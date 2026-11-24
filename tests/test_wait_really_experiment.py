from collections import Counter
from datetime import datetime, timedelta, timezone
from math import gcd

from prolific.core.config import settings
from prolific.services.topic_dedup import (
    PastTopicEmbedding,
    _SHORTS_CATEGORY_ROTATION,
    check_cluster_overlap,
    pick_current_category,
)
from prolific.shorts.nodes.clip_director import ClipShot, pace_shots
from prolific.shorts.nodes.script_writing import clean_on_screen_hook, hook_problem
from prolific.shorts.nodes.video_assembly import planned_clip_seconds
from prolific.shorts.schemas import CaptionSegment
from prolific.shorts.scheduler import _parse_schedule_hours
from prolific.shorts.services.caption import CaptionService, hook_display_end


def test_rotation_weights_and_slot_independence():
    counts = Counter(_SHORTS_CATEGORY_ROTATION)
    assert counts == {"animal_behavior": 3, "history_detail": 2, "science_curio": 2}
    assert gcd(len(_SHORTS_CATEGORY_ROTATION), len(_parse_schedule_hours())) == 1
    assert pick_current_category(0)["key"] == "animal_behavior"
    assert pick_current_category(7)["key"] == pick_current_category(0)["key"]


def test_schedule_spaces_shorts_five_hours_apart():
    assert settings.shorts_cron_hours == "10,15,20"
    assert _parse_schedule_hours() == [10, 15, 20]


def test_theme_cooldown_leaves_room_for_animals():
    assert settings.shorts_cluster_cooldown_days == 3


def _past(tags, days_ago=1):
    return PastTopicEmbedding(
        video_id="abc",
        topic="Coca-Cola is older than the country of Italy",
        title="Coca-Cola is older than the country of Italy",
        published_at=datetime.now(timezone.utc) - timedelta(days=days_ago),
        embedding=None,
        cluster_tags=tags,
    )


def test_cluster_gate_ignores_rotation_category_tags():
    past = [_past(["history-detail", "timeline-overlap"])]
    assert not check_cluster_overlap(["history-detail", "inventions"], past, cooldown_days=7).is_dupe
    assert check_cluster_overlap(["timeline-overlap"], past, cooldown_days=7).is_dupe
    assert not check_cluster_overlap(["timeline-overlap"], [_past(["timeline-overlap"], days_ago=9)], cooldown_days=7).is_dupe


def _shot(seq, start, end, asset_type="stock_clip"):
    return ClipShot(sequence_number=seq, start_time=start, end_time=end, search_query=f"q{seq}", asset_type=asset_type)


def test_pace_shots_cuts_every_few_seconds_and_stays_contiguous():
    shots = [_shot(1, 0.2, 5.1), _shot(2, 5.1, 11.7), _shot(3, 11.7, 15.4, "web_image"), _shot(4, 15.4, 21.3)]
    word_starts = [round(0.2 + 0.35 * i, 2) for i in range(60)]
    paced = pace_shots(shots, word_starts, audio_duration=21.0)
    assert paced[0].start_time == 0.0
    assert paced[0].end_time - paced[0].start_time <= 2.6
    assert abs(paced[-1].end_time - 21.3) < 1e-9
    for a, b in zip(paced, paced[1:]):
        assert abs(a.end_time - b.start_time) < 1e-9
    for s in paced:
        length = s.end_time - s.start_time
        assert length >= 1.2
        if s.asset_type == "stock_clip":
            assert length <= 3.6
    assert [s.sequence_number for s in paced] == list(range(1, len(paced) + 1))
    assert any(s.asset_type == "web_image" and s.end_time - s.start_time > 3.6 for s in paced)


def test_pace_shots_merges_slivers():
    shots = [_shot(1, 0.0, 2.0), _shot(2, 2.0, 2.5), _shot(3, 2.5, 5.0)]
    paced = pace_shots(shots, [0.0, 1.0, 2.0, 2.5, 3.5], audio_duration=4.7)
    assert all(s.end_time - s.start_time >= 1.2 for s in paced)
    assert paced[-1].end_time == 5.0


