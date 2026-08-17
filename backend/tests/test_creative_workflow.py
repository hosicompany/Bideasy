"""Creative brief/admin/runner workflow regression tests."""
from __future__ import annotations

import hashlib
import io
import json
import stat
from copy import deepcopy
from datetime import timedelta
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.db import models
from app.services import creative_workflow as workflow


@pytest.fixture
def creative_settings(tmp_path, db_session):
    previous = {
        "current": settings.CREATIVE_RUNNER_TOKEN_CURRENT,
        "old": settings.CREATIVE_RUNNER_TOKEN_PREVIOUS,
        "root": settings.CREATIVE_ASSET_ROOT,
        "base": settings.CREATIVE_ASSET_BASE_URL,
        "lease": settings.CREATIVE_RUNNER_LEASE_SECONDS,
        "cli": settings.HIGGSFIELD_CLI_VERSION,
    }
    settings.CREATIVE_RUNNER_TOKEN_CURRENT = "runner-current-test-token"
    settings.CREATIVE_RUNNER_TOKEN_PREVIOUS = "runner-previous-test-token"
    settings.CREATIVE_ASSET_ROOT = str(tmp_path / "creative-assets")
    settings.CREATIVE_ASSET_BASE_URL = "/assets/generated"
    settings.CREATIVE_RUNNER_LEASE_SECONDS = 300
    settings.HIGGSFIELD_CLI_VERSION = "1.1.23"
    db_session.query(models.CreativeOutput).delete()
    db_session.query(models.CreativeAttempt).delete()
    db_session.query(models.CreativeBrief).delete()
    db_session.commit()
    yield tmp_path
    db_session.query(models.CreativeOutput).delete()
    db_session.query(models.CreativeAttempt).delete()
    db_session.query(models.CreativeBrief).delete()
    db_session.commit()
    settings.CREATIVE_RUNNER_TOKEN_CURRENT = previous["current"]
    settings.CREATIVE_RUNNER_TOKEN_PREVIOUS = previous["old"]
    settings.CREATIVE_ASSET_ROOT = previous["root"]
    settings.CREATIVE_ASSET_BASE_URL = previous["base"]
    settings.CREATIVE_RUNNER_LEASE_SECONDS = previous["lease"]
    settings.HIGGSFIELD_CLI_VERSION = previous["cli"]


def _brief_payload(**overrides):
    payload = {
        "campaign_key": "pm_202608_message_a",
        "concept_key": "mechanism",
        "variant": "A",
        "channel": "naver_blog",
        "format": "static_1_1",
        "hook": "나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        "body_copy": "보고 있는 공고 화면에서 확인하세요.",
        "cta_copy": "이 공고 확인하기",
        "landing_path": "/calculator",
        "utm_source": "naver_blog",
        "utm_medium": "organic",
        "utm_campaign": "pm_202608_message_a",
        "generation_spec_json": {
            "job_type": "marketing_studio_image",
            "prompt": "clean blue editorial background, no text, no logo",
            "params": {
                "aspect_ratio": "1:1",
                "resolution": "2K",
                "composite_source_ui": True,
            },
            "input_files": [
                {
                    "url": "/guide-assets/01-main-g2b-with-sidepanel.png",
                    "sha256": "bdff901a2882995afd19bf0476cb99fb1407abb1011365e9616ec787d006d765",
                    "mime_type": "image/png",
                    "role": "source_ui",
                }
            ],
        },
    }
    payload.update(overrides)
    return payload


def _video_generation_spec():
    return {
        "job_type": "marketing_studio_video",
        "prompt": "calm professional background motion, no text, no UI, no people",
        "params": {
            "aspect_ratio": "9:16",
            "resolution": "1080p",
            "duration": 15,
            "mode": "ugc",
            "specific_mode": "from_storyboard",
            "generate_audio": False,
            "composite_source_ui": True,
        },
        "input_files": [
            {
                "url": "/assets/source-ui.png",
                "sha256": "1" * 64,
                "mime_type": "image/png",
                "role": "source_ui",
            },
            {
                "url": "/assets/storyboard.png",
                "sha256": "2" * 64,
                "mime_type": "image/png",
                "role": "storyboard",
            },
            {
                "url": "/assets/founder-voice.wav",
                "sha256": "3" * 64,
                "mime_type": "audio/wav",
                "role": "voiceover",
            },
        ],
    }


