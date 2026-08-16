from __future__ import annotations

import hashlib
from pathlib import Path

from bideasy_creative_runner.brand_policy import BrandPolicy
from bideasy_creative_runner.copy_layers import (
    CopySpec,
    render_static_copy_layer,
    render_video_copy_layers,
)
from PIL import Image


def _spec(runner_config) -> CopySpec:
    policy = BrandPolicy.load(runner_config.brand_policy_path)
    return CopySpec(
        hook="나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        body="보고 있는 공고 화면에서 참가조건·계산 기준·주의 조항을 확인하세요.",
        cta="이 공고 확인하기",
        endline=policy.endline,
        non_prediction_line=policy.video_non_prediction_line,
        disclaimer=policy.disclaimer,
        colors=policy.colors,
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_static_korean_copy_layer_is_exact_and_byte_deterministic(
    tmp_path: Path, runner_config
):
    first = render_static_copy_layer(
        (1080, 1350),
        _spec(runner_config),
        runner_config.font_dir,
        tmp_path / "first.png",
    )
    second = render_static_copy_layer(
        (1080, 1350),
        _spec(runner_config),
        runner_config.font_dir,
        tmp_path / "second.png",
    )

    assert _sha(first) == _sha(second)
    with Image.open(first) as layer:
        assert layer.size == (1080, 1350)
        assert layer.mode == "RGBA"
        assert layer.getbbox() is not None


def test_video_layers_are_transparent_png_timeline_inputs(
    tmp_path: Path, runner_config
):
    layers = render_video_copy_layers(
        (1280, 720),
        _spec(runner_config),
        runner_config.font_dir,
        tmp_path,
    )

    assert set(layers) == {"hook", "truth", "final"}
    assert len({_sha(path) for path in layers.values()}) == 3
    for path in layers.values():
        with Image.open(path) as layer:
            assert layer.size == (1280, 720)
            assert layer.mode == "RGBA"
            assert layer.getchannel("A").getextrema() == (0, 255)
