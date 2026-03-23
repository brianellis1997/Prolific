"""Clip sourcing node - downloads real clips from YouTube/Twitch for the short."""

import logging
from pathlib import Path

from langchain_core.messages import AIMessage

from prolific.core.config import settings
from prolific.shorts.schemas import SourceClip, VisualAsset
from prolific.shorts.state import ShortsPipelineState

logger = logging.getLogger(__name__)


async def clip_sourcing_node(state: ShortsPipelineState) -> dict:
    """Download and process source clips based on content mode."""
    logger.info("=== SHORTS: CLIP SOURCING ===")

    content_mode = state.get("content_mode", "news_commentary")
    topic = state.get("topic", "")
    source_urls = state.get("source_urls", [])

    output_dir = Path(settings.shorts_output_dir) / state["thread_id"] / "clips"
    output_dir.mkdir(parents=True, exist_ok=True)

    from prolific.shorts.services.clip_downloader import get_clip_downloader
    downloader = get_clip_downloader()

    source_clips = []
    visual_assets = []

    if content_mode == "clip_reaction":
        result = await _download_best_clip(
            urls=source_urls,
            search_topic=topic,
            downloader=downloader,
            output_dir=str(output_dir),
            filename="reaction_clip",
            max_duration=30,
        )
        if result:
            clip, audio_path, info = result
            sc = SourceClip(
                platform=info.get("platform", "other") if info else "other",
                original_url=info.get("url", "") if info else "",
                creator_name=info.get("uploader", "") if info else "",
                clip_title=info.get("title", "") if info else "",
                file_path=clip,
                audio_path=audio_path,
                duration_seconds=info.get("duration", 0) if info else 0,
                sequence_number=1,
                view_count=info.get("view_count", 0) if info else 0,
            )
            source_clips.append(sc)
            visual_assets.append(VisualAsset(
                sequence_number=1,
                asset_type="source_clip",
                search_query=topic,
                file_path=clip,
                duration_seconds=settings.shorts_target_duration_seconds,
            ))

    elif content_mode == "clip_compilation":
        compilation_items = state.get("compilation_items", [])
        direct_urls = [u for u in source_urls if _is_video_url(u)]
        use_direct_urls = len(direct_urls) >= 2

        clip_sources = direct_urls if use_direct_urls else []
        target_per_clip = settings.shorts_target_duration_seconds / max(
            len(clip_sources) if use_direct_urls else len(compilation_items), 3
        )

        if use_direct_urls:
            logger.info(f"Downloading {len(clip_sources)} clip sources (direct + search)")
            for i, url in enumerate(clip_sources):
                filename = f"comp_{i:02d}"

                if url.startswith("ytsearch:"):
                    query = url[len("ytsearch:"):]
                    logger.info(f"[{i+1}] Searching YouTube: {query}")
                    result = await _search_and_download(
                        query=query,
                        downloader=downloader,
                        output_dir=str(output_dir),
                        filename=filename,
                        max_duration=120,
                    )
                    if result:
                        clip_path, audio_path, info = result
                        sc = SourceClip(
                            platform="youtube",
                            original_url=info.get("url", ""),
                            creator_name=info.get("uploader", ""),
                            clip_title=info.get("title", ""),
                            file_path=clip_path,
                            audio_path=audio_path,
                            duration_seconds=info.get("duration", 0),
                            sequence_number=i + 1,
                            view_count=info.get("view_count", 0),
                        )
                        source_clips.append(sc)
                        visual_assets.append(VisualAsset(
                            sequence_number=i + 1,
                            asset_type="source_clip",
                            search_query=query,
                            file_path=clip_path,
                            duration_seconds=target_per_clip,
                        ))
                    else:
                        logger.warning(f"[{i+1}] YouTube search failed: {query}")
                    continue

                dl_result = await downloader.download_clip(
                    url=url,
                    output_dir=str(output_dir),
                    filename=filename,
                    max_duration=int(target_per_clip + 5),
                )
                if dl_result:
                    clip_path, audio_path = dl_result
                    info = await downloader.get_clip_info(url)
                    sc = SourceClip(
                        platform=info.get("platform", "other") if info else "other",
                        original_url=url,
                        creator_name=info.get("uploader", "") if info else "",
                        clip_title=info.get("title", "") if info else "",
                        file_path=clip_path,
                        audio_path=audio_path,
                        duration_seconds=info.get("duration", 0) if info else 0,
                        sequence_number=i + 1,
                        view_count=info.get("view_count", 0) if info else 0,
                    )
                    source_clips.append(sc)
                    visual_assets.append(VisualAsset(
                        sequence_number=i + 1,
                        asset_type="source_clip",
                        search_query=topic,
                        file_path=clip_path,
                        duration_seconds=target_per_clip,
                    ))
                else:
                    logger.warning(f"[{i+1}] Failed to download clip: {url}")
                    visual_assets.append(VisualAsset(
                        sequence_number=i + 1,
                        asset_type="web_image",
                        search_query=topic,
                        duration_seconds=target_per_clip,
                    ))
        else:
            for i, item in enumerate(compilation_items):
                filename = f"comp_{i:02d}"
                search_q = f"{item} {topic}"

                result = await _search_and_download(
                    query=search_q,
                    downloader=downloader,
                    output_dir=str(output_dir),
                    filename=filename,
                    max_duration=int(target_per_clip + 2),
                )
                if result:
                    clip, audio_path, info = result
                    sc = SourceClip(
                        platform=info.get("platform", "youtube"),
                        original_url=info.get("url", ""),
                        creator_name=info.get("uploader", ""),
                        clip_title=info.get("title", ""),
                        file_path=clip,
                        audio_path=audio_path,
                        duration_seconds=info.get("duration", 0),
                        sequence_number=i + 1,
                        view_count=info.get("view_count", 0),
                    )
                    source_clips.append(sc)
                    visual_assets.append(VisualAsset(
                        sequence_number=i + 1,
                        asset_type="source_clip",
                        search_query=search_q,
                        file_path=clip,
                        duration_seconds=target_per_clip,
                    ))
                else:
                    logger.warning(f"[{i+1}] No clip found for compilation item: {item}")
                    visual_assets.append(VisualAsset(
                        sequence_number=i + 1,
                        asset_type="web_image",
                        search_query=item,
                        duration_seconds=target_per_clip,
                    ))

    elif content_mode == "niche_drama":
        video_urls = [u for u in source_urls if _is_video_url(u)]
        if not video_urls:
            result = await _search_and_download(
                query=topic,
                downloader=downloader,
                output_dir=str(output_dir),
                filename="drama_00",
                max_duration=15,
            )
            if result:
                _, _, info = result
                video_urls = [info.get("url", "")]

        for i, url in enumerate(video_urls[:2]):
            filename = f"drama_{i:02d}"
            dl_result = await downloader.download_clip(
                url=url,
                output_dir=str(output_dir),
                filename=filename,
                max_duration=15,
            )
            if dl_result:
                clip_path, audio_path = dl_result
                info = await downloader.get_clip_info(url)
                sc = SourceClip(
                    platform=info.get("platform", "other") if info else "other",
                    original_url=url,
                    creator_name=info.get("uploader", "") if info else "",
                    clip_title=info.get("title", "") if info else "",
                    file_path=clip_path,
                    audio_path=audio_path,
                    duration_seconds=info.get("duration", 0) if info else 0,
                    sequence_number=i + 1,
                    view_count=info.get("view_count", 0) if info else 0,
                )
                source_clips.append(sc)
                visual_assets.append(VisualAsset(
                    sequence_number=i + 1,
                    asset_type="source_clip",
                    search_query=topic,
                    file_path=clip_path,
                    duration_seconds=10,
                ))

    ok = sum(1 for sc in source_clips if sc.file_path)
    logger.info(f"Clip sourcing complete: {ok} clips downloaded")

    attribution_texts = []
    if source_clips:
        from prolific.shorts.services.attribution import generate_attribution
        attribution_texts = [generate_attribution(source_clips)]

    return {
        "source_clips": source_clips,
        "visual_assets": visual_assets,
        "attribution_texts": attribution_texts,
        "current_phase": "script_writing",
        "messages": [AIMessage(content=f"Downloaded {ok} source clips")],
    }


