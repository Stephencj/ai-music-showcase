"""Score a video chapter by chapter.

A product video isn't cut to a beat, so one fixed tempo drifts off its
chapters. Each chapter is composed as its own segment at a tempo nudged
around ``base_tempo`` so the chapter spans a whole number of bars: the next
chapter starts exactly on a downbeat. Segments are merged into one score
(notes in seconds) and rendered once, so the mix and master are continuous.

Only the first chapter gets an intro (drums build into the band riff over its
title card); after that each chapter flows straight into its groove on its
downbeat, and the section change carries the transition. Keys and the lead
instrument can change per chapter.

Hits are curated to be musical, not one per caption: none right at a chapter
change (the downbeat already marks it), not the first caption after a
chapter starts, and at least ``min_gap`` seconds apart. In "groove" style they
land on the next beat inside the groove rather than stopping the band.
"""

from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np

logger = logging.getLogger(__name__)

MAX_TEMPO_NUDGE = 0.08          # most a chapter's tempo may move from base_tempo


@dataclass
class Chapter:
    start: float                        # seconds into the video
    card: float = 0.0                   # title card length at the start (0 = none)
    roles: tuple[str, ...] = ("verse",)  # what the demo plays, split evenly
    key: Optional[str] = None
    lead: str = "synth_lead"            # lead instrument id ("synth_lead" | "lead_guitar")
    label: str = ""
    intro: Optional[bool] = None        # title-card intro; None = only the first chapter
    # Explicit sections (a transcribed form): [{"role", "bars", "progression"?, "label"?}].
    # Used as-is at the base tempo; only for a single-chapter score.
    sections: Optional[list] = None


@dataclass
class SegmentPlan:
    index: int
    start: float
    end: float
    tempo: float
    bars: int
    sections: list[dict] = field(default_factory=list)


def choose_bars(lengths: list[float], base_tempo: float, max_nudge: float = 0.08) -> list[int]:
    """Bars per chapter so neighbouring chapters' tempos stay close.

    Each chapter may take any bar count that keeps it within ``max_nudge`` of
    ``base_tempo``; a small dynamic programme picks the sequence that
    minimises the squared tempo jumps between neighbours plus a lighter pull
    towards the base tempo.
    """
    options = []
    for length in lengths:
        lo = max(1, int(np.floor(length * base_tempo * (1 - max_nudge) / 240.0)))
        hi = max(lo, int(np.ceil(length * base_tempo * (1 + max_nudge) / 240.0)))
        opts = [n for n in range(lo, hi + 1)
                if abs(240.0 * n / length / base_tempo - 1) <= max_nudge] or [max(1, round(length * base_tempo / 240.0))]
        options.append(opts)
    tempo = lambda i, n: 240.0 * n / lengths[i]
    cost = [{n: 0.3 * (tempo(0, n) - base_tempo) ** 2 for n in options[0]}]
    back = [{}]
    for i in range(1, len(lengths)):
        cost.append({}); back.append({})
        for n in options[i]:
            prev = min(options[i - 1], key=lambda m: cost[i - 1][m] + (tempo(i, n) - tempo(i - 1, m)) ** 2)
            cost[i][n] = (cost[i - 1][prev] + (tempo(i, n) - tempo(i - 1, prev)) ** 2
                          + 0.3 * (tempo(i, n) - base_tempo) ** 2)
            back[i][n] = prev
    n = min(cost[-1], key=cost[-1].get)
    out = [n]
    for i in range(len(lengths) - 1, 0, -1):
        n = back[i][n]
        out.append(n)
    return out[::-1]


LATE_SLACK = 0.5           # a chapter's downbeat may land this much after its cut...
EARLY_SLACK = 0.2          # ...or this much before it


