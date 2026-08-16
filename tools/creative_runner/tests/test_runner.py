from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import bideasy_creative_runner.runner as runner_module
from bideasy_creative_runner.api import ClaimedAttempt, InputAsset
from bideasy_creative_runner.assets import LocalAsset
from bideasy_creative_runner.higgsfield import CreditBalance, HiggsfieldResult
from bideasy_creative_runner.postprocess import ProcessedAsset
from bideasy_creative_runner.runner import (
    CreativeRunner,
    _credit_usage,
    _normalise_virality,
    _safe_error,
)


class _FakeApi:
    def __init__(self):
        self.uploads = []
        self.heartbeats = []

    def upload_output(self, attempt_id, path, **kwargs):
        self.uploads.append((attempt_id, Path(path).name, kwargs))
        return {}

    def heartbeat(self, attempt_id, **kwargs):
        self.heartbeats.append((attempt_id, kwargs))


def test_auxiliary_outputs_are_uploaded_before_primary(tmp_path: Path, runner_config):
    api = _FakeApi()
    runner = CreativeRunner(runner_config, api=api)
    original = tmp_path / "original.png"
    webp = tmp_path / "final.webp"
    final = tmp_path / "final.png"
    original.write_bytes(b"original")
    webp.write_bytes(b"webp")
    final.write_bytes(b"png")
    attempt = ClaimedAttempt(
        1, "cr", 1, "gpt_image_2", "p", {}, (), None, None, "blog_hero_16_9"
    )

    runner._upload_assets(
        attempt,
        LocalAsset(original, "image/png", "generated", "a" * 64),
        [
            ProcessedAsset(final, "final_png", True, {"width": 1376}),
            ProcessedAsset(webp, "webp", False, {"width": 1376}),
        ],
        "job-id",
        {"before": 100, "after": 98, "delta": 2, "warnings": []},
    )

    assert [(item[2]["kind"], item[2]["is_primary"]) for item in api.uploads] == [
        ("original", False),
        ("webp", False),
        ("final_png", True),
    ]
    assert all(
        item[2]["metadata"]["credit_usage"]
        == {"before": 100, "after": 98, "delta": 2, "warnings": []}
        for item in api.uploads
    )
    assert all(
        item[2]["metadata"]["review"]["credit_usage"]["delta"] == 2
        for item in api.uploads
    )


def test_server_error_summary_never_contains_local_path_or_token():
    raw = RuntimeError("/Users/operator/private.mov Authorization: Bearer hf-secret")
    summary = _safe_error(raw)

    assert "/Users/" not in summary
    assert "hf-secret" not in summary
    assert summary == "RuntimeError: unexpected local runner failure"


def test_reframe_does_not_reapply_copy_or_source_ui(
    tmp_path: Path, runner_config, monkeypatch
):
    captured = {}

    def fake_process_video(*args, **kwargs):
        captured["params"] = args[2]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(runner_module, "process_video", fake_process_video)
    runner = CreativeRunner(runner_config, api=_FakeApi())
    generated = tmp_path / "reframed.mp4"
    source = tmp_path / "already-composited.mp4"
    attempt = ClaimedAttempt(
        3,
        "cr_reframe",
        1,
        "reframe",
        "",
        {
            "aspect_ratio": "1:1",
            "source_ui_timeline": "campaign_15s_v1",
        },
        (),
        None,
        None,
        "video_1_1",
        hook="approved hook",
        body_copy="approved body",
        cta_copy="approved CTA",
    )

    runner._postprocess(
        attempt,
        LocalAsset(generated, "video/mp4", "generated", "a" * 64),
        [LocalAsset(source, "video/mp4", "source_ui", "b" * 64)],
        tmp_path,
    )

    assert captured["copy_spec"] is None
    assert captured["font_dir"] is None
    assert captured["source_ui"] is None
    assert "source_ui_timeline" not in captured["params"]


