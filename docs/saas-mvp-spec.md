# Prolific-as-SaaS — MVP Spec (Quiet Intelligence)

**Decision this doc supports:** managed SaaS vs. licensed tool, what to fork from
InterviewWhisperer, what's net-new, effort, and unit economics.

**Context:** 3 months of running our own channels proved the pipeline works but showed
ad-monetization is 1.5–3 years out (1,000-sub wall). The April portfolio analysis called
"selling the tool > running own channels" the highest-ceiling play; this spec makes it
concrete. Target market: faceless-channel creators (huge, active on X/Twitter, currently
duct-taping together 5 tools or paying VAs).

---

## 1. What InterviewWhisperer already gives us (fork, don't rebuild)

IW is a *launched* SaaS under the same LLC. Verified in-repo:

| Capability | Where | Reuse for Prolific |
|---|---|---|
| Stripe checkout + webhook lifecycle | `landing/app/api/checkout,webhook` | As-is; new Products/Prices in the SAME Stripe account (KYB already done) |
| License keys: mint, validate, activate | `license-server/src/key_generator.py`, `license_service.py` | As-is |
| Per-license daily quotas w/ rollover | `license_service.py` (sessions/audio/screenshots/proxy counters) | Rename counters → videos_generated, tts_chars, uploads |
| Privacy-safe telemetry whitelist | `license_service.py` TELEMETRY_EVENTS | Pattern as-is |
| Short-lived provider-key minting | `deepgram_keys.py` | Pattern for any BYOK-less provider access |
| LLM proxy w/ per-license metering | `proxy_service.py` | Basis for metered managed mode |
| Admin dashboard | `admin_dashboard.py` | As-is |
| Landing + legal (ToS/privacy/refund) + success/license flow | `landing/app/*` | Fork, reskin |
| Deploy/ops stack | Railway + Vercel + Cloudflare + Resend + UptimeRobot + Mercury | Same accounts |

**Head start ≈ 4–6 weeks of boring-hard work already done.** The LLC answer is simply
yes: same Stripe, same bank, new product line.

## 2. What Prolific already gives us

- The whole content engine (both formats), battle-tested 4 months in prod: topic
  selection w/ dedup gates + live competitor analysis, script gen, TTS, image/thumbnail
  gen w/ vision verification, assembly, upload, comment engagement, schedulers,
  retry-hardened LLM layer, cost tracking.
- Multi-channel credential handling (2 channels today, env-b64 pattern).
- Partial niche generalization on shorts (`NICHE_DESCRIPTIONS` registry); long-form
  prompts are still hardcoded to sleep-history modes.

## 3. The fork in the road

### Option A — Managed SaaS ("we run it")
Customer connects channel via YouTube OAuth, picks niche + cadence in a dashboard; our
infra generates and uploads.

- **Market:** the big one (non-technical faceless-channel crowd). $99–299/mo defensible.
- **Net-new build:**
  1. Multi-tenancy: tenant model, per-tenant channel creds, job queue replacing the
     single-container APScheduler (per-tenant schedules, concurrency, isolation).
  2. **YouTube OAuth app verification (LONG POLE):** `youtube.upload` is a sensitive
     scope → Google verification for external users (privacy policy, demo video,
     possible security review). 2–6+ weeks, mostly waiting.
  3. **YouTube API quota (HARD CONSTRAINT):** default 10k units/day per project; an
     upload costs ~1,600 → ~6 uploads/day per project TOTAL across customers. Needs a
     quota-increase audit, or per-customer Google-project onboarding (see hybrid).
  4. Niche generalization: prompts → templates parameterized by an LLM-generated niche
     config at onboarding.
  5. Per-tenant cost metering + hard caps (adapt IW quota code).
  6. Customer dashboard (fork `landing`): connect channel, configure, see runs.
- **COGS reality (why naive managed pricing fails):** a long-form customer ≈ 1.8M TTS
  chars/mo ≈ $150–300/mo of 11Labs at retail — underwater at $199/mo. Managed-with-
  our-keys only works for shorts-only tiers, or with aggressive caps.
- **Effort:** ~6–10 weeks to MVP, dominated by OAuth verification + multi-tenant worker.

### Option B — Licensed tool ("they run it", IW's exact model)
License key unlocks the pipeline they self-host (docker-compose exists) with **their own**
API keys + their own Google Cloud project creds (what we do for our own channels today).

- **Market:** smaller, technical subset. $49–99/mo.
- **Net-new build:** startup license check calling license-server; packaging + setup docs;
  onboarding wizard for creds (.env); landing variant. **~2–3 weeks.**
- **Kills both Google problems** (their project = their quota, no OAuth verification) and
  **kills COGS** (BYO keys). Trade: support surface becomes "their machine problems," and
  most of the market can't/won't self-host.

### Option C — Hybrid: managed orchestration + BYO keys (recommended architecture)
We host the pipeline + dashboard (Option A UX); customers paste in their own 11Labs /
OpenRouter keys and — at least at first — their own Google project credentials
(guided onboarding wizard; competitors do exactly this).

- COGS → ~$0 marginal per customer (they pay providers directly). Our infra ≈ flat.
- No YouTube quota wall (per-customer projects), OAuth verification deferrable.
- Metering/caps still ours (IW quota code) to keep runaway tenants off our compute.
- **Effort:** ~5–8 weeks. Cheaper tier later can add managed-keys shorts-only.

## 4. Recommended path: concierge pilot → Option C

Don't build 8 weeks blind. **Weeks 1–2: concierge MVP.** Land 3–5 design partners from
the faceless-YT community at $99–149/mo (founder pricing, Stripe payment links — zero new
code). Onboard them manually exactly like our own channels (their Google project + keys,
we configure prompts by hand). This validates demand + price + the onboarding pain with
real money before any platform build. **Then** build Option C for the pilot cohort:
tenant model + niche config + dashboard, forking IW's license-server and landing.

Kill criterion: if we can't get 3 paying pilots in ~3 weeks of trying, the market is
telling us something — revisit before building.

## 5. Pricing sketch (validate in pilot)

| Tier | What | Price |
|---|---|---|
| Shorts Engine | 1 channel, 3 shorts/day, BYOK | $99/mo |
| Full Stack | shorts + long-form, 1 channel each, BYOK | $199/mo |
| Studio | multi-channel, priority support | $299+/mo |

20 customers at blended ~$150 = **$3k MRR** — vs. ~$18/quarter the channels would earn
at today's scale once monetized. Comps in the niche run $49–149/mo with far weaker tech.

## 6. Open questions / risks

1. **YouTube ToS posture** on automated uploads — need a clear customer-facing stance +
   ToS clause (channels run at customer's risk; our own channels are the live demo).
2. Google Cloud onboarding friction in pilot — measure it; it decides how urgent our own
   verified OAuth app (Option A upgrade) is.
3. Support load per customer — pilot will reveal.
4. Niche generalization quality — our prompts are tuned to 2 niches; pilot niches will
   stress-test the templating (pick pilots in adjacent niches first: history, facts,
   sleep, curiosity).
5. Own-channels role going forward: keep as demo/proof + marketing content ("built in
   public" meta-content funnels to the SaaS).