def _is_video_url(url: str) -> bool:
    """Check if a URL is likely a video platform URL (not a news article)."""
    u = url.lower()
    if u.startswith("ytsearch:"):
        return True
    if "twitch.tv" in u and "/clip/" in u:
        return True
    if "clips.twitch.tv/" in u:
        return True
    if "kick.com/clip/" in u or "clips.kick.com/" in u:
        return True
    video_domains = [
        "youtube.com/watch", "youtu.be/", "youtube.com/shorts/",
        "v.redd.it/", "tiktok.com/",
    ]
    return any(d in u for d in video_domains)


async def _download_best_clip(urls, search_topic, downloader, output_dir, filename, max_duration):
    """Try URLs first, then search if none work. Returns (path, audio_path, info) or None."""
    for url in urls:
        dl_result = await downloader.download_clip(url, output_dir, filename, max_duration)
        if dl_result:
            clip_path, audio_path = dl_result
            info = await downloader.get_clip_info(url)
            return clip_path, audio_path, info

    return await _search_and_download(search_topic, downloader, output_dir, filename, max_duration)


async def _search_and_download(query, downloader, output_dir, filename, max_duration):
    """Search YouTube and download the best clip. Returns (path, audio_path, info) or None."""
    try:
        result = await downloader.search_and_download(
            query=query,
            output_dir=output_dir,
            filename=filename,
            max_results=5,
            max_duration=max_duration,
        )
        if result is None:
            return None
        path, info = result
        if path is None:
            return None
        audio_path = str(Path(path).parent / f"{Path(path).stem}_audio.aac")
        if not Path(audio_path).exists():
            audio_path = ""
        return path, audio_path, info
    except Exception as e:
        logger.warning(f"Search and download failed for '{query}': {e}")
        return None
