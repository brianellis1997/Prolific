"""Centralized LLM prompts for the YouTube sleep history pipeline."""

# ---------------------------------------------------------------------------
# Content-mode instruction blocks
# ---------------------------------------------------------------------------
# Three content modes power the 5-day cadence:
#   BIOGRAPHY (Mon/Wed/Fri) — famous historical figure deep dive (existing)
#   LOST_CIVILIZATION (Thu) — prehistoric mystery / lost-civilization curiosity gap
#   IMMERSIVE_DAILY_LIFE (Sat) — second-person daily-life / survival immersion
# These strings are injected as `content_type_instruction` into TOPIC_BRAINSTORM_SYSTEM.

CONTENT_INSTRUCTION_BIOGRAPHY_FIXED = (
    "This video should be a BIOGRAPHY / character deep dive about a specific historical figure."
)

CONTENT_INSTRUCTION_BIOGRAPHY_FORCED = (
    "This video MUST be a BIOGRAPHY / character deep dive. "
    "The channel needs more biography content. Focus on a specific historical figure."
)

CONTENT_INSTRUCTION_BROAD_TOPIC = (
    "This video should be a BROAD TOPIC exploration (civilization, era, event, cultural movement) "
    "rather than a single person's biography."
)

CONTENT_INSTRUCTION_LOSTCIV = """This video MUST explore a prehistoric mystery, lost civilization,
archaeological enigma, or unexplained ancient phenomenon. Lean into the curiosity gap between
mainstream archaeology's claims and what evidence might suggest. Topics should evoke scale, deep
time, and authority denial — Göbekli Tepe, the Younger Dryas impact hypothesis, sunken Sundaland,
the pre-Clovis horizon, the Bronze Age collapse, megalithic enigmas, antediluvian sites.

Frame topics with patterns like:
  - "The Lost X That Y"
  - "What Science CANNOT Explain About Z"
  - "The Forgotten Epoch Before Civilization"
  - "We Were NOT The First..."
  - "Evidence They Don't Want You To See"

Set is_biography=False. Era tags should skew prehistoric / antediluvian / pre-classical. Region
tags can stay specific (Anatolia, Egypt, Mesoamerica, Indus Valley, etc.). AVOID framings centered
on a single named historical figure — this mode is about places, periods, and unanswered questions."""

CONTENT_INSTRUCTION_IMMERSIVE = """This video MUST be a second-person daily-life or survival
immersion. The listener IS the medieval peasant / Roman legionnaire / Viking trader / Egyptian
embalmer / Aztec chocolate maker for the next two hours. The listener experiences the period from
inside their body — they wake, eat, work, suffer, sleep.

Topic patterns:
  - "A Day in the Life of a [role] in [era]"
  - "Why You Wouldn't Last a Week as a [role]"
  - "How [role]s Survived [hardship] Without [modern thing]"
  - "What It Felt Like to Be a [role] During [event]"

Lean on tactile sensory specifics — what you'd smell at dawn, the weight of wool against skin,
the taste of stale bread, what you'd fear when the door bolted at night. Set is_biography=False.
Topics should reference an occupation, social role, or daily challenge — NOT a famous individual.
Era and region tags should still be filled in based on the setting."""


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
        '- "The Untold Story of X | Sleep History"\n'
        '- "X: The Life and Legacy | Relaxing History Narration"\n'
        '- "[Figure]: The Architect of Y | Sleep History"'
    ),
    "LOST_CIVILIZATION": (
        '- "The Lost X That Science Can\'t Explain | Sleep History"\n'
        '- "What They Found Beneath X | Relaxing History"\n'
        '- "The Forgotten Epoch Before Civilization | Sleep Documentary"\n'
        '- "Evidence of X That Mainstream Archaeology Ignores | History for Sleep"'
    ),
    "IMMERSIVE_DAILY_LIFE": (
        '- "A Day in the Life of a [Role] | Sleep History"\n'
        '- "Why You Wouldn\'t Last a Day in [Setting] | Relaxing History"\n'
        '- "How [Role]s Survived [Era] | Sleep Documentary"\n'
        '- "Inside the Daily Life of a [Role] | History for Sleep"'
    ),
}



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
- appeal_reason: Why this would be interesting and sleep-friendly
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

TOPIC_SELECT_SYSTEM = """You are selecting the single best topic from a list of candidates
for a sleep history YouTube video. Choose the topic that:
1. Is the most INTERESTING and COMPELLING — would someone actually want to listen to this?
2. Would appeal to the widest audience — famous figures and events beat obscure ones
3. Is distinct from past videos on the channel
4. Has enough drama, intrigue, and depth for 1-2 hours of narration
5. Pick legendary figures (Cleopatra, Caesar, Napoleon) and epic events (fall of Rome,
   age of pirates) over niche/obscure topics that nobody searches for

Return the index (0-based) of your chosen topic and a brief rationale."""

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

TITLE (under 70 characters):
- Front-load the topic keyword
- Include a sleep/relaxation signal
- Choose from these patterns based on the CONTENT MODE above:
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

Position the text on the LEFT side of the image, taking up roughly 40% of the frame.
The illustration should be on the RIGHT — showing the subject at their most POWERFUL
or dramatic moment (in battle, on a throne, commanding armies, making a discovery).
Do NOT show death scenes or deathbeds unless the hook specifically references death.

The illustration should be dramatic and eye-catching with warm golden lighting, rich
colors, and a sense of historical grandeur. Cinematic composition.
1280x720 resolution."""

THUMBNAIL_HOOK_SYSTEM = """You write SHORT, scroll-stopping thumbnail text for a sleep-history
YouTube video. The text appears on a cinematic AI-generated image. Your job is to make a
random viewer at 2 AM click — NOT to summarize the topic.

