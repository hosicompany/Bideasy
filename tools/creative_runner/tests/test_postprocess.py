from __future__ import annotations

import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import bideasy_creative_runner.postprocess as postprocess_module
import pytest
from bideasy_creative_runner.copy_layers import CopySpec
from bideasy_creative_runner.postprocess import (
    CAMPAIGN_15S_TIMELINE,
    probe_video,
    process_image,
    process_video,
)
from PIL import Image


def _copy_spec() -> CopySpec:
    return CopySpec(
        hook="나라장터 공고 옆에서, 자격·A값·하한선을 한 번에.",
        body="보고 있는 공고 화면에서 확인 가능한 기준을 보여드립니다.",
        cta="이 공고 확인하기",
        endline="투찰 전 마지막 확인, BidEasy.",
        non_prediction_line="낙찰가는 예측하지 않습니다. 확인 가능한 기준부터 보여드립니다.",
        disclaimer="조달청·나라장터의 공식 또는 제휴 서비스가 아닌 민간 서비스",
        colors={
            "surface": "#FFFFFF",
            "ink": "#11151C",
            "muted": "#5A6472",
            "accent": "#2B50E0",
        },
    )


def test_image_derivatives_have_exact_dimensions_and_ui_is_deterministic(
    tmp_path: Path, runner_config
):
    background = tmp_path / "background.png"
    ui = tmp_path / "ui.png"
    Image.new("RGB", (400, 400), "#F2F4F6").save(background)
    Image.new("RGB", (100, 50), "#3182F6").save(ui)

    outputs = process_image(
        background,
        tmp_path,
        {
            "output_preset": "static_4_5",
            "composite_source_ui": True,
            "overlay_box": [0.25, 0.25, 0.5, 0.5],
        },
        copy_spec=_copy_spec(),
        font_dir=runner_config.font_dir,
        source_ui=ui,
    )
    assert [asset.kind for asset in outputs] == ["final_png", "webp"]
    with Image.open(tmp_path / "final.png") as image:
        assert image.size == (1080, 1350)
        assert image.mode == "RGB"
        assert image.getpixel((540, 675)) == (49, 130, 246)
    with Image.open(tmp_path / "final.webp") as image:
        assert image.size == (1080, 1350)


def test_blog_hero_image_remains_text_free_background(tmp_path: Path):
    background = tmp_path / "background.png"
    Image.new("RGB", (1376, 768), "#F2F4F6").save(background)

    outputs = process_image(
        background,
        tmp_path,
        {"output_preset": "blog_hero_16_9"},
    )

    assert outputs[0].metadata["approved_copy_composited"] is False
    with Image.open(tmp_path / "final.png") as image:
        assert image.size == (1376, 768)
        assert image.getbbox() == (0, 0, 1376, 768)
        assert image.getpixel((100, 100)) == (242, 244, 246)
        assert image.mode == "RGB"
    with Image.open(tmp_path / "final.webp") as image:
        assert image.size == (1376, 768)


def test_probe_video_uses_argv_without_shell_or_runner_token(
    tmp_path: Path, monkeypatch
):
    path = tmp_path / "sample.mp4"
    path.write_bytes(
        b"\x00\x00\x00\x0cftypisom\x00\x00\x00\x08moov\x00\x00\x00\x08mdat"
    )
    calls = []
    monkeypatch.setenv("CREATIVE_RUNNER_TOKEN", "must-not-reach-ffprobe")

    def fake_run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(
            args,
            0,
            '{"streams":[{"codec_type":"video","codec_name":"h264","pix_fmt":"yuv420p","width":1280,"height":720},'
            '{"codec_type":"audio","codec_name":"aac"}],"format":{"duration":"1.25"}}',
            "",
        )

    metadata = probe_video(path, ffprobe_bin="/fake/ffprobe", run_func=fake_run)
    assert metadata == {
        "width": 1280,
        "height": 720,
        "duration_ms": 1250,
        "video_codec": "h264",
        "audio_codec": "aac",
        "pixel_format": "yuv420p",
        "faststart": True,
    }
    assert isinstance(calls[0][0], list)
    assert "shell" not in calls[0][1]
    assert "CREATIVE_RUNNER_TOKEN" not in calls[0][1]["env"]


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg unavailable",
)
def test_video_derivatives_meet_codec_pixel_format_faststart_and_poster(
    tmp_path: Path, runner_config
):
    source = tmp_path / "source.mp4"
    voiceover = tmp_path / "voice.wav"
    source_ui = tmp_path / "source-ui.png"
    Image.new("RGB", (320, 180), "#FFFFFF").save(source_ui)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x3182F6:s=320x180:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            str(voiceover),
        ],
        check=True,
        capture_output=True,
    )
    outputs = process_video(
        source,
        tmp_path,
        {"output_preset": "video_1_1"},
        copy_spec=_copy_spec(),
        font_dir=runner_config.font_dir,
        voiceover=voiceover,
        source_ui=source_ui,
    )
    assert [asset.kind for asset in outputs] == ["mp4", "poster"]
    metadata = probe_video(tmp_path / "final.mp4")
    assert metadata["width"] == 1080
    assert metadata["height"] == 1080
    assert metadata["video_codec"] == "h264"
    assert metadata["pixel_format"] == "yuv420p"
    assert metadata["faststart"] is True
    assert (tmp_path / "poster.png").exists()


