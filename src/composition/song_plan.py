"""Song plans: the one shape every "describe / revise my song" interpreter
produces (Claude through the AI request queue, the local model, or the rules).

A plan IS a ``GenerateRequest`` body (src/api/schemas.py): genre, key, tempo,
sections, instruments, the per-engine options (arrangement variants, lead
voice, hits, hit style) and the delivered loudness. ``normalize_plan`` turns
whatever an interpreter returned into a valid plan — unknown options are
dropped with a note, numbers are clamped, conflicting variants are resolved —
so a bad model answer can never crash generation.

Engines: each genre runs on an engine (``ENGINES``). Funk Fusion is the
high-quality one with arrangement variants; everything else goes to the
general ``compose_song`` path. A new engine plugs in by adding an
``EngineSpec`` (its genres + which options it honors) — the validator, the
summaries and the interpreter prompt all read from here and from
``song_plan_guide.md``, the single explanation of the options and the
producer's taste.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

GUIDE_PATH = Path(__file__).with_name("song_plan_guide.md")

ROLES = ("intro", "verse", "prechorus", "chorus", "bridge", "outro")
HIT_STYLES = ("punch", "groove")
_NOTE_RE = re.compile(r"^([A-Ga-g])([#b♯♭]?)$")
# The fields an interpreter may set (all GenerateRequest fields; the output
# conveniences — stems, PDF, save-as-block — stay the form's business).
PLAN_FIELDS = ("genre", "key", "scale", "tempo", "swing", "seed", "sections",
               "section_presets", "section_overrides", "instruments", "arrangement",
               "lead_patch", "hits", "hit_style", "target_lufs", "tune", "length_seconds",
               "remove_sections")
# Edits an answer may give instead of restating a list: add/remove
# arrangement variants or band members. Small models revise far more reliably
# this way (restating the arrangement, they drop variants nobody asked about).
EDIT_FIELDS = ("add_variants", "remove_variants", "add_instruments", "remove_instruments")


@dataclass(frozen=True)
class EngineSpec:
    """What one composition engine honors. ``genres`` empty = the fallback
    engine for every genre no other engine claims."""
    id: str
    label: str
    genres: frozenset = frozenset()
    arrangement_variants: tuple = ()
    lead_patches: bool = False            # honors lead_patch
    hits: bool = False                    # honors hits / hit_style
    # Variant → instruments it needs in the band (added when the plan uses it).
    variant_instruments: dict = field(default_factory=dict)
    # Groups of mutually exclusive variants (one per part).
    exclusive: tuple = ()
    # Shorthand variant → the per-part variants it stands for.
    expands: dict = field(default_factory=dict)
    tunes: bool = False                   # honors tune (a public-domain carol or "original")
    # Loudness a "background" request means for this engine's music.
    background_lufs: float = -25.0


def _funk_fusion() -> EngineSpec:
    from src.composition.funk_fusion import ARRANGEMENT_INSTRUMENTS, ARRANGEMENT_VARIANTS
    return EngineSpec(
        id="funk_fusion", label="Funk Fusion", genres=frozenset({"funk_fusion_full"}),
        arrangement_variants=tuple(ARRANGEMENT_VARIANTS), lead_patches=True, hits=True,
        variant_instruments=dict(ARRANGEMENT_INSTRUMENTS),
        # In engine precedence order; the variant the latest revision ADDED wins.
        exclusive=(("pocket_bass", "simple_bass", "calm_bass"),
                   ("calm_drums", "pocket_drums"),
                   ("falloff", "no_falloff")),
        expands={"calm": ("calm_drums", "calm_bass", "calm_keys")},
    )


def _christmas() -> EngineSpec:
    from src.composition.christmas import ARRANGEMENT_INSTRUMENTS, ARRANGEMENT_VARIANTS, STYLE_IDS
    return EngineSpec(
        id="christmas", label="Christmas", genres=frozenset(STYLE_IDS),
        arrangement_variants=tuple(ARRANGEMENT_VARIANTS),
        variant_instruments=dict(ARRANGEMENT_INSTRUMENTS),
        exclusive=(("key_change", "no_key_change"), ("plain_harmony", "rich_harmony"),
                   ("strings_ending", "celesta_ending"), ("backing_track", "guide_melody")),
        tunes=True,
        # Christmas ambience IS the video's sound (no voice over it): about
        # -16 LUFS, a little under YouTube's -14.
        background_lufs=-16.0,
    )


COMPOSE_SONG = EngineSpec(id="compose_song", label="General composer")
_ENGINES: Optional[list[EngineSpec]] = None


def engines() -> list[EngineSpec]:
    global _ENGINES
    if _ENGINES is None:
        _ENGINES = [_funk_fusion(), _christmas(), COMPOSE_SONG]
    return _ENGINES


def engine_for(genre: str) -> EngineSpec:
    for e in engines():
        if genre in e.genres:
            return e
    return COMPOSE_SONG


def _lead_voices() -> tuple:
    from src.audio_processing.render.lead_voices import LEAD_VOICES
    return tuple(LEAD_VOICES)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------
class PlanError(ValueError):
    """The interpreter's answer isn't a usable plan at all."""


def _num(v, lo: float, hi: float) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f != f:   # NaN
        return None
    return max(lo, min(hi, f))


def _key(v) -> Optional[str]:
    m = _NOTE_RE.match(str(v or "").strip())
    if not m:
        return None
    acc = {"♯": "#", "♭": "b"}.get(m.group(2), m.group(2))
    return m.group(1).upper() + acc


def _scale(v) -> Optional[str]:
    from src.daw_integration.generic.midi_export import SCALES
    s = str(v or "").strip().lower().replace(" ", "_")
    s = {"maj": "major", "min": "minor", "aeolian": "minor", "ionian": "major"}.get(s, s)
    return s if s in SCALES else None


def _genre(v) -> Optional[str]:
    from src.daw_integration.generic.styles import STYLES
    g = str(v or "").strip()
    if g in STYLES:
        return g
    low = g.lower().replace("-", " ").replace("_", " ")
    for k, p in STYLES.items():
        if low in (k.replace("_", " "), p.name.lower()):
            return k
    if "fusion" in low:
        return "funk_fusion_full"
    from src.composition.christmas import christmas_genre
    return christmas_genre(low)


def _tune(v, eng: EngineSpec, notes: list[str]) -> Optional[str]:
    """A carol id (or "original") for engines that play tunes."""
    from src.composition.carols import carol
    from src.composition.christmas import denied_song, tune_from_text
    text = str(v or "").strip()
    if not eng.tunes:
        notes.append(f"{eng.label} doesn't play carols; ignored tune {text!r}.")
        return None
    if text.lower() in ("original", "new", ""):
        return "original"
    if denied_song(text):
        notes.append(f"{text!r} is a copyrighted song, so it can't be arranged; using an original tune.")
        return "original"
    t = carol(text)
    tid = t.id if t else tune_from_text(text)
    if not tid:
        notes.append(f"Unknown carol {text!r}; using an original tune.")
        return "original"
    return tid


def split_variants(arr) -> list[str]:
    if isinstance(arr, (list, tuple)):
        arr = ",".join(str(a) for a in arr)
    return [a.strip() for a in str(arr or "").replace("+", ",").split(",") if a.strip()]


def _expand(vs: list[str], eng: EngineSpec, always: bool = False) -> tuple[list[str], set[str]]:
    """Replace a shorthand variant ("calm") by its per-part variants when one
    of them conflicts with another variant in the list (or ``always``).
    Returns the list and the variants that came from expansion."""
    out, implied = list(vs), set()
    for short, parts in eng.expands.items():
        if short not in out:
            continue
        others = set(out) - {short}
        if always or any(set(g) & set(parts) and set(g) & others for g in eng.exclusive):
            i = out.index(short)
            new = [p for p in parts if p not in out]
            out[i:i + 1] = new
            implied |= set(new)
    return out, implied


def _clean_variants(arr, eng: EngineSpec, previous, notes: list[str]) -> str:
    """Known variants only, shorthand expanded when it conflicts, one variant
    per exclusive group, canonical order. In a conflict the variant asked for
    explicitly and newly (vs ``previous``) wins: "bass too busy" adding
    simple_bass beats the pocket_bass that was already there."""
    want = split_variants(arr)
    if not eng.arrangement_variants:
        if want:
            notes.append(f"{eng.label} has no arrangement variants; ignored {', '.join(want)}.")
        return ""
    unknown = [v for v in want if v not in eng.arrangement_variants]
    if unknown:
        notes.append("Ignored unknown arrangement option(s): " + ", ".join(unknown) + ".")
    vs = [v for v in dict.fromkeys(want) if v in eng.arrangement_variants]
    vs, implied = _expand(vs, eng)
    before = set(_expand(split_variants(previous), eng, always=True)[0])
    for group in eng.exclusive:
        present = [v for v in vs if v in group]
        if len(present) > 1:
            keep = min(present, key=lambda v: (2 if v in before else 1 if v in implied else 0,
                                               group.index(v)))
            vs = [v for v in vs if v not in group or v == keep]
    order = {v: i for i, v in enumerate(eng.arrangement_variants)}
    return ",".join(sorted(vs, key=lambda v: order[v]))


def _clean_override(o: Any, eng: EngineSpec, prev: Any, notes: list[str]) -> dict:
    if not isinstance(o, dict):
        return {}
    out: dict = {}
    if o.get("energy") is not None and (e := _num(o["energy"], 0.4, 1.5)) is not None:
        out["energy"] = round(e, 2)
    if o.get("bars") is not None and (b := _num(o["bars"], 1, 64)) is not None:
        out["bars"] = int(b)
    if o.get("tempo") is not None and (t := _num(o["tempo"], 40, 260)) is not None:
        out["tempo"] = round(t, 1)
    if o.get("key") and (k := _key(o["key"])):
        out["key"] = k
    if o.get("scale") and (s := _scale(o["scale"])):
        out["scale"] = s
    if o.get("feature_lead"):
        out["feature_lead"] = True
    if isinstance(o.get("knobs"), dict):
        knobs = {str(k): float(v) for k, v in o["knobs"].items() if _num(v, -1e9, 1e9) is not None}
        if knobs:
            out["knobs"] = knobs
    # Section-builder settings ride along untouched (validated by the engine).
    if isinstance(o.get("progression"), list) and o["progression"]:
        out["progression"] = o["progression"]
    if isinstance(o.get("instruments"), list) and o["instruments"]:
        from src.composition.instruments import INSTRUMENT_REGISTRY
        ids = [str(i) for i in o["instruments"] if str(i) in INSTRUMENT_REGISTRY]
        if ids:
            out["instruments"] = ids
    if o.get("arrangement") is not None:
        out["arrangement"] = _clean_variants(o["arrangement"], eng,
                                             (prev or {}).get("arrangement"), notes)
    return out


def normalize_plan(raw: Any, previous: Optional[dict] = None,
                   default_genre: str = "pop_full_song") -> tuple[dict, list[str]]:
    """Validate an interpreter's plan into a GenerateRequest-compatible dict.

    ``previous`` (revisions) is the plan being revised: a field the answer
    leaves out keeps its previous value, an explicit ``null`` removes it.
    Returns ``(plan, notes)``; notes say what was dropped or clamped. Raises
    ``PlanError`` only when ``raw`` isn't a plan at all.
    """
    from src.api.schemas import GenerateRequest
    from src.composition.instruments import INSTRUMENT_REGISTRY
    from src.daw_integration.generic.styles import STYLES

    if not isinstance(raw, dict):
        raise PlanError("the answer is not a JSON object")
    prev = dict(previous or {})
    merged = {k: v for k, v in prev.items() if k in PLAN_FIELDS}
    for k, v in raw.items():
        if k in PLAN_FIELDS:
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
    edits = {k: [str(x) for x in raw[k]] if isinstance(raw.get(k), list) else split_variants(raw.get(k))
             for k in EDIT_FIELDS if raw.get(k)}
    if not merged and not edits:
        raise PlanError("the answer has no plan fields")
    if edits.get("add_variants") or edits.get("remove_variants"):
        rem = set(edits.get("remove_variants", ()))
        vs = [v for v in split_variants(merged.get("arrangement")) if v not in rem]
        merged["arrangement"] = ",".join(vs + [v for v in edits.get("add_variants", ()) if v not in vs])

    notes: list[str] = []
    plan: dict = {}
    g = _genre(merged.get("genre"))
    if merged.get("genre") is not None and g is None:
        notes.append(f"Unknown genre {merged.get('genre')!r}; kept {prev.get('genre') or default_genre}.")
    plan["genre"] = g or _genre(prev.get("genre")) or default_genre
    eng = engine_for(plan["genre"])

    if merged.get("key") is not None:
        if k := _key(merged["key"]):
            plan["key"] = k
        else:
            notes.append(f"Ignored key {merged['key']!r}.")
    if merged.get("scale") is not None:
        if s := _scale(merged["scale"]):
            plan["scale"] = s
        else:
            notes.append(f"Ignored scale {merged['scale']!r}.")
    if (t := _num(merged.get("tempo"), 40, 260)) is not None:
        plan["tempo"] = round(t, 1)
    if (sw := _num(merged.get("swing"), 0, 0.6)) is not None:
        plan["swing"] = round(sw, 2)
    if merged.get("seed") is not None and (sd := _num(merged["seed"], 0, 2**31 - 1)) is not None:
        plan["seed"] = int(sd)
    if isinstance(merged.get("sections"), list):
        roles = [r for r in (str(x).lower() for x in merged["sections"]) if r in ROLES]
        if roles:
            plan["sections"] = list(dict.fromkeys(roles))
    # Sections removed on the timeline (indices into the arranged list) only
    # mean anything for the section list they were picked from.
    if isinstance(merged.get("remove_sections"), list) and merged.get("sections") == prev.get("sections"):
        idx = sorted({int(x) for x in merged["remove_sections"]
                      if isinstance(x, (int, float)) and not isinstance(x, bool) and 0 <= x < 256})
        if idx:
            plan["remove_sections"] = idx
    if isinstance(merged.get("section_presets"), dict):
        sp = {r: _genre(p) for r, p in merged["section_presets"].items() if r in ROLES}
        sp = {r: p for r, p in sp.items() if p and p != plan["genre"]}
        if sp:
            plan["section_presets"] = sp
    if isinstance(merged.get("section_overrides"), dict):
        prev_ov = prev.get("section_overrides") or {}
        so = {r: _clean_override(o, eng, prev_ov.get(r), notes)
              for r, o in merged["section_overrides"].items() if r in ROLES}
        so = {r: o for r, o in so.items() if o}
        if so:
            plan["section_overrides"] = so

    arr = _clean_variants(merged.get("arrangement"), eng, prev.get("arrangement"), notes)
    if arr:
        plan["arrangement"] = arr

    if edits.get("add_instruments") or edits.get("remove_instruments"):
        rem = set(edits.get("remove_instruments", ()))
        band = merged.get("instruments") if isinstance(merged.get("instruments"), list) \
            else list(STYLES[plan["genre"]].default_instruments)
        band = [i for i in band if i not in rem]
        merged["instruments"] = band + [i for i in edits.get("add_instruments", ()) if i not in band]
    if isinstance(merged.get("instruments"), list):
        inst = [str(i) for i in merged["instruments"]]
        bad = [i for i in inst if i not in INSTRUMENT_REGISTRY]
        if bad:
            notes.append("Ignored unknown instrument(s): " + ", ".join(bad) + ".")
        inst = [i for i in dict.fromkeys(inst) if i in INSTRUMENT_REGISTRY]
        if inst:
            plan["instruments"] = inst
    # Variants that need players in the band bring them along.
    used = set(split_variants(arr)) | {v for o in (plan.get("section_overrides") or {}).values()
                                       for v in split_variants(o.get("arrangement"))}
    needs = [i for v in used for i in eng.variant_instruments.get(v, ())]
    if needs:
        base = plan.get("instruments") or list(STYLES[plan["genre"]].default_instruments)
        plan["instruments"] = base + [i for i in dict.fromkeys(needs) if i not in base]

    if merged.get("lead_patch") is not None:
        lp = str(merged["lead_patch"]).strip().lower()
        if eng.lead_patches and lp in _lead_voices():
            plan["lead_patch"] = lp
        else:
            notes.append(f"Ignored lead voice {merged['lead_patch']!r}"
                         + ("" if eng.lead_patches else f" ({eng.label} has no lead voices)") + ".")
    if merged.get("hits") is not None:
        if not eng.hits:
            if merged["hits"]:
                notes.append(f"{eng.label} doesn't play hit points; ignored them.")
        elif isinstance(merged["hits"], list):
            hs = sorted({round(h, 3) for h in (_num(x, 0, 3600) for x in merged["hits"]) if h is not None})
            plan["hits"] = hs[:64]
    if merged.get("hit_style") is not None:
        hst = str(merged["hit_style"]).strip().lower()
        if eng.hits and hst in HIT_STYLES:
            plan["hit_style"] = hst
    if (lu := _num(merged.get("target_lufs"), -40, -6)) is not None:
        plan["target_lufs"] = round(lu, 1)
    if merged.get("tune") is not None:
        plan_tune = _tune(merged["tune"], eng, notes)
        if plan_tune:
            plan["tune"] = plan_tune
    if (ls := _num(merged.get("length_seconds"), 30, 600)) is not None:
        plan["length_seconds"] = round(ls)

    GenerateRequest.model_validate(plan)        # the contract: always a valid /generate body
    return plan, notes


# --------------------------------------------------------------------------
# Plain-English read-backs
# --------------------------------------------------------------------------
def plan_chips(plan: dict) -> list[str]:
    """Short "here's what I understood" chips for a plan."""
    from src.daw_integration.generic.styles import STYLES
    p = STYLES.get(plan.get("genre", ""))
    chips = [p.name if p else plan.get("genre", "?")]
    if plan.get("tune"):
        from src.composition.carols import carol
        t = carol(plan["tune"]) if plan["tune"] != "original" else None
        chips.append(t.title if t else "Original tune")
    if plan.get("length_seconds"):
        sec = int(plan["length_seconds"])
        chips.append(f"About {sec // 60}:{sec % 60:02d}")
    if plan.get("tempo"):
        chips.append(f"{plan['tempo']:g} BPM")
    if plan.get("key") or plan.get("scale"):
        chips.append(" ".join(x for x in (plan.get("key"), plan.get("scale")) if x))
    if plan.get("swing"):
        chips.append("Swing")
    if plan.get("arrangement"):
        chips.append(plan["arrangement"].replace(",", " + "))
    if plan.get("lead_patch"):
        chips.append(f"Lead: {plan['lead_patch']}")
    if "hits" in plan:
        chips.append(f"{len(plan['hits'])} hits" if plan["hits"] else "No stabs")
    if plan.get("hit_style"):
        chips.append(f"Hits: {plan['hit_style']}")
    if plan.get("target_lufs") is not None:
        chips.append(f"{plan['target_lufs']:g} LUFS" + (" (background)" if plan["target_lufs"] <= -20 else ""))
    if plan.get("sections"):
        chips.append("Sections: " + ", ".join(plan["sections"]))
    for role, o in (plan.get("section_overrides") or {}).items():
        bits = [f"{k} {v}" for k, v in o.items() if k != "knobs"]
        if bits:
            chips.append(f"{role.capitalize()}: " + ", ".join(bits))
    if plan.get("instruments"):
        chips.append("Band: " + ", ".join(plan["instruments"]))
    return chips


def describe_changes(old: dict, new: dict) -> list[str]:
    """What a revision changed, field by field (independent of what the
    interpreter claims it did)."""
    out: list[str] = []
    for k in PLAN_FIELDS:
        a, b = old.get(k), new.get(k)
        if a == b:
            continue
        if k == "arrangement":
            va, vb = split_variants(a), split_variants(b)
            add = [v for v in vb if v not in va]
            rem = [v for v in va if v not in vb]
            out.append("Arrangement: " + ", ".join([f"+{v}" for v in add] + [f"−{v}" for v in rem]))
        elif k == "instruments":
            a = a or list(_preset_band(old.get("genre", "")))
            b = b or list(_preset_band(new.get("genre", "")))
            add = [v for v in b if v not in a]
            rem = [v for v in a if v not in b]
            if not add and not rem:
                continue
            out.append("Band: " + ", ".join([f"+{v}" for v in add] + [f"−{v}" for v in rem]))
        elif k == "hits":
            out.append("No stabs" if b == [] else f"Hits: {len(b or [])}")
        elif k == "section_overrides":
            out += _section_changes(a or {}, b or {})
        elif k == "remove_sections":
            out.append("Removed sections: " + (", ".join(str(i + 1) for i in b) if b else "none"))
        elif b is None:
            out.append(f"{k}: back to default")
        elif isinstance(b, (dict, list)):
            out.append(f"{k}: {json.dumps(b)}")
        else:
            out.append(f"{k}: {a if a is not None else 'default'} → {b}")
    return out


def _section_changes(old: dict, new: dict) -> list[str]:
    """One line per section whose override changed, e.g. "Chorus: energy
    1 → 1.25" or "Chorus arrangement: +soar, −hits_only"."""
    out: list[str] = []
    for role in dict.fromkeys([*old, *new]):
        a, b = old.get(role) or {}, new.get(role) or {}
        bits = []
        for k in dict.fromkeys([*a, *b]):
            if a.get(k) == b.get(k):
                continue
            if k == "arrangement":
                va, vb = split_variants(a.get(k)), split_variants(b.get(k))
                ch = [f"+{v}" for v in vb if v not in va] + [f"−{v}" for v in va if v not in vb]
                bits.append("arrangement " + (", ".join(ch) if b.get(k) is not None else "back to the song's"))
            elif b.get(k) is None:
                bits.append(f"{k} back to default")
            elif isinstance(b.get(k), (dict, list)):
                bits.append(f"{k} {json.dumps(b[k])}")
            else:
                bits.append(f"{k} {a.get(k) if a.get(k) is not None else 'default'} → {b[k]}")
        if bits:
            out.append(f"{role.capitalize()}: " + "; ".join(bits))
    return out


