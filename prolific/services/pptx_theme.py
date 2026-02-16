"""Consistent dark theme constants for PowerPoint generation.

All colors, fonts, and measurements are defined here so the theme
stays identical across every automatically generated presentation.
"""

from pptx.dml.color import RGBColor
from pptx.util import Inches, Pt

SLIDE_WIDTH = Inches(13.333)
SLIDE_HEIGHT = Inches(7.5)

# -- Color Palette (dark, modern, YouTube-optimized) --
BG_PRIMARY = RGBColor(0x0F, 0x0F, 0x14)
BG_SECTION = RGBColor(0x14, 0x14, 0x1E)
BG_ACCENT = RGBColor(0x1A, 0x1C, 0x2E)
ACCENT_PRIMARY = RGBColor(0x60, 0x9B, 0xFF)
ACCENT_SECONDARY = RGBColor(0x7C, 0x6A, 0xFF)
TEXT_PRIMARY = RGBColor(0xF0, 0xF0, 0xF5)
TEXT_SECONDARY = RGBColor(0x9A, 0x9A, 0xA8)
TEXT_ACCENT = ACCENT_PRIMARY
HIGHLIGHT_BG = RGBColor(0x1E, 0x29, 0x3B)
QUOTE_MARK_COLOR = RGBColor(0x60, 0x9B, 0xFF)

# -- Typography --
FONT_TITLE = "Arial"
FONT_BODY = "Arial"

# Title slide
TITLE_FONT_SIZE = Pt(40)
SUBTITLE_FONT_SIZE = Pt(20)
DATE_FONT_SIZE = Pt(14)

# Section divider
SECTION_TITLE_SIZE = Pt(36)
SECTION_SUBTITLE_SIZE = Pt(18)
SECTION_NUMBER_SIZE = Pt(48)

# Content slides
SLIDE_TITLE_SIZE = Pt(28)
BULLET_FONT_SIZE = Pt(18)
BULLET_SUB_SIZE = Pt(15)

# Quote slides
QUOTE_FONT_SIZE = Pt(24)
ATTRIBUTION_FONT_SIZE = Pt(14)

# Sources / small text
SOURCE_FONT_SIZE = Pt(11)
CAPTION_FONT_SIZE = Pt(12)

# -- Layout measurements --
MARGIN_LEFT = Inches(0.8)
MARGIN_RIGHT = Inches(0.8)
MARGIN_TOP = Inches(0.5)
CONTENT_TOP = Inches(1.6)
CONTENT_WIDTH = Inches(11.7)
CONTENT_HEIGHT = Inches(5.2)

# Title slide layout
TITLE_TOP = Inches(2.0)
TITLE_LEFT = Inches(1.2)
TITLE_WIDTH = Inches(10.9)

# Accent line
ACCENT_LINE_TOP = Inches(1.3)
ACCENT_LINE_WIDTH = Inches(1.5)
ACCENT_LINE_HEIGHT = Pt(3)

# Image feature layout
IMAGE_WIDTH = Inches(6.5)
IMAGE_HEIGHT = Inches(4.5)
IMAGE_LEFT = Inches(0.8)
IMAGE_TOP = Inches(1.8)
IMAGE_TEXT_LEFT = Inches(7.8)
IMAGE_TEXT_WIDTH = Inches(4.7)
