"""``compose_song()`` — high-level random song generator.

Given a genre (style preset) and a master seed, picks one technique
per ``(instrument, section)`` cell from :data:`src.composition.BANK`
and applies them in order over the right bar range. Same seed →
same song; bump the seed → related variation.

Used by:

- The Gradio "🎲 Generate full song" button (writes selections back
  into the rhythm-overrides accordion).
- The MCP ``compose_song`` tool (exposes the same pipeline to an LLM).
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Optional

import numpy as np
import soundfile as sf

from src.composition import BANK, role_for_label
from src.composition.roles import SECTION_ROLES
from src.composition.harmony import harmony_profile
from src.composition.knobs import resolve_knobs
from src.composition.pacing import apply_pacing, pick_pacing, modal_color
from src.composition.techniques import TechniqueContext, apply_technique
from src.composition.voicing_layer import (
    assign_layered_voicings, effective_voicing,
)
from src.daw_integration.generic.midi_export import (
    MidiExporter, roman_to_semitone_offset, NOTE_NAMES, FLAT_TO_SHARP,
    inject_tempo_changes,
)
from src.daw_integration.generic.styles import STYLES


logger = logging.getLogger(__name__)

# Default output paths — same locations the Gradio MIDI Compose tab writes
# to so the Playback tab can pick up the new piece on its next reload.
DEFAULT_OUTPUT_DIR = Path("data/outputs/app")
DEFAULT_MIDI_NAME = "last_composition.mid"
DEFAULT_WAV_NAME = "last_composition.wav"


# Order matters — chords land first, bass second, then drums and
# melody. Some techniques (riff_pass) read the bass track that's
# already in place.
_INSTRUMENT_ORDER: tuple[str, ...] = ("chords", "bass", "drums", "melody")


# Preset name → preferred technique-bank tags. The bank stores each
# genre family's techniques tagged with a short token (``"pop"``,
# ``"rock"``, ``"funk_rock"``, …); :func:`TechniqueBank.pick` doubles
# the weight of any candidate carrying one of these tags so picking
# ``rock_anthem_full`` actually pulls rock idioms rather than the
# cross-genre baseline.
# Genres whose tagged techniques are the whole idiom: a cell with a tagged
# technique never falls back to the cross-genre pool (fusion's straight 16ths
# would be wrecked by a swing walking bass or a country train beat).
_STRICT_GENRES: frozenset[str] = frozenset({"fusion_full", "funk_fusion_full", "neo_soul_full"})

_GENRE_TAG_MAP: dict[str, tuple[str, ...]] = {
    # Pop / rock family.
    "pop":               ("pop",),
    "pop_full_song":     ("pop",),
    "pop_dynamic":       ("pop",),
    "rock":              ("rock",),
    "rock_anthem_full":  ("rock",),
    "rock_buildup":      ("rock",),
    # Funk.
    "funk":              ("funk_rock",),
    "funk_full_song":    ("funk_rock", "funk"),
    "funk_dynamic":      ("funk_rock", "funk"),
    # Jazz / blues.
    "jazz":              ("jazz",),
    "fusion_full":       ("fusion",),
    "funk_fusion_full":  ("funk_fusion",),
    "neo_soul_full":     ("neo_soul",),
    "jazz_aaba_full":    ("jazz",),
    "jazz_trade_fours":  ("jazz",),
    "blues_12bar_full":  ("blues",),
    # Ballad.
    "ballad":            ("ballad",),
    "ballad_full":       ("ballad",),
    # Electronic.
    "edm":               ("edm",),
    "edm_full_song":     ("edm",),
    # Hip-hop / metal (the two new presets shipped this round).
    "hip_hop_full":      ("hip_hop",),
    "metal_full":        ("metal",),
    # Newer genre packs.
    "country_full":      ("country",),
    "reggae_full":       ("reggae",),
    "disco_full":        ("disco",),
    "soul_motown_full":  ("soul",),
    # Jazz sub-styles — preferred_tags stacks: a bossa_jazz technique
    # tagged ("jazz", "bossa_jazz") under preferred_tags=("jazz",
    # "bossa_jazz") gets 5×5 = 25× boost vs. a plain "jazz" tech.
    "jazz_bossa_full":     ("jazz", "bossa_jazz"),
    "jazz_hard_bop_full":  ("jazz", "hard_bop"),
    "jazz_modal_full":     ("jazz", "modal_jazz"),
    "jazz_ballad_full":    ("jazz", "ballad_jazz"),
    "jazz_blues_full":     ("jazz", "blues", "jazz_blues"),
    "jazz_bebop_full":     ("jazz", "bebop"),
    "jazz_piano_full":     ("jazz", "piano"),
}


# ---------------------------------------------------------------------------
# Section spec helpers
# ---------------------------------------------------------------------------

# Distinct section TYPES the song templates actually produce, beyond the five
# canonical roles. Each keeps its own identity (selectable + independently
# controllable + its own energy/behaviour) but maps to a canonical technique
# role (its closest catalogue) so the technique bank always finds a fit.
SPECIAL_IDENTITIES: tuple[str, ...] = ("prechorus", "buildup", "drop",
                                       "breakdown", "solo")


def _section_identity(label: str) -> str:
    """A section's identity for arrangement / UI / per-section controls — finer
    than the canonical technique role. Order matters (solo before bridge so
    "Bridge / Solo" reads as a solo)."""
    lo = (label or "").lower()
    if "prechorus" in lo or "pre-chorus" in lo or "pre chorus" in lo:
        return "prechorus"
    if "solo" in lo:
        return "solo"
    if "buildup" in lo or "build up" in lo or "build-up" in lo or "build" in lo:
        return "buildup"
    if "breakdown" in lo or "break" in lo:
        return "breakdown"
    if "drop" in lo:
        return "drop"
    return role_for_label(label)


# Semitones from a mode's tonic to its PARENT MAJOR (the major key whose
# signature it shares). Lets a section in a different mode land on the global
# key's matching scale DEGREE — so it stays inside the global key signature.
_PARENT_OFFSET = {
    "major": 0, "ionian": 0, "dorian": 2, "phrygian": 4, "lydian": 5,
    "mixolydian": 7, "minor": 9, "aeolian": 9, "natural_minor": 9, "locrian": 11,
    "harmonic_minor": 9, "melodic_minor": 9, "pentatonic_minor": 9, "blues": 9,
    "pentatonic_major": 0,
}


def _relative_degree_key(global_key: str, global_scale: str, sec_scale: str) -> str:
    """The tonic that places ``sec_scale`` on the global key's matching scale
    degree, sharing its key signature: C major + minor → A (the vi); C major +
    dorian → D (the ii); A minor + major → C (the relative major)."""
    try:
        gp = NOTE_NAMES.index(FLAT_TO_SHARP.get(global_key, global_key)) % 12
    except ValueError:
        return global_key
    parent = (gp - _PARENT_OFFSET.get((global_scale or "major").lower(), 0)) % 12
    tonic = (parent + _PARENT_OFFSET.get((sec_scale or "major").lower(), 0)) % 12
    return NOTE_NAMES[tonic]


def _canonical_role(section: dict) -> str:
    """The canonical technique role (one of SECTION_ROLES) for a section —
    its own ``role`` if already canonical, else mapped from its label. A
    pre-chorus → verse, a solo/breakdown → bridge, a drop → chorus, a buildup
    → intro."""
    r = section.get("role") or role_for_label(section.get("label", ""))
    return r if r in SECTION_ROLES else role_for_label(section.get("label", ""))


def _default_sections_for(genre: str) -> list[dict]:
    """Pull section list from the genre's "Full song" rhythm_variant.

    Falls back to a generic 4-section template if the preset has no
    rhythm_variants — keeps callers honest without a hard requirement.
    """
    preset = STYLES.get(genre)
    if preset and preset.rhythm_variants:
        variant_name = next(iter(preset.rhythm_variants))
        rows = preset.rhythm_variants[variant_name]
        out: list[dict] = []
        for row in rows:
            s = int(row.get("start_bar", 0))
            e = int(row.get("end_bar", s))
            label = row.get("label", "") or f"Section {len(out) + 1}"
            out.append({
                "start_bar": s, "end_bar": e,
                "label": label, "role": _section_identity(label),
            })
        return out
    # Generic fallback — 32-bar four-section sketch.
    return [
        {"start_bar": 0,  "end_bar": 3,  "label": "Intro",  "role": "intro"},
        {"start_bar": 4,  "end_bar": 19, "label": "Verse",  "role": "verse"},
        {"start_bar": 20, "end_bar": 27, "label": "Chorus", "role": "chorus"},
        {"start_bar": 28, "end_bar": 31, "label": "Outro",  "role": "outro"},
    ]


def _plays_in_section(inst_obj, role: str, has_harmonic: bool) -> bool:
    """Conservative per-section arrangement mask — so not every instrument
    plays in every section. Core instruments (chords/bass/melody/lead) always
    play; only non-essential layers are dropped, and only when a harmonic
    voice still carries the section (never leaves it empty).

    - Backing vocals enter to lift the chorus/bridge/outro.
    - Add-on percussion layers lift the chorus/bridge.
    - The main kit holds off in the intro so the band kicks in at the verse.
    """
    if inst_obj is None:
        return True
    iid = getattr(inst_obj, "id", None)
    if iid == "vocal_harmony":
        return role in ("chorus", "bridge", "outro")
    if getattr(inst_obj, "role", None) == "percussion":   # latin_perc / hiphop_perc
        return role in ("chorus", "bridge")
    if iid == "drum_kit" and role == "intro" and has_harmonic:
        return False
    return True


def _lead_guitar_section_plan(sections: list[dict], seed: int,
                              knobs: Optional[dict] = None) -> set:
    """Which section indices the LEAD GUITAR is FEATURED in.

    A lead is featured, not wallpaper: it riffs the odd verse/interlude,
    sometimes takes the bridge as a solo, comes in for the FINAL chorus
    payoff, and — when the knobs allow — riffs the intro/outro. Probabilities
    scale with ``knobs['lead_amount']`` (and the intro/outro knobs).
    Deterministic per seed.
    """
    knobs = knobs or {}
    amt = knobs.get("lead_amount", 1.0)
    p_intro = knobs.get("lead_intro", 0.0)
    p_outro = knobs.get("lead_outro", 0.0)
    rng = np.random.default_rng(_sub_seed(seed, "lead_arrangement"))
    roled = [
        (i, (s.get("role") or role_for_label(s.get("label", ""))),
         (s.get("label", "") or "").lower())
        for i, s in enumerate(sections)
    ]
    play: set = set()

    def _hit(base):
        return rng.random() < min(1.0, base * amt)

    # Choruses: only the FINAL one (the big finish the lead joins).
    chorus_idxs = [i for i, r, _ in roled if r == "chorus"]
    if chorus_idxs and _hit(1.0):
        play.add(chorus_idxs[-1])

    # Verses / interludes: usually the last verse, earlier ones now and then.
    verse_idxs = [i for i, r, _ in roled if r == "verse"]
    for pos, i in enumerate(verse_idxs):
        if _hit(0.65 if pos == len(verse_idxs) - 1 else 0.25):
            play.add(i)

    # Bridge solo sometimes (more when literally labelled a solo); intro/
    # outro riffs per their own knobs, also scaled by lead_amount so
    # lead_amount=0 means no lead anywhere.
    for i, r, label in roled:
        if r == "solo" and _hit(0.95):           # a dedicated solo section
            play.add(i)
        elif r == "bridge" and _hit(0.85 if "solo" in label else 0.55):
            play.add(i)
        elif r == "intro" and rng.random() < min(1.0, p_intro * amt):
            play.add(i)
        elif r == "outro" and rng.random() < min(1.0, p_outro * amt):
            play.add(i)
    return play


def _lead_fill_sections(sections: list[dict], seed: int, knobs: dict,
                        featured: set) -> set:
    """Mid-song sections where the lead (not featured) drops a SHORT fill —
    a 1-bar turnaround pickup into the next section. Disjoint from the
    featured set. Probability = ``knobs['lead_fills']``."""
    prob = (knobs or {}).get("lead_fills", 0.0)
    if prob <= 0.0:
        return set()
    rng = np.random.default_rng(_sub_seed(seed, "lead_fills"))
    out: set = set()
    for i, s in enumerate(sections):
        if i in featured:
            continue
        role = s.get("role") or role_for_label(s.get("label", ""))
        if role in ("verse", "chorus", "bridge") and rng.random() < prob:
            out.add(i)
    return out


def _sub_seed(master: int, *parts) -> int:
    """Derive a stable sub-seed from the master + arbitrary labels.

    Hash-based so the resulting seeds aren't trivially correlated with
    each other (no "+ 1" colocation effect across cells).
    """
    h = hashlib.blake2b(digest_size=4)
    h.update(str(int(master)).encode())
    for p in parts:
        h.update(b"\0")
        h.update(str(p).encode())
    return int.from_bytes(h.digest(), "big") & 0x7FFFFFFF


def _slice_progression(progression: list, total_bars: int,
                       start_bar: int, end_bar: int) -> list:
    """Return the chord cells active in ``[start_bar, end_bar]``.

    Accepts either ``["I", "V", …]`` (legacy bare strings = 1 bar each)
    or ``[("I", 2.0), …]`` (paced tuples). Loops the cycle if shorter
    than the requested span; truncates the tail to fit.
    """
    if not progression:
        return progression
    # Normalise to tuples first so the loop below has one shape.
    normalised: list = []
    for entry in progression:
        if isinstance(entry, (tuple, list)) and len(entry) >= 2:
            normalised.append((entry[0], float(entry[1])))
        else:
            normalised.append((str(entry), 1.0))

    out: list = []
    bar_cursor = 0.0
    span = float(end_bar + 1 - start_bar)
    # Cap iterations defensively in case a 0-duration tuple sneaks in.
    for _ in range(max(1, int(span * 4))):
        if bar_cursor >= span - 1e-9:
            break
        for sym, dur in normalised:
            if bar_cursor >= span - 1e-9:
                break
            remaining = span - bar_cursor
            out.append((sym, min(dur, remaining)))
            bar_cursor += dur
    return out


# ---------------------------------------------------------------------------
# Compose
# ---------------------------------------------------------------------------

def compose_song(
    *,
    genre: str = "pop",
    sections: Optional[list[dict]] = None,
    seed: int = 0,
    technique_overrides: Optional[dict[str, str]] = None,
    enabled_instruments: Optional[tuple] = None,
    key: Optional[str] = None,
    scale: Optional[str] = None,
    tempo: Optional[float] = None,
    bars: Optional[int] = None,
    swing: Optional[float] = None,
    progression: Optional[list] = None,
    knobs: Optional[dict] = None,
    hits: Optional[list] = None,
    lead_voice: Optional[str] = None,
    hit_style: str = "punch",
    stops: Optional[list] = None,
    arrangement: str = "",
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    output_midi: str = DEFAULT_MIDI_NAME,
    output_wav: str = DEFAULT_WAV_NAME,
    skip_audio: bool = False,
) -> dict:
    """Generate a full song by picking techniques per (instrument, section).

    Parameters mirror ``compose_midi`` for the basics; the technique
    picks come from :data:`src.composition.BANK`. Same ``seed`` ⇒
    identical song. ``technique_overrides`` pins specific cells with
    keys ``"{role}:{instrument}"`` or ``"{section_label}:{instrument}"``.

    Returns a dict with paths + summary + selections + an editable
    ``rhythm_overrides`` list shaped like the Gradio accordion expects.
    """
    preset = STYLES.get(genre)
    if preset is None:
        raise ValueError(f"unknown genre {genre!r}")

    # Resolve defaults from the preset.
    eff_key = key or preset.key
    eff_scale = scale or preset.scale
    eff_tempo = float(tempo if tempo is not None else preset.tempo)
    eff_swing = float(swing if swing is not None else preset.swing)
    eff_bars = int(bars if bars is not None else preset.default_bars)
    # A caller-supplied progression (e.g. one detected from an audio sample)
    # overrides the preset's; it still flows through pacing/slicing per section.
    # Otherwise, when the preset ships multiple progression_variants, seed-pick
    # ONE for the whole song — this gives cross-generation harmonic variety while
    # keeping the form consistent within the song (e.g. blues picks one 12-bar
    # form per generation instead of always the same one). Presets that use
    # per-section contrast (section_progressions) rely on that instead.
    if progression:
        progression = list(progression)
    elif len(preset.progression_variants) > 1:
        _variants = preset.progression_variants
        _vidx = int(np.random.default_rng(
            _sub_seed(seed, "song_progression")).integers(len(_variants)))
        progression = list(_variants[_vidx][1])
    else:
        progression = list(preset.progression)
    technique_overrides = technique_overrides or {}
    # Per-generation feel knobs (UI overrides merged over genre defaults).
    eff_knobs = resolve_knobs(genre, knobs)

    # Sections — caller-provided or derived from the preset variant.
    if sections is None:
        sections = _default_sections_for(genre)

    # Build exporter.
    midi = MidiExporter(
        tempo=eff_tempo,
        time_signature=preset.time_signature,
    )

    # Resolve enabled_instruments into a list of (label, role,
    # Instrument-or-None) tuples. Three shapes are accepted, in order
    # of priority:
    #
    # 1. ``["piano", "electric_bass", "drum_kit", …]`` — instrument
    #    ids from INSTRUMENT_REGISTRY. Each resolves to a specific
    #    Instrument; bank picks fire per-instrument with proper
    #    track routing.
    # 2. ``["chords", "bass", "melody", "drums"]`` — legacy role
    #    bucket tokens (still emitted by older callers).
    # 3. ``None`` — defaults to all four legacy roles for backward
    #    compat with the original compose_song shape.
    from src.composition.instruments import (
        INSTRUMENT_REGISTRY, expand_selection,
    )
    legacy_roles = {"chords", "bass", "melody", "drums"}
    active_passes: list[tuple] = []   # (instrument_token, role, Instrument | None)

    if enabled_instruments is None:
        for role in _INSTRUMENT_ORDER:
            active_passes.append((role, role, None))
    else:
        # Split between specific instrument ids and legacy role tokens.
        specific_ids = [
            i for i in enabled_instruments if i in INSTRUMENT_REGISTRY
        ]
        legacy_tokens = [
            i for i in enabled_instruments if i in legacy_roles
        ]
        # Expand section composites + dedupe.
        resolved = expand_selection(specific_ids)
        for inst in resolved:
            active_passes.append((inst.id, inst.role, inst))
        for token in legacy_tokens:
            # Only fire the legacy role if no concrete instrument is
            # already covering that role — otherwise we'd render the
            # part twice (once on a per-instrument track + once on the
            # legacy "Chords"/"Bass"/… track).
            if not any(role == token for _, role, _ in active_passes):
                active_passes.append((token, token, None))

    selections: list[dict] = []
    rhythm_overrides_out: list[dict] = []
    # Map the genre key to the technique-bank tag family. Adding a new
    # full-song preset means adding a row here so its techniques get
    # the +weight boost from preferred_tags. Unmapped presets get no
    # bias and fall back to the cross-genre baseline.
    preferred_tags = _GENRE_TAG_MAP.get(genre, ())

    # Stratified voicing assignment. When 2+ chord-role instruments are
    # active in this song, each gets a distinct layer role (mid_comp /
    # pad / top) so they occupy different register / chord-density
    # slices. Solo or zero chord instruments returns {} — techniques
    # render their pinned voicing unchanged.
    chord_role_instruments = [
        inst_obj for _, role, inst_obj in active_passes
        if role == "chords" and inst_obj is not None
    ]
    voicing_assignments = assign_layered_voicings(chord_role_instruments)
    # De-clutter: when several chord instruments stack (rock's dirty + clean
    # guitar + organ), only the FIRST is a core voice. The extras are "color"
    # layers that sit out the low-energy sections (intro/verse) and bloom back
    # in for the chorus/bridge/outro — so verses breathe and the chorus lifts.
    _color_chord_ids = {
        getattr(o, "id", None) for o in chord_role_instruments[1:]
    }
    # Is there a harmonic voice (chords/melody) to carry a section if we
    # drop a non-essential layer? Gates the intro drum-drop.
    _has_harmonic = any(
        r in ("chords", "melody") for _, r, _ in active_passes
    )
    # Featured lead-guitar arrangement: it riffs the odd verse, solos the
    # bridge sometimes, and joins the final chorus — not every section.
    # Plus occasional intro/outro riffs and short between-section fills.
    _lead_sections = _lead_guitar_section_plan(sections, seed, eff_knobs)
    # Sections explicitly asked to feature the lead (a "guitar solo here")
    # always get it, on top of the stochastic plan.
    # Explicit "feature the lead here" directives always win; template "Solo"
    # sections are featured via the plan above (so lead_amount=0 still silences
    # them).
    _lead_sections |= {i for i, s in enumerate(sections) if s.get("feature_lead")}
    _lead_fill_secs = _lead_fill_sections(sections, seed, eff_knobs, _lead_sections)

    # Capture the realized (post-reharmonization) chord per segment so the
    # Practice chart can show the exact intended progression rather than
    # re-detecting it from the rendered audio.
    try:
        _tonic_pc = NOTE_NAMES.index(FLAT_TO_SHARP.get(eff_key, eff_key)) % 12
    except ValueError:
        _tonic_pc = 0
    realized_progression: list[dict] = []

    pacing_picks: dict[str, object] = {}
    for sec_idx, section in enumerate(sections):
        s, e = int(section["start_bar"]), int(section["end_bar"])
        label = section.get("label", f"Section {sec_idx + 1}")
        role = section.get("role") or role_for_label(label)
        # The section keeps its own identity (e.g. "prechorus") for arrangement,
        # energy and the chart, but technique/pacing selection needs one of the
        # five canonical roles the bank is keyed on — a pre-chorus picks like a
        # verse (its closest catalogue) and gets its lift from the energy pass.
        pick_role = _canonical_role(section)

        # Per-section harmonic-rhythm variation. Bridge sections sample
        # from preset.bridge_pacing_options when set (bias toward
        # exotic strategies); other sections sample from
        # preset.pacing_options. Presets that didn't opt in always get
        # uniform_1 so the legacy 1-bar-per-chord behavior is
        # preserved for unmodified presets and tests.
        # Per-section preset (multi-preset songs): a section may declare its
        # own ``preset_id`` and we recompute its FEEL from that preset —
        # progression, pacing pools, technique-tag bias, reharmonization and
        # knobs — while key / scale / tempo / meter stay global (one exporter,
        # one tonal centre; section progressions are Roman-numeral so they
        # realize in the song key). Sections without one use the song genre.
        sec_genre = section.get("preset_id") or genre
        if sec_genre != genre and sec_genre not in STYLES:
            sec_genre = genre
        sec_preset = STYLES.get(sec_genre, preset)
        # Per-section knob overrides (playing-style directives) merge over the
        # song knobs for this section only.
        _sec_knob_ov = section.get("knobs") or None
        if sec_genre != genre or _sec_knob_ov:
            sec_knobs = resolve_knobs(sec_genre, {**(knobs or {}), **(_sec_knob_ov or {})})
        else:
            sec_knobs = eff_knobs
        sec_tags = (_GENRE_TAG_MAP.get(sec_genre, ()) if sec_genre != genre
                    else preferred_tags)
        # Progression source: explicit per-section override > the section
        # preset's own progression (only when it differs from the song) >
        # the song progression.
        # Per-section chord contrast: when the (section's) preset declares a
        # progression POOL for this role, seed-pick one so verse/chorus/bridge
        # differ and successive generations vary. Explicit overrides still win.
        _role_pool = (sec_preset if sec_genre != genre else preset) \
            .section_progressions.get(pick_role)
        if section.get("progression"):
            sec_progression = list(section["progression"])
        elif _role_pool:
            _pidx = int(np.random.default_rng(
                _sub_seed(seed, label, "section_progression")
            ).integers(len(_role_pool)))
            sec_progression = list(_role_pool[_pidx])
        elif sec_genre != genre:
            sec_progression = list(sec_preset.progression)
        else:
            sec_progression = progression

        # Per-section KEY and MODE. An explicit override wins. Otherwise the
        # MODE follows the section's preset, and the KEY lands on the DEGREE of
        # the global key whose mode matches — so the section shares the global
        # key signature and fits diatonically (a minor section of a C-major
        # song → A minor, the vi; a dorian section → D dorian, the ii).
        sec_scale = (section.get("scale")
                     or (sec_preset.scale if (sec_genre != genre and sec_preset.scale) else None)
                     or eff_scale)
        if section.get("key"):
            sec_key = section["key"]
        elif (sec_genre != genre or section.get("scale")) and sec_scale != eff_scale:
            sec_key = _relative_degree_key(eff_key, eff_scale, sec_scale)
        else:
            sec_key = eff_key
        try:
            sec_tonic_pc = NOTE_NAMES.index(FLAT_TO_SHARP.get(sec_key, sec_key)) % 12
        except ValueError:
            sec_tonic_pc = _tonic_pc

        pacing_rng = np.random.default_rng(
            _sub_seed(seed, label, "pacing"),
        )
        _hprof = harmony_profile(sec_genre)
        pacing = pick_pacing(pacing_rng, sec_preset, pick_role,
                             reharm=_hprof.reharm,
                             reharm_prob=sec_knobs["reharm_prob"])
        pacing_picks[label] = pacing
        paced_progression = apply_pacing(
            sec_progression, pacing, sec_key, sec_scale,
        )
        section_prog = _slice_progression(
            paced_progression, eff_bars, s, e,
        )
        # Lean the progression into its mode (modal colour chord + soften the
        # functional dominant toward the modal v). No-op for major/blues forms.
        if "blues" not in sec_genre:
            section_prog = modal_color(
                section_prog, sec_scale,
                np.random.default_rng(_sub_seed(seed, label, "modal")),
            )

        # Resolve this section's realized chords to absolute (root_pc, quality)
        # with absolute bar spans (same symbol→chord map the renderer uses).
        _cur = 0.0
        for _sym, _dur in section_prog:
            _off, _qual = roman_to_semitone_offset(_sym, sec_scale)
            realized_progression.append({
                "root_pc": (sec_tonic_pc + _off) % 12,
                "quality": _qual,
                "symbol": _sym,
                "start_bar": round(s + _cur, 4),
                "end_bar": round(s + _cur + float(_dur), 4),
            })
            _cur += float(_dur)

        row = {
            "start_bar": s, "end_bar": e, "label": label, "role": role,
            "pacing": pacing.name, "pacing_label": pacing.label,
            "chord_rhythm_h1": "", "chord_rhythm_h2": "",
            "bass_pattern": "",
        }

        for instrument_token, inst_role, inst_obj in active_passes:
            # Arrangement: drop non-essential layers in some sections so the
            # band breathes (backing vox/percussion enter on the chorus;
            # drums hold off in the intro).
            # Strict-idiom genres arrange every section themselves (a funk
            # intro is the whole band on the riff), so the generic thinning
            # below doesn't apply to them.
            _own_arrangement = genre in _STRICT_GENRES
            if not _own_arrangement and not _plays_in_section(inst_obj, pick_role, _has_harmonic):
                continue
            # Thin stacked chord "color" layers out of the low-energy sections
            # so verses aren't a wall of comping; they return for the lift.
            if (not _own_arrangement
                    and getattr(inst_obj, "id", None) in _color_chord_ids
                    and pick_role in ("intro", "verse")):
                continue
            # Per-section instrument MASK (section builder): when a section names
            # an explicit instrument subset, only those play in it.
            _sec_instruments = section.get("instruments")
            if _sec_instruments and (
                    instrument_token not in _sec_instruments
                    and getattr(inst_obj, "id", None) not in _sec_instruments):
                continue
            # Lead guitar is featured, not constant: it plays its featured
            # sections (some verses, bridge solo, final chorus, opt. intro/
            # outro) or drops a short fill in a fill section; else it sits out.
            is_lead = getattr(inst_obj, "id", None) == "lead_guitar"
            lead_is_fill = is_lead and sec_idx in _lead_fill_secs
            if (is_lead and not _own_arrangement
                    and sec_idx not in _lead_sections and not lead_is_fill):
                continue
            override_key = f"{role}:{instrument_token}"
            label_key = f"{label}:{instrument_token}"
            forced_name = (
                technique_overrides.get(label_key)
                or technique_overrides.get(override_key)
            )
            technique = (
                BANK.get(forced_name) if forced_name else None
            )
            if technique is None:
                sub = _sub_seed(seed, label, instrument_token)
                rng = np.random.default_rng(sub)
                # Try the specific instrument id first (so future
                # instrument-tagged techniques win), then fall back to
                # the role bucket for the 193 existing role-tagged
                # techniques.
                tags_for_pick = sec_tags
                strict = sec_genre in _STRICT_GENRES
                technique = BANK.pick(
                    instrument_token, pick_role, rng,
                    preferred_tags=tags_for_pick, strict=strict,
                )
                if instrument_token != inst_role and (
                        technique is None
                        or (strict and not set(technique.tags) & set(tags_for_pick))):
                    # A strict genre's own idiom on the role bucket beats a
                    # generic instrument-specific technique.
                    bucket = BANK.pick(
                        inst_role, pick_role, rng,
                        preferred_tags=tags_for_pick, strict=strict,
                    )
                    if bucket is not None and (
                            technique is None or set(bucket.tags) & set(tags_for_pick)):
                        technique = bucket
            if technique is None:
                logger.info(
                    "compose_song: no technique for (%s, %s) — skipping",
                    instrument_token, role,
                )
                continue

            ctx = TechniqueContext(
                start_bar=s, end_bar=e,
                section_role=pick_role, section_label=label,
                instrument=instrument_token,
                key=sec_key, scale=sec_scale,
                tempo=eff_tempo, genre=sec_genre,
                time_signature=preset.time_signature,
                progression=section_prog,
                swing=eff_swing,
                rng=np.random.default_rng(_sub_seed(
                    seed, label, instrument_token, "inner",
                )),
                instrument_obj=inst_obj,
                voicing_role=voicing_assignments.get(instrument_token),
                voicing_variety=sec_knobs["voicing_variety"],
                bass_inversion=sec_knobs["bass_inversion"],
                drum_fill=sec_knobs["drum_fill"],
                lead_fill=(is_lead and lead_is_fill),
                song_seed=int(seed),
                hits=tuple(float(h) for h in (hits or ()) if h is not None and float(h) >= 0),
                lead_voice=lead_voice,
                hit_style=hit_style,
                stops=tuple((float(a), float(b)) for a, b in (stops or ()) if float(b) > 0),
                arrangement=arrangement or "",
            )
            try:
                apply_technique(midi, technique, ctx)
            except Exception:
                logger.exception(
                    "compose_song: technique %r raised on (%s, %s) — "
                    "section will be incomplete",
                    technique.name, instrument_token, role,
                )

            selections.append({
                "section_label": label,
                "section_role":  role,
                "instrument":    instrument_token,
                "instrument_label": inst_obj.label if inst_obj else instrument_token,
                "technique":     technique.name,
                "technique_label": technique.label,
                "pacing":        pacing.name,
                "pacing_label":  pacing.label,
                "voicing_role":  voicing_assignments.get(instrument_token),
                "start_bar": s, "end_bar": e,
            })

            # Surface the technique's nominal rhythm into the editable
            # accordion. We can't always know the rhythm name (custom
            # techniques may compose multiple sub-rhythms), so we just
            # record the technique name in the label so the user sees
            # what fired.
            if inst_role == "chords":
                row["chord_rhythm_h1"] = technique.name
            elif inst_role == "bass":
                row["bass_pattern"] = technique.name

        rhythm_overrides_out.append(row)

    # Per-section dynamics: scale velocities so sections have distinct
    # energy (verses pulled back, choruses hit full) instead of everything
    # sitting at one level. Chorus = 1.0 reference; drums keep most of their
    # punch so the backbeat doesn't go limp in quiet sections.
    _SECTION_ENERGY = {
        "intro": 0.72, "buildup": 0.80, "verse": 0.82, "prechorus": 0.92,
        "chorus": 1.0, "drop": 1.06, "bridge": 0.90, "breakdown": 0.78,
        "solo": 0.96, "outro": 0.74,
    }
    for section in sections:
        s, e = int(section["start_bar"]), int(section["end_bar"])
        label = (section.get("label") or "")
        role = section.get("role") or _section_identity(label)
        lo = label.lower()
        sec_dyn = (section.get("knobs") or {}).get("dynamics", eff_knobs["dynamics"])
        explicit = section.get("energy")
        # A buildup CRESCENDOS: ramp the section from quiet up to full so it
        # actually feels like it's building into what follows (an explicit
        # per-section energy overrides the ramp).
        if role == "buildup" and explicit is None and e >= s:
            for b in range(s, e + 1):
                prog = (b - s) / max(1, e - s)         # 0 → 1 across the section
                f = 0.60 + prog * 0.50                 # 0.60 → 1.10
                f = 1.0 + (f - 1.0) * sec_dyn
                if abs(f - 1.0) > 1e-6:
                    midi.scale_region_velocity(b, b + 1, f, drum_factor=1.0 - (1.0 - f) * 0.5)
            continue
        if explicit is not None:
            # Explicit per-section level (a "sparse intro" / "big chorus"
            # directive) — used directly, not scaled by the contrast knob.
            energy = float(explicit)
        else:
            energy = _SECTION_ENERGY.get(role, 0.85)
            if "solo" in lo or section.get("feature_lead"):
                energy = max(energy, 0.96)   # solos ride energetic
            elif "pre-chorus" in lo or "prechorus" in lo:
                energy = 0.92                 # lift into the chorus
            # Scale the deviation-from-full by the dynamics knob: 1.0 = normal
            # contrast, 0 = flat (everything at chorus level), up to 2 = extreme.
            energy = 1.0 + (energy - 1.0) * sec_dyn
        if abs(energy - 1.0) > 1e-6:
            drum_f = 1.0 - (1.0 - energy) * 0.5
            midi.scale_region_velocity(s, e + 1, energy, drum_factor=drum_f)

    # Save MIDI + WAV.
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    midi_path = output_dir / output_midi
    midi.save(midi_path)

    # Per-section TEMPO map: a section can run at its own tempo (a half-time
    # bridge, a double-time outro). The render placed every bar at a fixed
    # tick, so we author a tempo map over the file — no notes move, and the
    # FluidSynth render + the score both honour it. Uniform-tempo songs are
    # untouched (the injector is a no-op for <2 distinct tempos).
    qpb = midi.quarters_per_bar
    section_tempos: list[dict] = []
    tempo_changes: list[tuple[float, float]] = []
    prev_t = None
    for sec in sorted(sections, key=lambda x: int(x["start_bar"])):
        st = float(sec.get("tempo") or eff_tempo)
        section_tempos.append({"start_bar": int(sec["start_bar"]),
                               "end_bar": int(sec["end_bar"]), "tempo": st})
        if prev_t is None or abs(st - prev_t) > 1e-6:
            tempo_changes.append((int(sec["start_bar"]) * qpb, st))
            prev_t = st
    try:
        inject_tempo_changes(midi_path, tempo_changes)
    except Exception:  # noqa: BLE001 — tempo map is an enhancement, not critical
        logger.exception("compose_song: tempo-map injection failed")

    wav_path: Optional[Path] = output_dir / output_wav
    if not skip_audio:
        try:
            audio, sr = midi.synthesize(sample_rate=44100)
            sf.write(str(wav_path), audio, sr)
        except Exception:
            logger.exception("compose_song: preview synthesis failed")
            wav_path = None

    # Human-readable summary.
    summary_lines = [
        f"{preset.name} — seed {seed} — {eff_bars} bars",
    ]
    by_section: dict[str, list[dict]] = {}
    for sel in selections:
        by_section.setdefault(sel["section_label"], []).append(sel)
    for label, items in by_section.items():
        span = items[0]
        # Tag the section header with its pacing only when it differs
        # from the legacy default; otherwise the line stays clean.
        pacing = pacing_picks.get(label)
        pacing_tag = ""
        if pacing is not None and pacing.name != "uniform_1":
            pacing_tag = f" [pacing: {pacing.label}]"
        # Per-instrument layering tag (only when 2+ chord instruments
        # active — voicing_assignments is non-empty).
        def _fmt(item):
            tag = ""
            role = item.get("voicing_role")
            if role:
                tag = f" [{role}]"
            return f"{item['instrument']}={item['technique']}{tag}"
        line = (
            f"  {label} (bars {span['start_bar'] + 1}-{span['end_bar'] + 1}):"
            f"{pacing_tag}  "
            + " · ".join(_fmt(it) for it in items)
        )
        summary_lines.append(line)
    summary = "\n".join(summary_lines)

    return {
        "midi_path": str(midi_path),
        "wav_path":  str(wav_path) if wav_path else "",
        "summary":   summary,
        "selections": selections,
        "rhythm_overrides": rhythm_overrides_out,
        "genre": genre,
        "seed": int(seed),
        "bars": eff_bars,
        "progression": realized_progression,
        "section_tempos": section_tempos,
    }
