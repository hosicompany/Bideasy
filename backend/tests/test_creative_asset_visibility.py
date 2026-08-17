"""Creative files stay private until their exact attempt is human-approved."""
from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import pytest
from PIL import Image

from app.core.config import settings
from app.db import models


@pytest.fixture
def asset_visibility_settings(tmp_path, db_session):
    previous = {
        "current": settings.CREATIVE_RUNNER_TOKEN_CURRENT,
        "previous": settings.CREATIVE_RUNNER_TOKEN_PREVIOUS,
        "root": settings.CREATIVE_ASSET_ROOT,
        "base": settings.CREATIVE_ASSET_BASE_URL,
    }
    settings.CREATIVE_RUNNER_TOKEN_CURRENT = "asset-visibility-runner-token"
    settings.CREATIVE_RUNNER_TOKEN_PREVIOUS = ""
    settings.CREATIVE_ASSET_ROOT = str(tmp_path / "creative-assets")
    settings.CREATIVE_ASSET_BASE_URL = "/assets/generated"
    db_session.query(models.CreativeOutput).delete()
    db_session.query(models.CreativeAttempt).delete()
    db_session.query(models.CreativeBrief).delete()
    db_session.commit()
    yield
    db_session.query(models.CreativeOutput).delete()
    db_session.query(models.CreativeAttempt).delete()
    db_session.query(models.CreativeBrief).delete()
    db_session.commit()
    settings.CREATIVE_RUNNER_TOKEN_CURRENT = previous["current"]
    settings.CREATIVE_RUNNER_TOKEN_PREVIOUS = previous["previous"]
    settings.CREATIVE_ASSET_ROOT = previous["root"]
    settings.CREATIVE_ASSET_BASE_URL = previous["base"]


def _brief_payload() -> dict:
    return {
        "campaign_key": "asset_visibility_a",
        "concept_key": "mechanism",
        "variant": "A",
        "channel": "youtube",
        "format": "static_1_1",
        "hook": "나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        "body_copy": "보고 있는 공고 화면에서 확인하세요.",
        "cta_copy": "이 공고 확인하기",
        "landing_path": "/calculator",
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
                    "sha256": "a" * 64,
                    "mime_type": "image/png",
                    "role": "source_ui",
                }
            ],
        },
    }


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (1080, 1080), color=(49, 130, 246)).save(stream, format="PNG")
    return stream.getvalue()


def _report_bytes() -> bytes:
    return json.dumps(
        {
            "higgsfield_job_id": "22222222-2222-4222-8222-222222222222",
            "virality_job_id": "22222222-2222-4222-8222-222222222222",
            "hook_peak_seconds": 1.8,
            "sustain_score": 0.76,
            "attention_overlaps_product": True,
            "report_url": (
                "https://app.higgsfield.ai/reports/"
                "22222222-2222-4222-8222-222222222222"
            ),
            "human_review_required": True,
            "analysis_warning": None,
            "credit_usage": {"before": 1200, "after": 1196, "delta": 4, "warnings": []},
        },
        separators=(",", ":"),
    ).encode()


def _runner_headers() -> dict[str, str]:
    return {"Authorization": "Bearer asset-visibility-runner-token"}