# --------------------------------------------------------------------------
# Rule-based last resort
# --------------------------------------------------------------------------
Op = Callable[[dict], Optional[str]]


def _variants(add: tuple = (), remove: tuple = ()) -> Op:
    """Add/remove arrangement variants; variants the plan's engine doesn't
    have are left out (each engine names its own options)."""
    def op(plan: dict) -> Optional[str]:
        known = engine_for(plan.get("genre", "")).arrangement_variants
        vs = [v for v in split_variants(plan.get("arrangement")) if v not in remove]
        vs += [v for v in add if v not in vs and v in known]
        plan["arrangement"] = ",".join(vs)
        return None
    return op


def _set(**kv) -> Op:
    def op(plan: dict) -> Optional[str]:
        plan.update(kv)
        return None
    return op


def _bass_down(plan: dict) -> Optional[str]:
    vs = split_variants(plan.get("arrangement"))
    nxt = "calm_bass" if "simple_bass" in vs else "simple_bass"
    vs = [v for v in vs if v not in ("pocket_bass", "simple_bass")] + [nxt]
    plan["arrangement"] = ",".join(vs)
    return None


def _slower(plan: dict) -> Optional[str]:
    from src.daw_integration.generic.styles import STYLES
    p = STYLES.get(plan.get("genre", ""))
    t = float(plan.get("tempo") or (p.tempo if p else 120))
    plan["tempo"] = round(t * 0.88)
    return None


