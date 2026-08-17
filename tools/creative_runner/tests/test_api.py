from __future__ import annotations

import hashlib
import json
from pathlib import Path

import httpx
import pytest
from bideasy_creative_runner.api import CreativeApiClient
from bideasy_creative_runner.errors import InvalidJobError


def test_claim_parses_contract_and_sends_bearer(runner_config):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(
            200,
            json={
                "attempt_id": 7,
                "creative_id": "cr_test",
                "attempt_no": 2,
                "job_type": "gpt_image_2",
                "prompt": "safe prompt",
                "hook": "나라장터 공고 옆에서",
                "body_copy": "확인 가능한 조건을 보여드립니다.",
                "cta_copy": "이 공고 확인하기",
                "params_json": {"aspect_ratio": "16:9"},
                "input_files_json": [],
                "input_hash": "a" * 64,
                "higgsfield_job_id": "11111111-1111-4111-8111-111111111111",
                "virality_job_id": "22222222-2222-4222-8222-222222222222",
                "lease_expires_at": "2026-08-14T00:00:00",
                "brief_format": "blog_hero_16_9",
            },
        )

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = CreativeApiClient(runner_config, client=http)
    attempt = client.claim()

    assert attempt is not None
    assert attempt.brief_format == "blog_hero_16_9"
    assert attempt.higgsfield_job_id == "11111111-1111-4111-8111-111111111111"
    assert attempt.virality_job_id == "22222222-2222-4222-8222-222222222222"
    assert attempt.params == {"aspect_ratio": "16:9"}
    assert attempt.hook == "나라장터 공고 옆에서"
    assert attempt.body_copy == "확인 가능한 조건을 보여드립니다."
    assert attempt.cta_copy == "이 공고 확인하기"
    assert seen[0].headers["authorization"] == "Bearer runner-test-token"
    assert json.loads(seen[0].content) == {
        "runner_id": "test-mac",
        "cli_version": "1.1.23",
    }


def test_claim_204_means_no_work(runner_config):
    http = httpx.Client(
        transport=httpx.MockTransport(lambda _request: httpx.Response(204))
    )
    client = CreativeApiClient(runner_config, client=http)
    assert client.claim() is None


def test_claim_rejects_non_uuid_provider_job_id(runner_config):
    payload = {
        "attempt_id": 7,
        "creative_id": "cr_test",
        "attempt_no": 2,
        "job_type": "gpt_image_2",
        "prompt": "safe prompt",
        "hook": "",
        "body_copy": "",
        "cta_copy": "",
        "params_json": {},
        "input_files_json": [],
        "higgsfield_job_id": "--workspace=attacker",
    }
    http = httpx.Client(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(200, json=payload)
        )
    )

    with pytest.raises(InvalidJobError, match="must be a UUID"):
        CreativeApiClient(runner_config, client=http).claim()


def test_heartbeat_sends_generation_and_predictor_job_ids(runner_config):
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"lease_expires_at": "2026-08-14T00:05:00"})

    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = CreativeApiClient(runner_config, client=http)
    client.heartbeat(
        7,
        status="PROCESSING",
        higgsfield_job_id="11111111-1111-4111-8111-111111111111",
        virality_job_id="22222222-2222-4222-8222-222222222222",
    )

    assert json.loads(seen[0].content) == {
        "runner_id": "test-mac",
        "status": "PROCESSING",
        "higgsfield_job_id": "11111111-1111-4111-8111-111111111111",
        "virality_job_id": "22222222-2222-4222-8222-222222222222",
    }


def test_upload_is_real_multipart_with_hash_and_rewinds_on_retry(
    tmp_path: Path, runner_config
):
    path = tmp_path / "final.png"
    payload = b"\x89PNG\r\n\x1a\nactual-bytes"
    path.write_bytes(payload)
    bodies: list[bytes] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content)
        if len(bodies) == 1:
            return httpx.Response(503)
        return httpx.Response(
            201,
            json={
                "output": {},
                "attempt_status": "REVIEW_REQUIRED",
                "creative_status": "REVIEW_REQUIRED",
            },
        )

    sleeps: list[float] = []
    http = httpx.Client(transport=httpx.MockTransport(handler))
    client = CreativeApiClient(runner_config, client=http, sleeper=sleeps.append)
    client.upload_output(
        8, path, kind="final_png", is_primary=True, metadata={"width": 1376}
    )

    assert sleeps == [0.1]
    assert len(bodies) == 2
    assert all(payload in body for body in bodies)
    assert all(
        b"final_png" in body and b"true" in body and b"test-mac" in body
        for body in bodies
    )
    assert all(hashlib.sha256(payload).hexdigest().encode() in body for body in bodies)
