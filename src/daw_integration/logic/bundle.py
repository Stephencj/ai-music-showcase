"""Build a Logic-Pro-friendly export bundle.

Output layout::

    My_Logic_Bundle/
    ├── LOGIC_README.md         ← drag/drop instructions + instrument map
    ├── manifest.json
    ├── midi/
    │   ├── 01_Pop_Chords.mid
    │   ├── 02_Pop_Bass.mid
    │   └── ...                 ← per-track MIDI (one instrument per file)
    └── audio/                  ← present only if rendered stems passed in
        ├── Pop_Chords.wav
        └── ...

Logic accepts drag-and-drop of MIDI files onto the timeline, which auto-
creates Software-Instrument tracks. The recommended-instrument map in
``LOGIC_README.md`` gives Stephen the curated patch suggestions for each
track family (Alchemy presets for pads, Drum Kit Designer for drums,
Vintage Electric Piano for chords, etc.).

We deliberately don't try to forge a ``.logicx`` project file — Logic's
project format is closed, brittle, and version-dependent.
"""

from __future__ import annotations

import json
import logging
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import pretty_midi

from src.daw_integration.generic.midi_export import MidiExporter

from src.audio_processing.render.effects import classify_family

logger = logging.getLogger(__name__)


# Per-family Logic instrument suggestions. These are stable Logic patch
# names that ship with Logic Pro 10.7+; the user can swap them freely.
LOGIC_INSTRUMENT_SUGGESTIONS: dict[str, list[str]] = {
    "drums": [
        "Drum Kit Designer → SoCal",
        "Drum Kit Designer → East Bay",
        "Ultrabeat → Pop Hits",
    ],
    "bass": [
        "Bass → Vintage Bass → P-Bass Slap",
        "Bass → Vintage Bass → Fingered Studio",
        "Alchemy → Bass → Sub Stack",
    ],
    "chords": [
        "Vintage Electric Piano → Suitcase Mk I",
        "Studio Piano → Steinway Grand",
        "Alchemy → Keys → Soft Wurly",
    ],
    "pad": [
        "Alchemy → Pads → Warm Analog",
        "Alchemy → Pads → Cinematic Strings",
        "Vintage Mellotron → Strings",
    ],
    "melody": [
        "Studio Strings → Violin Section",
        "Alchemy → Leads → Singing Saw",
        "Vintage Clav → Funky Clav",
    ],
    "lead": [
        "Alchemy → Leads → Big Synth Lead",
        "ES2 → Mod Lead",
        "Vintage Mellotron → Brass",
    ],
    "extra": [
        "Alchemy → Pads → Open Air",
        "Sampler → Pick a sample",
    ],
}


@dataclass
class LogicTrack:
    """One track in the bundle."""
    name: str
    program: int
    is_drum: bool
    family: str
    midi_filename: str
    audio_filename: Optional[str] = None