def test_planned_clip_seconds_compensates_crossfade():
    assert planned_clip_seconds([2.0, 3.0, 2.5], crossfade=0.15, tail=0.5) == [2.15, 3.15, 3.0]
    assert planned_clip_seconds([]) == []


def test_hook_rules():
    assert hook_problem("Octopuses punch fish just because they're annoyed. Scientists filmed it.") == ""
    assert "words" in hook_problem("You could have taken a train to see the last Samurai while people were dying on the Oregon Trail.")
    assert "slow setup" in hook_problem("You think the guillotine is ancient history.")
    assert "slow setup" in hook_problem("Imagine a wasp that never forgets.")


def test_on_screen_hook_cleanup():
    assert clean_on_screen_hook("octopuses {hold} grudges", "") == "OCTOPUSES HOLD GRUDGES"
    assert clean_on_screen_hook("", "Wasps never forget a face. They hold grudges.") == "WASPS NEVER FORGET A FACE"
    assert clean_on_screen_hook("one two three four five six seven eight", "") == "ONE TWO THREE FOUR FIVE SIX SEVEN"
    assert clean_on_screen_hook("", "This sentence is far too long to ever fit on the screen as a hook.") == ""


def _segments(n, step=0.4):
    return [CaptionSegment(word=f"w{i}", start_time=i * step, end_time=i * step + 0.3) for i in range(n)]


def test_hook_display_window():
    assert hook_display_end(_segments(20), 6) == 2.3
    assert hook_display_end(_segments(20), 2) == 2.0
    assert hook_display_end(_segments(20), 12) == 3.2
    assert hook_display_end([], 5) == 3.2


def test_ass_file_carries_hook_only_when_given(tmp_path):
    service = CaptionService(api_key="test")
    with_hook = tmp_path / "with.ass"
    service.generate_ass_subtitles(_segments(8), str(with_hook), hook_text="OCTOPUSES HOLD GRUDGES", hook_end=2.5)
    text = with_hook.read_text()
    assert "Style: Hook," in text
    assert "Dialogue: 1,0:00:00.00,0:00:02.50,Hook,,0,0,0,,{\\fad(0,250)}OCTOPUSES HOLD GRUDGES" in text
    without_hook = tmp_path / "without.ass"
    service.generate_ass_subtitles(_segments(8), str(without_hook))
    assert ",Hook,," not in without_hook.read_text()


def test_scoreboard_ranks_winners_duds_and_themes():
    from prolific.shorts.services.scoreboard import format_scoreboard, rank_shorts

    rows = [{"title": f"Mid {i}", "views": 600 + i, "themes": ["inventions"]} for i in range(10)]
    rows += [
        {"title": "Octopus grudges", "views": 2600, "themes": ["animal-intelligence", "marine-life"]},
        {"title": "Crow faces", "views": 1800, "themes": ["animal-intelligence"]},
        {"title": "Mammoths and pyramids", "views": 18, "themes": ["timeline-overlap"]},
        {"title": "Samurai and trains", "views": 7, "themes": ["timeline-overlap", "history-detail"]},
    ]
    board = rank_shorts(rows)
    assert [r["title"] for r in board["winners"]] == ["Octopus grudges", "Crow faces"]
    assert [r["title"] for r in board["duds"]] == ["Samurai and trains", "Mammoths and pyramids"]
    assert board["winning_themes"][0][0] == "animal-intelligence"
    assert board["dead_themes"][0][0] == "timeline-overlap"
    assert all(t != "history-detail" for t, _ in board["dead_themes"])
    text = format_scoreboard(board, 60)
    assert "WHAT IS WORKING" in text and "WHAT IS DEAD" in text and "timeline comparisons" in text


def test_sound_design_places_whooshes_and_impact_without_riser():
    from prolific.shorts.services.audio_mix import payoff_time_from_script, plan_sfx
    from prolific.shorts.schemas import ShortScript

    events = plan_sfx([2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0], payoff_time=10.5, duration=30.0)
    names = [(n, round(s, 2)) for n, s, _ in events]
    assert ("impact", 10.5) in names and not any(n == "riser" for n, _ in names)
    whooshes = [s for n, s in names if n == "whoosh"]
    assert whooshes == [3.88, 7.88, 11.88]
    script = ShortScript(hook="Octopuses punch fish.", setup="Scientists filmed it.")
    segs = [CaptionSegment(word=f"w{i}", start_time=i * 0.4, end_time=i * 0.4 + 0.3) for i in range(20)]
    assert round(payoff_time_from_script(script, segs), 3) == 2.4