def plan_timing(starts: list[float], duration: float, base_tempo: float, *,
                max_nudge: float = MAX_TEMPO_NUDGE, late: float = LATE_SLACK,
                early: float = EARLY_SLACK) -> list[tuple[float, float, int, float]]:
    """(music start, music end, bars, tempo) per chapter.

    Exact downbeats on every cut would need big tempo jumps when bars are long
    (slow tempos), so each chapter boundary may land a little late (or a touch
    early) and the tempo stays steady. A dynamic programme over (boundary
    offset, tempo) minimises tempo jumps, distance from the base tempo and
    boundary error together. The last chapter (an end card) keeps the
    previous tempo and lets its final hit ring out.
    """
    k = len(starts)
    bounds = [0.0] + list(starts[1:])               # video times of chapter starts
    tempos = np.arange(base_tempo * (1 - max_nudge), base_tempo * (1 + max_nudge) + 1e-9, 0.25)
    offsets = np.round(np.arange(-early, late + 1e-9, 0.02), 2)
    # state: (offset index, tempo index) at the start of chapter i
    INF = float("inf")
    cost = {(int(np.argmin(abs(offsets))), None): 0.0}
    back: list[dict] = []
    for i in range(k - 1):
        length_target = bounds[i + 1] - bounds[i]
        nxt: dict = {}
        bk: dict = {}
        for (oi, ti), c0 in cost.items():
            m_start = bounds[i] + offsets[oi]
            for tj, t in enumerate(tempos):
                bar = 240.0 / t
                for n in {max(1, int(np.floor((length_target - offsets[oi]) / bar))),
                          max(1, int(np.ceil((length_target - offsets[oi]) / bar)))}:
                    m_end = m_start + n * bar
                    off = m_end - bounds[i + 1]
                    if off < -early - 1e-9 or off > late + 1e-9:
                        continue
                    oj = int(np.argmin(abs(offsets - off)))
                    jump = 0.0 if ti is None else (t - tempos[ti]) ** 2
                    c = c0 + jump + 0.3 * (t - base_tempo) ** 2 + 60.0 * off ** 2
                    key = (oj, tj)
                    if c < nxt.get(key, INF):
                        nxt[key] = c
                        bk[key] = ((oi, ti), n, float(t), float(m_start), float(m_end))
        if not nxt:                                  # no fit within the slack: fall back to exact fits
            return [(s0, e, n, 240.0 * n / (e - s0)) for (s0, e), n in zip(
                [(bounds[j], bounds[j + 1] if j + 1 < k else duration) for j in range(k)],
                choose_bars([(bounds[j + 1] if j + 1 < k else duration) - bounds[j] for j in range(k)],
                            base_tempo, max_nudge))]
        cost = nxt
        back.append(bk)
    plan: list[tuple[float, float, int, float]] = []
    state = min(cost, key=cost.get) if back else None
    for bk in reversed(back):
        prev, n, t, m_start, m_end = bk[state]
        plan.append((m_start, m_end, n, t))
        state = prev
    plan.reverse()
    # Lay the chosen bars/tempos end to end so the music is seamless (the
    # programme's offsets are rounded to 20 ms).
    t0, seamless = 0.0, []
    for _, _, n, t in plan:
        seamless.append((t0, t0 + n * 240.0 / t, n, t))
        t0 = seamless[-1][1]
    plan = seamless
    tail_start = plan[-1][1] if plan else 0.0
    tail_tempo = plan[-1][3] if plan else base_tempo
    remaining = max(duration - tail_start, 0.1)
    n = max(1, int(np.floor(remaining * tail_tempo / 240.0 + 0.15)))
    plan.append((tail_start, min(duration, tail_start + n * 240.0 / tail_tempo), n, tail_tempo))
    return plan


def _explicit_plan(ch: Chapter, tempo: float) -> SegmentPlan:
    """A single chapter laid out exactly as its explicit sections say."""
    pos, sections = 0, []
    for k, sec in enumerate(ch.sections or []):
        n = int(sec.get("bars", 0))
        if n <= 0:
            continue
        s = {"start_bar": pos, "end_bar": pos + n - 1, "role": sec.get("role", "verse"),
             "label": sec.get("label") or f"Section {k + 1}"}
        if sec.get("progression"):
            s["progression"] = list(sec["progression"])
        if ch.key:
            s["key"] = ch.key
        sections.append(s)
        pos += n
    return SegmentPlan(0, 0.0, pos * 240.0 / tempo, tempo, pos, sections)