def _create_review_outputs(admin_client, client) -> tuple[str, dict, dict, dict]:
    created = admin_client.post("/api/v1/admin/creatives", json=_brief_payload())
    assert created.status_code == 201, created.text
    creative_id = created.json()["id"]
    approved_brief = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve", json={}
    )
    assert approved_brief.status_code == 200, approved_brief.text
    queued = admin_client.post(f"/api/v1/admin/creatives/{creative_id}/queue")
    assert queued.status_code == 200, queued.text
    attempt_id = queued.json()["id"]
    claimed = client.post(
        "/api/v1/creative-runner/claim",
        headers=_runner_headers(),
        json={"runner_id": "asset-runner", "cli_version": "1.1.23"},
    )
    assert claimed.status_code == 200, claimed.text

    original_content = _png_bytes()
    original = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("provider-original.png", original_content, "image/png")},
        data={
            "runner_id": "asset-runner",
            "kind": "original",
            "is_primary": "false",
            "sha256": hashlib.sha256(original_content).hexdigest(),
        },
    )
    assert original.status_code == 200, original.text

    report = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("report.json", _report_bytes(), "application/json")},
        data={"runner_id": "asset-runner", "kind": "virality_report", "is_primary": "false"},
    )
    assert report.status_code == 200, report.text

    content = _png_bytes()
    final = client.post(
        f"/api/v1/creative-runner/{attempt_id}/output",
        headers=_runner_headers(),
        files={"file": ("final.png", content, "image/png")},
        data={
            "runner_id": "asset-runner",
            "kind": "final_png",
            "is_primary": "true",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
    )
    assert final.status_code == 200, final.text
    return (
        creative_id,
        final.json()["output"],
        original.json()["output"],
        report.json()["output"],
    )


def test_outputs_are_private_until_approved_and_close_again_on_changes(
    admin_client,
    client,
    asset_visibility_settings,
    monkeypatch,
):
    creative_id, final, original, report = _create_review_outputs(admin_client, client)
    expected_final = _png_bytes()

    assert client.get(final["public_url"]).status_code == 404
    assert client.head(final["public_url"]).status_code == 404
    assert client.get(original["public_url"]).status_code == 404
    assert client.get(report["public_url"]).status_code == 404

    admin_download = admin_client.get(
        f"/api/v1/admin/creative-outputs/{final['id']}/download"
    )
    assert admin_download.status_code == 200
    assert admin_download.content == expected_final
    assert "x-accel-redirect" not in admin_download.headers
    assert admin_download.headers["cache-control"] == "private, no-store, max-age=0"

    assert client.get(f"/api/v1/creative-runner/outputs/{final['id']}/download").status_code == 401
    runner_download = client.get(
        f"/api/v1/creative-runner/outputs/{final['id']}/download",
        headers=_runner_headers(),
    )
    assert runner_download.status_code == 200
    assert runner_download.content == expected_final

    monkeypatch.setattr(settings, "APP_ENV", "production")
    production_download = admin_client.get(
        f"/api/v1/admin/creative-outputs/{final['id']}/download"
    )
    assert production_download.status_code == 200
    assert production_download.headers["x-accel-redirect"].endswith(final["storage_path"])
    assert production_download.content == b""
    monkeypatch.setattr(settings, "APP_ENV", "development")

    approved = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/approve",
        json={"note": "실제 UI와 카피를 사람 검수함"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "APPROVED"

    public_final = client.get(final["public_url"])
    assert public_final.status_code == 200
    assert public_final.content == expected_final
    assert public_final.headers["cache-control"] == "public, max-age=0, must-revalidate"
    public_head = client.head(final["public_url"])
    assert public_head.status_code == 200
    assert public_head.content == b""
    # Provider originals and operational reports do not become public merely
    # because the final attempt was approved.
    assert client.get(original["public_url"]).status_code == 404
    assert client.get(report["public_url"]).status_code == 404

    changes = admin_client.post(
        f"/api/v1/admin/creatives/{creative_id}/request-changes",
        json={"reason": "자막 위치 수정"},
    )
    assert changes.status_code == 200, changes.text
    assert client.get(final["public_url"]).status_code == 404
    assert admin_client.get(
        f"/api/v1/admin/creative-outputs/{final['id']}/download"
    ).status_code == 200


def _location_block(source: str, marker: str) -> str:
    start = source.index(marker)
    opening = source.index("{", start)
    depth = 0
    for index in range(opening, len(source)):
        if source[index] == "{":
            depth += 1
        elif source[index] == "}":
            depth -= 1
            if depth == 0:
                return source[start : index + 1]
    raise AssertionError(f"unclosed nginx block: {marker}")


def test_nginx_never_maps_public_generated_urls_directly():
    repo_root = Path(__file__).resolve().parents[2]
    public_configs = [
        repo_root / "infra/nginx/conf.d/default.conf",
        repo_root / "infra/nginx/conf.d-http/default.conf",
    ]
    for config in public_configs:
        source = config.read_text(encoding="utf-8")
        public = _location_block(source, "location ^~ /assets/generated/")
        internal = _location_block(source, "location ^~ /_creative_assets_internal/")
        assert "proxy_pass http://bideasy_api;" in public
        assert "alias /var/www/creative_assets/;" not in public
        assert "internal;" in internal
        assert "alias /var/www/creative_assets/;" in internal

    api_source = (
        repo_root / "infra/nginx/conf.d/api.bideasy.kr.conf.disabled"
    ).read_text(encoding="utf-8")
    api_internal = _location_block(api_source, "location ^~ /_creative_assets_internal/")
    assert "internal;" in api_internal
    assert "alias /var/www/creative_assets/;" in api_internal
