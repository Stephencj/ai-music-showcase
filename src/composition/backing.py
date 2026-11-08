"""Carol backing tracks: keys, voice presets and the timing JSON.

A backing track is a Christmas song planned with the ``backing_track`` (or
``guide_melody``) variant (src/composition/christmas.py): no lead, a one-bar
count-in, one verse per pass. This module

- picks keys: named keys, or the "low voice" / "high voice" presets that put
  the carol's melody in a comfortable range (:func:`voice_key`);
- names the chords in the rendered key (:func:`chord_name`);
- builds the timing JSON a video renderer reads (:func:`build_timing`): bar
  and beat times, the count-in, the chord at each moment, the sections and
  phrases, and the lyric lines with per-syllable times. Lyrics are referenced
  by line number and character span into ``data/lyrics/<carol>.txt``, never
  copied (src/composition/lyrics.py). The schema is in docs/backing_tracks.md;
- turns a timing into the karaoke payload the web KaraokeScreen reads
  (:func:`karaoke_payload`).

Times come from the rendered MIDI's own tempo map (the outro's ritardando
included), so they match the audio, which starts at MIDI time 0.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .carols import Tune, carol

SCHEMA = "ai-music.backing-timing/1"
BACKING_VARIANTS = ("backing_track", "guide_melody")
# The default set of keys to render (major-key names; a minor carol uses the
# relative minors, A B D E G minor), plus the two voice presets.
DEFAULT_KEYS = ("C", "D", "F", "G", "Bb", "low", "high")
VOICE_PRESETS = ("low", "high")
# Comfortable sounding ranges (MIDI) the presets fit the melody into: a low
# voice (alto / baritone an octave down) and a high one (soprano / tenor an
# octave down).
VOICE_RANGES = {"low": (53, 72), "high": (60, 79)}

_SHARPS = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
_FLATS = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
_PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# Major keys spelled with flats, and minor tonics spelled with flats.
_FLAT_MAJOR = {5, 10, 3, 8, 1, 6}
_FLAT_MINOR = {2, 7, 0, 5, 10, 3}
_SUFFIX = {"maj": "", "min": "m", "7": "7", "maj7": "maj7", "min7": "m7", "dim": "dim7", "aug": "+",
           "sus4": "sus4", "sus2": "sus2", "min6": "m6", "maj6": "6", "m7b5": "m7b5"}


def is_backing(arrangement: str) -> bool:
    from .christmas import variants
    return bool(variants(arrangement) & set(BACKING_VARIANTS))


_KEY_RE = re.compile(r"^\s*([A-Ga-g])\s*([#\u266fb\u266d]?)\s*(m(?:in(?:or)?)?|maj(?:or)?)?\s*$", re.I)


def _parse_key(name: str) -> tuple[int, bool]:
    m = _KEY_RE.match(name or "")
    if not m:
        raise ValueError(f"bad key {name!r} (use e.g. C, Bb, F#, Em)")
    acc = {"#": 1, "\u266f": 1, "b": -1, "\u266d": -1, "": 0}[m.group(2)]
    q = (m.group(3) or "").lower()
    return (_PC[m.group(1).upper()] + acc) % 12, q.startswith("m") and not q.startswith("maj")


def key_pc(name: str) -> int:
    """Pitch class of a key name ("Bb", "F#", "Ebm", "G minor")."""
    return _parse_key(name)[0]


def is_minor_name(name: str) -> bool:
    return _parse_key(name)[1]


def spell(pc: int, minor: bool) -> str:
    pc %= 12
    flats = pc in (_FLAT_MINOR if minor else _FLAT_MAJOR)
    return (_FLATS if flats else _SHARPS)[pc]


def tonic_name(name: str, tune: Tune) -> str:
    """The tonic a key name means for ``tune``: "G" is G major for a major
    carol and G minor for a minor one; "Em" is E minor either way."""
    minor = "minor" in tune.scale
    return spell(key_pc(name), minor)


def written_range(tune: Tune) -> tuple[int, int]:
    pitches = [n.pitch for n in tune.melody]
    return min(pitches), max(pitches)


def voice_key(tune: Tune, voice: str) -> str:
    """The key that puts the melody in the ``voice`` range ("low" / "high"):
    the transposition with the least of the melody outside the range,
    then the most centred, then the common singers' keys."""
    lo, hi = VOICE_RANGES[voice]
    mlo, mhi = written_range(tune)
    common = {0, 2, 3, 5, 7, 9, 10}           # C D Eb F G A Bb (or their minors)
    best = None
    for t in range(-12, 13):
        a, b = mlo + t, mhi + t
        out = max(0, lo - a) + max(0, b - hi)
        centre = abs((a + b) / 2 - (lo + hi) / 2)
        pc = (tune.tonic_pc + t) % 12
        rel = (pc + 3) % 12 if "minor" in tune.scale else pc
        score = (out, centre + (0 if rel in common else 1.5))
        if best is None or score < best[0]:
            best = (score, t)
    t = best[1]
    return spell(tune.tonic_pc + t, "minor" in tune.scale)


