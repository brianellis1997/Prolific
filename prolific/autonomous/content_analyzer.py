"""Analyze existing blog posts for deduplication."""

import logging
import re
from pathlib import Path

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ExistingPostSummary(BaseModel):
    slug: str
    title: str
    date: str
    excerpt: str
    topics: list[str] = Field(default_factory=list)
    word_count: int = 0


def _parse_frontmatter(content: str) -> dict[str, str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", content, re.DOTALL)
    if not match:
        return {}
    fm = {}
    for line in match.group(1).splitlines():
        if ":" in line:
            key, _, value = line.partition(":")
            fm[key.strip()] = value.strip().strip('"').strip("'")
    return fm


def _extract_headings(content: str) -> list[str]:
    return [
        line.lstrip("#").strip()
        for line in content.splitlines()
        if line.startswith("## ")
    ]


def get_existing_posts(blog_dir: Path | None = None) -> list[ExistingPostSummary]:
    if blog_dir is None:
        blog_dir = Path(__file__).parent.parent.parent / "blog" / "content" / "posts"

    if not blog_dir.exists():
        logger.warning(f"Blog posts directory not found: {blog_dir}")
        return []

    posts = []
    for md_file in sorted(blog_dir.glob("*.md")):
        try:
            raw = md_file.read_text(encoding="utf-8")
            fm = _parse_frontmatter(raw)

            body_start = raw.find("---", 3)
            body = raw[body_start + 3:].strip() if body_start != -1 else raw

            posts.append(ExistingPostSummary(
                slug=md_file.stem,
                title=fm.get("title", md_file.stem),
                date=fm.get("date", ""),
                excerpt=fm.get("excerpt", ""),
                topics=_extract_headings(body),
                word_count=len(body.split()),
            ))
        except Exception as e:
            logger.warning(f"Failed to parse {md_file.name}: {e}")

    logger.info(f"Found {len(posts)} existing blog posts")
    return posts