def test_dynamic_captions_highlight_each_spoken_word():
    from prolific.shorts.services.caption import caption_groups, dynamic_caption_events

    segs = [CaptionSegment(word=w, start_time=i * 0.4, end_time=i * 0.4 + 0.3)
            for i, w in enumerate("Bees play ball. Ants farm fungi".split())]
    assert [[s.word for s in g] for g in caption_groups(segs)] == [["Bees", "play", "ball."], ["Ants", "farm", "fungi"]]
    events = dynamic_caption_events(segs, CaptionService._seconds_to_ass_time)
    assert len(events) == 6
    assert "\\fscx86" in events[0] and "{\\c&H0000E1FF&}BEES{\\c&H00FFFFFF&} PLAY BALL" in events[0]
    assert "BEES PLAY {\\c&H0000E1FF&}BALL{\\c&H00FFFFFF&}" in events[2]
    assert "\\fscx86" not in events[1]
    long_words = [CaptionSegment(word=w, start_time=i * 0.4, end_time=i * 0.4 + 0.3)
                  for i, w in enumerate("Octopuses punch fish.".split())]
    assert [[s.word for s in g] for g in caption_groups(long_words)] == [["Octopuses", "punch"], ["fish."]]


def test_motion_filter_zooms_in_and_out():
    from prolific.shorts.nodes.video_assembly import motion_filter

    assert motion_filter(2.0, None) == ""
    zoom_in = motion_filter(2.0, "in")
    assert "eval=frame" in zoom_in and "crop=1080:1920" in zoom_in and "min(t/2.000\\,1)" in zoom_in
    assert "(1-min(t/2.000\\,1))" in motion_filter(2.0, "out")


def test_real_clip_guardrails():
    from prolific.shorts.services.money_shot import excerpt_window, is_blocked_source

    assert is_blocked_source("BBC Earth", "")
    assert is_blocked_source("Nat Geo WILD", "")
    assert is_blocked_source("Some Guy", "For licensing contact licensing@viralhog.com")
    assert not is_blocked_source("EarthSky", "Watch octopuses punch fish")
    assert not is_blocked_source("Creativity Lab", "")
    assert excerpt_window(10.0, 60.0, 5.0) == (8.25, 5.0)
    assert excerpt_window(1.0, 60.0, 5.0) == (0.0, 5.0)
    assert excerpt_window(58.0, 60.0, 5.0) == (55.0, 5.0)
    assert excerpt_window(2.0, 3.0, 5.0) == (0.0, 3.0)


def test_dynamic_captions_never_overlap():
    from prolific.shorts.services.caption import dynamic_caption_events

    segs = [
        CaptionSegment(word="as", start_time=10.0, end_time=10.2),
        CaptionSegment(word="a", start_time=10.2, end_time=10.3),
        CaptionSegment(word="compass", start_time=10.3, end_time=10.8),
        CaptionSegment(word="to", start_time=10.75, end_time=10.9),
        CaptionSegment(word="map", start_time=10.7, end_time=11.1),
    ]
    events = dynamic_caption_events(segs, lambda s: f"{s:.3f}")
    spans = [(float(e.split(",")[1]), float(e.split(",")[2])) for e in events]
    for (s0, e0), (s1, e1) in zip(spans, spans[1:]):
        assert s1 >= e0 and e1 > s1


def test_web_images_skip_watermarked_stock_sites():
    from prolific.shorts.nodes.image_generation import is_watermarked_source

    assert is_watermarked_source("https://image.shutterstock.com/image-vector/germs-260nw-123.jpg")
    assert is_watermarked_source("https://media.gettyimages.com/id/1/photo.jpg")
    assert not is_watermarked_source("https://upload.wikimedia.org/wikipedia/commons/a/ab/Toilet.jpg")