def _faster(plan: dict) -> Optional[str]:
    from src.daw_integration.generic.styles import STYLES
    p = STYLES.get(plan.get("genre", ""))
    t = float(plan.get("tempo") or (p.tempo if p else 120))
    plan["tempo"] = round(t * 1.1)
    return None


def _bigger_section(role: str) -> Op:
    def op(plan: dict) -> Optional[str]:
        so = plan.setdefault("section_overrides", {})
        o = so.setdefault(role, {})
        o["energy"] = min(1.5, round(float(o.get("energy") or 1.0) + 0.25, 2))
        return None
    return op


def _background(plan: dict) -> Optional[str]:
    plan["target_lufs"] = engine_for(plan.get("genre", "")).background_lufs
    return None


def _choir_pad(plan: dict) -> Optional[str]:
    if plan.get("genre") != "christmas_choir_full":      # the choir style already sings
        _variants(add=("choir_pad",))(plan)
    return None


def _key_of(plan: dict, voice: str) -> Optional[str]:
    """The plan's key, or (none set) a carol's voice-preset key / the style's."""
    if plan.get("key"):
        return plan["key"]
    from src.composition.carols import carol
    t = carol(plan.get("tune") or "") if plan.get("tune") not in (None, "", "original") else None
    if t is not None:
        from src.composition.backing import voice_key
        return voice_key(t, voice)
    from src.daw_integration.generic.styles import STYLES
    p = STYLES.get(plan.get("genre", ""))
    return p.key if p else None