def test_marketing_video_injects_locked_campaign_timeline(
    tmp_path: Path, runner_config, monkeypatch
):
    captured = {}

    def fake_process_video(*args, **kwargs):
        captured["params"] = args[2]
        captured.update(kwargs)
        return []

    monkeypatch.setattr(runner_module, "process_video", fake_process_video)
    runner = CreativeRunner(runner_config, api=_FakeApi())
    generated = tmp_path / "generated.mp4"
    attempt = ClaimedAttempt(
        4,
        "cr_video",
        1,
        "marketing_studio_video",
        "safe prompt",
        {
            "composite_source_ui": True,
            "source_ui_timeline": "brief_cannot_override_this",
        },
        (),
        None,
        None,
        "video_9_16",
        hook="approved hook",
        body_copy="approved body",
        cta_copy="approved CTA",
    )
    inputs = [
        LocalAsset(tmp_path / "ui.png", "image/png", "source_ui", "a" * 64),
        LocalAsset(tmp_path / "voice.wav", "audio/wav", "voiceover", "b" * 64),
    ]

    runner._postprocess(
        attempt,
        LocalAsset(generated, "video/mp4", "generated", "c" * 64),
        inputs,
        tmp_path,
    )

    assert captured["params"]["source_ui_timeline"] == "campaign_15s_v1"
    assert captured["copy_spec"] is not None
    assert captured["source_ui"] == tmp_path / "ui.png"
    assert captured["voiceover"] == tmp_path / "voice.wav"


def test_final_video_runs_brain_activity_and_uploads_report_before_primary(
    tmp_path: Path, runner_config
):
    class FakeHiggsfield:
        def __init__(self):
            self.calls = []

        def run(self, attempt, inputs, heartbeat, *, on_job_id=None):
            self.calls.append((attempt, inputs))
            if on_job_id:
                on_job_id("22222222-2222-4222-8222-222222222222")
            return HiggsfieldResult(
                {
                    "hook_peak_seconds": 1.8,
                    "sustain_score": 76,
                    "attention_overlaps_product": True,
                },
                "22222222-2222-4222-8222-222222222222",
                (),
            )

    api = _FakeApi()
    higgsfield = FakeHiggsfield()
    runner = CreativeRunner(runner_config, api=api, higgsfield=higgsfield)
    original = tmp_path / "original.mp4"
    final = tmp_path / "final.mp4"
    poster = tmp_path / "poster.png"
    original.write_bytes(b"original-video")
    final.write_bytes(b"final-composited-video")
    poster.write_bytes(b"poster")
    attempt = ClaimedAttempt(
        9,
        "cr_video",
        1,
        "marketing_studio_video",
        "safe prompt",
        {},
        (),
        None,
        None,
        "video_9_16",
        higgsfield_job_id="11111111-1111-4111-8111-111111111111",
        virality_job_id="22222222-2222-4222-8222-222222222222",
        hook="approved hook",
        body_copy="approved body",
        cta_copy="approved CTA",
    )
    processed = [
        ProcessedAsset(final, "mp4", True, {"width": 1080, "height": 1920}),
        ProcessedAsset(poster, "poster", False, {"width": 1080, "height": 1920}),
    ]

    report = runner._automatic_virality_report(
        attempt,
        processed,
        tmp_path,
        attempt.higgsfield_job_id,
    )
    processed.append(report)
    runner._upload_assets(
        attempt,
        LocalAsset(original, "video/mp4", "generated", "a" * 64),
        processed,
        attempt.higgsfield_job_id,
        {"before": 1200, "after": 1196, "delta": 4, "warnings": []},
    )

    analysis_attempt, analysis_inputs = higgsfield.calls[0]
    assert analysis_attempt.job_type == "brain_activity"
    assert analysis_attempt.higgsfield_job_id == "22222222-2222-4222-8222-222222222222"
    assert analysis_inputs[0].path == final
    assert [item[2]["kind"] for item in api.uploads] == [
        "original",
        "poster",
        "virality_report",
        "mp4",
    ]
    payload = json.loads(report.path.read_text(encoding="utf-8"))
    assert payload["hook_peak_seconds"] == 1.8
    assert payload["sustain_score"] == 0.76
    assert any(
        heartbeat[1].get("virality_job_id") == "22222222-2222-4222-8222-222222222222"
        for heartbeat in api.heartbeats
    )