class LogicSessionBundle:
    """Assemble a Logic-friendly drag-and-drop bundle."""

    def __init__(
        self,
        bundle_name: str,
        *,
        tempo: float = 120.0,
        time_signature: tuple[int, int] = (4, 4),
        sample_rate: int = 44100,
    ):
        self.bundle_name = bundle_name
        self.tempo = float(tempo)
        self.time_signature = time_signature
        self.sample_rate = int(sample_rate)
        self.tracks: list[LogicTrack] = []
        self._per_track_pms: list[tuple[str, pretty_midi.PrettyMIDI]] = []
        self._stem_sources: dict[str, Path] = {}

    @classmethod
    def from_midi_exporter(
        cls,
        bundle_name: str,
        midi: MidiExporter,
        *,
        rendered_stems: Optional[dict[str, Path]] = None,
    ) -> "LogicSessionBundle":
        """Build a bundle directly from a :class:`MidiExporter`."""
        bundle = cls(
            bundle_name,
            tempo=midi.tempo,
            time_signature=midi.time_signature,
        )
        for track_name, pm in midi.iter_single_track_pms():
            inst = pm.instruments[0] if pm.instruments else None
            if inst is None or not inst.notes:
                continue
            family = classify_family(track_name, inst.program, inst.is_drum)
            bundle._per_track_pms.append((track_name, pm))
            bundle.tracks.append(LogicTrack(
                name=track_name,
                program=int(inst.program),
                is_drum=bool(inst.is_drum),
                family=family,
                midi_filename="",  # filled in at export
            ))
        if rendered_stems:
            bundle._stem_sources = {
                name: Path(p) for name, p in rendered_stems.items()
            }
        return bundle

    def export(self, output_dir: str | Path) -> Path:
        """Write the bundle to ``output_dir / <bundle_name>``.

        Returns the bundle directory.
        """
        output_dir = Path(output_dir)
        bundle_dir = output_dir / self.bundle_name.replace(" ", "_")
        midi_dir = bundle_dir / "midi"
        audio_dir = bundle_dir / "audio"
        midi_dir.mkdir(parents=True, exist_ok=True)

        # Per-track MIDI write
        for idx, ((track_name, pm), record) in enumerate(
            zip(self._per_track_pms, self.tracks), start=1
        ):
            safe_name = _safe_filename(track_name)
            fname = f"{idx:02d}_{safe_name}.mid"
            pm.write(str(midi_dir / fname))
            record.midi_filename = fname

        # Optional rendered stems
        if self._stem_sources:
            audio_dir.mkdir(parents=True, exist_ok=True)
            track_lookup = {t.name: t for t in self.tracks}
            for stem_name, src in self._stem_sources.items():
                src = Path(src)
                if not src.exists():
                    logger.warning("logic bundle: stem missing %s", src)
                    continue
                rec = track_lookup.get(stem_name)
                if rec is None:
                    logger.warning(
                        "logic bundle: stem %r has no matching track; "
                        "copying anyway", stem_name)
                    audio_filename = f"{_safe_filename(stem_name)}{src.suffix}"
                else:
                    audio_filename = f"{_safe_filename(stem_name)}{src.suffix}"
                    rec.audio_filename = audio_filename
                shutil.copy2(src, audio_dir / audio_filename)

        # README + manifest
        (bundle_dir / "LOGIC_README.md").write_text(self._render_readme())
        (bundle_dir / "manifest.json").write_text(self._render_manifest())

        logger.info(
            "logic bundle: %s (%d tracks, stems=%s)",
            bundle_dir, len(self.tracks), bool(self._stem_sources),
        )

        self._per_track_pms.clear()
        self._stem_sources = {}
        import gc
        gc.collect()

        return bundle_dir

    # -- internals ---------------------------------------------------------

    def _render_readme(self) -> str:
        ts_label = f"{self.time_signature[0]}/{self.time_signature[1]}"
        lines: list[str] = []
        lines.append(f"# {self.bundle_name} — Logic Pro bundle\n")
        lines.append(
            "Drag the `.mid` files in `midi/` onto a fresh Logic Pro\n"
            "project — Logic auto-creates Software-Instrument tracks. The\n"
            "table below suggests a curated Logic patch for each track.\n"
        )
        lines.append(f"- **Tempo:** {self.tempo:.0f} BPM")
        lines.append(f"- **Time signature:** {ts_label}")
        lines.append(f"- **Sample rate (rendered audio):** {self.sample_rate} Hz")
        lines.append("\n## Tracks\n")
        lines.append("| # | Track | GM Program | Family | Suggested Logic instrument |")
        lines.append("|---|-------|------------|--------|----------------------------|")
        for idx, t in enumerate(self.tracks, start=1):
            suggestions = LOGIC_INSTRUMENT_SUGGESTIONS.get(t.family, [])
            top = suggestions[0] if suggestions else "(use any)"
            program_label = "Drum kit (Ch 10)" if t.is_drum else f"GM {t.program}"
            lines.append(
                f"| {idx} | `{t.name}` | {program_label} | {t.family} | {top} |"
            )
        lines.append("")
        lines.append("### Alternative patches per family\n")
        for family in sorted({t.family for t in self.tracks}):
            alts = LOGIC_INSTRUMENT_SUGGESTIONS.get(family, [])
            if not alts:
                continue
            lines.append(f"**{family}**")
            for s in alts:
                lines.append(f"- {s}")
            lines.append("")
        if self._stem_sources:
            lines.append("## Pre-rendered stems\n")
            lines.append(
                "`audio/` contains a render of each track produced by\n"
                "`src/audio_processing/render` — useful for reference,\n"
                "comp ideas, or as direct audio if you don't need to\n"
                "finish the track in Logic.\n"
            )
        return "\n".join(lines)

    def _render_manifest(self) -> str:
        manifest = {
            "bundle_name": self.bundle_name,
            "created": datetime.now().isoformat(timespec="seconds"),
            "tempo": self.tempo,
            "time_signature": list(self.time_signature),
            "sample_rate": self.sample_rate,
            "tracks": [
                {
                    "index": i + 1,
                    "name": t.name,
                    "program": t.program,
                    "is_drum": t.is_drum,
                    "family": t.family,
                    "midi": f"midi/{t.midi_filename}",
                    "audio": (f"audio/{t.audio_filename}"
                              if t.audio_filename else None),
                    "logic_suggestions": LOGIC_INSTRUMENT_SUGGESTIONS.get(
                        t.family, []
                    ),
                }
                for i, t in enumerate(self.tracks)
            ],
        }
        return json.dumps(manifest, indent=2)


def _safe_filename(name: str) -> str:
    keep = "-_."
    return "".join(c if c.isalnum() or c in keep else "_" for c in name).strip("_")
