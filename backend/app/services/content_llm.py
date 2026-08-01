"""콘텐츠 LLM 호출 단일 진입점 — 키·모델·폴백 정책을 한 곳에서 관리.

왜 별도 모듈인가: 콘텐츠 계열 호출부(정본 블록 생성·채널 파생·주제 제안·데이터스토리
서술)가 각자 `settings.OPENAI_API_KEY` 를 직접 보고 모델명을 하드코딩하고 있었다.
그 결과 `CONTENT_LLM_API_KEY`(OpenRouter 등)만 설정한 구성에서는 초안 생성만 되고
채널 파생·주제 제안은 **조용히 비활성**되는 불일치가 있었다. 게이트를 여기로 모은다.

정책:
- 1차 = `CONTENT_LLM_API_KEY` + `CONTENT_LLM_BASE_URL` + `CONTENT_LLM_MODEL`
  (`CONTENT_LLM_API_KEY` 가 비면 `OPENAI_API_KEY` 재사용 — config 주석의 계약)
- 폴백 = OpenAI 직결 `gpt-4o-mini` (`OPENAI_API_KEY` 가 있을 때만).
  1차가 프로바이더 장애·미지원 모델로 죽어도 콘텐츠 파이프라인이 멈추지 않게 한다.
- 둘 다 불가하면 예외 — 호출부가 `None` 을 반환해 **가짜 산출물 대신 정직하게 실패**한다.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from app.core.config import settings

logger = logging.getLogger(__name__)

FALLBACK_MODEL = "gpt-4o-mini"


def primary_key() -> str:
    """콘텐츠 1차 호출에 쓸 키. 전용 키 우선, 없으면 OpenAI 키 재사용."""
    return settings.CONTENT_LLM_API_KEY or settings.OPENAI_API_KEY


def available() -> bool:
    """콘텐츠 LLM 을 지금 쓸 수 있는가.

    `primary_key()` 가 이미 두 키의 합집합이라 이 하나로 충분하다 —
    호출부는 전부 이 게이트만 본다(예전처럼 각자 다른 키를 보지 않도록).
    """
    return bool(primary_key())


def cheap_model() -> str:
    """정본 외 가벼운 호출(채널 파생·주제 제안·주간 서술)에 쓸 저가 모델."""
    return settings.CONTENT_LLM_CHEAP_MODEL or FALLBACK_MODEL


class ContentLLMError(RuntimeError):
    """콘텐츠 LLM 응답이 쓸 수 없는 상태 — 호출부가 폴백/실패로 분기하게 한다."""


# ```json … ``` 펜스 제거 — Claude 계열은 response_format=json_object 를 줘도
# 마크다운 코드펜스로 감싸 보낸다(2026-08-01 OpenRouter 실측). 이걸 안 벗기면
# json.loads 가 'Expecting value: line 1 column 1' 로 죽는다.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.S)


def _unfence(text: str) -> str:
    m = _FENCE_RE.match(text)
    return m.group(1) if m else text


def _completion(client, model: str, system: str, user: str, max_tokens: int, temperature: float) -> dict:
    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        response_format={"type": "json_object"},
        max_tokens=max_tokens,
    )
    # Claude 계열(Sonnet 5 등)은 temperature 등 샘플링 파라미터를 거부(400)
    if "claude" not in model.lower():
        kwargs["temperature"] = temperature
    resp = client.chat.completions.create(**kwargs)
    choice = resp.choices[0]
    content = (getattr(choice.message, "content", None) or "").strip()
    if not content:
        # 추론형 모델(Claude 5 등)은 reasoning 에 토큰을 먼저 쓴다. max_tokens 가
        # 빠듯하면 추론만 하다 끝나 본문이 비어서 온다 — 원인을 메시지에 남긴다.
        reasoning = getattr(
            getattr(resp.usage, "completion_tokens_details", None), "reasoning_tokens", None
        )
        raise ContentLLMError(
            f"빈 응답 (model={model}, finish_reason={choice.finish_reason}, "
            f"max_tokens={max_tokens}, reasoning_tokens={reasoning}) — "
            "추론형 모델이면 max_tokens 를 늘려야 한다"
        )
    try:
        return json.loads(_unfence(content))
    except json.JSONDecodeError as e:
        if choice.finish_reason == "length":
            raise ContentLLMError(
                f"응답이 max_tokens({max_tokens})에서 잘려 JSON 이 깨졌다 (model={model})"
            ) from e
        raise


def chat_json(
    system: str,
    user: str,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.4,
    model: Optional[str] = None,
) -> dict:
    """JSON 응답 LLM 호출. 1차 실패 시 OpenAI 직결 폴백.

    반환: 파싱된 dict. 키 미설정이거나 1차·폴백 모두 실패하면 예외를 올린다
    (호출부는 이를 잡아 None 을 반환 — 지어낸 산출물 금지).
    """
    from openai import OpenAI

    key = primary_key()
    if not key:
        raise RuntimeError("content LLM key not configured")

    primary_model = model or settings.CONTENT_LLM_MODEL or FALLBACK_MODEL
    client = OpenAI(api_key=key, base_url=settings.CONTENT_LLM_BASE_URL or None)
    try:
        return _completion(client, primary_model, system, user, max_tokens, temperature)
    except Exception:
        # 폴백은 항상 OpenAI 직결 — 1차 프로바이더 장애와 독립적이어야 의미가 있다.
        if not settings.OPENAI_API_KEY or (
            primary_model == FALLBACK_MODEL and not settings.CONTENT_LLM_BASE_URL
        ):
            raise  # 폴백이 1차와 같은 경로 → 재시도해도 같은 결과. 정직하게 실패.
        logger.warning("content model %s failed — fallback to %s", primary_model, FALLBACK_MODEL)
        fallback_client = OpenAI(api_key=settings.OPENAI_API_KEY)
        return _completion(fallback_client, FALLBACK_MODEL, system, user, max_tokens, temperature)
