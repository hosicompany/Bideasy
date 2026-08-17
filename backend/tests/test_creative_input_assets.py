"""Private creative input upload, delivery and claim contract tests."""
from __future__ import annotations

import hashlib
import io
import wave
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.db import models


@pytest.fixture
def private_input_settings(tmp_path, db_session):
    previous = {
        "current": settings.CREATIVE_RUNNER_TOKEN_CURRENT,
        "previous": settings.CREATIVE_RUNNER_TOKEN_PREVIOUS,
        "root": settings.CREATIVE_ASSET_ROOT,
        "max_upload": settings.CREATIVE_MAX_UPLOAD_BYTES,
        "public_api": settings.PUBLIC_API_URL,
        "app_env": settings.APP_ENV,
    }
    settings.CREATIVE_RUNNER_TOKEN_CURRENT = "private-input-runner-token"
    settings.CREATIVE_RUNNER_TOKEN_PREVIOUS = ""
    settings.CREATIVE_ASSET_ROOT = str(tmp_path / "creative-assets")
    settings.CREATIVE_MAX_UPLOAD_BYTES = 150 * 1024 * 1024
    settings.PUBLIC_API_URL = "https://api.bideasy.kr"
    settings.APP_ENV = "development"
    db_session.query(models.CreativeInputAsset).delete()
    db_session.query(models.CreativeOutput).delete()
    db_session.query(models.CreativeAttempt).delete()
    db_session.query(models.CreativeBrief).delete()
    db_session.commit()
    yield
    db_session.query(models.CreativeInputAsset).delete()
    db_session.query(models.CreativeOutput).delete()
    db_session.query(models.CreativeAttempt).delete()
    db_session.query(models.CreativeBrief).delete()
    db_session.commit()
    settings.CREATIVE_RUNNER_TOKEN_CURRENT = previous["current"]
    settings.CREATIVE_RUNNER_TOKEN_PREVIOUS = previous["previous"]
    settings.CREATIVE_ASSET_ROOT = previous["root"]
    settings.CREATIVE_MAX_UPLOAD_BYTES = previous["max_upload"]
    settings.PUBLIC_API_URL = previous["public_api"]
    settings.APP_ENV = previous["app_env"]


def _png_bytes(size: tuple[int, int] = (320, 180)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color=(43, 80, 224)).save(stream, format="PNG")
    return stream.getvalue()


def _wav_bytes(
    seconds: float = 0.25,
    sample_rate: int = 16_000,
    channels: int = 1,
) -> bytes:
    stream = io.BytesIO()
    with wave.open(stream, "wb") as target:
        target.setnchannels(channels)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(
            b"\x00\x00" * round(seconds * sample_rate) * channels
        )
    return stream.getvalue()


def _brief_payload(**overrides) -> dict:
    payload = {
        "campaign_key": "private_input_contract",
        "concept_key": "mechanism",
        "variant": "A",
        "channel": "youtube",
        "format": "video_9_16",
        "hook": "나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        "body_copy": "보고 있는 공고 화면에서 확인하세요.",
        "cta_copy": "이 공고 확인하기",
        "landing_path": "/calculator",
        "generation_spec_json": {
            "job_type": "marketing_studio_video",
            "prompt": "calm abstract blue motion background, no text, no UI",
            "params": {
                "specific_mode": "from_storyboard",
                "aspect_ratio": "9:16",
                "resolution": "1080p",
                "generate_audio": False,
                "composite_source_ui": True,
            },
            "input_files": [],
        },
    }
    payload.update(overrides)
    return payload


def _create_brief(admin_client, **overrides) -> str:
    response = admin_client.post(
        "/api/v1/admin/creatives", json=_brief_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _upload(admin_client, creative_id: str, role: str, name: str, body: bytes, mime: str):
    return admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/inputs",
        data={"role": role},
        files={"file": (name, body, mime)},
    )


def _runner_headers() -> dict[str, str]:
    return {"Authorization": "Bearer private-input-runner-token"}


