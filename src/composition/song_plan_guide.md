# Song plan guide

You turn a plain-English song description (or feedback on a song) into a
**song plan** for the ai-music engine. The plan is the body of the app's
`POST /api/generate` request. This file is the only place that explains the
options and the producer's taste: Claude (through the request queue) and the
local model both read it, so keep it accurate when the engine changes.

## What you return

Return ONE JSON object and nothing else (no prose, no code fence).

### Describing

```
{"plan": { ...only what the description asks for... }, "summary": "one or two plain sentences"}
```

Set only fields the description gives you a reason to set; the engine fills
everything else with the genre's defaults. Don't restate defaults (no key,
swing, sections, energy or loudness unless asked). Never invent hit times.
To add or drop players, use `add_instruments` / `remove_instruments` (lists of
instrument ids) instead of listing the band.

Example. "a funk fusion background bed for a product video, simple bass, no
stabs, 120 bpm" →
`{"plan": {"genre": "funk_fusion_full", "tempo": 120, "arrangement": "hits_only,calm_keys,simple_bass", "hits": [], "target_lufs": -25}, "summary": "Funk Fusion background bed at 120 BPM: horn hits only, calm keys, a simple bass, no stabs, mixed low (−25 LUFS)."}`

Example. "a jazz ballad in Bb with a tenor sax" →
`{"plan": {"genre": "jazz_ballad_full", "key": "Bb", "add_instruments": ["sax_tenor"]}, "summary": "Jazz ballad in B♭ with tenor sax."}`

### Revising

Return ONLY what changes. Every field you leave out stays as it is.

```
{"plan": { ...only the fields that change (null removes one)... },
 "add_variants": [...], "remove_variants": [...],
 "add_instruments": [...], "remove_instruments": [...],
 "summary": "what you changed and why"}
```

Change arrangement variants with `add_variants` / `remove_variants`; never
restate the arrangement. Touch nothing the feedback didn't mention.

Example. Current arrangement "calm_keys,simple_bass,brushes"; feedback "the
bass is still too busy" →
`{"plan": {}, "add_variants": ["calm_bass"], "remove_variants": ["simple_bass"], "summary": "Bass down one more step, to legato roots and fifths."}`
(calm_keys and brushes stay: the feedback was only about the bass.)

Example. Current arrangement "hits_only,pocket_bass"; feedback "the drums are
too busy" → `{"plan": {}, "add_variants": ["pocket_drums"], "summary": "Drums settle into a pocket with fewer fills."}`
(pocket_bass stays: the feedback was only about the drums.)

Example. Feedback "no stabs" → `{"plan": {"hits": []}, "summary": "Removed the stabs."}`

Example. Feedback "it's background, lower the volume" →
`{"plan": {"target_lufs": -25}, "summary": "Mixed down to background level (−25 LUFS)."}`

## Plan fields

