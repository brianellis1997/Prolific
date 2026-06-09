"""Centralized LLM prompts for the YouTube sleep history pipeline."""

# ---------------------------------------------------------------------------
# Content-mode instruction blocks
# ---------------------------------------------------------------------------
# Three content modes power the 5-day cadence:
#   BIOGRAPHY (Mon/Wed/Fri) — famous historical figure deep dive (existing)
#   LOST_CIVILIZATION (Thu) — prehistoric mystery / lost-civilization curiosity gap
#   IMMERSIVE_DAILY_LIFE (Sat) — second-person daily-life / survival immersion
# These strings are injected as `content_type_instruction` into TOPIC_BRAINSTORM_SYSTEM.

CONTENT_INSTRUCTION_BIOGRAPHY_FIXED = """This video is a BIOGRAPHY / character deep dive about
a specific historical figure. The figure should be someone a curious viewer would WANT to know
more about — ideally someone with dramatic stakes, moral ambiguity, or a hidden / contested side
to their story.

Cast wide across ALL of world history — not just the Western canon, not just emperors and kings.
Strong picks come from any culture/period: Sufi mystics, Khmer god-kings, Yuan-dynasty admirals,
Songhai scholars, Polynesian wayfinders, Russian Old Believer rebels, Indian poet-philosophers,
Tang-dynasty courtesan-poets, Persian astronomers, Caribbean maroon leaders, Joseon-era reformers,
Aztec tlatoanis, Norse skald-warriors, Andean rebel queens, Sahelian mansas, Byzantine intriguers,
Mughal princesses... Many of the channel's strongest performers will be names viewers half-recognize
or don't recognize at all but find dramatically irresistible.

CURIOSITY TRIGGERS (one must apply to the topic you propose):
  - A specific dramatic arc — rise, fall, betrayal, return, revenge
  - A figure famous in one frame and invisible in pop history (e.g., Asian scientists, female
    rulers, non-European generals, religious dissenters)
  - A hidden / contested side to a famous name (what nobody talks about)
  - A figure who shaped events most people credit to someone else

DO NOT:
  - Use formulaic title scaffolds like "X: The Life and Legacy" — the topic dictates its own framing
  - Default to the obvious top-of-mind set (Napoleon, Caesar, Cleopatra, Genghis, Alexander) when
    the channel already has those — see the DO-NOT-REPEAT and AVOID-STEMS lists for what's stale
"""

CONTENT_INSTRUCTION_BIOGRAPHY_FORCED = CONTENT_INSTRUCTION_BIOGRAPHY_FIXED + (
    "\n\nNOTE: the channel needs more biography content this cycle — strictly biography, not broader."
)

CONTENT_INSTRUCTION_BROAD_TOPIC = (
    "This video is a BROAD TOPIC exploration (civilization, era, event, cultural movement) "
    "rather than a single person's biography. Pick something dramatic and specific to a place "
    "and period — a war, a collapse, a movement, a discovery, a cultural rupture. Cast wide "
    "across world history; the channel skews Western too often."
)

CONTENT_INSTRUCTION_LOSTCIV = """This video explores a SPECIFIC unresolved historical or
archaeological mystery — a place, period, artifact, or event whose story is genuinely contested
or uncertain. The strongest format is a real question at the heart of the video ("what happened
to X?", "who built Y?", "why does Z exist?"), not a vague "alternative history" vibe.

The space is enormous. Cast across ALL of world history, not just the same five
alternative-history talking points the LLM tends to reach for. Strong territory includes:
pre-Columbian Americas (Caral, Chinchorro, Olmec colossal heads, Cahokia, Casas Grandes,
Cliff dwellings), Pacific Islander deep-time seafaring, Saharan green-period civilizations,
Tibetan plateau prehistory, Caspian and Black Sea drowned-landscape mysteries, Indus Valley
script and city collapse, Australian Dreamtime archaeology, Mediterranean Sea Peoples and
end-of-Bronze-Age, North African Fezzan and Garamantes, Steppe nomad confederacies, Polynesian
deep-time, Andean Chavín and Norte Chico, sub-Saharan iron-age complexes, Mesoamerican
codices, ancient Chinese pyramids, Russian taiga megaliths, Madagascar's lost megafauna...

CURIOSITY TRIGGERS (one must apply):
  - A WHO/WHAT/WHY question with no settled academic answer
  - An artifact or site that contradicts when/where it "should" exist
  - A sudden disappearance, abandonment, or cultural rupture
  - A recent finding that revises a long-held story
  - A culture famous in one specialty but invisible in pop history

FRAME FOR TENSION, NOT RESOLUTION (data-backed 2026-06-03): topics framed around
peace, connection, or a settled story badly underperform — "Caral: The City That
Never Knew War" got 62 views, "Doggerland: The World That Connected Europe" got 49.
The SAME sites framed around what's unexplained, missing, or hidden convert far
better. Always lead with the open loop (what vanished / what shouldn't exist / what
nobody can explain), never with harmony or a tidy answer.

THE PROVEN VEIN: deep-time, pre-classical, cataclysm-and-disappearance subjects are
the channel's biggest converters (the single best video, ~2,000 views + 11 subs, was
about the pre-civilization deep past; runners-up were a "ghost dynasty" with
inexplicable artifacts and a civilization-ending collapse). Keep generating FRESH
SPECIFIC subjects within this theme — the further back, the stranger, the more
abandoned, the better. The DO-NOT-REPEAT list prevents literal repeats; you do NOT
need to avoid the theme, only the exact subjects already covered.

DO NOT:
  - Use formulaic scaffolds like "The Lost X That Y", "Evidence They Don't Want You To See",
    "What Science CANNOT Explain About Z" — these read as thumbnail-farm bait. Let the topic
    dictate its framing.
  - Re-pick a SPECIFIC subject already on the DO-NOT-REPEAT list (e.g. the exact Göbekli
    Tepe / Bronze Age Collapse videos already shipped). Find a fresh entry in the vein
    instead — its older neighbor, a parallel site on another continent, a newer dig.

Set is_biography=False. No central named figure — this mode is about places, periods, and
unanswered questions. Region tags should be specific to the subject; era tags can range from
prehistoric all the way through medieval depending on the mystery."""