def test_private_image_upload_has_no_public_route_and_requires_auth(
    admin_client,
    client,
    db_session,
    private_input_settings,
    monkeypatch,
):
    creative_id = _create_brief(admin_client)
    content = _png_bytes()

    unauthenticated = client.post(
        f"/api/v1/admin/creatives/{creative_id}/inputs",
        data={"role": "source_ui"},
        files={"file": ("screen.png", content, "image/png")},
    )
    assert unauthenticated.status_code == 401

    uploaded = _upload(
        admin_client,
        creative_id,
        "source_ui",
        "actual-g2b-screen.png",
        content,
        "image/png",
    )
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["role"] == "source_ui"
    assert body["sha256"] == hashlib.sha256(content).hexdigest()
    assert body["width"] == 320
    assert body["height"] == 180
    assert body["duration_ms"] is None
    assert body["manifest"] == {
        "url": f"/api/v1/creative-runner/inputs/{body['id']}/download",
        "sha256": hashlib.sha256(content).hexdigest(),
        "mime_type": "image/png",
        "role": "source_ui",
    }
    assert body["preview_url"] == (
        f"/api/v1/admin/creative-inputs/{body['id']}/download"
    )
    assert "public_url" not in body
    assert body["storage_path"].startswith(f"_inputs/{creative_id}/source_ui-")

    assert client.get(
        f"/api/v1/admin/creatives/{creative_id}/inputs"
    ).status_code == 401
    listed = admin_client.get(f"/api/v1/admin/creatives/{creative_id}/inputs")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [body["id"]]
    second_id = _create_brief(
        admin_client,
        campaign_key="private_input_empty_second",
        variant="B",
    )
    second_list = admin_client.get(f"/api/v1/admin/creatives/{second_id}/inputs")
    assert second_list.status_code == 200
    assert second_list.json() == []

    row = db_session.get(models.CreativeInputAsset, body["id"])
    assert row is not None
    stored = Path(settings.CREATIVE_ASSET_ROOT, *Path(row.storage_path).parts)
    assert stored.read_bytes() == content
    assert db_session.get(models.CreativeBrief, creative_id).status == "DRAFT"
    assert db_session.query(models.CreativeAttempt).count() == 0

    assert client.get(body["preview_url"]).status_code == 401
    admin_preview = admin_client.get(body["preview_url"])
    assert admin_preview.status_code == 200
    assert admin_preview.content == content
    assert admin_preview.headers["cache-control"] == "private, no-store, max-age=0"
    assert "actual-g2b-screen" not in admin_preview.headers["content-disposition"]

    runner_url = body["manifest"]["url"]
    assert client.get(runner_url).status_code == 401
    runner_download = client.get(runner_url, headers=_runner_headers())
    assert runner_download.status_code == 200
    assert runner_download.content == content

    assert client.get(f"/assets/generated/{body['storage_path']}").status_code == 404
    assert client.get(f"/_creative_assets_internal/{body['storage_path']}").status_code == 404

    monkeypatch.setattr(settings, "APP_ENV", "production")
    production_preview = admin_client.get(body["preview_url"])
    assert production_preview.status_code == 200
    assert production_preview.content == b""
    assert production_preview.headers["x-accel-redirect"].endswith(
        body["storage_path"]
    )
    assert "actual-g2b-screen" not in production_preview.headers["content-disposition"]


