"""Rule-based natural-language → song-plan parser.

Turns a plain-English description ("a pop song with a funky verse and a big
hip-hop chorus in G minor around 95 bpm, add some 808s") into a SongPlan dict
that maps directly onto the Generate form / GenerateRequest. Deterministic — no
model — and unit-tested.

This is the NL→song feature's parser. It covers what the Generate request can
express today: the global genre, per-section presets (multi-preset songs),
key / scale / tempo / swing, and instruments. Playing-style directives it can't
yet act on ("guitar solo in the bridge", "sparse intro") are surfaced in
``notes`` so the user knows they were seen — per-section dynamics/solo styling
is the next increment.
"""

from __future__ import annotations

import re
from typing import Optional

# ── Lexicons ────────────────────────────────────────────────────────────────
# keyword regex → preset id. Order matters: longer / more specific first so
# "boom bap" wins before "hip hop", "nu metal" before "metal". Values must be
# real STYLES keys (validated at parse time; unknowns are skipped). Full-song
# variants are preferred for richer default arrangements.
_GENRE_LEXICON: list[tuple[str, str]] = [
    (r"boom[\s-]?bap", "hip_hop_90s"),
    (r"90s\s+hip[\s-]?hop", "hip_hop_90s"),
    (r"hip[\s-]?hop", "hip_hop_full"),
    (r"\brap\b", "hip_hop_full"),
    (r"\btrap\b", "trap_dj"),
    (r"\br\s*&\s*b\b|\brnb\b|\br\s+and\s+b\b", "rnb_90s"),
    (r"\bfunk\w*", "funk_full_song"),
    (r"\bbossa(\s+nova)?\b", "jazz_bossa_full"),
    (r"\bjazz\w*", "jazz_aaba_full"),
    (r"\bblues\b", "blues_12bar_full"),
    (r"\bcountry\b", "country_full"),
    (r"\breggaeton\b", "reggaeton"),
    (r"\breggae\b", "reggae_full"),
    (r"\bdisco\b", "disco_full"),
    (r"\bsoul\b|\bmotown\b", "soul_motown_full"),
    (r"\bedm\b|\bhouse\b|\belectronic\b|\bdance\b", "edm_full_song"),
    (r"\bsynth[\s-]?wave\b", "synthwave"),
    (r"\bnew\s+wave\b", "new_wave"),
    (r"nu[\s-]?metal", "nu_metal"),
    (r"\bmetal\b", "metal_full"),
    (r"surf(\s+rock)?", "surf_rock"),
    (r"\brock\b", "rock_anthem_full"),
    (r"\bballad\b", "ballad_full"),
    (r"\bsalsa\b", "salsa"),
    (r"\bmambo\b", "latin_mambo"),
    (r"\bcumbia\b", "latin_cumbia"),
    (r"\bflamenco\b", "flamenco"),
    (r"\bafrobeat\b", "afrobeat"),
    (r"\bbollywood\b", "bollywood"),
    (r"\bbhangra\b", "bhangra"),
    (r"\bj[\s-]?pop\b", "j_pop"),
    (r"\blatin\b", "latin_pop"),
    (r"\bcinematic\b|\bepic\b|\bfilm\s+score\b|\btrailer\b", "cinematic_epic"),
    (r"\bheroic\b", "cinematic_heroic"),
    (r"\bbaroque\b", "classical_baroque"),
    (r"\bwaltz\b", "classical_waltz"),
    (r"\bclassical\b|\borchestral\b|\bromantic\b", "classical_romantic"),
    (r"\bchiptune\b|8[\s-]?bit|\bchip\b", "game_chiptune"),
    (r"\bjrpg\b", "game_jrpg"),
    (r"\bgamelan\b", "gamelan_ambient"),
    (r"\bsaloon\b|\bragtime\b|\bhonky[\s-]?tonk\b", "saloon_piano"),
    (r"\boud\b|\bmiddle\s+eastern\b", "oud_ballad"),
    (r"\bboy\s+band\b", "boy_band"),
    (r"\bpop\b", "pop_full_song"),
]