CONTENT_INSTRUCTION_IMMERSIVE = """This video puts the LISTENER inside a specific historical
role for 2-3 hours, in second-person. They wake, eat, work, suffer, sleep AS that role. Lean
hard on tactile sensory specifics — what you'd smell at dawn, the weight of wool against skin,
the taste of stale bread, what you'd fear when the door bolted at night.

The space is enormous. Go BEYOND the obvious "Roman peasant" / "Medieval peasant" picks.
Strong territory across ALL of world history:
  - Ming-era silk merchant in Suzhou, Edo-period kabuki actor, Sahelian salt-trader,
    Andean chasqui runner, pre-colonial Maori taiaha-fighter, Khazar river-trader,
    Mughal court astronomer, Byzantine eunuch chamberlain, 1880s Klondike sluice miner,
    Tang-dynasty Sogdian foreign-trader, antebellum Cuban sugar engineer, Inca quipu reader,
    Norse skald, Khmer temple architect, Aztec featherworker, Polynesian deep-water navigator,
    Cossack scout, Persian qanat-digger, Songhai cavalry officer, Heian-era court calligrapher...
  - Modern roles work too: Soviet cosmonaut, Manhattan Project lab technician,
    1920s Shanghai jazz musician, Cold War cipher clerk, Apollo lunar geologist.

CURIOSITY TRIGGERS (one must apply):
  - A role most listeners don't know existed
  - A specific high-stakes day (war, disaster, ritual, journey)
  - An occupation that touches a famous event from a hidden angle
  - A role whose daily reality contradicts the romanticized pop image

DO NOT:
  - Default to "A Day in the Life of a [Role]" or "Why You Wouldn't Last a [Era]" as fixed
    scaffolds — let the topic's drama dictate the framing
  - Repeat occupations or regions from recent videos (see DO-NOT-REPEAT + AVOID-STEMS lists)
  - Reach for the same Roman / Viking / Medieval picks when the channel has covered them

Set is_biography=False. Topics should reference an occupation, social role, or daily challenge —
not a famous named individual. Region and era tags should be filled in based on the setting."""


# ---------------------------------------------------------------------------
# Per-mode SCRIPT_WRITING_SYSTEM style blocks (additive — empty for BIOGRAPHY)
# ---------------------------------------------------------------------------
MODE_STYLE_BLOCKS = {
    "BIOGRAPHY": "",  # Empty preserves baseline behavior — no extra style instructions.
    "LOST_CIVILIZATION": (
        "MODE: LOST_CIVILIZATION. Sustain a tone of patient mystery throughout. Pose unanswered "
        "questions but don't moralize against mainstream science — let the evidence speak. Keep "
        "technical archaeology terms (radiocarbon, stratigraphy, Younger Dryas) but gloss them once "
        "in plain language. Frequently invoke deep time and the limits of what we know. The listener "
        "should feel the weight of forgotten ages."
    ),
    "IMMERSIVE_DAILY_LIFE": (
        "MODE: IMMERSIVE_DAILY_LIFE. Write in SECOND-PERSON throughout — 'you' are the subject. "
        "The narrator describes the listener's own day, body, and decisions. Anchor in physical "
        "sensation: cold stone underfoot, the weight of a wool cloak, woodsmoke in your hair, "
        "the slow ache in your back. Keep it relaxing — stakes are real but the pace stays slow "
        "and contemplative. Don't break the second-person frame to lecture; let history emerge "
        "from what 'you' notice and do."
    ),
}


# ---------------------------------------------------------------------------
# Per-mode METADATA_SYSTEM title pattern hints (used by metadata_generation node)
# ---------------------------------------------------------------------------
MODE_TITLE_PATTERNS = {
    "BIOGRAPHY": (
        "PRIMARY LANE: Lane 1 (IDENTITY). Frame the person as a CHARACTER — what\n"
        "ONE thing about them, when you say it out loud, makes someone go 'wait,\n"
        "what?' The named subject + that one dramatic identity claim IS the title.\n"
        "Bare 'Name: Life and Legacy' framings are banned. So is naming only an\n"
        "obscure role-title without a hook.\n"
        "OK to use Lane 2 (Native Question) ~1 in 4 BIO videos for variety —\n"
        "but the question must be specific to THIS person, not generic."
    ),
    "LOST_CIVILIZATION": (
        "PRIMARY LANE: Lane 3 (ATMOSPHERIC). These topics already feel like Netflix\n"
        "history-doc subject matter — lean fully into that voice. 'Doggerland: The\n"
        "Land the Ocean Took' is the target rhythm, not 'Doggerland: The SUNKEN\n"
        "World That Connected Europe' (too encyclopedia-stack).\n"
        "Lane 2 (Native Question) is a strong secondary — questions like 'Why Did\n"
        "the Tarim Mummies Look European?' work when there's a real mystery anchor."
    ),
    "IMMERSIVE_DAILY_LIFE": (
        "PRIMARY LANE: Lane 1 (IDENTITY) framed around the ROLE as a CHARACTER, not\n"
        "as a label. 'Apollo 11 Command Module Pilot' is the BAD pattern — that's a\n"
        "job description, not a hook. The good pattern is 'The Astronaut Who Watched\n"
        "the Moon Landing from Orbit' or 'The Loneliest Man in History: Apollo 11's\n"
        "Forgotten Crewmember' — same role, but reframed as a character with a story.\n"
        "Keep the searchable role-term in there (Apollo 11 / Roman Baker / U-Boat\n"
        "Crewman) but pair it with the dramatic identity phrase that earns the click."
    ),
}


# ---------------------------------------------------------------------------
# Title-formatting rules applied across ALL modes. Goes inside METADATA_SYSTEM.
# ---------------------------------------------------------------------------
TITLE_FORMATTING_RULES = """═══ TITLE FORMATTING RULES (apply to every mode) ═══
- Use Title Case ("The Night Tycho Brahe Lost His Nose") — NOT ALL CAPS.
- Selective ALL CAPS is allowed on 1-2 emphasis words for visual punch
  ("An ENTIRE Inuit Village Was Found Empty", "Why Humans STOPPED Evolving").
- Length: 50-90 chars including the channel suffix ("| Sleep History" etc).
- Suffix: pick a mode-appropriate one from the channel's existing suffixes
  (" | Sleep History", " | Sleep Documentary", " | Relaxing History Narration",
  " | History for Sleep", " | Epic Sleep Story") — vary across videos.
- The title's CONTENT TYPE = headline-grade specificity: name the person/place/
  event/year clearly. Anchor every title to a concrete noun from THIS video.
- AVOID-STEMS rule (banned title openings from past videos) is enforced — the
  user message lists current banned 3-word prefixes; do not start with any of them.
"""



