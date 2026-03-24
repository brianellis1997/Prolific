"""YouTube Analytics API service for performance tracking and topic feedback."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, UTC
from pathlib import Path

from prolific.core.config import settings

logger = logging.getLogger(__name__)


@dataclass
class VideoPerformance:
    video_id: str
    title: str
    topic: str
    views: int = 0
    estimated_minutes_watched: float = 0.0
    average_view_duration_seconds: float = 0.0
    impressions: int = 0
    ctr: float = 0.0
    likes: int = 0
    subscribers_gained: int = 0
    is_biography: bool = False
    era_tags: list[str] = field(default_factory=list)
    region_tags: list[str] = field(default_factory=list)


@dataclass
class ChannelInsights:
    total_videos_analyzed: int = 0
    avg_views: float = 0.0
    avg_ctr: float = 0.0
    avg_watch_minutes: float = 0.0
    top_performers: list[VideoPerformance] = field(default_factory=list)
    worst_performers: list[VideoPerformance] = field(default_factory=list)
    biography_avg_views: float = 0.0
    broad_topic_avg_views: float = 0.0
    era_performance: dict[str, float] = field(default_factory=dict)
    region_performance: dict[str, float] = field(default_factory=dict)
    summary: str = ""


class YouTubeAnalyticsService:
    def __init__(self, credentials_path: str | None = None):
        self.credentials_path = credentials_path or settings.youtube_credentials_path

    def _get_analytics_service(self):
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds_data = json.loads(Path(self.credentials_path).read_text())
        credentials = Credentials(
            token=creds_data.get("token"),
            refresh_token=creds_data.get("refresh_token"),
            token_uri=creds_data.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=creds_data.get("client_id"),
            client_secret=creds_data.get("client_secret"),
        )
        return build("youtubeAnalytics", "v2", credentials=credentials)

    async def get_video_performance(
        self,
        video_id: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict:
        import asyncio

        if not start_date:
            start_date = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now(UTC).strftime("%Y-%m-%d")

        analytics = self._get_analytics_service()

        def _query():
            return analytics.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,likes,subscribersGained",
                filters=f"video=={video_id}",
            ).execute()

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _query)

        rows = response.get("rows", [])
        if not rows:
            return {}

        row = rows[0]
        return {
            "views": int(row[0]),
            "estimated_minutes_watched": float(row[1]),
            "average_view_duration_seconds": float(row[2]),
            "likes": int(row[3]),
            "subscribers_gained": int(row[4]),
        }

    async def get_all_video_stats(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
        max_results: int = 50,
    ) -> list[dict]:
        import asyncio

        if not start_date:
            start_date = (datetime.now(UTC) - timedelta(days=90)).strftime("%Y-%m-%d")
        if not end_date:
            end_date = datetime.now(UTC).strftime("%Y-%m-%d")

        analytics = self._get_analytics_service()

        def _query():
            return analytics.reports().query(
                ids="channel==MINE",
                startDate=start_date,
                endDate=end_date,
                metrics="views,estimatedMinutesWatched,averageViewDuration,likes,subscribersGained",
                dimensions="video",
                sort="-views",
                maxResults=max_results,
            ).execute()

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _query)

        results = []
        for row in response.get("rows", []):
            results.append({
                "video_id": row[0],
                "views": int(row[1]),
                "estimated_minutes_watched": float(row[2]),
                "average_view_duration_seconds": float(row[3]),
                "likes": int(row[4]),
                "subscribers_gained": int(row[5]),
            })
        return results

    async def get_channel_insights(self, db_path: str | None = None, table: str = "videos") -> ChannelInsights:
        import aiosqlite

        video_stats = await self.get_all_video_stats()

        if not video_stats:
            return ChannelInsights(summary="No analytics data available yet.")

        video_id_to_stats = {s["video_id"]: s for s in video_stats}

        history_db = db_path or settings.youtube_history_db_path
        async with aiosqlite.connect(history_db) as db:
            db.row_factory = aiosqlite.Row
            if table == "shorts":
                cursor = await db.execute(
                    "SELECT youtube_video_id, topic, topic as title, 0 as is_biography, '[]' as era_tags, '[]' as region_tags "
                    "FROM shorts WHERE youtube_video_id IS NOT NULL AND youtube_video_id != ''"
                )
            else:
                cursor = await db.execute(
                    "SELECT youtube_video_id, topic, title, is_biography, era_tags, region_tags "
                    "FROM videos WHERE youtube_video_id IS NOT NULL AND youtube_video_id != ''"
                )
            rows = await cursor.fetchall()

        performances = []
        for row in rows:
            vid = row["youtube_video_id"]
            stats = video_id_to_stats.get(vid)
            if not stats:
                continue
            performances.append(VideoPerformance(
                video_id=vid,
                title=row["title"],
                topic=row["topic"],
                views=stats["views"],
                estimated_minutes_watched=stats["estimated_minutes_watched"],
                average_view_duration_seconds=stats["average_view_duration_seconds"],
                likes=stats["likes"],
                subscribers_gained=stats["subscribers_gained"],
                is_biography=bool(row["is_biography"]),
                era_tags=json.loads(row["era_tags"]) if row["era_tags"] else [],
                region_tags=json.loads(row["region_tags"]) if row["region_tags"] else [],
            ))

        if not performances:
            return ChannelInsights(summary="No matching analytics data for published videos.")

        total = len(performances)
        avg_views = sum(p.views for p in performances) / total
        avg_watch = sum(p.estimated_minutes_watched for p in performances) / total

        sorted_by_views = sorted(performances, key=lambda p: p.views, reverse=True)
        top = sorted_by_views[:3]
        worst = sorted_by_views[-3:] if total > 3 else []

        bios = [p for p in performances if p.is_biography]
        broad = [p for p in performances if not p.is_biography]
        bio_avg = sum(p.views for p in bios) / len(bios) if bios else 0
        broad_avg = sum(p.views for p in broad) / len(broad) if broad else 0

        era_views: dict[str, list[int]] = {}
        region_views: dict[str, list[int]] = {}
        for p in performances:
            for era in p.era_tags:
                era_views.setdefault(era, []).append(p.views)
            for region in p.region_tags:
                region_views.setdefault(region, []).append(p.views)

        era_perf = {k: sum(v) / len(v) for k, v in era_views.items() if len(v) >= 1}
        region_perf = {k: sum(v) / len(v) for k, v in region_views.items() if len(v) >= 1}

        summary_lines = [f"Channel performance across {total} videos (last 90 days):"]
        summary_lines.append(f"- Average views: {avg_views:.0f}")
        summary_lines.append(f"- Average watch time: {avg_watch:.0f} minutes")

        if bios and broad:
            summary_lines.append(f"- Biography videos avg {bio_avg:.0f} views vs broad topics avg {broad_avg:.0f} views")
            if bio_avg > broad_avg * 1.2:
                summary_lines.append("  -> Biographies are significantly outperforming broad topics")
            elif broad_avg > bio_avg * 1.2:
                summary_lines.append("  -> Broad topics are significantly outperforming biographies")

        summary_lines.append("\nTop performers:")
        for p in top:
            summary_lines.append(f"  - \"{p.topic}\" ({p.views} views, {p.estimated_minutes_watched:.0f}min watched)")

        if worst and total > 5:
            summary_lines.append("\nUnderperformers:")
            for p in worst:
                summary_lines.append(f"  - \"{p.topic}\" ({p.views} views)")

        if era_perf:
            sorted_eras = sorted(era_perf.items(), key=lambda x: x[1], reverse=True)
            summary_lines.append("\nPerformance by era:")
            for era, avg in sorted_eras[:5]:
                summary_lines.append(f"  - {era}: {avg:.0f} avg views")

        if region_perf:
            sorted_regions = sorted(region_perf.items(), key=lambda x: x[1], reverse=True)
            summary_lines.append("\nPerformance by region:")
            for region, avg in sorted_regions[:5]:
                summary_lines.append(f"  - {region}: {avg:.0f} avg views")

        insights = ChannelInsights(
            total_videos_analyzed=total,
            avg_views=avg_views,
            avg_watch_minutes=avg_watch,
            top_performers=top,
            worst_performers=worst,
            biography_avg_views=bio_avg,
            broad_topic_avg_views=broad_avg,
            era_performance=era_perf,
            region_performance=region_perf,
            summary="\n".join(summary_lines),
        )

        logger.info(f"Channel insights: {total} videos analyzed, avg {avg_views:.0f} views")
        return insights


_analytics_service: YouTubeAnalyticsService | None = None


def get_youtube_analytics_service() -> YouTubeAnalyticsService:
    global _analytics_service
    if _analytics_service is None:
        _analytics_service = YouTubeAnalyticsService()
    return _analytics_service