def test_upload_validates_role_magic_extension_size_and_wav_metadata(
    admin_client,
    db_session,
    private_input_settings,
    monkeypatch,
):
    creative_id = _create_brief(admin_client)
    content = _png_bytes()

    invalid_role = _upload(
        admin_client, creative_id, "public", "screen.png", content, "image/png"
    )
    assert invalid_role.status_code == 422

    wrong_role = _upload(
        admin_client, creative_id, "voiceover", "voice.png", content, "image/png"
    )
    assert wrong_role.status_code == 422

    wrong_declared_mime = _upload(
        admin_client,
        creative_id,
        "source_ui",
        "screen.png",
        content,
        "application/octet-stream",
    )
    assert wrong_declared_mime.status_code == 422

    wrong_magic = _upload(
        admin_client,
        creative_id,
        "voiceover",
        "voice.wav",
        b"not-a-wave-file",
        "audio/wav",
    )
    assert wrong_magic.status_code == 422
    assert "실제 형식" in wrong_magic.json()["detail"]

    wrong_extension = _upload(
        admin_client, creative_id, "storyboard", "board.jpg", content, "image/png"
    )
    assert wrong_extension.status_code == 422

    oversized_dimensions = _upload(
        admin_client,
        creative_id,
        "storyboard",
        "wide.png",
        _png_bytes((10_001, 1)),
        "image/png",
    )
    assert oversized_dimensions.status_code == 422
    assert "해상도" in oversized_dimensions.json()["detail"]

    wav = _wav_bytes()
    voice = _upload(
        admin_client, creative_id, "voiceover", "founder.wav", wav, "audio/x-wav"
    )
    assert voice.status_code == 201, voice.text
    voice_body = voice.json()
    assert voice_body["mime_type"] == "audio/wav"
    assert voice_body["duration_ms"] == 250
    assert voice_body["media_metadata_json"]["channels"] == 1
    assert voice_body["media_metadata_json"]["sample_rate"] == 16_000

    monkeypatch.setattr(settings, "CREATIVE_MAX_UPLOAD_BYTES", 32)
    too_large = _upload(
        admin_client, creative_id, "source_ui", "screen.png", content, "image/png"
    )
    assert too_large.status_code == 422
    assert "한도" in too_large.json()["detail"]
    assert db_session.query(models.CreativeInputAsset).count() == 1
    assert not list(Path(settings.CREATIVE_ASSET_ROOT).rglob(".input-upload-*"))


def test_wav_upload_rejects_missing_or_truncated_pcm_payload_and_keeps_mono_stereo(
    admin_client,
    db_session,
    private_input_settings,
):
    creative_id = _create_brief(admin_client)

    for channels in (1, 2):
        wav = _wav_bytes(channels=channels)
        valid = _upload(
            admin_client,
            creative_id,
            "voiceover",
            f"valid-{channels}-channel.wav",
            wav,
            "audio/wav",
        )
        assert valid.status_code == 201, valid.text
        assert valid.json()["duration_ms"] == 250
        assert valid.json()["media_metadata_json"]["channels"] == channels

    complete_wav = _wav_bytes()
    header_only = _upload(
        admin_client,
        creative_id,
        "voiceover",
        "header-only.wav",
        complete_wav[:44],
        "audio/wav",
    )
    assert header_only.status_code == 422
    assert "선언된 길이" in header_only.json()["detail"]

    truncated = _upload(
        admin_client,
        creative_id,
        "voiceover",
        "truncated.wav",
        complete_wav[:-2],
        "audio/wav",
    )
    assert truncated.status_code == 422
    assert "선언된 길이" in truncated.json()["detail"]

    unsupported_width = bytearray(_wav_bytes())
    unsupported_width[28:32] = (16_000 * 5).to_bytes(4, "little")
    unsupported_width[32:34] = (5).to_bytes(2, "little")
    unsupported_width[34:36] = (5 * 8).to_bytes(2, "little")
    malformed_sample_width = _upload(
        admin_client,
        creative_id,
        "voiceover",
        "unsupported-sample-width.wav",
        bytes(unsupported_width),
        "audio/wav",
    )
    assert malformed_sample_width.status_code == 422
    assert "샘플폭" in malformed_sample_width.json()["detail"]

    assert db_session.query(models.CreativeInputAsset).count() == 2
    assert not list(Path(settings.CREATIVE_ASSET_ROOT).rglob(".input-upload-*"))