def plan_segments(chapters: list[Chapter], duration: float, base_tempo: float) -> list[SegmentPlan]:
    """Bars and tempo per chapter, and its section list (bar ranges)."""
    chapters = sorted(chapters, key=lambda c: c.start)
    if len(chapters) == 1 and chapters[0].sections:
        return [_explicit_plan(chapters[0], base_tempo)]
    timing = plan_timing([c.start for c in chapters], duration, base_tempo)
    plans = []
    for i, ch in enumerate(chapters):
        start, end, bars, tempo = timing[i]
        if end - start <= 0:
            continue
        bar = 240.0 / tempo
        card_bars = 0
        wants_intro = ch.intro if ch.intro is not None else i == 0
        if wants_intro and ch.card > 0 and bars >= 2:
            card_bars = int(np.clip(round((ch.card + (ch.start - start)) / bar), 1, bars - 1))
        sections = []
        label = ch.label or f"Chapter {i + 1}"
        pos = 0
        if card_bars:
            sections.append({"start_bar": 0, "end_bar": card_bars - 1, "label": "Title", "role": "intro"})
            pos = card_bars
        rest = bars - pos
        roles = list(ch.roles) or ["verse"]
        roles = roles[:max(1, rest)]
        for k, role in enumerate(roles):
            n = rest // len(roles) + (1 if k < rest % len(roles) else 0)
            if n <= 0:
                continue
            sections.append({"start_bar": pos, "end_bar": pos + n - 1,
                             "label": f"{label} {role.title()}", "role": role})
            pos += n
        if ch.key:
            for s in sections:
                s["key"] = ch.key
        plans.append(SegmentPlan(i, start, end, tempo, bars, sections))
    return plans


def curate_hits(hits: list[float], chapter_starts: list[float], *, min_gap: float = 3.0,
                settle: float = 1.6) -> list[float]:
    """Musical hit points from raw ones (captions, cards): drop any within
    ``settle`` seconds of a chapter change, the first one after each chapter
    starts, and any closer than ``min_gap`` to the previous kept hit."""
    starts = sorted(chapter_starts)
    kept: list[float] = []
    first_seen: set[int] = set()
    for h in sorted(set(hits)):
        chapter = max((i for i, s in enumerate(starts) if s <= h + 1e-6), default=-1)
        if any(abs(h - s) < settle for s in starts):
            continue
        if chapter not in first_seen:
            first_seen.add(chapter)                  # let the chapter settle in first
            continue
        if kept and h - kept[-1] < min_gap:
            continue
        kept.append(h)
    return kept


