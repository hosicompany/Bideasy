"""콘텐츠 LLM 응답 처리 회귀 테스트.

전부 **2026-08-01 실주행에서 실제로 터진 것들**이다. 정본 모델(Claude Sonnet 5 via
OpenRouter)로 K2~K5 를 돌리려다 3연속 실패했고, 원인이 아래 3가지였다.
목킹 없이 라이브로 돌려보지 않았으면 못 찾았을 버그들이라 반드시 고정해 둔다.
"""
import json
from types import SimpleNamespace

import pytest

from app.services import content_llm as cl


def _resp(content, finish_reason="stop", reasoning=None):
    """OpenAI SDK 응답 최소 목 — message.content / finish_reason / usage."""
    return SimpleNamespace(
        choices=[SimpleNamespace(
            message=SimpleNamespace(content=content),
            finish_reason=finish_reason,
        )],
        usage=SimpleNamespace(
            completion_tokens_details=SimpleNamespace(reasoning_tokens=reasoning)
        ),
    )


class _Client:
    def __init__(self, resp):
        self._resp = resp
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))
        self.calls = []

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._resp


def _complete(resp, model="anthropic/claude-sonnet-5"):
    return cl._completion(_Client(resp), model, "sys", "user", 4000, 0.5)


class TestFenceStripping:
    def test_json_fence_is_stripped(self):
        """★ Claude 는 response_format=json_object 를 줘도 ```json 펜스로 감싸 보낸다."""
        assert _complete(_resp('```json\n{"hook": "훅"}\n```')) == {"hook": "훅"}

    def test_bare_fence_is_stripped(self):
        assert _complete(_resp('```\n{"a": 1}\n```')) == {"a": 1}

    def test_plain_json_still_works(self):
        assert _complete(_resp('{"a": 1}')) == {"a": 1}

    def test_fence_like_string_inside_json_is_safe(self):
        payload = json.dumps({"body": "코드는 ```python 처럼 씁니다"}, ensure_ascii=False)
        assert _complete(_resp(payload))["body"].startswith("코드는")


class TestEmptyResponse:
    def test_none_content_raises_clear_error(self):
        """★ 추론형 모델이 max_tokens 를 reasoning 에 다 써서 본문이 비어 온 사고."""
        with pytest.raises(cl.ContentLLMError) as e:
            _complete(_resp(None, finish_reason="length", reasoning=2143))
        msg = str(e.value)
        assert "빈 응답" in msg
        assert "reasoning_tokens=2143" in msg   # 원인이 메시지에 남아야 진단이 된다
        assert "max_tokens" in msg

    def test_blank_content_raises(self):
        with pytest.raises(cl.ContentLLMError):
            _complete(_resp("   "))


class TestTruncation:
    def test_truncated_json_reports_max_tokens(self):
        with pytest.raises(cl.ContentLLMError) as e:
            _complete(_resp('{"hook": "잘린', finish_reason="length"))
        assert "잘려" in str(e.value)

    def test_malformed_json_without_truncation_propagates(self):
        """잘린 게 아니면 원래 JSONDecodeError 를 숨기지 않는다."""
        with pytest.raises(json.JSONDecodeError):
            _complete(_resp("이건 JSON 이 아니에요", finish_reason="stop"))


class TestSamplingParams:
    def test_temperature_omitted_for_claude(self):
        """Claude 계열은 temperature 를 400 으로 거부한다."""
        c = _Client(_resp('{"a":1}'))
        cl._completion(c, "anthropic/claude-sonnet-5", "s", "u", 100, 0.5)
        assert "temperature" not in c.calls[0]

    def test_temperature_sent_for_openai(self):
        c = _Client(_resp('{"a":1}'))
        cl._completion(c, "openai/gpt-4o-mini", "s", "u", 100, 0.5)
        assert c.calls[0]["temperature"] == 0.5
