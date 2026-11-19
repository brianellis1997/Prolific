import argparse
import json
import re
import statistics as st
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ET = ZoneInfo("America/New_York")
EXPERIMENT_START: datetime | None = datetime(2026, 10, 22, 18, 55, tzinfo=ET)
BASELINE_START = datetime(2026, 8, 1, tzinfo=ET)
MATURE_DAYS = 7
PASS_MEDIAN = 1200
CHANNEL_START = date(2026, 3, 24)


def _clients(credentials_path: str):
    creds = Credentials.from_authorized_user_info(json.loads(Path(credentials_path).read_text()))
    if not creds.valid:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds), build("youtubeAnalytics", "v2", credentials=creds)


def _uploads(yt) -> dict[str, dict]:
    channel = yt.channels().list(part="contentDetails", mine=True).execute()["items"][0]
    playlist = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while True:
        page = yt.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50, pageToken=token).execute()
        ids += [item["contentDetails"]["videoId"] for item in page["items"]]
        token = page.get("nextPageToken")
        if not token:
            break
    videos = {}
    for i in range(0, len(ids), 50):
        batch = yt.videos().list(part="snippet,status,statistics,contentDetails", id=",".join(ids[i:i + 50])).execute()
        for item in batch["items"]:
            if item["status"]["privacyStatus"] != "public":
                continue
            videos[item["id"]] = {
                "title": item["snippet"]["title"],
                "published": datetime.fromisoformat(item["snippet"]["publishedAt"].replace("Z", "+00:00")).astimezone(ET),
                "views": int(item["statistics"].get("viewCount", 0)),
            }
    return videos


def _per_video_analytics(ya, video_ids: list[str], end: date) -> dict[str, dict]:
    out = {}
    for i in range(0, len(video_ids), 50):
        chunk = video_ids[i:i + 50]
        report = ya.reports().query(
            ids="channel==MINE", startDate=str(CHANNEL_START), endDate=str(end), dimensions="video",
            filters="video==" + ",".join(chunk), maxResults=50,
            metrics="views,engagedViews,averageViewPercentage,subscribersGained",
        ).execute()
        cols = [h["name"] for h in report["columnHeaders"]]
        for row in report.get("rows", []):
            out[row[0]] = dict(zip(cols, row))
    return out


def _channel_daily(ya, start: date, end: date) -> list[list]:
    report = ya.reports().query(
        ids="channel==MINE", startDate=str(start), endDate=str(end), dimensions="day", sort="day",
        metrics="views,engagedViews,subscribersGained,subscribersLost",
    ).execute()
    return report.get("rows", [])


def _summary(shorts: list[dict]) -> dict:
    if not shorts:
        return {}
    views = [s["views"] for s in shorts]
    hooks = [s["hook_rate"] for s in shorts if s["hook_rate"] is not None]
    return {
        "n": len(shorts),
        "median_views": st.median(views),
        "p75_views": sorted(views)[int(0.75 * (len(views) - 1))],
        "pct_over_1k": 100 * sum(v > 1000 for v in views) / len(views),
        "pct_under_100": 100 * sum(v < 100 for v in views) / len(views),
        "median_hook_rate": st.median(hooks) if hooks else None,
        "subs_per_short": st.mean(s["subs"] for s in shorts),
    }


def _row(label: str, s: dict) -> str:
    if not s:
        return f"| {label} | 0 | | | | | | |"
    hook = f"{s['median_hook_rate']:.1f}%" if s["median_hook_rate"] is not None else ""
    return (
        f"| {label} | {s['n']} | {s['median_views']:,.0f} | {s['p75_views']:,} | {s['pct_over_1k']:.0f}% | "
        f"{s['pct_under_100']:.0f}% | {hook} | {s['subs_per_short']:.2f} |"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait Really experiment report: baseline vs experiment cohorts of shorts.")
    parser.add_argument("--credentials", default="youtube_credentials.json")
    parser.add_argument("--start", default=EXPERIMENT_START.isoformat() if EXPERIMENT_START else None,
                        help="experiment start (the deploy time), ISO datetime in ET")
    args = parser.parse_args()
    if not args.start:
        parser.error("the changes are not live yet: pass --start with the deploy time, or set EXPERIMENT_START")

    start = datetime.fromisoformat(args.start)
    if start.tzinfo is None:
        start = start.replace(tzinfo=ET)
    now = datetime.now(ET)
    yt, ya = _clients(args.credentials)
    videos = _uploads(yt)
    stats = _per_video_analytics(ya, list(videos), now.date())

    shorts = []
    for vid, meta in videos.items():
        a = stats.get(vid, {})
        analytic_views = a.get("views", 0)
        shorts.append({
            "id": vid,
            "title": meta["title"],
            "published": meta["published"],
            "age_days": (now - meta["published"]).total_seconds() / 86400,
            "views": meta["views"],
            "hook_rate": 100 * a["engagedViews"] / analytic_views if analytic_views >= 50 and "engagedViews" in a else None,
            "subs": a.get("subscribersGained", 0),
        })

    baseline = [s for s in shorts if BASELINE_START <= s["published"] < start and s["age_days"] >= MATURE_DAYS]
    experiment = [s for s in shorts if s["published"] >= start]
    mature = [s for s in experiment if s["age_days"] >= MATURE_DAYS]

    print(f"Wait Really experiment report, {now:%Y-%m-%d %H:%M} ET (experiment start {start:%b %d %H:%M} ET)\n")
    print("| Cohort | Shorts | Median views | p75 views | Over 1k | Under 100 | Median hook rate | Subs per short |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    print(_row(f"Baseline ({BASELINE_START:%b %d} to {start:%b %d})", _summary(baseline)))
    print(_row(f"Experiment, {MATURE_DAYS}+ days old", _summary(mature)))
    print(_row("Experiment, all so far", _summary(experiment)))

    if mature:
        verdict = "PASS" if _summary(mature)["median_views"] >= PASS_MEDIAN else "below the bar"
        print(f"\nMedian of mature experiment shorts vs the {PASS_MEDIAN:,} bar: {verdict}")

    print("\n| Slot (ET) | Baseline median | Experiment median (7+ days) |")
    print("| --- | --- | --- |")
    for hour in sorted({s["published"].hour for s in baseline + mature}):
        b = [s["views"] for s in baseline if s["published"].hour == hour]
        e = [s["views"] for s in mature if s["published"].hour == hour]
        print(f"| {hour:02d}:00 | {st.median(b):,.0f} (n={len(b)}) |" if b else f"| {hour:02d}:00 | |", end="")
        print(f" {st.median(e):,.0f} (n={len(e)}) |" if e else " |")

    daily = _channel_daily(ya, (start - timedelta(days=28)).date(), now.date())
    before = [r for r in daily if r[0] < start.date().isoformat()]
    after = [r for r in daily if r[0] > start.date().isoformat()]
    if before and after:
        print(f"\nChannel views per day: {sum(r[1] for r in before) / len(before):,.0f} in the 28 days before, "
              f"{sum(r[1] for r in after) / len(after):,.0f} since (analytics lag about 2 days)")

    if experiment:
        print("\nExperiment shorts, newest first:")
        for s in sorted(experiment, key=lambda s: s["published"], reverse=True)[:30]:
            hook = f"{s['hook_rate']:.0f}%" if s["hook_rate"] is not None else "n/a"
            print(f"  {s['published']:%m-%d %H:%M} {s['views']:>6,} views  hook {hook:>4}  {re.sub(r'\s+', ' ', s['title'])[:70]}")


if __name__ == "__main__":
    main()