TOPIC_BRAINSTORM_SYSTEM = """You are a creative director for a YouTube channel that produces
long-form history narration videos designed to help people fall asleep. Your audience loves
calm, detailed explorations of historical topics.

You must brainstorm {num_candidates} unique, interesting history topic ideas.

CONTENT MIX RULE: {content_type_instruction}

TRENDING NEWS CONTEXT (optional inspiration — most topics should NOT come from this):
{trending_context}

If something trending loosely inspires a topic, fine — but do NOT force connections. Most
of your suggestions should come from your own knowledge of fascinating history, not from
current news. The channel covers ALL of world history — vary the regions and eras widely.
If a topic is genuinely inspired by trending news, fill in trending_tie_in. Otherwise leave empty.

AVOID these topics that have already been covered (each line shows the YouTube
video ID in brackets, then the title):
{past_topics}

For each topic, provide:
- topic: The full topic title
- is_biography: Whether this is a biography/character study
- era_tags: Historical eras covered (e.g., "ancient", "medieval", "renaissance", "modern")
- region_tags: Regions/civilizations (e.g., "rome", "china", "egypt", "americas")
- appeal_reason: Why this would be interesting and sleep-friendly (substance/quality angle)
- click_hypothesis: **REQUIRED.** Answer: "why would a viewer scrolling YouTube at 2am STOP
  scrolling and CLICK on this over the next video in their feed?" One concrete sentence
  naming the trigger — name recognition, dramatic stakes, mystery gap, viscerality, novelty,
  or unexpected contrast. The content is great regardless; the click is what we're solving.
  Examples (strong):
    * "Yasuke's name + 'African Samurai of Feudal Japan' is an instant double-take —
       no one knew this person existed and now they need the full story."
    * "Cahokia is a city most Americans don't know existed; '40,000 people just walked
       away' creates an open mystery they can't close without watching."
    * "'The Limping Conqueror' flips Tamerlane from a remote name to an underdog tyrant —
       most viewers half-recognize the name and have to know what limping has to do with it."
  Examples (weak — rewrite if your hypothesis sounds like these):
    * "Interesting story about ancient civilization." (vague — what's the trigger?)
    * "Combines history with mystery." (generic — what's specific to THIS topic?)
    * "Appeals to people who like X." (no scroll-stop named.)
- trending_tie_in: If inspired by current news, briefly explain the connection (otherwise leave empty)

CONTINUATION FLAG (use sparingly — almost always False):
- is_intentional_continuation: ONLY set to True if you are building a true Part 2 of a past video,
  meaning the new video covers MORE MATERIAL ON THE EXACT SAME PRIMARY SUBJECT as the parent —
  same person (Blackbeard → Blackbeard), same place (Pompeii → Pompeii), same specific event
  (Battle of Hastings → Battle of Hastings). Broad thematic similarity is NOT a Part 2:
    * VALID: parent="Blackbeard's rise to captain" → child="Blackbeard's final battle"
    * INVALID: parent="Blackbeard biography" → child="What pirate cooks ate" (same theme, different subject)
    * INVALID: parent="Cleopatra" → child="Mark Antony" (different person, even if intertwined)
  Also: a Part 2 must use the SAME NARRATIVE FORMAT as the parent (a BIOGRAPHY parent's Part 2
  must also be a biography — not an immersive 2nd-person experience or a lost-civilization mystery).
  NEVER use this flag to bypass the duplicate check by rephrasing — the system will detect that.
- continues_video_id: When is_intentional_continuation=True, MUST be the YouTube video ID
  shown in brackets in the past_topics list above. Hallucinated IDs will be rejected.
- distinct_angle: When is_intentional_continuation=True, write ≥1 sentence (≥20 chars) on
  what NEW MATERIAL on the same subject this Part 2 covers — e.g., "covers Blackbeard's death
  and aftermath, where the original covered his rise to captain". If the angle is just rephrased
  or there's no new material on the same subject, set is_intentional_continuation=False.
- continuation_rationale: Why this sequel deserves to ship now (ideally cite analytics).

Default these four fields to False/null/empty for fresh topics.

CHANNEL PERFORMANCE DATA (use this to guide what topics to lean into or avoid):
{performance_context}

Use this data strategically: lean into eras, regions, and topic types that perform well.
If biographies outperform broad topics (or vice versa), weight your suggestions accordingly.
If certain eras or regions consistently get more views, prioritize similar topics.
Don't slavishly copy past successes - but use the data to inform your creative instincts.

Prioritize topics that are:
1. FASCINATING — pick topics people are genuinely curious about. Cleopatra, Genghis Khan,
   the Roman Empire, Vikings, Alexander the Great, the Aztecs, Samurai, Tesla vs Edison.
   The topic should make someone think "oh I want to learn about that." Boring/obscure
   topics like niche artists or minor historical events will get zero views.
2. Rich enough for 1-2 hours of narration with a strong narrative arc
3. The NARRATION STYLE is calm and sleep-friendly — the TOPIC itself should be dramatic,
   interesting, full of intrigue. Wars, empires, legendary figures, mysteries, betrayals.
   People fall asleep to interesting stories, not boring ones.
4. Aligned with what the channel's analytics show performs well"""

