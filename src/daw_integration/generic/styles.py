"""
Genre style presets for the MIDI composer.

Each StylePreset bundles tempo, key/scale, chord progression, voicings,
bass/drum patterns, and swing into one recipe. Apply one with
``styles.apply(STYLES["funk"], bars=16, seed=42)`` to get a fully-built
MidiExporter ready to save or synthesize.

Each preset carries a *list* of progression variations (different pacing
and/or chord cells idiomatic to the genre). The first variation is the
"Default" and what ``progression`` returns for legacy callers. The full
list is exposed via ``progression_variants`` so the Compose tab's
variation dropdown can offer alternatives without breaking compatibility
with code that reads ``StylePreset.progression`` directly.
"""

from dataclasses import dataclass, field
from typing import Optional, Union

from .midi_export import MidiExporter


# A single progression plan — same shape the parser / generators accept.
# Each item is either a bare roman numeral (1.0-bar duration implicit) or
# a (symbol, duration_bars) tuple that supports sub-bar pacing.
ProgressionPlan = list[Union[str, tuple[str, float]]]

# A named variation displayed in the UI dropdown.
ProgressionVariation = tuple[str, ProgressionPlan]


@dataclass
class StylePreset:
    """A genre recipe for the MIDI composer.

    ``progression`` is the *default* progression (variation 0). Optional
    ``progression_variants`` adds named alternatives — the Compose tab's
    "Preset variation" dropdown picks among these, and the Random toggle
    rolls one each Compose. When ``progression_variants`` is empty,
    ``__post_init__`` synthesises a single ("Default", progression) entry
    so every preset uniformly exposes a non-empty variant list.
    """

    name: str
    tempo: float
    key: str
    scale: str                # SCALES key
    progression: ProgressionPlan   # default — see also progression_variants
    voicing: str              # triad | seventh | ninth | power | drop2
    bass_pattern: str
    drum_pattern: Optional[str]  # None or "" → skip drums (orchestral)
    chord_octave: int = 3
    bass_octave: int = 2
    melody_octave: int = 4       # vocal range: C4-C5 anchor, palette reaches C5-C6
    melody_density: float = 0.7
    swing: float = 0.0        # 0 straight, ~0.33 full triplet
    chord_rhythm: str = "pulse_quarter"  # see STRUM_RHYTHMS / ARPEGGIO_PATTERNS
    melody_style: str = "motif"          # motif | riff | arc | random
    chord_program: int = 0    # GM program for chord track
    bass_program: int = 33    # Electric Bass (finger)
    melody_program: int = 0
    time_signature: tuple[int, int] = (4, 4)  # (4,4), (3,4), or (6,8)
    progression_variants: list[ProgressionVariation] = field(default_factory=list)

    # Per-instrument idiom variants — each is a flat dict of
    # ``{generator_kwarg: value}`` that flows into the matching
    # generator call when this preset is active. Empty dict / None
    # means no override (= today's behavior). compose_midi merges these
    # in after user-explicit kwargs take precedence.
    #
    # Examples:
    #   chord_variant = {"voice_leading": "common_tone",
    #                    "avoid_melody_track": "Melody"}
    #   bass_variant  = {"approach_tones": True}
    #   melody_variant = {"phrase_shape": "arc"}
    chord_variant: Optional[dict] = None
    bass_variant: Optional[dict] = None
    melody_variant: Optional[dict] = None

    # Optional named multi-section rhythm sets. Each variant is a list
    # of override-row dicts shaped:
    #   {start_bar, end_bar, chord_rhythm_h1, chord_rhythm_h2,
    #    bass_pattern, label}
    # The "Per-bar rhythm overrides" UI in MIDI Compose surfaces these
    # in an "Apply variant from style" dropdown — picking one
    # populates rhythm_overrides_state for the current compose, no
    # change to the preset's base ``chord_rhythm`` / ``bass_pattern``.
    rhythm_variants: dict = field(default_factory=dict)

    # Default bars to load into the UI when the user picks this preset.
    # Existing presets keep the historical 8-bar default; full-song
    # presets (the *_full keys below) carry 60-128 to drive verse /
    # chorus / bridge arrangements via rhythm_variants.
    default_bars: int = 8

    # When the user picks this preset, the family-checkbox accordions
    # auto-tick exactly this list of instrument ids (see
    # :mod:`src.composition.instruments`). Empty list = "don't touch
    # the user's current selection" — used by the 49 cultural presets
    # that share generic rhythm/bass/chord/melody coverage. Full-song
    # presets populate this with idiom-correct instrumentation so e.g.
    # picking ``jazz_aaba_full`` swaps the brass family into trumpet +
    # tenor sax automatically.
    default_instruments: list[str] = field(default_factory=list)

    # Pacing-strategy names ``compose_song`` picks from per-section
    # (see :mod:`src.composition.pacing`). Empty tuple ⇒ every section
    # uses ``uniform_1`` (1 bar per chord — legacy behavior). Each
    # full-song preset opts into the pacing pools that fit the genre's
    # harmonic-rhythm idioms.
    pacing_options: tuple[str, ...] = ()
    # Pool used specifically for sections whose role resolves to
    # ``"bridge"``. When non-empty, the bridge picks from this pool
    # instead — biased toward exotic strategies (secondary dominants,
    # chromatic passing, short-long sub-bar) because bridges in
    # songwriting are the contrast section. Empty ⇒ falls back to
    # ``pacing_options``.
    bridge_pacing_options: tuple[str, ...] = ()

    def __post_init__(self):
        # Synthesise a Default entry if no variants were declared so every
        # preset uniformly exposes a non-empty list.
        if not self.progression_variants:
            self.progression_variants = [("Default", list(self.progression))]
            return
        # If the caller declared only extras (typical pattern), prepend an
        # automatic "Default" pointing at the canonical ``progression``.
        # If they declared variants explicitly led by a non-Default plan,
        # we still prepend so the dropdown always offers "Default" first.
        head_name, head_plan = self.progression_variants[0]
        if head_plan != self.progression:
            self.progression_variants = (
                [("Default", list(self.progression))]
                + list(self.progression_variants)
            )


