"""Thumbnail text overlay using Pillow — two-color emphasis text."""

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

logger = logging.getLogger(__name__)

FONT_PATH = str(Path(__file__).parent.parent / "fonts" / "BebasNeue-Regular.ttf")
THUMBNAIL_W = 1280
THUMBNAIL_H = 720
PRIMARY_COLOR = (255, 255, 255)
EMPHASIS_COLOR = (255, 40, 40)
STROKE_COLOR = (0, 0, 0)


def _split_emphasis(text: str) -> tuple[list[str], list[bool]]:
    """Split hook text into lines, marking the last line as emphasis (red).

    For 2-3 word hooks, the last word is emphasis.
    For 4+ word hooks, the last line (1-2 words) is emphasis.
    """
    words = text.upper().split()
    if len(words) <= 2:
        return [text.upper()], [False]

    if len(words) <= 4:
        lines = [" ".join(words[:-1]), words[-1]]
        emphasis = [False, True]
    else:
        mid = len(words) - 2
        lines = [" ".join(words[:mid]), " ".join(words[mid:])]
        emphasis = [False, True]

    return lines, emphasis


def add_text_overlay(
    image_path: str,
    hook_text: str,
    output_path: str | None = None,
    position: str = "top",
    stroke_width: int = 6,
) -> str:
    """Add bold two-color text overlay to a thumbnail image."""
    if output_path is None:
        output_path = image_path

    img = Image.open(image_path).convert("RGBA")
    img = img.resize((THUMBNAIL_W, THUMBNAIL_H), Image.LANCZOS)

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    _draw_gradient_vignette(overlay, position)

    lines, emphasis_flags = _split_emphasis(hook_text)

    font = _fit_font(draw, lines, stroke_width)

    line_heights = []
    line_widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        line_widths.append(bbox[2] - bbox[0])
        line_heights.append(bbox[3] - bbox[1])

    line_spacing = 10
    total_h = sum(line_heights) + line_spacing * (len(lines) - 1)

    if position == "top":
        y_start = 30
    elif position == "bottom":
        y_start = THUMBNAIL_H - total_h - 40
    else:
        y_start = (THUMBNAIL_H - total_h) // 2

    y = y_start
    for i, (line, is_emphasis) in enumerate(zip(lines, emphasis_flags)):
        x = (THUMBNAIL_W - line_widths[i]) // 2
        color = EMPHASIS_COLOR if is_emphasis else PRIMARY_COLOR

        draw.text(
            (x, y), line, font=font,
            fill=color, stroke_width=stroke_width, stroke_fill=STROKE_COLOR,
        )
        y += line_heights[i] + line_spacing

    result = Image.alpha_composite(img, overlay)
    result = result.convert("RGB")
    result.save(output_path, quality=95)

    logger.info(f"Thumbnail overlay: '{hook_text}' -> {output_path}")
    return output_path


def _fit_font(draw, lines: list[str], stroke_width: int) -> ImageFont.FreeTypeFont:
    """Find largest font that fits all lines within the thumbnail width."""
    max_w = int(THUMBNAIL_W * 0.90)
    max_h = int(THUMBNAIL_H * 0.50)

    for size in range(180, 40, -4):
        font = ImageFont.truetype(FONT_PATH, size=size)
        widths = []
        heights = []
        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
            widths.append(bbox[2] - bbox[0])
            heights.append(bbox[3] - bbox[1])
        if max(widths) <= max_w and sum(heights) <= max_h:
            return font

    return ImageFont.truetype(FONT_PATH, size=40)


def _draw_gradient_vignette(
    overlay: Image.Image,
    position: str = "top",
    max_alpha: int = 180,
) -> None:
    """Draw a smooth gradient fade for text readability."""
    w, h = overlay.size
    gradient_height = int(h * 0.50)

    gradient = Image.new("L", (1, gradient_height), 0)

    for y in range(gradient_height):
        if position == "bottom":
            alpha = int(max_alpha * (y / gradient_height) ** 1.5)
        elif position == "top":
            alpha = int(max_alpha * (1 - y / gradient_height) ** 1.5)
        else:
            center = gradient_height // 2
            dist = abs(y - center) / center
            alpha = int(max_alpha * (1 - dist) ** 1.5)
        gradient.putpixel((0, y), alpha)

    gradient = gradient.resize((w, gradient_height), Image.BILINEAR)

    black_bar = Image.new("RGBA", (w, gradient_height), (0, 0, 0, 255))
    black_bar.putalpha(gradient)

    if position == "bottom":
        overlay.paste(black_bar, (0, h - gradient_height), black_bar)
    elif position == "top":
        overlay.paste(black_bar, (0, 0), black_bar)
    else:
        overlay.paste(black_bar, (0, (h - gradient_height) // 2), black_bar)
