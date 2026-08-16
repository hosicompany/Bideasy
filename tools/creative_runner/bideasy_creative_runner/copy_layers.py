"""Deterministic Korean copy layers rendered from the approved local brand policy."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor, ImageDraw, ImageFont

from .errors import ConfigurationError

_FONT_FILES = {
    "regular": "Pretendard-Regular.otf",
    "medium": "Pretendard-Medium.otf",
    "bold": "Pretendard-Bold.otf",
}
_HEX_COLOR = re.compile(r"#[0-9a-fA-F]{6}")


@dataclass(frozen=True)
class CopySpec:
    hook: str
    body: str
    cta: str
    endline: str
    non_prediction_line: str
    disclaimer: str
    colors: dict[str, str]


def validate_font_dir(font_dir: Path) -> None:
    missing = [name for name in _FONT_FILES.values() if not (font_dir / name).is_file()]
    if missing:
        raise ConfigurationError(
            f"Pretendard font directory is incomplete: {', '.join(missing)}"
        )
    try:
        for filename in _FONT_FILES.values():
            ImageFont.truetype(str(font_dir / filename), size=16)
    except OSError as exc:
        raise ConfigurationError("Pretendard font files could not be loaded") from exc


def _font(font_dir: Path, weight: str, size: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(
            str(font_dir / _FONT_FILES[weight]), size=max(8, size)
        )
    except (KeyError, OSError) as exc:
        raise ConfigurationError(
            "approved Pretendard font could not be loaded"
        ) from exc


def _color(spec: CopySpec, name: str, alpha: int = 255) -> tuple[int, int, int, int]:
    value = spec.colors.get(name, "")
    if not _HEX_COLOR.fullmatch(value):
        raise ConfigurationError(f"brand color is invalid: {name}")
    return (*ImageColor.getrgb(value), alpha)


def _text_width(
    draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont
) -> float:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def _split_token(
    draw: ImageDraw.ImageDraw,
    token: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
) -> list[str]:
    pieces: list[str] = []
    current = ""
    for character in token:
        candidate = current + character
        if current and _text_width(draw, candidate, font) > max_width:
            pieces.append(current)
            current = character
        else:
            current = candidate
    if current:
        pieces.append(current)
    return pieces or [""]


def wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: int,
    max_lines: int,
) -> list[str]:
    """Pixel-wrap Korean/Latin text and deterministically truncate with an ellipsis."""
    lines: list[str] = []
    paragraphs = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for paragraph in paragraphs:
        words = paragraph.split()
        if not words:
            if lines:
                lines.append("")
            continue
        current = ""
        for word in words:
            pieces = _split_token(draw, word, font, max_width)
            for piece_index, piece in enumerate(pieces):
                separator = " " if current and piece_index == 0 else ""
                candidate = f"{current}{separator}{piece}"
                if current and _text_width(draw, candidate, font) > max_width:
                    lines.append(current)
                    current = piece
                else:
                    current = candidate
            if len(lines) >= max_lines:
                break
        if current and len(lines) < max_lines:
            lines.append(current)
        if len(lines) >= max_lines:
            break

    lines = lines[:max_lines]
    consumed = "".join(lines).replace(" ", "")
    original = "".join(text.split())
    if lines and len(consumed) < len(original):
        last = lines[-1].rstrip()
        while last and _text_width(draw, f"{last}…", font) > max_width:
            last = last[:-1]
        lines[-1] = f"{last}…" if last else "…"
    return lines


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    xy: tuple[int, int],
    *,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    spacing: int,
) -> int:
    x, y = xy
    line_height = font.getbbox("가Ag")[3] - font.getbbox("가Ag")[1]
    for line in lines:
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height + spacing
    return y


def _scaled_font_sizes(width: int, height: int) -> dict[str, int]:
    scale = max(0.72, min(1.35, min(width / 1080, height / 1080)))
    return {
        "hook": round(54 * scale),
        "body": round(29 * scale),
        "cta": round(28 * scale),
        "endline": round(23 * scale),
        "disclaimer": round(15 * scale),
    }


def render_static_copy_layer(
    size: tuple[int, int],
    spec: CopySpec,
    font_dir: Path,
    destination: Path,
) -> Path:
    validate_font_dir(font_dir)
    width, height = size
    sizes = _scaled_font_sizes(width, height)
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    hook_font = _font(font_dir, "bold", sizes["hook"])
    body_font = _font(font_dir, "regular", sizes["body"])
    cta_font = _font(font_dir, "bold", sizes["cta"])
    endline_font = _font(font_dir, "medium", sizes["endline"])
    disclaimer_font = _font(font_dir, "regular", sizes["disclaimer"])

    left = round(width * 0.045)
    top = round(height * 0.055)
    panel_width = round(width * 0.34)
    panel_bottom = round(height * 0.9)
    padding = round(width * 0.025)
    radius = max(18, round(min(width, height) * 0.02))
    draw.rounded_rectangle(
        (left, top, left + panel_width, panel_bottom),
        radius=radius,
        fill=_color(spec, "surface", 244),
    )
    draw.rounded_rectangle(
        (
            left + padding,
            top + padding,
            left + padding + round(panel_width * 0.16),
            top + padding + 8,
        ),
        radius=4,
        fill=_color(spec, "accent"),
    )

    text_left = left + padding
    text_width = panel_width - 2 * padding
    y = top + padding + round(height * 0.045)
    y = _draw_lines(
        draw,
        wrap_text(draw, spec.hook, hook_font, text_width, 4),
        (text_left, y),
        font=hook_font,
        fill=_color(spec, "ink"),
        spacing=max(4, round(sizes["hook"] * 0.24)),
    )
    y += round(height * 0.035)
    _draw_lines(
        draw,
        wrap_text(draw, spec.body, body_font, text_width, 6),
        (text_left, y),
        font=body_font,
        fill=_color(spec, "muted"),
        spacing=max(4, round(sizes["body"] * 0.35)),
    )

    cta_height = round(height * 0.075)
    cta_top = panel_bottom - round(height * 0.19)
    draw.rounded_rectangle(
        (text_left, cta_top, left + panel_width - padding, cta_top + cta_height),
        radius=max(12, round(cta_height * 0.22)),
        fill=_color(spec, "accent"),
    )
    cta_lines = wrap_text(draw, spec.cta, cta_font, text_width - 24, 1)
    cta_text = cta_lines[0] if cta_lines else ""
    cta_box = draw.textbbox((0, 0), cta_text, font=cta_font)
    cta_x = left + panel_width // 2 - (cta_box[2] - cta_box[0]) // 2
    cta_y = cta_top + (cta_height - (cta_box[3] - cta_box[1])) // 2 - cta_box[1]
    draw.text((cta_x, cta_y), cta_text, font=cta_font, fill=_color(spec, "surface"))

    endline_lines = wrap_text(draw, spec.endline, endline_font, text_width, 2)
    _draw_lines(
        draw,
        endline_lines,
        (text_left, cta_top + cta_height + round(height * 0.025)),
        font=endline_font,
        fill=_color(spec, "ink"),
        spacing=4,
    )

    footer_height = max(round(height * 0.035), sizes["disclaimer"] + 16)
    draw.rectangle(
        (0, height - footer_height, width, height), fill=_color(spec, "ink", 218)
    )
    disclaimer = wrap_text(draw, spec.disclaimer, disclaimer_font, width - 40, 1)[0]
    draw.text(
        (20, height - footer_height + (footer_height - sizes["disclaimer"]) // 2 - 2),
        disclaimer,
        font=disclaimer_font,
        fill=_color(spec, "surface", 230),
    )
    layer.save(destination, "PNG", optimize=True, compress_level=9)
    return destination


def render_video_copy_layers(
    size: tuple[int, int],
    spec: CopySpec,
    font_dir: Path,
    output_dir: Path,
) -> dict[str, Path]:
    validate_font_dir(font_dir)
    width, height = size
    sizes = _scaled_font_sizes(width, height)
    paths = {
        "hook": output_dir / "copy-hook.png",
        "truth": output_dir / "copy-truth.png",
        "final": output_dir / "copy-final.png",
    }
    hook_font = _font(font_dir, "bold", round(sizes["hook"] * 1.08))
    truth_font = _font(font_dir, "bold", sizes["body"])
    cta_font = _font(font_dir, "bold", sizes["cta"])
    endline_font = _font(font_dir, "bold", round(sizes["endline"] * 1.2))
    disclaimer_font = _font(font_dir, "regular", sizes["disclaimer"])

    hook_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(hook_layer)
    margin = round(width * 0.055)
    card_top = round(height * 0.055)
    card_bottom = round(height * 0.31)
    draw.rounded_rectangle(
        (margin, card_top, width - margin, card_bottom),
        radius=max(20, round(width * 0.03)),
        fill=_color(spec, "surface", 245),
    )
    hook_lines = wrap_text(draw, spec.hook, hook_font, width - 2 * margin - 60, 3)
    _draw_lines(
        draw,
        hook_lines,
        (margin + 30, card_top + 28),
        font=hook_font,
        fill=_color(spec, "ink"),
        spacing=max(6, round(sizes["hook"] * 0.22)),
    )
    hook_layer.save(paths["hook"], "PNG", optimize=True, compress_level=9)

    truth_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(truth_layer)
    truth_top = round(height * 0.68)
    truth_bottom = round(height * 0.88)
    draw.rounded_rectangle(
        (margin, truth_top, width - margin, truth_bottom),
        radius=max(20, round(width * 0.03)),
        fill=_color(spec, "ink", 228),
    )
    truth_lines = wrap_text(
        draw, spec.non_prediction_line, truth_font, width - 2 * margin - 60, 3
    )
    _draw_lines(
        draw,
        truth_lines,
        (margin + 30, truth_top + 28),
        font=truth_font,
        fill=_color(spec, "surface"),
        spacing=max(5, round(sizes["body"] * 0.3)),
    )
    truth_layer.save(paths["truth"], "PNG", optimize=True, compress_level=9)

    final_layer = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(final_layer)
    final_top = round(height * 0.62)
    draw.rectangle((0, final_top, width, height), fill=_color(spec, "accent", 240))
    endline_lines = wrap_text(draw, spec.endline, endline_font, width - 2 * margin, 2)
    y = _draw_lines(
        draw,
        endline_lines,
        (margin, final_top + 28),
        font=endline_font,
        fill=_color(spec, "surface"),
        spacing=max(4, round(sizes["endline"] * 0.25)),
    )
    y += 18
    cta_lines = wrap_text(draw, spec.cta, cta_font, width - 2 * margin - 40, 1)
    cta_text = cta_lines[0] if cta_lines else ""
    cta_box = draw.textbbox((0, 0), cta_text, font=cta_font)
    cta_height = max(64, round(height * 0.065))
    draw.rounded_rectangle(
        (margin, y, width - margin, y + cta_height),
        radius=max(14, round(cta_height * 0.22)),
        fill=_color(spec, "surface"),
    )
    draw.text(
        (
            width // 2 - (cta_box[2] - cta_box[0]) // 2,
            y + (cta_height - (cta_box[3] - cta_box[1])) // 2 - cta_box[1],
        ),
        cta_text,
        font=cta_font,
        fill=_color(spec, "accent"),
    )
    disclaimer = wrap_text(
        draw, spec.disclaimer, disclaimer_font, width - 2 * margin, 1
    )[0]
    draw.text(
        (margin, height - sizes["disclaimer"] - 18),
        disclaimer,
        font=disclaimer_font,
        fill=_color(spec, "surface", 220),
    )
    final_layer.save(paths["final"], "PNG", optimize=True, compress_level=9)
    return paths
