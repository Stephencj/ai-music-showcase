"""Splitting a song into section blocks never collides with a block file the
listing doesn't show (e.g. a sidecar whose stored name differs: "Chorus_1"
for "Chorus 1"), so every section is saved."""

import pretty_midi
import pytest

from src.daw_integration.generic import block_concat
from src.daw_integration.generic import blocks as block_store


@pytest.fixture
def blocks_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(block_store, "BLOCKS_DIR", tmp_path)
    return tmp_path


def _song(bars: int, tempo: float = 120.0) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=tempo)
    inst = pretty_midi.Instrument(program=0)
    spb = 2.0  # 4/4 at 120
    for b in range(bars):
        inst.notes.append(pretty_midi.Note(velocity=90, pitch=60, start=b * spb, end=b * spb + 0.5))
    pm.instruments.append(inst)
    return pm


def test_split_skips_names_taken_by_unlisted_files(blocks_dir):
    (blocks_dir / "Chorus_1.yaml").write_text("name: Chorus_1\ntempo: 120\n")
    secs = [{"start_bar": 0, "end_bar": 1, "label": "Verse"},
            {"start_bar": 2, "end_bar": 3, "label": "Chorus 1"}]
    names = block_concat.split_into_section_blocks(_song(4), secs, tempo=120.0, time_signature=(4, 4))
    assert names == ["Verse", "Chorus 1 2"]
