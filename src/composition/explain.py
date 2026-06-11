"""'Explain this song' — turn a generated block's stored spec into a plain,
teaching-oriented breakdown: the key/mode and how each section relates to it,
the chords with their harmonic FUNCTION (tonic / predominant / dominant), named
progressions and devices (ii-V-I, the four-chord pop loop, secondary dominants,
borrowed chords, the Dorian IV…), and why the arrangement does what it does.

The point of the product is to show *under the hood*, so this surfaces the
reasoning the engine already used — nothing here re-generates anything.
"""

from __future__ import annotations

from src.daw_integration.generic.midi_export import NOTE_NAMES, FLAT_TO_SHARP

_MAJOR = [0, 2, 4, 5, 7, 9, 11]
# Semitones from a mode's tonic to its PARENT MAJOR (shared with song_composer).
_PARENT_OFFSET = {
    "major": 0, "ionian": 0, "dorian": 2, "phrygian": 4, "lydian": 5,
    "mixolydian": 7, "minor": 9, "aeolian": 9, "natural_minor": 9, "locrian": 11,
    "harmonic_minor": 9, "melodic_minor": 9, "pentatonic_minor": 9, "blues": 9,
    "pentatonic_major": 0,
}
_DEGREE_NAME = {
    1: "I (tonic)", 2: "ii (supertonic)", 3: "iii (mediant)", 4: "IV (subdominant)",
    5: "V (dominant)", 6: "vi (the relative minor / submediant)", 7: "vii (leading tone)",
}


def _pc(key: str) -> int:
    try:
        return NOTE_NAMES.index(FLAT_TO_SHARP.get(key, key)) % 12
    except ValueError:
        return 0


def _stem(roman: str) -> str:
    """Bare Roman stem, accidentals + quality stripped: 'bVII7' → 'VII'."""
    s = roman
    while s and s[0] in "b#♭♯":
        s = s[1:]
    out = ""
    for ch in s:
        if ch.isalpha() and ch in "iIvV":
            out += ch
        else:
            break
    return out


def _function(roman: str) -> str:
    """Harmonic function of a Roman-numeral chord (simplified, teaching-level)."""
    r = roman.strip()
    flat = r.startswith("b") or r.startswith("♭")
    stem = _stem(r).upper()
    if flat and stem == "II":
        return "dominant (Neapolitan / tritone-sub)"
    return {
        "I": "tonic", "II": "predominant", "III": "tonic group (mediant)",
        "IV": "predominant (subdominant)", "V": "dominant",
        "VI": "tonic group (submediant)", "VII": "dominant (leading)",
    }.get(stem, "colour")


def _key_relation(sec_key, sec_scale, g_key, g_scale) -> str:
    """How the section's key relates to the song key, in teaching terms."""
    from src.daw_integration.generic.midi_export import SCALES
    sk, ss = (sec_key or g_key), (sec_scale or g_scale)
    same_tonic = _pc(sk) == _pc(g_key)
    same_mode = (ss or "").lower() == (g_scale or "").lower()
    if same_tonic and same_mode:
        return f"{sk} {ss} — the home key"
    sec_parent = (_pc(sk) - _PARENT_OFFSET.get((ss or "major").lower(), 0)) % 12
    g_parent = (_pc(g_key) - _PARENT_OFFSET.get((g_scale or "major").lower(), 0)) % 12
    if sec_parent == g_parent:                # diatonic relative — shares the signature
        g_int = SCALES.get(g_scale, SCALES["major"])
        deg_semi = (_pc(sk) - _pc(g_key)) % 12
        degname = (_DEGREE_NAME.get(g_int.index(deg_semi) + 1, "a related degree")
                   if deg_semi in g_int else "a related degree")
        return (f"{sk} {ss} — built on the {degname} of {g_key} {g_scale}, so it "
                f"keeps the same key signature (no new sharps or flats — it just "
                f"*feels* different)")
    if same_tonic:                            # parallel — same root, borrowed mode
        return (f"{sk} {ss} — the parallel {ss}: same root as the song but "
                f"borrowing the {ss} colour (modal interchange)")
    return f"{sk} {ss} — a modulation away from {g_key} {g_scale}"


# Progression shapes recognised by their Roman sequence (rotation-insensitive).
def _name_progression(romans: list[str]) -> str | None:
    core = [_stem(r).upper() or r for r in romans]
    # collapse immediate repeats and trim to a cycle
    seq = []
    for c in core:
        if not seq or seq[-1] != c:
            seq.append(c)
    s = " ".join(seq)
    sset = set(seq)

    def rot(target):
        t = target.split()
        return any(seq[i:] + seq[:i] == t for i in range(len(seq))) if len(seq) == len(t) else False

    if rot("I V VI IV"):
        return "the four-chord pop loop (I–V–vi–IV) — the 'Axis' progression behind countless hits"
    if rot("I VI IV V") or rot("I VI II V"):
        return "the '50s doo-wop' progression (I–vi–IV–V)"
    if seq[:3] == ["II", "V", "I"] or rot("II V I"):
        return "a ii–V–I — the fundamental jazz cadence"
    if sset <= {"I", "IV", "V"} and "V" in sset and "IV" in sset:
        return "a I–IV–V blues/rock backbone"
    if seq[:3] == ["I", "VII", "VI"] or rot("I VII VI VII"):
        return "the Aeolian i–♭VII–♭VI loop (the 'epic' minor sound)"
    return None