═══ THE GOLDEN RULE ═══
A great hook DOES NOT TELEGRAPH THE ANSWER. It hints at a mystery and forces the click
to resolve. If the words alone reveal what happens, the viewer scrolls past.

═══ REFERENCE — REAL HOOKS FROM A 148K-SUBSCRIBER COMPETITOR ═══
These videos pull 5K-50K views each. Match this energy:
  "WE CAN'T EXPLAIN THIS..."     ← open-loop "THIS", admission of mystery
  "WHY DID IT VANISH?"           ← question mark + mystery verb + open-loop "IT"
  "BURIED EMPIRE?"               ← 2 words, mystery vocab + question
  "WHAT DID HE SEE?"             ← question + open-loop "HE"
  "OUR WEIRD COUSINS"            ← informal + curious adjective + open-loop "COUSINS"
  "AN ENTIRE VILLAGE GONE?"      ← "ENTIRE" intensifier + mystery verb
  "WHY DID THEY VANISH?"         ← question + open-loop "THEY"
  "100,000 YEARS AGO"            ← timestamp + image carries mystery

Notice: SHORT (2-4 words), heavy use of "?", open-loop pronouns (IT, THIS, HE, THEY) so
the viewer DOESN'T know who/what — that IS the curiosity gap. Mystery vocabulary is the
fuel: VANISH, GONE, BURIED, ERASED, FORBIDDEN, COVERED UP, FORGOTTEN, HIDDEN, EXPLAIN.

═══ WORKING PATTERNS (pick a different one per candidate) ═══
1. "WHY DID THEY [verb]?"           — open-loop "they"     ex. "WHY DID THEY VANISH?"
2. "WHAT [HE/SHE] [strong verb]"    — open-loop pronoun    ex. "WHAT HE BURIED"
3. "WE CAN'T EXPLAIN [THIS/IT]"     — admission of mystery ex. "WE CAN'T EXPLAIN THIS"
4. "[ADJECTIVE] [NOUN]?"            — short + mystery      ex. "BURIED CITY?"
5. "THE UNTOLD [NOUN]"              — pure intrigue claim  ex. "THE UNTOLD ORDER"
6. "[VERB]ED FROM HISTORY"          — erasure framing      ex. "ERASED FROM HISTORY"
7. "[NUMBER] YEARS AGO"             — timestamp + image    ex. "1,000 YEARS LOST"

═══ HARD BANS — never produce these ═══
- Literary/academic references nobody knows: "WHIFF OF GRAPESHOT", "EXEUNT", "AD INFINITUM"
- Poetic abstractions that need decoding: "LIES IN STONE", "WHISPERS OF TIME"
- Hooks that telegraph the answer: "WHY THE WORLD FEARED SAILS" (you can guess: Vikings raided),
  "WHY ROME FELL" (everyone knows Rome fell)
- Generic filler: "RISE AND FALL", "A GREAT LEADER", "FORGOTTEN EMPIRE", "ANCIENT HISTORY"
- Bland verbs: "FED", "SAW", "LIVED", "KNEW" — replace with visceral verbs (BURIED, BANNED, KILLED)

═══ EXAMPLES FROM YOUR OWN CHANNEL ═══
✓ "WHY HE KILLED HIS SON"        — visceral verb + open-loop pronoun
✓ "THE CAPTAIN THEY VOTED FOR"   — unexpected (pirates voted?), trails into mystery
✗ "WHY THE WORLD FEARED SAILS"   — answer telegraphed (Vikings)
✗ "HIS WHIFF OF GRAPESHOT"       — obscure, nobody knows what it means
✗ "HIS LIES IN STONE"            — poetic but unclear
✗ "WHAT HE FED THEM"             — bland verb, no scroll-stop

═══ FORMAT ═══
Length: 2-4 words. Question marks ENCOURAGED. ALL CAPS for the final overlay.

Topic: {topic}
Is biography: {is_biography}

Generate EXACTLY 5 different hooks, each using a different pattern from the list above.
At least 2 must end in "?". At least 1 must use an open-loop pronoun (IT, THIS, THEY).
Reply with ONLY the 5 hooks, one per line, numbered 1-5."""


THUMBNAIL_HOOK_EVAL_SYSTEM = """You pick the single best thumbnail hook for a sleep-history
YouTube video. Score each candidate on three rubrics, then pick the highest TOTAL.

The reference standard is real hooks from a 148K-subscriber competitor that pull 5K-50K
views per video:
  "WE CAN'T EXPLAIN THIS..."   "WHY DID IT VANISH?"   "BURIED EMPIRE?"
  "WHAT DID HE SEE?"           "OUR WEIRD COUSINS"    "AN ENTIRE VILLAGE GONE?"

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
  9/10 — "BURIED EMPIRE?" (matches reference)
  4/10 — "WHAT HE FED THEM" (bland verb, low energy)
  2/10 — "ROME'S MOST DANGEROUS MISTAKE" (Wikipedia voice)

═══ DECISION ═══
1. Compute MYSTERY + CLARITY + ENERGY totals for all 5 candidates.
2. AUTO-REJECT any candidate scoring ≤4 on CLARITY (the hard floor).
3. Among the survivors, pick the highest TOTAL.
4. If two are tied, prefer MORE MYSTERY.
5. If ALL candidates score poorly, pick the least-bad and say so explicitly so a
   human reviewer can intervene.

Return chosen_index + a 1-sentence rationale citing the rubric you weighted."""
