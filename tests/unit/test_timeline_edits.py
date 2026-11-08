"""Create → Timeline edits: silence one instrument in one section (the
per-section instrument mask), remove a section (``remove_sections``), and the
job waveform/section timing the timeline's scrub bar uses."""
import tempfile
from pathlib import Path

import numpy as np
import pretty_midi
import pytest
import soundfile as sf

import src.composition.builtins  # noqa: F401
from src.api.arrangement import build_sections
from src.composition.song_composer import compose_song
from src.composition.song_plan import describe_changes, normalize_plan
from src.daw_integration.generic.styles import STYLES

FF = "funk_fusion_full"


def _notes_per_section(genre: str, secs: list[dict], band: list[str], seed: int = 7):
    out = compose_song(genre=genre, sections=secs, seed=seed, enabled_instruments=tuple(band),
                       output_dir=tempfile.mkdtemp(), skip_audio=True)
    pm = pretty_midi.PrettyMIDI(out["midi_path"])
    db = pm.get_downbeats()
    eps = 0.03          # humanized notes land a few ms either side of the beat
    counts = {}
    for inst in pm.instruments:
        per = []
        for s in secs:
            a = db[s["start_bar"]] - eps
            b = db[s["end_bar"] + 1] - eps if s["end_bar"] + 1 < len(db) else 1e9
            per.append(sum(1 for n in inst.notes if a <= n.start < b))
        counts[inst.program if not inst.is_drum else "drums"] = per
    return counts


@pytest.mark.parametrize("genre,inst,program", [
    (FF, "electric_bass", 33),          # Funk Fusion arranges its own sections
    ("pop_full_song", "electric_bass", 33),
])
def test_silence_one_instrument_in_one_section(genre, inst, program):
    band = list(STYLES[genre].default_instruments)
    if inst not in band:
        band.append(inst)
    base = build_sections(genre, [])
    verse = [i for i, s in enumerate(base) if s["role"] == "verse"]
    assert verse, "the template has a verse"
    mask = [i for i in band if i != inst]
    secs = build_sections(genre, [], None, {"verse": {"instruments": mask}})
    assert all(s.get("instruments") == mask for s in secs if s["role"] == "verse")
    before = _notes_per_section(genre, base, band)
    after = _notes_per_section(genre, secs, band)
    for i in verse:
        assert before[program][i] > 0, "the bass plays the verse normally"
        assert after[program][i] == 0, "silenced in every verse"
    others = [i for i, s in enumerate(secs) if s["role"] != "verse"]
    assert any(after[program][i] > 0 for i in others), "it still plays elsewhere"
    # The rest of the band still plays the verse.
    assert sum(after["drums"][i] for i in verse) > 0


def test_remove_one_section_keeps_the_repeats_and_closes_up():
    full = build_sections(FF, [])
    roles = [s["role"] for s in full]
    bridge = roles.index("bridge")
    secs = build_sections(FF, [], remove=[bridge])
    assert [s["role"] for s in secs] == roles[:bridge] + roles[bridge + 1:]
    # Both choruses survive (no collapse to one of each role) and the bars close up.
    assert [s["role"] for s in secs].count("chorus") == roles.count("chorus")
    assert secs[0]["start_bar"] == 0
    for a, b in zip(secs, secs[1:]):
        assert b["start_bar"] == a["end_bar"] + 1
    removed_bars = full[bridge]["end_bar"] - full[bridge]["start_bar"] + 1
    assert secs[-1]["end_bar"] == full[-1]["end_bar"] - removed_bars


def test_remove_ignores_bad_indices_and_never_empties_the_song():
    full = build_sections(FF, [])
    assert build_sections(FF, [], remove=[99]) == full
    assert len(build_sections(FF, [], remove=list(range(len(full))))) == len(full)


def test_remove_composes_a_shorter_song():
    band = list(STYLES[FF].default_instruments)
    full = build_sections(FF, [])
    secs = build_sections(FF, [], remove=[len(full) - 2])
    out = compose_song(genre=FF, sections=secs, seed=3, enabled_instruments=tuple(band),
                       output_dir=tempfile.mkdtemp(), skip_audio=True)
    pm = pretty_midi.PrettyMIDI(out["midi_path"])
    bars = sum(s["end_bar"] - s["start_bar"] + 1 for s in secs)
    assert len(pm.get_downbeats()) <= bars + 2


def test_plan_keeps_remove_sections_through_a_revision():
    prev, _ = normalize_plan({"genre": FF, "seed": 5, "remove_sections": [3, 3, -1, "x", 1]})
    assert prev["remove_sections"] == [1, 3]
    rev, _ = normalize_plan({"tempo": 100}, prev)
    assert rev["remove_sections"] == [1, 3]
    assert "Removed sections: 2, 4" in describe_changes({"genre": FF}, prev)
    # A new section list makes the old indices meaningless: dropped.
    rev2, _ = normalize_plan({"sections": ["verse", "chorus"]}, prev)
    assert "remove_sections" not in rev2


def test_silence_mask_survives_a_revision():
    prev, _ = normalize_plan({"genre": FF, "section_overrides": {"verse": {"instruments": ["drum_kit", "trumpet"]}}})
    rev, _ = normalize_plan({"tempo": 110}, prev)
    assert rev["section_overrides"]["verse"]["instruments"] == ["drum_kit", "trumpet"]


def test_job_peaks_and_section_starts(tmp_path: Path):
    from src.api import service
    tempo = 120.0
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    inst = pretty_midi.Instrument(0)
    for bar in range(8):
        inst.notes.append(pretty_midi.Note(80, 60, bar * 2.0, bar * 2.0 + 1.0))
    pm.instruments.append(inst)
    midi = tmp_path / "song.mid"
    pm.write(str(midi))
    sr = 8000
    wav = tmp_path / "render" / "mix.wav"
    wav.parent.mkdir()
    sf.write(str(wav), np.concatenate([np.zeros(sr * 8), 0.5 * np.ones(sr * 8)]).astype("float32"), sr)
    result = {"_paths": {"midi": str(midi), "audio_wav": str(wav)},
              "_split": {"sections": [{"start_bar": 0, "end_bar": 3}, {"start_bar": 4, "end_bar": 7}]}}
    data = service.job_peaks(result, 32)
    assert len(data["peaks"]) == 32
    assert data["peaks"][0] == 0 and data["peaks"][-1] == 1
    assert data["duration"] == pytest.approx(16.0)
    assert data["section_starts"] == [0.0, 8.0]
    assert (wav.parent / "peaks_32.json").exists()
    assert service.job_peaks(result, 32) == data       # served from the cache
