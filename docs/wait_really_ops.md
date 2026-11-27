# Wait Really operations

Brian, Nov 22 2026: run Wait Really autonomously. Check in every few days, read the analytics and the
comments, change what does not work, use real clips of the actual subject, and run it smart. This file
is the playbook each check-in follows, and its State section is the memory between check-ins.

Tracking doc (Brian reads this one): https://claude.ai/artifact/CC24TL1iYqEHPbuKrj1ewX
(Claude Docs doc 5a9e5c15-5e62-424e-be8e-d5a8d7f8b34e; read it before an edit, it has Round 1 and
Round 2 sections with checkpoint rows).

## Goal and scorecard

- Goal: more people reached per short. Breakouts (10k+ views) are what grow the channel.
- Main number: the median same-age ratio from `scripts/wait_really_checkin.py`, new shorts against the
  "old normal" cohort (Sep 15 to Oct 14). Raw totals mislead because shorts of different ages are mixed.
- Also watch: hook rate (engaged views / views; Analytics lags 2 days), breakouts per week, and
  repeated viewer comments.

## What is live

- Round 2 since Nov 19 2026 00:13 ET (commit 306f18c, deploy 4c0631ec): synced cuts every 2 to 3.6 s,
  slow zoom on every clip, music with ducking and SFX, highlighted word captions, the scoreboard feeds
  topic choice, rotation animal / history / science, 3 a day at 10:00, 15:00 and 20:00 ET.
- Real clips (money shots): see State. Code: `prolific/shorts/services/money_shot.py`. Each pick is
  searched on YouTube, vetted through the Data API (CC license confirmed, `licensedContent` skipped,
  re-upload and agency text skipped), downloaded through `YTDLP_PROXY`, checked by a vision model, and
  cut to portrait. Credits go in the description under "Footage credits:".

## Rules

- One change at a time. A change gets 9 shorts (3 days) before it is judged, because the topic swings
  a single short far more than any edit does.
- Judge with same-age ratios from the check-in script. Keep a change at 1.0x or better against the
  version before it, roll it back below 0.8x, and give it 3 more days in between.
- Deploy only under the deploy skill: pipeline idle, never within 10 minutes of 10:00, 15:00 or
  20:00 ET. Commit only the files you changed, never `git add -A` (other sessions keep uncommitted
  work in this repo).