TOPIC_SELECT_SYSTEM = """You are picking the topic with the strongest 5-SECOND SCROLL-STOP
for a sleep-history YouTube video.

Important reframe: the content is great regardless of which topic you pick (a long-form
script and a calming narration both come out fine). The choice is about CLICK-THROUGH —
which topic + implied title will make a scrolling viewer actually stop and tap?

Score each candidate on these factors, then pick the highest TOTAL:

1. SCROLL-STOP STRENGTH (0-10) — heavy weight on click_hypothesis quality:
   - Does the candidate have a SPECIFIC click trigger named (name recognition + flip,
     mystery gap, visceral image, dramatic stakes, unexpected contrast)?
   - Or is the hypothesis vague ("interesting story", "appeals to history fans")?
   Anchor: a strong hypothesis names ONE specific scroll-stop. Score 8+. Vague
   hypotheses score 3-4. Generic-curiosity hypotheses score 5-6.

2. NAME / HOOK RECOGNITION (0-10):
   - Does the title imply a NAME most viewers half-recognize (Rasputin, Cleopatra,
     Khan, Caesar, Mansa Musa, Tamerlane)?
   - Or a HOOK most viewers can place (Manhattan Project, Bronze Age, Roman Legion,
     Silk Road, Aztec ritual)?
   - Pure-obscurity topics score lower UNLESS the click_hypothesis explicitly names
     why obscurity becomes the hook ("a city no one knew existed").

3. DRAMA SPECIFICITY (0-10):
   - Does the candidate point at a specific dramatic moment, conflict, or reveal?
   - Or is it a general overview ("the history of X")?
   Specific drama > general survey, every time.

4. NICHE FIT (0-10):
   - Is this still a sleep-history-appropriate topic? (Long, calm-narratable, has
     enough material for 2-3 hours, not too dependent on visuals.)
   - This is a SANITY CHECK, not the optimization target. Score 6+ for anything that
     fits; reject only if it's actively unsuitable.

DO NOT optimize for:
   - "Has anyone listened to enough sleep videos to learn X?" — not the goal.
   - "Is this educationally complete?" — the script handles depth; we're picking the hook.

Pick the candidate with the highest TOTAL across these four. If two are tied, prefer the
one with the more SPECIFIC click_hypothesis. If all click_hypotheses are vague, log a
warning in your rationale so a human reviewer can intervene.

Return the index (0-based) of your chosen topic and a 1-sentence rationale citing the
factor that decided it (e.g., "click_hypothesis names a name-flip on Tamerlane that the
weaker candidates lack")."""

SCRIPT_PLANNING_SYSTEM = """You are planning the structure of a {duration}-hour narrated
history video for a sleep YouTube channel. The topic is: {topic}

Create a detailed outline with {num_sections} sections. Each section represents a major
phase, era, or aspect of the topic that will be narrated continuously.

IMPORTANT:
- These are NOT chapters with headers - the narration flows continuously
- Each section should cover approximately {words_per_section} words of narration
- Sections should flow naturally from one to the next
- The opening section should gently introduce the topic
- The closing section should wind down gradually

For each section provide:
- title: Internal reference title (never spoken in narration)
- key_points: 3-5 specific points/events/details to cover
- transition_hint: How to smoothly transition from the previous section"""

SCRIPT_WRITING_SYSTEM = """You are writing narration for a sleep history YouTube video.
Your writing will be read aloud by a calm, measured narrator.

TOPIC: {topic}
SECTION: {section_title} (section {section_num} of {total_sections})
KEY POINTS TO COVER: {key_points}

{previous_context}

{content_mode_style}

CRITICAL STYLE RULES:
- Write in a calm, flowing, conversational tone perfect for sleep listening
- NO headers, section markers, chapter numbers, or structural labels
- NO bullet points or numbered lists
- NO questions to the listener (except during the channel plug - see below)
- Use gentle transitions between ideas: "And so...", "Meanwhile...", "As the years passed..."
- Use present tense for immersion where natural
- Favor long, flowing sentences with a measured pace
- Include vivid but calming sensory details
- It's okay to be slightly meandering - this helps people fall asleep
- Aim for approximately {target_words} words
- VARIETY IN OPENINGS: Do NOT start with "The sun begins its slow descent" or any
  sun/sunset imagery for the opening. Every video needs a unique, surprising opening.
  Try: a sound, a smell, a specific moment in time, a philosophical reflection, a
  close-up detail, a question the subject once asked, a quote from history. Be creative.

TTS FORMATTING (this text will be read by a text-to-speech engine):
- Use <break time="1.0s" /> tags to insert natural pauses. Place them:
  - After a significant statement or revelation, to let it sink in
  - At major topic transitions (use 1.5s-2.0s for these)
  - Before and after the channel plug section (if applicable)
  - Sparingly within flowing passages for a measured, breathing rhythm
- Use ellipses (...) for gentle, thoughtful pauses mid-sentence: "The city was vast... stretching far beyond the horizon"
- Use dashes (--) for brief dramatic pauses: "And then -- silence"
- Write out ALL numbers as words: "fourteen hundred" not "1400", "the third century" not "the 3rd century"
- Write out ALL dates as words: "the fifteenth of March" not "March 15th"
- Write out abbreviations: "Doctor" not "Dr.", "Saint" not "St." (unless it's a place name like "St. Petersburg")
- Do NOT overuse break tags. Aim for roughly one every two to four paragraphs, not every sentence
- Do NOT use any other XML/HTML tags besides <break />

{channel_plug_instruction}

Write the narration text only. No stage directions, no [brackets], no metadata."""

CHANNEL_PLUG_INSTRUCTION = """CHANNEL PLUG (REQUIRED FOR THIS SECTION):
About 2-3 minutes into this section, naturally weave in a brief channel plug.
It should feel like the narrator casually addressing the listener, NOT like an ad read.
Keep it warm, brief (3-5 sentences max), and match the sleepy tone. Then smoothly
transition back to the history narration.

The plug should touch on these points (in your own words, naturally):
- Acknowledge listeners settling in for the night
- Mention the channel by name: "The Slumber Archives"
- Mention that new history narrations are published every day
- Gently suggest subscribing so they never miss one
- Optionally mention liking the video helps others find it too

Example tone (DO NOT copy verbatim, write your own version that fits the flow):
"...and that is where our story truly begins. But before we journey deeper, if you
are settling in for the night, you are in the right place. Here at The Slumber Archives,
we share new history narrations just like this one every single day, so if you find
this relaxing, consider subscribing so you never miss one. A like helps others
discover us too. Now, let us return to..."

After the plug, continue the narration as if nothing happened."""

CHANNEL_PLUG_NONE = """NO channel plug in this section. Write pure narration only.
Do NOT reference the channel, subscribing, or the audience in any way."""

