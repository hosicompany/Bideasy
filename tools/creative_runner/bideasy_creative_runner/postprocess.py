"""Deterministic image/video derivatives; no generative model touches product UI or copy."""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

from .assets import LocalAsset
from .copy_layers import CopySpec, render_static_copy_layer, render_video_copy_layers
from .errors import AssetError, ConfigurationError, InvalidJobError

_IMAGE_PRESETS = {
    "blog_hero_16_9": (1376, 768),
    "static_4_5": (1080, 1350),
    "static_1_1": (1080, 1080),
    "vertical_image": (1080, 1920),
}
_VIDEO_PRESETS = {
    "video_9_16": (1080, 1920),
    "video_16_9": (1280, 720),
    "video_1_1": (1080, 1080),
}

# Versioned, internal-only post-processing contract for the approved 15-second
# acquisition creative. The runner injects this value for
# ``marketing_studio_video`` jobs; it is never forwarded to Higgsfield.
CAMPAIGN_15S_TIMELINE = "campaign_15s_v1"
_CAMPAIGN_DURATION_SECONDS = 15.0
_CAMPAIGN_DURATION_TOLERANCE_MS = 100
_CAMPAIGN_FRAME_RATE = 30
_CAMPAIGN_CONTEXT_SECONDS = (2, 5)
_CAMPAIGN_FOCUS_SECONDS = (5, 13)
_CAMPAIGN_SOURCE_FOCUS_BOX = (0.58, 0.08, 0.40, 0.84)
_CAMPAIGN_FOCUS_OVERLAY_BOX = (0.05, 0.16, 0.90, 0.64)


def _media_env() -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "CREATIVE_RUNNER_TOKEN",
        "CREATIVE_RUNNER_TOKEN_CURRENT",
        "CREATIVE_RUNNER_TOKEN_PREVIOUS",
    ):
        env.pop(name, None)
    return env


@dataclass(frozen=True)
class ProcessedAsset:
    path: Path
    kind: str
    is_primary: bool
    metadata: dict[str, Any]


def _image_preset(params: dict[str, Any]) -> str:
    requested = str(params.get("output_preset") or "").strip()
    if requested:
        if requested not in _IMAGE_PRESETS:
            raise InvalidJobError(f"invalid image output_preset: {requested}")
        return requested
    aspect = str(params.get("aspect_ratio") or "16:9")
    return {
        "16:9": "blog_hero_16_9",
        "4:5": "static_4_5",
        "1:1": "static_1_1",
        "9:16": "vertical_image",
    }.get(aspect, "blog_hero_16_9")


def _video_preset(params: dict[str, Any]) -> str:
    requested = str(params.get("output_preset") or "").strip()
    if requested:
        if requested not in _VIDEO_PRESETS:
            raise InvalidJobError(f"invalid video output_preset: {requested}")
        return requested
    aspect = str(params.get("aspect_ratio") or "9:16")
    return {"16:9": "video_16_9", "1:1": "video_1_1", "9:16": "video_9_16"}.get(
        aspect, "video_9_16"
    )


def _load_rgb(path: Path) -> Image.Image:
    try:
        with Image.open(path) as source:
            source.load()
            if source.width * source.height > 100_000_000:
                raise AssetError("image exceeds 100 megapixels")
            if source.mode in {"RGBA", "LA"}:
                rgba = source.convert("RGBA")
                canvas = Image.new("RGB", rgba.size, "white")
                canvas.paste(rgba, mask=rgba.getchannel("A"))
                return canvas
            return source.convert("RGB")
    except (OSError, Image.DecompressionBombError) as exc:
        raise AssetError("image input is invalid") from exc


def _overlay_box(value: Any) -> tuple[float, float, float, float]:
    if value in (None, ""):
        return (0.42, 0.08, 0.54, 0.84)
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise InvalidJobError("overlay_box must be [x,y,width,height]")
    try:
        box = tuple(float(item) for item in value)
    except (TypeError, ValueError) as exc:
        raise InvalidJobError("overlay_box values must be numbers") from exc
    x, y, width, height = box
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 1 or y + height > 1:
        raise InvalidJobError(
            "overlay_box values must fit inside a normalised 0..1 canvas"
        )
    return box


