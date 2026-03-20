"""Thumbnail generator for YouTube Shorts.

Creates eye-catching 1280x720 thumbnails with:
- Background image (best visual asset or solid gradient)
- Bold hook text overlay with drop shadow
- Semi-transparent dark gradient bar at bottom
- Accent color bar at top
"""

import logging
import textwrap
from pathlib import Path

logger = logging.getLogger(__name__)

THUMB_W = 1280
THUMB_H = 720
ACCENT_COLOR = (255, 60, 60)      # red-orange
TEXT_COLOR = (255, 255, 255)
SHADOW_COLOR = (0, 0, 0)
GRADIENT_COLOR = (0, 0, 0, 200)   # semi-transparent black


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
    accent_color: tuple = ACCENT_COLOR,
) -> str | None:
    """Generate a thumbnail with bold hook text overlay.

    Returns the output path on success, None on failure.
    """
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont

        if background_image_path and Path(background_image_path).exists():
            bg = Image.open(background_image_path).convert("RGB")
            bg = bg.resize((THUMB_W, THUMB_H), Image.LANCZOS)
            bg = bg.filter(ImageFilter.GaussianBlur(radius=2))
        else:
            bg = _make_gradient_bg(accent_color)

        draw = ImageDraw.Draw(bg, "RGBA")

        _draw_gradient_bar(draw, bg.size)

        accent_height = 12
        draw.rectangle([(0, 0), (THUMB_W, accent_height)], fill=accent_color)

        short_hook = _shorten_hook(hook_text, max_words=8)

        font_size = 90
        font = _get_font(font_size)

        wrapped = textwrap.fill(short_hook, width=20)
        lines = wrapped.split("\n")

        line_height = font_size + 12
        total_h = len(lines) * line_height
        y_start = THUMB_H - total_h - 60

        for i, line in enumerate(lines):
            y = y_start + i * line_height
            bbox = draw.textbbox((0, 0), line, font=font)
            text_w = bbox[2] - bbox[0]
            x = (THUMB_W - text_w) // 2

            for dx, dy in [(-3, -3), (3, -3), (-3, 3), (3, 3), (0, 4), (4, 0)]:
                draw.text((x + dx, y + dy), line, font=font, fill=(*SHADOW_COLOR, 220))

            draw.text((x, y), line, font=font, fill=TEXT_COLOR)

        bg = bg.convert("RGB")
        bg.save(output_path, "JPEG", quality=92)
        logger.info(f"Thumbnail generated: {output_path}")
        return output_path

    except Exception as e:
        logger.warning(f"Thumbnail generation failed: {e}")
        return None


def _make_gradient_bg(accent_color: tuple) -> "Image":
    from PIL import Image, ImageDraw
    img = Image.new("RGB", (THUMB_W, THUMB_H), (15, 15, 20))
    draw = ImageDraw.Draw(img)
    r, g, b = accent_color
    for y in range(THUMB_H // 2):
        alpha = 1 - (y / (THUMB_H // 2))
        dr = int(r * alpha * 0.4)
        dg = int(g * alpha * 0.4)
        db = int(b * alpha * 0.4)
        draw.line([(0, y), (THUMB_W, y)], fill=(dr, dg, db))
    return img


def _draw_gradient_bar(draw, size: tuple):
    from PIL import Image, ImageDraw
    w, h = size
    bar_h = 220
    for y in range(bar_h):
        alpha = int(220 * (y / bar_h))
        draw.line([(0, h - bar_h + y), (w, h - bar_h + y)], fill=(0, 0, 0, alpha))


def _shorten_hook(text: str, max_words: int = 8) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text.upper()
    return " ".join(words[:max_words]).rstrip(".,!?") + "..."
