"""LLM 호출 단일 관문 — 앱의 모든 LLM 요청이 여기를 지난다.

**OpenAI 직결 폐지 (2026-08-02).** 공고 요약·독소조항, 첨부 심층분석, 고객 챗봇,
블로그 정본·채널 파생까지 전부 OpenRouter 한 곳을 경유한다. 계정·키·청구가 하나가 되고,
모델 교체가 설정 한 줄로 끝난다.

왜 관문이 필요한가 — 흩어져 있을 때 실제로 났던 사고들:
- 호출부마다 다른 키를 봐서, OpenRouter 만 설정하면 일부 기능이 **조용히** 죽었다.
- 추론형 모델(Claude 5·GPT-5 계열)은 reasoning 에 토큰을 먼저 쓴다. max_tokens 가
  빠듯하면 본문이 빈 채로 온다 — `json.loads(None)` 이 그대로 터졌다.
- Claude 계열은 JSON 을 ```json 펜스로 감싸 보낸다(response_format 을 줘도).
- Claude 계열은 temperature 를 400 으로 거부한다.
이 넷을 한 곳에서 처리한다. 호출부는 모델명과 프롬프트만 신경 쓰면 된다.

설정: `LLM_API_KEY`/`LLM_BASE_URL` (비면 `CONTENT_LLM_*` 재사용 — 구 배포 호환).
모델은 용도별 설정(`settings.LLM_MODEL_*`, `CONTENT_LLM_MODEL`)으로 지정한다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)


class LLMError(RuntimeError):
    """LLM 응답이 쓸 수 없는 상태 — 호출부가 폴백/실패로 분기하게 한다."""


# 하위 호환 별칭 (구 content_llm.ContentLLMError 를 잡던 코드)
ContentLLMError = LLMError


# ```json … ``` 펜스 제거 — Claude 계열은 response_format=json_object 를 줘도
# 마크다운 코드펜스로 감싸 보낸다(2026-08-01 OpenRouter 실측). 이걸 안 벗기면
# json.loads 가 'Expecting value: line 1 column 1' 로 죽는다.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def _unfence(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


# ─── 게이트웨이 설정 ──────────────────────────────────────────

def api_key() -> str:
    """게이트웨이 키. 구 설정(`CONTENT_LLM_API_KEY`)도 그대로 받아준다."""
    return settings.LLM_API_KEY or settings.CONTENT_LLM_API_KEY


def base_url() -> Optional[str]:
    return (settings.LLM_BASE_URL or settings.CONTENT_LLM_BASE_URL) or None


def available() -> bool:
    """LLM 을 지금 쓸 수 있는가. **모든 호출부가 이 하나만 본다.**"""
    return bool(api_key())


def cheap_model() -> str:
    """정본 외 가벼운 호출(채널 파생·주제 제안·주간 서술)에 쓸 저가 모델."""
    return settings.CONTENT_LLM_CHEAP_MODEL


def _client():
    from openai import OpenAI
    key = api_key()
    if not key:
        raise LLMError("LLM key not configured")
    return OpenAI(api_key=key, base_url=base_url())


def _supports_temperature(model: str) -> bool:
    # Claude 계열은 샘플링 파라미터를 400 으로 거부한다.
    return "claude" not in model.lower()


def _request(client, model: str, messages: list, max_tokens: int,
             temperature: float, as_json: bool):
    kwargs = dict(model=model, messages=messages, max_tokens=max_tokens)
    if as_json:
        kwargs["response_format"] = {"type": "json_object"}
    if _supports_temperature(model):
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    content = (getattr(choice.message, "content", None) or "").strip()
    if not content:
        # 추론형 모델은 reasoning 에 토큰을 먼저 쓴다. max_tokens 가 빠듯하면
        # 추론만 하다 끝나 본문이 비어서 온다 — 원인을 메시지에 남긴다.
        reasoning = getattr(
            getattr(resp.usage, "completion_tokens_details", None), "reasoning_tokens", None
        )
        raise LLMError(
            f"빈 응답 (model={model}, finish_reason={choice.finish_reason}, "
            f"max_tokens={max_tokens}, reasoning_tokens={reasoning}) — "
            "추론형 모델이면 max_tokens 를 늘려야 한다"
        )
    return content, choice.finish_reason


def _completion(client, model: str, system: str, user: str,
                max_tokens: int, temperature: float) -> dict:
    """단일 모델 JSON 호출 (테스트가 이 경계를 잡는다)."""
    messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    content, finish = _request(client, model, messages, max_tokens, temperature, True)
    try:
        return json.loads(_unfence(content))
    except json.JSONDecodeError as e:
        if finish == "length":
            raise LLMError(
                f"응답이 max_tokens({max_tokens})에서 잘려 JSON 이 깨졌다 (model={model})"
            ) from e
        raise


# ─── 공개 API ─────────────────────────────────────────────────

def chat_json(
    system: str,
    user: str,
    *,
    model: Optional[str] = None,
    fallback: Optional[str] = None,
    max_tokens: int = 2000,
    temperature: float = 0.4,
) -> dict:
    """JSON 응답 호출. `fallback` 지정 시 1차 실패하면 그 모델로 한 번 더 시도.

    반환: 파싱된 dict. 키 미설정이거나 전부 실패하면 예외 — 호출부는 이를 잡아
    None/빈 결과를 반환한다(지어낸 산출물 금지).
    """
    client = _client()
    primary = model or settings.CONTENT_LLM_MODEL
    try:
        return _completion(client, primary, system, user, max_tokens, temperature)
    except Exception:
        if not fallback or fallback == primary:
            raise
        logger.warning("LLM %s failed — fallback to %s", primary, fallback)
        return _completion(client, fallback, system, user, max_tokens, temperature)


def chat_text(
    messages: list,
    *,
    model: Optional[str] = None,
    max_tokens: int = 800,
    temperature: float = 0.3,
) -> str:
    """자유 텍스트 응답 호출(챗봇 등). messages 는 OpenAI 형식 그대로."""
    client = _client()
    content, _ = _request(client, model or cheap_model(), messages,
                          max_tokens, temperature, False)
    return content