def test_uploaded_manifests_are_verified_and_claimed_from_authenticated_api_origin(
    admin_client,
    client,
    db_session,
    private_input_settings,
):
    creative_id = _create_brief(admin_client)
    source = _upload(
        admin_client,
        creative_id,
        "source_ui",
        "source.png",
        _png_bytes((640, 360)),
        "image/png",
    ).json()
    storyboard = _upload(
        admin_client,
        creative_id,
        "storyboard",
        "storyboard.png",
        _png_bytes((540, 960)),
        "image/png",
    ).json()
    voice = _upload(
        admin_client,
        creative_id,
        "voiceover",
        "voice.wav",
        _wav_bytes(0.5),
        "audio/wav",
    ).json()

    spec = _brief_payload()["generation_spec_json"]
    spec["input_files"] = [
        source["manifest"],
        storyboard["manifest"],
        voice["manifest"],
    ]
    updated = admin_client.put(
        f"/api/v1/admin/creatives/{creative_id}",
        json={"generation_spec_json": spec},
    )
    assert updated.status_code == 200, updated.text
    approved = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve", json={}
    )
    assert approved.status_code == 200, approved.text
    queued = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/queue")
    assert queued.status_code == 200, queued.text

    claim = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "private-input-mac", "cli_version": "1.1.23"},
    )
    assert claim.status_code == 200, claim.text
    claimed_inputs = claim.json()["input_files_json"]
    assert len(claimed_inputs) == 3
    for claimed, uploaded in zip(claimed_inputs, (source, storyboard, voice), strict=True):
        assert claimed["url"] == settings.PUBLIC_API_URL + uploaded["manifest"]["url"]
        assert claimed["sha256"] == uploaded["sha256"]
        assert "/assets/generated/" not in claimed["url"]

    attempt = db_session.get(models.CreativeAttempt, queued.json()["id"])
    assert attempt is not None
    assert all(
        item["url"].startswith("/api/v1/creative-runner/inputs/")
        for item in attempt.input_files_json
    )


def test_private_manifest_cannot_cross_briefs_or_forge_hash(
    admin_client,
    private_input_settings,
):
    first_id = _create_brief(admin_client)
    second_id = _create_brief(
        admin_client,
        campaign_key="private_input_contract_second",
        variant="B",
    )
    source = _upload(
        admin_client,
        first_id,
        "source_ui",
        "source.png",
        _png_bytes(),
        "image/png",
    ).json()

    spec = {
        "job_type": "marketing_studio_image",
        "prompt": "clean blue editorial background, no text, no UI",
        "params": {
            "aspect_ratio": "1:1",
            "resolution": "2K",
            "composite_source_ui": True,
        },
        "input_files": [],
    }
    spec["input_files"] = [{**source["manifest"], "sha256": "0" * 64}]
    updated = admin_client.put(
        f"/api/v1/admin/creatives/{first_id}",
        json={"format": "static_1_1", "generation_spec_json": spec},
    )
    assert updated.status_code == 200
    forged = admin_client.post(
        f"/api/v1/admin/creatives/{first_id}/approve", json={}
    )
    assert forged.status_code == 422
    assert "SHA-256" in forged.json()["detail"]

    spec["input_files"] = [
        {**source["manifest"], "url": source["manifest"]["url"] + "?download=1"}
    ]
    admin_client.put(
        f"/api/v1/admin/creatives/{first_id}",
        json={"generation_spec_json": spec},
    )
    near_private = admin_client.post(
        f"/api/v1/admin/creatives/{first_id}/approve", json={}
    )
    assert near_private.status_code == 422
    assert "query" in near_private.json()["detail"]

    spec["input_files"] = [source["manifest"]]
    copied = admin_client.put(
        f"/api/v1/admin/creatives/{second_id}",
        json={"format": "static_1_1", "generation_spec_json": spec},
    )
    assert copied.status_code == 200
    cross_brief = admin_client.post(
        f"/api/v1/admin/creatives/{second_id}/approve", json={}
    )
    assert cross_brief.status_code == 422
    assert "다른 브리프" in cross_brief.json()["detail"]