# section keyword → canonical role (intro/verse/chorus/bridge/outro).
_SECTION_LEXICON: list[tuple[str, str]] = [
    (r"pre[\s-]?chorus", "prechorus"),       # its own role now
    (r"chorus(es)?|\bhook\b|\bdrop\b|\brefrain\b", "chorus"),
    (r"verse(s)?", "verse"),
    (r"\bintro(duction)?\b|build[\s-]?up|\briser\b", "intro"),
    (r"\boutro\b|\bending\b|\bcoda\b|fade[\s-]?out", "outro"),
    (r"\bbridge\b|break[\s-]?down|middle\s+eight", "bridge"),
]

# instrument keyword → registry id. Longer/specific first.
_INSTRUMENT_LEXICON: list[tuple[str, str]] = [
    (r"\b808s?\b", "bass_808"),
    (r"\bsub\s*bass\b", "sub_bass"),
    (r"\bsynth\s*bass\b", "synth_bass"),
    (r"\b(upright|double)\s+bass\b", "upright_bass"),
    (r"\bbass\b", "electric_bass"),
    (r"\blatin\s+perc\w*", "latin_perc"),
    (r"\bdrum\s*kit\b|\bdrums?\b|\bbeat\b", "drum_kit"),
    (r"\bpercussion\b|\bperc\b", "percussion"),
    (r"\b(electric\s+piano|rhodes|wurli\w*)\b", "electric_piano"),
    (r"\bpiano\b|\bkeys\b", "piano"),
    (r"\b(hammond|organ)\b", "organ_hammond"),
    (r"\bacoustic\s+guitar\b", "acoustic_guitar"),
    (r"\bclean\s+guitar\b", "electric_guitar_clean"),
    (r"\b(dirty|distorted|crunchy)\s+guitar\b", "electric_guitar_dirty"),
    (r"\blead\s+guitar\b|\bguitar\s+solo\b", "lead_guitar"),
    (r"\bguitar\b", "electric_guitar_clean"),
    (r"\bsynth\s*pad\b|\bpads?\b", "synth_pad"),
    (r"\b(synth\s*lead|lead\s*synth)\b", "synth_lead"),
    (r"\bsynth\w*", "synth_pad"),
    (r"\b(brass|horns?)\b", "brass_section"),
    (r"\btrumpet\b", "trumpet"),
    (r"\btrombone\b", "trombone"),
    (r"\balto\s+sax\w*", "sax_alto"),
    (r"\btenor\s+sax\w*", "sax_tenor"),
    (r"\bbari(tone)?\s+sax\w*", "sax_baritone"),
    (r"\bsax\w*|\bsaxophone\b", "sax_tenor"),
    (r"\bflute\b", "flute"),
    (r"\bclarinet\b", "clarinet"),
    (r"\boboe\b", "oboe"),
    (r"\bbassoon\b", "bassoon"),
    (r"\bwoodwinds?\b", "woodwind_section"),
    (r"\bstring\s*section\b|\bstrings\b", "string_section"),
    (r"\b(violin|fiddle)\b", "violin"),
    (r"\bviola\b", "viola"),
    (r"\bcello\b", "cello"),
    (r"\bcontrabass\b", "contrabass"),
    (r"\b(harmonies|backing\s+vocals?)\b", "vocal_harmony"),
]

# playing-style directives → an effect kind. When bound to a section they
# become per-section overrides; otherwise they're surfaced as notes.
_STYLE_HINTS: list[tuple[str, str]] = [
    (r"\bguitar\s+solo\b|\bsolo\b", "solo"),
    (r"\b(sparse|stripped|minimal|mellow|quiet|laid[\s-]?back)\b", "sparse"),
    (r"\b(big|huge|anthemic|massive|powerful|energetic)\b", "big"),
    (r"\b(lots\s+of\s+)?fills?\b", "fills"),
    (r"\b(buildup|build[\s-]?up|building|builds|build)\b", "build"),
]
_HINT_DESC = {
    "solo": "a solo", "sparse": "a sparse/quiet feel", "big": "a big/energetic feel",
    "fills": "drum fills", "build": "a build",
}
# kind → per-section override fragment. "build" has no clean per-section lever
# yet, so it stays note-only (absent here).
_HINT_EFFECT: dict[str, dict] = {
    "sparse": {"energy": 0.62},
    "big": {"energy": 1.25},
    "fills": {"knobs": {"drum_fill": 1.7}},
    "solo": {"feature_lead": True, "energy": 0.97},
}