def test_candidate_vetting_skips_reuploads_and_managed_content():
    from prolific.shorts.services.money_shot import is_reupload, vet_candidate

    def item(title="Octopus hunting at night", description="Filmed on a night dive in Bali.", channel="Reef Diver",
             license="creativeCommon", licensed=False):
        return {"snippet": {"title": title, "description": description, "channelTitle": channel},
                "status": {"license": license}, "contentDetails": {"licensedContent": licensed}}

    assert vet_candidate(item(), "creativeCommon") == ""
    assert vet_candidate(item(license="youtube"), "creativeCommon") == "license is not creativeCommon"
    assert vet_candidate(item(licensed=True), "creativeCommon") == "managed by a Content ID partner"
    assert vet_candidate(item(channel="BBC Earth"), "creativeCommon") == "blocked source"
    assert vet_candidate(item(description="Planet Earth II clip, all credit to the BBC"), "creativeCommon") == "looks like a re-upload"
    assert vet_candidate(item(license="youtube"), "any") == ""
    assert is_reupload("Top 10 craziest octopus moments", "")
    assert is_reupload("Octopus", "I do not own this footage")
    assert is_reupload("Octopus", "Credit: @someone")
    assert is_reupload("Octopus", "© 2024 Ocean Films")
    assert not is_reupload("A new discovery: octopus throws shells", "Filmed by our lab team in Sydney")


def test_proxy_port_is_picked_per_download(monkeypatch):
    from prolific.shorts.services import clip_downloader as cd

    monkeypatch.setattr(cd.settings, "ytdlp_proxy", "http://u:p@gw.example.com:{port}")
    monkeypatch.setattr(cd.settings, "ytdlp_proxy_ports", "10000-10002")
    downloader = cd.ClipDownloader.__new__(cd.ClipDownloader)
    seen = {downloader._proxy_args()[1] for _ in range(60)}
    assert seen <= {f"http://u:p@gw.example.com:{p}" for p in (10000, 10001, 10002)} and len(seen) > 1
    monkeypatch.setattr(cd.settings, "ytdlp_proxy", "")
    assert downloader._proxy_args() == []


def test_money_shot_skips_reposters_and_falls_back_to_the_subject(monkeypatch, tmp_path):
    import asyncio

    from prolific.shorts.services import money_shot as ms

    cands = [
        {"url": "u1", "title": "t1", "creator": "Daily Funny Pets", "channel_id": "c1", "license_kind": "cc"},
        {"url": "u2", "title": "t2", "creator": "Zoo A", "channel_id": "c2", "license_kind": "cc"},
        {"url": "u3", "title": "t3", "creator": "Zoo B", "channel_id": "c3", "license_kind": "cc"},
    ]
    downloads, cuts = [], []

    async def search(query, video_license, video_duration="short"):
        if video_duration != "short":
            return []
        return cands if video_license == "creativeCommon" else []

    async def own(cand):
        return cand["channel_id"] != "c1"

    class Downloader:
        async def download_source(self, url, output_dir, filename):
            downloads.append(url)
            path = tmp_path / f"{filename}.mp4"
            path.write_bytes(b"x")
            return str(path)

    async def locate(desc, strip, n, subject=""):
        return False, 2, True, "© Zoo A"

    async def cut(src, out, start, seconds):
        cuts.append((src, start))
        return True

    monkeypatch.setattr(ms.settings, "shorts_money_shot_enabled", True)
    monkeypatch.setattr(ms.settings, "shorts_money_shot_license", "cc_only")
    monkeypatch.setattr(ms, "_own_channel_id", lambda: "own")
    monkeypatch.setattr(ms, "_search_candidates", search)
    monkeypatch.setattr(ms, "_uploader_films_own_footage", own)
    monkeypatch.setattr(ms, "_frames_strip", lambda path, num_frames=6: ("strip", [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]))
    monkeypatch.setattr(ms, "_locate_event", locate)
    monkeypatch.setattr(ms, "_probe_duration", lambda path: 30.0)
    monkeypatch.setattr(ms, "_cut_portrait", cut)
    import prolific.shorts.services.clip_downloader as cd
    monkeypatch.setattr(cd, "get_clip_downloader", lambda: Downloader())

    result = asyncio.run(ms.find_verified_clip("q", "jacana fighting", str(tmp_path), "clip_03", 3.0, max_candidates=2))
    assert downloads == ["u2", "u3"]
    assert result is not None and result.match == "subject" and result.creator == "Zoo A"
    assert len(cuts) == 1 and cuts[0][0].endswith("clip_03_ms1.mp4")
    assert not (tmp_path / "clip_03_ms1.mp4").exists() and not (tmp_path / "clip_03_ms2.mp4").exists()


