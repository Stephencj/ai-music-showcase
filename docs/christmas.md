# Christmas styles

Background-friendly Christmas music for long, cozy videos. Engine:
`src/composition/christmas.py`; tunes: `src/composition/carols.py`.

## Styles

| genre | sound |
|---|---|
| `christmas_swing_full` | Big-band crooner swing: ride (or brushes), walking upright bass, piano, sax section with the tune, muted trumpets + French horn pads |
| `christmas_jazz_trio_full` | Cozy jazz trio: piano over left-hand shells, upright bass, brushes, rubato ending |
| `christmas_orchestral_full` | Warm film orchestra: strings, horn, flute, clarinet, harp, glockenspiel, sleigh bells; ends on the strings |
| `christmas_fireside_full` | Acoustic: nylon guitar fingerpicking, soft piano, cello, light shaker |
| `christmas_choir_full` | Reverent: choir chorale, quiet pipe organ, strings, "Amen" ending |
| `christmas_pop_full` | Light pop anthem: soft kit, bass, piano, acoustic guitar, strings, sleigh bells, glockenspiel, clean guitar lead |

They show up on the genre wheel under **Christmas**.

## Tunes

`tune` is a public-domain carol (melody and words published before 1929):
`silent_night`, `jingle_bells`, `deck_the_halls`, `good_king_wenceslas`,
`joy_to_the_world`, `angels_we_have_heard`, `what_child_is_this`,
`the_first_noel`, `carol_of_the_bells` (Leontovych's 1916 melody,
instrumental) — or `original` (the default): a new AABA tune with Christmas
harmony (ii–V turnarounds, secondary dominants, diminished passing chords,
IV–iv–I, suspensions) and a cozy title. Copyrighted songs (White Christmas,
Let It Snow, Rudolph, Sleigh Ride, …) are refused; `carols.DENYLIST` and a
unit test keep them out.

## Form

`plan_song` lays out: intro on the tune's last phrase → a soft first pass →
fuller passes (countermelody, sparkle) → an interlude → a last pass that may
lift a half step (through a pivot dominant) → a tag → a plagal cadence held
with a ritardando. `length_seconds` (120–300) picks the number of passes.
Every accompaniment note that would rub a half step against a held melody
note is moved to a chord tone (unit-tested at zero across every carol and
style).

## Options

`arrangement` (comma-separated): `sleigh_bells`, `brushes`, `less_busy`,
`warmer`, `celesta_ending`, `strings_ending`, `key_change`,
`no_key_change`, `plain_harmony`, `rich_harmony`, `choir_pad`,
`backing_track`, `guide_melody` (sing-along backing tracks: no melody or a
very quiet one, a count-in, one verse per pass and a timing JSON; see
[backing_tracks.md](backing_tracks.md)).
Christmas songs are delivered at **−16 LUFS** unless `target_lufs` says
otherwise (a gentle limiter shaves peaky piano transients so they reach it).

Describe / revise understand e.g. "cozy jazz trio Christmas, Silent Night,
background", "add sleigh bells", "warmer", "less busy", "end on the celesta",
"make it orchestral", "Silent Night backing track in G", "with a guide
melody", "lower key".

## Playlist mixes (hour-long videos)

One file of N songs, levelled to one loudness and joined with equal-power
crossfades; styles, keys, tempos, tunes and seeds vary (no style twice in a
row, no carol repeated before every carol has played). A tracklist JSON and
YouTube chapter lines come back.

- Song tool (MCP / `/api/tools`): `christmas_mix(total_minutes=60, target_lufs=-16)`
- HTTP: `POST /api/christmas-mix {"total_minutes": 60}` → a job
- CLI: `python scripts/christmas_mix.py --minutes 60 --name christmas-ambience-1`

Files land in `data/outputs/playlists/` (MP3 320 kbps; `--wav` / `formats`
for a 24-bit WAV). Rendering takes about 10–20 s per song.

## Instruments

All CC0 recordings where a free library exists (see
`data/instruments/README.md`): VCSL grand piano, harp, glockenspiel, sleigh
bells, shaker; VSCO 2 CE strings, horn, flute, clarinet, oboe, quiet pipe
organ, muted trumpets; Karoryfer Sneakybass upright bass; the recorded brush
kit. Celesta, nylon / acoustic guitar and choir use the General MIDI
soundfont (MuseScore_General).