def sounding_shift(tune: Tune, key: str) -> int:
    """Semitones from the written tune to the key, as the arrangement plays
    it (within -5..+6, the nearest octave)."""
    s = (key_pc(key) - tune.tonic_pc) % 12
    return s - 12 if s > 6 else s


def resolve_keys(tune: Tune, keys: list[str]) -> list[tuple[str, str]]:
    """(label, tonic name) for each requested key: voice presets resolved
    (a preset may land on a key already in the list; the renderer renders
    each tonic once), the default major names turned into relative minors
    for a minor carol, repeated labels dropped."""
    minor = "minor" in tune.scale
    defaults = not keys
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for k in keys or DEFAULT_KEYS:
        k = str(k).strip()
        if k.lower() in VOICE_PRESETS:
            tonic = voice_key(tune, k.lower())
            label = f"{k.lower()}-voice"
        else:
            pc = key_pc(k)
            if minor and defaults:
                pc = (pc + 9) % 12                 # C → A minor (relative), as the defaults mean
            tonic = spell(pc, minor)
            label = tonic + ("m" if minor else "")
        if label in seen:
            continue
        seen.add(label)
        out.append((label, tonic))
    return out


def chord_name(symbol: str, key: str, scale: str) -> str:
    """A roman numeral in ``key`` as a chord symbol ("V7" in G → "D7")."""
    from .christmas import _tonic_pc, parse_symbol
    tonic = _tonic_pc(key)
    root, quality = parse_symbol(symbol, tonic, scale)
    # Spell by the key's signature: flat keys use flats throughout.
    flats = (tonic in _FLAT_MINOR) if "minor" in scale else (tonic in _FLAT_MAJOR)
    name = (_FLATS if flats else _SHARPS)[root]
    if symbol.rstrip().endswith("6") and quality in ("maj", "min"):
        quality = "min6" if quality == "min" else "maj6"
    return name + _SUFFIX.get(quality, quality)


# ---------------------------------------------------------------------------
# Tempo map
# ---------------------------------------------------------------------------

class TempoMap:
    """Quarter-note beats ↔ seconds from a MIDI file's tempo map."""

    def __init__(self, midi: "str | Path | object"):
        import pretty_midi
        pm = midi if isinstance(midi, pretty_midi.PrettyMIDI) else pretty_midi.PrettyMIDI(str(midi))
        times, tempi = pm.get_tempo_changes()
        self.times = [float(t) for t in times] or [0.0]
        self.tempi = [float(b) for b in tempi] or [120.0]
        self.beats = [0.0]
        for k in range(1, len(self.times)):
            self.beats.append(self.beats[-1] + (self.times[k] - self.times[k - 1]) * self.tempi[k - 1] / 60.0)
        self.end = float(pm.get_end_time())

    def time(self, beat: float) -> float:
        k = 0
        while k + 1 < len(self.beats) and beat >= self.beats[k + 1] - 1e-9:
            k += 1
        return round(self.times[k] + (beat - self.beats[k]) * 60.0 / self.tempi[k], 4)


# ---------------------------------------------------------------------------
# Timing JSON
# ---------------------------------------------------------------------------