def _create_and_queue(admin_client):
    created = admin_client.post("/api/v1/admin/creatives", json=_brief_payload())
    assert created.status_code == 201, created.text
    creative_id = created.json()["id"]
    approved = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/approve", json={})
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "BRIEF_APPROVED"
    queued = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/queue")
    assert queued.status_code == 200, queued.text
    return creative_id, queued.json()["id"]


def _runner_headers(token="runner-current-test-token"):
    return {"Authorization": f"Bearer {token}"}


def _png_bytes(size=(1080, 1080)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color=(49, 130, 246)).save(stream, format="PNG")
    return stream.getvalue()


def _virality_report(**overrides) -> bytes:
    payload = {
        "higgsfield_job_id": "22222222-2222-4222-8222-222222222222",
        "virality_job_id": "22222222-2222-4222-8222-222222222222",
        "hook_peak_seconds": 1.8,
        "sustain_score": 0.76,
        "attention_overlaps_product": True,
        "report_url": "https://app.higgsfield.ai/reports/22222222-2222-4222-8222-222222222222",
        "human_review_required": True,
        "analysis_warning": None,
        "credit_usage": {
            "before": 1200,
            "after": 1196,
            "delta": 4,
            "warnings": [],
        },
    }
    payload.update(overrides)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()


def test_admin_creatives_require_admin(client):
    response = client.get("/api/v1/admin/creatives")
    assert response.status_code == 401


def test_create_update_approve_and_queue(admin_client, creative_settings):
    created = admin_client.post("/api/v1/admin/creatives", json=_brief_payload())
    assert created.status_code == 201, created.text
    body = created.json()
    assert len(body["id"]) == 36
    assert body["status"] == "DRAFT"
    assert body["attempts"] == []

    updated = admin_client.put(
        f"/api/v1/admin/creatives/{body['id']}",
        json={"hook": "이 공고, 우리 회사가 진짜 넣어도 될까요?", "variant": "B"},
    )
    assert updated.status_code == 200
    assert updated.json()["version"] == 2
    assert updated.json()["variant"] == "B"

    approved = admin_client.post(f"/api/v1/admin/creatives/{body['id']}/approve", json={})
    assert approved.status_code == 200
    assert approved.json()["status"] == "BRIEF_APPROVED"

    queued = admin_client.post(f"/api/v1/admin/creatives/{body['id']}/queue")
    assert queued.status_code == 200
    assert queued.json()["attempt_no"] == 1
    assert queued.json()["status"] == "QUEUED"
    # Double-click is idempotent; it must not spend credits on another attempt.
    duplicate = admin_client.post(f"/api/v1/admin/creatives/{body['id']}/queue")
    assert duplicate.status_code == 200
    assert duplicate.json()["id"] == queued.json()["id"]


def test_invalid_external_landing_is_rejected(admin_client):
    response = admin_client.post(
        "/api/v1/admin/creatives",
        json=_brief_payload(landing_path="https://evil.example/phish"),
    )
    assert response.status_code == 422


def test_marketing_video_requires_approved_real_inputs(admin_client, creative_settings):
    valid_spec = _video_generation_spec()
    invalid_specs = []
    for key, value in (
        ("specific_mode", "avatar"),
        ("generate_audio", True),
        ("resolution", "720p"),
        ("composite_source_ui", False),
    ):
        spec = deepcopy(valid_spec)
        spec["params"][key] = value
        invalid_specs.append(spec)
    for missing_role in ("voiceover", "source_ui", "storyboard"):
        spec = deepcopy(valid_spec)
        spec["input_files"] = [
            item for item in spec["input_files"] if item["role"] != missing_role
        ]
        invalid_specs.append(spec)
    duplicate_ui = deepcopy(valid_spec)
    duplicate_ui["input_files"].append(
        {
            "url": "/assets/source-ui-second.png",
            "sha256": "4" * 64,
            "mime_type": "image/png",
            "role": "source_ui",
        }
    )
    invalid_specs.append(duplicate_ui)
    duplicate_storyboard = deepcopy(valid_spec)
    duplicate_storyboard["input_files"].append(
        {
            "url": "/assets/storyboard-second.png",
            "sha256": "5" * 64,
            "mime_type": "image/png",
            "role": "storyboard",
        }
    )
    invalid_specs.append(duplicate_storyboard)

    for index, spec in enumerate(invalid_specs):
        created = admin_client.post(
            "/api/v1/admin/creatives",
            json=_brief_payload(
                campaign_key=f"pm_video_invalid_{index}",
                channel="youtube",
                format="video_9_16",
                generation_spec_json=spec,
            ),
        )
        assert created.status_code == 201, created.text
        approved = admin_client.post(
            f"/api/v1/admin/creatives/{created.json()['id']}/approve",
            json={},
        )
        assert approved.status_code == 422, approved.text

    valid = admin_client.post(
        "/api/v1/admin/creatives",
        json=_brief_payload(
            campaign_key="pm_video_valid",
            channel="youtube",
            format="video_9_16",
            generation_spec_json=valid_spec,
        ),
    )
    approved = admin_client.post(
        f"/api/v1/admin/creatives/{valid.json()['id']}/approve",
        json={},
    )
    assert approved.status_code == 200, approved.text
    queued = admin_client.post(f"/api/v1/admin/creatives/{valid.json()['id']}/queue")
    assert queued.status_code == 200, queued.text


