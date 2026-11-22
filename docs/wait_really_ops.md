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
- Never delete, hide or edit a published short. Comments are read only: never reply, like or pin.
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
5. Fact check on the hook claim. The blue raspberry short said a 1970s dye ban forced the flavor;
   a viewer replied that ICEE made it blue because cherry was already red. Add a source check on the
   one claim the hook makes before the script is final.
6. Slot test: Ask Grim found its 7 PM ET short beat noon on 5 of 6 days. Compare our 10 / 15 / 20
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
> 5. Comments: note any request or complaint that 2 or more viewers repeat. Read only.
> 6. Full review when the last one is 3 or more days old: judge the current experiment by the Rules,
>    start the next backlog item if it is judged, add a line to the Results log, and fill any due
>    checkpoint row in the tracking doc.
> 7. Update State. Push Brian only for a breakout (10k+ views within 48 hours), a broken pipeline you
>    cannot fix, a copyright problem, or a decision that is his. Otherwise answer in one line.
> 8. If State says this job is 6 or more days old, re-create it (CronList, CronDelete, then CronCreate
>    with the same cron and this prompt) and update the date in State.

## State (each check-in updates this)

- Check-in job: fceecc18, created Nov 22 2026 at 11:16 AM PT. Re-create it on Nov 28.
- One-shot 6059470d: Nov 22 5:23 PM PT (8:23 PM ET), checks the first fair-use short (20:00 ET run).
  (4d2ae36a was cancelled: the 15:00 short was checked at once, before the redeploy reset the logs.)
- Last check-in: Nov 22 14:47 ET (10 of 10 slots, no status problems, no copyright email, no new
  comments). Last full review: Nov 22.
- Experiment under test: Round 2 (since Nov 19 00:13 ET) plus real clips: CC only from Nov 22 14:14 ET
  (commit c4f53b7), fair-use test from Nov 22 15:04 ET (commit 3b194cc, first short at 20:00 ET).
- Railway variables: SHORTS_MONEY_SHOT_ENABLED=true, SHORTS_MONEY_SHOT_LICENSE=fair_use,
  SHORTS_MONEY_SHOT_MAX_PER_VIDEO=4 (max fair use 2 per short is the code default), YTDLP_PROXY
  (template with a `{port}` slot; the value holds the proxy login, never print it).
- Proxy: DataImpulse residential, plan "Wait Really real clips", $5 for 5 GB bought Nov 22 (invoice
  in_1UefnsAWZZJCgSrYQn7Td34n, Chase Sapphire 4733 through Stripe Link). Traffic never expires. Login in
  ~/.claude/secrets/passwords.txt under "DataImpulse". US exit IPs (`__cr.us` on the login), sticky
  ports 10000 to 20000. Dry run: about 35 MB per short, so about 3 GB a month. Auto-recharge is OFF:
  top up by hand when under 1 GB, and tell Brian.

## Pending

- [ ] Nov 24: Analytics should reach Nov 20 to 21. Report where the blue raspberry views came from
  (traffic source, subscribed or not, country) and its engaged views and average % viewed.
- [ ] Nov 26: Round 2 one-week checkpoint row in the tracking doc.
- [ ] Dec 3: Round 2 two-week checkpoint row in the tracking doc.
- [ ] Nov 29: "Real clips, first read" row in the tracking doc (shorts with a real clip against
  shorts without, same age, plus any copyright claim). Doc rev 22 after the Nov 22 update.

## Results log (newest first)

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