def _swung(beat: float, swing: bool) -> float:
    if not swing:
        return beat
    whole = int(beat // 1)
    return whole + 2.0 / 3.0 if abs(beat - whole - 0.5) < 1e-6 else beat


def build_timing(plan: dict, midi_path: "str | Path | object", *, audio: Optional[str] = None,
                 duration: Optional[float] = None) -> dict:
    """The timing JSON for a planned (and rendered) Christmas song.
    ``midi_path``: the song's MIDI file (or a loaded PrettyMIDI)."""
    from .christmas import STYLE_DEFAULTS
    from . import lyrics as L
    tm = TempoMap(midi_path)
    beats = int(plan["time_signature"][0])
    scale = plan["scale"]
    song_key = plan["key"]
    tune = carol(plan.get("tune") or "")
    swing = bool(STYLE_DEFAULTS.get(plan.get("style", ""), {}).get("swing"))
    sections = plan["sections"]
    total_bars = sum(s["end_bar"] - s["start_bar"] + 1 for s in sections)

    def at(beat: float) -> float:
        return tm.time(beat)

    out: dict = {
        "schema": SCHEMA,
        "tune": plan.get("tune"), "title": plan.get("tune_title"), "style": plan.get("style"),
        "variant": "guide_melody" if plan.get("guide") else "backing_track" if plan.get("backing") else "full",
        "key": song_key, "final_key": plan.get("final_key", song_key), "scale": scale,
        "transpose": sounding_shift(tune, song_key) if tune else None,
        "tempo": plan["tempo"], "time_signature": list(plan["time_signature"]),
        "audio": audio, "duration": round(float(duration if duration is not None else tm.end), 3),
    }
    # Bars and beats.
    bars = []
    sec_of_bar = {}
    for i, s in enumerate(sections):
        for b in range(s["start_bar"], s["end_bar"] + 1):
            sec_of_bar[b] = i
    for b in range(total_bars + 1):
        if b == total_bars:
            break
        bt = [at(b * beats + k) for k in range(beats)]
        bars.append({"n": b, "start": bt[0], "end": at((b + 1) * beats), "beats": bt, "section": sec_of_bar[b]})
    out["bars"] = bars
    # Count-in.
    ci = next((s for s in sections if s["info"].get("kind") == "count_in"), None)
    out["count_in"] = ({"bars": 1, "start": at(ci["start_bar"] * beats), "end": at((ci["end_bar"] + 1) * beats),
                        "clicks": [at(ci["start_bar"] * beats + k) for k in range(beats)], "sound": "closed hi-hat"}
                       if ci else None)
    # Sections and chords.
    out_secs, chords = [], []
    for i, s in enumerate(sections):
        base = s["start_bar"] * beats
        key = s.get("key") or song_key
        info = s["info"]
        out_secs.append({"index": i, "label": s["label"], "role": s["role"], "kind": info.get("kind"),
                         "start": at(base), "end": at((s["end_bar"] + 1) * beats),
                         "bars": [s["start_bar"], s["end_bar"]], "key": key,
                         **({"pass": info["pass"]} if info.get("pass") else {})})
        for sym, st, d in ([] if info.get("kind") == "count_in" else info.get("chords", [])):
            chords.append({"start": at(base + st), "end": at(base + st + d), "symbol": chord_name(sym, key, scale),
                           "roman": sym, "bar": s["start_bar"] + int(st // beats), "beat": round(st % beats, 3)})
    # Merge a chord that carries on across a section boundary.
    merged: list[dict] = []
    for c in chords:
        if merged and merged[-1]["symbol"] == c["symbol"] and abs(merged[-1]["end"] - c["start"]) < 1e-3:
            merged[-1]["end"] = c["end"]
        else:
            merged.append(dict(c))
    out["sections"], out["chords"] = out_secs, merged
    # Phrases and lyrics: every pass of the tune, verse by verse.
    lyr = L.load(tune.id) if tune else None
    aligned = L.align_passes(tune, lyr) if (tune and lyr) else []
    phrases, lines, melody = [], [], []
    rep = 0
    span = (tune.bars * beats) if tune else 0
    for i, s in enumerate(sections):
        info = s["info"]
        if info.get("kind") not in ("pass1", "pass2", "var", "final") or not tune:
            continue
        times = int(info.get("times") or plan.get("times") or 1)
        shift = sounding_shift(tune, s.get("key") or song_key)
        for r in range(times):
            origin = s["start_bar"] * beats + r * span
            verse = aligned[rep] if rep < len(aligned) else None
            stanza = rep if verse else None
            for n in tune.melody:
                st = origin + n.start
                melody.append([n.pitch + shift, at(_swung(st, swing)), at(_swung(st + n.dur, swing))])
            if verse:
                for lt in verse:
                    syl = [{"i": sy.index, "start": at(_swung(origin + sy.start, swing)),
                            "end": at(_swung(origin + sy.end, swing)),
                            "chars": list(lyr.syllables(lt.line)[sy.index])} for sy in lt.syllables]
                    lines.append({"line": lt.line, "stanza": stanza, "pass": rep + 1, "section": i,
                                  "start": syl[0]["start"], "end": syl[-1]["end"], "syllables": syl})
                    phrases.append({"start": syl[0]["start"], "end": syl[-1]["end"], "section": i,
                                    "pass": rep + 1, "line": lt.line})
            else:
                pb = tune.phrase_bars * beats
                k = 0.0
                while k < span - 1e-6:
                    phrases.append({"start": at(origin + k), "end": at(origin + min(span, k + pb)), "section": i,
                                    "pass": rep + 1, "line": None})
                    k += pb
            rep += 1
    out["phrases"] = phrases
    out["melody"] = melody
    rel = None
    if lyr is not None:
        try:
            rel = str(lyr.path.relative_to(L.PROJECT_ROOT))
        except ValueError:
            rel = str(lyr.path)
    out["lyrics"] = {"available": bool(lines), "file": rel, "verses": len(lyr.verses) if lyr else 0,
                     "lines": lines}
    return out


def timing_for_spec(spec: dict, midi) -> Optional[dict]:
    """Rebuild a saved backing track's timing from its generation spec (the
    plan inputs ``service.run_generation`` records) and its MIDI."""
    from .christmas import STYLE_IDS, plan_song
    args = spec.get("plan_args")
    if not args or args.get("genre") not in STYLE_IDS or not is_backing(args.get("arrangement") or ""):
        return None
    plan = plan_song(args["genre"], seed=int(args["seed"]), tune=args.get("tune"), key=args.get("key"),
                     tempo=args.get("tempo"), length_seconds=args.get("length_seconds"),
                     arrangement=args.get("arrangement") or "", instruments=args.get("instruments"))
    if args.get("remove_sections"):
        from src.api.arrangement import drop_sections
        plan = {**plan, "sections": drop_sections([dict(s) for s in plan["sections"]], args["remove_sections"])}
    return build_timing(plan, midi)


def write_timing(timing: dict, path: "str | Path") -> Path:
    import json
    p = Path(path)
    p.write_text(json.dumps(timing, indent=1))
    return p


def karaoke_payload(timing: dict) -> dict:
    """The KaraokeScreen payload (service.karaoke_data's shape) from a timing:
    the melody as the pitch lane, the lyric words with their times."""
    from . import lyrics as L
    lyr = L.load(timing.get("tune") or "") if timing.get("lyrics", {}).get("available") else None
    words: list[dict] = []
    used_lines: list[int] = []
    for ln in timing.get("lyrics", {}).get("lines", []):
        text = lyr.text_lines[ln["line"]] if lyr else ""
        used_lines.append(ln["line"])
        spans = lyr.syllables(ln["line"]) if lyr else []
        by_char = {tuple(s["chars"]): s for s in ln["syllables"]}
        for a, b, _n in L.line_words(text):
            syl = [by_char[sp] for sp in spans if a <= sp[0] < b and sp in by_char]
            if syl:
                words.append({"text": text[a:b], "start": syl[0]["start"], "end": syl[-1]["end"]})
    lyrics_text = ""
    if lyr:
        lyrics_text = "\n".join(lyr.text_lines[i] for i in dict.fromkeys(used_lines))
    notes = [[int(p), s, e] for p, s, e in timing.get("melody", [])]
    return {
        "duration": timing.get("duration") or 0.0,
        "tempo": timing.get("tempo") or 120.0,
        "key": timing.get("key") or "C",
        "scale": timing.get("scale") or "major",
        "notes": notes,
        "words": words,
        "lyrics": lyrics_text,
        "has_lead": bool(notes),
    }