def test_generation_job_format_and_input_contracts(admin_client, creative_settings):
    gpt_spec = {
        "job_type": "gpt_image_2",
        "prompt": "text-free editorial background",
        "params": {"aspect_ratio": "16:9", "resolution": "2K"},
        "input_files": [],
    }
    video_input = {
        "url": "/assets/generated/source/final.mp4",
        "sha256": "e" * 64,
        "mime_type": "video/mp4",
        "role": "reference",
    }
    reframe_spec = {
        "job_type": "reframe",
        "prompt": "",
        "params": {"aspect_ratio": "1:1", "resolution": "1080p"},
        "input_files": [video_input],
    }
    image_spec = deepcopy(_brief_payload()["generation_spec_json"])
    invalid_cases = [
        ("gpt_format", "static_1_1", gpt_spec),
        (
            "gpt_input",
            "blog_hero_16_9",
            {**gpt_spec, "input_files": [image_spec["input_files"][0]]},
        ),
        ("image_format", "blog_hero_16_9", image_spec),
        (
            "image_source",
            "static_1_1",
            {**image_spec, "input_files": []},
        ),
        (
            "image_extra_input",
            "static_1_1",
            {
                **image_spec,
                "input_files": image_spec["input_files"]
                + [{**image_spec["input_files"][0], "sha256": "d" * 64, "role": "reference"}],
            },
        ),
        ("video_format", "video_1_1", _video_generation_spec()),
        ("reframe_format", "static_1_1", reframe_spec),
        (
            "reframe_duplicate_video",
            "video_1_1",
            {**reframe_spec, "input_files": [video_input, {**video_input, "sha256": "f" * 64}]},
        ),
        (
            "reframe_extra_nonvideo",
            "video_1_1",
            {**reframe_spec, "input_files": [video_input, image_spec["input_files"][0]]},
        ),
        (
            "reframe_composite",
            "video_1_1",
            {**reframe_spec, "params": {**reframe_spec["params"], "composite_source_ui": True}},
        ),
        (
            "brain_format",
            "static_1_1",
            {**reframe_spec, "job_type": "brain_activity"},
        ),
        (
            "brain_video",
            "video_16_9",
            {**reframe_spec, "job_type": "brain_activity", "input_files": []},
        ),
        (
            "brain_extra_nonvideo",
            "video_16_9",
            {
                **reframe_spec,
                "job_type": "brain_activity",
                "input_files": [video_input, image_spec["input_files"][0]],
            },
        ),
    ]
    for key, brief_format, spec in invalid_cases:
        created = admin_client.post(
            "/api/v1/admin/creatives",
            json=_brief_payload(
                campaign_key=f"generation_contract_{key}",
                format=brief_format,
                generation_spec_json=spec,
            ),
        )
        assert created.status_code == 201, created.text
        approved = admin_client.post(
            f"/api/v1/admin/creatives/{created.json()['id']}/approve",
            json={},
        )
        assert approved.status_code == 422, (key, approved.text)

    valid_reframe = admin_client.post(
        "/api/v1/admin/creatives",
        json=_brief_payload(
            campaign_key="generation_contract_reframe_valid",
            format="video_1_1",
            generation_spec_json=reframe_spec,
        ),
    )
    approved = admin_client.post(
        f"/api/v1/admin/creatives/{valid_reframe.json()['id']}/approve",
        json={},
    )
    assert approved.status_code == 200, approved.text


