"""
Concatenate saved blocks into a single PrettyMIDI.

The Compose Song tab provides a timeline of ``{block_name, repeat}`` entries.
This module loads each block, time-shifts its notes by the running cursor,
and inserts tempo + time-signature change events at each block boundary so
the heterogeneous blocks (different tempos, different meters) play exactly
as they were rendered.

Smart instrument merging:
  - Two blocks' instruments collapse into one output instrument when they
    share (name, GM program, is_drum).
  - Same name + different program → disambiguate with a ``" (alt)"`` suffix
    on the second one's name (and ``" (alt 2)"``, ``" (alt 3)"``, etc.).
  - Drums merge cleanly (channel-9 is reassigned by pretty_midi at write).

Melody-plan override:
  - If a sibling ``{block_name}_melody.yaml`` exists alongside the block,
    its rendered melody track REPLACES the block's stored melody before
    concat, and any harmony track from the plan is appended as a new
    instrument. This is how Melody Studio edits propagate into rendered
    songs without rewriting block ``.mid`` files.
"""

from __future__ import annotations

import copy
import logging
from typing import Iterable, Optional

import pretty_midi

from . import blocks as _blocks
from . import melody_plan as _melody_plan

logger = logging.getLogger(__name__)


def _resolve_unique_name(base_name: str, existing: dict) -> str:
    """Return ``base_name`` if it isn't taken, else ``base_name (alt)`` / ``(alt 2)`` / ..."""
    if base_name not in existing:
        return base_name
    n = 1
    while True:
        candidate = f"{base_name} (alt)" if n == 1 else f"{base_name} (alt {n})"
        if candidate not in existing:
            return candidate
        n += 1


def _shifted_notes(inst: pretty_midi.Instrument,
                   time_offset: float) -> list[pretty_midi.Note]:
    out: list[pretty_midi.Note] = []
    for n in inst.notes:
        out.append(pretty_midi.Note(
            velocity=n.velocity,
            pitch=n.pitch,
            start=n.start + time_offset,
            end=n.end + time_offset,
        ))
    return out


def _merge_instruments(out: dict, src_pm: pretty_midi.PrettyMIDI,
                       time_offset: float) -> None:
    """Append (time-shifted) src instruments into the merge dict.

    `out` keys: (track_name_in_output, program, is_drum). Values: pretty_midi.Instrument.
    Same (name, program, is_drum) → merge notes. Same name + different program
    → new key with disambiguated name.
    """
    # Track names already present in `out` (regardless of program/drum) so we
    # can disambiguate quickly.
    name_to_keys: dict[str, list[tuple]] = {}
    for k in out.keys():
        name_to_keys.setdefault(k[0], []).append(k)

    for src in src_pm.instruments:
        merge_key = (src.name, int(src.program), bool(src.is_drum))
        if merge_key in out:
            # Identical track already in output → just append notes.
            out[merge_key].notes.extend(_shifted_notes(src, time_offset))
            continue

        # Same name but different program → pick a unique name.
        name = src.name or "unnamed"
        if name in name_to_keys:
            # Build a name-only collision view: any existing key with this name
            # but different (program, is_drum) means we need a new label.
            same_name_keys = name_to_keys[name]
            # Check if exact (name, program, is_drum) matches any existing
            if not any(k[1] == int(src.program) and k[2] == bool(src.is_drum)
                       for k in same_name_keys):
                name = _resolve_unique_name(
                    name,
                    {k[0]: True for k in out.keys()},
                )

        new_inst = pretty_midi.Instrument(
            program=int(src.program),
            is_drum=bool(src.is_drum),
            name=name,
        )
        new_inst.notes.extend(_shifted_notes(src, time_offset))
        new_key = (name, int(src.program), bool(src.is_drum))
        out[new_key] = new_inst
        name_to_keys.setdefault(name, []).append(new_key)