def _extract_frame(video: Path, timestamp: float, destination: Path) -> Image.Image:
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-ss",
            f"{timestamp:.3f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(destination),
        ],
        check=True,
        capture_output=True,
    )
    with Image.open(destination) as frame:
        frame.load()
        return frame.convert("RGB")


@pytest.mark.skipif(
    not shutil.which("ffmpeg") or not shutil.which("ffprobe"),
    reason="ffmpeg unavailable",
)
def test_campaign_video_has_exact_duration_and_frame_level_source_ui_timing(
    tmp_path: Path, runner_config, monkeypatch
):
    # Keep the integration test quick while exercising the exact production
    # filter graph. Production presets remain 1080x1920/1080x1080/1280x720.
    monkeypatch.setitem(postprocess_module._VIDEO_PRESETS, "video_1_1", (320, 320))
    source = tmp_path / "source.mp4"
    voiceover = tmp_path / "voice.wav"
    source_ui = tmp_path / "source-ui.png"
    Image.new("RGB", (320, 180), "#FF0000").save(source_ui)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=0x0000FF:s=320x180:r=30:d=1",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=channel_layout=stereo:sample_rate=48000",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(source),
        ],
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000:duration=1",
            str(voiceover),
        ],
        check=True,
        capture_output=True,
    )

    outputs = process_video(
        source,
        tmp_path,
        {
            "output_preset": "video_1_1",
            "source_ui_timeline": CAMPAIGN_15S_TIMELINE,
        },
        copy_spec=_copy_spec(),
        font_dir=runner_config.font_dir,
        voiceover=voiceover,
        source_ui=source_ui,
    )

    metadata = probe_video(tmp_path / "final.mp4")
    assert abs(metadata["duration_ms"] - 15_000) <= 100
    assert metadata["video_codec"] == "h264"
    assert metadata["pixel_format"] == "yuv420p"
    assert metadata["audio_codec"] == "aac"
    assert metadata["faststart"] is True
    assert outputs[0].metadata["source_ui_timeline"] == CAMPAIGN_15S_TIMELINE
    assert outputs[0].metadata["source_ui_timeline_seconds"] == {
        "hidden_hook": [0, 2],
        "context": [2, 5],
        "focused_results": [5, 13],
        "hidden_final": [13, 15],
    }
    assert outputs[1].metadata["source_time_ms"] == 7500

    frames = {
        second: _extract_frame(
            tmp_path / "final.mp4", second, tmp_path / f"frame-{second}.png"
        )
        for second in (1.0, 3.0, 7.0, 11.0, 14.0)
    }

    # The hook and final-card segments contain no source UI at the canvas
    # centre. Context (3s) and focused-result (7s/11s) segments do.
    hidden_hook = frames[1.0].getpixel((160, 160))
    context_ui = frames[3.0].getpixel((160, 160))
    focus_ui = frames[7.0].getpixel((160, 160))
    truth_ui = frames[11.0].getpixel((160, 160))
    hidden_final = frames[14.0].getpixel((160, 160))
    assert hidden_hook[2] > 180 and hidden_hook[0] < 80
    assert context_ui[0] > 180 and context_ui[2] < 80
    assert focus_ui[0] > 180 and focus_ui[2] < 80
    assert truth_ui[0] > 180 and truth_ui[2] < 80
    assert hidden_final[2] > 180 and hidden_final[0] < 80

    variant_b_dir = tmp_path / "variant-b"
    variant_b_dir.mkdir()
    process_video(
        source,
        variant_b_dir,
        {
            "output_preset": "video_1_1",
            "source_ui_timeline": CAMPAIGN_15S_TIMELINE,
        },
        copy_spec=replace(
            _copy_spec(), hook="이 공고, 우리 회사가 진짜 넣어도 될까요?"
        ),
        font_dir=runner_config.font_dir,
        voiceover=voiceover,
        source_ui=source_ui,
    )
    variant_b_frames = {
        second: _extract_frame(
            variant_b_dir / "final.mp4",
            second,
            variant_b_dir / f"frame-{second}.png",
        )
        for second in (1.0, 3.0, 7.0, 11.0, 14.0)
    }
    assert frames[1.0].tobytes() != variant_b_frames[1.0].tobytes()
    assert all(
        frames[second].tobytes() == variant_b_frames[second].tobytes()
        for second in (3.0, 7.0, 11.0, 14.0)
    )