def test_burned_in_marks_must_name_the_uploader():
    from prolific.shorts.services.money_shot import same_owner

    assert same_owner("", "Anyone")
    assert same_owner("Elizabeth II NP, January 2025 © Pascal Vagner", "Pascal Vagner")
    assert same_owner("@reefdiver", "Reef Diver")
    assert same_owner("Elephant Listening Project", "ElephantListenProj")
    assert not same_owner("African Jacana (Actophilornis africanus)", "Pascal Vagner")
    assert not same_owner("@THEFISHINGMUTTS", "Stella & Chewy's")
    assert not same_owner("ViralHog", "Bob Smith")


def test_letterbox_bars_are_detected(tmp_path):
    import asyncio
    import shutil
    import subprocess

    from prolific.shorts.services.money_shot import _detect_crop

    src = tmp_path / "boxed.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30", "-t", "2",
         "-vf", "pad=640:480:0:60:black", "-pix_fmt", "yuv420p", "-y", str(src)],
        check=True,
    )
    assert asyncio.run(_detect_crop(shutil.which("ffmpeg"), str(src), 0.0, 2.0)) == (640, 360, 0, 60)


def test_fair_use_guardrails_cooldown_cap_and_no_repeat(monkeypatch, tmp_path):
    import asyncio
    from datetime import datetime, timedelta

    from prolific.shorts.services import money_shot as ms

    monkeypatch.setattr(ms.settings, "shorts_history_db_path", str(tmp_path / "shorts_history.sqlite"))
    monkeypatch.setattr(ms, "_own_channel_id", lambda: "")
    ms.record_fair_use_source("old", now=datetime.utcnow() - timedelta(days=40))
    ms.record_fair_use_source("recent", now=datetime.utcnow() - timedelta(days=3))
    assert ms.recent_fair_use_channels() == {"recent"}

    searched = []

    async def search(query, video_license, video_duration="short"):
        if video_duration != "short":
            return []
        searched.append(video_license)
        if video_license == "creativeCommon":
            return []
        return [
            {"url": "f1", "title": "t", "creator": "Recent", "channel_id": "recent", "license_kind": "fair_use"},
            {"url": "f2", "title": "t", "creator": "Used Here", "channel_id": "c2", "license_kind": "fair_use"},
            {"url": "f3", "title": "t", "creator": "Fresh", "channel_id": "c3", "license_kind": "fair_use"},
        ]

    async def own(cand):
        return True

    downloads = []

    class Downloader:
        async def download_source(self, url, output_dir, filename):
            downloads.append(url)
            path = tmp_path / f"{filename}.mp4"
            path.write_bytes(b"x")
            return str(path)

    async def locate(desc, strip, n, subject=""):
        return True, 1, True, ""

    async def cut(src, out, start, seconds):
        return True

    monkeypatch.setattr(ms.settings, "shorts_money_shot_enabled", True)
    monkeypatch.setattr(ms.settings, "shorts_money_shot_license", "fair_use")
    monkeypatch.setattr(ms, "_search_candidates", search)
    monkeypatch.setattr(ms, "_uploader_films_own_footage", own)
    monkeypatch.setattr(ms, "_frames_strip", lambda path, num_frames=6: ("strip", [1.0, 2.0]))
    monkeypatch.setattr(ms, "_locate_event", locate)
    monkeypatch.setattr(ms, "_probe_duration", lambda path: 30.0)
    monkeypatch.setattr(ms, "_cut_portrait", cut)
    import prolific.shorts.services.clip_downloader as cd
    monkeypatch.setattr(cd, "get_clip_downloader", lambda: Downloader())

    result = asyncio.run(ms.find_verified_clip("q", "e", str(tmp_path), "clip_01", 3.0, exclude_urls={"f2"}))
    assert downloads == ["f3"] and result.creator == "Fresh" and result.license_kind == "fair_use"
    assert "c3" in ms.recent_fair_use_channels()

    searched.clear()
    assert asyncio.run(ms.find_verified_clip("q", "e", str(tmp_path), "clip_02", 3.0, allow_fair_use=False)) is None
    assert searched == ["creativeCommon"]