def _shift_key(semis: int) -> Op:
    """"Lower key" / "higher key": a whole step from the plan's key (a carol
    with no key set goes to its low / high voice key instead)."""
    def op(plan: dict) -> Optional[str]:
        from src.composition.backing import key_pc, spell
        had = bool(plan.get("key"))
        k = _key_of(plan, "low" if semis < 0 else "high")
        if not k:
            return None
        plan["key"] = spell(key_pc(k) + (semis if had else 0), plan.get("scale") == "minor")
        return None
    return op


def _voice(voice: str) -> Op:
    def op(plan: dict) -> Optional[str]:
        from src.composition.carols import carol
        t = carol(plan.get("tune") or "") if plan.get("tune") not in (None, "", "original") else None
        if t is not None:
            from src.composition.backing import voice_key
            plan["key"] = voice_key(t, voice)
        return None
    return op


def _no_stabs(plan: dict) -> Optional[str]:
    plan["hits"] = []
    return _variants(remove=("horn_bed",))(plan)


def _drop_trumpet(plan: dict) -> Optional[str]:
    from src.daw_integration.generic.styles import STYLES
    p = STYLES.get(plan.get("genre", ""))
    band = plan.get("instruments") or list(p.default_instruments if p else [])
    plan["instruments"] = [i for i in band if i not in ("trumpet", "brass_section")]
    if plan.get("lead_patch") in ("trumpet", "trumpet_guitar", "layered", "horns"):
        plan["lead_patch"] = "guitar_stack"
    _variants(add=("no_falloff",), remove=("horn_bed",))(plan)
    return None