def test_execute_includes_generation_and_predictor_in_credit_delta(
    tmp_path: Path, runner_config, monkeypatch
):
    class CapturingApi(_FakeApi):
        def upload_output(self, attempt_id, path, **kwargs):
            self.uploads.append(
                (attempt_id, Path(path).name, kwargs, Path(path).read_bytes())
            )
            return {}

    class FakeDownloader:
        def set_heartbeat(self, heartbeat):
            self.heartbeat = heartbeat

        def close(self):
            self.closed = True

    class FakeHiggsfield:
        def __init__(self):
            self.credit_values = iter((CreditBalance(1200), CreditBalance(1194)))
            self.jobs = []

        def credit_balance(self):
            return next(self.credit_values)

        def run(self, attempt, inputs, heartbeat, *, on_job_id=None):
            self.jobs.append(attempt.job_type)
            job_id = (
                "22222222-2222-4222-8222-222222222222"
                if attempt.job_type == "brain_activity"
                else "11111111-1111-4111-8111-111111111111"
            )
            if on_job_id:
                on_job_id(job_id)
            raw = (
                {
                    "hook_peak_seconds": 1.9,
                    "sustain_score": 0.75,
                    "attention_overlaps_product": True,
                }
                if attempt.job_type == "brain_activity"
                else {"id": job_id}
            )
            return HiggsfieldResult(raw, job_id, ())

    source_ui = InputAsset(
        "https://bideasy.kr/guide-assets/01-main-g2b-with-sidepanel.png",
        "bdff901a2882995afd19bf0476cb99fb1407abb1011365e9616ec787d006d765",
        "image/png",
        "source_ui",
    )
    storyboard = InputAsset(
        "https://bideasy.kr/storyboard.png", "b" * 64, "image/png", "storyboard"
    )
    voiceover = InputAsset(
        "https://bideasy.kr/founder.wav", "c" * 64, "audio/wav", "voiceover"
    )
    attempt = ClaimedAttempt(
        10,
        "cr_video_execute",
        1,
        "marketing_studio_video",
        "safe product background",
        {"composite_source_ui": True},
        (source_ui, storyboard, voiceover),
        "d" * 64,
        "2026-08-14T00:05:00",
        "video_9_16",
        hook="approved hook",
        body_copy="approved body",
        cta_copy="approved CTA",
    )
    original = tmp_path / "original.mp4"
    final = tmp_path / "final.mp4"
    poster = tmp_path / "poster.png"
    original.write_bytes(b"original")
    final.write_bytes(b"final")
    poster.write_bytes(b"poster")
    local_inputs = [
        LocalAsset(tmp_path / "ui.png", "image/png", "source_ui", source_ui.sha256),
        LocalAsset(
            tmp_path / "storyboard.png", "image/png", "storyboard", storyboard.sha256
        ),
        LocalAsset(
            tmp_path / "founder.wav", "audio/wav", "voiceover", voiceover.sha256
        ),
    ]
    downloader = FakeDownloader()
    api = CapturingApi()
    higgsfield = FakeHiggsfield()
    policy_payload = json.loads(
        runner_config.brand_policy_path.read_text(encoding="utf-8")
    )
    policy_payload["source_ui_assets"][0]["campaign_approved"] = True
    policy_path = tmp_path / "approved-source-policy.json"
    policy_path.write_text(
        json.dumps(policy_payload, ensure_ascii=False), encoding="utf-8"
    )
    approved_config = replace(runner_config, brand_policy_path=policy_path)
    runner = CreativeRunner(approved_config, api=api, higgsfield=higgsfield)
    monkeypatch.setattr(
        runner,
        "_download_inputs",
        lambda _attempt, _directory: (local_inputs, downloader),
    )
    monkeypatch.setattr(
        runner,
        "_download_result",
        lambda _attempt, _result, _directory, _downloader: LocalAsset(
            original, "video/mp4", "generated", "e" * 64
        ),
    )
    monkeypatch.setattr(
        runner,
        "_postprocess",
        lambda _attempt, _generated, _inputs, _directory: [
            ProcessedAsset(final, "mp4", True, {"width": 1080, "height": 1920}),
            ProcessedAsset(poster, "poster", False, {"width": 1080, "height": 1920}),
        ],
    )

    runner.execute(attempt)

    assert higgsfield.jobs == ["marketing_studio_video", "brain_activity"]
    assert [upload[2]["kind"] for upload in api.uploads] == [
        "original",
        "poster",
        "virality_report",
        "mp4",
    ]
    assert all(
        upload[2]["metadata"]["credit_usage"]
        == {"before": 1200, "after": 1194, "delta": 6, "warnings": []}
        for upload in api.uploads
    )
    assert all(
        upload[2]["metadata"]["review"]["credit_usage"]["delta"] == 6
        for upload in api.uploads
    )
    report_upload = next(
        upload for upload in api.uploads if upload[2]["kind"] == "virality_report"
    )
    report_payload = json.loads(report_upload[3])
    assert report_payload["credit_usage"]["delta"] == 6
    assert downloader.closed is True