def test_fair_use_event_beats_cc_subject_only(monkeypatch, tmp_path):
    import asyncio

    from prolific.shorts.services import money_shot as ms

    async def search(query, video_license, video_duration="short"):
        if video_duration != "short":
            return []
        if video_license == "creativeCommon":
            return [{"url": "cc1", "title": "t", "creator": "Birder", "channel_id": "a", "license_kind": "cc"},
                    {"url": "cc2", "title": "t", "creator": "Zoo", "channel_id": "b", "license_kind": "cc"}]
        return [{"url": "fu1", "title": "t", "creator": "Filmer", "channel_id": "c", "license_kind": "fair_use"}]

    async def own(cand):
        return True

    downloads = []

    class Downloader:
        async def download_source(self, url, output_dir, filename):
            downloads.append(url)
            path = tmp_path / f"{filename}.mp4"
            path.write_bytes(b"x")
            return str(path)

    async def locate(desc, strip, n, subject=""):
        shows = downloads[-1] == "fu1"
        return shows, 1, True, ""

    async def cut(src, out, start, seconds):
        return True

    monkeypatch.setattr(ms.settings, "shorts_money_shot_enabled", True)
    monkeypatch.setattr(ms.settings, "shorts_money_shot_license", "fair_use")
    monkeypatch.setattr(ms.settings, "shorts_history_db_path", str(tmp_path / "shorts_history.sqlite"))
    monkeypatch.setattr(ms, "_own_channel_id", lambda: "")
    monkeypatch.setattr(ms, "_search_candidates", search)
    monkeypatch.setattr(ms, "_uploader_films_own_footage", own)
    monkeypatch.setattr(ms, "_frames_strip", lambda path, num_frames=6: ("strip", [1.0, 2.0]))
    monkeypatch.setattr(ms, "_locate_event", locate)
    monkeypatch.setattr(ms, "_probe_duration", lambda path: 30.0)
    monkeypatch.setattr(ms, "_cut_portrait", cut)
    import prolific.shorts.services.clip_downloader as cd
    monkeypatch.setattr(cd, "get_clip_downloader", lambda: Downloader())

    result = asyncio.run(ms.find_verified_clip("q", "crows gather around a dead crow", str(tmp_path), "clip_05", 3.0))
    assert downloads == ["cc1", "fu1"]
    assert result.match == "event" and result.license_kind == "fair_use" and result.creator == "Filmer"
    assert not list(tmp_path.glob("clip_05_ms*"))


def test_scene_text_is_the_words_spoken_during_the_shot():
    from prolific.shorts.nodes.stock_clip_sourcing import spoken_words
    from prolific.shorts.schemas import VisualAsset

    words = [CaptionSegment(word=w, start_time=i * 0.5, end_time=i * 0.5 + 0.4)
             for i, w in enumerate("Cows have best friends and panic when farmers pull them apart".split())]
    shot = VisualAsset(sequence_number=6, narration_start=3.0, narration_end=5.5, search_query="cow running to fence")
    assert spoken_words(words, shot) == "when farmers pull them apart"
    dict_words = [{"word": "hello", "start_time": 0.0}]
    empty_shot = VisualAsset(sequence_number=1, narration_start=9.0, narration_end=10.0, search_query="stock query")
    assert spoken_words(dict_words, empty_shot) == "stock query"