# (regex, op, what it means). Order matters only for readability; every match
# applies. The same phrases are documented in song_plan_guide.md.
FEEDBACK_RULES: list[tuple[str, Op, str]] = [
    (r"bass\b.{0,30}\b(too much|too busy|busy|simpler|calm(er)?|less)|(don'?t|not) follow(ing)? the drums"
     r"|\b(simpler|calmer|less busy) bass",
     _bass_down, "simpler bass"),
    (r"bass\b.{0,30}\b(flare|life)|occasional flare", _variants(add=("bass_flare",)), "bass flares"),
    (r"too many fills|fewer fills|drums?\b.{0,20}\b(too busy|busy|too much)|chad smith|ghost notes",
     _variants(add=("pocket_drums",), remove=("calm_drums",)), "pocket drums"),
    (r"\bbrush(es)?\b|drums?\b.{0,20}\btoo percussive|softer drums", _variants(add=("brushes",)), "brushes"),
    (r"\bno (stabs|hits)\b|(remove|drop|lose) the (stabs|hits)|stabs?\b.{0,30}\bout of place",
     _no_stabs, "no stabs"),
    (r"\bhits[\s_-]?only\b|just the hits|less complex|more impactful|70s (funk )?horns",
     _variants(add=("hits_only",)), "hits only"),
    (r"under (the )?(voice[\s-]?over|narration)|voice[\s-]?over", _set(target_lufs=-25.0), "under a voice-over"),
    (r"\bbackground\b|lower (the )?volume|quieter|under (the )?video|bed\b", _background, "background level"),
    (r"too fast|slower|slow (it|this) down", _slower, "slower"),
    (r"(bigger|louder|lift the) chorus|chorus\b.{0,20}\b(bigger|lift|more energy)", _bigger_section("chorus"),
     "bigger chorus"),
    (r"too slow|faster|speed (it|this) up", _faster, "faster"),
    (r"\bsoar|\bstrings?\b|bigger without", _variants(add=("soar",)), "soaring strings"),
    (r"fall[\s-]?off|held (note|ending)|ending\b.{0,20}\b(silly|cute|comic)", _variants(add=("no_falloff",)),
     "held ending"),
    (r"\bno trumpets?\b|(remove|drop|lose) the trumpets?", _drop_trumpet, "no trumpet"),
    (r"end(ing)? on the strings", _variants(add=("soar", "no_falloff")), "strings ending"),
    (r"horns? (build|climb|grow)|horn bed", _variants(add=("horn_bed",)), "horns build to hits"),
    (r"keys?\b.{0,20}\b(too busy|too much|simpler|calm)", _variants(add=("calm_keys",)), "calm keys"),
    (r"preschool|too plain|more life", _variants(add=("pocket_drums", "bass_flare"), remove=("calm", "calm_drums")),
     "more life"),
    (r"\bcalmer\b|more calm|calm (it|this|things) down|laid[\s-]?back|\bchill", _variants(add=("calm_keys", "simple_bass")),
     "calmer"),
    # Christmas
    (r"less busy|too busy|simpler|calmer|more calm|too much going on", _variants(add=("less_busy",)), "less busy"),
    (r"\bwarm(er)?\b|cozier|\bcosy|\bcozy|darker|softer", _variants(add=("warmer",)), "warmer"),
    (r"sleigh[\s-]?bells?", _variants(add=("sleigh_bells",)), "sleigh bells"),
    (r"end(ing)? on (the )?(celesta|glock\w*|bells)", _variants(add=("celesta_ending",), remove=("strings_ending",)),
     "celesta ending"),
    (r"end(ing)? on (the )?strings", _variants(add=("strings_ending",), remove=("celesta_ending",)), "strings ending"),
    (r"\bno key change|stay in (one|the same) key|don'?t (change|modulate)", _variants(add=("no_key_change",),
     remove=("key_change",)), "no key change"),
    (r"(?<!no )(?<!without a )\bkey change\b|(?<!don't )(?<!dont )\bmodulate\b|lift (it|the last)",
     _variants(add=("key_change",), remove=("no_key_change",)), "key change"),
    (r"\b(add (a )?)?choir\b|voices", _choir_pad, "choir pad"),
    (r"jazz(ier)? (chords|harmony)|richer (chords|harmony)|reharm", _variants(add=("rich_harmony",),
     remove=("plain_harmony",)), "richer harmony"),
    (r"simple (chords|harmony)|as written|traditional (chords|harmony)", _variants(add=("plain_harmony",),
     remove=("rich_harmony",)), "plain harmony"),
    # Backing tracks (sing / play along)
    (r"backing[\s-]?track|karaoke|sing[\s-]?along|play[\s-]?along|minus[\s-]?one|accompaniment only"
     r"|\bno (melody|lead|tune)\b|without (the |a )?(melody|lead|tune)|(drop|remove|lose|mute) the (melody|lead|tune)",
     _variants(add=("backing_track",), remove=("guide_melody",)), "backing track"),
    (r"guide[\s-]?melody|with a guide|(quiet|soft|faint) (guide|melody)|melody (very |really )?(quiet|soft)",
     _variants(add=("guide_melody",), remove=("backing_track",)), "guide melody"),
    (r"\blower (the )?key|key (down|lower)|in a lower key|drop the key|transpose (it )?down",
     _shift_key(-2), "lower key"),
    (r"\bhigher (the )?key|key (up|higher)|in a higher key|raise the key|transpose (it )?up",
     _shift_key(2), "higher key"),
    (r"\blow(er)? voice|\balto\b|\bbaritone\b|deep voice", _voice("low"), "low voice"),
    (r"\bhigh(er)? voice|\bsoprano\b", _voice("high"), "high voice"),
]