- Never delete, hide or edit a published short. Comments are read only for Claude: never reply, like or
  pin (the pipeline's own reply bot answers comments every 2 hours).
- Viewer feedback (Brian, Nov 23): one viewer is enough. Log every specific, reasonable request or
  complaint in "Viewer requests" below with the action taken, and act on it when it fits the goal. Skip
  only requests that are off topic or would replace the whole approach, and write down why.
- Spend: the proxy is pay as you go. Any new cost over $20 a month needs Brian's OK.
- Copyright kill switch: at the first claim, strike, takedown, region block or copyright email, set
  `SHORTS_MONEY_SHOT_ENABLED=false` on Railway, log it here and push Brian. Wait Really and Ask Grim
  share Brian's Google account, so 3 strikes in 90 days could end both channels.
- Fair-use test (Brian, Nov 22: competitors show the actual footage and he is "willing to test it"):
  up to 4 real clips per short, at most 2 of them fair use, never the same fair-use source channel twice
  in 30 days (/app/data/money_shot_sources.json), never a Content ID partner video
  (`licensedContent`), an agency, a network, a re-poster or another creator's watermark. Every source is
  credited in the description. The kill switch above applies at the first claim, strike or email.

## Experiment backlog (top first)

1. Real clips with the fair-use test (CC only from 14:14 ET Nov 22, fair use from the 20:00 ET run).
   Readout after 9 shorts: compare with and without real clips (the check-in script splits them).
2. Competitor check, Nov 22: the top Shorts on our own topics show the real subject in almost every
   frame (jacana dad 3.5M views, stop signs 4.1M, Britney pirates 330k). Ours on the same topics got
   1.0k to 1.4k. Real footage for most of the runtime is the gap to close.
3. Subject accuracy: check that stock clips show the named animal; else use real photos of the exact
   species (Wikimedia Commons, iNaturalist). Viewer ask Nov 22: "Please show the actual animal".
4. Double down on winners: the scoreboard already steers topics. On each full review, look at the top 5
   and bottom 5 by same-age ratio and move the rotation toward the winners. So far: weird food and
   everyday-object origins won (blue raspberry 23.7k, stop signs 1.3k), word origins lost (buck, 87).
5. Fact check on the hook claim: BUILT Nov 25 after two viewer corrections (blue raspberry origin,
   white chocolate "zero chocolate components").
6. People topics: the vision check accepted an Einstein lookalike from a Movember ad as "Einstein
   writing on a chalkboard" (Nov 23). For a real person, reject actors, costumes, statues and lookalikes.
7. "Part 2" continuations: 6 of the last 13 shorts carry "Part 2" (elephants twice, crows, Einstein,
   cows, orcas). A viewer in the feed has not seen Part 1. At the Nov 28 review, compare Part 2 shorts
   with the rest at the same age; if they are lower, stop the label or the continuations.
8. Slot test: Ask Grim found its 7 PM ET short beat noon on 5 of 6 days. Compare our 10 / 15 / 20
   slots on same-age ratio before you move them.

## The check-in job

Cron `17 11 * * *` in this session (local time, Pacific since Nov 1). The scheduler offset makes it
fire at about 11:47 AM PT, 2:47 PM ET, after the 10 AM ET short has had almost 5 hours. Session jobs expire after 7 days and only fire while this
Claude session is open and the Mac is awake. If the session restarts, Brian says "resume the Wait
Really check-ins" and Claude re-creates the job with this prompt:

> Wait Really check-in (daily, set up Nov 22 2026). Work in ~/repos/Prolific. Read
> docs/wait_really_ops.md first (Rules, State, Pending). The Mac may have been asleep: do what is due,
> then stop.
> 1. Run `.venv/bin/python scripts/wait_really_checkin.py`. It prints pipeline health, same-age views,
>    hook rate, real-clip use, video status problems and new comments.
> 2. Pipeline: if fewer shorts were published than slots expected, read the Railway logs for the
>    missed slot (deploy skill) and fix the cause, under the deploy rules.
> 3. Copyright: if the script lists a status problem, or Gmail has a YouTube copyright email about
>    Wait Really, apply the kill switch in Rules at once.
> 4. Real clips: from the Railway logs since the last check-in, count `money-shot USED` lines against
>    the shorts made, and note the proxy traffic used (State has the provider).
> 5. Comments: log every specific, reasonable request or complaint, even from one viewer, in the
>    "Viewer requests" table with the action taken, and act on it when it fits the goal. Read only.
> 6. Full review when the last one is 3 or more days old: judge the current experiment by the Rules,
>    start the next backlog item if it is judged, add a line to the Results log, and fill any due
>    checkpoint row in the tracking doc.
> 7. Update State. Push Brian only for a breakout (10k+ views within 48 hours), a broken pipeline you
>    cannot fix, a copyright problem, or a decision that is his. Otherwise answer in one line.
> 8. If State says this job is 6 or more days old, re-create it (CronList, CronDelete, then CronCreate
>    with the same cron and this prompt) and update the date in State.

## State (each check-in updates this)

- Check-in job: e1c8030c, created Nov 23 2026 at about 7:50 PM PT with the new comment rule (replaced
  fceecc18). Re-create it on Nov 29.
- One-shots: none open (6059470d ran Nov 22 20:23 ET; 4d2ae36a was cancelled after the 15:00 short was
  checked at once, before the redeploy reset the logs).
- Last check-in: Nov 27 14:47 ET (25 of 25 slots, no status problem, no copyright email). Last full
  review: Nov 25. Next full review: Nov 28.
- Proxy balance: 3.19 GB on Nov 25 (about 375 MB a day, so top up near Dec 1).
- Fact check (backlog 5, two viewer corrections): every curiosity script is checked against a web
  search after it is written; wrong or overstated sentences are fixed (log lines "Fact check fix").
  Live since 15:08 ET Nov 25 (commit 4016ebf), first short 20:00 ET Nov 25.
- Fair-use source log (/app/data/money_shot_sources.json): Movember (UCuISjZcTmzLbBQ6OEAoUSqA) since
  Nov 23 10:07 ET.
- Experiment under test: Round 2 (since Nov 19 00:13 ET) plus real clips: CC only from Nov 22 14:14 ET
  (commit c4f53b7), fair-use test from Nov 22 15:04 ET (commit 3b194cc). Candidate order fix live from
  Nov 22 20:25 ET (commit 1d45ee5): CC and fair use alternate, the first event clip wins.
  Nov 23 22:16 ET (commits 05aab81, e15efae), first short 10:00 ET Nov 24: picks read the words spoken
  during each shot and rank action scenes first; both queries are searched for the event; medium
  videos are searched through their storyboard thumbnails and only the needed seconds are pulled;
  search runs through yt-dlp (0 API units); the riser sound is gone (Brian: "rocket ship" sound).
  SHORTS_MONEY_SHOT_MAX_PER_VIDEO=5.
  Nov 24 15:24 ET (commits eb66297, bc9ead0), first short 20:00 ET Nov 24: subject pool (stock shots
  that name the subject get a window cut from the real-clip sources, rotated, at most 3 uses per
  source), explainer-title filter, competitor explainers count as re-posts, public domain archives
  accepted, non-CC stock footage sellers skipped. A run now takes about 15 minutes.
- API quota: Wait Really, Ask Grim and Slumber use ONE Google Cloud project (same OAuth client), so
  every Data API search (100 units) competes with Ask Grim's uploads. Never add search.list calls; the
  money-shot search only falls back to it when yt-dlp search fails 3 times.
- Railway variables: SHORTS_MONEY_SHOT_ENABLED=true, SHORTS_MONEY_SHOT_LICENSE=fair_use,
  SHORTS_MONEY_SHOT_MAX_PER_VIDEO=4 (max fair use 2 per short is the code default), YTDLP_PROXY
  (template with a `{port}` slot; the value holds the proxy login, never print it).
- Proxy: DataImpulse residential, plan "Wait Really real clips", $5 for 5 GB bought Nov 22 (invoice
  in_1UefnsAWZZJCgSrYQn7Td34n, Chase Sapphire 4733 through Stripe Link). Traffic never expires. Login in
  ~/.claude/secrets/passwords.txt under "DataImpulse". US exit IPs (`__cr.us` on the login), sticky
  ports 10000 to 20000. Nov 23 dry run with 5 picks and long videos: about 125 MB per short, so about
  11 GB (about $11) a month. Auto-recharge is OFF: top up by hand when under 1 GB (expected near Dec 1),
  and tell Brian.

## Viewer requests (newest first)

| Date | Viewer | Short | Request | Action | Status |
| --- | --- | --- | --- | --- | --- |
| Nov 27 | @dr.chemical8231 | Wombat cubes (CnlhgmEPNcI) | 'Those "sharp right angles" look pretty rounded to me' | Right. The fact check now softens vivid details the sources do not state; on this script it gave "distinct edges" and "dozens of blocks each night". Live since 15:14 ET Nov 27 (commit 3c71e4f). | Done, watch |
| Nov 26 | @MrMelichor | White chocolate (U9rjb7Binws) | "Clickbait bullshit" (title: "White Chocolate is a Lie") | The title claimed more than the script. Plan: a truth check on titles (keep curiosity, no false claim) at the Nov 28 review. | Open |
| Nov 21 | @ronettviljoen9449 | Jacana dads (ZtZUPTzqfUo, Nov 19) | "Please show the actual animal in question... they just need more footage of the animal or objects" | The short showed stock of a lapwing, not a jacana. Real clips of the actual subject since Nov 22; matched to the spoken words and long videos since Nov 23; stock shots that name the animal now use real footage of it from the subject pool since Nov 24 (cow test: 8 of 15 shots real). | Done, watch |
| Nov 24 | @jonathansuber1551 | White chocolate (U9rjb7Binws) | "Zero chocolate components. Lists Cocoa butter a chocolate component." | Right: cocoa butter comes from the cocoa bean. Fact check built Nov 25; on this script it rewrote the hook to "zero cocoa solids". | Done, watch |
| Nov 22 | (comment) | Blue raspberry | The origin story is wrong: ICEE made it blue because cherry was already red | Fact check built Nov 25; on this script it replaced the made-up motive and the dates (blue raspberry dates from 1958). | Done, watch |

## Pending

- [x] Nov 24: stock shots must show the right species. Built as the subject pool (live 15:24 ET).
- [ ] Nov 28 full review: a truth check on titles (the white chocolate "is a Lie" title drew
  "Clickbait bullshit"): curiosity stays, a false claim goes.
- [ ] Nov 25 full review: check the 20:00 Nov 24 short and later ones for pool shots (log line
  "SUBJECT POOL"), run time, and proxy traffic left in the DataImpulse dashboard.

- [x] Nov 24: blue raspberry source report (see the Results log, Nov 24).
- [x] Nov 26: Round 2 one-week row filled (doc rev 24, "On track").
- [ ] Dec 3: Round 2 two-week checkpoint row in the tracking doc.
- [ ] Nov 29: "Real clips, first read" row in the tracking doc (shorts with a real clip against
  shorts without, same age, plus any copyright claim). Doc rev 22 after the Nov 22 update.

## Results log (newest first)

- Nov 27 check-in: 25 of 25 slots. Median 1.33x the old normal (n=22), with real clips 1.26x (n=12),
  without 1.47x (n=10). Hook rate 52.2% (n=18) against 45.7%, rising each day. Runs: Roman statues 1
  clip, Japanese bees 4 clips plus 3 pool shots, wombat cubes 4 clips plus 4 pool shots. Fact check:
  2, 3 and 1 fixes. Two viewer complaints logged and acted on (see Viewer requests).

- Nov 26 check-in: 22 of 22 slots. Median 1.27x the old normal (n=19), with real clips 1.21x (n=9),
  without 1.47x (n=10). Confounded: the no-clip shorts came during the blue raspberry spike (channel
  23k views on Nov 21), and the later set has more "Part 2" and non-animal topics. First read row
  filled: median 1,106 views (22 shorts) against 251 and 858, 68% over 1k, hook 50.8%. Fact check
  live: 2 fixes in each of the last 2 scripts (for example "twice as hard as oak" became "roughly three
  times as hard as white oak"). Elephants 20:00: 3 event clips plus 6 pool shots.

- Nov 25 full review: 19 of 19 slots. Round 2 median 1.46x the old normal (n=16), hook rate 50.6%
  (n=11) against 45.7%: keep. Real clips: with 1.31x (n=6), without 1.47x (n=10), ratio 0.89, so by
  the Rules give it 3 more days; the current version (word matching, long videos, subject pool) only
  began with the 20:00 Nov 24 short, so judge it at the Nov 29 row. Runs since Nov 24 14:47: spiders 4
  clips (1 event, 3 subject), white chocolate 2 events, orcas 2 subject plus 3 pool shots. Next
  backlog item started: the fact check (two viewer corrections in a week).

- Nov 24 14:47 ET check-in: 16 of 16 slots, median 1.46x the old normal (n=13), hook rate 48.4% (n=9)
  against 45.7%. Real clips: with 1.43x (n=3), without 1.47x (n=10), too early. Bat bomb short (10:00):
  1 of 4 picks real (bat swarm, CC); history searches are mostly other history explainer channels
  (rejected), and the uploader check also rejected public domain archives (atomcentral,
  PublicResourceOrg). Square windows short (Nov 23 20:00) used two competitor explainers (StickQuirk,
  Break Even Math). Fixes built: explainer-title filter, competitor explainers count as re-posts, a
  public_domain_archive verdict, and the subject pool (see State).
- Nov 24, blue raspberry (vc3wJY8cd7M) from Analytics: 24,421 views, 14,114 engaged (58%), average
  36 s of 38 s (96% viewed). Day 1 4,982, day 2 16,869, day 3 2,570. Traffic: Shorts feed 97%, search
  3%. Non-subscribers 100%. US 59%, India 12%, UK 9%, Philippines 9%, Canada 6%, Australia 5%. Mobile
  60%, tablet 21%, TV 14%. Only 6 subscribers gained. Channel views Nov 21: 23,310 (baseline about
  2,700). Lesson: a near-full watch (96%) is what makes the feed push a short; the channel turns almost
  no viewers into subscribers.

- Nov 23 22:16 ET, Brian's review of the cow short (czPrmrjhyK0): at 12.4 to 17.5 s the voice says cows
  are pulled apart while a lone cow walks (query "cow running to fence"); the reunion used stock; one
  shot was "microscopic cell" stock. Causes: the picker read stock phrases, not the spoken words; it
  picked generic scenes; the real moments live in longer farm and sanctuary videos or with The Dodo
  (Content ID, skipped). Re-run of the cow script with the new code: 4 of 4 scenes real, 3 events
  (AnimalPlace reunion, mooing, herd); separation still subject only. Long-video live test: The Gentle
  Barn "Karma's Reunion" gave the cow and calf reunion for 1.5 MB.

- Nov 23 14:47 ET check-in: 13 of 13 slots. Median 1.52x the old normal (n=10), hook rate 46.8% (n=6)
  against 45.7%. Real clips since Nov 22 14:47: peppers 1 of 2 picks (CC, event), crows 4 of 4 (CC,
  subject), Einstein's eyes 2 of 4 (Empire Safe CC event, Movember fair use event: the first fair-use
  clip, and a lookalike, see backlog 6). Early views: crows 115 at 0.8 days (typical 605, weak),
  Einstein 1,144 at 0.2 days (typical 247, strong). The script flagged 3 July videos as "missing": a
  false alarm from its 400-video window (the channel has 754). They are public; the script now looks
  up each missing ID before it reports a problem.

- Nov 22 20:06 ET, first fair-use-mode short: "Crows Solve Murders: The Terrifying Truth (Part 2)"
  (SEfUhFCLAbw, 33 s). 4 of 4 picks got real crow footage, about 18.5 s of the 33 s, all CC and all
  subject only (no clip showed the "funeral" behavior). 0 fair-use clips, so no source log yet. All 4
  credited in the description; frames checked: right animal, our credit line, no other watermark, no
  black bars. Cause of no event clips: three CC tries ran before any fair-use candidate. Fixed in
  1d45ee5 (alternate CC and fair use, up to 4 tries, events first).

- Nov 22 15:03 ET, first real-clip short (CC mode, 2 picks): "Peppers Evolved Spice Specifically to
  Torture You" (YLMa60DH_Yg). 1 of 2 picks used: chickens eating hot peppers (THEBOKBOKSISTERS, CC,
  own footage), credited. "horse chewing close up" found no verified clip.

- Nov 22 15:00 ET, outlier check: without blue raspberry, Round 2's median is 1.3x the old normal
  (n=6), against 1.45x with it. Blue raspberry is 67% of all Round 2 views (23,741 of 35,337) and
  stopped at about 23.7k. Analytics data ends at Nov 19, so its traffic split is not in yet.

- Nov 22 14:14 ET, real clips live (CC only). Dry run on 4 recent scripts: 7 of 7 picks found real
  footage of the actual animal (3 showed the exact event, 4 the animal itself), about 35 MB per short.
  Guards that fired in the dry run: Content ID managed videos, re-upload text, re-post channels
  ("Daily Funny Pets", "Facts Fuel", "Clip Forge"), and another creator's watermark
  ("@THEFISHINGMUTTS" on a brand channel).

- Nov 22 13:41 ET, Round 2 day 3.5: 10 of 10 slots published. Median 1.45x the old normal and 5.23x
  Round 1 at the same age (n=7). Record breakout: blue raspberry, 23,737 views at 2.2 days. Goats
  3,972 at 1.2 days. Hook rate 48.7% vs 45.7% (n=2, early). Dud: word origin "buck", 87 views.
  Comment: "Please show the actual animal in question."