def compose_score(chapters: list[Chapter], *, duration: float, hits: list[float],
                  genre: str = "funk_fusion_full", seed: int = 52, base_tempo: float = 158.0,
                  band: Optional[list[str]] = None, lead_voice: Optional[str] = None,
                  hit_style: str = "groove", curate: bool = True, min_gap: float = 3.0,
                  offset: float = 0.0, stops: Optional[list] = None, arrangement: str = "",
                  progress: Optional[Callable[[str, float], None]] = None):
    """``offset``: where music time 0 sits in the video (negative = the music
    starts before the video, e.g. a pickup into a downbeat). ``hits`` and
    ``stops`` are in video time."""
    """Compose every chapter and merge them into one MidiExporter (seconds)."""
    import pretty_midi
    from src.composition.song_composer import compose_song
    from src.daw_integration.generic.midi_export import MidiExporter, NoteEvent
    from src.daw_integration.generic.styles import STYLES

    preset = STYLES[genre]
    band = list(band or [i for i in preset.default_instruments if i not in ("synth_lead", "lead_guitar", "sax_alto")])
    plans = plan_segments(chapters, duration, base_tempo)
    hits = [h - offset for h in hits]
    stops = [(a - offset, b - offset) for a, b in (stops or [])]
    if curate:
        hits = curate_hits(hits, [p.start for p in plans] + [c.start - offset for c in chapters], min_gap=min_gap)
    tracks: dict[tuple[str, int, bool], list] = {}
    ordered = sorted(chapters, key=lambda c: c.start)
    for plan in plans:
        ch = ordered[plan.index]
        if progress:
            progress(f"Composing chapter {plan.index + 1} of {len(plans)}…", 0.05 + 0.4 * plan.index / max(1, len(plans)))
        with tempfile.TemporaryDirectory() as td:
            res = compose_song(
                genre=genre, sections=plan.sections, seed=seed, tempo=plan.tempo,
                key=ch.key, enabled_instruments=tuple(band + [ch.lead]),
                hits=[h - plan.start for h in hits if h - plan.start >= 0],
                stops=[(a - plan.start, b - plan.start) for a, b in stops if b - plan.start > 0],
                lead_voice=lead_voice, hit_style=hit_style, arrangement=arrangement,
                output_dir=Path(td), skip_audio=True,
            )
            pm = pretty_midi.PrettyMIDI(res["midi_path"])
        for inst in pm.instruments:
            k = (inst.name, int(inst.program), bool(inst.is_drum))
            bucket = tracks.setdefault(k, [])
            for n in inst.notes:
                if n.start >= plan.end - plan.start + 0.02 and not inst.is_drum:
                    continue
                start = float(n.start) + plan.start + offset
                end = float(n.end) + plan.start + offset
                if end <= 0:
                    continue                        # before the video starts
                bucket.append(NoteEvent(pitch=int(n.pitch), start=max(0.0, start), end=end,
                                        velocity=int(n.velocity)))
    midi = MidiExporter(tempo=base_tempo, time_signature=preset.time_signature)
    for (name, program, is_drum), notes in tracks.items():
        if notes:
            midi.add_notes(sorted(notes, key=lambda n: n.start), track_name=name, program=program, is_drum=is_drum)
    return midi, plans, [h + offset for h in hits]


def gate_stops(audio: np.ndarray, sample_rate: int, stops: list[tuple[float, float]], *,
               fade_out: float = 0.006, fade_in: float = 0.004) -> np.ndarray:
    """Hard band stops in the finished mix: silence inside each (start, end)
    window — tails and reverb included, like an edit — with short fades so
    the cuts don't click."""
    out = audio.copy()
    n = out.shape[1]
    for a, b in stops:
        i0, i1 = int(round(a * sample_rate)), int(round(b * sample_rate))
        if i1 <= 0 or i0 >= n or i1 <= i0:
            continue
        fo, fi = int(fade_out * sample_rate), int(fade_in * sample_rate)
        lo = max(0, i0 - fo)
        if i0 > lo:
            out[:, lo:i0] *= np.linspace(1.0, 0.0, i0 - lo, dtype=out.dtype)
        out[:, max(0, i0):min(n, i1)] = 0.0
        hi = min(n, i1 + fi)
        if hi > i1:
            out[:, i1:hi] *= np.linspace(0.0, 1.0, hi - i1, dtype=out.dtype)
    return out


def fit_to_length(audio: np.ndarray, sample_rate: int, length: float, *, fade: float = 0.45) -> np.ndarray:
    """Pad or cut ``(2, N)`` audio to exactly ``length`` seconds, fading the end."""
    n = int(round(length * sample_rate))
    if audio.shape[1] < n:
        audio = np.concatenate([audio, np.zeros((audio.shape[0], n - audio.shape[1]), dtype=audio.dtype)], axis=1)
    audio = audio[:, :n].copy()
    k = min(int(fade * sample_rate), n)
    if k:
        audio[:, -k:] *= np.linspace(1.0, 0.0, k, dtype=audio.dtype) ** 2
    return audio