def apply_feedback_rules(plan: dict, text: str, describing: bool = False) -> list[str]:
    """Apply every matching feedback rule to ``plan`` in place; returns the
    labels of the rules that fired. Variant names written out ("simple bass",
    "pocket drums", "hits only") add that variant on engines that have it —
    anywhere in a description, but in feedback only when asked for ("use
    brushes"), since feedback names variants to complain about them too
    ("calm drums + calm bass sounds like preschool")."""
    low = (text or "").lower()
    fired: list[str] = []
    eng = engine_for(plan.get("genre", ""))
    ask = "" if describing else r"\b(use|add|try|with|want|go with|switch to)\s+(the\s+|a\s+|some\s+)?"
    for v in eng.arrangement_variants:
        if re.search(ask + r"\b" + v.replace("_", r"[\s_-]?") + r"\b", low) and \
                v not in split_variants(plan.get("arrangement")):
            _variants(add=(v,))(plan)
            fired.append(v.replace("_", " "))
    for pattern, op, label in FEEDBACK_RULES:
        if re.search(pattern, low):
            op(plan)
            if label not in fired and label.replace(" ", "_") not in [f.replace(" ", "_") for f in fired]:
                fired.append(label)
    return fired


def rule_describe(text: str) -> tuple[dict, list[str], list[str]]:
    """Description → (raw plan, understood chips, notes) without a model."""
    from src.composition.nl_parser import parse_prompt
    parsed = parse_prompt(text)
    raw = {k: parsed[k] for k in ("genre", "key", "scale", "tempo", "swing",
                                  "section_presets", "section_overrides", "instruments", "tune")
           if parsed.get(k) not in (None, [], {})}
    if (m := re.search(r"(\d+(?:\.\d+)?)\s*(min(?:ute)?s?|sec(?:ond)?s?|s)\b", (text or "").lower())):
        n = float(m.group(1))
        raw["length_seconds"] = n * 60 if m.group(2).startswith("m") else n
    if raw.get("instruments"):
        # The parser lists only the instruments the text named; a plan's list
        # REPLACES the band, so add them to the genre's defaults (and leave it
        # out when they're all in the band already).
        from src.daw_integration.generic.styles import STYLES
        base = list(STYLES[raw["genre"]].default_instruments)
        extra = [i for i in raw["instruments"] if i not in base]
        if extra:
            raw["instruments"] = base + extra
        else:
            del raw["instruments"]
    _remove_instruments(raw, parsed.get("removed_instruments") or [])
    fired = apply_feedback_rules(raw, text, describing=True)
    return raw, parsed.get("understood", []) + [f.capitalize() for f in fired], parsed.get("notes", [])


