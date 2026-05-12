"""
Song-level composition: sections, modulations, dynamics, fills.

A SongSpec describes a full multi-section song in YAML. The renderer
walks each Section in order and lays down chord/bass/melody/drum content
onto a single MidiExporter using ``bar_offset``. Each section can override
the base style: progression, key, scale, voicing, patterns, swing,
density, tempo_mod, track subset, fill.

See ``data/song_specs/*.yaml`` for worked examples.
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from .midi_export import MidiExporter
from .styles import STYLES, StylePreset


VALID_TRACKS = {"chords", "bass", "melody", "drums"}


@dataclass
class Section:
    """One section of a song (intro, verse, chorus, bridge, outro, etc.)."""

    name: str
    bars: int
    progression: Optional[list[str]] = None
    key: Optional[str] = None
    scale: Optional[str] = None
    voicing: Optional[str] = None
    bass_pattern: Optional[str] = None
    drum_pattern: Optional[str] = None
    swing: Optional[float] = None
    tempo_mod: float = 1.0        # applied globally post-render isn't supported — per-section tempo would require multi-tempo MIDI
    density: float = 1.0
    tracks: Optional[list[str]] = None
    melody_octave: Optional[int] = None
    chord_rhythm: Optional[str] = None
    melody_style: Optional[str] = None
    fill_at: Optional[str] = None  # None | "start" | "end" | "both"
    fade: bool = False
    accent_in: bool = False        # crash+kick+snare on the section's downbeat
    harmony: int = 0               # 0=solo, 2=duet (+3rd), 3=trio (+3rd, +5th)
    harmony_style: str = "follow"  # follow | accents | oohs | abba | queen | boston | journey | elton | chicago
    # Extra tracks layered on top of the primary bass/chord/melody:
    extra_basses: Optional[list[dict]] = None   # list of {pattern, track_name, program}
    lead_parts: Optional[list[dict]] = None     # list of {pattern, track_name, program}
    # Theme/leitmotif — name of an entry in midi_export.THEMES (e.g. "hit_the_sack")
    # Renders as its own "Theme" track on top of melody/chords.
    theme: Optional[str] = None
    theme_octave: Optional[int] = None
    theme_program: Optional[int] = None
    theme_track_name: Optional[str] = None
    # Free-form list of additional tracks. Each entry is a dict with at least:
    #   {type: "chord"|"bass"|"melody"|"drums"|"lead"|"theme", track_name: str, ...}
    # Plus per-type params accepted by the matching MidiExporter.add_* method.
    # Unset params fall back to the section/preset/spec values via _resolve().
    # This is the path the new Compose-Song UI uses; legacy fields (tracks,
    # extra_basses, lead_parts, theme) keep working for old YAML specs.
    custom_tracks: Optional[list[dict]] = None


@dataclass
class SongSpec:
    """A full song description."""

    title: str
    style: str
    key: str
    tempo: float
    sections: list[Section]
    seed: Optional[int] = None
    include_melody: bool = True
    scale: Optional[str] = None        # override style scale globally
    time_signature: tuple = (4, 4)     # (num, den); only 4/4, 3/4, 6/8 supported today


def load_spec(path: str | Path) -> SongSpec:
    """Load a SongSpec from a YAML file."""
    with open(path, "r") as f:
        data = yaml.safe_load(f)

    sections_data = data.pop("sections", [])
    sections = [Section(**s) for s in sections_data]
    return SongSpec(sections=sections, **data)


def _resolve(section: Section, spec: SongSpec, preset: StylePreset) -> dict:
    """Resolve section/spec/preset values into a concrete per-section config."""
    return {
        "key": section.key or spec.key,
        "scale": section.scale or spec.scale or preset.scale,
        "progression": section.progression or preset.progression,
        "voicing": section.voicing or preset.voicing,
        "bass_pattern": section.bass_pattern or preset.bass_pattern,
        "drum_pattern": section.drum_pattern or preset.drum_pattern,
        "swing": section.swing if section.swing is not None else preset.swing,
        "density": section.density,
        # tracks=None  -> all four primary tracks (legacy default).
        # tracks=[]    -> no primary tracks (freeform: only custom_tracks render).
        # tracks=[...] -> explicit subset.
        "tracks": set(section.tracks) if section.tracks is not None else VALID_TRACKS,
        "melody_octave": section.melody_octave or preset.melody_octave,
        "chord_rhythm": section.chord_rhythm or preset.chord_rhythm,
        "melody_style": section.melody_style or preset.melody_style,
    }


def _render_custom_track(midi: MidiExporter, tr: dict, cfg: dict,
                         sec_bars: int, bar_cursor: int,
                         seed_cursor: Optional[int],
                         preset: StylePreset,
                         section_index: int = 0) -> None:
    """Render one entry from Section.custom_tracks onto the MidiExporter.

    Falls back to section / preset values for any param the track dict omits,
    so a freeform track only needs to specify what differs from the preset.

    Melody and lead tracks use seed_cursor + section_index so each section
    gets a distinct phrase even when the same track plays through the whole
    song — matches the legacy primary-track render's seed convention.
    """
    ttype = tr.get("type")
    if not ttype:
        return
    name = tr.get("track_name", ttype.title())
    melody_seed = ((seed_cursor + section_index)
                   if seed_cursor is not None else None)
    if ttype == "chord":
        midi.add_chord_progression(
            key=tr.get("key", cfg["key"]),
            progression=tr.get("progression", cfg["progression"]),
            bars=sec_bars,
            octave=tr.get("octave", preset.chord_octave),
            scale_name=tr.get("scale", cfg["scale"]),
            voicing=tr.get("voicing", cfg["voicing"]),
            program=tr.get("program", preset.chord_program),
            track_name=name,
            bar_offset=bar_cursor,
            rhythm=tr.get("chord_rhythm", cfg["chord_rhythm"]),
            swing=tr.get("swing", cfg["swing"]),
        )
    elif ttype == "bass":
        midi.add_bass_line(
            key=tr.get("key", cfg["key"]),
            progression=tr.get("progression", cfg["progression"]),
            bars=sec_bars,
            octave=tr.get("octave", preset.bass_octave),
            pattern=tr.get("pattern", cfg["bass_pattern"]),
            scale_name=tr.get("scale", cfg["scale"]),
            swing=tr.get("swing", cfg["swing"]),
            program=tr.get("program", preset.bass_program),
            track_name=name,
            bar_offset=bar_cursor,
            density=tr.get("density", cfg["density"]),
            seed=seed_cursor,
        )
    elif ttype == "melody":
        midi.add_melody(
            key=tr.get("key", cfg["key"]),
            scale_name=tr.get("scale", cfg["scale"]),
            bars=sec_bars,
            octave=tr.get("octave", cfg["melody_octave"]),
            seed=melody_seed,
            swing=tr.get("swing", cfg["swing"]),
            program=tr.get("program", preset.melody_program),
            track_name=name,
            bar_offset=bar_cursor,
            density=tr.get("density", cfg["density"]),
            progression=tr.get("progression", cfg["progression"]),
            melody_style=tr.get("melody_style", cfg["melody_style"]),
        )
    elif ttype == "drums":
        midi.add_drum_pattern(
            pattern=tr.get("pattern", cfg["drum_pattern"]),
            bars=sec_bars,
            swing=tr.get("swing", cfg["swing"]),
            track_name=name,
            bar_offset=bar_cursor,
            density=tr.get("density", cfg["density"]),
            seed=seed_cursor,
        )
    elif ttype == "lead":
        midi.add_lead_line(
            key=tr.get("key", cfg["key"]),
            progression=tr.get("progression", cfg["progression"]),
            bars=sec_bars,
            octave=tr.get("octave", 4),
            pattern=tr.get("pattern", "clinton_synth"),
            scale_name=tr.get("scale", cfg["scale"]),
            swing=tr.get("swing", cfg["swing"]),
            program=tr.get("program", 82),
            track_name=name,
            bar_offset=bar_cursor,
            density=tr.get("density", cfg["density"]),
            seed=seed_cursor,
        )
    elif ttype == "theme":
        theme_name = tr.get("theme") or tr.get("name")
        if not theme_name:
            return
        midi.add_theme(
            theme_name=theme_name,
            key=tr.get("key", cfg["key"]),
            scale_name=tr.get("scale", cfg["scale"]),
            bars=sec_bars,
            octave=tr.get("octave", cfg["melody_octave"]),
            bar_offset=bar_cursor,
            program=tr.get("program", preset.melody_program),
            track_name=name if name != "Theme" else "Theme",
            swing=tr.get("swing", cfg["swing"]),
        )
    # Unknown types are silently ignored — UI prevents picking them.


def render(spec: SongSpec) -> MidiExporter:
    """Build a MidiExporter with every section laid down in sequence."""
    if spec.style not in STYLES:
        raise ValueError(f"Unknown style '{spec.style}'. Choose from: {list(STYLES)}")
    preset = STYLES[spec.style]
    ts = tuple(spec.time_signature) if spec.time_signature else (4, 4)
    midi = MidiExporter(tempo=spec.tempo, time_signature=ts)

    bar_cursor = 0
    seed_cursor = spec.seed

    for i, section in enumerate(spec.sections):
        cfg = _resolve(section, spec, preset)
        sec_bars = section.bars

        # Pre-section fill (drop in the PREVIOUS section's final bar)
        if section.fill_at in ("start", "both") and bar_cursor > 0:
            midi.add_drum_fill(
                bar_offset=bar_cursor - 1,
                length_bars=1.0,           # spans the full last bar; crash on next section downbeat
                intensity=1.1,
            )

        # Big downbeat accent for section entries that need to land hard
        if section.accent_in:
            midi.add_accent_hit(bar_offset=bar_cursor, velocity=118)

        # Chords
        if "chords" in cfg["tracks"]:
            midi.add_chord_progression(
                key=cfg["key"],
                progression=cfg["progression"],
                bars=sec_bars,
                octave=preset.chord_octave,
                scale_name=cfg["scale"],
                voicing=cfg["voicing"],
                program=preset.chord_program,
                track_name="Chords",
                bar_offset=bar_cursor,
                rhythm=cfg["chord_rhythm"],
                swing=cfg["swing"],
            )

        # Bass
        if "bass" in cfg["tracks"]:
            midi.add_bass_line(
                key=cfg["key"],
                progression=cfg["progression"],
                bars=sec_bars,
                octave=preset.bass_octave,
                pattern=cfg["bass_pattern"],
                scale_name=cfg["scale"],
                swing=cfg["swing"],
                program=preset.bass_program,
                track_name="Bass",
                bar_offset=bar_cursor,
                density=cfg["density"],
                seed=seed_cursor,
            )

        # Melody (only when enabled at spec level + primary "melody" listed).
        # The custom_tracks path renders any custom melody entries separately.
        custom_has_melody = any(
            t.get("type") == "melody" for t in (section.custom_tracks or [])
        )
        primary_melody_present = (spec.include_melody
                                  and "melody" in cfg["tracks"])
        # melody_present (used by harmony block) is the broader check.
        melody_present = (spec.include_melody
                          and ("melody" in cfg["tracks"] or custom_has_melody))
        if primary_melody_present:
            midi.add_melody(
                key=cfg["key"],
                scale_name=cfg["scale"],
                bars=sec_bars,
                octave=cfg["melody_octave"],
                seed=(seed_cursor + i) if seed_cursor is not None else None,
                swing=cfg["swing"],
                program=preset.melody_program,
                track_name="Melody",
                bar_offset=bar_cursor,
                density=cfg["density"],
                progression=cfg["progression"],
                melody_style=cfg["melody_style"],
            )

        # Extra bass layers (Flea, Geddy, Bootsy) — independent of melody
        for extra in (section.extra_basses or []):
            midi.add_bass_line(
                key=cfg["key"],
                progression=cfg["progression"],
                bars=sec_bars,
                octave=extra.get("octave", preset.bass_octave),
                pattern=extra["pattern"],
                scale_name=cfg["scale"],
                swing=cfg["swing"],
                program=extra.get("program", preset.bass_program),
                track_name=extra.get("track_name", f"Bass {extra['pattern']}"),
                bar_offset=bar_cursor,
                density=cfg["density"],
                seed=seed_cursor,
            )

        # Lead instrument parts (synth, guitar) — independent of melody
        for lead in (section.lead_parts or []):
            midi.add_lead_line(
                key=cfg["key"],
                progression=cfg["progression"],
                bars=sec_bars,
                octave=lead.get("octave", 4),
                pattern=lead["pattern"],
                scale_name=cfg["scale"],
                swing=cfg["swing"],
                program=lead.get("program", 82),
                track_name=lead.get("track_name", f"Lead {lead['pattern']}"),
                bar_offset=bar_cursor,
                density=cfg["density"],
                seed=seed_cursor,
            )

        # Theme / leitmotif — independent of melody, can run even when
        # include_melody=False (chill backing tracks still want a brief motif).
        if section.theme:
            midi.add_theme(
                theme_name=section.theme,
                key=cfg["key"],
                scale_name=cfg["scale"],
                bars=sec_bars,
                octave=section.theme_octave or cfg["melody_octave"],
                bar_offset=bar_cursor,
                program=section.theme_program if section.theme_program is not None
                        else preset.melody_program,
                track_name=section.theme_track_name or "Theme",
                swing=cfg["swing"],
            )

        # Drums
        if "drums" in cfg["tracks"]:
            midi.add_drum_pattern(
                pattern=cfg["drum_pattern"],
                bars=sec_bars,
                swing=cfg["swing"],
                track_name="Drums",
                bar_offset=bar_cursor,
                density=cfg["density"],
                seed=seed_cursor,
            )

        # Free-form custom tracks (the new Compose-Song UI populates this).
        for tr in (section.custom_tracks or []):
            _render_custom_track(
                midi, tr, cfg, sec_bars, bar_cursor, seed_cursor, preset,
                section_index=i,
            )

        # Optional parallel harmony lines — run AFTER both primary and custom
        # melody renders so the source Melody track is populated.
        if melody_present and section.harmony >= 2:
            intervals = [1] if section.harmony == 2 else [1, 2]
            midi.add_harmony(
                source_track="Melody",
                intervals_steps=intervals,
                key=cfg["key"],
                scale_name=cfg["scale"],
                bar_start=bar_cursor,
                bar_end=bar_cursor + sec_bars,
                program=preset.melody_program,
                style=section.harmony_style,
                progression=cfg["progression"],
            )

        # End-of-section fill (lands on the last bar of this section
        # so the crash hits the downbeat of the NEXT section)
        if section.fill_at in ("end", "both"):
            midi.add_drum_fill(
                bar_offset=bar_cursor + sec_bars - 1,
                length_bars=1.0,           # full last bar; crash lands on next section downbeat
                intensity=1.1,
            )

        # Fade: taper this section's last portion
        if section.fade:
            midi.fade_out(
                from_bar=bar_cursor,
                to_bar=bar_cursor + sec_bars,
            )

        bar_cursor += sec_bars

    return midi


def total_bars(spec: SongSpec) -> int:
    return sum(s.bars for s in spec.sections)