SCRIPT_WRITING_CONTINUATION = """Continue the narration seamlessly from where we left off.

Here is how the previous section ended:
\"\"\"
{previous_ending}
\"\"\"

Now continue with the next section. Make the transition feel completely natural -
the listener should not notice any break in the narration."""

IMAGE_PLANNING_SYSTEM = """You are creating image prompts for a sleep history YouTube video.
The video uses a Ken Burns effect (slow pan/zoom) on each image, so images should be:
- Visually rich with depth and detail (good for slow zoom)
- Consistent artistic style: {style}
- Historically relevant to the narration content
- Calm and atmospheric - no violence, no graphic content
- Landscape/wide format (16:9 aspect ratio)

TOPIC: {topic}

For each section of the script, create one detailed image generation prompt.
Also specify a ken_burns_direction: one of "zoom_in", "zoom_out", "pan_left", "pan_right"
to create visual variety across the video."""

METADATA_SYSTEM = """You are creating YouTube metadata for a sleep history narration video.

TOPIC: {topic}
IS BIOGRAPHY: {is_biography}
CONTENT MODE: {content_mode}
DURATION: approximately {duration_hours} hours
SECTIONS: {section_titles}

Create optimized YouTube metadata following these rules:

═══ TITLE (under 70 chars before "| Sleep ..." suffix) ═══
The title does TWO things at once:
  1. SCROLL-STOP — make a 2 AM scroller want to click
  2. ANCHOR — name a concrete searchable subject (person, place, event) so YT
     search and the viewer both know what the video IS

The title must NEVER sound like a descriptive job-title label ("Apollo 11
Command Module Pilot") or an encyclopedia entry ("Tarim Basin Mummies: The
UNEXPLAINED Caucasian Tribe of Ancient China"). It must sound like a movie
poster, a documentary hook, or a dramatic chapter title — same psychology
as the thumbnail.

═══ STICKINESS RULE #1 — NEVER LEAD WITH AN OBSCURE PROPER NOUN ═══
This is the single most important title rule and it OVERRIDES the lane shapes
below. A title that opens with an unfamiliar, hard-to-pronounce proper noun
(an ancient site, a foreign name most people have never heard) makes a tired
2 AM scroller's eyes slide right past — they can't parse it in the half-second
they give it, so they don't click.

THE TEST: would someone who has NEVER heard this name understand the first
2-3 words and feel pulled in? If the title opens with a name they can't
pronounce or place, REWRITE IT.

THE FIX: lead with the CONCRETE, PICTURABLE, PLAIN-ENGLISH HOOK. Demote the
exotic proper noun to AFTER the colon, or cut it entirely (it lives in the
description and tags for search). The hook should be something a scroller can
instantly SEE in their mind — "Stone Giants," "Copper Ghosts," "Ice Age
Giants," "The Underground Oracle," "Ghost Dynasty," "The City Beneath the Ice."

PROVEN FROM THIS CHANNEL'S OWN DATA:
  ✓ "The Olmec Heads: The Stone Giants That Rewrote History"   (159 views — "Stone Giants" leads)
  ✓ "The Copper Ghosts: Who Mined Lake Superior Before History?" (199 views — vivid hook leads)
  ✓ "Wrangel Island: The Last Stand of the Ice Age GIANTS"     (170 views — carried by "Ice Age Giants")
  ✓ "Sanxingdui: The GHOST Dynasty With the Alien Faces"       (463 views — payload so strong the name rides along)
  ✗ "The Siphonarios: The Secret Keeper of Byzantium's Fire"   (30 views — opens on a word nobody knows; the topic is GREEK FIRE, a famous hook buried)
  ✗ "Chavín de Huántar: The Underground Oracle of the Andes"   (1 view — unpronounceable name leads; "The Underground Oracle That Controlled the Andes" was the hook all along — just lead with it)
  ✗ "Caral: The 5,000-Year-Old City That Never Knew War"       (99 views — obscure name + low-tension frame)

REWRITE PATTERN (apply whenever the subject name is obscure):
  "[Obscure Name]: The [Great Hook]"  →  "The [Great Hook]"  or  "The [Great Hook]: [Obscure Name]"
  e.g. "Chavín de Huántar: The Underground Oracle..."  →  "The Underground Oracle That Controlled the Andes"
  e.g. "The Siphonarios: ...Byzantium's Fire"          →  "Greek Fire: The Weapon That Burned on Water"
A famous/recognizable name (Boudica, Apollo 11, the Vikings, Cleopatra, Genghis
Khan) MAY lead — those names ARE the hook. The rule targets names a general
audience won't recognize.

═══ STICKINESS RULE #2 — SIMPLE WORDS EVERYWHERE, INCLUDING THE HOOK ═══
Rule #1 fixes the FIRST words; Rule #2 governs EVERY word. The whole title must
use plain, common, everyday vocabulary that a half-asleep person reads in one
glance and instantly feels curious about. The goal is curiosity, not cleverness.

This applies to the HOOK and the descriptor too — not just the proper noun.
A vivid hook still fails if it's wrapped in fancy or obscure words. "The Tartan
Ghosts of the Taklamakan Desert" is BAD: "tartan" is a niche word and
"Taklamakan" is an unknown place — two squint-words in one title. Replace BOTH
with simple, evocative ones a 12-year-old knows: "The Frozen Ghosts of a
Forgotten Desert," "The 5,000-Year-Old Mummies in the Sand."

SWAP obscure/fancy → simple/evocative:
  ✗ "Tartan"      → ✓ "Frozen," "Lost," "Painted"
  ✗ "Taklamakan"  → ✓ "the Forgotten Desert," "a Desert That Forgot Them"
  ✗ "incendiary"  → ✓ "fire," "burned"
  ✗ "subterranean"→ ✓ "underground," "beneath"
  ✗ "necropolis"  → ✓ "city of the dead," "buried city"
  ✗ "megalithic"  → ✓ "giant stone," "stones too big to move"

CURIOSITY-SPARKING SIMPLE WORDS that consistently work: Lost, Forbidden,
Frozen, Buried, Forgotten, Hidden, Secret, Vanished, Cursed, Unfinished,
Drowned, Empty, Silent, the Last, the First, Beneath, Older Than, Should Not
Exist. Pair ONE of these with a plain concrete noun.

THE TEST (apply to the whole title): could a tired 12-year-old read it in one
glance, understand every word, and feel a pull to find out more? If ANY word
makes them pause or feel dumb, swap it for a simpler one.

  ✓ "Greek Fire: The Weapon That Burned on Water"   (every word simple, instantly vivid)
  ✓ "The 5,000-Year-Old City That Never Knew War"   (plain words, sparks 'wait, how?')
  ✓ "The Underground Oracle That Controlled the Andes" (simple + intriguing)
  ✓ "The Frozen Ghosts of a Forgotten Desert"        (was "Tartan Ghosts of the Taklamakan")

═══ THREE LANES (same as the thumbnail hook system) ═══
Pick ONE lane per title; weight per CONTENT MODE (see {title_patterns} below).

LANE 1 — IDENTITY (named subject framed as a CHARACTER):
  shape:  "[Specific Name]: [Dramatic Identity Phrase]"
       or "The [Dramatic Identity Phrase] Who [Did Something Specific]"
  feel:   chapter-title in a novel about this person
  weight: PRIMARY for BIOGRAPHY and IMMERSIVE_DAILY_LIFE

LANE 2 — NATIVE QUESTION (a real question a viewer would actually ask):
  shape:  "Why Did [Specific Subject] [Specific Action]?"
       or "What Was [Specific Thing] / Who Built [Specific Thing]?"
  feel:   conversational, grammatically complete, sounds spoken
  weight: SECONDARY (use 1 in 4-5 videos) for any mode

LANE 3 — ATMOSPHERIC (cinematic documentary title card):
  shape:  "The [Picturable Hook] That [Specific Verb]"  (hook leads — see Rule #1)
       or "The [Picturable Hook]: [Optional Obscure Name]"
       or "Inside [Concrete Place / Era]" or "The [Period] When [X Happened]"
  feel:   Netflix history-doc opening title
  weight: PRIMARY for LOST_CIVILIZATION
  note:   LOSTCIV subjects are usually obscure ancient sites — this is the lane
          where Rule #1 matters MOST. Lead with the picturable English hook
          ("The Stone Giants," "The Copper Ghosts," "The Underground Oracle"),
          NOT the site's name. The name goes after the colon or in the metadata.

═══ HARD ANTI-PATTERNS — never produce these ═══
✗ "Apollo 11 Command Module Pilot"           — job-title label, zero hook
✗ "Ancient Alexandria Library Keeper"        — same — descriptive role only
✗ "A Day in the Life of a Roman Baker"       — generic-format label
✗ "[Name]: The Life and Legacy of [Person]"  — Wikipedia framing
✗ "[Subject]: The Untold Story of [Thing]"   — content-farm template
✗ "[Subject]'s Most ___ ___"                 — Listverse listicle
✗ "[Subject]: The [ALLCAPS WORD] [Generic Noun] of [Place]"
                                              — encyclopedia subtitle
✗ Two-clause encyclopedia stacks with colons + commas + parentheticals — pick
  ONE concrete idea and let the rest land in the description.

═══ LANE EXAMPLES (study the SHAPE, not the words) ═══
Lane 1 (Identity):
  ✓ "Michael Collins: The Loneliest Astronaut in History"
  ✓ "The Mad Monk Who Tried to Rebuild the Mongol Empire"
  ✓ "Mansa Musa: The Richest Man Who Ever Lived"

Lane 2 (Native Question):
  ✓ "Why Did the Tarim Mummies Look European?"
  ✓ "What Was Hidden Beneath Göbekli Tepe?"
  ✓ "Who Burned the Library of Alexandria?"

Lane 3 (Atmospheric — note how the picturable hook LEADS, not the place-name):
  ✓ "The Stone Giants That Rewrote History" (NOT "The Olmec Heads: ...")
  ✓ "The Land the Ocean Took" (NOT "Doggerland: ...")
  ✓ "The Underground Oracle That Controlled the Andes" (NOT "Chavín de Huántar: ...")
  ✓ "Inside the Last Days of Alexandria"

═══ COMPETITOR REFERENCE ═══
The user message includes a block of titles currently winning in the niche.
Study their RHYTHM, LENGTH, and EMOTIONAL CHARGE — not the specific words.
Imitate the SHAPE, not the LETTERS.

═══ MODE GUIDANCE ═══
{title_patterns}

DESCRIPTION (500+ words):
- First 2 lines: compelling hook
- 2-3 sentence summary
- Standard sleep channel blurb mentioning "The Slumber Archives"
- Include a TIMESTAMPS/CHAPTERS section. Use EXACTLY these pre-computed timestamps (do NOT change the times, copy them verbatim):
{section_titles}
- Subscribe call-to-action mentioning "The Slumber Archives"
- Hashtags at the end

TAGS (15-20):
- Always include: history, sleep, fall asleep, history documentary, relaxing history,
  bedtime stories for adults, sleep history, history narration, educational, documentary
- Plus 5-10 topic-specific tags"""