def test_from_blog_is_source_hashed_and_idempotent(
    admin_client,
    db_session,
    creative_settings,
):
    post = admin_client.post(
        "/api/v1/admin/blog",
        json={
            "title": "A값 계산 가이드",
            "slug": "creative-source-blog",
            "summary": "공고별 A값을 확인해요.",
            "body_md": "# 본문",
        },
    )
    assert post.status_code == 201
    first = admin_client.post(f"/api/v1/admin/creatives/from-blog/{post.json()['id']}")
    second = admin_client.post(f"/api/v1/admin/creatives/from-blog/{post.json()['id']}")
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"]
    assert len(first.json()["source_hash"]) == 64
    assert first.json()["generation_spec_json"]["job_type"] == "gpt_image_2"

    creative_id = first.json()["id"]
    # 게시 상태에서도 동일 source hash의 정본을 다시 만들어 내지 않는다.
    row = db_session.get(models.CreativeBrief, creative_id)
    row.status = "PUBLISHED"
    row.published_at = workflow.utcnow()
    db_session.commit()
    after_publish = admin_client.post(
        f"/api/v1/admin/creatives/from-blog/{post.json()['id']}"
    )
    assert after_publish.status_code == 201
    assert after_publish.json()["id"] == creative_id
    assert first.json()["source_hash"] == after_publish.json()["source_hash"]


def test_blog_source_change_stales_all_linked_attempts(admin_client, creative_settings):
    post = admin_client.post(
        "/api/v1/admin/blog",
        json={
            "title": "기존 A값 가이드",
            "slug": "creative-stale-source",
            "summary": "기존 설명",
            "body_md": "# 기존 본문",
        },
    )
    post_id = post.json()["id"]
    brief = admin_client.post(f"/api/v1/admin/creatives/from-blog/{post_id}")
    creative_id = brief.json()["id"]
    admin_client.post(f"/api/v1/admin/creatives/{creative_id}/approve", json={})
    queued = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/queue")
    assert queued.status_code == 200

    updated_post = admin_client.put(
        f"/api/v1/admin/blog/{post_id}",
        json={"title": "수정된 A값 가이드", "body_md": "# 수정된 본문"},
    )
    assert updated_post.status_code == 200, updated_post.text
    stale = admin_client.get(f"/api/v1/admin/creatives/{creative_id}")
    assert stale.json()["status"] == "STALE"
    assert stale.json()["attempts"][0]["status"] == "STALE"

    replacement = admin_client.post(f"/api/v1/admin/creatives/from-blog/{post_id}")
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["id"] != creative_id
    assert replacement.json()["source_hash"] != brief.json()["source_hash"]


def test_runner_rotating_auth_claim_and_heartbeat(admin_client, client, creative_settings):
    creative_id, attempt_id = _create_and_queue(admin_client)

    assert client.post(
        "/api/v1/creative-runner/claim",
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    ).status_code == 401
    assert client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers("wrong-token"),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    ).status_code == 401

    # Previous token remains accepted during rotation.
    claimed = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers("runner-previous-test-token"),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    assert claimed.status_code == 200, claimed.text
    body = claimed.json()
    assert body["attempt_id"] == attempt_id
    assert body["creative_id"] == creative_id
    assert body["brief_format"] == "static_1_1"
    assert body["hook"] == "나라장터 공고 옆에서, 자격·A값·하한선을 한 번에."
    assert body["body_copy"] == "보고 있는 공고 화면에서 확인하세요."
    assert body["cta_copy"] == "이 공고 확인하기"
    assert body["higgsfield_job_id"] is None
    assert body["virality_job_id"] is None

    heartbeat = client.post(
        f"/api/v1/creative-runner/{attempt_id}/heartbeat",
        headers=_runner_headers(),
        json={
            "runner_id": "mac-01",
            "status": "GENERATING",
            "higgsfield_job_id": "hf-job-123",
            "virality_job_id": "virality-job-456",
        },
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["status"] == "GENERATING"

    repeated_job_ids = client.post(
        f"/api/v1/creative-runner/{attempt_id}/heartbeat",
        headers=_runner_headers(),
        json={
            "runner_id": "mac-01",
            "status": "GENERATING",
            "higgsfield_job_id": "hf-job-123",
            "virality_job_id": "virality-job-456",
        },
    )
    assert repeated_job_ids.status_code == 200
    conflicting_virality_job = client.post(
        f"/api/v1/creative-runner/{attempt_id}/heartbeat",
        headers=_runner_headers(),
        json={
            "runner_id": "mac-01",
            "status": "GENERATING",
            "virality_job_id": "virality-job-other",
        },
    )
    assert conflicting_virality_job.status_code == 409

    reclaimed_snapshot = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    assert reclaimed_snapshot.status_code == 200
    assert reclaimed_snapshot.json()["higgsfield_job_id"] == "hf-job-123"
    assert reclaimed_snapshot.json()["virality_job_id"] == "virality-job-456"

    empty = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-02", "cli_version": "1.1.23"},
    )
    assert empty.status_code == 204


