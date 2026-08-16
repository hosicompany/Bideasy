"""Deterministic, non-publishable 15-second prevoice storyboards and previews.

This module never calls Higgsfield.  It renders one provider-safe, text-free
motion board plus internal A/B review assets.  Internal frames use an explicit
wireframe instead of pretending that an outdated screenshot is current UI.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .copy_layers import (
    CopySpec,
    render_video_copy_layers,
    validate_font_dir,
    wrap_text,
)
from .postprocess import probe_video


class PrevoiceValidationError(ValueError):
    """The preproduction spec no longer matches the approved brand contract."""


_FONT_FILES = {
    "regular": "Pretendard-Regular.otf",
    "medium": "Pretendard-Medium.otf",
    "bold": "Pretendard-Bold.otf",
}
_EXPECTED_TIMELINE = (
    ("hook", 0, 2000),
    ("workflow", 2000, 5000),
    ("evidence", 5000, 10000),
    ("non_prediction", 10000, 13000),
    ("endcard", 13000, 15000),
)
_CANVAS = (1080, 1920)
_REVIEW_BOARD = (1920, 1080)


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PrevoiceValidationError(f"{label} JSON을 읽을 수 없어요") from exc
    if not isinstance(payload, dict):
        raise PrevoiceValidationError(f"{label}는 JSON object여야 해요")
    return payload


def _required_dict(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise PrevoiceValidationError(f"{label}가 없거나 object가 아니에요")
    return value


def validate_preproduction_spec(
    spec_path: Path,
    brand_policy_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fail closed when copy, timing, notice provenance, or queue gates drift."""
    spec = _load_json(spec_path, "preproduction spec")
    brand = _load_json(brand_policy_path, "brand policy")
    message = _required_dict(brand.get("message"), "brand.message")
    brand_data = _required_dict(brand.get("brand"), "brand.brand")
    shared = _required_dict(spec.get("shared_copy"), "shared_copy")

    expected_shared = {
        "body": message.get("description"),
        "non_prediction": message.get("video_non_prediction_line"),
        "cta": message.get("cta"),
        "endline": message.get("endline"),
        "disclaimer": brand_data.get("official_relationship_disclaimer"),
    }
    if shared != expected_shared:
        raise PrevoiceValidationError("공유 카피가 CREATIVE_BRAND_KIT 정본과 달라요")

    variants = spec.get("variants")
    expected_variants = [
        {"id": "A", "hook": message.get("acquisition_default")},
        {"id": "B", "hook": message.get("test_variant_b")},
    ]
    if variants != expected_variants:
        raise PrevoiceValidationError(
            "A/B hook이 브랜드 정본과 다르거나 순서가 바뀌었어요"
        )

    timeline = spec.get("timeline")
    if not isinstance(timeline, list) or len(timeline) != len(_EXPECTED_TIMELINE):
        raise PrevoiceValidationError("15초 timeline은 다섯 장면이어야 해요")
    actual_timeline = tuple(
        (
            item.get("scene"),
            item.get("start_ms"),
            item.get("end_ms"),
        )
        for item in timeline
        if isinstance(item, dict)
    )
    if actual_timeline != _EXPECTED_TIMELINE:
        raise PrevoiceValidationError("timeline은 0/2/5/10/13/15초 경계를 지켜야 해요")

    acceptance = _required_dict(spec.get("acceptance"), "acceptance")
    if (
        spec.get("publishable") is not False
        or acceptance.get("duration_ms") != 15000
        or spec.get("status") != "PREVOICE_READY_SOURCE_UI_REQUIRED"
    ):
        raise PrevoiceValidationError("프리비즈는 15초·비게시·입력 대기 상태여야 해요")

    notice = _required_dict(spec.get("notice"), "notice")
    source = str(notice.get("official_source") or "")
    parsed = urlsplit(source)
    if (
        parsed.scheme != "https"
        or (parsed.hostname or "").lower() != "www.g2b.go.kr"
        or notice.get("bid_no") != "R26BK01488342-000"
    ):
        raise PrevoiceValidationError("공고 사례는 고정된 공식 G2B 원문이어야 해요")

    source_ui = _required_dict(spec.get("source_ui"), "source_ui")
    voice = _required_dict(spec.get("voice"), "voice")
    if (
        source_ui.get("status") != "REQUIRED_NEW_CAPTURE"
        or voice.get("status") != "REQUIRED_NOT_UPLOADED"
        or voice.get("generated_audio") is not False
    ):
        raise PrevoiceValidationError(
            "실제 화면·대표 음성의 blocking gate가 약해졌어요"
        )

    higgsfield = _required_dict(spec.get("higgsfield"), "higgsfield")
    params = _required_dict(higgsfield.get("params"), "higgsfield.params")
    if (
        higgsfield.get("cli_version") != "1.1.23"
        or higgsfield.get("job_type") != "marketing_studio_video"
        or params.get("specific_mode") != "from_storyboard"
        or params.get("aspect_ratio") != "9:16"
        or params.get("resolution") != "1080p"
        or params.get("duration") != 15
        or params.get("generate_audio") is not False
        or params.get("composite_source_ui") is not True
        or params.get("source_ui_timeline") != "campaign_15s_v1"
        or higgsfield.get("paid_generation_status") != "NOT_STARTED"
    ):
        raise PrevoiceValidationError("Higgsfield 15초 무음·후합성 계약이 달라졌어요")

    prompt = str(higgsfield.get("prompt") or "")
    copy_texts = [
        *(str(item["hook"]) for item in expected_variants),
        *(str(value) for value in shared.values()),
        str(voice.get("shared_script") or ""),
    ]
    prohibited = brand.get("prohibited_claims")
    if not isinstance(prohibited, list):
        raise PrevoiceValidationError("금지 주장 목록을 찾을 수 없어요")
    if any(claim in text for claim in prohibited for text in copy_texts):
        raise PrevoiceValidationError("승인 카피에 금지 주장이 포함됐어요")
    if any(text in prompt for text in copy_texts if text):
        raise PrevoiceValidationError("provider prompt에 실제 한글 카피가 들어갔어요")
    return spec, brand


