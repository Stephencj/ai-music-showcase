"""Mix per-track stems into a stereo bus, then apply the master chain.

Per-family defaults set pan + relative gain. Drums and bass center, chords
slightly wide, melody/lead off-center, pad wide. Final mix is normalized
to ~-1 dBFS peak before the master chain — the master limiter then sets
final headroom.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

import pedalboard as pdb

from .effects import (
    EffectChainLibrary,
    apply_chain,
    classify_family,
)
from .synth import RenderedStems, TrackStem

logger = logging.getLogger(__name__)


def _track_board(s: dict) -> "pdb.Pedalboard":
    """Build a per-track adjustment chain (EQ → compressor → FX) from a settings
    dict. Everything is RELATIVE to the family baseline: zeros/off = no change,
    so a producer just dials in adjustments. Signal order is conventional
    (tone/dynamics before the time-based effects)."""
    fx: list = []
    eq = s.get("eq") or {}
    if eq.get("low_db"):
        fx.append(pdb.LowShelfFilter(cutoff_frequency_hz=120.0, gain_db=float(eq["low_db"])))
    if eq.get("mid_db"):
        fx.append(pdb.PeakFilter(cutoff_frequency_hz=1000.0, gain_db=float(eq["mid_db"]), q=0.8))
    if eq.get("high_db"):
        fx.append(pdb.HighShelfFilter(cutoff_frequency_hz=4500.0, gain_db=float(eq["high_db"])))
    comp = s.get("comp") or {}
    if float(comp.get("ratio", 1) or 1) > 1.0:
        fx.append(pdb.Compressor(threshold_db=float(comp.get("threshold_db", -18.0)),
                                 ratio=float(comp["ratio"]), attack_ms=12.0, release_ms=140.0))
    fxs = s.get("fx") or {}
    if fxs.get("distortion"):
        fx.append(pdb.Distortion(drive_db=float(fxs["distortion"]) * 26.0))
    if fxs.get("chorus"):
        fx.append(pdb.Chorus(rate_hz=0.8, depth=0.25, feedback=0.0, mix=float(fxs["chorus"]) * 0.5))
    if fxs.get("delay"):
        fx.append(pdb.Delay(delay_seconds=0.25, feedback=0.28, mix=float(fxs["delay"]) * 0.45))
    if fxs.get("reverb"):
        wet = float(fxs["reverb"]) * 0.42
        fx.append(pdb.Reverb(room_size=0.55, damping=0.5, wet_level=wet, dry_level=1.0 - wet))
    return pdb.Pedalboard(fx)


# Per-family mix defaults. ``pan`` ∈ [-1, 1] (-1=L, +1=R). ``gain_db`` is
# applied before panning. ``stereo_widen`` ∈ [0, 1] adds a 12 ms haas-
# delayed mirror at the opposing pan for backing-vocal-style thickness.
# Values are anchored to industry mixing practice (research:
# 2026-05-15) with the LEAD VOCAL as reference. Other families sit at
# specific offsets so every element is heard without masking, and
# percussion / brass / strings get conventional stereo placement.
@dataclass(frozen=True)
class MixDefaults:
    pan: float
    gain_db: float
    stereo_widen: float = 0.0


_FAMILY_MIX: dict[str, MixDefaults] = {
    # Drums / bass anchor the bottom; kick + bass mono center.
    "drums":      MixDefaults(pan=0.0,  gain_db=-2.0),
    "bass":       MixDefaults(pan=0.0,  gain_db=-3.5),
    # Comp instruments sit ~9 dB under the vocal, slightly off-center to
    # leave the center for the lead vocal.
    "chords":     MixDefaults(pan=-0.15, gain_db=-5.0),
    "brass":      MixDefaults(pan=0.25, gain_db=-7.0),
    "woodwind":   MixDefaults(pan=-0.20, gain_db=-9.0),
    "strings":    MixDefaults(pan=0.0,  gain_db=-10.0, stereo_widen=0.35),
    # Lead vocal sits forward, mono center — the anchor of the mix.
    "lead_vocal": MixDefaults(pan=0.0,  gain_db=-9.0),
    # Backing vocals: widened pair, ~5 dB below the lead.
    "bvocal":     MixDefaults(pan=0.0,  gain_db=-8.0, stereo_widen=0.40),
    # Legacy lead / melody families (used when nothing more specific
    # classifies). Kept for back-compat with cells that fall back to
    # the role-token names.
    "melody":     MixDefaults(pan=0.15, gain_db=-12.0),
    "lead":       MixDefaults(pan=-0.15, gain_db=-16.0),
    "pad":        MixDefaults(pan=0.10, gain_db=-7.0),
    "extra":      MixDefaults(pan=0.0,  gain_db=-7.0),
}


@dataclass
class ProcessedStem:
    """Stem after per-family effects + pan/gain, ready to sum."""
    name: str
    family: str
    audio: np.ndarray            # (2, N) stereo float32
    sample_rate: int


class Mixer:
    """Process stems through per-family effect chains, sum, master."""

    def __init__(
        self,
        library: Optional[EffectChainLibrary] = None,
        *,
        family_mix: Optional[dict[str, MixDefaults]] = None,
        sidechain_kick_into: tuple[str, ...] = (),
        track_mix: Optional[dict[str, dict]] = None,
        stem_targets: Optional[dict[str, float]] = None,
    ):
        self.library = library or EffectChainLibrary()
        # Loudness targets per stem (MixProfile.stem_targets): the first key
        # that is a substring of the track name (or "family:<name>") sets the
        # stem's integrated LUFS before the producer's own track settings.
        self.stem_targets = stem_targets or {}
        self.family_mix = family_mix or _FAMILY_MIX
        # Families ducked by the kick's envelope before they reach the
        # master bus. Empty tuple = no ducking. Driven by MixProfile.
        self.sidechain_kick_into = tuple(sidechain_kick_into)
        # Per-TRACK producer adjustments (mute / fader / pan / EQ / comp / FX),
        # keyed by track name, layered on top of the family baseline.
        self.track_mix = track_mix or {}

    # -- single-stem path --------------------------------------------------

    def process_stem(self, stem: TrackStem) -> ProcessedStem:
        family = classify_family(stem.name, stem.program, stem.is_drum)
        chain = self.library.for_family(family)
        mono_processed = apply_chain(chain, stem.audio, stem.sample_rate)

        # Pedalboard chains may emit stereo (Reverb etc.) — normalize shape.
        if mono_processed.ndim == 1:
            stereo = _mono_to_stereo(mono_processed)
        elif mono_processed.shape[0] == 2:
            stereo = mono_processed
        else:
            stereo = mono_processed.T  # (samples, 2) → (2, samples)

        defaults = self.family_mix.get(family, _FAMILY_MIX["extra"])
        stereo = _apply_gain_db(stereo, defaults.gain_db)
        stereo = _apply_pan(stereo, defaults.pan)
        widen = getattr(defaults, "stereo_widen", 0.0)
        if widen > 0:
            stereo = _apply_haas_widen(stereo, stem.sample_rate, widen)

        target = self._stem_target(stem.name, family)
        if target is not None:
            stereo = _level_to(stereo, stem.sample_rate, target)

        # Per-track producer adjustments, layered on the family baseline.
        ts = self.track_mix.get(stem.name)
        if ts:
            if ts.get("mute"):
                stereo = np.zeros_like(stereo)
            else:
                board = _track_board(ts)
                if len(board):
                    stereo = apply_chain(board, stereo, stem.sample_rate)
                    if stereo.ndim == 1:
                        stereo = _mono_to_stereo(stereo)
                    elif stereo.shape[0] != 2 and stereo.shape[-1] == 2:
                        stereo = stereo.T
                if ts.get("gain_db"):
                    stereo = _apply_gain_db(stereo, float(ts["gain_db"]))
                if ts.get("pan") is not None:
                    stereo = _apply_pan(stereo, float(ts["pan"]))

        return ProcessedStem(
            name=stem.name,
            family=family,
            audio=stereo.astype(np.float32, copy=False),
            sample_rate=stem.sample_rate,
        )

    def _stem_target(self, name: str, family: str) -> Optional[float]:
        low = name.lower()
        for key, lufs in self.stem_targets.items():
            if key.startswith("family:"):
                if key[7:] == family:
                    return float(lufs)
            elif key in low:
                return float(lufs)
        return None

    # -- full mix ----------------------------------------------------------

    def mix(
        self,
        stems: RenderedStems,
        *,
        master_preset: str = "default",
    ) -> tuple[np.ndarray, list[ProcessedStem]]:
        """Process all stems, sum to a stereo bus, run the master chain.

        Returns ``(mix, processed_stems)`` where ``mix`` is shape
        ``(2, N)`` float32 at ``stems.sample_rate``.
        """
        processed = [self.process_stem(s) for s in stems.stems]

        if not processed:
            raise ValueError("No stems to mix.")

        n = max(p.audio.shape[1] for p in processed)

        # Sidechain ducking — compute the kick envelope (if any drums
        # stem is present + ducking is enabled) and attenuate the
        # listed family stems before summing. Implemented as a simple
        # peak-follow on the drums stem; not perfect but produces the
        # characteristic EDM pumping when the profile asks for it.
        sidechain_targets = set(self.sidechain_kick_into)
        envelope: Optional[np.ndarray] = None
        if sidechain_targets:
            drum_stems = [p for p in processed if p.family == "drums"]
            if drum_stems:
                envelope = _build_kick_envelope(
                    drum_stems[0].audio, stems.sample_rate, n,
                )

        bus = np.zeros((2, n), dtype=np.float32)
        for p in processed:
            audio = p.audio
            if audio.shape[1] < n:
                pad = np.zeros((2, n - audio.shape[1]), dtype=np.float32)
                audio = np.concatenate([audio, pad], axis=1)
            # Apply sidechain ducking when this stem is in the target
            # list. Envelope ranges [duck_amount, 1.0] — peaks pull the
            # stem down by up to ~3 dB during kick hits.
            if envelope is not None and p.family in sidechain_targets:
                audio = audio * envelope[None, :]
            bus += audio

        # Pre-master normalization — gives the master chain a consistent
        # input level regardless of how many stems were summed.
        peak = float(np.max(np.abs(bus)))
        if peak > 0:
            bus *= 0.89 / peak  # ~-1 dBFS

        master = self.library.master(master_preset)
        mastered = apply_chain(master, bus, stems.sample_rate)
        if mastered.ndim == 1:
            mastered = _mono_to_stereo(mastered)
        elif mastered.shape[0] != 2 and mastered.shape[1] == 2:
            mastered = mastered.T

        return mastered.astype(np.float32, copy=False), processed


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _level_to(stereo: np.ndarray, sample_rate: int, target_lufs: float, max_db: float = 24.0) -> np.ndarray:
    """Scale a stem to ``target_lufs`` integrated (gated, so a part that plays
    only some sections is levelled by what it plays). Silent stems pass."""
    from .loudness import integrated_lufs
    try:
        lufs = integrated_lufs(stereo, sample_rate)
    except Exception:  # noqa: BLE001 — a stem too short to measure keeps its level
        return stereo
    if not np.isfinite(lufs) or lufs < -70:
        return stereo
    gain = float(np.clip(target_lufs - lufs, -max_db, max_db))
    return _apply_gain_db(stereo, gain)


def _mono_to_stereo(mono: np.ndarray) -> np.ndarray:
    return np.stack([mono, mono], axis=0)


def _apply_gain_db(stereo: np.ndarray, gain_db: float) -> np.ndarray:
    if gain_db == 0.0:
        return stereo
    return stereo * (10.0 ** (gain_db / 20.0))


def _build_kick_envelope(drums_stereo: np.ndarray, sample_rate: int,
                         total_samples: int,
                         attack_ms: float = 10.0,
                         release_ms: float = 150.0,
                         duck_amount_db: float = -3.0,
                         threshold: float = 0.25) -> np.ndarray:
    """Build a sidechain envelope ∈ [duck_factor, 1.0] from the drums
    stem. When the drums peak exceeds ``threshold``, generate a
    fast-attack / slow-release dip that pulls listed family stems
    down by up to ``duck_amount_db`` (default -3 dB).

    Returns a 1-D float32 array of length ``total_samples``. Pure
    numpy — no scipy / DSP framework. The result multiplies stem
    audio directly.
    """
    mono = np.mean(drums_stereo, axis=0) if drums_stereo.ndim == 2 else drums_stereo
    n = min(len(mono), total_samples)
    duck_factor = 10.0 ** (duck_amount_db / 20.0)
    # Detect kick onsets — peak detection above threshold.
    abs_mono = np.abs(mono[:n])
    # Smooth via simple moving max to catch the body of the kick.
    window = max(1, int(0.005 * sample_rate))  # 5 ms
    if window > 1:
        kernel = np.ones(window, dtype=np.float32) / window
        abs_mono = np.convolve(abs_mono, kernel, mode="same")
    onsets = abs_mono > threshold
    # Build an attack/release envelope: 1.0 → duck_factor on attack,
    # duck_factor → 1.0 on release.
    env = np.ones(total_samples, dtype=np.float32)
    if not np.any(onsets):
        return env
    attack_samples = max(1, int(attack_ms * sample_rate / 1000))
    release_samples = max(1, int(release_ms * sample_rate / 1000))
    target = duck_factor
    prev = 1.0
    attack_step = (target - 1.0) / attack_samples
    release_step = (1.0 - target) / release_samples
    in_attack = False
    in_release = False
    samples_left = 0
    for i in range(n):
        if onsets[i] and not in_attack:
            in_attack = True
            in_release = False
            samples_left = attack_samples
            prev = env[i - 1] if i > 0 else 1.0
        if in_attack:
            prev = max(target, prev + attack_step)
            samples_left -= 1
            if samples_left <= 0:
                in_attack = False
                in_release = True
                samples_left = release_samples
        elif in_release:
            prev = min(1.0, prev + release_step)
            samples_left -= 1
            if samples_left <= 0:
                in_release = False
                prev = 1.0
        env[i] = prev
    return env


def _apply_haas_widen(stereo: np.ndarray, sample_rate: int,
                      amount: float) -> np.ndarray:
    """Synthesize a wider stereo image by Haas-delaying one channel.

    ``amount`` ∈ [0, 1] — scales the delayed-channel mix in. Adds an
    ~12 ms delay to the right channel of a mirror copy and sums it
    back into both channels. Backing-vocal-style thickness without
    actually doubling the source.
    """
    if amount <= 0.0:
        return stereo
    delay_samples = max(1, int(0.012 * sample_rate))
    if delay_samples >= stereo.shape[1]:
        return stereo
    delayed = np.zeros_like(stereo)
    delayed[:, delay_samples:] = stereo[:, :-delay_samples]
    # Mirror the delayed copy: L → R and R → L for the spread.
    mirrored = np.stack([delayed[1], delayed[0]], axis=0)
    return stereo + (mirrored * float(amount))


def _apply_pan(stereo: np.ndarray, pan: float) -> np.ndarray:
    """Equal-power pan. ``pan`` ∈ [-1, 1]."""
    if pan == 0.0:
        return stereo
    pan = float(np.clip(pan, -1.0, 1.0))
    angle = (pan + 1.0) * (np.pi / 4.0)   # 0..π/2
    left_gain = float(np.cos(angle))
    right_gain = float(np.sin(angle))
    out = stereo.copy()
    out[0] *= left_gain * np.sqrt(2.0)
    out[1] *= right_gain * np.sqrt(2.0)
    return out