def test_runner_rejects_wrong_cli_version(admin_client, client, creative_settings):
    _create_and_queue(admin_client)
    response = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.22"},
    )
    assert response.status_code == 409
    assert "1.1.23" in response.json()["detail"]


def test_repeated_claim_by_same_runner_returns_live_attempt(
    admin_client,
    client,
    creative_settings,
):
    first_creative_id, first_attempt_id = _create_and_queue(admin_client)
    second_created = admin_client.post(
        "/api/v1/admin/creatives",
        json=_brief_payload(campaign_key="pm_202608_message_b", variant="B"),
    )
    second_creative_id = second_created.json()["id"]
    admin_client.post(f"/api/v1/admin/creatives/{second_creative_id}/approve", json={})
    second_queued = admin_client.post(
        f"/api/v1/admin/creatives/{second_creative_id}/queue"
    )
    second_attempt_id = second_queued.json()["id"]

    first_claim = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    repeated_claim = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    other_runner_claim = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-02", "cli_version": "1.1.23"},
    )

    assert first_claim.status_code == 200
    assert first_claim.json()["creative_id"] == first_creative_id
    assert first_claim.json()["attempt_id"] == first_attempt_id
    assert repeated_claim.status_code == 200
    assert repeated_claim.json()["attempt_id"] == first_attempt_id
    assert other_runner_claim.status_code == 200
    assert other_runner_claim.json()["attempt_id"] == second_attempt_id


def test_expired_lease_reclaims_same_attempt(admin_client, client, db_session, creative_settings):
    _, attempt_id = _create_and_queue(admin_client)
    first = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-old", "cli_version": "1.1.23"},
    )
    assert first.status_code == 200
    attempt = db_session.get(models.CreativeAttempt, attempt_id)
    attempt.higgsfield_job_id = "existing-job"
    attempt.lease_expires_at = workflow.utcnow() - timedelta(seconds=1)
    db_session.commit()

    reclaimed = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-new", "cli_version": "1.1.23"},
    )
    assert reclaimed.status_code == 200, reclaimed.text
    assert reclaimed.json()["attempt_id"] == attempt_id
    assert reclaimed.json()["higgsfield_job_id"] == "existing-job"


def test_verified_output_approval_and_publish(admin_client, client, creative_settings):
    creative_id, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    content = _png_bytes()
    digest = hashlib.sha256(content).hexdigest()
    uploaded = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("../../outside.png", content, "image/png")},
        data={
            "runner_id": "mac-01",
            "kind": "final_png",
            "is_primary": "true",
            "metadata_json": json.dumps(
                {
                    "review": {
                        "higgsfield_job_id": "11111111-1111-4111-8111-111111111111",
                        "cli_version": "1.1.23",
                        "credit_usage": {
                            "before": 1200,
                            "after": 1198,
                            "delta": 2,
                            "warnings": [],
                        },
                    }
                }
            ),
            "sha256": digest,
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    body = uploaded.json()
    assert body["attempt_status"] == "REVIEW_REQUIRED"
    output = body["output"]
    assert output["width"] == 1080 and output["height"] == 1080
    assert output["sha256"] == digest
    assert ".." not in output["storage_path"]
    root = Path(settings.CREATIVE_ASSET_ROOT).resolve()
    saved = (root / output["storage_path"]).resolve()
    assert root in saved.parents and saved.exists()
    assert stat.S_IMODE(saved.stat().st_mode) == 0o644

    blocked = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve",
        json={"note": "실제 UI·카피 검수 완료"},
    )
    assert blocked.status_code == 409
    assert "virality_report_missing" in blocked.json()["detail"]

    approved = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve",
        json={
            "note": "실제 UI·카피 검수 완료",
            "review_json": {"visual_check": "passed"},
            "override_reason": "Predictor 응답 누락을 확인하고 실제 화면을 수동 검수함",
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"
    primary = approved.json()["attempts"][-1]["outputs"][0]
    assert "virality_report_missing" in primary["review_json"]["virality_warnings"]
    assert "virality_report_missing" in primary["review_json"]["virality_failures"]
    assert primary["review_json"]["higgsfield_job_id"].startswith("11111111")
    assert primary["review_json"]["cli_version"] == "1.1.23"
    assert primary["review_json"]["credit_usage"]["delta"] == 2
    assert primary["review_json"]["human_review"]["details"] == {
        "visual_check": "passed"
    }
    assert primary["review_json"]["human_review_history"][0]["decision"] == "APPROVED"

    published = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/mark-published",
        json={},
    )
    assert published.status_code == 200
    assert published.json()["status"] == "PUBLISHED"
    assert published.json()["published_at"]