def _campaign_timeline(params: dict[str, Any]) -> bool:
    value = params.get("source_ui_timeline")
    if value in (None, ""):
        return False
    if value != CAMPAIGN_15S_TIMELINE:
        raise InvalidJobError("invalid source_ui_timeline")
    return True


def _normalised_canvas_box(
    width: int,
    height: int,
    box: tuple[float, float, float, float],
) -> tuple[int, int, int, int]:
    x, y, box_width, box_height = box
    return (
        int(width * x),
        int(height * y),
        max(2, int(width * box_width)),
        max(2, int(height * box_height)),
    )


def process_image(
    source: Path,
    output_dir: Path,
    params: dict[str, Any],
    *,
    copy_spec: CopySpec | None = None,
    font_dir: Path | None = None,
    source_ui: Path | None = None,
) -> list[ProcessedAsset]:
    preset = _image_preset(params)
    width, height = _IMAGE_PRESETS[preset]
    image = ImageOps.fit(
        _load_rgb(source), (width, height), method=Image.Resampling.LANCZOS
    )

    if params.get("composite_source_ui") is True:
        if source_ui is None:
            raise InvalidJobError("composite_source_ui requires one source_ui image")
        overlay = _load_rgb(source_ui)
        x, y, box_width, box_height = _overlay_box(params.get("overlay_box"))
        target_width, target_height = int(width * box_width), int(height * box_height)
        overlay.thumbnail((target_width, target_height), Image.Resampling.LANCZOS)
        left = int(width * x + (target_width - overlay.width) / 2)
        top = int(height * y + (target_height - overlay.height) / 2)
        image.paste(overlay, (left, top))

    if copy_spec is not None:
        if font_dir is None:
            raise ConfigurationError(
                "font_dir is required for approved copy composition"
            )
        copy_layer_path = render_static_copy_layer(
            (width, height),
            copy_spec,
            font_dir,
            output_dir / "copy-static.png",
        )
        with Image.open(copy_layer_path) as copy_layer:
            composed = Image.alpha_composite(
                image.convert("RGBA"), copy_layer.convert("RGBA")
            )
        image = composed.convert("RGB")

    png_path = output_dir / "final.png"
    webp_path = output_dir / "final.webp"
    image.save(png_path, "PNG", optimize=True, compress_level=9)
    image.save(webp_path, "WEBP", quality=82, method=6)
    metadata = {
        "width": width,
        "height": height,
        "preset": preset,
        "color_mode": "RGB",
        "approved_copy_composited": copy_spec is not None,
    }
    return [
        ProcessedAsset(png_path, "final_png", True, metadata),
        ProcessedAsset(webp_path, "webp", False, {**metadata, "quality": 82}),
    ]