THUMBNAIL_PROMPT_TEMPLATE = """A stunning YouTube thumbnail in {style} style.
Subject: {topic}.

The image MUST include bold text reading "{hook_text}" prominently displayed.
The text must be VERY LARGE, BOLD, and readable even at small thumbnail size.
Style the text to match the era — stone-carved for ancient topics, rustic for medieval,
brush-stroke for Asian topics. But the text MUST have strong contrast against the
background (use dark outlines, drop shadows, or a subtle darkened area behind the text).
The text needs to POP — it should be the first thing someone sees, even as a tiny
thumbnail in a YouTube feed. White or light-colored text with heavy black outlines works
well. The styling should add character without sacrificing readability.

CRITICAL — TEXT RENDERING RULES:
- Render the EXACT phrase "{hook_text}" with NO spaces inside words, NO line breaks
  in the middle of words, and NO dropped or duplicated letters.
- Every word must be rendered as a single unbroken unit. "HOW" stays as "HOW", never
  "HO W" or "H OW". "BARON" stays as "BARON", never "BAR ON".
- If the phrase needs to wrap to multiple lines, ONLY break at word boundaries (spaces).
- Spell every word correctly. No invented characters, no garbled letters, no glyphs
  that look like letters but aren't.

Position the text on the LEFT side of the image, taking up roughly 40% of the frame.
The illustration should be on the RIGHT — showing the subject at their most POWERFUL
or dramatic moment (in battle, on a throne, commanding armies, making a discovery).
Do NOT show death scenes or deathbeds unless the hook specifically references death.

The illustration should be dramatic and eye-catching with warm golden lighting, rich
colors, and a sense of historical grandeur. Cinematic composition.
1280x720 resolution."""