def test_output_hash_mismatch_leaves_no_asset(admin_client, client, db_session, creative_settings):
    _, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    response = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("creative.png", _png_bytes(), "image/png")},
        data={
            "runner_id": "mac-01",
            "kind": "final_png",
            "is_primary": "true",
            "sha256": "0" * 64,
        },
    )
    assert response.status_code == 422
    assert db_session.query(models.CreativeOutput).filter_by(attempt_id=attempt_id).count() == 0
    assert not list(Path(settings.CREATIVE_ASSET_ROOT).rglob("*.png"))


def test_output_requires_lease_owner_and_live_lease(
    admin_client,
    client,
    db_session,
    creative_settings,
):
    _, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-owner", "cli_version": "1.1.23"},
    )
    upload = {
        "files": {"file": ("creative.png", _png_bytes(), "image/png")},
        "headers": _runner_headers(),
    }

    wrong_runner = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        data={"runner_id": "mac-other", "kind": "final_png", "is_primary": "true"},
        **upload,
    )
    assert wrong_runner.status_code == 409
    assert "다른 runner" in wrong_runner.json()["detail"]

    attempt = db_session.get(models.CreativeAttempt, attempt_id)
    attempt.lease_expires_at = workflow.utcnow() - timedelta(seconds=1)
    db_session.commit()
    expired = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        data={"runner_id": "mac-owner", "kind": "final_png", "is_primary": "true"},
        **upload,
    )
    assert expired.status_code == 409
    assert "lease" in expired.json()["detail"]
    assert db_session.query(models.CreativeOutput).filter_by(attempt_id=attempt_id).count() == 0


def test_virality_failure_requires_override(admin_client, client, creative_settings):
    creative_id, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    report = _virality_report(hook_peak_seconds=4.2, sustain_score=0.62)
    report_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("report.json", report, "application/json")},
        data={"runner_id": "mac-01", "kind": "virality_report", "is_primary": "false"},
    )
    assert report_upload.status_code == 200, report_upload.text
    stored_report = report_upload.json()["output"]["virality_json"]
    assert set(stored_report) == {
        "higgsfield_job_id",
        "virality_job_id",
        "hook_peak_seconds",
        "sustain_score",
        "attention_overlaps_product",
        "report_url",
        "human_review_required",
        "analysis_warning",
        "credit_usage",
    }
    assert stored_report["report_url"].startswith("https://app.higgsfield.ai/reports/")
    final = _png_bytes()
    final_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("final.png", final, "image/png")},
        data={"runner_id": "mac-01", "kind": "final_png", "is_primary": "true"},
    )
    assert final_upload.status_code == 200, final_upload.text

    blocked = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/approve", json={})
    assert blocked.status_code == 409
    overridden = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve",
        json={"override_reason": "타깃 전문가에게는 제품 장면이 더 중요하다고 판단"},
    )
    assert overridden.status_code == 200, overridden.text
    assert overridden.json()["status"] == "APPROVED"


