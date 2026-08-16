from __future__ import annotations

import copy
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from bideasy_creative_runner.prevoice import (
    PrevoiceValidationError,
    render_prevoice_package,
    render_provider_storyboard,
    render_review_storyboard,
    validate_preproduction_spec,
)
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[3]
SPEC_PATH = REPO_ROOT / "docs" / "CREATIVE_PREPRODUCTION_15S.json"
BRAND_PATH = REPO_ROOT / "docs" / "CREATIVE_BRAND_KIT.json"


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_prevoice_spec_is_exactly_bound_to_brand_and_remains_non_publishable():
    spec, brand = validate_preproduction_spec(SPEC_PATH, BRAND_PATH)

    assert [item["id"] for item in spec["variants"]] == ["A", "B"]
    assert spec["publishable"] is False
    assert spec["higgsfield"]["paid_generation_status"] == "NOT_STARTED"
    assert spec["source_ui"]["status"] == "REQUIRED_NEW_CAPTURE"
    assert spec["voice"]["status"] == "REQUIRED_NOT_UPLOADED"
    assert brand["production_rules"]["representative_real_voice_only"] is True


def test_prevoice_spec_rejects_copy_drift(tmp_path: Path):
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    changed = copy.deepcopy(spec)
    changed["variants"][0]["hook"] = "낙찰 보장"
    changed_path = tmp_path / "changed.json"
    changed_path.write_text(json.dumps(changed, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(PrevoiceValidationError, match="A/B hook"):
        validate_preproduction_spec(changed_path, BRAND_PATH)


def test_provider_storyboard_is_shared_while_review_boards_keep_only_hook_difference(
    tmp_path: Path, runner_config
):
    spec, brand = validate_preproduction_spec(SPEC_PATH, BRAND_PATH)
    provider_one = render_provider_storyboard(brand, tmp_path / "provider-one.png")
    provider_two = render_provider_storyboard(brand, tmp_path / "provider-two.png")
    board_a = render_review_storyboard(
        spec,
        brand,
        spec["variants"][0],
        runner_config.font_dir,
        tmp_path / "review-a.png",
    )
    board_b = render_review_storyboard(
        spec,
        brand,
        spec["variants"][1],
        runner_config.font_dir,
        tmp_path / "review-b.png",
    )

    assert _sha(provider_one) == _sha(provider_two)
    assert _sha(board_a) != _sha(board_b)
    for path in (provider_one, board_a, board_b):
        with Image.open(path) as image:
            assert image.size == (1920, 1080)
            assert image.mode == "RGB"


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg unavailable",
)
def test_silent_previs_is_15_seconds_and_only_hook_sample_differs(
    tmp_path: Path, runner_config
):
    manifest = render_prevoice_package(
        SPEC_PATH,
        BRAND_PATH,
        runner_config.font_dir,
        tmp_path,
    )
    videos = {
        item["variant"]: item
        for item in manifest["artifacts"]
        if item["kind"] == "silent_previs"
    }
    assert set(videos) == {"A", "B"}
    assert all(item["duration_ms"] == 15000 for item in videos.values())
    assert all(item["audio_codec"] == "aac" for item in videos.values())
    layers = {
        (item["variant"], item["kind"]): item["sha256"]
        for item in manifest["artifacts"]
        if item["kind"].startswith("deterministic_copy_")
    }
    assert (
        layers[("A", "deterministic_copy_hook")]
        != layers[("B", "deterministic_copy_hook")]
    )
    assert (
        layers[("A", "deterministic_copy_truth")]
        == layers[("B", "deterministic_copy_truth")]
    )
    assert (
        layers[("A", "deterministic_copy_final")]
        == layers[("B", "deterministic_copy_final")]
    )

    def frame_hash(variant: str, timestamp: float) -> str:
        result = subprocess.run(
            [
                "ffmpeg",
                "-v",
                "error",
                "-ss",
                str(timestamp),
                "-i",
                str(tmp_path / f"silent-previs-{variant}.mp4"),
                "-map",
                "0:v:0",
                "-frames:v",
                "1",
                "-f",
                "framemd5",
                "-",
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        row = next(
            line
            for line in reversed(result.stdout.splitlines())
            if line and not line.startswith("#")
        )
        return row.rsplit(", ", 1)[-1]

    assert frame_hash("A", 1.0) != frame_hash("B", 1.0)
    for timestamp in (3.5, 7.5, 11.5, 14.0):
        assert frame_hash("A", timestamp) == frame_hash("B", timestamp)
