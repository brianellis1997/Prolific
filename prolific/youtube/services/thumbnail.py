"""Thumbnail text overlay using Pillow."""

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

FONT_PATH = str(Path(__file__).parent.parent / "fonts" / "BebasNeue-Regular.ttf")
THUMBNAIL_W = 1280
THUMBNAIL_H = 720


def _get_multiline_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    stroke_width: int = 0,
) -> tuple[int, int]:
    """Get the total width and height of multiline text."""
    bbox = draw.multiline_textbbox(
        (0, 0), text, font=font, stroke_width=stroke_width, align="center"
    )
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_text_size(
    draw: ImageDraw.ImageDraw,
    text: str,
    font_path: str,
    max_width: int,
    max_height: int,
    start_size: int = 200,
    min_size: int = 40,
    stroke_width: int = 5,
) -> ImageFont.FreeTypeFont:
    """Find the largest font size that fits within the bounding box."""
    for size in range(start_size, min_size - 1, -4):
        font = ImageFont.truetype(font_path, size=size)
        text_w, text_h = _get_multiline_size(draw, text, font, stroke_width)
        if text_w <= max_width and text_h <= max_height:
            return font
    return ImageFont.truetype(font_path, size=min_size)


def _wrap_text(text: str, max_words_per_line: int = 3) -> str:
    """Wrap text to multiple lines, max N words per line."""
    words = text.split()
    if len(words) <= max_words_per_line:
        return text
    lines = []
    for i in range(0, len(words), max_words_per_line):
        lines.append(" ".join(words[i : i + max_words_per_line]))
    return "\n".join(lines)


def add_text_overlay(
    image_path: str,
    hook_text: str,
    output_path: str | None = None,
    position: str = "bottom",
    text_color: str = "white",
    stroke_color: str = "black",
    stroke_width: int = 5,
) -> str:
    """Add bold text overlay to a thumbnail image."""
    if output_path is None:
        output_path = image_path

    img = Image.open(image_path).convert("RGBA")
    img = img.resize((THUMBNAIL_W, THUMBNAIL_H), Image.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    hook_upper = hook_text.upper().strip()
    wrapped = _wrap_text(hook_upper, max_words_per_line=3)

    max_text_w = int(THUMBNAIL_W * 0.85)
    max_text_h = int(THUMBNAIL_H * 0.45)
    font = _fit_text_size(
        draw, wrapped, FONT_PATH, max_text_w, max_text_h,
        start_size=180, stroke_width=stroke_width,
    )

    text_w, text_h = _get_multiline_size(draw, wrapped, font, stroke_width)

    text_x = (THUMBNAIL_W - text_w) // 2
    if position == "bottom":
        text_y = THUMBNAIL_H - text_h - 40
    elif position == "top":
        text_y = 40
    else:
        text_y = (THUMBNAIL_H - text_h) // 2

    padding_x = 30
    padding_y = 15
    draw.rectangle(
        [
            text_x - padding_x,
            text_y - padding_y,
            text_x + text_w + padding_x,
            text_y + text_h + padding_y,
        ],
        fill=(0, 0, 0, 120),
    )

    draw.multiline_text(
        (text_x, text_y),
        wrapped,
        font=font,
        fill=text_color,
        stroke_width=stroke_width,
        stroke_fill=stroke_color,
        align="center",
    )

    result = Image.alpha_composite(img, overlay)
    result = result.convert("RGB")
    result.save(output_path, quality=95)

    logger.info(f"Thumbnail overlay: '{hook_text}' -> {output_path}")
    return output_path