def test_fallback_query_is_searched_before_settling_for_the_subject(monkeypatch, tmp_path):
    import asyncio

    from prolific.shorts.services import money_shot as ms

    async def search(query, video_license, video_duration="short"):
        if video_duration != "short":
            return []
        if video_license != "creativeCommon":
            return []
        if query == "cow separated from friend":
            return [{"url": "m1", "title": "t", "creator": "Farm", "channel_id": "a", "license_kind": "cc"}]
        return [{"url": "f1", "title": "t", "creator": "Sanctuary", "channel_id": "b", "license_kind": "cc"}]

    async def own(cand):
        return True

    downloads = []

    class Downloader:
        async def download_source(self, url, output_dir, filename):
            downloads.append(url)
            path = tmp_path / f"{filename}.mp4"
            path.write_bytes(b"x")
            return str(path)

    async def locate(desc, strip, n, subject=""):
        return downloads[-1] == "f1", 1, True, ""

    async def cut(src, out, start, seconds):
        return True

    monkeypatch.setattr(ms.settings, "shorts_money_shot_enabled", True)
    monkeypatch.setattr(ms.settings, "shorts_money_shot_license", "cc_only")
    monkeypatch.setattr(ms.settings, "shorts_history_db_path", str(tmp_path / "shorts_history.sqlite"))
    monkeypatch.setattr(ms, "_own_channel_id", lambda: "")
    monkeypatch.setattr(ms, "_search_candidates", search)
    monkeypatch.setattr(ms, "_uploader_films_own_footage", own)
    monkeypatch.setattr(ms, "_frames_strip", lambda path, num_frames=6: ("strip", [1.0, 2.0]))
    monkeypatch.setattr(ms, "_locate_event", locate)
    monkeypatch.setattr(ms, "_probe_duration", lambda path: 30.0)
    monkeypatch.setattr(ms, "_cut_portrait", cut)
    import prolific.shorts.services.clip_downloader as cd
    monkeypatch.setattr(cd, "get_clip_downloader", lambda: Downloader())

    result = asyncio.run(ms.find_verified_clip(
        "cow separated from friend", "a cow is led away while her friend calls", str(tmp_path), "clip_06", 3.0,
        fallback_query="cows crying for each other",
    ))
    assert downloads == ["m1", "f1"] and result.match == "event" and result.creator == "Sanctuary"


def test_storyboard_grid_reads_tiles_at_the_right_times(tmp_path):
    from PIL import Image

    from prolific.shorts.services.money_shot import _storyboard_grid

    sprite = Image.new("RGB", (3 * 48, 3 * 27))
    for k in range(9):
        r, c = divmod(k, 3)
        sprite.paste((k * 25, 0, 0), (c * 48, r * 27, (c + 1) * 48, (r + 1) * 27))
    urls = []
    for j in range(2):
        path = tmp_path / f"sprite{j}.jpg"
        sprite.save(path)
        urls.append({"url": path.as_uri(), "duration": 18.0})
    info = {"duration": 36.0, "formats": [
        {"format_id": "sb0", "width": 48, "height": 27, "rows": 3, "columns": 3, "fps": 0.5, "fragments": urls},
        {"format_id": "137", "width": 1920},
    ]}
    grid, times = _storyboard_grid(info, num_frames=6, per_row=3)
    assert grid and len(times) == 6
    assert times == sorted(times) and all(0 <= t <= 36 for t in times)
    assert all(abs((t % 18) % 2) < 1e-6 for t in times)


