"""Per-family effect chains and master-bus presets, built on `pedalboard`.

Tracks are sorted into *families* (drums / bass / chords / pad / melody /
lead / extra) by track name + GM program. Each family has a default chain
(HPF + comp on bass, bus comp on drums, plate-verb send on melody, etc.)
that's applied to its stem before mixing.

The master bus has its own preset chain (``default`` / ``loud`` /
``cinematic`` / ``transparent``) applied after summing.

All chains use only `pedalboard`'s built-in DSP — no VST3/AU plugin
dependencies. Users who want real plugins can extend
``EffectChainLibrary`` later by populating ``family_chains`` with chains
that include ``pedalboard.load_plugin(...)`` results.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import pedalboard as pdb

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Family classification
# ---------------------------------------------------------------------------

# GM program ranges → family. Names used for unambiguous mapping; falls
# back to a name-substring heuristic.
_GM_PROGRAM_FAMILIES: list[tuple[range, str]] = [
    (range(0, 8),    "chords"),     # piano
    (range(8, 16),   "chords"),     # chromatic perc
    (range(16, 24),  "pad"),        # organs
    (range(24, 32),  "chords"),     # guitar (used as chord/comp)
    (range(32, 40),  "bass"),
    (range(40, 48),  "strings"),    # strings (solo + ensemble)
    (range(48, 52),  "strings"),    # ensemble strings
    (range(52, 56),  "bvocal"),     # choir / voice oohs / synth voice
    (range(56, 64),  "brass"),      # brass section + solos
    (range(64, 72),  "woodwind"),   # reeds: sax, oboe, clarinet, bassoon
    (range(72, 80),  "woodwind"),   # pipes: piccolo, flute, recorder, ocarina
    (range(80, 88),  "lead"),       # synth lead
    (range(88, 96),  "pad"),        # synth pad
    (range(96, 104), "pad"),        # synth fx
    (range(104, 112), "melody"),    # ethnic
    (range(112, 120), "drums"),     # percussive
    (range(120, 128), "extra"),     # sound effects
]

# Lowercase substrings → family. Track-name-driven overrides — checked
# in order so longer / more-specific names match first ("lead vocal"
# beats the bare "lead" hint, "backing vocals" beats "bvocal" alone).
_NAME_HINT_FAMILIES: list[tuple[str, str]] = [
    # Vocals — most specific first.
    ("lead vocal", "lead_vocal"),
    ("backing vocal", "bvocal"),
    ("vocal harmon", "bvocal"),
    ("choir", "bvocal"),
    # Drums.
    ("drum", "drums"), ("kick", "drums"), ("snare", "drums"),
    ("perc", "drums"), ("hat", "drums"),
    # Bass.
    ("bass", "bass"), ("flea", "bass"), ("bootsy", "bass"),
    # Brass section.
    ("brass section", "brass"), ("trumpet", "brass"), ("trombone", "brass"),
    ("sax", "brass"),  # sax_alto / sax_tenor / sax_baritone
    # Woodwinds.
    ("woodwind", "woodwind"), ("flute", "woodwind"),
    ("clarinet", "woodwind"), ("oboe", "woodwind"),
    ("bassoon", "woodwind"),
    # Strings (orchestral, separate from synth pads).
    ("string section", "strings"), ("violin", "strings"),
    ("viola", "strings"), ("cello", "strings"), ("contrabass", "strings"),
    # Lead guitar — must beat the bare "guitar" -> chords hint below so
    # the riff/solo voice mixes as a forward lead, not a rhythm comp.
    ("lead guitar", "lead"),
    # Chord / lead.
    ("chord", "chords"), ("rhodes", "chords"), ("piano", "chords"),
    ("rhythm gt", "chords"), ("comp", "chords"), ("organ", "chords"),
    ("guitar", "chords"),
    # Pad / lead / melody fallbacks.
    ("pad", "pad"),
    ("lead", "lead"), ("riff", "lead"),
    ("melody", "melody"), ("theme", "melody"),
]

VALID_FAMILIES = (
    "drums", "bass", "chords", "pad", "melody", "lead", "extra",
    "brass", "woodwind", "strings", "lead_vocal", "bvocal",
)


def classify_family(track_name: str, program: int, is_drum: bool) -> str:
    """Return the family for a track. Drums always win."""
    if is_drum:
        return "drums"
    name = track_name.lower()
    for hint, fam in _NAME_HINT_FAMILIES:
        if hint in name:
            return fam
    for prog_range, fam in _GM_PROGRAM_FAMILIES:
        if program in prog_range:
            return fam
    return "extra"


# ---------------------------------------------------------------------------
# Default chain factories
# ---------------------------------------------------------------------------
# Each factory returns a list[Plugin] in the order they should run. Returning
# a fresh list per call is intentional — pedalboard plugins hold state.

ChainFactory = Callable[[], list[pdb.Plugin]]


def _drums_chain() -> list[pdb.Plugin]:
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=35.0),
        pdb.Compressor(threshold_db=-14.0, ratio=2.5,
                       attack_ms=8.0, release_ms=110.0),
        pdb.PeakFilter(cutoff_frequency_hz=120.0, gain_db=1.5, q=0.8),
        pdb.PeakFilter(cutoff_frequency_hz=6000.0, gain_db=2.0, q=0.7),
        pdb.Reverb(room_size=0.18, damping=0.5, wet_level=0.04, dry_level=0.96),
    ]


def _bass_chain() -> list[pdb.Plugin]:
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=40.0),
        pdb.Compressor(threshold_db=-16.0, ratio=4.0,
                       attack_ms=12.0, release_ms=140.0),
        pdb.PeakFilter(cutoff_frequency_hz=90.0, gain_db=1.5, q=0.9),
        pdb.PeakFilter(cutoff_frequency_hz=2000.0, gain_db=1.5, q=0.8),
    ]


def _chords_chain() -> list[pdb.Plugin]:
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=120.0),
        # Cut the 200-400 Hz mud zone so the comp doesn't fight the bass /
        # vocal body.
        pdb.PeakFilter(cutoff_frequency_hz=250.0, gain_db=-2.0, q=0.9),
        # Reciprocal carve at 3-4 kHz — leaves room for the vocal's
        # presence boost so they don't mask each other.
        pdb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=-0.5, q=0.7),
        pdb.Compressor(threshold_db=-18.0, ratio=2.0,
                       attack_ms=15.0, release_ms=160.0),
        pdb.Chorus(rate_hz=0.6, depth=0.18, feedback=0.0, mix=0.15),
        pdb.Reverb(room_size=0.30, damping=0.5, wet_level=0.10, dry_level=0.90),
    ]


def _pad_chain() -> list[pdb.Plugin]:
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=150.0),
        pdb.PeakFilter(cutoff_frequency_hz=250.0, gain_db=-2.0, q=0.9),
        pdb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=-1.0, q=0.7),
        pdb.Compressor(threshold_db=-22.0, ratio=2.0,
                       attack_ms=25.0, release_ms=240.0),
        pdb.Chorus(rate_hz=0.4, depth=0.25, feedback=0.0, mix=0.25),
        pdb.Reverb(room_size=0.55, damping=0.45, wet_level=0.28, dry_level=0.72),
    ]


def _melody_chain() -> list[pdb.Plugin]:
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=130.0),
        pdb.Compressor(threshold_db=-20.0, ratio=2.5,
                       attack_ms=12.0, release_ms=140.0),
        pdb.PeakFilter(cutoff_frequency_hz=4500.0, gain_db=0.5, q=0.8),
        pdb.Delay(delay_seconds=0.18, feedback=0.12, mix=0.07),
        pdb.Reverb(room_size=0.45, damping=0.55, wet_level=0.36, dry_level=0.64),
    ]


def _lead_chain() -> list[pdb.Plugin]:
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=130.0),
        pdb.Compressor(threshold_db=-18.0, ratio=3.0,
                       attack_ms=8.0, release_ms=120.0),
        pdb.PeakFilter(cutoff_frequency_hz=3000.0, gain_db=0.5, q=0.7),
        pdb.Delay(delay_seconds=0.22, feedback=0.18, mix=0.10),
        pdb.Reverb(room_size=0.45, damping=0.5, wet_level=0.40, dry_level=0.60),
    ]


def _brass_chain() -> list[pdb.Plugin]:
    """Brass-section / solo brass — bright presence + medium plate verb."""
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=120.0),
        pdb.PeakFilter(cutoff_frequency_hz=250.0, gain_db=-2.0, q=0.9),
        # Reciprocal carve for vocal presence.
        pdb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=-0.5, q=0.7),
        pdb.Compressor(threshold_db=-16.0, ratio=4.0,
                       attack_ms=3.0, release_ms=120.0),  # tame transients
        pdb.PeakFilter(cutoff_frequency_hz=5000.0, gain_db=1.5, q=0.8),  # bite
        pdb.Reverb(room_size=0.35, damping=0.5, wet_level=0.18, dry_level=0.82),
    ]


def _woodwind_chain() -> list[pdb.Plugin]:
    """Woodwinds (flute / clarinet / oboe / bassoon) — gentler comp + hall."""
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=150.0),
        pdb.PeakFilter(cutoff_frequency_hz=300.0, gain_db=-1.5, q=0.8),
        pdb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=-0.5, q=0.7),
        pdb.Compressor(threshold_db=-20.0, ratio=2.5,
                       attack_ms=15.0, release_ms=160.0),
        pdb.PeakFilter(cutoff_frequency_hz=8000.0, gain_db=1.0, q=0.8),  # air
        pdb.Reverb(room_size=0.50, damping=0.45, wet_level=0.25, dry_level=0.75),
    ]


def _strings_chain() -> list[pdb.Plugin]:
    """Orchestral strings — gentle comp + long hall, gentle mud cut."""
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=120.0),
        pdb.PeakFilter(cutoff_frequency_hz=300.0, gain_db=-2.0, q=0.9),
        pdb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=-0.5, q=0.7),
        pdb.Compressor(threshold_db=-20.0, ratio=2.0,
                       attack_ms=30.0, release_ms=300.0),
        pdb.Reverb(room_size=0.70, damping=0.40, wet_level=0.38, dry_level=0.62),
    ]


def _lead_vocal_chain() -> list[pdb.Plugin]:
    """Lead vocal — presence boost at 3.5 kHz + de-ess + short plate verb."""
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=120.0),
        # Mud cut.
        pdb.PeakFilter(cutoff_frequency_hz=250.0, gain_db=-2.0, q=0.9),
        # Presence — this is the vocal's signature boost. The chord /
        # brass / strings chains cut the SAME band so the vocal cuts
        # through.
        # Slight cut (not a boost) so the melody sits back instead of cutting through.
        pdb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=-1.0, q=0.7),
        # De-essing equivalent — cut sibilance band.
        pdb.PeakFilter(cutoff_frequency_hz=6500.0, gain_db=-3.0, q=2.5),
        # No air boost — keep it from grabbing attention.
        pdb.PeakFilter(cutoff_frequency_hz=12000.0, gain_db=0.0, q=0.6),
        # Light, high-threshold comp so the melody keeps its dynamics and
        # doesn't suck the air out of the mix.
        pdb.Compressor(threshold_db=-14.0, ratio=1.7,
                       attack_ms=15.0, release_ms=140.0),
        # Wetter, bigger plate so it blends into the bed.
        pdb.Reverb(room_size=0.45, damping=0.5, wet_level=0.35, dry_level=0.65),
    ]


def _bvocal_chain() -> list[pdb.Plugin]:
    """Backing vocals — wider with chorus + medium plate verb."""
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=130.0),
        pdb.PeakFilter(cutoff_frequency_hz=250.0, gain_db=-2.0, q=0.9),
        pdb.PeakFilter(cutoff_frequency_hz=3500.0, gain_db=-0.5, q=0.7),  # duck vocal band
        pdb.Compressor(threshold_db=-18.0, ratio=4.0,
                       attack_ms=8.0, release_ms=120.0),
        pdb.Chorus(rate_hz=0.5, depth=0.20, feedback=0.0, mix=0.20),
        pdb.Reverb(room_size=0.45, damping=0.5, wet_level=0.28, dry_level=0.72),
    ]


def _extra_chain() -> list[pdb.Plugin]:
    return [
        pdb.HighpassFilter(cutoff_frequency_hz=80.0),
        pdb.Compressor(threshold_db=-18.0, ratio=2.0,
                       attack_ms=15.0, release_ms=160.0),
        pdb.Reverb(room_size=0.30, damping=0.5, wet_level=0.10, dry_level=0.90),
    ]


_FAMILY_FACTORIES: dict[str, ChainFactory] = {
    "drums": _drums_chain,
    "bass": _bass_chain,
    "chords": _chords_chain,
    "pad": _pad_chain,
    "melody": _melody_chain,
    "lead": _lead_chain,
    "brass": _brass_chain,
    "woodwind": _woodwind_chain,
    "strings": _strings_chain,
    "lead_vocal": _lead_vocal_chain,
    "bvocal": _bvocal_chain,
    "extra": _extra_chain,
}


# ---------------------------------------------------------------------------
# Master presets
# ---------------------------------------------------------------------------

def _master_default() -> list[pdb.Plugin]:
    """Streaming-target master chain (-14 LUFS integrated, -1 dBTP).

    Modest tone-shaping at the low / high shelves + 1.5:1-ish bus-glue
    compression + brick-wall limiter at -1 dB. Targets the broad
    Spotify / Apple Music / YouTube loudness normalisation point so
    finished mixes feel even when the listener hits play across
    multiple platforms.
    """
    return [
        pdb.PeakFilter(cutoff_frequency_hz=80.0, gain_db=1.0, q=0.8),
        # Gentle wide dip through the harsh upper-mid "presence" band so a
        # forward lead/synth stops blaring; tames the whole mix's edge.
        pdb.PeakFilter(cutoff_frequency_hz=3000.0, gain_db=-4.0, q=0.9),
        # Roll off the top end so highs/hiss aren't exaggerated (de-harsh).
        pdb.HighShelfFilter(cutoff_frequency_hz=8000.0, gain_db=-2.0),
        # Bus-glue compression — a touch firmer (2.2:1) to even sections and
        # let quieter backing parts come through under the loud peaks.
        pdb.Compressor(threshold_db=-16.0, ratio=2.2,
                       attack_ms=20.0, release_ms=180.0),
        pdb.Limiter(threshold_db=-1.0, release_ms=120.0),
    ]


def _master_loud() -> list[pdb.Plugin]:
    return [
        pdb.PeakFilter(cutoff_frequency_hz=80.0, gain_db=1.5, q=0.8),
        pdb.PeakFilter(cutoff_frequency_hz=10000.0, gain_db=2.0, q=0.6),
        pdb.Compressor(threshold_db=-15.0, ratio=3.0,
                       attack_ms=10.0, release_ms=120.0),
        pdb.Gain(gain_db=2.0),
        pdb.Limiter(threshold_db=-0.3, release_ms=80.0),
    ]


def _master_cinematic() -> list[pdb.Plugin]:
    return [
        pdb.PeakFilter(cutoff_frequency_hz=60.0, gain_db=2.0, q=0.7),
        pdb.PeakFilter(cutoff_frequency_hz=12000.0, gain_db=2.0, q=0.6),
        pdb.Compressor(threshold_db=-14.0, ratio=2.5,
                       attack_ms=25.0, release_ms=240.0),
        pdb.Reverb(room_size=0.45, damping=0.4,
                   wet_level=0.06, dry_level=0.94),
        pdb.Limiter(threshold_db=-1.0, release_ms=180.0),
    ]


def _master_transparent() -> list[pdb.Plugin]:
    return [
        pdb.Compressor(threshold_db=-10.0, ratio=1.5,
                       attack_ms=30.0, release_ms=240.0),
        pdb.Limiter(threshold_db=-1.5, release_ms=200.0),
    ]


MASTER_PRESETS: dict[str, ChainFactory] = {
    "default": _master_default,
    "loud": _master_loud,
    "cinematic": _master_cinematic,
    "transparent": _master_transparent,
}


# ---------------------------------------------------------------------------
# EffectChainLibrary
# ---------------------------------------------------------------------------

@dataclass
class EffectChainLibrary:
    """Build per-family pedalboards. One library, one render pass.

    Override defaults by setting ``family_overrides[family]`` to a custom
    ``ChainFactory`` before calling :meth:`for_family`.
    """
    family_overrides: dict[str, ChainFactory] = field(default_factory=dict)

    def for_family(self, family: str) -> pdb.Pedalboard:
        if family not in VALID_FAMILIES:
            raise ValueError(
                f"Unknown family {family!r}. Valid: {VALID_FAMILIES}"
            )
        factory = self.family_overrides.get(family) or _FAMILY_FACTORIES[family]
        return pdb.Pedalboard(factory())

    @staticmethod
    def master(preset: str) -> pdb.Pedalboard:
        if preset not in MASTER_PRESETS:
            raise ValueError(
                f"Unknown master preset {preset!r}. "
                f"Valid: {list(MASTER_PRESETS.keys())}"
            )
        return pdb.Pedalboard(MASTER_PRESETS[preset]())


def apply_chain(
    board: pdb.Pedalboard, audio: np.ndarray, sample_rate: int,
) -> np.ndarray:
    """Apply ``board`` to ``audio``.

    ``audio`` may be mono ``(N,)`` or stereo ``(2, N)`` / ``(N, 2)``.
    Returns the same orientation as input (channels-first stereo).
    """
    if audio.ndim == 1:
        out = board(audio, sample_rate=sample_rate)
        return np.asarray(out, dtype=np.float32)

    # Pedalboard expects (samples, channels) for multi-channel input.
    if audio.shape[0] == 2 and audio.shape[1] > 2:
        audio_in = audio.T            # (samples, 2)
    else:
        audio_in = audio              # already (samples, 2)
    out = board(audio_in, sample_rate=sample_rate)
    out = np.asarray(out, dtype=np.float32)
    if out.ndim == 2 and out.shape[1] == 2:
        out = out.T                   # back to (2, samples)
    return out