def _devices(romans: list[str], scale: str) -> list[str]:
    """Named harmonic devices present in the section's progression."""
    found: list[str] = []
    keys: set[str] = set()

    def add(k: str, text: str):
        if k not in keys:
            keys.add(k)
            found.append(text)

    minor = (scale or "").lower() in (
        "minor", "natural_minor", "aeolian", "dorian", "phrygian", "locrian")
    for r in romans:
        low = r.lower()
        stem = _stem(r)
        is_major = bool(stem) and stem[0].isupper()
        if low.startswith("bii") and "7" in low:
            add("tritone", "tritone substitution (♭II7 sliding chromatically into I)")
        elif is_major and "7" in r and not r.startswith("b") and stem.upper() in ("II", "III", "VI", "VII"):
            add("secdom", "a secondary dominant — a chord that points at the next one, like a temporary V")
        if low.startswith("bvi") or low.startswith("bvii"):
            add("borrowed", "borrowed chords (modal interchange) — colour pinched from the parallel minor")
        if (not minor) and stem == "iv":
            add("miniv", "the borrowed minor iv — a bittersweet subdominant")
    if (scale or "").lower() == "dorian" and any(_stem(r) == "IV" for r in romans):
        add("doriv", "the bright Dorian IV (a major IV where a minor key expects a minor one)")
    return found


def _arrangement_note(sec: dict) -> str:
    role = sec.get("role") or "section"
    notes = []
    e = sec.get("energy")
    if role == "buildup":
        notes.append("builds tension by ramping the dynamics up into the next section")
    elif role == "drop":
        notes.append("the payoff — the loudest, fullest moment")
    elif role == "breakdown":
        notes.append("stripped back to create space before the energy returns")
    elif role == "solo" or sec.get("feature_lead"):
        notes.append("features the lead instrument out front")
    elif role == "prechorus":
        notes.append("lifts the energy to set up the chorus")
    elif role == "intro":
        notes.append("eases in — the full kit usually holds back")
    if e is not None:
        notes.append(f"set to a custom energy of {e:.2f} (1.0 = chorus level)")
    return "; ".join(notes)


def explain_spec(spec: dict, *, genre_name=None, feel_name=None) -> dict:
    g_key = spec.get("key") or "C"
    g_scale = spec.get("scale") or "major"
    tempo = spec.get("tempo")
    sections = spec.get("sections") or []
    prog = spec.get("progression") or []

    from src.daw_integration.generic.styles import STYLES
    from src.daw_integration.generic.chord_analysis import _label_chord

    def style_name(pid):
        p = STYLES.get(pid or "")
        return getattr(p, "name", pid)

    song_feel = genre_name or style_name(spec.get("genre"))
    out_sections = []
    for sec in sections:
        sb, eb = int(sec.get("start_bar", 0)), int(sec.get("end_bar", 0))
        sec_key = sec.get("key") or g_key
        sec_scale = (sec.get("scale")
                     or (getattr(STYLES.get(sec.get("preset_id") or ""), "scale", None))
                     or g_scale)
        tonic = _pc(sec_key)
        # chords active in this section's bars (collapsed to unique downbeats)
        chords, romans, seen = [], [], None
        for p in prog:
            if sb <= float(p["start_bar"]) < eb + 1:
                lab = _label_chord(int(p["root_pc"]) % 12, str(p["quality"]), tonic)
                rn = p.get("symbol") or lab["roman"]
                if rn == seen:
                    continue
                seen = rn
                romans.append(rn)
                chords.append({
                    "name": lab["symbol"], "roman": rn,
                    "nashville": lab["nashville"], "function": _function(rn),
                })
        out_sections.append({
            "label": sec.get("label") or sec.get("role") or "Section",
            "role": sec.get("role"),
            "bars": eb - sb + 1,
            "feel": style_name(sec.get("preset_id")) if sec.get("preset_id") else song_feel,
            "key_relation": _key_relation(sec_key, sec_scale, g_key, g_scale),
            "tempo": sec.get("tempo"),
            "chords": chords,
            "progression_name": _name_progression(romans),
            "devices": _devices(romans, sec_scale),
            "arrangement": _arrangement_note(sec),
        })

    return {
        "key": f"{g_key} {g_scale}",
        "tempo": tempo,
        "genre": genre_name or style_name(spec.get("genre")),
        "form": [s["label"] for s in out_sections],
        "sections": out_sections,
    }


def explain_block(name: str) -> dict:
    from src.daw_integration.generic import blocks as block_store
    _pm, meta = block_store.load_block(name)
    spec = meta.get("spec") or {}
    if not spec.get("sections"):
        # Fall back to a minimal single-section view from whatever we know.
        spec = {**spec, "sections": [{
            "start_bar": 0, "end_bar": int(meta.get("bars") or 4) - 1,
            "label": "Whole block", "role": "verse"}]}
    return explain_spec(spec)