def test_long_video_moment_is_found_from_thumbnails_and_cut(monkeypatch, tmp_path):
    import asyncio

    from prolific.shorts.services import money_shot as ms

    async def search(query, video_license, video_duration="short"):
        if video_duration == "medium" and video_license == "creativeCommon":
            return [{"url": "long1", "title": "Karma's Reunion", "creator": "Gentle Barn", "channel_id": "g", "license_kind": "cc"}]
        return []

    async def own(cand):
        return True

    sections = []

    class Downloader:
        async def video_info(self, url):
            return {"duration": 281.0, "formats": [], "webpage_url": url}, "http://proxy:1"

        async def download_section(self, info, proxy, output_dir, filename, start, end):
            sections.append((info["webpage_url"], round(start, 1), round(end, 1)))
            path = tmp_path / f"{filename}_sec.mp4"
            path.write_bytes(b"x")
            return str(path)

    async def locate(desc, strip, n, subject=""):
        return True, 2, True, ""

    cuts = []

    async def cut(src, out, start, seconds):
        cuts.append((start, seconds))
        return True

    monkeypatch.setattr(ms.settings, "shorts_money_shot_enabled", True)
    monkeypatch.setattr(ms.settings, "shorts_money_shot_license", "cc_only")
    monkeypatch.setattr(ms.settings, "shorts_history_db_path", str(tmp_path / "shorts_history.sqlite"))
    monkeypatch.setattr(ms, "_own_channel_id", lambda: "")
    monkeypatch.setattr(ms, "_search_candidates", search)
    monkeypatch.setattr(ms, "_uploader_films_own_footage", own)
    monkeypatch.setattr(ms, "_storyboard_grid", lambda info, proxy="": ("grid", [10.0, 120.0, 200.0]))
    monkeypatch.setattr(ms, "_frames_strip", lambda path, num_frames=6: ("strip", [1.0, 3.0, 5.0]))
    monkeypatch.setattr(ms, "_locate_event", locate)
    monkeypatch.setattr(ms, "_probe_duration", lambda path: 8.0)
    monkeypatch.setattr(ms, "_cut_portrait", cut)
    import prolific.shorts.services.clip_downloader as cd
    monkeypatch.setattr(cd, "get_clip_downloader", lambda: Downloader())

    result = asyncio.run(ms.find_verified_clip("cows reunited", "two cows run to each other", str(tmp_path), "clip_14", 3.0))
    assert result is not None and result.match == "event" and result.creator == "Gentle Barn"
    assert sections == [("long1", 116.85, 125.85)] or sections == [("long1", 116.8, 125.8)] or sections == [("long1", 116.9, 125.9)]
    assert not (tmp_path / "clip_14_lv1_sec.mp4").exists()


def test_candidate_search_uses_web_results_and_one_vetting_call(monkeypatch):
    import asyncio

    from prolific.shorts.services import money_shot as ms

    calls = {"search": 0, "videos": 0}

    def item(vid, license, licensed=False, desc="Filmed at our farm."):
        return {"id": vid, "snippet": {"title": f"t {vid}", "description": desc, "channelTitle": f"ch {vid}", "channelId": f"c{vid}"},
                "status": {"license": license}, "contentDetails": {"licensedContent": licensed}}

    class Req:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class Videos:
        def list(self, part, id):
            calls["videos"] += 1
            pool = {"a": item("a", "creativeCommon"), "b": item("b", "youtube"), "c": item("c", "youtube", licensed=True),
                    "d": item("d", "youtube")}
            return Req({"items": [pool[v] for v in id.split(",") if v in pool]})

    class Search:
        def list(self, **kw):
            calls["search"] += 1
            return Req({"items": [{"id": {"videoId": "d"}}]})

    class Client:
        def videos(self):
            return Videos()

        def search(self):
            return Search()

    monkeypatch.setattr(ms, "_get_search_client", lambda: Client())

    async def web(query, cc_only, limit=30):
        return [{"id": "a", "duration": 50}, {"id": "b", "duration": 120}, {"id": "c", "duration": 90},
                {"id": "d", "duration": 600}, {"id": "e", "duration": None}]

    monkeypatch.setattr(ms, "_web_search", web)
    short_any = asyncio.run(ms._search_candidates("q", "any"))
    assert [(c["url"][-1], c["license_kind"]) for c in short_any] == [("a", "cc"), ("b", "fair_use")]
    medium_any = asyncio.run(ms._search_candidates("q", "any", video_duration="medium"))
    assert [c["url"][-1] for c in medium_any] == ["d"]
    assert calls["search"] == 0

    async def web_down(query, cc_only, limit=30):
        return None

    monkeypatch.setattr(ms, "_web_search", web_down)
    fallback = asyncio.run(ms._search_candidates("q", "any"))
    assert [c["url"][-1] for c in fallback] == ["d"] and calls["search"] == 1
