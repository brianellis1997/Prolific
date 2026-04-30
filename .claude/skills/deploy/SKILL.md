---
name: deploy
description: Deploy the Prolific content pipelines (Slumber Archives long-form + Wait Really? shorts) to Railway, verify the deploy is live, and read production logs. Invoke when the user says "deploy", "push this to prod", "ship it", "check production logs", "verify the deploy", "is X live in prod", "redeploy", or asks how to roll back. ALWAYS run the pre-deploy safety checks before pushing — a long-form pipeline run can be in flight and a deploy will kill it (~$5-20 wasted per killed run).
---

# Prolific deploy skill

This repo runs two production pipelines on Railway. Use this skill BEFORE deploying — there are non-obvious gotchas (auto-deploy isn't configured; long-form runs take 20+ min and a deploy mid-run kills them).

## Quick reference

```bash
# 1. PRE-DEPLOY SAFETY (mandatory — never skip)
TZ=America/New_York date "+%a %b %d %H:%M ET"   # check current time vs cron
# Check Railway logs for any in-flight pipeline:
#   mcp__railway__get-logs --filter "Pipeline started OR Pipeline finished"

# 2. Stage + commit (NEVER `git add -A` — exclude .claude/settings.local.json)
git add prolific/...                               # specific files
git commit -m "..."                                # see commit-message style below

# 3. Push (this does NOT trigger an auto-deploy on this repo)
git push origin main

# 4. Trigger manual Railway deploy via MCP
#    mcp__railway__deploy with workspacePath=/Users/bdogellis/repos/Prolific, ci=true
#    Build takes ~70-180s. Returns "Deploy complete" when image is built.

# 5. Verify live (after deploy returns)
#    mcp__railway__get-logs --filter "scheduler OR Application startup"
#    Expect: "Application startup complete", scheduler jobs registered
```

## Pre-deploy safety checks (MANDATORY)

A previous Claude killed a render and wasted ~$20 by deploying during an in-flight run. Always check both:

### Check 1: in-flight pipeline?

```
mcp__railway__get-logs --logType deploy --filter "Pipeline started OR Pipeline finished" --lines 5
```

If the most recent line is `Pipeline started` (no matching `Pipeline finished`), a run is in flight — **do not deploy**. Wait for the `Pipeline finished` line, or ask the user.

### Check 2: cron proximity

Crons that fire long-form runs at **16:00 America/New_York**:
- `youtube_mwf_bio` — Mon/Wed/Fri (BIOGRAPHY content mode, ~20 min runtime)
- `youtube_thu_lostciv` — Thursday (LOST_CIVILIZATION mode)
- `youtube_sat_immersive` — Saturday (IMMERSIVE_DAILY_LIFE mode)

Shorts cron fires daily at **9/12/16/20 ET** (~3 min runtime each).

Comment-reply runs every 2h (cheap, fine to overlap).

If current ET time is within ~25 min of any cron above, **wait until after**. The pipeline_lock prevents concurrent runs across modes but doesn't help if a run is killed mid-deploy.

```bash
TZ=America/New_York date "+%a %H:%M ET"
```

## Deploy procedure

### 1. Stage files specifically — never `git add -A`

`.claude/settings.local.json` is user-tooling state, do not commit it. Stage by exact paths:

```bash
git add prolific/youtube/foo.py prolific/services/bar.py ...
git status                                # confirm only intended files
```

### 2. Commit-message style (matches repo history)

Sentence-case, present tense, descriptive but concise. No conventional-commits prefix.
Look at `git log --oneline -8` for examples. Recent good ones:
- "Add semantic topic dedup gate with intentional-continuation flag"
- "Overhaul shorts clip pipeline: director-first flow, vision selection, cross-session dedup"
- "Fix AI video mode ignoring KLING_CRON_HOURS changes due to @lru_cache"

Always use HEREDOC for the message body and end with the Co-Authored-By footer per CLAUDE.md.

### 3. Push to main

```bash
git push origin main
```

### 4. Trigger Railway deploy manually

**Auto-deploy is NOT configured for this repo.** Pushing to main does not trigger a build. You MUST manually trigger via MCP:

```
mcp__railway__deploy
  workspacePath: /Users/bdogellis/repos/Prolific
  ci: true     # streams build logs, exits when build completes
```

Build typically takes **70-180 seconds** (Dockerfile-based, layer cache reuses python:3.12-slim + ffmpeg). The returned output ends with `Deploy complete`.

If the build fails: read `mcp__railway__get-logs --logType build` for the failed deployment ID. Common failures: missing dep in `requirements.txt`, syntax error caught by import-check.

### 5. Verify live

After the deploy returns, the new container should restart within ~30s. Verify by:

```
mcp__railway__get-logs --logType deploy --filter "scheduler OR Application startup OR ImportError OR Traceback OR ERROR" --lines 25
```

Expected output:
- `INFO: Application startup complete.`
- `YouTube scheduler started with 3 active jobs: youtube_mwf_bio, youtube_thu_lostciv, youtube_sat_immersive`
- `Shorts scheduler started: daily at 9:00, 12:00, 16:00, 20:00 ET`
- `Comment reply scheduler started: every 2 hours`

Any `ImportError`, `Traceback`, or missing scheduler line → deploy is broken; investigate. The healthy state should NOT log `ERROR` lines at startup.

For pipeline-level verification (DEDUP gate, content_mode routing), wait for the next scheduled run and grep specific signatures. See [Watching production logs](#watching-production-logs) below.

## Watching production logs

The Railway MCP tool `mcp__railway__get-logs` is the primary interface. Key flags:

- `--logType deploy` — runtime application logs (default for verification)
- `--logType build` — Dockerfile build logs (only useful for failed deploys)
- `--filter "..."` — Railway log filter syntax. **Quotes inside the filter break the parser** — keep terms simple, use OR/AND between them.
- `--lines N` — disables streaming, returns last N lines. Default 100. For broad scans use 50-100; for narrow filtering use 10-30.

### Useful filter recipes

```
# All recent topic_selection events (both pipelines)
--filter "TOPIC SELECTION OR Selected topic"

# Dedup gate firing
--filter "DEDUP REJECTED OR DEDUP WARN BAND OR CONTINUATION"

# Content-mode routing (after the variant-modes feature shipped)
--filter "Content mode OR mode=BIOGRAPHY OR mode=LOST_CIVILIZATION OR mode=IMMERSIVE"

# Pipeline lifecycle (for safety-check)
--filter "Pipeline started OR Pipeline finished OR PIPELINE COMPLETE"

# Errors only
--filter "ERROR OR Traceback OR ImportError OR @level:error"

# A specific run by topic name
--filter "Cyrus the Great"
```

### Filter syntax gotchas

- `OR` and `AND` work, but multi-word phrases need surrounding spaces, not quotes.
- `"Persian Empire"` → parser treats `Persian` and `Empire` as separate args and breaks. Use `Persian` alone, or pivot to a less-ambiguous term.
- `@level:error`, `@level:warn` work. `@status:500` works.
- See https://docs.railway.com/guides/logs

## Rollback / kill switches

The pipeline has env-var kill switches for safe rollback without code changes:

| Switch | Effect |
|---|---|
| `YOUTUBE_CRON_ENABLED=false` | Disables ALL long-form crons (Mon/Wed/Fri/Thu/Sat) |
| `YOUTUBE_LOSTCIV_ENABLED=false` | Disables Thursday LOST_CIVILIZATION job only |
| `YOUTUBE_IMMERSIVE_ENABLED=false` | Disables Saturday IMMERSIVE_DAILY_LIFE job only |
| `SHORTS_CRON_ENABLED=false` | Disables all shorts crons (9/12/16/20 ET) |
| `TOPIC_DEDUP_ENABLED=false` | Bypasses semantic dedup gate (both pipelines) |
| `KLING_ENABLED=false` | Disables AI-video mode for shorts (currently off in prod) |

Set via Railway dashboard env vars + redeploy (or `mcp__railway__set-variables`). Disabling a single mode's flag does not need a code change — just env update + redeploy.

For code-level rollback, `git revert <sha>` + push + manual deploy. The two recent feature shas:
- Topic dedup gate: see git log around 2026-04-29 (commit message starts "Add semantic topic dedup gate")
- Variant content modes: see git log around 2026-04-30 (commit message starts "Add LOST_CIVILIZATION + IMMERSIVE_DAILY_LIFE")

## Pipeline schedule reference

```
                Mon   Tue   Wed   Thu        Fri   Sat            Sun
Long-form 16ET  bio    -    bio   lostciv    bio   immersive       -
Shorts 9/12/    yes    yes  yes   yes        yes   yes             yes
  16/20 ET
Comment reply   every 2h, all days
```

**Build/deploy takes 70-180s.** **Long-form runs take ~18-22 min.** **Shorts runs take ~2-3 min.**

The shared `slumber_archives_youtube` pipeline_lock prevents two long-form runs at once. Shorts have their own lock (`wait_really_shorts`).

## Railway project context

- Project: `prolific-content-engine` (id `d618d3fc-2735-4ec9-bca7-705af2da8686`)
- Service: `prolific-content-engine` (id `4b6fb791-888c-4193-ab5c-b9cee8dcb38e`)
- Environment: `production`
- Volume mount: `/app/data/` — both SQLite DBs (`youtube_history.sqlite`, `shorts_history.sqlite`) live here
- Region: `us-east4-eqdc4a`
- Build: Dockerfile-based (no nixpacks despite reports), Python 3.12-slim base
- Two YouTube channels:
  - **Slumber Archives** (long-form, biographies + variants) — uses `youtube_credentials_slumber.json`
  - **Wait Really?** (shorts, curiosity facts) — uses `youtube_credentials.json`

## Common pitfalls

1. **Auto-deploy is NOT on.** Past historical correlation between commits and deploys was misleading — the GitHub trigger isn't actually wired up. Always run `mcp__railway__deploy` manually after pushing.
2. **The `--filter` flag's word-boundary parsing breaks on quotes.** Keep filter terms simple (`Cyrus`, not `"Cyrus the Great"`).
3. **Two-channel confusion.** Long-form goes to "Slumber Archives", shorts go to "Wait Really?" — different OAuth credentials, different SocialBlade/analytics. Don't mix them up when reading channel-history DBs.
4. **DB path.** Prod DBs are at `/app/data/*.sqlite` (mounted volume), NOT in the repo. To debug locally against prod data, copy the file out via `railway run` or via the dashboard.
5. **Memory caveat.** The user-level memory has notes about prior deploys (`feedback_deploy_safety.md`, `project_shorts_unlisted.md`). Read those before assuming anything about state.
6. **`.claude/settings.local.json`** is user-tooling state with permission grants. NEVER commit it.

## Local verification before deploy

For non-trivial changes, run import-check + smoke tests locally first:

```bash
PYTHONPATH=. .venv/bin/python -c "
from prolific.youtube.graph import build_youtube_pipeline_graph
from prolific.shorts.graph import build_shorts_pipeline_graph
build_youtube_pipeline_graph()
build_shorts_pipeline_graph()
print('Both graphs assemble OK')
"
```

If the change touches the DB schema, additionally run a fresh-DB migration test (see `prolific/services/topic_dedup.py` test pattern from prior session).