def _font(font_dir: Path, weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(font_dir / _FONT_FILES[weight]), size=size)


def _rgb(colors: dict[str, str], key: str) -> tuple[int, int, int]:
    value = colors.get(key)
    if not isinstance(value, str):
        raise PrevoiceValidationError(f"브랜드 색상이 없어요: {key}")
    return ImageColor.getrgb(value)


def _draw_text_block(
    draw: ImageDraw.ImageDraw,
    text: str,
    *,
    font: ImageFont.FreeTypeFont,
    box: tuple[int, int, int, int],
    fill: tuple[int, int, int],
    max_lines: int,
    spacing: int = 12,
    align: str = "left",
) -> None:
    left, top, right, _bottom = box
    lines = wrap_text(draw, text, font, right - left, max_lines)
    line_height = font.getbbox("가Ag")[3] - font.getbbox("가Ag")[1]
    y = top
    for line in lines:
        width = draw.textbbox((0, 0), line, font=font)[2]
        x = left if align == "left" else left + (right - left - width) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + spacing


def _draw_previs_mark(
    draw: ImageDraw.ImageDraw,
    size: tuple[int, int],
    font_dir: Path,
    colors: dict[str, str],
) -> None:
    width, height = size
    bar_height = max(58, round(height * 0.038))
    draw.rectangle((0, 0, width, bar_height), fill=_rgb(colors, "danger"))
    label = "PREVIZ · 실제 UI/음성 교체 전 · 게시 금지"
    font = _font(font_dir, "bold", max(18, round(width * 0.026)))
    text_width = draw.textbbox((0, 0), label, font=font)[2]
    draw.text(
        ((width - text_width) // 2, max(8, (bar_height - font.size) // 2 - 2)),
        label,
        font=font,
        fill=_rgb(colors, "surface"),
    )


def _draw_product_wireframe(
    draw: ImageDraw.ImageDraw,
    size: tuple[int, int],
    font_dir: Path,
    colors: dict[str, str],
    *,
    evidence: bool,
    facts: dict[str, Any],
) -> None:
    width, height = size
    margin = round(width * 0.055)
    top = round(height * 0.25)
    bottom = round(height * 0.79)
    radius = max(24, round(width * 0.03))
    draw.rounded_rectangle(
        (margin, top, width - margin, bottom),
        radius=radius,
        fill=_rgb(colors, "surface"),
        outline=_rgb(colors, "muted"),
        width=max(2, round(width * 0.003)),
    )
    chrome_h = round(height * 0.045)
    draw.rounded_rectangle(
        (margin, top, width - margin, top + chrome_h),
        radius=radius,
        fill=_rgb(colors, "accent_soft"),
    )
    dot = max(6, round(width * 0.008))
    for index, key in enumerate(("danger", "warn", "safe")):
        cx = margin + 28 + index * (dot * 3)
        cy = top + chrome_h // 2
        draw.ellipse((cx - dot, cy - dot, cx + dot, cy + dot), fill=_rgb(colors, key))

    inner_top = top + chrome_h + round(height * 0.025)
    split = round(width * 0.61)
    draw.rounded_rectangle(
        (margin + 22, inner_top, split - 12, bottom - 22),
        radius=18,
        fill=_rgb(colors, "canvas"),
    )
    draw.rounded_rectangle(
        (split + 8, inner_top, width - margin - 22, bottom - 22),
        radius=18,
        fill=_rgb(colors, "accent_soft"),
    )
    title_font = _font(font_dir, "bold", max(24, round(width * 0.032)))
    body_font = _font(font_dir, "regular", max(20, round(width * 0.025)))
    small_font = _font(font_dir, "medium", max(17, round(width * 0.021)))
    _draw_text_block(
        draw,
        "실제 공개 전기공사 G2B 화면 삽입 위치",
        font=title_font,
        box=(margin + 48, inner_top + 44, split - 42, inner_top + 160),
        fill=_rgb(colors, "ink"),
        max_lines=3,
    )
    _draw_text_block(
        draw,
        "실제 BidEasy 사이드패널 삽입 위치",
        font=title_font,
        box=(split + 38, inner_top + 44, width - margin - 45, inner_top + 175),
        fill=_rgb(colors, "accent"),
        max_lines=3,
    )

    if evidence:
        cards = (
            ("참가자격", str(facts["qualification"])),
            ("A값", f"{int(facts['a_value_krw']):,}원"),
            ("하한율", f"{float(facts['lower_bound_rate_percent']):.3f}%"),
        )
        card_left = margin + 48
        card_right = width - margin - 48
        card_top = round(height * 0.48)
        card_h = round(height * 0.075)
        gap = round(height * 0.018)
        for index, (label, value) in enumerate(cards):
            y = card_top + index * (card_h + gap)
            draw.rounded_rectangle(
                (card_left, y, card_right, y + card_h),
                radius=16,
                fill=_rgb(colors, "surface"),
                outline=_rgb(colors, "accent"),
                width=3,
            )
            draw.text(
                (card_left + 24, y + 18),
                label,
                font=small_font,
                fill=_rgb(colors, "muted"),
            )
            value_width = draw.textbbox((0, 0), value, font=body_font)[2]
            draw.text(
                (card_right - 24 - value_width, y + 16),
                value,
                font=body_font,
                fill=_rgb(colors, "ink"),
            )
        note = "스토리보드 주석 · 최종본은 실제 UI 픽셀로 교체"
    else:
        note = "와이어프레임 · 실제 UI가 아님"
    note_width = draw.textbbox((0, 0), note, font=small_font)[2]
    draw.text(
        ((width - note_width) // 2, bottom + 22),
        note,
        font=small_font,
        fill=_rgb(colors, "danger"),
    )


def render_review_scene(
    spec: dict[str, Any],
    brand: dict[str, Any],
    variant: dict[str, str],
    scene: str,
    font_dir: Path,
    *,
    size: tuple[int, int] = _CANVAS,
) -> Image.Image:
    visual = _required_dict(brand.get("visual"), "brand.visual")
    colors = _required_dict(visual.get("colors"), "brand.visual.colors")
    shared = _required_dict(spec.get("shared_copy"), "shared_copy")
    notice = _required_dict(spec.get("notice"), "notice")
    facts = _required_dict(notice.get("facts"), "notice.facts")
    width, height = size
    image = Image.new("RGB", size, _rgb(colors, "canvas"))
    draw = ImageDraw.Draw(image)
    _draw_previs_mark(draw, size, font_dir, colors)
    margin = round(width * 0.065)
    ink = _rgb(colors, "ink")
    muted = _rgb(colors, "muted")
    accent = _rgb(colors, "accent")
    surface = _rgb(colors, "surface")

    if scene == "hook":
        draw.rounded_rectangle(
            (margin, round(height * 0.23), width - margin, round(height * 0.68)),
            radius=max(28, round(width * 0.04)),
            fill=surface,
        )
        draw.rectangle(
            (
                margin + 42,
                round(height * 0.28),
                margin + round(width * 0.18),
                round(height * 0.29),
            ),
            fill=accent,
        )
        _draw_text_block(
            draw,
            variant["hook"],
            font=_font(font_dir, "bold", round(width * 0.075)),
            box=(
                margin + 42,
                round(height * 0.34),
                width - margin - 42,
                round(height * 0.62),
            ),
            fill=ink,
            max_lines=4,
            spacing=20,
        )
        label = f"메시지 {variant['id']} · 유일한 A/B 차이"
        draw.text(
            (margin + 42, round(height * 0.62)),
            label,
            font=_font(font_dir, "medium", round(width * 0.032)),
            fill=muted,
        )
    elif scene == "workflow":
        _draw_product_wireframe(
            draw, size, font_dir, colors, evidence=False, facts=facts
        )
        _draw_text_block(
            draw,
            shared["body"],
            font=_font(font_dir, "medium", round(width * 0.038)),
            box=(margin, round(height * 0.84), width - margin, round(height * 0.94)),
            fill=ink,
            max_lines=3,
            spacing=10,
            align="center",
        )
    elif scene == "evidence":
        _draw_product_wireframe(
            draw, size, font_dir, colors, evidence=True, facts=facts
        )
        caption = str(spec.get("caption") or "")
        _draw_text_block(
            draw,
            caption,
            font=_font(font_dir, "regular", round(width * 0.024)),
            box=(margin, round(height * 0.84), width - margin, round(height * 0.96)),
            fill=muted,
            max_lines=4,
            spacing=7,
            align="center",
        )
    elif scene == "non_prediction":
        draw.rounded_rectangle(
            (margin, round(height * 0.32), width - margin, round(height * 0.69)),
            radius=max(28, round(width * 0.04)),
            fill=ink,
        )
        _draw_text_block(
            draw,
            shared["non_prediction"],
            font=_font(font_dir, "bold", round(width * 0.061)),
            box=(
                margin + 48,
                round(height * 0.41),
                width - margin - 48,
                round(height * 0.62),
            ),
            fill=surface,
            max_lines=4,
            spacing=18,
            align="center",
        )
    elif scene == "endcard":
        image = Image.new("RGB", size, accent)
        draw = ImageDraw.Draw(image)
        _draw_previs_mark(draw, size, font_dir, colors)
        _draw_text_block(
            draw,
            shared["endline"],
            font=_font(font_dir, "bold", round(width * 0.064)),
            box=(margin, round(height * 0.28), width - margin, round(height * 0.48)),
            fill=surface,
            max_lines=3,
            spacing=18,
            align="center",
        )
        cta_top = round(height * 0.54)
        cta_bottom = round(height * 0.64)
        draw.rounded_rectangle(
            (margin, cta_top, width - margin, cta_bottom),
            radius=max(24, round(width * 0.035)),
            fill=surface,
        )
        cta_font = _font(font_dir, "bold", round(width * 0.045))
        cta_width = draw.textbbox((0, 0), shared["cta"], font=cta_font)[2]
        draw.text(
            ((width - cta_width) // 2, cta_top + round(height * 0.024)),
            shared["cta"],
            font=cta_font,
            fill=accent,
        )
        _draw_text_block(
            draw,
            shared["disclaimer"],
            font=_font(font_dir, "regular", round(width * 0.027)),
            box=(margin, round(height * 0.82), width - margin, round(height * 0.91)),
            fill=surface,
            max_lines=2,
            spacing=8,
            align="center",
        )
    else:
        raise PrevoiceValidationError(f"알 수 없는 storyboard scene이에요: {scene}")
    return image


def render_provider_storyboard(
    brand: dict[str, Any],
    destination: Path,
) -> Path:
    """Render five left-to-right, text-free motion beats for Higgsfield."""
    colors = _required_dict(
        _required_dict(brand.get("visual"), "brand.visual").get("colors"),
        "brand.visual.colors",
    )
    width, height = _REVIEW_BOARD
    canvas = Image.new("RGB", (width, height), _rgb(colors, "canvas"))
    draw = ImageDraw.Draw(canvas)
    margin = 54
    gap = 28
    panel_width = (width - 2 * margin - 4 * gap) // 5
    panel_height = round(panel_width * 16 / 9)
    top = (height - panel_height) // 2
    for index in range(5):
        left = margin + index * (panel_width + gap)
        right = left + panel_width
        bottom = top + panel_height
        base = "surface" if index < 4 else "accent"
        draw.rounded_rectangle(
            (left, top, right, bottom),
            radius=24,
            fill=_rgb(colors, base),
        )
        if index == 0:
            draw.rounded_rectangle(
                (left + 38, top + 56, right - 38, top + 185),
                radius=20,
                fill=_rgb(colors, "accent_soft"),
            )
        elif index in {1, 2}:
            y = top + 205 if index == 1 else top + 170
            draw.rounded_rectangle(
                (left + 28, y, right - 28, y + 220),
                radius=18,
                fill=_rgb(colors, "accent_soft"),
                outline=_rgb(colors, "accent"),
                width=3,
            )
            if index == 2:
                for offset in range(3):
                    card_y = y + 28 + offset * 57
                    draw.rounded_rectangle(
                        (left + 50, card_y, right - 50, card_y + 36),
                        radius=10,
                        fill=_rgb(colors, "surface"),
                    )
        elif index == 3:
            draw.rounded_rectangle(
                (left + 32, top + 285, right - 32, top + 435),
                radius=22,
                fill=_rgb(colors, "ink"),
            )
        else:
            draw.rounded_rectangle(
                (left + 36, top + 260, right - 36, top + 338),
                radius=20,
                fill=_rgb(colors, "surface"),
            )
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, "PNG", optimize=True, compress_level=9)
    return destination


def render_review_storyboard(
    spec: dict[str, Any],
    brand: dict[str, Any],
    variant: dict[str, str],
    font_dir: Path,
    destination: Path,
) -> Path:
    width, height = _REVIEW_BOARD
    colors = _required_dict(
        _required_dict(brand.get("visual"), "brand.visual").get("colors"),
        "brand.visual.colors",
    )
    board = Image.new("RGB", (width, height), _rgb(colors, "canvas"))
    draw = ImageDraw.Draw(board)
    title_font = _font(font_dir, "bold", 36)
    detail_font = _font(font_dir, "medium", 19)
    title = f"BidEasy 15초 메시지 {variant['id']} · 사람 검수용"
    draw.text((48, 30), title, font=title_font, fill=_rgb(colors, "ink"))
    draw.text(
        (48, 78),
        "PREVIZ · provider 업로드 금지 · 실제 UI/대표 음성 교체 전",
        font=detail_font,
        fill=_rgb(colors, "danger"),
    )

    margin = 48
    gap = 26
    panel_width = (width - 2 * margin - 4 * gap) // 5
    panel_height = round(panel_width * 16 / 9)
    top = 168
    labels = ("0–2초", "2–5초", "5–10초", "10–13초", "13–15초")
    for index, (scene, _start, _end) in enumerate(_EXPECTED_TIMELINE):
        left = margin + index * (panel_width + gap)
        frame = render_review_scene(
            spec, brand, variant, scene, font_dir, size=(540, 960)
        ).resize((panel_width, panel_height), Image.Resampling.LANCZOS)
        board.paste(frame, (left, top))
        label_width = draw.textbbox((0, 0), labels[index], font=detail_font)[2]
        draw.text(
            (left + (panel_width - label_width) // 2, top - 35),
            labels[index],
            font=detail_font,
            fill=_rgb(colors, "muted"),
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    board.save(destination, "PNG", optimize=True, compress_level=9)
    return destination


def _render_silent_preview(
    spec: dict[str, Any],
    brand: dict[str, Any],
    variant: dict[str, str],
    font_dir: Path,
    destination: Path,
    *,
    ffmpeg_bin: str,
    ffprobe_bin: str,
) -> dict[str, Any]:
    if shutil.which(ffmpeg_bin) is None and Path(ffmpeg_bin).name == ffmpeg_bin:
        raise PrevoiceValidationError("ffmpeg이 없어 무음 프리비즈를 만들 수 없어요")
    with tempfile.TemporaryDirectory(prefix="bideasy-prevoice-") as temp_name:
        temp_dir = Path(temp_name)
        frame_paths: list[Path] = []
        durations: list[float] = []
        for scene, start, end in _EXPECTED_TIMELINE:
            path = temp_dir / f"{scene}.png"
            render_review_scene(spec, brand, variant, scene, font_dir).save(
                path, "PNG", optimize=True, compress_level=6
            )
            frame_paths.append(path)
            durations.append((end - start) / 1000)

        args = [ffmpeg_bin, "-y"]
        for path, duration in zip(frame_paths, durations, strict=True):
            args.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", str(path)])
        audio_index = len(frame_paths)
        args.extend(
            [
                "-f",
                "lavfi",
                "-t",
                "15.000",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=48000",
            ]
        )
        filters = []
        for index in range(len(frame_paths)):
            filters.append(
                f"[{index}:v]fps=30,scale=1080:1920,setsar=1,format=yuv420p[v{index}]"
            )
        inputs = "".join(f"[v{index}]" for index in range(len(frame_paths)))
        filters.append(f"{inputs}concat=n={len(frame_paths)}:v=1:a=0[outv]")
        args.extend(
            [
                "-filter_complex",
                ";".join(filters),
                "-map",
                "[outv]",
                "-map",
                f"{audio_index}:a:0",
                "-t",
                "15.000",
                "-c:v",
                "libx264",
                "-preset",
                "medium",
                "-crf",
                "20",
                "-pix_fmt",
                "yuv420p",
                "-force_key_frames",
                "0,2,5,10,13",
                "-c:a",
                "aac",
                "-b:a",
                "128k",
                "-movflags",
                "+faststart",
                "-map_metadata",
                "-1",
                str(destination),
            ]
        )
        result = subprocess.run(args, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "ffmpeg failed").splitlines()[
                -1
            ]
            raise PrevoiceValidationError(detail[:500])

    metadata = probe_video(destination, ffprobe_bin=ffprobe_bin)
    if (
        metadata["width"] != 1080
        or metadata["height"] != 1920
        or metadata["video_codec"] != "h264"
        or metadata["audio_codec"] != "aac"
        or metadata["pixel_format"] != "yuv420p"
        or not metadata["faststart"]
        or abs(metadata["duration_ms"] - 15000) > 100
    ):
        raise PrevoiceValidationError("무음 프리비즈 규격 검증에 실패했어요")
    return metadata


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_prevoice_package(
    spec_path: Path,
    brand_policy_path: Path,
    font_dir: Path,
    output_dir: Path,
    *,
    ffmpeg_bin: str = "ffmpeg",
    ffprobe_bin: str = "ffprobe",
) -> dict[str, Any]:
    spec, brand = validate_preproduction_spec(spec_path, brand_policy_path)
    validate_font_dir(font_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    provider_path = render_provider_storyboard(
        brand, output_dir / "higgsfield-storyboard.png"
    )
    artifacts: list[dict[str, Any]] = [
        {
            "path": provider_path.name,
            "kind": "provider_storyboard",
            "sha256": _sha256(provider_path),
            "width": _REVIEW_BOARD[0],
            "height": _REVIEW_BOARD[1],
            "provider_upload_allowed": True,
            "publishable": False,
        }
    ]
    for variant in spec["variants"]:
        shared = spec["shared_copy"]
        layer_dir = output_dir / "copy-layers" / variant["id"]
        layer_dir.mkdir(parents=True, exist_ok=True)
        layer_paths = render_video_copy_layers(
            _CANVAS,
            CopySpec(
                hook=variant["hook"],
                body=shared["body"],
                cta=shared["cta"],
                endline=shared["endline"],
                non_prediction_line=shared["non_prediction"],
                disclaimer=shared["disclaimer"],
                colors=brand["visual"]["colors"],
            ),
            font_dir,
            layer_dir,
        )
        review_path = render_review_storyboard(
            spec,
            brand,
            variant,
            font_dir,
            output_dir / f"review-storyboard-{variant['id']}.png",
        )
        preview_path = output_dir / f"silent-previs-{variant['id']}.mp4"
        video_metadata = _render_silent_preview(
            spec,
            brand,
            variant,
            font_dir,
            preview_path,
            ffmpeg_bin=ffmpeg_bin,
            ffprobe_bin=ffprobe_bin,
        )
        artifacts.extend(
            [
                *(
                    {
                        "path": path.relative_to(output_dir).as_posix(),
                        "kind": f"deterministic_copy_{name}",
                        "variant": variant["id"],
                        "sha256": _sha256(path),
                        "width": _CANVAS[0],
                        "height": _CANVAS[1],
                        "provider_upload_allowed": False,
                        "publishable": False,
                    }
                    for name, path in layer_paths.items()
                ),
                {
                    "path": review_path.name,
                    "kind": "human_review_storyboard",
                    "variant": variant["id"],
                    "sha256": _sha256(review_path),
                    "width": _REVIEW_BOARD[0],
                    "height": _REVIEW_BOARD[1],
                    "provider_upload_allowed": False,
                    "publishable": False,
                },
                {
                    "path": preview_path.name,
                    "kind": "silent_previs",
                    "variant": variant["id"],
                    "sha256": _sha256(preview_path),
                    **video_metadata,
                    "provider_upload_allowed": False,
                    "publishable": False,
                    "audio_note": "silent AAC placeholder; founder voice required",
                },
            ]
        )
    manifest = {
        "schema_version": "1.0",
        "campaign_key": spec["campaign_key"],
        "status": spec["status"],
        "publishable": False,
        "paid_generation_started": False,
        "notice_bid_no": spec["notice"]["bid_no"],
        "blocking_inputs": spec["acceptance"]["blocking_inputs"],
        "artifacts": artifacts,
    }
    manifest_path = output_dir / "preproduction-manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest
