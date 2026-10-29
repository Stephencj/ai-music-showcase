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


@dataclass(frozen=True)
class LeadVoice:
    label: str
    layers: tuple[LeadLayer, ...]
    register: str = "synth"       # "synth" | "horn" | "guitar"
    gain_db: float = 0.0          # level-matches voices (sampled ones are peakier)


FUSION_DRIVE = 16.0      # dB into the overdrive (see sampled._amp): singing, not fuzz

_PUNCH = LeadVoice("Punchy synth (the \"Sonic\" synth)", (LeadLayer("synth", "punch"),))

LEAD_VOICES: dict[str, LeadVoice] = {
    "punch": _PUNCH,
    # Kept by name: the bright analog-style lead from the sizzle-reel takes.
    "sonic": _PUNCH,
    "ewi": LeadVoice("Wind-controller synth (EWI / Lyricon)", (LeadLayer("synth", "ewi"),)),
    "layered": LeadVoice("Synth over a trumpet an octave below", (
        LeadLayer("synth", "layered"),
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet", octave=-1, db=-4.0),
    )),
    # The big-band lead: trumpet and alto sax in unison, trombone an octave down.
    "horns": LeadVoice("Horn section (trumpet + alto sax, trombone below)", (
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet"),
        LeadLayer("sfz", sfz="alto_sax", db=-2.0),
        LeadLayer("sfz", sfz="trombone", octave=-1, db=-6.0),
    ), register="horn", gain_db=2.5),
    "trumpet": LeadVoice("Solo trumpet", (
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet"),
    ), register="horn", gain_db=6.5),
    "guitar": LeadVoice("Electric guitar (Gretsch, fusion overdrive)", (
        LeadLayer("sfz", sfz="guitar_twang", sfz_short="guitar_staccato", drive_db=FUSION_DRIVE),
    ), register="guitar", gain_db=2.5),
    # Trumpet and overdriven guitar in unison: the horn's attack and body, the
    # guitar's singing sustain.
    "trumpet_guitar": LeadVoice("Trumpet + overdriven guitar in unison", (
        LeadLayer("sfz", sfz="trumpet_sus", sfz_short="trumpet"),
        LeadLayer("sfz", sfz="guitar_twang", sfz_short="guitar_staccato", drive_db=FUSION_DRIVE, db=-1.5),
    ), register="horn", gain_db=3.5),
}

DEFAULT_VOICE = "punch"


def voice(name: str | None) -> LeadVoice:
    return LEAD_VOICES.get(name or DEFAULT_VOICE, LEAD_VOICES[DEFAULT_VOICE])