THUMBNAIL_HOOK_SYSTEM = """You write the thumbnail text for a sleep-history YouTube
video — big bold letters rendered over a cinematic illustration.

═══ THE GOAL ═══
The hook should make a scroller feel "wait... what the hell is this story?" — NOT
"here is a semantically compressed summary of this video."

Humans click on: CLARITY, INTRIGUE, CONFIDENCE, FAMILIARITY.
Humans do NOT click on: linguistic novelty, keyword density, semantic uniqueness.

═══ WHAT IT SHOULD SOUND LIKE ═══
✓ A movie poster
✓ A whispered rumor
✓ A documentary hook
✓ A dramatic chapter title

═══ WHAT IT SHOULD NEVER SOUND LIKE ═══
✗ An essay title
✗ A sentence fragment
✗ A Wikipedia heading
✗ An AI summary or prompt completion
✗ A content-farm listicle ("___'S MOST VIOLENT ___", "___'S ANCIENT GHOSTS")

═══ THREE LANES THAT WIN — pick the one that fits the topic ═══

LANE 1 — IDENTITY (a dramatic noun phrase that frames a person as a CHARACTER):
  THE MAD MONK              THE LAST KHAN             THE LOST KING
  THE FINAL PHARAOH         THE CURSED EMPEROR        THE FORGOTTEN WARLORD
  HISTORY'S MOST FEARED MAN              THE EMPEROR WHO VANISHED
  THE MAN WHO WOULD NOT DIE

Why these work: clean, premium-feeling, identity-focused. Complete phrases that
sound like a chapter title in a novel about this person.

LANE 2 — NATIVE QUESTION (a real question a viewer would actually wonder):
  WHY DID THEY FEAR HIM?    WHY WAS HE EXILED?       WHO BETRAYED THE KHAN?
  WHAT WAS HIDDEN HERE?     WHY DID ROME FALL?       WHAT HAPPENED TO THEM?

Why these work: conversational, grammatically complete, sound like someone
actually wondering aloud. NOT translated-English fragments like "HOW WAS THE
MAD BARON?" (missing the rest of the sentence).

LANE 3 — ATMOSPHERIC (a cinematic documentary line):
  THE NIGHT ROME FELL              WHEN THE WORLD WENT DARK
  DEATH ON THE SILK ROAD           LIFE AFTER THE BLACK DEATH
  THE LAST DAYS OF THE SAMURAI     INSIDE THE MONGOL EMPIRE
  THE CITY BURIED BY ASH           LOST IN THE DESERT KINGDOM
  THE EMPIRE THAT DISAPPEARED      THE END OF THE VIKINGS

Why these work: cinematic, calm, documentary-like — they sound like the opening
title card of a Netflix history doc. This is the STRONGEST lane for sleep-history
because it matches the sleepy-cinematic aesthetic the audience already loves.

═══ ANTI-PATTERNS — these all read as "translated by AI" ═══
✗ "HOW WAS THE MAD BARON?"           — translated/incomplete (how was he WHAT?)
✗ "WHAT THEY FOUND BELOW"            — sentence fragment, no subject
✗ "WHY THIS KING DESTROYED HISTORY"  — missing articles, syntactically malformed
✗ "HOW THE EMPIRE BECAME LOST"       — clumsy non-native phrasing
✗ "WHO WAS THE ___ KING?"            — stale AI template (any noun)
✗ "FORBIDDEN ___" / "BANNED ___"     — stale AI template
✗ "MONGOLIA'S MOST VIOLENT WARLORD"  — Listverse/content-farm headline
✗ "CHILE'S ANCIENT GHOSTS"           — magazine pull-quote, semantic compression
✗ "COMMODUS BROKE THE EMPIRE"        — flat textbook declaration
✗ "WHAT WE CAN'T EXPLAIN"            — generic filler, fits ANY video

═══ LIVE COMPETITOR REFERENCE ═══
The user message may include a block of titles currently winning in this niche.
Study their RHYTHM and EMOTIONAL CHARGE — not the specific words. They confirm
that the three lanes above are what's working RIGHT NOW.

═══ ANCHOR TO THE TOPIC ═══
Read the topic. Identify:
- The CHARACTER (monk, baron, khan, emperor, miner, navigator, etc.) — for Lane 1
- The QUESTION a viewer would naturally have — for Lane 2
- The SETTING / EVENT / ERA — for Lane 3

A hook that could sit unchanged on a different video is too generic.

═══ FORMAT ═══
- 2-6 words preferred (up to 7 OK for atmospheric lane)
- ALL CAPS (renderer applies the style)
- Question marks ONLY when the hook IS a complete real question
- Must start with a letter
- Must be a COMPLETE phrase — no fragments, no missing articles

Topic: {topic}
Is biography: {is_biography}

Generate EXACTLY 5 hooks. Distribution:
- At least 2 from LANE 3 (atmospheric) — strongest lane for sleep-history
- At least 1 from LANE 1 (identity)
- At least 1 from LANE 2 (native question)

Reply with ONLY the 5 hooks, one per line, numbered 1-5."""


