import argparse
import json
import statistics as st
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

ET = ZoneInfo("America/New_York")
PT = ZoneInfo("America/Los_Angeles")
COHORTS = {
    "old normal (Sep 15 to Oct 14)": (datetime(2026, 9, 15, tzinfo=ET), datetime(2026, 10, 15, tzinfo=ET)),
    "round 1 (Oct 22 to Nov 18)": (datetime(2026, 10, 22, 18, 55, tzinfo=ET), datetime(2026, 11, 19, 0, 13, tzinfo=ET)),
}
STATE_FILE = Path("docs/wait_really_checkin_state.json")


def clients(credentials_path: str):
    creds = Credentials.from_authorized_user_info(json.loads(Path(credentials_path).read_text()))
    if not creds.valid:
        creds.refresh(Request())
    return build("youtube", "v3", credentials=creds), build("youtubeAnalytics", "v2", credentials=creds)


def uploads(yt, limit: int = 400) -> tuple[list[dict], list[dict]]:
    playlist = yt.channels().list(part="contentDetails", mine=True).execute(num_retries=4)["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
    ids, token = [], None
    while len(ids) < limit:
        page = yt.playlistItems().list(part="contentDetails", playlistId=playlist, maxResults=50, pageToken=token).execute(num_retries=4)
        ids += [i["contentDetails"]["videoId"] for i in page["items"]]
        token = page.get("nextPageToken")
        if not token:
            break
    out, problems, seen = [], [], set()
    for i in range(0, len(ids), 50):
        for it in yt.videos().list(part="snippet,status,statistics,contentDetails", id=",".join(ids[i:i + 50])).execute(num_retries=4)["items"]:
            seen.add(it["id"])
            status, title = it["status"], it["snippet"]["title"]
            if status.get("uploadStatus") in ("rejected", "failed", "deleted"):
                problems.append({"id": it["id"], "title": title, "issue": f"{status.get('uploadStatus')}: {status.get('rejectionReason') or status.get('failureReason', '')}"})
            restriction = it.get("contentDetails", {}).get("regionRestriction")
            if restriction:
                problems.append({"id": it["id"], "title": title, "issue": f"region restriction {json.dumps(restriction)[:120]}"})
            if status["privacyStatus"] != "public":
                continue
            out.append({
                "id": it["id"],
                "title": title,
                "published": datetime.fromisoformat(it["snippet"]["publishedAt"].replace("Z", "+00:00")).astimezone(ET),
                "views": int(it["statistics"].get("viewCount", 0)),
                "comments": int(it["statistics"].get("commentCount", 0)),
                "real_clips": real_clip_credits(it["snippet"].get("description", "")),
            })
    for vid in ids:
        if vid not in seen:
            problems.append({"id": vid, "title": "", "issue": "in the uploads playlist but not returned by videos.list (removed?)"})
    return sorted(out, key=lambda v: v["published"]), problems


def real_clip_credits(description: str) -> list[str]:
    if "Footage credits:" not in description:
        return []
    tail = description.split("Footage credits:", 1)[1]
    return [line.strip() for line in tail.splitlines() if line.strip().startswith("- ") or "youtube.com" in line or "youtu.be" in line]


def daily_curve(ya, video: dict, days: int = 7) -> list[tuple[float, float]]:
    pub_pt = video["published"].astimezone(PT)
    rows = ya.reports().query(
        ids="channel==MINE", startDate=str(pub_pt.date()), endDate=str(pub_pt.date() + timedelta(days=days)),
        dimensions="day", sort="day", filters=f"video=={video['id']}", metrics="views",
    ).execute(num_retries=4).get("rows", [])
    by_day = {r[0]: r[1] for r in rows}
    curve, total = [(0.0, 0.0)], 0.0
    for k in range(days + 1):
        total += by_day.get(str(pub_pt.date() + timedelta(days=k)), 0)
        end_of_day = datetime.combine(pub_pt.date() + timedelta(days=k + 1), datetime.min.time(), tzinfo=PT)
        curve.append(((end_of_day - pub_pt).total_seconds() / 86400, total))
    return curve


def at_age(curve: list[tuple[float, float]], age: float) -> float:
    for (a0, c0), (a1, c1) in zip(curve, curve[1:]):
        if a0 <= age <= a1:
            return c0 + (c1 - c0) * (age - a0) / (a1 - a0) if a1 > a0 else c1
    return curve[-1][1]


def hook_rates(ya, ids: list[str], start: date, end: date) -> dict[str, float]:
    out = {}
    for i in range(0, len(ids), 50):
        chunk = ids[i:i + 50]
        rows = ya.reports().query(
            ids="channel==MINE", startDate=str(start), endDate=str(end), dimensions="video",
            filters="video==" + ",".join(chunk), maxResults=50, metrics="views,engagedViews",
        ).execute(num_retries=4).get("rows", [])
        for r in rows:
            if r[1] >= 50:
                out[r[0]] = 100 * r[2] / r[1]
    return out


def new_comments(yt, videos: list[dict], since: datetime) -> list[dict]:
    found = []
    for v in videos:
        if v["comments"] == 0:
            continue
        try:
            resp = yt.commentThreads().list(part="snippet", videoId=v["id"], maxResults=20, order="time").execute(num_retries=4)
        except Exception:
            continue
        for item in resp.get("items", []):
            top = item["snippet"]["topLevelComment"]["snippet"]
            when = datetime.fromisoformat(top["publishedAt"].replace("Z", "+00:00")).astimezone(ET)
            if when > since:
                found.append({
                    "video": v["title"], "author": top.get("authorDisplayName", ""), "text": top.get("textOriginal", ""),
                    "likes": top.get("likeCount", 0), "replies": item["snippet"].get("totalReplyCount", 0), "when": when,
                })
    return sorted(found, key=lambda c: c["when"])


def main() -> None:
    parser = argparse.ArgumentParser(description="Wait Really check-in: pipeline health, same-age performance, hook rate, comments.")
    parser.add_argument("--credentials", default="youtube_credentials.json")
    parser.add_argument("--start", default="2026-11-19T00:13", help="start of the version under test, ET")
    parser.add_argument("--slots", default="10,15,20", help="upload hours ET")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=ET)
    now = datetime.now(ET)
    yt, ya = clients(args.credentials)
    videos, problems = uploads(yt)
    current = [v for v in videos if v["published"] >= start]
    state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
    public_ids = {v["id"] for v in videos}
    for vid in state.get("public_ids", []):
        if vid not in public_ids and not any(p["id"] == vid for p in problems):
            problems.append({"id": vid, "title": "", "issue": "was public at the last check-in, now missing"})

    expected = 0
    slots = [int(h) for h in args.slots.split(",")]
    day = start.date()
    while day <= now.date():
        for h in slots:
            t = datetime(day.year, day.month, day.day, h, 5, tzinfo=ET)
            if start <= t <= now:
                expected += 1
        day += timedelta(days=1)
    print(f"Wait Really check-in, {now:%a %b %d %H:%M} ET. Version under test since {start:%b %d %H:%M} ET.")
    print(f"Pipeline: {len(current)} shorts published, {expected} slots expected.")

    curves = {}
    for name, (a, b) in COHORTS.items():
        cohort = [v for v in videos if a <= v["published"] < b and (now - v["published"]).days >= 8]
        curves[name] = [daily_curve(ya, v) for v in cohort]
    print("\n| Short | Age (days) | Views | Real clips | " + " | ".join(f"Typical {n} at same age" for n in COHORTS) + " |")
    print("| --- | --- | --- | --- | " + " | ".join("---" for _ in COHORTS) + " |")
    ratios = {n: [] for n in COHORTS}
    for v in current:
        age = (now - v["published"]).total_seconds() / 86400
        cells = []
        for name in COHORTS:
            typical = st.median(at_age(c, age) for c in curves[name]) if curves[name] else 0
            cells.append(f"{typical:,.0f}")
            if age >= 1.0 and typical > 0:
                ratios[name].append(v["views"] / typical)
        print(f"| {v['published']:%m-%d %H}h {v['title'][:55]} | {age:.1f} | {v['views']:,} | {len(v['real_clips'])} | " + " | ".join(cells) + " |")
    for name, r in ratios.items():
        if r:
            print(f"Median of new shorts (1+ days old) vs {name}: {st.median(r):.2f}x (n={len(r)})")
    split = {"with real clips": [], "without real clips": []}
    first_name = next(iter(COHORTS))
    for v in current:
        age = (now - v["published"]).total_seconds() / 86400
        if age >= 1.0 and curves[first_name]:
            typical = st.median(at_age(c, age) for c in curves[first_name])
            if typical > 0:
                split["with real clips" if v["real_clips"] else "without real clips"].append(v["views"] / typical)
    if split["with real clips"]:
        print("Real clips: " + ", ".join(f"{k} {st.median(r):.2f}x (n={len(r)})" for k, r in split.items() if r) + f" vs {first_name}")
    for v in current:
        for credit in v["real_clips"]:
            print(f"  real clip in {v['id']} ({v['title'][:40]}): {credit[:120]}")

    print(f"\nVideo status problems: {len(problems)}")
    for p in problems:
        print(f"- {p['id']} {p['title'][:50]}: {p['issue']}")

    rates = hook_rates(ya, [v["id"] for v in current], start.date(), now.date())
    old = [v for v in videos if COHORTS["old normal (Sep 15 to Oct 14)"][0] <= v["published"] < COHORTS["old normal (Sep 15 to Oct 14)"][1]]
    old_rates = hook_rates(ya, [v["id"] for v in old], date(2026, 9, 15), now.date())
    if rates:
        print(f"Hook rate (engaged views / views): new {st.median(rates.values()):.1f}% (n={len(rates)}) vs old normal {st.median(old_rates.values()):.1f}%")

    since = datetime.fromisoformat(state["last_checkin"]) if state.get("last_checkin") else now - timedelta(days=7)
    recent = [v for v in videos if v["published"] >= now - timedelta(days=30)]
    comments = new_comments(yt, recent, since)
    print(f"\nNew comments since {since:%b %d %H:%M} ET: {len(comments)}")
    for c in comments[-25:]:
        print(f"- [{c['video'][:40]}] {c['author']}: {c['text'][:160]!r} (likes {c['likes']}, replies {c['replies']})")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps({"last_checkin": now.isoformat(), "public_ids": sorted(public_ids)}, indent=2))


if __name__ == "__main__":
    main()
