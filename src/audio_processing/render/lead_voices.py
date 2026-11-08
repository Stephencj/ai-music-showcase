"""Named lead voices: what the lead track (GM synth leads 80-87) sounds like
under ``sound="sampled"``.

A voice stacks layers. A layer is the built-in synth (a patch from
:mod:`.synth_lead`) or a sampled instrument from
:data:`.sampled.SAMPLED_INSTRUMENTS`, optionally with a different library for
short notes (staccato vs. sustain samples), an octave shift, a level and amp
drive. ``register`` tells the composer where the voice sounds best (see
``_LEAD_REGISTER`` in src/composition/funk_fusion.py).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LeadLayer:
    kind: str                     # "synth" or "sfz"
    patch: str = "punch"          # synth patch (synth layers)
    sfz: str = ""                 # sampled instrument id for long notes (sfz layers)
    sfz_short: str = ""           # optional id for notes shorter than ``short_below``
    short_below: float = 0.2      # seconds
    octave: int = 0
    db: float = 0.0
    drive_db: float = 0.0         # amp drive (guitar)
    space: float = 0.0            # 0..1: this layer's own delay + big reverb (on top of the mix chain)
    chorus: float = 0.0           # 0..1: a light stereo chorus (clean guitar shimmer)
    vibrato: float = 0.0          # ± cents of delayed vibrato on held notes (0 = none)


@dataclass(frozen=True)
class LeadVoice:
    label: str
    layers: tuple[LeadLayer, ...]
    register: str = "synth"       # "synth" | "horn" | "guitar" | "guitar_high"
    gain_db: float = 0.0          # level-matches voices (sampled ones are peakier)


HELD_VIBRATO = 15.0      # ± cents on held notes for sampled lead layers (eases long notes)
FUSION_DRIVE = 16.0      # dB into the overdrive (see sampled._amp): singing, not fuzz
HIGH_SPACE = 0.2         # delay + reverb on the high guitar (1.0, 0.65, 0.4 were all too wet)

_PUNCH = LeadVoice("Punchy synth (the \"Sonic\" synth)", (LeadLayer("synth", "punch"),))

LEAD_VOICES: dict[str, LeadVoice] = {
    "punch": _PUNCH,
    # Kept by name: the bright analog-style lead from the sizzle-reel takes.
    "sonic": _PUNCH,
    "ewi": LeadVoice("Wind-controller synth (EWI / Lyricon)", (LeadLayer("synth", "ewi"),)),
    "layered": LeadVoice("Synth over a trumpet an octave below", (
        LeadLayer("synth", "layered"),
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet", octave=-1, db=-4.0, vibrato=HELD_VIBRATO),
    )),
    # The big-band lead: trumpet and alto sax in unison, trombone an octave down.
    "horns": LeadVoice("Horn section (trumpet + alto sax, trombone below)", (
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet", vibrato=HELD_VIBRATO),
        LeadLayer("sfz", sfz="alto_sax", db=-2.0, vibrato=HELD_VIBRATO),
        LeadLayer("sfz", sfz="trombone", octave=-1, db=-6.0, vibrato=HELD_VIBRATO),
    ), register="horn", gain_db=2.5),
    "trumpet": LeadVoice("Solo trumpet", (
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet", vibrato=HELD_VIBRATO),
    ), register="horn", gain_db=6.5),
    "guitar": LeadVoice("Electric guitar (Gretsch, fusion overdrive)", (
        LeadLayer("sfz", sfz="guitar_twang", sfz_short="guitar_staccato", drive_db=FUSION_DRIVE, vibrato=HELD_VIBRATO),
    ), register="guitar", gain_db=2.5),
    # The overdriven guitar an octave up, singing in a big space.
    "guitar_high": LeadVoice("Overdriven guitar, an octave up, with delay + reverb", (
        LeadLayer("sfz", sfz="guitar_twang", sfz_short="guitar_staccato", drive_db=FUSION_DRIVE, space=HIGH_SPACE, vibrato=HELD_VIBRATO),
    ), register="guitar_high", gain_db=2.5),
    # The guitar as it is, with the high, spacious one stacked an octave above.
    "guitar_stack": LeadVoice("Overdriven guitar + the same an octave up in reverb", (
        LeadLayer("sfz", sfz="guitar_twang", sfz_short="guitar_staccato", drive_db=FUSION_DRIVE, vibrato=HELD_VIBRATO),
        LeadLayer("sfz", sfz="guitar_twang", sfz_short="guitar_staccato", drive_db=FUSION_DRIVE,
                  octave=1, space=HIGH_SPACE, db=-3.0, vibrato=HELD_VIBRATO),
    ), register="guitar", gain_db=2.5),
    # The Gretsch clean: a light chorus and a small, dry room (neo-soul).
    # A clean Fender (FreePats FSBS clean, CC0): the Gretsch twang samples
    # carried a hissy noise band above 8 kHz.
    "guitar_clean": LeadVoice("Clean electric guitar (Fender, light chorus)", (
        LeadLayer("sfz", sfz="guitar_fsbs_clean", chorus=1.0, space=0.15, vibrato=HELD_VIBRATO),
    ), register="guitar", gain_db=3.0),
    # Trumpet and overdriven guitar in unison: the horn's attack and body, the
    # guitar's singing sustain.
    "trumpet_guitar": LeadVoice("Trumpet + overdriven guitar in unison", (
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet", vibrato=HELD_VIBRATO),
        LeadLayer("sfz", sfz="guitar_twang", sfz_short="guitar_staccato", drive_db=FUSION_DRIVE, db=-1.5, vibrato=HELD_VIBRATO),
    ), register="horn", gain_db=3.5),
}

DEFAULT_VOICE = "punch"


def voice(name: str | None) -> LeadVoice:
    return LEAD_VOICES.get(name or DEFAULT_VOICE, LEAD_VOICES[DEFAULT_VOICE])