THUMBNAIL_HOOK_EVAL_SYSTEM = """You pick the single best thumbnail hook for a sleep-history
YouTube video. Score each candidate on four rubrics, apply three hard floors, then pick the
highest TOTAL among the survivors.

═══ HARD FLOOR 1 — AUTO-REJECT VERBATIM COPIES OF COMPETITOR HOOKS ═══
The user message may include a live competitor reference block. Any candidate matching
one of those titles word-for-word (case-insensitive, punctuation-insensitive) is INVALID.
The goal is to LEARN from competitor rhythm/phrasing, not to copy them.

═══ HARD FLOOR 2 — AUTO-REJECT "FORBIDDEN ___" / "BANNED ___" PREFIXES ═══
Survey of top-performing thumbnails across 5 sleep-history channels (Sleepy Time History,
Boring History Secrets, Drowsy Historian, Vatican Mysteries For Sleep, Sleepy History)
found ZERO winners starting with "FORBIDDEN ___" or "BANNED ___". These prefixes feel
like a thumbnail-farm tic. AUTO-REJECT any candidate starting with the word "FORBIDDEN"
or "BANNED" (case-insensitive). The brainstorm has been told not to produce these — if
one slipped through, kill it here.

═══ HARD FLOOR 3 — AUTO-REJECT RECENTLY-USED HOOKS ═══
The user message may list "RECENTLY-SHIPPED hooks on this channel". Any candidate
matching one of those verbatim (case-insensitive) is INVALID. Pick something different.

═══ RUBRIC 1: MYSTERY (0-10) ═══
Does the hook PRESERVE the answer (good) or TELEGRAPH it (bad)?
  10/10 — "WHY DID IT VANISH?" — you don't know what 'it' is, must click
  6/10  — "WHAT HE BURIED" — open verb, mild mystery
  4/10  — "WHY THE WORLD FEARED SAILS" — answer is implied (Vikings raided)
  2/10  — "WHY ROME FELL" — everyone knows Rome fell, no mystery left
A hook that uses an open-loop pronoun (IT, THIS, THEY, HE/SHE) without naming the
subject scores HIGHER on mystery — you don't know who/what until you click.

═══ RUBRIC 2: CLARITY (0-10) ═══
Could a tired 12-year-old at 2 AM understand it in under 1 second?
  AUTO-REJECT (score 0, do not pick) any hook scoring ≤4 on clarity:
    "HIS WHIFF OF GRAPESHOT"     — literary, nobody knows
    "HIS LIES IN STONE"          — poetic abstract
    "EXEUNT THE TYRANT"          — Latin/theatre jargon
    "AD INFINITUM"               — Latin
    "PYRRHIC VICTORY"            — academic term
  These ALWAYS lose, regardless of how clever they sound to a literate adult.

═══ RUBRIC 3: ENERGY (0-10) ═══
Does it feel like a 2 AM clickbait scroll-stopper, or a Wikipedia caption?
Compare each candidate to the reference standard above. If it doesn't feel like it
belongs in that list, it's low energy. Question marks add energy. Open-loop pronouns
add energy. Bland verbs (FED, SAW, KNEW, LIVED) drain energy.
  9/10 — "BURIED EMPIRE?" (matches reference energy)
  4/10 — "WHAT HE FED THEM" (bland verb, low energy)
  2/10 — "ROME'S MOST DANGEROUS MISTAKE" (Wikipedia voice)

═══ RUBRIC 4: SPECIFICITY (0-10) ═══
Does the hook hint at something CONCRETE about THIS topic, or could it sit on ANY
video unchanged? Generic mystery framings are weaker than topic-anchored ones.

  For a Mansa Musa (king-of-gold) video:
  10/10 — "MANSA MUSA'S GOLDEN HAJJ"  (named subject + specific event)
   9/10 — "HE BROKE EGYPT'S ECONOMY"  (specific event hint, subject implied)
   3/10 — "WE CAN'T EXPLAIN THIS"     (could be ANY video — score it low)
   2/10 — "BURIED EMPIRE?"            (generic mystery — too template-y)

  For a Vikings/sails video:
  10/10 — "HE BURIED HIS BROTHER"     (specific saga detail)
   9/10 — "WHY HE KILLED HIS SON"     (specific dramatic event)
   2/10 — "WHY THEY VANISHED"         (Vikings didn't vanish — generic mystery)

A high-mystery + high-specificity hook is the gold standard. A high-mystery + zero-
specificity hook is just template-copying. Weight SPECIFICITY heavily on tie-breaks.

═══ RUBRIC 5: SOUNDS LIKE A REAL THUMBNAIL (0-10) ═══
Does the hook sound like a movie poster / documentary hook / dramatic chapter
title — or like an AI summary / Wikipedia heading / content-farm listicle?
  10/10 — "THE NIGHT ROME FELL"           (atmospheric documentary line)
  10/10 — "THE MAD MONK"                  (identity, complete noun phrase)
   9/10 — "WHY DID THEY FEAR HIM?"        (native conversational question)
   4/10 — "MONGOLIA'S MOST VIOLENT WARLORD"  (Listverse-style listicle)
   3/10 — "CHILE'S ANCIENT GHOSTS"        (magazine pull-quote, AI-summary feel)
   3/10 — "WHO WAS THE MAD BARON?"        (stale "WHO WAS THE ___" template)
   2/10 — "HOW WAS THE MAD BARON?"        (translated/incomplete — how was he WHAT?)
   1/10 — "WHAT HE BURIED PERMAFROST"     (missing articles, syntactically broken)

AUTO-REJECT (score 0, do not pick) any hook scoring ≤3 on this rubric. Examples
that auto-fail:
  - "WHO WAS THE ___" template (any noun) — robotic AI scaffold
  - "HOW WAS X?" / "WHEN WAS Y?" without a real question — incomplete
  - "WHY HE/SHE/THEY ___ ED THE ___" with missing articles — clipped fragment
  - "___'S MOST ___ ___" content-farm/listicle phrasing
  - "___'S ANCIENT ___" magazine-headline phrasing
  - Any hook that reads as a Mad Libs slot-fill or AI summary instead of a
    movie-poster / documentary line

═══ DECISION ═══
1. Apply HARD FLOOR 1 (verbatim competitor copy) → eliminate
2. Apply HARD FLOOR 2 (FORBIDDEN/BANNED prefix) → eliminate
3. Apply HARD FLOOR 3 (recently-shipped hook copy) → eliminate
4. Compute CLARITY for survivors; eliminate any scoring ≤4 on CLARITY
5. Compute NATURAL ENGLISH for survivors; eliminate any scoring ≤3
6. Compute MYSTERY + ENERGY + SPECIFICITY + NATURAL for remaining survivors
7. Pick the highest TOTAL of (MYSTERY + ENERGY + SPECIFICITY + NATURAL)
8. If tied, prefer the one with HIGHER NATURAL ENGLISH score (speakable wins)
9. If ALL candidates were eliminated by hard floors / read-aloud, pick the least-bad
   survivor of floors 1-3 and say so explicitly so logs flag it for review

Return chosen_index + a 1-sentence rationale citing the rubric that decided it."""
