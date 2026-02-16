"""Convert pipeline output to a blog post and handle git operations."""

import logging
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel

logger = logging.getLogger(__name__)


class PublishResult(BaseModel):
    status: str
    file_path: str
    slug: str
    title: str
    images_copied: int = 0
    error: str | None = None


def _generate_slug(topic: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", topic.lower()).strip("-")


def _extract_excerpt(content: str) -> str:
    first_para = content.split("\n\n")[0]
    first_para = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", first_para)
    first_para = re.sub(r"\*\*([^*]+)\*\*", r"\1", first_para)
    first_para = re.sub(r"\*([^*]+)\*", r"\1", first_para)
    first_para = re.sub(r"^#+\s*", "", first_para)
    if len(first_para) > 250:
        return first_para[:250] + "..."
    return first_para


async def publish_blog_post(
    final_state: dict,
    topic: str,
    slug: str | None = None,
    excerpt: str | None = None,
    project_root: Path | None = None,
) -> PublishResult:
    if project_root is None:
        project_root = Path(__file__).parent.parent.parent

    if slug is None:
        slug = _generate_slug(topic)

    draft_chunks = final_state.get("draft_chunks", [])
    chapter_briefs = {b.chapter_id: b for b in final_state.get("chapter_briefs", [])}
    visual_assets = final_state.get("visual_assets", [])

    if not draft_chunks:
        return PublishResult(
            status="failed",
            file_path="",
            slug=slug,
            title=topic,
            error="No draft chunks to publish",
        )

    blog_images_dir = project_root / "blog" / "public" / "images" / slug
    blog_images_dir.mkdir(parents=True, exist_ok=True)

    image_path_map = {}
    images_copied = 0
    for asset in visual_assets:
        if asset.file_path:
            src_path = Path(asset.file_path)
            if src_path.exists():
                dest_path = blog_images_dir / src_path.name
                shutil.copy2(src_path, dest_path)
                image_path_map[asset.file_path] = f"/images/{slug}/{src_path.name}"
                images_copied += 1

    generated_images_dir = project_root / "generated_images"
    localhost_re = re.compile(r'http://localhost:\d+/images/([^\s\)\"]+)')
    for chunk in draft_chunks:
        for match in localhost_re.finditer(chunk.content):
            img_filename = match.group(1)
            localhost_url = match.group(0)
            if localhost_url not in image_path_map:
                src_path = generated_images_dir / img_filename
                if src_path.exists():
                    shutil.copy2(src_path, blog_images_dir / img_filename)
                    image_path_map[localhost_url] = f"/images/{slug}/{img_filename}"
                    images_copied += 1
        gen_dir_str = str(generated_images_dir)
        if gen_dir_str in chunk.content:
            gen_re = re.compile(re.escape(gen_dir_str) + r'/([^\s\)\"]+)')
            for match in gen_re.finditer(chunk.content):
                img_filename = match.group(1)
                full_path = match.group(0)
                if full_path not in image_path_map:
                    src_path = generated_images_dir / img_filename
                    if src_path.exists():
                        shutil.copy2(src_path, blog_images_dir / img_filename)
                        image_path_map[full_path] = f"/images/{slug}/{img_filename}"
                        images_copied += 1

    sorted_chunks = sorted(
        draft_chunks,
        key=lambda c: getattr(
            chapter_briefs.get(c.chapter_id), "chapter_number", 0
        ),
    )

    content_parts = []
    for chunk in sorted_chunks:
        brief = chapter_briefs.get(chunk.chapter_id)
        chunk_content = chunk.content
        for old_path, new_path in image_path_map.items():
            chunk_content = chunk_content.replace(old_path, new_path)
        if brief and len(sorted_chunks) > 1:
            content_parts.append(f"## {brief.title}\n\n{chunk_content}")
        else:
            content_parts.append(chunk_content)

    full_content = "\n\n".join(content_parts)

    if excerpt is None:
        excerpt = _extract_excerpt(full_content)

    today = datetime.now().strftime("%Y-%m-%d")
    frontmatter = f'---\ntitle: "{topic}"\ndate: "{today}"\nexcerpt: "{excerpt.replace(chr(34), chr(92) + chr(34))}"\n---\n\n'
    blog_content = frontmatter + full_content

    blog_posts_dir = project_root / "blog" / "content" / "posts"
    if not blog_posts_dir.exists():
        return PublishResult(
            status="failed",
            file_path="",
            slug=slug,
            title=topic,
            error=f"Blog posts directory not found: {blog_posts_dir}",
        )

    file_path = blog_posts_dir / f"{slug}.md"
    file_path.write_text(blog_content, encoding="utf-8")
    logger.info(f"Published blog post: {file_path}")

    return PublishResult(
        status="published",
        file_path=str(file_path),
        slug=slug,
        title=topic,
        images_copied=images_copied,
    )


def git_commit_and_push(
    file_path: Path,
    images_dir: Path,
    topic: str,
    project_root: Path,
) -> str:
    try:
        add_paths = [str(file_path)]
        if images_dir.exists() and any(images_dir.iterdir()):
            add_paths.append(str(images_dir))

        presentations_dir = project_root / "blog" / "public" / "presentations"
        if presentations_dir.exists() and any(presentations_dir.glob("*.pptx")):
            add_paths.append(str(presentations_dir))

        metrics_file = project_root / "blog" / "data" / "metrics.json"
        if metrics_file.exists():
            add_paths.append(str(metrics_file))

        subprocess.run(
            ["git", "add"] + add_paths,
            cwd=project_root,
            check=True,
            capture_output=True,
        )
        subprocess.run(
            ["git", "commit", "-m", f"Add blog post: {topic}"],
            cwd=project_root,
            check=True,
            capture_output=True,
        )
        rebase_result = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=project_root,
            capture_output=True,
        )
        if rebase_result.returncode != 0:
            logger.warning(
                f"git pull --rebase failed (non-fatal): "
                f"{rebase_result.stderr.decode().strip()}"
            )
        subprocess.run(
            ["git", "push", "origin", "main"],
            cwd=project_root,
            check=True,
            capture_output=True,
        )
        logger.info(f"Git push successful for: {topic}")
        return "pushed"
    except subprocess.CalledProcessError as e:
        error_msg = e.stderr.decode() if e.stderr else str(e)
        logger.error(f"Git operation failed: {error_msg}")
        return f"git_failed: {error_msg}"
