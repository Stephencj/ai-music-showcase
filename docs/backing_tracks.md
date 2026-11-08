# Carol backing tracks

Sing-along / play-along versions of the public-domain carols in
`src/composition/carols.py`, in any of the six Christmas styles, for videos
like "Silent Night • Backing Track in C • Lyrics & Chords".

## What a backing track is

Two arrangement variants (`arrangement` on `/api/generate`, the song plan and
the song tools):

- `backing_track`: the full arrangement with **no lead or melody
  instrument** (the instrument that would carry the tune plays its
  accompaniment part instead). It starts with a **one-bar count-in** on a
  recorded closed hi-hat (the sampled kit, GM key 42; never a synthesised
  click), then a clear intro (the carol's last phrase, chords only), **one
  verse per pass** of the carol, an interlude before the last verse when
  there are three or more, and the held ending with its ritardando. No key
  change unless `key_change` is asked for. With no `length_seconds`, it plays
  one pass per verse of the carol's lyric file (up to four); carols without a
  lyric file use the normal length.
- `guide_melody`: the same, with the melody kept **very quiet** as a guide
  (a "Guide Melody (<instrument>)" track levelled to -32 LUFS, well under
  the band; the count-in hits are levelled to about the band's peaks).

The two are exclusive (the latest one asked for wins). They work in every
Christmas style (`christmas_*_full`) and with the other variants
(`less_busy`, `warmer`, `sleigh_bells`, ...).

Ways in:

| Where | How |
|---|---|
| Describe / revise (web Create, `/api/describe`, `/api/revise`) | "backing track", "karaoke", "sing-along", "no melody" → `backing_track`; "with a guide melody" → `guide_melody`; "in G" → `key`; "lower key" / "higher key" → a whole step down / up (no key yet: the carol's low / high voice key); "for a low voice" / "high voice" → the voice preset key |
| `POST /api/generate` | `{"genre": "christmas_jazz_trio_full", "tune": "silent_night", "key": "G", "arrangement": "backing_track"}`; the finished job's `urls.timing` is the timing JSON |
| `POST /api/backing-tracks` | one carol in several keys (below) |
| Song tools (MCP, `/api/tools`) | `generate_song(..., arrangement="backing_track")` (its `files.timing`), `backing_tracks(tune=..., keys=[...])` |

## Keys

`key` is the tonic: "G" is G major for a major carol and G minor for a minor
one (What Child Is This, Carol of the Bells); "Em" is E minor. The tempo
comes from the style and the carol (or `tempo`) and stays the same from key
to key for the same seed.

`backing_tracks` / `POST /api/backing-tracks` render one carol in several keys
at once (`src/audio_processing/render/backing.py`). Default keys: C, D, F, G,
Bb (a minor carol uses their relative minors: A, B, D, E, G minor) plus two
voice presets:

- `low`: the transposition that puts the melody in about F3-C5 (alto, or a
  baritone an octave down);
- `high`: about C4-G5 (soprano, or a tenor an octave down).

The preset picks the key with the least of the melody outside the range,
then the most centred, preferring common singers' keys
(`src/composition/backing.py: voice_key`). When a preset lands on a key that
is already rendered, the index points it at that key's files.

Output, in `data/outputs/backing/<carol>/` (MP3 and JSON only; the WAVs and
MIDI are deleted):

```
silent_night_orchestral_G.mp3         backing track
silent_night_orchestral_G.json        its timing
silent_night_orchestral_G_guide.mp3   with the guide melody (guide_melody or both)
silent_night_orchestral_G_guide.json
silent_night_orchestral_keys.json     index: every key and preset → its files
```

## Lyrics

The words are not in the code. `scripts/setup/fetch_carol_lyrics.py`
downloads each carol's public-domain text into `data/lyrics/<carol>.txt`
(sources and why each is public domain: `data/lyrics/SOURCES.md`) and prints
only counts. `src/composition/lyrics.py` splits each line into syllables
(character spans) and lines them up with the melody:

- the verses' lines are matched to the tune's phrases (all verses at once,
  so every verse shares the music's phrase boundaries: lines end on held
  notes and start on their bar or as a pickup);
- within a line, extra notes become melismas (a syllable slurred over quick
  stepwise notes, at most 6 per line) and extra syllables split the longest
  notes (at most 3 per line);
- a refrain is sung after each verse when the tune carries it (the First
  Nowell, Jingle Bells).

Carols without a lyric file (Carol of the Bells, which is instrumental, and
Angels We Have Heard on High) get chords-only timings
(`lyrics.available: false`).

## Timing JSON (schema `ai-music.backing-timing/1`)

All times are seconds from the start of the audio. Lyric text is never
copied: lines are physical line numbers in `lyrics.file`
(`text.splitlines()[line]`) and syllables are `[start, end)` character spans
in that line.

```jsonc
{
  "schema": "ai-music.backing-timing/1",
  "tune": "silent_night", "title": "Silent Night", "style": "orchestral",
  "variant": "backing_track",            // or "guide_melody"
  "key": "G", "final_key": "G", "scale": "major",
  "transpose": -5,                       // semitones from the written melody (C / A minor) to the key
  "tempo": 72.0, "time_signature": [3, 4],
  "audio": "silent_night_orchestral_G.mp3", "duration": 271.4,

  "count_in": {"bars": 1, "start": 0.0, "end": 2.5, "clicks": [0.0, 0.83, 1.67], "sound": "closed hi-hat"},

  // every bar: its beat times (quarter-note beats) and its section index
  "bars": [{"n": 0, "start": 0.0, "end": 2.5, "beats": [0.0, 0.83, 1.67], "section": 0}, ...],

  // the form
  "sections": [{"index": 1, "label": "Intro", "role": "intro", "kind": "intro",
                "start": 2.5, "end": 12.5, "bars": [1, 4], "key": "G"},
               {"index": 2, "label": "Verse 1", "kind": "pass1", "pass": 1, ...}, ...],

  // the chord sounding at each moment, named in the rendered key
  "chords": [{"start": 2.5, "end": 5.0, "symbol": "G", "roman": "I", "bar": 1, "beat": 0.0}, ...],

  // the tune's phrases: lyric lines where there are lyrics, else phrase_bars chunks
  "phrases": [{"start": 12.5, "end": 21.8, "section": 2, "pass": 1, "line": 4}, ...],

  // the melody in the rendered key (what the guide plays, octave aside): [MIDI pitch, start, end]
  "melody": [[67, 12.5, 13.75], ...],

  "lyrics": {
    "available": true,
    "file": "data/lyrics/silent_night.txt",
    "verses": 5,
    "lines": [{"line": 4, "stanza": 0, "pass": 1, "section": 2, "start": 12.5, "end": 21.8,
               "syllables": [{"i": 0, "start": 12.5, "end": 13.75, "chars": [0, 2]}, ...]}, ...]
  }
}
```

Field notes:

- `count_in` is null for a full (non-backing) song; `bars[0]` is the
  count-in bar for a backing track.
- `sections[].key` changes only with `key_change`; chords are named in their
  section's key.
- `lyrics.lines[].stanza` is the verse index (0-based) in the file;
  `pass` counts passes of the tune from 1. A pass beyond the file's verses
  has no lines (instrumental).
- Times follow the MIDI tempo map, including the ending's ritardando; swung
  styles (swing, trio) place off-beat syllables on the swung eighth.

## Karaoke and the vocal guide

Save a backing track as a block (Generate → Save as block, or
`save_as_block` in the tools): `GET /api/blocks/{name}/karaoke` then serves
the carol's melody as the pitch lane and its words with their times (built
from the same timing), so the web KaraokeScreen works on it; for a
`guide_melody` block, `GET /api/blocks/{name}/vocal-guide-audio` plays the
guide track.

## Tests

`tests/unit/test_backing_tracks.py` (no lead, guide level, transposition,
count-in, timing schema and lyric alignment counts),
`tests/e2e/test_backing_tracks_mcp.py` (one carol in two keys through the
song tools) and `web/tests/e2e/carol-describe.spec.ts` (a carol named in
Describe reaches `/api/generate` with its `tune`).