def _apply_melody_plan_to_block(
    pm_block: pretty_midi.PrettyMIDI,
    plan: _melody_plan.MelodyPlan,
    progression: Optional[list] = None,
) -> pretty_midi.PrettyMIDI:
    """Return a copy of ``pm_block`` whose Melody track is replaced by the
    plan's rendered output. If the plan has HarmonyTags, a Harmony track
    is appended too. Identifies the "melody track" by name (case-insensitive
    substring ``melody``) on non-drum instruments; if none exists, the
    plan's melody is appended as a new track without replacing anything.
    """
    new_pm = copy.deepcopy(pm_block)

    mel_track, harm_track = _melody_plan.render_melody_plan(
        plan, progression=progression,
    )

    # Drop existing melody track(s) — replace, don't layer
    new_pm.instruments = [
        i for i in new_pm.instruments
        if not (("melody" in (i.name or "").lower()) and not i.is_drum)
    ]

    if mel_track.notes:
        mel_inst = pretty_midi.Instrument(
            program=0, is_drum=False, name="Melody",
        )
        for n in mel_track.notes:
            mel_inst.notes.append(pretty_midi.Note(
                velocity=int(n.velocity), pitch=int(n.pitch),
                start=float(n.start), end=float(n.end),
            ))
        new_pm.instruments.append(mel_inst)

    if harm_track is not None and harm_track.notes:
        harm_inst = pretty_midi.Instrument(
            program=0, is_drum=False, name="Harmony",
        )
        for n in harm_track.notes:
            harm_inst.notes.append(pretty_midi.Note(
                velocity=int(n.velocity), pitch=int(n.pitch),
                start=float(n.start), end=float(n.end),
            ))
        new_pm.instruments.append(harm_inst)

    return new_pm


def _try_apply_sibling_melody_plan(
    block_name: str,
    pm_block: pretty_midi.PrettyMIDI,
    meta: dict,
) -> tuple[pretty_midi.PrettyMIDI, bool]:
    """Look for ``data/blocks/{name}_melody.yaml`` and, if present, apply
    it. Returns ``(pm, applied)``. Failures are swallowed so a broken plan
    file doesn't tank the whole concat — the original block flows through.
    """
    safe_name = _blocks._safe_name(block_name)
    yaml_path = _blocks.BLOCKS_DIR / f"{safe_name}_melody.yaml"
    if not yaml_path.exists():
        return pm_block, False
    try:
        plan = _melody_plan.from_yaml(yaml_path)
        progression = meta.get("progression")
        new_pm = _apply_melody_plan_to_block(pm_block, plan, progression)
        return new_pm, True
    except Exception:
        logger.exception(
            "block_concat: melody plan for %r failed to apply — "
            "falling back to block's stored melody", block_name,
        )
        return pm_block, False