def _run_checked(
    args: Sequence[str],
    *,
    timeout: float,
    run_func: Callable[..., subprocess.CompletedProcess[str]],
    heartbeat: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess[str]:
    try:
        if heartbeat is not None and run_func is subprocess.run:
            process = subprocess.Popen(
                list(args),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                env=_media_env(),
            )
            deadline = time.monotonic() + timeout
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(
                        list(args), timeout, output=stdout, stderr=stderr
                    )
                try:
                    stdout, stderr = process.communicate(timeout=min(30.0, remaining))
                    result = subprocess.CompletedProcess(
                        list(args), process.returncode or 0, stdout, stderr
                    )
                    break
                except subprocess.TimeoutExpired:
                    try:
                        heartbeat()
                    except Exception:
                        process.kill()
                        process.communicate()
                        raise
        else:
            result = run_func(
                list(args),
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
                env=_media_env(),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise AssetError(f"media command failed to execute: {args[0]}") from exc
    if result.returncode != 0:
        message = (
            (result.stderr or result.stdout or "media command failed")
            .strip()
            .splitlines()[-1]
        )
        raise AssetError(message[:500])
    return result


def probe_video(
    path: Path,
    *,
    ffprobe_bin: str = "ffprobe",
    run_func: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    heartbeat: Callable[[], None] | None = None,
) -> dict[str, Any]:
    if shutil.which(ffprobe_bin) is None and Path(ffprobe_bin).name == ffprobe_bin:
        raise ConfigurationError("ffprobe is required for creative video processing")
    result = _run_checked(
        [
            ffprobe_bin,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(path),
        ],
        timeout=30,
        run_func=run_func,
        heartbeat=heartbeat,
    )
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise AssetError("ffprobe returned invalid JSON") from exc
    streams = payload.get("streams") if isinstance(payload, dict) else None
    if not isinstance(streams, list):
        raise AssetError("ffprobe returned no streams")
    video = next(
        (stream for stream in streams if stream.get("codec_type") == "video"), None
    )
    audio = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"), None
    )
    if not video:
        raise AssetError("video file has no video stream")
    duration_raw = (
        (payload.get("format") or {}).get("duration") or video.get("duration") or 0
    )
    try:
        duration_ms = max(0, round(float(duration_raw) * 1000))
    except (TypeError, ValueError):
        duration_ms = 0
    return {
        "width": int(video.get("width") or 0),
        "height": int(video.get("height") or 0),
        "duration_ms": duration_ms,
        "video_codec": video.get("codec_name"),
        "audio_codec": audio.get("codec_name") if audio else None,
        "pixel_format": video.get("pix_fmt"),
        "faststart": mp4_has_faststart(path),
    }


def mp4_has_faststart(path: Path) -> bool:
    offsets: dict[bytes, int] = {}
    try:
        with path.open("rb") as handle:
            offset = 0
            file_size = path.stat().st_size
            while offset + 8 <= file_size:
                header = handle.read(8)
                if len(header) != 8:
                    break
                size, kind = struct.unpack(">I4s", header)
                header_size = 8
                if size == 1:
                    large_size = handle.read(8)
                    if len(large_size) != 8:
                        break
                    size = struct.unpack(">Q", large_size)[0]
                    header_size = 16
                elif size == 0:
                    size = file_size - offset
                if size < header_size:
                    break
                if kind in {b"moov", b"mdat"}:
                    offsets.setdefault(kind, offset)
                    if len(offsets) == 2:
                        break
                offset += size
                handle.seek(offset)
    except OSError:
        return False
    return (
        b"moov" in offsets
        and b"mdat" in offsets
        and offsets[b"moov"] < offsets[b"mdat"]
    )


def process_video(
    source: Path,
    output_dir: Path,
    params: dict[str, Any],
    *,
    copy_spec: CopySpec | None = None,
    font_dir: Path | None = None,
    voiceover: Path | None = None,
    source_ui: Path | None = None,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
    run_func: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    heartbeat: Callable[[], None] | None = None,
) -> list[ProcessedAsset]:
    if shutil.which(ffmpeg_bin) is None and Path(ffmpeg_bin).name == ffmpeg_bin:
        raise ConfigurationError("ffmpeg is required for creative video processing")
    source_metadata = probe_video(
        source,
        ffprobe_bin=ffprobe_bin,
        run_func=run_func,
        heartbeat=heartbeat,
    )
    preset = _video_preset(params)
    width, height = _VIDEO_PRESETS[preset]
    campaign_timeline = _campaign_timeline(params)
    if campaign_timeline and (
        copy_spec is None or source_ui is None or voiceover is None
    ):
        raise InvalidJobError(
            "campaign_15s_v1 requires approved copy, source_ui, and voiceover"
        )
    final_path = output_dir / "final.mp4"
    poster_path = output_dir / "poster.png"
    video_filter = (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},setsar=1"
    )
    if campaign_timeline:
        video_filter = (
            f"{video_filter},setpts=PTS-STARTPTS,fps={_CAMPAIGN_FRAME_RATE},"
            f"tpad=stop_mode=clone:stop_duration={_CAMPAIGN_DURATION_SECONDS:g},"
            f"trim=duration={_CAMPAIGN_DURATION_SECONDS:g}"
        )

    copy_layers: dict[str, Path] = {}
    if copy_spec is not None:
        if font_dir is None:
            raise ConfigurationError(
                "font_dir is required for approved copy composition"
            )
        copy_layers = render_video_copy_layers(
            (width, height), copy_spec, font_dir, output_dir
        )
    args = [ffmpeg_bin, "-y", "-i", str(source)]
    next_input_index = 1
    source_ui_index: int | None = None
    if source_ui:
        source_ui_index = next_input_index
        next_input_index += 1
        if source_ui.suffix.lower() in {".png", ".jpg", ".jpeg", ".webp"}:
            args.extend(["-loop", "1"])
        args.extend(["-i", str(source_ui)])
    voiceover_index: int | None = None
    if voiceover:
        voiceover_index = next_input_index
        next_input_index += 1
        args.extend(["-i", str(voiceover)])
    copy_indexes: dict[str, int] = {}
    for name in copy_layers:
        copy_indexes[name] = next_input_index
        next_input_index += 1
        args.extend(["-loop", "1", "-i", str(copy_layers[name])])

    filters: list[str] = []
    current_label: str | None = None
    if source_ui_index is not None or copy_layers:
        filters.append(f"[0:v]{video_filter}[base]")
        current_label = "base"
    if source_ui_index is not None and current_label is not None and campaign_timeline:
        context_left, context_top, context_width, context_height = (
            _normalised_canvas_box(
                width, height, _overlay_box(params.get("overlay_box"))
            )
        )
        focus_left, focus_top, focus_width, focus_height = _normalised_canvas_box(
            width, height, _CAMPAIGN_FOCUS_OVERLAY_BOX
        )
        focus_x, focus_y, focus_crop_width, focus_crop_height = (
            _CAMPAIGN_SOURCE_FOCUS_BOX
        )
        filters.extend(
            [
                (
                    f"[{source_ui_index}:v]setpts=PTS-STARTPTS,"
                    f"tpad=stop_mode=clone:stop_duration={_CAMPAIGN_DURATION_SECONDS:g},"
                    "split=2[ui_context_input][ui_focus_input]"
                ),
                (
                    f"[ui_context_input]format=rgba,scale={context_width}:{context_height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={context_width}:{context_height}:(ow-iw)/2:(oh-ih)/2:"
                    "color=0x00000000,"
                    f"fade=t=in:st={_CAMPAIGN_CONTEXT_SECONDS[0]}:d=0.35:alpha=1"
                    "[ui_context]"
                ),
                (
                    "[ui_focus_input]"
                    f"crop=iw*{focus_crop_width:g}:ih*{focus_crop_height:g}:"
                    f"iw*{focus_x:g}:ih*{focus_y:g},format=rgba,"
                    f"scale={focus_width}:{focus_height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={focus_width}:{focus_height}:(ow-iw)/2:(oh-ih)/2:"
                    "color=0x00000000[ui_focus]"
                ),
                (
                    f"[{current_label}][ui_context]overlay={context_left}:{context_top}:"
                    f"enable='gte(t,{_CAMPAIGN_CONTEXT_SECONDS[0]})*"
                    f"lt(t,{_CAMPAIGN_CONTEXT_SECONDS[1]})':"
                    "eof_action=pass[with_ui_context]"
                ),
                (
                    f"[with_ui_context][ui_focus]overlay={focus_left}:{focus_top}:"
                    f"enable='gte(t,{_CAMPAIGN_FOCUS_SECONDS[0]})*"
                    f"lt(t,{_CAMPAIGN_FOCUS_SECONDS[1]})':"
                    "eof_action=pass[with_ui]"
                ),
            ]
        )
        current_label = "with_ui"
    elif source_ui_index is not None and current_label is not None:
        x, y, box_width, box_height = _overlay_box(params.get("overlay_box"))
        target_width, target_height = int(width * box_width), int(height * box_height)
        left, top = int(width * x), int(height * y)
        filters.extend(
            [
                (
                    f"[{source_ui_index}:v]scale={target_width}:{target_height}:"
                    "force_original_aspect_ratio=decrease[ui]"
                ),
                f"[{current_label}][ui]overlay={left}:{top}:eof_action=pass[with_ui]",
            ]
        )
        current_label = "with_ui"
    timeline = (("hook", 0, 2), ("truth", 10, 13), ("final", 13, 15))
    for name, start, end in timeline if copy_layers else ():
        image_label = f"copy_{name}"
        output_label = f"with_{name}"
        filters.extend(
            [
                f"[{copy_indexes[name]}:v]format=rgba[{image_label}]",
                (
                    f"[{current_label}][{image_label}]overlay=0:0:"
                    f"enable='gte(t,{start})*lt(t,{end})':"
                    f"eof_action=pass[{output_label}]"
                ),
            ]
        )
        current_label = output_label
    audio_label: str | None = None
    if campaign_timeline and voiceover_index is not None:
        audio_label = "campaign_audio"
        filters.append(
            f"[{voiceover_index}:a]apad=pad_dur={_CAMPAIGN_DURATION_SECONDS:g},"
            f"atrim=duration={_CAMPAIGN_DURATION_SECONDS:g},"
            f"asetpts=PTS-STARTPTS[{audio_label}]"
        )
    if current_label is not None:
        args.extend(
            ["-filter_complex", ";".join(filters), "-map", f"[{current_label}]"]
        )
    else:
        args.extend(["-map", "0:v:0", "-vf", video_filter])
    if audio_label is not None:
        args.extend(["-map", f"[{audio_label}]"])
    elif voiceover:
        args.extend(["-map", f"{voiceover_index}:a:0"])
    else:
        args.extend(["-map", "0:a?"])
    if campaign_timeline:
        args.extend(["-t", f"{_CAMPAIGN_DURATION_SECONDS:.3f}"])
    elif source_metadata["duration_ms"]:
        args.extend(["-t", f"{source_metadata['duration_ms'] / 1000:.3f}"])
    args.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
        ]
    )
    if campaign_timeline:
        args.extend(
            [
                "-force_key_frames",
                "0,2,5,10,13",
                "-x264-params",
                "scenecut=0",
            ]
        )
    args.append(str(final_path))
    _run_checked(args, timeout=900, run_func=run_func, heartbeat=heartbeat)
    final_metadata = probe_video(
        final_path,
        ffprobe_bin=ffprobe_bin,
        run_func=run_func,
        heartbeat=heartbeat,
    )
    if (
        final_metadata["width"] != width
        or final_metadata["height"] != height
        or final_metadata["video_codec"] != "h264"
        or final_metadata["pixel_format"] != "yuv420p"
        or not final_metadata["faststart"]
    ):
        raise AssetError(
            "deterministic MP4 failed its codec, dimensions, pixel format, or faststart contract"
        )
    if final_metadata["audio_codec"] != "aac":
        raise AssetError("representative video must contain an AAC audio track")
    if (
        campaign_timeline
        and abs(
            final_metadata["duration_ms"] - round(_CAMPAIGN_DURATION_SECONDS * 1000)
        )
        > _CAMPAIGN_DURATION_TOLERANCE_MS
    ):
        raise AssetError("campaign MP4 must be exactly 15 seconds")

    midpoint = (
        7.5
        if campaign_timeline
        else (
            min(1.0, (source_metadata["duration_ms"] / 1000) / 2)
            if source_metadata["duration_ms"]
            else 0.0
        )
    )
    _run_checked(
        [
            ffmpeg_bin,
            "-y",
            "-ss",
            f"{midpoint:.3f}",
            "-i",
            str(final_path),
            "-frames:v",
            "1",
            "-vf",
            f"scale={width}:-2",
            str(poster_path),
        ],
        timeout=60,
        run_func=run_func,
        heartbeat=heartbeat,
    )
    with Image.open(poster_path) as poster:
        poster_metadata = {
            "width": poster.width,
            "height": poster.height,
            "source_time_ms": round(midpoint * 1000),
        }

    return [
        ProcessedAsset(
            final_path,
            "mp4",
            True,
            {
                **final_metadata,
                "preset": preset,
                "approved_copy_composited": copy_spec is not None,
                "source_ui_timeline": (
                    CAMPAIGN_15S_TIMELINE if campaign_timeline else None
                ),
                "source_ui_timeline_seconds": (
                    {
                        "hidden_hook": [0, 2],
                        "context": [2, 5],
                        "focused_results": [5, 13],
                        "hidden_final": [13, 15],
                    }
                    if campaign_timeline
                    else None
                ),
                "source_ui_focus_box_normalized": (
                    list(_CAMPAIGN_SOURCE_FOCUS_BOX) if campaign_timeline else None
                ),
                "copy_timeline_seconds": (
                    {
                        "hook": [0, 2],
                        "non_prediction": [10, 13],
                        "endline_cta": [13, 15],
                    }
                    if copy_spec is not None
                    else None
                ),
            },
        ),
        ProcessedAsset(poster_path, "poster", False, poster_metadata),
    ]


def find_role(inputs: Sequence[LocalAsset], role: str, mime_prefix: str) -> Path | None:
    matches = [
        asset.path
        for asset in inputs
        if asset.role == role and asset.mime_type.startswith(mime_prefix)
    ]
    if len(matches) > 1:
        raise InvalidJobError(
            f"only one {role} {mime_prefix.rstrip('/')} input is allowed"
        )
    return matches[0] if matches else None