_WORD_TEMPOS: list[tuple[str, int]] = [
    (r"\bvery\s+fast\b|\bfrantic\b", 160),
    (r"\bfast\b|\buptempo\b|\bup[\s-]?tempo\b", 140),
    (r"\bupbeat\b|\bbouncy\b|\bbright\b", 124),
    (r"\bmid[\s-]?tempo\b|\bmedium\b|\bmoderate\b", 100),
    (r"\bdown[\s-]?tempo\b|\blaid[\s-]?back\b|\bchill\b", 85),
    (r"\bslow\b|\bballad\b", 70),
]

_SCALE_WORDS = {
    "major": "major", "maj": "major", "minor": "minor", "min": "minor",
    "dorian": "dorian", "phrygian": "phrygian", "lydian": "lydian",
    "mixolydian": "mixolydian", "locrian": "locrian",
    "harmonic minor": "harmonic_minor", "melodic minor": "melodic_minor",
    "blues": "blues",
}

_NOTE = r"[A-Ga-g](?:#|b|♯|♭)?"
# "key of G", "in Gm", "G minor", "Bb major", "F# dorian"
_KEY_CTX_RE = re.compile(
    r"\b(?:in\s+(?:the\s+)?key\s+of|key\s+of|in)\s+(" + _NOTE + r")"
    r"\s*(major|minor|maj|min|m|dorian|phrygian|lydian|mixolydian|locrian)?\b",
    re.I)
_KEY_QUAL_RE = re.compile(
    r"\b(" + _NOTE + r")\s*(major|minor|dorian|phrygian|lydian|mixolydian|"
    r"locrian|harmonic\s+minor|melodic\s+minor)\b", re.I)
_KEY_M_RE = re.compile(r"\b([A-G](?:#|b)?)m\b")  # "Gm", "Bbm" shorthand
# "key of C" / "in the key of C" (a quality-less key needs the explicit "key
# of" lead-in; a bare "in C" is too easily a false hit on words like "in funk").
_KEY_OF_RE = re.compile(
    r"\b(?:in\s+(?:the\s+)?)?key\s+of\s+(" + _NOTE + r")"
    r"\s*(major|minor|maj|min|m|dorian|phrygian|lydian|mixolydian|locrian)?\b", re.I)
_BPM_RE = re.compile(r"\b(\d{2,3})\s*(?:bpm|beats\s*per\s*minute)\b", re.I)
_AT_BPM_RE = re.compile(r"\bat\s+(\d{2,3})\b", re.I)
_HALF_DOUBLE_RE = re.compile(r"\b(half|double)[\s-]?time\b", re.I)


def _scale_from_qual(qual: str) -> str:
    q = (qual or "").lower().strip()
    if q in ("m", "min", "minor"):
        return "minor"
    return _SCALE_WORDS.get(q) or "major"


def _find_key_matches(raw: str) -> list[tuple[int, int, str, str]]:
    """Every key mention as (start, end, key, scale). Uses note+quality and the
    explicit "key of" form (which can be quality-less); de-duplicates overlaps."""
    out: list[tuple[int, int, str, str]] = []
    claimed: list[tuple[int, int]] = []

    def add(s, e, note, qual):
        if any(not (e <= os or s >= oe) for os, oe in claimed):
            return
        claimed.append((s, e))
        out.append((s, e, _norm_note(note), _scale_from_qual(qual)))

    for m in _KEY_QUAL_RE.finditer(raw):
        add(m.start(), m.end(), m.group(1), m.group(2) or "")
    for m in _KEY_OF_RE.finditer(raw):
        add(m.start(1), m.end(), m.group(1), m.group(2) or "")
    for m in _KEY_M_RE.finditer(raw):
        add(m.start(), m.end(), m.group(1), "minor")
    out.sort()
    return out


DEFAULT_GENRE = "pop_full_song"


def _norm_note(tok: str) -> str:
    """Title-case the letter, normalise accidental glyphs to #/b."""
    tok = tok.replace("♯", "#").replace("♭", "b")
    return tok[0].upper() + tok[1:]