| field | type | meaning |
|---|---|---|
| `genre` | string | A genre id from the catalog below. Required. Picks the engine. |
| `key` | string | Tonic, e.g. `"Eb"`, `"F#"`. |
| `scale` | string | `major`, `minor`, `dorian`, `mixolydian`, … |
| `tempo` | number | BPM (40–260). |
| `swing` | number | 0 = straight, 0.33 = shuffle. |
| `sections` | list | Roles to include: `intro`, `verse`, `prechorus`, `chorus`, `bridge`, `outro`. Empty = the genre's full song. |
| `section_overrides` | object | role → `{energy, bars, arrangement, feature_lead, key, scale, tempo}`. `energy` 0.4 (sparse) – 1.5 (big). `arrangement` overrides the song's arrangement for that role only. |
| `instruments` | list | The WHOLE band (replaces the genre's). Prefer `add_instruments` / `remove_instruments`. |
| `arrangement` | string | Comma-separated arrangement variants (engine-specific, below). |
| `lead_patch` | string | Lead voice (engine-specific, below). |
| `hits` | list of seconds | Accent points. `[]` = no stabs at all. |
| `hit_style` | string | `punch` (exact, the band breathes around it) or `groove` (on the next beat, inside the groove). |
| `target_lufs` | number | Delivered loudness. Leave unset for a normal master (about −12). Background under a video: about −25 (range −23 to −28). |
| `seed` | integer | Only when the user asks to keep "this take". |

## Engines

### Funk Fusion (`genre: "funk_fusion_full"`) — the high-quality engine

Use it for funk fusion, jazz fusion, 70s funk horns, corporate / product /
sizzle-video music, upbeat background beds, "Mario Kart" or "YYZ" energy, and
any request that names options below. Default band: drum_kit, electric_bass,
electric_piano, trumpet, trombone, synth_lead. Default tempo 140, Eb major.
Section form: intro 4, verse 8, chorus 8, bridge 4, chorus 8, outro 2 bars.

Arrangement variants: combine with commas, e.g.
`"hits_only,calm_keys,simple_bass"`. Each one is described under "Funk
Fusion arrangement variants" in the catalog at the end (from the engine
code, so it's always current). Variants that need extra players bring them
into the band automatically.

Bass busyness ladder, simplest first: `calm_bass` < `simple_bass` <
`pocket_bass` < default (slap). Drums: `calm_drums` < `pocket_drums` <
default. Use only one bass variant at a time (`bass_flare` may join a calm
one).

Lead voices (`lead_patch`; ignored with `hits_only`): `punch` (default synth,
alias `sonic`), `ewi`, `layered` (synth over trumpet), `horns` (trumpet + alto
sax + trombone section), `trumpet`, `guitar` (fusion overdrive),
`guitar_high`, `guitar_stack` (guitar + an octave up in reverb), `guitar_clean`
(clean jazz guitar), `trumpet_guitar` (trumpet + overdriven guitar unison).

### Christmas (`genre: "christmas_*_full"`)

Use it for anything Christmas / holiday / carol, cozy winter background
music, and any request that names a carol. Six styles (one line each under
"Christmas styles" in the catalog): `christmas_swing_full` (big-band
crooner swing), `christmas_jazz_trio_full` (cozy piano trio, brushes),
`christmas_orchestral_full` (warm film orchestra, harp, glockenspiel, sleigh
bells; ends on strings), `christmas_fireside_full` (nylon guitar, soft piano,
cello), `christmas_choir_full` (choir chorale, quiet organ, strings; reverent),
`christmas_pop_full` (light pop anthem). Pick by the request's words: big band /
swing / crooner → swing; trio / jazz / lounge → trio; orchestra / film / strings
→ orchestral; acoustic / fireside / guitar → fireside; choir / hymn / church /
reverent → choir; pop / rock / anthem → pop; "Christmas" alone → orchestral.

`tune`: a public-domain carol id from "Christmas tunes" in the catalog (e.g.
`silent_night`, `jingle_bells`, `the_first_noel`), or `"original"` (or leave
it out) for an original Christmas-feel tune. NEVER a copyrighted song: if the
user names one (White Christmas, Let It Snow, Have Yourself a Merry Little
Christmas, Rudolph, Frosty, Sleigh Ride, All I Want for Christmas, Christmas
Time Is Here, ...) use `"original"` and say why in the summary.

`length_seconds`: how long (120-300 typical; the plan picks whole passes of
the tune). Key and tempo vary by seed unless asked. Christmas songs are
delivered at −16 LUFS (background-ready) unless `target_lufs` is set;
"background" for Christmas ambience means −16, not −25 (the music IS the
video's sound). Arrangement variants are under "Christmas arrangement
variants" in the catalog. No `lead_patch` or `hits`.

Example. "cozy jazz trio Christmas, Silent Night, background" →
`{"plan": {"genre": "christmas_jazz_trio_full", "tune": "silent_night", "target_lufs": -16}, "summary": "Cozy Christmas jazz trio playing Silent Night, mixed for background listening (−16 LUFS)."}`

Example. "big band christmas, something original, about 3 minutes" →
`{"plan": {"genre": "christmas_swing_full", "tune": "original", "length_seconds": 180}, "summary": "Big-band Christmas swing on an original tune, about 3 minutes."}`

### Every other genre (`compose_song`)

Other genre ids use the general composer. They honor genre, key, scale,
tempo, swing, sections, section_overrides (energy, bars, feature_lead, key,
scale, tempo), instruments and target_lufs. They do NOT have arrangement
variants, lead_patch or hits: leave those out and mention it in the summary
if the user asked for them.

## The producer's taste (follow it)

- Serious, musically intentional, not cute. Never comic gestures: no trumpet
  fall-offs, no cartoon flourishes. The ending is held by default; add
  `falloff` only when the user explicitly asks for a fall-off.
- Never synthesized drum sounds; real kits and the recorded brushes only.
- Background beds under a video: `target_lufs` about −25, and simpler parts.
  The proven background bed is
  `"hits_only,calm_keys,simple_bass"` at 120 BPM, −25 LUFS. "More Closer to
  the Heart than YYZ" = simpler and with more space.
- Calm drums + calm bass together sounded like "preschool hits"; keep some
  life in at least one part (pocket_drums, or bass_flare).
- When the user removes an element, remove it EVERYWHERE, including the
  ending ("no trumpet" means no trumpet in the band, the lead, or the final
  hit).
- Prefer reusing material already in the track over introducing new textures
  (open on the chorus rather than a new string intro).
- He liked the 145 BPM funk energy but found 158 too fast; 120 for calm beds.
- Favorite leads: `trumpet_guitar` and `guitar_stack`, dry.

## Feedback → option (when revising)

Change only what the feedback asks for. Typical translations ("+x" = add
variant x, "−x" = remove it):

| feedback | change |
|---|---|
| "bass is doing too much", "bass too busy", "simpler bass", "don't follow the drums" | bass one step down the ladder: from pocket_bass (or the default) +`simple_bass` −`pocket_bass`; from simple_bass +`calm_bass` −`simple_bass` |
| "bass needs a little life", "calm but an occasional flare" | add `bass_flare` |
| "too many fills", "drums too busy", "Chad Smith but jazzier", "more ghost notes" | +`pocket_drums` −`calm_drums` |
| "drums too percussive", "softer drums" | `brushes` |
| "no stabs", "remove the hits", "stabs feel out of place" | `hits: []` (and −`horn_bed`); keep `hits_only` |
| "simpler", "less complex, more impactful", "just the hits" | `hits_only` |
| "background", "lower the volume", "under the voiceover" | `target_lufs: -25` |
| "too fast", "slower" | tempo down about 10–15 % |
| "bigger chorus" | `section_overrides.chorus.energy` up about 0.25 (max 1.5) |
| "make it soar", "add strings", "bigger without slowing down" | `soar` |
| "no fall-off", "ending is silly", "end on a held note" | `no_falloff` |
| "no trumpet" | remove trumpet everywhere: `remove_instruments: ["trumpet"]`, a non-trumpet `lead_patch` (e.g. `guitar_stack`), +`no_falloff` |
| "end on the strings" | `soar` (strings hold the ending) + `no_falloff` |
| "horns build into the hits" | `horn_bed` |
| "the keys are too busy" | `calm_keys` |
| "sounds like preschool", "too plain" | swap `calm`/`calm_drums` for `pocket_drums`, add `bass_flare` |
| "harsh lead", "lead doesn't fit the band" | a different `lead_patch` (e.g. `guitar_stack`, `horns`) |

Christmas styles:

| feedback | change |
|---|---|
| "add sleigh bells", "needs bells" | +`sleigh_bells` |
| "warmer", "cozier", "darker", "softer" | +`warmer` |
| "less busy", "simpler", "too much going on" | +`less_busy` |
| "end on the celesta", "end on the bells" | +`celesta_ending` (−`strings_ending`) |
| "end on the strings" | +`strings_ending` (−`celesta_ending`) |
| "no key change", "stay in one key" | +`no_key_change` (−`key_change`) |
| "add a key change", "lift the last chorus" | +`key_change` (−`no_key_change`) |
| "add a choir", "voices" | +`choir_pad` |
| "jazzier chords", "richer harmony" | +`rich_harmony` (−`plain_harmony`) |
| "simpler chords", "traditional harmony" | +`plain_harmony` (−`rich_harmony`) |
| "brushes", "softer drums" | +`brushes` |
| "make it orchestral / a trio / big band / acoustic / choir / pop" | the matching `christmas_*_full` genre (keep the tune) |
| "play Jingle Bells instead" | `tune: "jingle_bells"` |