STYLES: dict[str, StylePreset] = {
    "funk": StylePreset(
        name="Funk", tempo=100, key="C", scale="dorian",
        progression=["i7", "IV7", "i7", "V7"],
        voicing="ninth", bass_pattern="funk_16ths", drum_pattern="funk",
        chord_rhythm="funk_comp", melody_style="pentatonic",
        chord_octave=4, bass_octave=2, swing=0.15,
        chord_program=4,  # Electric Piano 1
        melody_program=26,  # Electric Guitar (jazz)
        # Funk's 9th-chord voicings sing when they share common tones,
        # and the melody usually carves single-line stabs — keep the
        # chord pad out of its way. Melody picks up the 16th-note
        # syncopated rhythm motif and a call/response soul-rnb lick.
        chord_variant={
            "voice_leading": "common_tone",
            "avoid_melody_track": "Melody",
        },
        melody_variant={
            "phrase_shape": "call_response",
            "rhythm_motif": "funk_16th_synco",
            "velocity_curve": "call_response",
            "lick_pool": ["call_response_3_1"],
        },
        progression_variants=[
            ("Long form (2-bar)", [("i7", 2.0), ("IV7", 2.0), ("i7", 2.0), ("V7", 2.0)]),
            ("Sub-bar stabs", [("i7", 0.5), ("IV7", 0.5), ("i7", 0.5), ("V7", 0.5)]),
            ("II-V-i turnaround", ["ii7", "V7", "i7", "i7"]),
        ],
    ),
    "pop": StylePreset(
        name="Pop", tempo=118, key="C", scale="major",
        progression=["I", "V", "vi", "IV"],
        voicing="triad", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="pulse_quarter", melody_style="chord_tone",
        chord_octave=3, bass_octave=3,   # bass sits at A3 register (user preference)
        chord_program=0,  # Acoustic Grand
        # Pop triads benefit from smooth voice leading + a clear melody
        # line. The melody arc keeps a hook contour audible. Pop also
        # gets a cleaner pop_anacrusis rhythm and a phrase-arc velocity
        # curve so the hook breathes louder mid-phrase.
        chord_variant={"voice_leading": "common_tone"},
        melody_variant={
            "phrase_shape": "arc",
            "rhythm_motif": "pop_anacrusis",
            "velocity_curve": "phrase_arc",
            "lick_pool": ["pop_anacrusis_2_3_5", "arpeggio_climb_1_3_5_8"],
        },
        progression_variants=[
            ("Pachelbel", ["vi", "IV", "I", "V"]),
            ("Long form (2-bar)", [("I", 2.0), ("V", 2.0), ("vi", 2.0), ("IV", 2.0)]),
            ("Descending 8-bar", ["I", "V", "vi", "iii", "IV", "I", "IV", "V"]),
            ("Doo-wop", ["I", "vi", "IV", "V"]),
        ],
    ),
    "dance": StylePreset(
        name="Dance", tempo=126, key="A", scale="minor",
        progression=["i", "VI", "III", "VII"],
        voicing="triad", bass_pattern="offbeat", drum_pattern="dance_house",
        chord_rhythm="disco_stabs", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=81,  # Synth Lead (square)
        bass_program=38,   # Synth Bass 1
        progression_variants=[
            ("Long form (2-bar)", [("i", 2.0), ("VI", 2.0), ("III", 2.0), ("VII", 2.0)]),
            ("Minor rotation", ["VI", "III", "VII", "i"]),
            ("Trance build (4+4)", [("i", 4.0), ("VII", 2.0), ("VI", 2.0)]),
        ],
    ),
    "jazz_fusion": StylePreset(
        name="Jazz Fusion", tempo=110, key="D", scale="dorian",
        progression=["ii7", "V7", "Imaj7", "vi7"],
        voicing="drop2", bass_pattern="walking_swing", drum_pattern="jazz_swing",
        chord_rhythm="charleston", melody_style="motif",
        chord_octave=3, bass_octave=2, swing=0.33,
        chord_program=4,   # Electric Piano 1
        melody_program=66, # Alto Sax
        # Headline jazz idiom: walking bass with chromatic leading-tone
        # approach into each new chord, drop-2 voicings connected by
        # common tones, and the alto sax line arcs over the form with
        # charleston rhythm + a chromatic-enclosure turnaround.
        bass_variant={"approach_tones": True},
        chord_variant={
            "voice_leading": "common_tone",
            "avoid_melody_track": "Melody",
        },
        melody_variant={
            "phrase_shape": "arc",
            "rhythm_motif": "jazz_charleston",
            "velocity_curve": "phrase_arc",
            "lick_pool": [
                "chromatic_enclosure_3",
                "turn_around_1_6_4_5",
            ],
        },
        progression_variants=[
            ("Classic ii-V-I turnaround", ["ii7", "V7", "Imaj7", "Imaj7"]),
            ("Long form (2-bar)", [("ii7", 2.0), ("V7", 2.0), ("Imaj7", 2.0), ("vi7", 2.0)]),
            ("Modal vamp", [("Imaj7", 4.0), ("ii7", 4.0)]),
        ],
    ),
    "rock": StylePreset(
        name="Rock", tempo=120, key="E", scale="minor",
        progression=["i", "VII", "VI", "VII"],
        voicing="power", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="stabs_8th", melody_style="pentatonic",
        chord_octave=3, bass_octave=2,
        chord_program=29,  # Overdriven Guitar
        bass_program=34,   # Electric Bass (pick)
        progression_variants=[
            ("Long form (2-bar)", [("i", 2.0), ("VII", 2.0), ("VI", 2.0), ("VII", 2.0)]),
            ("8-bar repeat", ["i", "VII", "VI", "VII", "i", "VII", "VI", "VII"]),
            ("Anthem (4 chords)", ["i", "VI", "III", "VII"]),
        ],
    ),
    "metal": StylePreset(
        name="Metal", tempo=160, key="E", scale="minor",
        progression=["i", "bII", "i", "VII"],
        voicing="power", bass_pattern="palm_mute_8ths", drum_pattern="metal_gallop",
        chord_rhythm="stabs_8th", melody_style="pentatonic",
        chord_octave=3, bass_octave=1,
        chord_program=30,  # Distortion Guitar
        bass_program=34,   # Electric Bass (pick)
        progression_variants=[
            ("Sludge (2-bar)", [("i", 2.0), ("bII", 2.0), ("i", 2.0), ("VII", 2.0)]),
            ("8-bar gallop", ["i", "bII", "i", "VII", "i", "bII", "i", "VII"]),
            ("Phrygian descent", ["i", "bII", "bIII", "i"]),
        ],
    ),
    "disco": StylePreset(
        name="Disco", tempo=120, key="A", scale="minor",
        progression=["i7", "VI7", "III7", "VII7"],
        voicing="seventh", bass_pattern="disco_octave", drum_pattern="disco",
        chord_rhythm="disco_stabs", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=27,  # Electric Guitar (clean)
        bass_program=37,   # Slap Bass 2
        progression_variants=[
            ("Long form (2-bar)", [("i7", 2.0), ("VI7", 2.0), ("III7", 2.0), ("VII7", 2.0)]),
            ("Bee Gees", ["i7", "iv7", "VII7", "III7"]),
        ],
    ),
    "country": StylePreset(
        name="Country", tempo=88, key="G", scale="major",
        progression=["I", "IV", "I", "V"],
        voicing="sixth", bass_pattern="walking", drum_pattern="basic_rock",
        chord_rhythm="arpeggio_up", melody_style="pentatonic",
        chord_octave=3, bass_octave=2,
        chord_program=24,  # Acoustic Guitar (nylon)
        bass_program=32,   # Acoustic Bass
        melody_program=25, # Acoustic Guitar (steel) — lead
        # Country bass is built on the leading-tone "5-and-a-half" walk
        # into the next chord; the steel-guitar melody rises through
        # the form with long-short country rhythm + a walk-up lick.
        bass_variant={"approach_tones": True},
        melody_variant={
            "phrase_shape": "rise",
            "rhythm_motif": "country_long_short",
            "velocity_curve": "rise",
            "lick_pool": ["country_walk_up_5_to_1"],
        },
        progression_variants=[
            ("Long form (2-bar)", [("I", 2.0), ("IV", 2.0), ("I", 2.0), ("V", 2.0)]),
            ("Nashville I-IV-V-I", ["I", "IV", "V", "I"]),
            ("12-bar country", ["I", "I", "I", "I", "IV", "IV", "I", "I",
                                 "V", "IV", "I", "V"]),
        ],
    ),
    "surf_rock": StylePreset(
        name="Surf Rock", tempo=122, key="E", scale="major",
        progression=["I", "vi", "IV", "V"],
        voicing="seventh", bass_pattern="walking", drum_pattern="basic_rock",
        chord_rhythm="charleston", melody_style="pentatonic",
        chord_octave=3, bass_octave=2,
        chord_program=27,  # Electric Guitar (clean)
        bass_program=33,   # Electric Bass (finger)
        melody_program=29, # Overdriven Guitar — twangy lead
    ),
    "synthwave": StylePreset(
        name="Synthwave", tempo=132, key="A", scale="minor",
        progression=["i", "VI", "III", "VII"],
        voicing="add9", bass_pattern="offbeat", drum_pattern="dance_house",
        chord_rhythm="pulse_quarter", melody_style="chord_tone",
        chord_octave=3, bass_octave=2,
        chord_program=51,  # SynthStrings 2 — pad
        bass_program=38,   # Synth Bass 1
        melody_program=81, # Synth Lead 2 (sawtooth)
    ),
    "holiday_cinematic": StylePreset(
        name="Holiday Cinematic", tempo=124, key="F", scale="major",
        progression=["IV", "I", "V", "vi"],
        voicing="sus2", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="arpeggio_up", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=48,  # String Ensemble 1
        bass_program=43,   # Cello (or use 33 finger bass) — orchestra-low feel
        melody_program=14, # Tubular Bells — bell motif
    ),
    # ---------- Cinematic ----------
    "cinematic_epic": StylePreset(
        name="Cinematic Epic", tempo=90, key="D", scale="minor",
        progression=["i", "VI", "III", "VII"],   # Zimmer-style heroic-dark cycle
        voicing="add9", bass_pattern="palm_mute_8ths", drum_pattern="halftime",
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=48,  # String Ensemble 1
        bass_program=43,   # Cello (sub-bass ostinato)
        melody_program=60, # French Horn
    ),
    "cinematic_heroic": StylePreset(
        name="Cinematic Heroic", tempo=110, key="D", scale="major",
        progression=["I", "IV", "I", "V"],       # Williams fanfare bones
        voicing="triad", bass_pattern="walking", drum_pattern=None,
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=48,  # String Ensemble 1
        bass_program=43,   # Cello
        melody_program=60, # French Horn
    ),
    "cinematic_6_8": StylePreset(
        name="Cinematic 6/8", tempo=126, key="D", scale="minor",
        progression=["i", "VI", "III", "VII"],
        voicing="add9", bass_pattern="compound_6_8_bass",
        drum_pattern="compound_6_8",
        chord_rhythm="compound_6_8_strum", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=48,  # String Ensemble 1
        bass_program=43,   # Cello
        melody_program=73, # Flute
        time_signature=(6, 8),
    ),
    # ---------- Classical ----------
    "classical_baroque": StylePreset(
        name="Classical Baroque", tempo=110, key="G", scale="major",
        progression=["I", "V", "vi", "iii", "IV", "I", "ii", "V"],  # Pachelbel-ish
        voicing="seventh", bass_pattern="walking", drum_pattern=None,
        chord_rhythm="arpeggio_16th", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=6,   # Harpsichord
        bass_program=42,   # Cello (continuo)
        melody_program=71, # Clarinet (or 73 Flute)
    ),
    "classical_waltz": StylePreset(
        name="Classical Waltz", tempo=132, key="G", scale="major",
        progression=["I", "V", "I", "I", "IV", "I", "V", "I"],  # 8-bar waltz cycle
        voicing="triad", bass_pattern="waltz_bass", drum_pattern=None,
        chord_rhythm="waltz_strum", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=0,   # Acoustic Grand Piano
        bass_program=43,   # Cello
        melody_program=73, # Flute
        time_signature=(3, 4),
    ),
    "classical_romantic": StylePreset(
        name="Classical Romantic", tempo=76, key="F", scale="harmonic_minor",
        progression=["i", "iv", "V", "i", "VI", "iv", "V", "i"],
        voicing="ninth", bass_pattern="root_fifth", drum_pattern=None,
        chord_rhythm="arpeggio_16th", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=0,   # Acoustic Grand Piano
        bass_program=43,   # Cello
        melody_program=40, # Violin
    ),
    # ---------- Video Game ----------
    "game_chiptune": StylePreset(
        name="Game Chiptune", tempo=150, key="C", scale="major",
        progression=["I", "vi", "IV", "V"],
        voicing="triad", bass_pattern="disco_octave", drum_pattern="basic_rock",
        chord_rhythm="stabs_8th", melody_style="chord_tone",
        chord_octave=4, bass_octave=3,
        chord_program=80,  # Lead 1 (square)
        bass_program=39,   # Synth Bass 2
        melody_program=80, # Lead 1 (square)
    ),
    "game_jrpg": StylePreset(
        name="Game JRPG", tempo=100, key="A", scale="minor",
        progression=["i", "VI", "III", "VII"],   # Uematsu-style heroic-dark
        voicing="ninth", bass_pattern="root_fifth", drum_pattern="pop_disco",
        chord_rhythm="arpeggio_up", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=49,  # String Ensemble 2 (slow strings)
        bass_program=38,   # Synth Bass 1
        melody_program=82, # Lead 3 (calliope) — bright JRPG lead
    ),
    "game_adventure_6_8": StylePreset(
        name="Game Adventure 6/8", tempo=144, key="G", scale="major",
        progression=["I", "V", "vi", "IV"],      # Zelda-overworld bones
        voicing="triad", bass_pattern="compound_6_8_bass",
        drum_pattern="compound_6_8",
        chord_rhythm="compound_6_8_strum", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=46,  # Orchestral Harp
        bass_program=43,   # Cello
        melody_program=73, # Flute
        time_signature=(6, 8),
    ),
    # ---------- Era-specific pop / urban ----------
    "new_wave": StylePreset(
        name="New Wave", tempo=130, key="A", scale="minor",
        progression=["i", "VII", "VI", "VII"],   # Talking Heads / Cars feel
        voicing="triad", bass_pattern="offbeat", drum_pattern="four_on_floor",
        chord_rhythm="stabs_8th", melody_style="pentatonic",
        chord_octave=4, bass_octave=2,
        chord_program=81,  # Lead 2 (sawtooth) — synth stab
        bass_program=39,   # Synth Bass 2 — TB-303 / Moog
        melody_program=81, # Lead 2 (sawtooth) — synth lead
    ),
    "nu_metal": StylePreset(
        name="Nu Metal", tempo=96, key="E", scale="minor",
        progression=["i", "bVI", "VII", "i"],    # Korn / Limp Bizkit angular
        voicing="power", bass_pattern="palm_mute_8ths", drum_pattern="halftime",
        chord_rhythm="stabs_8th", melody_style="pentatonic",
        chord_octave=3, bass_octave=1,
        chord_program=30,  # Distortion Guitar
        bass_program=34,   # Electric Bass (pick)
        melody_program=29, # Overdriven Guitar
    ),
    "hip_hop_90s": StylePreset(
        name="90s Hip Hop", tempo=90, key="F", scale="minor",
        progression=["i7", "iv7", "VI7", "v7"],  # Tribe / Wu-Tang jazz-sample
        voicing="ninth", bass_pattern="root_fifth", drum_pattern="funk",
        chord_rhythm="charleston", melody_style="blues",
        chord_octave=3, bass_octave=2, swing=0.1,
        chord_program=4,   # Electric Piano 1 — Rhodes
        bass_program=33,   # Electric Bass (finger)
        melody_program=17, # Drawbar Organ — sampled organ flavor
    ),
    "rap_2000s": StylePreset(
        name="2000s Rap", tempo=92, key="C", scale="minor",
        progression=["i", "VI", "iv", "v"],      # dark Kanye / 808s era
        voicing="open5", bass_pattern="palm_mute_8ths", drum_pattern="halftime",
        chord_rhythm="pad", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=50,  # Synth Strings 1
        bass_program=38,   # Synth Bass 1 — 808 thump
        melody_program=81, # Lead 2 (sawtooth)
    ),
    "rnb_90s": StylePreset(
        name="90s R&B", tempo=78, key="D", scale="major",
        progression=["I", "vi", "ii", "V"],      # Boyz II Men slow-jam
        voicing="ninth", bass_pattern="walking", drum_pattern="pop_16ths",
        chord_rhythm="pad", melody_style="chord_tone",
        chord_octave=3, bass_octave=2, swing=0.1,
        chord_program=4,   # Electric Piano 1 — Rhodes
        bass_program=33,   # Electric Bass (finger)
        melody_program=53, # Choir Aahs — lead vocal stand-in
    ),
    "boy_band": StylePreset(
        name="Boy Band", tempo=104, key="C", scale="major",
        progression=["vi", "IV", "I", "V"],      # NSYNC / BSB descending-line
        voicing="triad", bass_pattern="root_fifth", drum_pattern="pop_16ths",
        chord_rhythm="pulse_quarter", melody_style="chord_tone",
        chord_octave=3, bass_octave=2,
        chord_program=0,   # Acoustic Grand
        bass_program=33,   # Electric Bass (finger)
        melody_program=53, # Choir Aahs — boy-band vocal stack
        progression_variants=[
            ("Long form (2-bar)", [("vi", 2.0), ("IV", 2.0), ("I", 2.0), ("V", 2.0)]),
            ("Ballad I-V-vi-IV", ["I", "V", "vi", "IV"]),
            ("8-bar loop", ["vi", "IV", "I", "V", "vi", "IV", "I", "V"]),
        ],
    ),
    "saloon_piano": StylePreset(
        name="Saloon Piano", tempo=116, key="C", scale="major",
        progression=["I", "I7", "IV", "V7"],     # 19th-century stride/ragtime
        voicing="seventh", bass_pattern="walking", drum_pattern=None,
        chord_rhythm="stabs_8th", melody_style="blues",
        chord_octave=4, bass_octave=2, swing=0.2,
        chord_program=3,   # Honky-tonk Piano (right-hand chord stabs)
        bass_program=3,    # Honky-tonk Piano (left-hand stride bass)
        melody_program=3,  # Honky-tonk Piano (right-hand melody)
    ),

    # ----- Latin / Caribbean / Spanish -----
    "latin_pop": StylePreset(
        name="Latin Pop", tempo=96, key="C", scale="major",
        progression=["I", "V", "vi", "IV"],
        voicing="triad", bass_pattern="tumbao", drum_pattern="salsa",
        chord_rhythm="montuno_2_3", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=24,  # Acoustic Guitar (nylon)
        bass_program=33,
        melody_program=78, # Whistle / vocal substitute
        progression_variants=[
            ("Long form (2-bar)", [("I", 2.0), ("V", 2.0), ("vi", 2.0), ("IV", 2.0)]),
            ("Tropical vi-IV", ["vi", "IV", "I", "V"]),
            ("Bachata cycle", ["I", "vi", "ii", "V"]),
        ],
    ),
    "salsa": StylePreset(
        name="Salsa", tempo=95, key="A", scale="minor",
        progression=["i", "iv", "V7", "i"],
        voicing="seventh", bass_pattern="salsa_montuno_bass", drum_pattern="salsa",
        chord_rhythm="montuno_2_3", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=0,   # Acoustic Grand Piano (montuno)
        bass_program=33,
        melody_program=56, # Trumpet
        progression_variants=[
            ("Long form (2-bar)", [("i", 2.0), ("iv", 2.0), ("V7", 2.0), ("i", 2.0)]),
            ("Montuno 2-3", [("i", 0.5), ("V7", 0.5), ("i", 0.5), ("V7", 0.5)]),
            ("Anticipated cycle", ["i", "iv", "i", "V7"]),
        ],
    ),
    "bossa_nova": StylePreset(
        name="Bossa Nova", tempo=100, key="D", scale="minor",
        progression=["ii7", "V7", "Imaj7", "Imaj7"],
        voicing="ninth", bass_pattern="samba_partido_alto", drum_pattern="bossa_nova",
        chord_rhythm="bossa_comp", melody_style="chord_tone",
        chord_octave=4, bass_octave=2, swing=0.1,
        chord_program=24,  # Nylon-string guitar
        bass_program=32,   # Acoustic Bass
        melody_program=66, # Alto Sax
        # Bossa is defined by smooth, conversational chord voicings; the
        # sax melody breathes in call-and-response phrases over the
        # form, riding the 3-3-2 partido alto rhythm.
        chord_variant={"voice_leading": "common_tone"},
        melody_variant={
            "phrase_shape": "call_response",
            "rhythm_motif": "bossa_partido",
            "velocity_curve": "call_response",
            "lick_pool": ["arpeggio_climb_1_3_5_8"],
        },
        progression_variants=[
            ("Elongated", [("ii7", 2.0), ("V7", 2.0), ("Imaj7", 4.0)]),
            ("Short-long", [("ii7", 0.5), ("V7", 0.5), ("Imaj7", 1.0), ("Imaj7", 1.0)]),
            ("Jobim cycle", ["Imaj7", "vi7", "ii7", "V7"]),
        ],
    ),
    "reggaeton": StylePreset(
        name="Reggaeton", tempo=95, key="A", scale="minor",
        progression=["i", "VI", "III", "VII"],
        voicing="triad", bass_pattern="reggaeton_dembow_bass", drum_pattern="reggaeton",
        chord_rhythm="tresillo", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=81,  # Synth Lead (square)
        bass_program=38,   # Synth Bass 1
        melody_program=80, # Synth Lead (square wave)
    ),
    "flamenco": StylePreset(
        name="Flamenco", tempo=130, key="E", scale="phrygian_dominant",
        progression=["i", "bII", "bIII", "IV"],   # Andalusian cadence
        voicing="triad", bass_pattern="tumbao", drum_pattern="salsa",
        chord_rhythm="flamenco_rasgueado", melody_style="motif",
        chord_octave=4, bass_octave=2,
        chord_program=24,  # Nylon guitar
        bass_program=32,
        melody_program=25, # Steel-string lead
    ),
    "afrobeat": StylePreset(
        name="Afrobeat", tempo=110, key="E", scale="dorian",
        progression=["i7", "IV7", "i7", "IV7"],
        voicing="ninth", bass_pattern="funk_16ths", drum_pattern="afrobeat",
        chord_rhythm="funk_comp", melody_style="pentatonic",
        chord_octave=4, bass_octave=2, swing=0.1,
        chord_program=4,   # Electric Piano 1
        bass_program=33,
        melody_program=66, # Alto Sax (Fela horns)
    ),

    # ----- Middle Eastern -----
    "oud_ballad": StylePreset(
        name="Oud Ballad", tempo=70, key="A", scale="maqam_hijaz",
        progression=["i", "iv", "V", "i"],
        voicing="quartal", bass_pattern="arabic_iqa_baladi", drum_pattern=None,
        chord_rhythm="arab_baladi", melody_style="maqam_hijaz",
        chord_octave=3, bass_octave=2,
        chord_program=48,  # String Ensemble 1
        bass_program=32,
        melody_program=104, # Sitar (closest GM oud substitute)
    ),

    # ----- Indian -----
    "bollywood": StylePreset(
        name="Bollywood", tempo=105, key="D", scale="raga_yaman",
        progression=["I", "IV", "V", "IV"],
        voicing="sus4_add9", bass_pattern="indian_dhol_root", drum_pattern="basic_rock",
        chord_rhythm="indian_teental_16", melody_style="raga_yaman",
        chord_octave=4, bass_octave=2,
        chord_program=48,   # String Ensemble (santoor stand-in for chord pad)
        bass_program=32,
        melody_program=104, # Sitar
    ),
    "bhangra": StylePreset(
        name="Bhangra", tempo=144, key="F#", scale="minor",
        progression=["i", "iv", "VI", "V"],
        voicing="power", bass_pattern="indian_dhol_root", drum_pattern="basic_rock",
        chord_rhythm="indian_keherwa_8", melody_style="motif",
        chord_octave=3, bass_octave=2,
        chord_program=29,   # Overdriven Guitar (modern bhangra blend)
        bass_program=33,
        melody_program=109, # Bagpipe (closest to shehnai)
    ),

    # ----- East / Southeast Asian -----
    "j_pop": StylePreset(
        name="J-Pop", tempo=130, key="C", scale="major",
        progression=["vi", "IV", "I", "V"],   # royal-road inverted
        voicing="add9", bass_pattern="root_fifth", drum_pattern="pop_disco",
        chord_rhythm="arpeggio_16th", melody_style="chord_tone",
        chord_octave=4, bass_octave=2,
        chord_program=4,    # Electric Piano 1
        bass_program=33,
        melody_program=81,  # Synth Lead (saw)
    ),
    "gamelan_ambient": StylePreset(
        name="Gamelan Ambient", tempo=80, key="F#", scale="gamelan_slendro",
        progression=["I", "IV", "V", "I"],
        voicing="quintal", bass_pattern="gamelan_balungan", drum_pattern=None,
        chord_rhythm="gamelan_kotekan", melody_style="gamelan_slendro",
        chord_octave=4, bass_octave=2,
        chord_program=12,   # Marimba (saron substitute)
        bass_program=12,
        melody_program=107, # Koto
    ),

    # ----- Dynamic variants -----------------------------------------------
    # These sit ALONGSIDE the simple presets above. The base preset
    # (chord_rhythm + bass_pattern) is just one cell of the per-bar
    # override system; the real character comes from rhythm_variants,
    # which the Compose tab's "Apply variant from style" dropdown reads.
    "pop_dynamic": StylePreset(
        name="Pop (Dynamic)", tempo=104, key="C", scale="major",
        progression=["I", "V", "vi", "IV"],
        voicing="triad", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=2,
        rhythm_variants={
            "Verse / Chorus": [
                {"start_bar": 0, "end_bar": 3, "label": "Verse",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 4, "end_bar": 7, "label": "Chorus",
                 "chord_rhythm_h1": "disco_stabs", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 7, "end_bar": 7, "label": "Fill",
                 "chord_rhythm_h1": "", "chord_rhythm_h2": "stabs_8th",
                 "bass_pattern": ""},
            ],
        },
    ),
    "funk_dynamic": StylePreset(
        name="Funk (Dynamic)", tempo=100, key="C", scale="dorian",
        progression=["i7", "IV7", "i7", "V7"],
        voicing="ninth", bass_pattern="funk_16ths", drum_pattern="funk",
        chord_rhythm="funk_comp", melody_style="pentatonic",
        chord_octave=4, bass_octave=2, swing=0.15,
        rhythm_variants={
            "Groove / Bridge / Drop": [
                {"start_bar": 0, "end_bar": 3, "label": "Groove",
                 "chord_rhythm_h1": "funk_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "funk_16ths"},
                {"start_bar": 4, "end_bar": 5, "label": "Bridge",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "root_only"},
                {"start_bar": 6, "end_bar": 7, "label": "Drop",
                 "chord_rhythm_h1": "funk_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "funk_16ths"},
            ],
        },
    ),
    "jazz_trade_fours": StylePreset(
        name="Jazz (Trade fours)", tempo=140, key="F", scale="major",
        progression=["ii7", "V7", "I", "I"],
        voicing="seventh", bass_pattern="walking_swing", drum_pattern="basic_rock",
        chord_rhythm="charleston", melody_style="motif",
        chord_octave=4, bass_octave=2, swing=0.32,
        rhythm_variants={
            "Trade fours": [
                {"start_bar": 0, "end_bar": 3, "label": "A",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 4, "end_bar": 7, "label": "B",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
            ],
        },
    ),
    "rock_buildup": StylePreset(
        name="Rock (Buildup)", tempo=120, key="E", scale="minor",
        progression=["i", "VI", "III", "VII"],
        voicing="triad", bass_pattern="root", drum_pattern="basic_rock",
        chord_rhythm="pad", melody_style="motif",
        chord_octave=4, bass_octave=2,
        rhythm_variants={
            "Buildup → Lift": [
                {"start_bar": 0, "end_bar": 3, "label": "Pad",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4, "end_bar": 6, "label": "Drive",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 7, "end_bar": 7, "label": "Lift",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "stabs_8th",
                 "bass_pattern": "walking"},
            ],
        },
    ),

    # ----- Full-song presets ----------------------------------------------
    # One-click classic song structures. Each carries `default_bars` so
    # the bars slider snaps to the canonical length when the preset is
    # picked, and a `rhythm_variants["Full song"]` entry that auto-
    # populates the per-bar override accordion with intro / verse /
    # chorus / bridge / outro rows. Section breakdowns sum exactly to
    # default_bars (test enforced).

    "pop_full_song": StylePreset(
        name="Pop (Full song)", tempo=104, key="C", scale="major",
        # 4-bar pop cycle ×20 = 80 bars.
        progression=[("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)] * 20,
        voicing="triad", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=3, default_bars=80,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "Verse 1",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 20, "end_bar": 23, "label": "Pre-chorus",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 24, "end_bar": 39, "label": "Chorus 1",
                 "chord_rhythm_h1": "disco_stabs", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 40, "end_bar": 51, "label": "Verse 2",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 52, "end_bar": 59, "label": "Bridge",
                 "chord_rhythm_h1": "off_skank", "chord_rhythm_h2": "",
                 "bass_pattern": "offbeat"},
                {"start_bar": 60, "end_bar": 75, "label": "Chorus 2",
                 "chord_rhythm_h1": "disco_stabs", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 76, "end_bar": 79, "label": "Outro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'piano', 'electric_guitar_clean'],
        pacing_options=('uniform_1', 'uniform_1', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'stretch_tonic_2', 'with_chromatic_passing'),
    ),

    "rock_anthem_full": StylePreset(
        name="Rock anthem (Full song)", tempo=128, key="E", scale="minor",
        # i-VI-III-VII minor anthem ×24 = 96 bars.
        progression=[("i", 1.0), ("VI", 1.0), ("III", 1.0), ("VII", 1.0)] * 24,
        voicing="triad", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=2, default_bars=96,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 7,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 8,  "end_bar": 23, "label": "Verse 1",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 24, "end_bar": 39, "label": "Chorus 1",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 40, "end_bar": 55, "label": "Verse 2",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 56, "end_bar": 71, "label": "Chorus 2",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 72, "end_bar": 87, "label": "Solo",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 88, "end_bar": 95, "label": "Outro",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'electric_guitar_dirty', 'electric_guitar_clean', 'organ_hammond'],
        pacing_options=('uniform_1', 'uniform_1', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'stretch_tonic_2', 'with_chromatic_passing'),
    ),

    "funk_full_song": StylePreset(
        name="Funk (Full song)", tempo=100, key="C", scale="dorian",
        # 2-bar i7-IV7 vamp ×16 = 64 bars.
        progression=[("i7", 2.0), ("IV7", 2.0)] * 16,
        voicing="ninth", bass_pattern="funk_16ths", drum_pattern="funk",
        chord_rhythm="funk_comp", melody_style="pentatonic",
        chord_octave=4, bass_octave=2, swing=0.15, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "funk_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "Vamp A",
                 "chord_rhythm_h1": "funk_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "funk_16ths"},
                {"start_bar": 20, "end_bar": 23, "label": "Break",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 24, "end_bar": 39, "label": "Vamp B",
                 "chord_rhythm_h1": "funk_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "funk_16ths"},
                {"start_bar": 40, "end_bar": 47, "label": "Bridge",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "offbeat"},
                {"start_bar": 48, "end_bar": 63, "label": "Outro vamp",
                 "chord_rhythm_h1": "funk_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "funk_16ths"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'electric_piano', 'electric_guitar_clean', 'brass_section'],
        pacing_options=('uniform_1', 'short_long_subbar', 'uniform_2'),
        bridge_pacing_options=('short_long_subbar', 'uniform_2'),
    ),

    "jazz_aaba_full": StylePreset(
        name="Jazz AABA (Full song)", tempo=140, key="F", scale="major",
        # ii-V-I-I ×16 = 64 bars (four 16-bar A/B sections).
        progression=[("ii7", 1.0), ("V7", 1.0), ("I", 1.0), ("I", 1.0)] * 16,
        voicing="seventh", bass_pattern="walking_swing", drum_pattern="basic_rock",
        chord_rhythm="charleston", melody_style="motif",
        chord_octave=4, bass_octave=2, swing=0.32, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 15, "label": "A1",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 16, "end_bar": 31, "label": "A2",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 32, "end_bar": 47, "label": "B (bridge)",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 48, "end_bar": 63, "label": "A3",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
            ],
        },
        default_instruments=['drum_kit', 'upright_bass', 'piano', 'sax_tenor', 'trumpet'],
        pacing_options=('uniform_1', 'cadence_accel', 'with_secondary_doms'),
        bridge_pacing_options=('with_secondary_doms', 'short_long_subbar', 'cadence_accel'),
    ),

    "blues_12bar_full": StylePreset(
        name="12-Bar Blues (Full song)", tempo=92, key="A", scale="major",
        # Classic 12-bar dominant cycle ×5 = 60 bars (5 choruses).
        progression=(
            [("I7", 1.0), ("IV7", 1.0), ("I7", 1.0), ("I7", 1.0),
             ("IV7", 1.0), ("IV7", 1.0), ("I7", 1.0), ("I7", 1.0),
             ("V7", 1.0), ("IV7", 1.0), ("I7", 1.0), ("V7", 1.0)] * 5
        ),
        voicing="seventh", bass_pattern="walking", drum_pattern="basic_rock",
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=2, swing=0.18, default_bars=60,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 11, "label": "Chorus 1 (head)",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 12, "end_bar": 23, "label": "Chorus 2",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 24, "end_bar": 35, "label": "Chorus 3 (var)",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 36, "end_bar": 47, "label": "Chorus 4",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 48, "end_bar": 59, "label": "Chorus 5 (out)",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'electric_guitar_clean', 'organ_hammond'],
        pacing_options=('uniform_1',),
        bridge_pacing_options=('uniform_1',),
    ),

    "ballad_full": StylePreset(
        name="Ballad (Full song)", tempo=72, key="C", scale="major",
        # I-vi-IV-V "50s progression" ×20 = 80 bars.
        progression=[("I", 1.0), ("vi", 1.0), ("IV", 1.0), ("V", 1.0)] * 20,
        voicing="seventh", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="pad", melody_style="motif",
        chord_octave=4, bass_octave=3, default_bars=80,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "Verse 1",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 20, "end_bar": 35, "label": "Chorus 1",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 36, "end_bar": 51, "label": "Verse 2",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 52, "end_bar": 59, "label": "Bridge",
                 "chord_rhythm_h1": "elton_octaves", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 60, "end_bar": 75, "label": "Chorus 2",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 76, "end_bar": 79, "label": "Outro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'piano', 'string_section'],
        pacing_options=('ballad_4_2', 'stretch_tonic_2', 'uniform_2'),
        bridge_pacing_options=('with_secondary_doms', 'stretch_tonic_2'),
    ),

    "hip_hop_full": StylePreset(
        name="Hip-hop (Full song)", tempo=90, key="A", scale="minor",
        # 4-bar minor loop ×16 = 64 bars.
        progression=[("i", 1.0), ("VI", 1.0), ("VII", 1.0), ("i", 1.0)] * 16,
        voicing="seventh", bass_pattern="root", drum_pattern="halftime",
        chord_rhythm="pad", melody_style="motif",
        chord_octave=4, bass_octave=2, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 7,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 8,  "end_bar": 23, "label": "Verse 1",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 24, "end_bar": 31, "label": "Hook 1",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 32, "end_bar": 47, "label": "Verse 2",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 48, "end_bar": 55, "label": "Bridge",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "stabs_8th",
                 "bass_pattern": "offbeat"},
                {"start_bar": 56, "end_bar": 63, "label": "Hook out",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
            ],
        },
        default_instruments=['drum_kit', 'synth_bass', 'electric_piano'],
        pacing_options=('uniform_1', 'uniform_2'),
        bridge_pacing_options=('uniform_2', 'with_chromatic_passing'),
    ),

    "country_full": StylePreset(
        name="Country (Full song)", tempo=112, key="G", scale="major",
        # I-V-vi-IV with V on the chorus turnaround × 20 = 80 bars.
        progression=[("I", 1.0), ("V", 1.0), ("vi", 1.0), ("IV", 1.0)] * 20,
        voicing="triad", bass_pattern="root_fifth", drum_pattern="basic_rock",
        chord_rhythm="pulse_quarter", melody_style="pentatonic",
        chord_octave=4, bass_octave=3, default_bars=80,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "Verse 1",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 20, "end_bar": 35, "label": "Chorus 1",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 36, "end_bar": 51, "label": "Verse 2",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 52, "end_bar": 59, "label": "Bridge",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 60, "end_bar": 75, "label": "Chorus 2",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 76, "end_bar": 79, "label": "Outro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'acoustic_guitar', 'electric_guitar_clean'],
        pacing_options=('uniform_1', 'uniform_1', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'stretch_tonic_2', 'with_chromatic_passing'),
    ),

    "reggae_full": StylePreset(
        name="Reggae (Full song)", tempo=78, key="A", scale="minor",
        # i-VII-VI-V cycle × 16 = 64 bars.
        progression=[("i", 1.0), ("VII", 1.0), ("VI", 1.0), ("V", 1.0)] * 16,
        voicing="seventh", bass_pattern="root", drum_pattern="halftime",
        chord_rhythm="off_skank", melody_style="pentatonic",
        chord_octave=4, bass_octave=2, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "Verse 1",
                 "chord_rhythm_h1": "off_skank", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 20, "end_bar": 27, "label": "Chorus 1",
                 "chord_rhythm_h1": "off_skank", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 28, "end_bar": 43, "label": "Verse 2",
                 "chord_rhythm_h1": "off_skank", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 44, "end_bar": 51, "label": "Bridge",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "off_skank",
                 "bass_pattern": "root"},
                {"start_bar": 52, "end_bar": 59, "label": "Chorus 2",
                 "chord_rhythm_h1": "off_skank", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 60, "end_bar": 63, "label": "Outro",
                 "chord_rhythm_h1": "off_skank", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'electric_guitar_clean', 'organ_hammond'],
        pacing_options=('uniform_1', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'short_long_subbar'),
    ),

    "disco_full": StylePreset(
        name="Disco (Full song)", tempo=118, key="A", scale="minor",
        # i-bVII-bVI-bVII × 20 = 80 bars.
        progression=[("i", 1.0), ("VII", 1.0), ("VI", 1.0), ("VII", 1.0)] * 20,
        voicing="seventh", bass_pattern="disco_octave", drum_pattern="disco",
        chord_rhythm="disco_stabs", melody_style="motif",
        chord_octave=4, bass_octave=2, default_bars=80,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 7,  "label": "Intro",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 8,  "end_bar": 23, "label": "Verse 1",
                 "chord_rhythm_h1": "disco_stabs", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 24, "end_bar": 39, "label": "Chorus 1",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 40, "end_bar": 55, "label": "Verse 2",
                 "chord_rhythm_h1": "disco_stabs", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 56, "end_bar": 63, "label": "Bridge",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "offbeat"},
                {"start_bar": 64, "end_bar": 79, "label": "Chorus 2 (out)",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'electric_piano', 'brass_section'],
        pacing_options=('uniform_1', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'short_long_subbar'),
    ),

    "soul_motown_full": StylePreset(
        name="Soul / Motown (Full song)", tempo=98, key="C", scale="major",
        # Motown-style I-vi-IV-V × 20 = 80 bars.
        progression=[("I", 1.0), ("vi", 1.0), ("IV", 1.0), ("V", 1.0)] * 20,
        voicing="seventh", bass_pattern="walking", drum_pattern="halftime",
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=3, default_bars=80,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "Verse 1",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 20, "end_bar": 35, "label": "Chorus 1",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 36, "end_bar": 51, "label": "Verse 2",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 52, "end_bar": 59, "label": "Bridge",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "walking"},
                {"start_bar": 60, "end_bar": 75, "label": "Chorus 2",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 76, "end_bar": 79, "label": "Outro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'electric_piano', 'brass_section'],
        pacing_options=('uniform_1', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'short_long_subbar'),
    ),

    "jazz_bossa_full": StylePreset(
        name="Jazz Bossa (Full song)", tempo=128, key="F", scale="major",
        # ii-V-I bossa cycle × 16 = 64 bars.
        progression=[("ii7", 1.0), ("V7", 1.0), ("I", 1.0), ("I", 1.0)] * 16,
        voicing="ninth", bass_pattern="samba_partido_alto", drum_pattern="bossa_nova",
        chord_rhythm="bossa_comp", melody_style="motif",
        chord_octave=4, bass_octave=2, swing=0.08, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 15, "label": "A1",
                 "chord_rhythm_h1": "bossa_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "samba_partido_alto"},
                {"start_bar": 16, "end_bar": 31, "label": "A2",
                 "chord_rhythm_h1": "bossa_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "samba_partido_alto"},
                {"start_bar": 32, "end_bar": 47, "label": "B (bridge)",
                 "chord_rhythm_h1": "bossa_comp", "chord_rhythm_h2": "tresillo",
                 "bass_pattern": "samba_partido_alto"},
                {"start_bar": 48, "end_bar": 63, "label": "A3",
                 "chord_rhythm_h1": "bossa_comp", "chord_rhythm_h2": "",
                 "bass_pattern": "samba_partido_alto"},
            ],
        },
        default_instruments=['drum_kit', 'upright_bass', 'piano', 'sax_tenor', 'flute'],
        pacing_options=('uniform_1', 'short_long_subbar'),
        bridge_pacing_options=('short_long_subbar', 'with_secondary_doms'),
    ),

    "jazz_hard_bop_full": StylePreset(
        name="Jazz Hard Bop (Full song)", tempo=176, key="Bb", scale="major",
        # ii-V-I cycle × 16 = 64 bars at fast bop tempo.
        progression=[("ii7", 1.0), ("V7", 1.0), ("I", 1.0), ("I", 1.0)] * 16,
        voicing="seventh", bass_pattern="walking_swing", drum_pattern="jazz_swing",
        chord_rhythm="charleston", melody_style="motif",
        chord_octave=4, bass_octave=2, swing=0.33, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 15, "label": "Head A",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 16, "end_bar": 31, "label": "Solo 1",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 32, "end_bar": 47, "label": "Solo 2",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 48, "end_bar": 63, "label": "Head out",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
            ],
        },
        default_instruments=['drum_kit', 'upright_bass', 'piano', 'sax_tenor', 'trumpet'],
        pacing_options=('uniform_1', 'cadence_accel', 'with_secondary_doms'),
        bridge_pacing_options=('with_secondary_doms', 'short_long_subbar', 'cadence_accel'),
    ),

    "jazz_modal_full": StylePreset(
        name="Jazz Modal (Full song)", tempo=132, key="D", scale="dorian",
        # Two-chord modal vamp i7-IV7 × 16 = 64 bars.
        progression=[("i7", 2.0), ("IV7", 2.0)] * 16,
        voicing="ninth", bass_pattern="walking_swing", drum_pattern="jazz_swing",
        chord_rhythm="pad", melody_style="motif",
        chord_octave=4, bass_octave=2, swing=0.22, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 15, "label": "A1",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 16, "end_bar": 31, "label": "A2 (solo)",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 32, "end_bar": 47, "label": "B (open)",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 48, "end_bar": 63, "label": "A3 (out)",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'upright_bass', 'piano', 'sax_tenor'],
        pacing_options=('uniform_2', 'uniform_2', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'uniform_2'),
    ),

    "jazz_ballad_full": StylePreset(
        name="Jazz Ballad (Full song)", tempo=70, key="Eb", scale="major",
        # ii-V-I + vi turnaround × 12 = 48 bars.
        progression=[("ii7", 1.0), ("V7", 1.0), ("I", 1.0), ("vi", 1.0)] * 12,
        voicing="ninth", bass_pattern="walking_swing", drum_pattern="halftime",
        chord_rhythm="pad", melody_style="motif",
        chord_octave=4, bass_octave=3, swing=0.2, default_bars=48,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "arpeggio_up", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "A1",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 20, "end_bar": 31, "label": "A2",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 32, "end_bar": 43, "label": "Bridge",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 44, "end_bar": 47, "label": "Outro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'upright_bass', 'piano', 'sax_tenor'],
        pacing_options=('uniform_2', 'ballad_4_2', 'stretch_tonic_2'),
        bridge_pacing_options=('with_secondary_doms', 'uniform_2'),
    ),

    "jazz_piano_full": StylePreset(
        name="Jazz Piano (Full song)", tempo=128, key="F", scale="major",
        # ii-V-I cycle × 16 = 64 bars.
        progression=[("ii7", 1.0), ("V7", 1.0), ("I", 1.0), ("I", 1.0)] * 16,
        voicing="ninth", bass_pattern="walking_swing", drum_pattern="jazz_swing",
        chord_rhythm="dotted_8ths", melody_style="motif",
        chord_octave=4, bass_octave=2, swing=0.28, default_bars=64,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 3,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 4,  "end_bar": 19, "label": "A1 (comp)",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 20, "end_bar": 35, "label": "A2 (solo)",
                 "chord_rhythm_h1": "charleston", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 36, "end_bar": 51, "label": "Bridge",
                 "chord_rhythm_h1": "alberti", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
                {"start_bar": 52, "end_bar": 63, "label": "Head out",
                 "chord_rhythm_h1": "dotted_8ths", "chord_rhythm_h2": "",
                 "bass_pattern": "walking_swing"},
            ],
        },
        default_instruments=['drum_kit', 'upright_bass', 'piano'],
        pacing_options=('uniform_1', 'cadence_accel', 'with_secondary_doms'),
        bridge_pacing_options=('with_secondary_doms', 'short_long_subbar'),
    ),

    "metal_full": StylePreset(
        name="Metal (Full song)", tempo=150, key="E", scale="minor",
        # Power-chord drone with bVII / V drops ×20 = 80 bars.
        progression=[("i", 1.0), ("VII", 1.0), ("i", 1.0), ("V", 1.0)] * 20,
        voicing="power", bass_pattern="palm_mute_8ths",
        drum_pattern="metal_gallop",
        chord_rhythm="van_halen_chug", melody_style="motif",
        chord_octave=3, bass_octave=2, default_bars=80,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,  "end_bar": 7,  "label": "Intro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 8,  "end_bar": 23, "label": "Verse 1",
                 "chord_rhythm_h1": "van_halen_chug", "chord_rhythm_h2": "",
                 "bass_pattern": "palm_mute_8ths"},
                {"start_bar": 24, "end_bar": 39, "label": "Chorus 1",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 40, "end_bar": 55, "label": "Verse 2",
                 "chord_rhythm_h1": "van_halen_chug", "chord_rhythm_h2": "",
                 "bass_pattern": "palm_mute_8ths"},
                {"start_bar": 56, "end_bar": 63, "label": "Bridge / Solo",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
                {"start_bar": 64, "end_bar": 79, "label": "Chorus 2",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "root_fifth"},
            ],
        },
        default_instruments=['drum_kit', 'electric_bass', 'electric_guitar_dirty', 'electric_guitar_clean'],
        pacing_options=('uniform_1',),
        bridge_pacing_options=('uniform_2',),
    ),

    "edm_full_song": StylePreset(
        name="EDM (Full song)", tempo=126, key="A", scale="minor",
        # vi-IV-I-V cycle (minor reading) ×32 = 128 bars.
        progression=[("vi", 1.0), ("IV", 1.0), ("I", 1.0), ("V", 1.0)] * 32,
        voicing="triad", bass_pattern="disco_octave", drum_pattern="four_on_floor",
        chord_rhythm="pulse_quarter", melody_style="motif",
        chord_octave=4, bass_octave=2, default_bars=128,
        rhythm_variants={
            "Full song": [
                {"start_bar": 0,   "end_bar": 15,  "label": "Intro",
                 "chord_rhythm_h1": "pulse_quarter", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 16,  "end_bar": 31,  "label": "Buildup 1",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 32,  "end_bar": 47,  "label": "Drop 1",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 48,  "end_bar": 63,  "label": "Breakdown",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
                {"start_bar": 64,  "end_bar": 79,  "label": "Buildup 2",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 80,  "end_bar": 111, "label": "Drop 2",
                 "chord_rhythm_h1": "stabs_8th", "chord_rhythm_h2": "",
                 "bass_pattern": "disco_octave"},
                {"start_bar": 112, "end_bar": 127, "label": "Outro",
                 "chord_rhythm_h1": "pad", "chord_rhythm_h2": "",
                 "bass_pattern": "root"},
            ],
        },
        default_instruments=['drum_kit', 'synth_bass', 'synth_pad', 'synth_lead'],
        pacing_options=('uniform_1', 'uniform_2'),
        bridge_pacing_options=('uniform_2', 'uniform_1'),
    ),
}


