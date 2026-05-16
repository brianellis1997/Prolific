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

DO NOT:
  - Use formulaic scaffolds like "The Lost X That Y", "Evidence They Don't Want You To See",
    "What Science CANNOT Explain About Z" — these read as thumbnail-farm bait. Let the topic
    dictate its framing.
  - Default to the same handful of subjects (Göbekli Tepe, Sundaland, Younger Dryas, pre-Clovis,
    Bronze Age Collapse) — the channel has covered these. The DO-NOT-REPEAT list shows what's stale.

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
        "STRUCTURE: Put the specific FIGURE first or center. The title should hint at\n"
        "what makes THIS person's story unexpected — a dramatic event, a contested side,\n"
        "or a claim that flips their pop-culture image. Avoid generic 'X: The Life and\n"
        "Legacy of Y' framings. Anchor to a SPECIFIC arc, not the whole life.\n"
        "ENERGY: Match what's actually winning right now (see LIVE COMPETITOR INSPIRATION\n"
        "block in the prompt). Don't invent stale templates. Watch the AVOID-STEMS list."
    ),
    "LOST_CIVILIZATION": (
        "STRUCTURE: Feel like the headline of a real unsolved case file, anchored to the\n"
        "SPECIFIC subject of this video. The viewer should learn what the video is about\n"
        "from the title — not be teased by a poetic abstraction.\n"
        "ENERGY: Match what's actually winning right now (see LIVE COMPETITOR INSPIRATION\n"
        "block in the prompt). Don't invent stale templates. Watch the AVOID-STEMS list."
    ),
    "IMMERSIVE_DAILY_LIFE": (
        "STRUCTURE: The title must tell the viewer what the video IS — name the\n"
        "specific role + setting clearly (e.g., 'Manhattan Project Lab Technician',\n"
        "'WWI U-Boat Crewman', 'Ming Dynasty Eunuch Chamberlain'). The sensory immersion\n"
        "happens INSIDE the script — the title's job is to make the viewer pick it up.\n"
        "Do not lead with abstract sensory openings like 'THE HEAT OF THE SIPHON' or\n"
        "'THE TICK OF THE TELETYPE' — they obscure the topic. Lead with the role/event.\n"
        "ENERGY: Match what's actually winning right now (see LIVE COMPETITOR INSPIRATION\n"
        "block in the prompt). Don't invent stale templates. Watch the AVOID-STEMS list."
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
to resolve. AND the hook must anchor to something SPECIFIC about THIS topic — a generic
mystery phrase that could sit on any video means nothing.

═══ WHAT'S ACTUALLY WORKING (real top-performer thumbnails, 5 sleep-history channels) ═══
Study WHY each works. **NEVER copy these verbatim** — the eval auto-rejects exact copies.

  Sleepy Time History (153K subs):
    "WHAT DID WE ACTUALLY DO?"          (2.1M views — direct question + "WE")
    "THE MYSTERY OF RH NEGATIVE BLOOD"  (1.2M — CATEGORY-OF-thing + specific subject)
    "WE CAN'T EXPLAIN THIS HISTORY GAP" (832K — mystery admission + specific anchor)
    "THE FIRST WHITE PEOPLE?"           (671K — provocative claim/question)
    "WHY AFRICA?"                       (397K — 2-word direct question)
    "THE FULL HISTORY OF CATS"          (381K — "THE FULL HISTORY OF X")

  Vatican Mysteries For Sleep (32K subs):
    "TOP SECRET"                        (685K — bold claim, intrigue)
    "VATICAN'S GREATEST FEAR?"          (456K — possessive + intensifier + ?)
    "THE VATICAN KNOWS WHO THEY WERE"   (276K — authority-reveal claim)
    "TERRIFYING SECRETS REVEALED"       (— intensifier + reveal promise)
    "WHO WERE THEY?"                    (— bare question + open-loop pronoun)

  Sleepy History (26K subs):
    "Fall asleep to the history of LONDON"        (808K — soft promise + specific place)
    "FALL ASLEEP The history of THE INDUSTRIAL REVOLUTION" (— soft promise + specific event)
    "Fall Asleep To the history of KING HENRY VIII"        (— soft promise + specific figure)

═══ FIVE PATTERNS THAT WIN — vary across the 5 hooks you generate ═══
1. **DIRECT QUESTION** (highest CTR pattern in the data):
   "WHO BUILT THIS?", "WHY DID THEY LEAVE?", "WHAT DID HE SEE?", "WHO WERE THEY?"
   Use WHO/WHAT/WHY + an open-loop pronoun (THEY, HE, SHE, IT, THIS).

2. **MYSTERY ADMISSION + SPECIFIC ANCHOR**:
   "WE CAN'T EXPLAIN THE TARIM MUMMIES", "NOBODY KNOWS WHO CARVED THESE"
   Pair "WE CAN'T EXPLAIN / NOBODY KNOWS / SCIENCE IGNORES" with a SPECIFIC thing
   from your video. NOT generic — name the specific subject.

3. **PROVOCATIVE CLAIM / DECLARATION**:
   "THE FIRST AMERICANS", "TOP SECRET", "THE BIBLE GOT IT WRONG", "HE BURIED A CONTINENT"
   A short, declarative, controversial-feeling statement that contradicts a default belief.

4. **CATEGORY-OF-THING** (works great when the subject is the click):
   "THE MYSTERY OF RH-NEGATIVE BLOOD", "THE FULL HISTORY OF CATS",
   "THE SECRET OF MOHENJO-DARO", "THE LAST DAY OF POMPEII"
   "THE [adjective] [category] OF [specific topic]" — anchors hard to the subject.

5. **CAPITAL INTENSIFIER + REVEAL**:
   "TERRIFYING SECRETS REVEALED", "WHAT HE BURIED", "WHY THEY OBEYED"
   Use a strong intensifier (TERRIFYING, GREATEST, REAL, FIRST, LAST) + a curiosity hook.

═══ HARD ANTI-PATTERNS — never produce these ═══
- **"FORBIDDEN ___"** and **"BANNED ___"** prefixes are STALE — they don't appear in
  any top-performer thumbnail across 5 channels surveyed. Avoid both.
- Literary/academic references nobody knows: "WHIFF OF GRAPESHOT", "AD INFINITUM"
- Poetic abstractions: "LIES IN STONE", "WHISPERS OF TIME"
- Hooks that telegraph the answer: "WHY THE WORLD FEARED SAILS" (Vikings raided),
  "WHY ROME FELL" (everyone knows Rome fell)
- Generic filler that could sit on any video: "ANCIENT HISTORY", "RISE AND FALL",
  "FORGOTTEN EMPIRE"
- Bland verbs: "FED", "SAW", "LIVED", "KNEW" — replace with visceral verbs

═══ EXAMPLES FROM YOUR OWN CHANNEL ═══
✓ "WHY HE KILLED HIS SON"        — visceral verb + open-loop pronoun
✓ "WHY DID THEY BUILD THIS?"     — direct question, open-loop "THEY" and "THIS"
✓ "THE CAPTAIN THEY VOTED FOR"   — unexpected drama, trails into mystery
✗ "FORBIDDEN GOLD?"              — generic FORBIDDEN prefix; subject too abstract
✗ "BANNED ANCESTORS?"            — generic BANNED prefix
✗ "BURIED FOR CENTURIES?"        — could sit on any video; no specific anchor
✗ "BRAIDS IN THE DESERT?"        — confusing, no clear hook
✗ "HIS WHIFF OF GRAPESHOT"       — obscure reference
✗ ",000 MILES LOST?"             — malformed (broken number)

═══ FORMAT ═══
Length: 2-6 words. Question marks ENCOURAGED. ALL CAPS for the final overlay.
**MUST start with a letter or "$" or quote.** Never start with a comma, period,
or stray digit (parser-broken output).

Topic: {topic}
Is biography: {is_biography}

Generate EXACTLY 5 different hooks, each using a DIFFERENT pattern from the five above.
At least 2 must use Pattern 1 (DIRECT QUESTION). At least 1 must include a specific
noun/name from the topic (subject anchor). NONE may start with "FORBIDDEN" or "BANNED".
Reply with ONLY the 5 hooks, one per line, numbered 1-5."""


THUMBNAIL_HOOK_EVAL_SYSTEM = """You pick the single best thumbnail hook for a sleep-history
YouTube video. Score each candidate on four rubrics, apply three hard floors, then pick the
highest TOTAL among the survivors.

═══ HARD FLOOR 1 — AUTO-REJECT VERBATIM COPIES OF REFERENCES ═══
The brainstorm prompt lists real competitor thumbnails. Any candidate matching one of
these word-for-word (case-insensitive, punctuation-insensitive) is INVALID:
  "WHAT DID WE ACTUALLY DO?"        "THE MYSTERY OF RH NEGATIVE BLOOD"
  "WE CAN'T EXPLAIN THIS HISTORY GAP"   "THE FIRST WHITE PEOPLE?"
  "WHY AFRICA?"                     "THE FULL HISTORY OF CATS"
  "TOP SECRET"                      "VATICAN'S GREATEST FEAR?"
  "THE VATICAN KNOWS WHO THEY WERE" "TERRIFYING SECRETS REVEALED"
  "WHO WERE THEY?"                  any "Fall asleep to the history of X"

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
  10/10 — "FORBIDDEN GOLD?" (specific to gold-bringing king)
   9/10 — "HE BURIED A KINGDOM"  (specific event hint)
   3/10 — "WE CAN'T EXPLAIN THIS"  (could be ANY video — score it low)
   2/10 — "BURIED EMPIRE?"  (could apply to dozens of topics — generic mystery)

  For a Vikings/sails video:
  10/10 — "HE BURIED HIS BROTHER"  (specific Viking saga detail)
   9/10 — "WHY HE KILLED HIS SON"  (specific dramatic event)
   2/10 — "WHY THEY VANISHED"  (Vikings didn't vanish — generic mystery)

A high-mystery + high-specificity hook is the gold standard. A high-mystery + zero-
specificity hook is just template-copying. Weight SPECIFICITY heavily on tie-breaks.

═══ DECISION ═══
1. Apply HARD FLOOR 1 (verbatim reference copy) → eliminate
2. Apply HARD FLOOR 2 (recently-shipped hook copy) → eliminate
3. Compute CLARITY for survivors; eliminate any scoring ≤4 on CLARITY
4. Compute MYSTERY + ENERGY + SPECIFICITY for remaining survivors
5. Pick the highest TOTAL of (MYSTERY + ENERGY + SPECIFICITY)
6. If tied, prefer the one with HIGHER SPECIFICITY (topic-anchored beats generic)
7. If ALL candidates were eliminated by hard floors, pick the least-bad survivor of
   floors 1-2 (ignore clarity floor as last resort) and say so explicitly

Return chosen_index + a 1-sentence rationale citing the rubric that decided it."""
