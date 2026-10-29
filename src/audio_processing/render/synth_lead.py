"""A monophonic subtractive synth lead (the classic fusion lead).

Two detuned band-limited sawtooths plus a square an octave down, through a
resonant low-pass whose cutoff jumps on each new phrase and settles, with
glide between legato notes and vibrato that fades in on held notes. Mono and
legato like a real lead synth: overlapping or back-to-back notes slide
instead of retriggering.

Rendered offline in numpy/scipy; the mixer's lead chain adds the delay and
reverb.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable

import numpy as np
from scipy.signal import lfilter

from .sfz import Note


@dataclass(frozen=True)
class LeadPatch:
    """Defaults are a punchy fusion lead: a bright filter "blip" on every
    note, some grit and a pulse edge, little glide."""
    detune_cents: float = 12.0
    sub_level: float = 0.08           # square, one octave down (body, not pitch)
    pulse_level: float = 0.2          # narrow pulse for a nasal edge
    pulse_width: float = 0.3
    glide: float = 0.025              # seconds to (mostly) reach the new pitch
    legato_gap: float = 0.008         # only truly joined notes slide
    attack: float = 0.002
    decay: float = 0.16
    sustain: float = 0.62
    release: float = 0.09
    cutoff: float = 1400.0            # resting cutoff, Hz
    cutoff_env: float = 5000.0        # extra cutoff at the attack
    cutoff_decay: float = 0.12        # seconds for the filter to settle
    cutoff_keytrack: float = 0.5      # cutoff follows pitch (0..1)
    resonance: float = 1.9            # filter Q
    retrigger_filter: bool = True     # every note re-opens the filter, even legato
    vibrato_rate: float = 6.0
    vibrato_cents: float = 8.0
    vibrato_delay: float = 0.4        # held notes only
    drive: float = 1.7                # saturation after the filter
    noise_level: float = 0.0          # breath noise into the filter (wind-controller leads)
    saw_level: float = 1.0


DEFAULT_PATCH = LeadPatch()

# Synth patches. Lead *voices* (render/lead_voices.py) pick one of these and
# can layer sampled instruments with it.
LEAD_PATCHES: dict[str, LeadPatch] = {
    # Punchy analog-style lead: bright filter blip on every note, some grit.
    "punch": DEFAULT_PATCH,
    # Wind-controller (EWI / Lyricon) lead, the 80s fusion-band sound: breathy,
    # softer edge, the filter follows how hard each note is played, and it
    # slides and swells like a horn so it sits with acoustic instruments.
    "ewi": LeadPatch(
        detune_cents=5.0, sub_level=0.05, pulse_level=0.55, pulse_width=0.5, saw_level=0.55,
        noise_level=0.07, glide=0.05, legato_gap=0.03, attack=0.018, decay=0.3,
        sustain=0.85, release=0.11, cutoff=900.0, cutoff_env=2600.0, cutoff_decay=0.25,
        cutoff_keytrack=0.6, resonance=1.1, retrigger_filter=True, vibrato_rate=5.2,
        vibrato_cents=11.0, vibrato_delay=0.22, drive=1.2,
    ),
    # A slightly smoother punch for sitting on top of a real trumpet.
    "layered": LeadPatch(drive=1.4, pulse_level=0.15),
}


def _hz(pitch: float) -> np.ndarray | float:
    return 440.0 * 2.0 ** ((pitch - 69.0) / 12.0)


def _blep_saw(phase: np.ndarray, dt: np.ndarray) -> np.ndarray:
    """PolyBLEP sawtooth from a 0..1 phase and per-sample phase increment."""
    t = phase % 1.0
    out = 2.0 * t - 1.0
    lo = t < dt
    x = t[lo] / dt[lo]
    out[lo] -= x + x - x * x - 1.0
    hi = t > 1.0 - dt
    x = (t[hi] - 1.0) / dt[hi]
    out[hi] -= x * x + x + x + 1.0
    return out


def _segments(notes: list[Note], patch: LeadPatch):
    """Group notes into legato phrases: lists of notes that slide into each other."""
    phrases: list[list[Note]] = []
    for n in sorted(notes, key=lambda n: (n.start, n.pitch)):
        if phrases and n.start - phrases[-1][-1].end <= patch.legato_gap:
            phrases[-1].append(n)
        else:
            phrases.append([n])
    return phrases


def _lowpass_blocks(x: np.ndarray, cutoff: np.ndarray, q: float, sr: int, block: int = 64) -> np.ndarray:
    """Time-varying RBJ low-pass, coefficients updated every ``block`` samples."""
    out = np.empty_like(x)
    zi = np.zeros(2)
    for i in range(0, len(x), block):
        fc = float(np.clip(cutoff[i], 40.0, sr * 0.45))
        w = 2 * math.pi * fc / sr
        alpha = math.sin(w) / (2 * q)
        cw = math.cos(w)
        b = np.array([(1 - cw) / 2, 1 - cw, (1 - cw) / 2])
        a = np.array([1 + alpha, -2 * cw, 1 - alpha])
        seg, zi = lfilter(b / a[0], a / a[0], x[i:i + block], zi=zi)
        out[i:i + block] = seg
    return out


def render_lead(notes: Iterable[Note], sample_rate: int = 44100, *,
                patch: LeadPatch = DEFAULT_PATCH, tail_seconds: float = 1.0) -> np.ndarray:
    """Render ``notes`` to a ``(2, N)`` float32 buffer."""
    notes = [n for n in notes if n.end > n.start]
    if not notes:
        return np.zeros((2, 0), dtype=np.float32)
    sr = sample_rate
    total = int((max(n.end for n in notes) + patch.release + tail_seconds) * sr)
    out_l = np.zeros(total)
    out_r = np.zeros(total)
    detune = 2.0 ** (patch.detune_cents / 1200.0)

    for phrase in _segments(notes, patch):
        start = int(phrase[0].start * sr)
        end = min(total, int((phrase[-1].end + patch.release) * sr))
        n = end - start
        if n <= 0:
            continue
        t = np.arange(n) / sr
        # Pitch curve with glide between the phrase's notes, plus held-note vibrato.
        pitch = np.full(n, float(phrase[0].pitch))
        note_start = np.zeros(n)           # time since the current note began
        vel = np.full(n, phrase[0].velocity / 127.0)
        prev = float(phrase[0].pitch)
        for k, note in enumerate(phrase):
            a = max(0, int(note.start * sr) - start)
            b = n if k == len(phrase) - 1 else max(a, int(phrase[k + 1].start * sr) - start)
            seg_t = np.arange(b - a) / sr
            target = float(note.pitch)
            if k:
                pitch[a:b] = target + (prev - target) * np.exp(-seg_t / max(patch.glide / 3, 1e-4))
            else:
                pitch[a:b] = target
            note_start[a:b] = seg_t
            vel[a:b] = note.velocity / 127.0
            prev = target
        ramp = np.clip((note_start - patch.vibrato_delay) / 0.25, 0.0, 1.0)
        pitch = pitch + ramp * (patch.vibrato_cents / 100.0) * np.sin(2 * math.pi * patch.vibrato_rate * t)
        freq = _hz(pitch)

        dt1 = freq * detune / sr
        dt2 = freq / detune / sr
        dt_sub = freq * 0.5 / sr
        saw1 = _blep_saw(np.cumsum(dt1), dt1)
        saw2 = _blep_saw(np.cumsum(dt2) + 0.37, dt2)
        sub_phase = np.cumsum(dt_sub)
        square = _blep_saw(sub_phase, dt_sub) - _blep_saw(sub_phase + 0.5, dt_sub)
        dt_p = freq / sr
        p_phase = np.cumsum(dt_p) + 0.13
        pulse = (_blep_saw(p_phase, dt_p) - _blep_saw(p_phase + patch.pulse_width, dt_p)) * 0.5

        # Amp envelope: one attack per phrase (legato notes don't retrigger).
        gate_len = int((phrase[-1].end - phrase[0].start) * sr)
        env = np.full(n, patch.sustain)
        att = max(1, int(patch.attack * sr))
        dec = max(1, int(patch.decay * sr))
        env[:att] = np.linspace(0.0, 1.0, att)
        d_end = min(n, att + dec)
        env[att:d_end] = patch.sustain + (1 - patch.sustain) * np.exp(-4.0 * np.arange(d_end - att) / dec)
        if gate_len < n:
            level = env[min(gate_len, n - 1)]
            rel = n - gate_len
            env[gate_len:] = level * np.exp(-6.9 * np.arange(rel) / max(1, int(patch.release * sr)))

        # Filter: opens on each attack (each note if retrigger_filter), settles,
        # tracks the pitch.
        since = note_start if patch.retrigger_filter else t
        f_env = np.exp(-since / max(patch.cutoff_decay, 1e-3))
        key = (freq / 440.0) ** patch.cutoff_keytrack
        cutoff = (patch.cutoff + patch.cutoff_env * f_env * (0.5 + 0.5 * vel)) * key

        amp = env * (0.55 + 0.45 * vel)
        common = patch.sub_level * square + patch.pulse_level * pulse
        if patch.noise_level:
            common = common + patch.noise_level * np.random.default_rng(start).standard_normal(n) * (0.4 + 0.6 * vel)
        sl = patch.saw_level
        left = _lowpass_blocks(sl * (saw1 * 0.6 + saw2 * 0.4) + common, cutoff, patch.resonance, sr, block=32)
        right = _lowpass_blocks(sl * (saw1 * 0.4 + saw2 * 0.6) + common, cutoff, patch.resonance, sr, block=32)
        out_l[start:end] += np.tanh(patch.drive * left) / math.tanh(patch.drive) * 0.6 * amp
        out_r[start:end] += np.tanh(patch.drive * right) / math.tanh(patch.drive) * 0.6 * amp

    return np.vstack([out_l, out_r]).astype(np.float32)