def _remove_instruments(plan: dict, removed: list[str]) -> None:
    """Drop instruments the text excluded ("no piano") from the band."""
    if not removed:
        return
    from src.daw_integration.generic.styles import STYLES
    p = STYLES.get(plan.get("genre", ""))
    band = plan.get("instruments") or list(p.default_instruments if p else [])
    plan["instruments"] = [i for i in band if i not in removed]


def rule_revise(plan: dict, feedback: str) -> tuple[dict, list[str]]:
    """Plan + feedback → (raw revised plan, labels of what fired)."""
    from src.composition.nl_parser import _AT_BPM_RE, _BPM_RE, mentions_genre, parse_prompt
    from src.composition import christmas
    new = json.loads(json.dumps(plan))
    parsed = parse_prompt(feedback)
    if plan.get("genre") in christmas.STYLE_IDS:
        # A Christmas song stays Christmas: "make it orchestral" picks the
        # Christmas orchestral style; "add sleigh bells" changes no style.
        to = christmas.style_word(feedback)
        if to and to != plan.get("genre"):
            new["genre"] = to
        elif mentions_genre(feedback) and parsed["genre"] not in christmas.STYLE_IDS:
            new["genre"] = parsed["genre"]
    elif mentions_genre(feedback) and parsed["genre"] != plan.get("genre"):
        new["genre"] = parsed["genre"]
    for k in ("key", "scale"):
        if parsed.get(k) is not None:
            new[k] = parsed[k]
    if parsed.get("tune") and parsed["tune"] != plan.get("tune"):
        new["tune"] = parsed["tune"]
    # Only an explicit BPM; tempo words ("fast") are relative in feedback and
    # handled by the rules ("too fast" → slower).
    if parsed.get("tempo") is not None and (_BPM_RE.search(feedback) or _AT_BPM_RE.search(feedback)):
        new["tempo"] = parsed["tempo"]
    if parsed.get("instruments"):
        band = new.get("instruments") or list(_preset_band(new.get("genre", "")))
        new["instruments"] = band + [i for i in parsed["instruments"] if i not in band]
    _remove_instruments(new, parsed.get("removed_instruments") or [])
    fired = apply_feedback_rules(new, feedback)
    if parsed.get("instruments") or parsed.get("removed_instruments"):
        fired.append("band")
    return new, fired


