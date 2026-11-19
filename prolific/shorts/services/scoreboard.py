import asyncio
import logging
import statistics
from datetime import datetime, timedelta, timezone

from prolific.core.config import settings

logger = logging.getLogger(__name__)

_IGNORED_THEMES = {
    "animal-behavior", "history-detail", "science-curio", "horror-fact",
    "general", "miscellaneous", "fact", "facts", "story", "stories",
    "history", "science", "topic", "topics", "video", "videos",
}


def rank_shorts(
    rows: list[dict],
    max_winners: int = 8,
    max_duds: int = 8,
    winner_ratio: float = 1.3,
    dud_ratio: float = 0.25,
    dud_floor: int = 100,
    theme_min_count: int = 2,
) -> dict:
    if not rows:
        return {}
    median = statistics.median(r["views"] for r in rows)
    ordered = sorted(rows, key=lambda r: r["views"], reverse=True)
    winners = [r for r in ordered if r["views"] >= winner_ratio * median][:max_winners]
    dud_cut = max(dud_floor, dud_ratio * median)
    duds = sorted((r for r in rows if r["views"] < dud_cut), key=lambda r: r["views"])[:max_duds]

    by_theme: dict[str, list[int]] = {}
    for r in rows:
        for theme in {t.strip().lower() for t in r.get("themes", []) if t}:
            if theme not in _IGNORED_THEMES:
                by_theme.setdefault(theme, []).append(r["views"])
    theme_ratios = {
        theme: statistics.median(views) / median
        for theme, views in by_theme.items()
        if len(views) >= theme_min_count and median > 0
    }
    winning_themes = sorted(((t, x) for t, x in theme_ratios.items() if x >= 1.4), key=lambda tx: -tx[1])[:6]
    dead_themes = sorted(((t, x) for t, x in theme_ratios.items() if x <= 0.5), key=lambda tx: tx[1])[:6]
    return {
        "count": len(rows),
        "median": median,
        "winners": winners,
        "duds": duds,
        "winning_themes": winning_themes,
        "dead_themes": dead_themes,
    }


def format_scoreboard(board: dict, days: int) -> str:
    if not board:
        return ""
    lines = [
        f"CHANNEL SCOREBOARD (last {days} days, {board['count']} shorts, median {board['median']:,.0f} views per short).",
        "",
        "WHAT IS WORKING. Make more stories of the same kind as these, each with a NEW subject:",
    ]
    lines += [f"- \"{r['title']}\" ({r['views']:,} views)" for r in board["winners"]]
    if board["winning_themes"]:
        lines.append("Winning themes: " + ", ".join(f"{t} ({x:.1f}x the median)" for t, x in board["winning_themes"]))
    lines += ["", "WHAT IS DEAD. Never make anything like these again:"]
    lines += [f"- \"{r['title']}\" ({r['views']:,} views)" for r in board["duds"]]
    if board["dead_themes"]:
        lines.append("Dead themes: " + ", ".join(f"{t} ({x:.1f}x the median)" for t, x in board["dead_themes"]))
    lines.append(
        "Also dead every time: 'X was alive or existed when Y happened' timeline comparisons "
        "(mammoths and pyramids, samurai and trains). Never pitch one."
    )
    return "\n".join(lines)


async def build_scoreboard(days: int = 60, min_age_days: float = 3.0) -> str:
    from prolific.shorts.services.shorts_history import get_shorts_history_service
    from prolific.youtube.services.youtube_analytics import YouTubeAnalyticsService

    records = await get_shorts_history_service().get_past_topics_with_embeddings(limit=300)
    now = datetime.now(timezone.utc)
    recent = []
    for r in records:
        if not r.video_id or r.published_at is None:
            continue
        published = r.published_at if r.published_at.tzinfo else r.published_at.replace(tzinfo=timezone.utc)
        age_days = (now - published).total_seconds() / 86400
        if min_age_days <= age_days <= days:
            recent.append((r, published))
    if len(recent) < 10:
        return ""

    analytics = YouTubeAnalyticsService(credentials_path=settings.shorts_credentials_path)._get_analytics_service()
    start = min(p for _, p in recent).date()
    ids = [r.video_id for r, _ in recent]

    def _query(chunk: list[str]) -> list[list]:
        resp = analytics.reports().query(
            ids="channel==MINE", startDate=str(start), endDate=str(now.date()),
            dimensions="video", filters="video==" + ",".join(chunk),
            metrics="views,engagedViews", maxResults=len(chunk),
        ).execute()
        return resp.get("rows", [])

    loop = asyncio.get_event_loop()
    stats: dict[str, tuple[int, int]] = {}
    for i in range(0, len(ids), 50):
        for row in await loop.run_in_executor(None, _query, ids[i:i + 50]):
            stats[row[0]] = (int(row[1]), int(row[2]))

    rows = [
        {"title": r.title or r.topic, "views": stats.get(r.video_id, (0, 0))[0], "themes": r.cluster_tags or []}
        for r, _ in recent
    ]
    board = rank_shorts(rows)
    text = format_scoreboard(board, days)
    if text:
        logger.info(
            f"Scoreboard: {board['count']} shorts, median {board['median']:.0f}, "
            f"{len(board['winners'])} winners, {len(board['duds'])} duds, "
            f"winning themes {[t for t, _ in board['winning_themes']]}, dead themes {[t for t, _ in board['dead_themes']]}"
        )
    return text