def concat_blocks(timeline: Iterable[dict],
                  initial_tempo: float | None = None) -> tuple[pretty_midi.PrettyMIDI, dict]:
    """Concatenate the blocks listed in ``timeline`` into one PrettyMIDI.

    ``timeline`` is an iterable of dicts: ``{"block_name": str, "repeat": int}``.

    Returns ``(pm, info)`` where ``info`` summarizes the result for the UI.
    Skips entries whose block files have been deleted (logged silently).
    Raises ValueError if the timeline produces zero notes overall.
    """
    timeline_list = [t for t in timeline if t.get("block_name")]
    if not timeline_list:
        raise ValueError("Timeline is empty.")

    # Initial tempo: first entry's saved tempo, or fallback to caller-supplied.
    first = timeline_list[0]
    try:
        first_pm, first_meta = _blocks.load_block(first["block_name"])
    except FileNotFoundError:
        raise ValueError(
            f"Block {first['block_name']!r} is missing — refresh the library."
        )
    seed_tempo = float(first_meta.get("tempo") or initial_tempo or 120.0)

    out_pm = pretty_midi.PrettyMIDI(initial_tempo=seed_tempo)
    out_pm.time_signature_changes.clear()
    merged: dict = {}

    cursor = 0.0
    info_parts: list[str] = []
    last_tempo = None
    last_ts: tuple[int, int] | None = None

    for entry in timeline_list:
        name = entry["block_name"]
        # ``repeat`` may be fractional (<1 to shorten a block, e.g. 0.5 of an
        # 8-bar block = 4 bars) or whole (>=1 to loop). An explicit ``bars``
        # overrides it. We translate to a target bar count, then emit full
        # copies + a partial first-N-bars slice for any remainder.
        repeat = float(entry.get("repeat") or 1)
        try:
            pm_block, meta = _blocks.load_block(name)
        except FileNotFoundError:
            info_parts.append(f"⚠ skipped missing block {name!r}")
            continue

        # Apply sibling melody-plan override if present. This swaps the
        # block's stored melody track for the Studio-edited version
        # (and tacks on a Harmony track for any HarmonyTag in the plan)
        # before the rest of the concat machinery sees the block.
        pm_block, plan_applied = _try_apply_sibling_melody_plan(
            name, pm_block, meta,
        )

        block_tempo = float(meta.get("tempo") or pm_block.estimate_tempo())
        ts_meta = meta.get("time_signature") or [4, 4]
        ts = (int(ts_meta[0]), int(ts_meta[1]))
        block_dur = float(pm_block.get_end_time())
        block_bars = int(meta.get("bars") or 0)
        bar_sec = _bar_seconds(block_tempo, ts) if block_bars else block_dur

        # Resolve the target length in bars for this entry.
        if entry.get("bars"):
            target_bars = max(1, int(entry["bars"]))
        elif block_bars:
            target_bars = max(1, round(repeat * block_bars))
        else:
            target_bars = max(1, round(repeat))

        # Build the list of (pm, duration) units: N full copies + a partial.
        if block_bars:
            full, rem = divmod(target_bars, block_bars)
        else:
            full, rem = max(1, round(repeat)), 0
        units: list[tuple] = [(pm_block, block_bars * bar_sec if block_bars else block_dur)] * full
        if rem:
            sliced = slice_pm_by_bars(pm_block, 0, rem - 1, block_tempo, ts)
            units.append((sliced, rem * bar_sec))

        for unit_pm, unit_dur in units:
            # Time-signature change at this boundary.
            if last_ts != ts:
                out_pm.time_signature_changes.append(
                    pretty_midi.TimeSignature(ts[0], ts[1], cursor)
                )
                last_ts = ts

            # Tempo change at this boundary.
            if last_tempo != block_tempo:
                _append_tempo_change(out_pm, cursor, block_tempo)
                last_tempo = block_tempo

            _merge_instruments(merged, unit_pm, time_offset=cursor)
            cursor += unit_dur

        bars_label = meta.get("bars", "?")
        plan_tag = " 🎵" if plan_applied else ""
        info_parts.append(f"{name}→{target_bars}b (of {bars_label}){plan_tag}")

    if not merged:
        raise ValueError("Timeline produced zero notes — all blocks missing or empty.")

    out_pm.instruments.extend(merged.values())

    info = {
        "summary": " | ".join(info_parts),
        "duration_seconds": cursor,
        "n_instruments": len(out_pm.instruments),
        "n_notes": sum(len(i.notes) for i in out_pm.instruments),
    }
    return out_pm, info


def _append_tempo_change(pm: pretty_midi.PrettyMIDI,
                         time_seconds: float, tempo_bpm: float) -> None:
    """Append a tempo change to a PrettyMIDI's internal _tick_scales table.

    pretty_midi stores tempo as (tick, tick_scale) pairs. tick_scale is the
    seconds-per-tick value: 60.0 / (tempo * resolution).
    """
    resolution = pm.resolution
    tick = int(round(pm.time_to_tick(time_seconds)))
    tick_scale = 60.0 / (float(tempo_bpm) * resolution)
    # Avoid emitting a duplicate at the same tick.
    if pm._tick_scales and pm._tick_scales[-1][0] == tick:
        # Replace the last entry's scale.
        pm._tick_scales[-1] = (tick, tick_scale)
    else:
        pm._tick_scales.append((tick, tick_scale))
    # Refresh the tick→time cache.
    pm._update_tick_to_time(pm._tick_scales[-1][0] + 1)


# ---------------------------------------------------------------------------
# Splitting a rendered song back into per-section blocks (mix-and-match).
# ---------------------------------------------------------------------------