def test_credit_usage_is_numeric_only_and_warns_when_unavailable():
    assert _credit_usage(CreditBalance(1200), CreditBalance(1197.5)) == {
        "before": 1200,
        "after": 1197.5,
        "delta": 2.5,
        "warnings": [],
    }
    missing = _credit_usage(
        CreditBalance(None, "credits_value_missing"),
        CreditBalance(None, "account_status_unavailable"),
    )
    assert missing["before"] is None
    assert missing["after"] is None
    assert missing["delta"] is None
    assert missing["warnings"] == [
        "credits_value_missing",
        "account_status_unavailable",
    ]


def test_virality_metrics_normalise_known_flat_and_nested_keys_without_inference():
    flat = _normalise_virality(
        {
            "hook_peak_seconds": 2.4,
            "sustain_score": 78,
            "attention_overlaps_product": True,
            "report_url": "https://higgsfield.ai/report/approved",
        }
    )
    assert flat == {
        "hook_peak_seconds": 2.4,
        "sustain_score": 0.78,
        "attention_overlaps_product": True,
        "report_url": "https://higgsfield.ai/report/approved",
    }

    nested = _normalise_virality(
        {
            "results": {
                "hookPeakSecond": {"seconds": "1.5"},
                "sustainedAttentionScore": {"score": 0.74},
                "productAttentionOverlap": False,
                "openReportUrl": "https://higgsfield.ai/report/nested",
            }
        }
    )
    assert nested["hook_peak_seconds"] == 1.5
    assert nested["sustain_score"] == 0.74
    assert nested["attention_overlaps_product"] is False
    assert nested["report_url"] == "https://higgsfield.ai/report/nested"

    unknown = _normalise_virality({"overall_score": 99, "peak_second": 1})
    assert unknown == {
        "hook_peak_seconds": None,
        "sustain_score": None,
        "attention_overlaps_product": None,
        "report_url": None,
    }

    conflicting = _normalise_virality(
        {
            "hook_peak_seconds": 1.0,
            "hookPeakSecond": 2.0,
            "attention_overlaps_product": True,
            "productAttentionOverlap": 1,
        }
    )
    assert conflicting["hook_peak_seconds"] is None
    assert conflicting["attention_overlaps_product"] is None


def test_virality_report_drops_raw_provider_secrets_and_signed_urls(tmp_path: Path):
    secret = "provider-secret-that-must-never-be-published"
    result = HiggsfieldResult(
        {
            "metrics": {
                "hook_peak_seconds": 1.7,
                "sustain_score": 81,
                "attention_overlaps_product": True,
            },
            "email": "operator@example.com",
            "token": secret,
            "signed_url": f"https://cdn.example/video.mp4?token={secret}",
            "report_url": f"https://app.higgsfield.ai/report/42?token={secret}",
        },
        "22222222-2222-4222-8222-222222222222",
        (),
    )

    report = runner_module._write_report(result, tmp_path)
    report_bytes = report.read_bytes()
    payload = json.loads(report_bytes)

    assert payload["hook_peak_seconds"] == 1.7
    assert payload["sustain_score"] == 0.81
    assert payload["attention_overlaps_product"] is True
    assert payload["report_url"] is None
    assert payload["human_review_required"] is True
    assert b"operator@example.com" not in report_bytes
    assert secret.encode() not in report_bytes
    assert b"signed_url" not in report_bytes
    assert "analysis" not in payload


def test_unknown_virality_schema_is_null_with_review_warning(tmp_path: Path):
    result = HiggsfieldResult(
        {"unrecognised": {"overall": 98}},
        "22222222-2222-4222-8222-222222222222",
        (),
    )

    report = runner_module._write_report(result, tmp_path)
    payload = json.loads(report.read_text(encoding="utf-8"))

    assert payload["hook_peak_seconds"] is None
    assert payload["sustain_score"] is None
    assert payload["attention_overlaps_product"] is None
    assert payload["analysis_warning"] == "virality_metrics_incomplete"
    assert payload["human_review_required"] is True