def _preset_band(genre: str) -> tuple:
    from src.daw_integration.generic.styles import STYLES
    p = STYLES.get(genre)
    return tuple(p.default_instruments) if p else ()


# --------------------------------------------------------------------------
# Interpreter prompt (shared by Claude and the local model)
# --------------------------------------------------------------------------
def catalog_text() -> str:
    from src.composition.instruments import INSTRUMENT_REGISTRY
    from src.daw_integration.generic.styles import STYLES
    genres = "\n".join(f"- {k}: {p.name}" for k, p in STYLES.items())
    return ("## Catalog\n\nGenre ids:\n" + genres
            + "\n\nInstrument ids: " + ", ".join(INSTRUMENT_REGISTRY)
            + "\n\nLead voices: " + ", ".join(_lead_voices()) + "\n"
            + _variant_catalog())


def _variant_catalog() -> str:
    from src.composition import christmas
    from src.composition.carols import carol_catalog
    from src.composition.funk_fusion import ARRANGEMENT_VARIANTS
    return ("\nFunk Fusion arrangement variants:\n"
            + "\n".join(f"- `{k}`: {v}" for k, v in ARRANGEMENT_VARIANTS.items())
            + "\n\nChristmas styles:\n"
            + "\n".join(f"- `{k}`: {v}" for k, v in christmas.STYLE_INFO.items())
            + "\n\nChristmas arrangement variants:\n"
            + "\n".join(f"- `{k}`: {v}" for k, v in christmas.ARRANGEMENT_VARIANTS.items())
            + "\n\nChristmas tunes (`tune`; public-domain carols, or \"original\"):\n"
            + "\n".join(f"- `{k}`: {v['title']} ({v['meter']})" for k, v in carol_catalog().items()) + "\n")


def system_prompt() -> str:
    """The guide + the live catalog: everything an interpreter needs."""
    return GUIDE_PATH.read_text() + "\n" + catalog_text()


def user_prompt(kind: str, text: str = "", plan: Optional[dict] = None) -> str:
    if kind == "revise":
        return ("Revise this song plan.\n\nCurrent plan:\n" + json.dumps(plan or {})
                + f"\n\nFeedback: {text}\n\nReturn only the JSON object with ONLY the changes "
                  "(see “Revising”).")
    return (f"Song description: {text}\n\nReturn only the JSON object "
            "(see “Describing”).")


# --------------------------------------------------------------------------
# Robust parsing of model output
# --------------------------------------------------------------------------
_THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)


def _repair(s: str) -> str:
    s = re.sub(r",\s*([}\]])", r"\1", s)                       # trailing commas
    s = re.sub(r"\bTrue\b", "true", s)
    s = re.sub(r"\bFalse\b", "false", s)
    s = re.sub(r"\bNone\b", "null", s)
    s = s.replace("“", '"').replace("”", '"').replace("−", "-")
    return s


def _objects(text: str):
    dec = json.JSONDecoder()
    for src in (text, _repair(text)):
        i = src.find("{")
        while i != -1:
            try:
                obj, end = dec.raw_decode(src, i)
            except ValueError:
                i = src.find("{", i + 1)
                continue
            if isinstance(obj, dict):
                yield obj
            i = src.find("{", end)


def parse_model_output(out: Any) -> tuple[dict, str]:
    """Pull ``(plan, summary)`` out of whatever a model returned: a dict, JSON
    text, JSON in a code fence or after prose, a tool call
    (``{"name":…, "arguments":{…}}``, arguments possibly a JSON string), or a
    bare plan. Raises ``PlanError`` when there's no plan in it."""
    cands: list[dict] = []
    if isinstance(out, dict):
        cands.append(out)
    else:
        text = _THINK_RE.sub("", str(out or ""))
        text = re.sub(r"```(?:json)?", "", text)
        cands.extend(_objects(text))
    for obj in cands:
        for _ in range(3):   # unwrap tool-call / function envelopes
            args = obj.get("arguments", obj.get("parameters", obj.get("input")))
            if isinstance(args, str):
                try:
                    args = json.loads(_repair(args))
                except ValueError:
                    args = None
            if isinstance(args, dict) and "name" in obj:
                obj = args
                continue
            fn = obj.get("function")
            if isinstance(fn, dict) and "arguments" in fn:
                obj = {"name": fn.get("name"), "arguments": fn["arguments"]}
                continue
            break
        summary = str(obj.get("summary") or obj.get("understood") or "").strip()
        plan = obj.get("plan")
        if isinstance(plan, str):
            try:
                plan = json.loads(_repair(plan))
            except ValueError:
                plan = None
        edits = {k: obj[k] for k in EDIT_FIELDS if k in obj}
        if isinstance(plan, dict):
            return {**plan, **edits}, summary
        if any(k in obj for k in PLAN_FIELDS + EDIT_FIELDS):
            return {k: v for k, v in obj.items() if k in PLAN_FIELDS + EDIT_FIELDS}, summary
    raise PlanError("no song plan in the model's answer")