def _first_match(text: str, lexicon: list[tuple[str, str]]):
    """Lowest-position match across a lexicon → (start, end, value) or None."""
    best = None
    for pat, val in lexicon:
        m = re.search(pat, text, re.I)
        if m and (best is None or m.start() < best[0]):
            best = (m.start(), m.end(), val)
    return best


def _all_matches(text: str, lexicon: list[tuple[str, str]]):
    """Every non-overlapping match, left→right, first lexicon entry winning a
    given span: list of (start, end, value)."""
    spans: list[tuple[int, int, str]] = []
    for pat, val in lexicon:
        for m in re.finditer(pat, text, re.I):
            s, e = m.start(), m.end()
            if any(not (e <= os or s >= oe) for os, oe, _ in spans):
                continue  # overlaps an already-claimed span
            spans.append((s, e, val))
    spans.sort()
    return spans


def parse_prompt(text: str) -> dict:
    """Parse a free-text song description into a SongPlan dict:

    ``{genre, key, scale, tempo, swing, sections, section_presets,
       instruments, understood, notes}`` — shaped to drop straight onto the
    Generate form. ``understood`` lists what was applied; ``notes`` flags
    things seen but not (yet) actionable.
    """
    from src.daw_integration.generic.styles import STYLES
    from src.composition.instruments import INSTRUMENT_REGISTRY

    raw = text or ""
    low = raw.lower()
    understood: list[str] = []
    notes: list[str] = []

    def label(pid: str) -> str:
        p = STYLES.get(pid)
        return p.name if p else pid

    # ── genres + sections, then bind adjacent genre→section ──────────────────
    genre_hits = [(s, e, v) for (s, e, v) in _all_matches(raw, _GENRE_LEXICON)
                  if v in STYLES]
    section_hits = _all_matches(raw, _SECTION_LEXICON)

    section_presets: dict[str, str] = {}
    consumed_genres: set[int] = set()
    BIND_WINDOW = 16  # chars between a genre word and the section it styles
    for (ss, se, role) in section_hits:
        # nearest unconsumed genre adjacent to this section (either side)
        best_i, best_dist = None, BIND_WINDOW + 1
        for i, (gs, ge, gv) in enumerate(genre_hits):
            if i in consumed_genres:
                continue
            dist = ss - ge if gs < ss else gs - se  # gap between spans
            if 0 <= dist < best_dist:
                best_i, best_dist = i, dist
        if best_i is not None:
            gv = genre_hits[best_i][2]
            section_presets.setdefault(role, gv)
            consumed_genres.add(best_i)

    unbound = [gv for i, (_, _, gv) in enumerate(genre_hits) if i not in consumed_genres]

    # global genre: first unbound genre; else the chorus's (or verse's) genre;
    # else default. Then drop section overrides equal to the global.
    if unbound:
        genre = unbound[0]
    elif section_presets:
        genre = (section_presets.get("chorus") or section_presets.get("verse")
                 or next(iter(section_presets.values())))
    else:
        genre = DEFAULT_GENRE
    section_presets = {r: g for r, g in section_presets.items() if g != genre}

    understood.append(f"Genre: {label(genre)}")
    for role in ("intro", "verse", "chorus", "bridge", "outro"):
        if role in section_presets:
            understood.append(f"{role.capitalize()} → {label(section_presets[role])}")

    # Per-section overrides accumulate here (key/scale/tempo + playing style).
    section_overrides: dict[str, dict] = {}

    def _merge_override(role: str, eff: dict) -> None:
        cur = section_overrides.setdefault(role, {})
        for k, v in eff.items():
            if k == "knobs":
                cur.setdefault("knobs", {}).update(v)
            else:
                cur[k] = v

    _clause_seps = [i for i, c in enumerate(raw) if c in ",;"]

    def _bind_section(hs: int, he: int):
        """Bind a span to the nearest section IN THE SAME comma/semicolon
        clause — so "verse in A minor, chorus in C" ties each key to its own
        clause's section rather than leaking across the comma."""
        cs = max([s + 1 for s in _clause_seps if s < hs], default=0)
        ce = min([s for s in _clause_seps if s >= he], default=len(raw))
        best, best_d = None, 10 ** 9
        for (ss, se, r) in section_hits:
            if ss < cs or se > ce:
                continue
            d = ss - he if ss >= he else hs - se
            if d < best_d:
                best, best_d = r, d
        return best

    # ── key / scale (per-section modulations + the song key) ─────────────────
    key: Optional[str] = None
    scale: Optional[str] = None
    for (ks, ke, kk, ksc) in _find_key_matches(raw):
        role = _bind_section(ks, ke)
        if role:
            _merge_override(role, {"key": kk, "scale": ksc})
            understood.append(f"{role.capitalize()} key: {kk} {ksc.replace('_', ' ')}")
        elif key is None:
            key, scale = kk, ksc
    if key:
        understood.append(f"Key: {key} {(scale or 'major').replace('_', ' ')}")

    # ── tempo (song tempo + per-section half/double-time) ────────────────────
    tempo: Optional[float] = None
    bm = _BPM_RE.search(low) or _AT_BPM_RE.search(low)
    if bm:
        tempo = float(int(bm.group(1)))
    else:
        wt = _first_match(low, [(p, str(v)) for p, v in _WORD_TEMPOS])
        if wt:
            tempo = float(int(wt[2]))
    if tempo:
        understood.append(f"Tempo: {int(tempo)} BPM")
    for m in _HALF_DOUBLE_RE.finditer(raw):
        factor = 0.5 if m.group(1).lower() == "half" else 2.0
        role = _bind_section(m.start(), m.end())
        bt = round((tempo or 120.0) * factor)
        if role:
            _merge_override(role, {"tempo": float(bt)})
            understood.append(
                f"{role.capitalize()} tempo: {bt} BPM "
                f"({'half' if factor < 1 else 'double'}-time)")
        else:
            notes.append(
                f"Noticed {m.group(1).lower()}-time but couldn't tie it to a "
                "section — name one (e.g. “half-time bridge”).")

    # ── swing ────────────────────────────────────────────────────────────────
    swing: Optional[float] = None
    if re.search(r"\b(swing|shuffle|swung|triplet\s+feel)\b", low):
        swing = 0.33
        understood.append("Feel: swing/shuffle")
    elif re.search(r"\bstraight\b", low):
        swing = 0.0
        understood.append("Feel: straight")

    # ── instruments ──────────────────────────────────────────────────────────
    instruments: list[str] = []
    for (_, _, iid) in _all_matches(raw, _INSTRUMENT_LEXICON):
        if iid in INSTRUMENT_REGISTRY and iid not in instruments:
            instruments.append(iid)
    if instruments:
        regn = INSTRUMENT_REGISTRY
        understood.append("Add: " + ", ".join(
            getattr(regn.get(i), "label", i) for i in instruments))

    # ── playing-style hints → per-section overrides ──────────────────────────
    # Bind each hint to the nearest section (same adjacency rule as genres);
    # an unbound "solo" defaults to the bridge (the classic spot). Bound hints
    # become section_overrides; anything we can't place becomes a note.
    hint_hits = _all_matches(raw, _STYLE_HINTS)
    unplaced: list[str] = []
    applied: set[tuple[str, str]] = set()   # (role, kind) already recorded
    for (hs, he, kind) in hint_hits:
        # A style word modifies the section in its clause ("big chorus", "solo
        # in the bridge").
        role = _bind_section(hs, he)
        if role is None and kind == "solo":
            role = "bridge"             # default solo location
        eff = _HINT_EFFECT.get(kind)
        if role and eff:
            if (role, kind) in applied:
                continue
            applied.add((role, kind))
            _merge_override(role, eff)
            if kind == "solo" and "lead_guitar" not in instruments:
                instruments.append("lead_guitar")
            understood.append(f"{role.capitalize()} → {_HINT_DESC[kind]}")
        else:
            d = _HINT_DESC.get(kind, kind)
            if d not in unplaced:
                unplaced.append(d)
    if unplaced:
        notes.append(
            "Noticed " + ", ".join(unplaced)
            + " — couldn't tie that to a specific section, so it wasn't applied. "
              "Try naming the section (e.g. “big chorus”, “sparse intro”).")

    return {
        "genre": genre,
        "key": key,
        "scale": scale,
        "tempo": tempo,
        "swing": swing,
        "sections": [],                 # leave empty → genre's full arrangement
        "section_presets": section_presets,
        "section_overrides": section_overrides,
        "instruments": instruments,
        "understood": understood,
        "notes": notes,
    }