def _bar_seconds(tempo: float, time_signature: tuple[int, int]) -> float:
    """Seconds per bar at ``tempo`` (quarter-notes/min) in ``time_signature``.

    Uses the SAME meter convention the renderer lays bars with, so slice
    boundaries land exactly on bar lines: bar_in_quarters · 60/tempo.
    """
    from .midi_export import meter_info
    bar_in_quarters = meter_info((int(time_signature[0]), int(time_signature[1])))["bar_in_quarters"]
    return float(bar_in_quarters) * 60.0 / float(tempo)


def slice_pm_by_bars(pm: pretty_midi.PrettyMIDI, start_bar: int, end_bar: int,
                     tempo: float, time_signature: tuple[int, int]
                     ) -> pretty_midi.PrettyMIDI:
    """Return a new PrettyMIDI with only the notes that *start* within bars
    ``[start_bar, end_bar]`` (inclusive), shifted so the slice begins at
    t=0. Instrument program / name / drum-flag are preserved; notes that
    spill past the slice end are clamped to it."""
    spb = _bar_seconds(tempo, time_signature)
    t0 = start_bar * spb
    t1 = (end_bar + 1) * spb
    out = pretty_midi.PrettyMIDI(initial_tempo=float(tempo))
    out.time_signature_changes = [
        pretty_midi.TimeSignature(int(time_signature[0]), int(time_signature[1]), 0.0)
    ]
    for inst in pm.instruments:
        new_inst = pretty_midi.Instrument(
            program=int(inst.program), is_drum=bool(inst.is_drum),
            name=inst.name,
        )
        for n in inst.notes:
            if t0 <= n.start < t1:
                new_inst.notes.append(pretty_midi.Note(
                    velocity=int(n.velocity), pitch=int(n.pitch),
                    start=max(0.0, n.start - t0),
                    end=min(t1, n.end) - t0,
                ))
        if new_inst.notes:
            out.instruments.append(new_inst)
    return out


def split_into_section_blocks(pm: pretty_midi.PrettyMIDI, sections: Iterable[dict],
                              *, tempo: float, time_signature: tuple[int, int],
                              prefix: str = "", overwrite: bool = False,
                              tag: str | None = None,
                              spec_base: dict | None = None) -> list[str]:
    """Slice ``pm`` into one saved block per section so the parts can be
    mixed and matched on the Compose Song timeline.

    ``sections`` items are ``{"start_bar", "end_bar", "label", ...}`` — the
    same shape ``compose_song`` consumes. Empty (note-less) slices are
    skipped. Names collide-safely: ``"Verse"`` → ``"Verse 2"`` etc.
    Returns the list of block names actually written.
    """
    from . import blocks as _b
    existing = {b.get("name") for b in _b.list_blocks()}
    saved: list[str] = []
    for i, sec in enumerate(sections):
        s, e = int(sec["start_bar"]), int(sec["end_bar"])
        label = (sec.get("label") or f"Section {i + 1}").strip()
        sub = slice_pm_by_bars(pm, s, e, tempo, time_signature)
        if not sub.instruments:
            continue
        base = f"{prefix}{label}".strip() if prefix else label
        name = base
        n = 1
        # Names can be taken by files the listing skips (a sidecar with no
        # name, a half-deleted block), so check the files too.
        while not overwrite and (name in existing or _b._yaml_path(name).exists()
                                 or _b._midi_path(name).exists()):
            n += 1
            name = f"{base} {n}"
        try:
            # Each section block remembers the full generation spec plus
            # its own bar-range, so a single instrument can be regenerated
            # later (re-run the full song, slice to this section, splice).
            spec = None
            if spec_base is not None:
                spec = {**spec_base, "section": {"start_bar": s, "end_bar": e}}
            _b.save_block(name, sub, tempo=float(tempo),
                          time_signature=(int(time_signature[0]), int(time_signature[1])),
                          bars=e - s + 1, overwrite=overwrite,
                          spec=spec, tags=[tag] if tag else None)
            existing.add(name)
            saved.append(name)
        except (FileExistsError, ValueError) as exc:
            logger.warning("split_into_section_blocks: skipped %r (%s)", name, exc)
    return saved