def apply(
    style: StylePreset,
    bars: int = 16,
    seed: Optional[int] = None,
    tempo: Optional[float] = None,
    key: Optional[str] = None,
    include_melody: bool = True,
) -> MidiExporter:
    """Build a MidiExporter populated with chord / bass / melody / drum tracks
    from the preset.

    ``tempo`` and ``key`` override the preset values if provided — everything
    else (scale, voicing, patterns) follows the style.
    """
    final_tempo = tempo if tempo is not None else style.tempo
    final_key = key if key is not None else style.key

    midi = MidiExporter(tempo=final_tempo, time_signature=style.time_signature)

    midi.add_chord_progression(
        key=final_key,
        progression=style.progression,
        bars=bars,
        octave=style.chord_octave,
        scale_name=style.scale,
        voicing=style.voicing,
        program=style.chord_program,
        track_name=f"{style.name} Chords",
        rhythm=style.chord_rhythm,
        swing=style.swing,
    )

    midi.add_bass_line(
        key=final_key,
        progression=style.progression,
        bars=bars,
        octave=style.bass_octave,
        pattern=style.bass_pattern,
        scale_name=style.scale,
        swing=style.swing,
        program=style.bass_program,
        track_name=f"{style.name} Bass",
    )

    if include_melody:
        midi.add_melody(
            key=final_key,
            scale_name=style.scale,
            bars=bars,
            octave=style.melody_octave,
            note_density=style.melody_density,
            seed=seed,
            swing=style.swing,
            program=style.melody_program,
            track_name=f"{style.name} Melody",
            progression=style.progression,
            melody_style=style.melody_style,
        )

    if style.drum_pattern:
        midi.add_drum_pattern(
            pattern=style.drum_pattern,
            bars=bars,
            swing=style.swing,
            track_name=f"{style.name} Drums",
        )

    return midi


def list_styles() -> list[str]:
    """Return registered style keys in display order."""
    return list(STYLES.keys())