def test_missing_metrics_and_predictor_error_require_override(
    admin_client,
    client,
    creative_settings,
):
    creative_id, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    report_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={
            "file": (
                "report.json",
                _virality_report(
                    hook_peak_seconds=None,
                    analysis_warning="virality_metrics_incomplete",
                ),
                "application/json",
            )
        },
        data={"runner_id": "mac-01", "kind": "virality_report", "is_primary": "false"},
    )
    assert report_upload.status_code == 200, report_upload.text
    final_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("final.png", _png_bytes(), "image/png")},
        data={"runner_id": "mac-01", "kind": "final_png", "is_primary": "true"},
    )
    assert final_upload.status_code == 200, final_upload.text

    blocked = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/approve", json={})
    assert blocked.status_code == 409
    assert "virality_predictor_error" in blocked.json()["detail"]
    assert "hook_peak_seconds_missing" in blocked.json()["detail"]

    overridden = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve",
        json={"override_reason": "Predictor 오류를 기록하고 실제 장면을 수동 검수함"},
    )
    assert overridden.status_code == 200, overridden.text
    primary = next(
        output
        for output in overridden.json()["attempts"][-1]["outputs"]
        if output["is_primary"]
    )
    assert "virality_predictor_error" in primary["review_json"]["virality_failures"]
    assert "hook_peak_seconds_missing" in primary["review_json"]["virality_failures"]


@pytest.mark.parametrize(
    "report_overrides",
    [
        {"provider_raw": {"email": "operator@example.com", "token": "secret"}},
        {"operator@example.com": "secret"},
        {"report_url": "https://app.higgsfield.ai/reports/abc?signature=secret"},
        {"analysis_warning": "operator@example.com"},
        {
            "credit_usage": {
                "before": 1200,
                "after": 1198,
                "delta": 2,
                "warnings": [],
                "raw": {"token": "secret"},
            }
        },
    ],
)
def test_virality_report_rejects_untrusted_provider_data(
    admin_client,
    client,
    db_session,
    creative_settings,
    report_overrides,
):
    _, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    response = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={
            "file": (
                "report.json",
                _virality_report(**report_overrides),
                "application/json",
            )
        },
        data={"runner_id": "mac-01", "kind": "virality_report", "is_primary": "false"},
    )
    assert response.status_code == 422
    assert "secret" not in response.text
    assert "operator@example.com" not in response.text
    assert (
        db_session.query(models.CreativeOutput)
        .filter_by(attempt_id=attempt_id, kind="virality_report")
        .count()
        == 0
    )


def test_human_review_history_preserves_runner_metadata(
    admin_client,
    client,
    creative_settings,
):
    creative_id, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    report_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("report.json", _virality_report(), "application/json")},
        data={"runner_id": "mac-01", "kind": "virality_report", "is_primary": "false"},
    )
    assert report_upload.status_code == 200, report_upload.text
    provenance = {
        "higgsfield_job_id": "11111111-1111-4111-8111-111111111111",
        "cli_version": "1.1.23",
        "credit_usage": {"before": 1200, "after": 1194, "delta": 6, "warnings": []},
    }
    final_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("final.png", _png_bytes(), "image/png")},
        data={
            "runner_id": "mac-01",
            "kind": "final_png",
            "is_primary": "true",
            "metadata_json": json.dumps({"review": provenance}),
        },
    )
    assert final_upload.status_code == 200, final_upload.text

    approved = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve",
        json={"note": "실제 화면 확인", "review_json": {"visual_check": "passed"}},
    )
    assert approved.status_code == 200, approved.text
    changed = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/request-changes",
        json={"reason": "CTA 대비 강화", "review_json": {"copy_check": "revise"}},
    )
    assert changed.status_code == 200, changed.text
    primary = next(
        output
        for output in changed.json()["attempts"][-1]["outputs"]
        if output["is_primary"]
    )
    review = primary["review_json"]
    assert review["higgsfield_job_id"] == provenance["higgsfield_job_id"]
    assert review["cli_version"] == "1.1.23"
    assert review["credit_usage"]["delta"] == 6
    assert [event["decision"] for event in review["human_review_history"]] == [
        "APPROVED",
        "CHANGES_REQUESTED",
    ]
    assert review["human_review"]["details"] == {"copy_check": "revise"}


