"""Thumbnail generator for YouTube Shorts.

Creates attention-grabbing 1280x720 thumbnails with:
- Background image (NOT blurred — crisp and vivid)
- Bold hook text with thick outline (Impact-style)
- Red circle + arrow pointing at the subject
- Bright accent elements for visual pop
"""

import logging
import math
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

THUMB_W = 1280
THUMB_H = 720
TEXT_COLOR = (255, 255, 255)
OUTLINE_COLOR = (0, 0, 0)
ARROW_COLOR = (255, 40, 40)
CIRCLE_COLOR = (255, 40, 40)


def _get_font(size: int):
    """Load a bold font, falling back to default."""
    from PIL import ImageFont
    font_candidates = [
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ]
    for path in font_candidates:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def generate_thumbnail(
    output_path: str,
    hook_text: str,
    background_image_path: str | None = None,
    accent_color: tuple = ARROW_COLOR,
) -> str | None:
    """Generate an attention-grabbing thumbnail with bold text and visual elements."""
    try:
        from PIL import Image, ImageDraw, ImageFilter

        if background_image_path and Path(background_image_path).exists():
            bg = Image.open(background_image_path).convert("RGB")
            bg = bg.resize((THUMB_W, THUMB_H), Image.LANCZOS)
        else:
            bg = _make_gradient_bg(accent_color)

        overlay = Image.new("RGBA", (THUMB_W, THUMB_H), (0, 0, 0, 0))
        draw = ImageDraw.Draw(overlay, "RGBA")

        _draw_bottom_gradient(draw)
        _draw_red_circle(draw)
        _draw_arrow(draw)

        bg = bg.convert("RGBA")
        bg = Image.alpha_composite(bg, overlay)

        draw_final = ImageDraw.Draw(bg)
        _draw_hook_text(draw_final, hook_text)

        bg = bg.convert("RGB")
        bg.save(output_path, "JPEG", quality=95)
        logger.info(f"Thumbnail generated: {output_path}")
        return output_path

    except Exception as e:
        logger.warning(f"Thumbnail generation failed: {e}")
        return None


def _draw_hook_text(draw, hook_text: str):
    """Draw bold outlined hook text, centered at bottom."""
    short_hook = _shorten_hook(hook_text, max_words=8)
    font = _get_font(80)

    wrapped = textwrap.fill(short_hook, width=18)
    lines = wrapped.split("\n")

    line_height = 88
    total_h = len(lines) * line_height
    y_start = THUMB_H - total_h - 40

    for i, line in enumerate(lines):
        y = y_start + i * line_height
        bbox = draw.textbbox((0, 0), line, font=font)
        text_w = bbox[2] - bbox[0]
        x = (THUMB_W - text_w) // 2

        outline_width = 5
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx * dx + dy * dy <= outline_width * outline_width:
                    draw.text((x + dx, y + dy), line, font=font, fill=OUTLINE_COLOR)

        draw.text((x, y), line, font=font, fill=TEXT_COLOR)


def _draw_red_circle(draw):
    """Draw a red circle in the upper-right area to draw attention."""
    cx, cy = THUMB_W - 280, 180
    radius = 90
    for r in range(radius, radius - 8, -1):
        draw.ellipse(
            [(cx - r, cy - r), (cx + r, cy + r)],
            outline=(*CIRCLE_COLOR, 240),
            width=4,
        )


def _draw_arrow(draw):
    """Draw a red arrow pointing toward center-right."""
    tip_x, tip_y = THUMB_W - 200, 300
    tail_x, tail_y = THUMB_W - 80, 160

    draw.line([(tail_x, tail_y), (tip_x, tip_y)], fill=(*ARROW_COLOR, 240), width=8)

    angle = math.atan2(tip_y - tail_y, tip_x - tail_x)
    head_len = 30
    for offset in [-0.4, 0.4]:
        hx = tip_x - head_len * math.cos(angle + offset)
        hy = tip_y - head_len * math.sin(angle + offset)
        draw.line([(tip_x, tip_y), (int(hx), int(hy))], fill=(*ARROW_COLOR, 240), width=8)


def _draw_bottom_gradient(draw):
    """Semi-transparent gradient at bottom for text readability."""
    bar_h = 280
    for y in range(bar_h):
        alpha = int(200 * (y / bar_h))
        draw.line(
            [(0, THUMB_H - bar_h + y), (THUMB_W, THUMB_H - bar_h + y)],
            fill=(0, 0, 0, alpha),
        )


def _make_gradient_bg(accent_color: tuple) -> "Image":
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (THUMB_W, THUMB_H), (15, 15, 25))
    draw = ImageDraw.Draw(img)
    r, g, b = accent_color
    for y in range(THUMB_H):
        alpha = 1 - (y / THUMB_H)
        dr = int(r * alpha * 0.3)
        dg = int(g * alpha * 0.3)
        db = int(b * alpha * 0.3)
        draw.line([(0, y), (THUMB_W, y)], fill=(15 + dr, 15 + dg, 25 + db))
    return img


def _shorten_hook(text: str, max_words: int = 8) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.upper()
    return " ".join(words[:max_words]).rstrip(".,!?").upper() + "..."