def test_brain_activity_report_only_attempt_reaches_review(
    admin_client,
    client,
    creative_settings,
):
    created = admin_client.post(
        "/api/v1/admin/creatives",
        json=_brief_payload(
            campaign_key="brain_activity_review",
            format="video_9_16",
            generation_spec_json={
                "job_type": "brain_activity",
                "prompt": "",
                "params": {},
                "input_files": [
                    {
                        "url": "/assets/generated/source/final.mp4",
                        "sha256": "d" * 64,
                        "mime_type": "video/mp4",
                        "role": "reference",
                    }
                ],
            },
        ),
    )
    creative_id = created.json()["id"]
    approved = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve",
        json={},
    )
    assert approved.status_code == 200, approved.text
    queued = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/queue")
    attempt_id = queued.json()["id"]
    claimed = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    assert claimed.status_code == 200

    report = _virality_report(hook_peak_seconds=2.0, sustain_score=0.75)
    uploaded = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("report.json", report, "application/json")},
        data={
            "runner_id": "mac-01",
            "kind": "virality_report",
            "is_primary": "false",
        },
    )
    assert uploaded.status_code == 200, uploaded.text
    assert uploaded.json()["attempt_status"] == "REVIEW_REQUIRED"
    assert uploaded.json()["creative_status"] == "REVIEW_REQUIRED"


def test_malformed_virality_metrics_fail_closed(admin_client, client, creative_settings):
    creative_id, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    report = _virality_report(
        hook_peak_seconds="not-a-number",
        sustain_score="NaN",
        attention_overlaps_product="yes",
    )
    report_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("report.json", report, "application/json")},
        data={"runner_id": "mac-01", "kind": "virality_report", "is_primary": "false"},
    )
    assert report_upload.status_code == 422, report_upload.text
    assert "hook_peak_seconds" in report_upload.json()["detail"]
    final_upload = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("final.png", _png_bytes(), "image/png")},
        data={"runner_id": "mac-01", "kind": "final_png", "is_primary": "true"},
    )
    assert final_upload.status_code == 200, final_upload.text

    blocked = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/approve", json={})
    assert blocked.status_code == 409
    assert "virality_report_missing" in blocked.json()["detail"]


def test_runner_api_fails_closed_without_server_token(client, creative_settings):
    settings.CREATIVE_RUNNER_TOKEN_CURRENT = ""
    settings.CREATIVE_RUNNER_TOKEN_PREVIOUS = ""

    response = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )

    assert response.status_code == 503


def test_runner_failure_auth_required_and_retry(admin_client, client, creative_settings):
    creative_id, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    failed = client.post(
        f"/api/v1/creative-runner/{attempt_id}/fail",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "error": "login expired", "auth_required": True},
    )
    assert failed.status_code == 200
    assert failed.json()["status"] == "AUTH_REQUIRED"

    # Admin can requeue the same immutable snapshot as a new attempt after login repair.
    retried = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/queue")
    assert retried.status_code == 200, retried.text
    assert retried.json()["attempt_no"] == 2


def test_editing_running_brief_marks_attempt_stale(admin_client, client, creative_settings):
    creative_id, attempt_id = _create_and_queue(admin_client)
    client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "cli_version": "1.1.23"},
    )
    updated = admin_client.put(
        f"/api/v1/admin/creatives/{creative_id}",
        json={"hook": "수정된 메시지"},
    )
    assert updated.status_code == 200
    assert updated.json()["status"] == "STALE"
    assert updated.json()["attempts"][-1]["status"] == "STALE"
    heartbeat = client.post(
        f"/api/v1/creative-runner/{attempt_id}/heartbeat",
        headers=_runner_headers(),
        json={"runner_id": "mac-01", "status": "PROCESSING"},
    )
    assert heartbeat.status_code == 409


def test_landing_path_rejected_at_creation_when_redirect_would_reject_it(admin_client):
    """생성 시 검증과 /go 리다이렉트의 allowlist 가 같아야 한다.

    회귀: 생성은 '동일 사이트 절대경로' 만 보고 리다이렉트는 좁은 allowlist 를
    강제해서, /search·/compare·/account·/dashboard·맨 /blog 로 만든 브리프가
    승인·게시까지 통과한 뒤 방문자 전원이 400 을 받았다. 실패는 생성 시점에
    관리자에게 보여야 한다.
    """
    for landing in ("/search", "/compare", "/account", "/dashboard", "/blog", "/login"):
        response = admin_client.post(
            "/api/v1/admin/creatives",
            json=_brief_payload(landing_path=landing),
        )
        assert response.status_code == 422, (landing, response.text)

    # 허용 경로는 여전히 통과한다 (allowlist 자체가 줄어들면 안 된다)
    for landing in ("/", "/calculator", "/diagnose", "/blog/some-post", "/bid/R26BK01488342-000"):
        response = admin_client.post(
            "/api/v1/admin/creatives",
            json=_brief_payload(landing_path=landing),
        )
        assert response.status_code == 201, (landing, response.text)
