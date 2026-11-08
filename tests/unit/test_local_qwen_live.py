"""LIVE: the producer's feedback phrases through the real local model (MLX
Qwen behind the gateway). Skipped unless ``AI_MUSIC_LIVE_QWEN=1``:

    AI_MUSIC_LIVE_QWEN=1 .venv/bin/python -m pytest -s tests/unit/test_local_qwen_live.py

Prints how many phrases the model mapped to the right option. Every answer
must come back as a valid plan (or fall through cleanly); the accuracy floor
is deliberately modest because the 9B model is the fallback, not the main
interpreter.
"""

import os

import pytest

from src.api import describe

from .test_describe import BED, CANNED, FF

pytestmark = pytest.mark.skipif(os.environ.get("AI_MUSIC_LIVE_QWEN") != "1",
                                reason="live local-model test (set AI_MUSIC_LIVE_QWEN=1)")

DESCRIPTIONS = [
    ("a funk fusion background bed for a product video, simple bass, no stabs, 120 bpm",
     lambda p: p["genre"] == FF and "simple_bass" in p.get("arrangement", "") and p.get("hits") == []
     and p.get("tempo") == 120 and (p.get("target_lufs") or 0) <= -20),
    ("a slow jazz ballad in Bb with a tenor sax",
     lambda p: p["genre"].startswith("jazz") and p.get("key") == "Bb"),
    ("upbeat 70s funk horns for a sizzle reel, just the hits, guitar lead",
     lambda p: p["genre"] == FF and "hits_only" in p.get("arrangement", "")),
]


def test_local_qwen_on_feedback_phrases():
    """Raw model accuracy, and the pipeline's (model answer, checked against
    the rules for known phrases, rules when it disagrees)."""
    from src.composition import song_plan as sp
    system = sp.system_prompt()
    rows, raw_ok, final_ok = [], 0, 0
    for feedback, _canned, check in CANNED:
        base, _ = sp.normalize_plan(BED)
        try:
            out = describe.ask_local("revise", system, sp.user_prompt("revise", feedback, base),
                                     {"feedback": feedback}, describe._noop)
            plan, _ = sp.normalize_plan(sp.parse_model_output(out)[0], base)
        except Exception as exc:  # noqa: BLE001
            plan = None
            rows.append((feedback, False, False, f"error: {exc}"[:120]))
            continue
        good = check(plan)
        problem = describe.disagrees_with_rules(base, plan, feedback)
        final = plan if not problem else sp.normalize_plan(sp.rule_revise(base, feedback)[0], base)[0]
        rows.append((feedback, good, check(final), sp.describe_changes(base, plan)
                     + ([f"[guard: {problem} → rules]"] if problem else [])))
        raw_ok += good
        final_ok += check(final)
    for text, check in DESCRIPTIONS:
        out = describe.ask_local("describe", system, sp.user_prompt("describe", text), {}, describe._noop)
        plan, _ = sp.normalize_plan(sp.parse_model_output(out)[0])
        good = check(plan)
        rows.append((text, good, good, plan))
        raw_ok += good
        final_ok += good
    print(f"\nlocal model alone: {raw_ok}/{len(rows)} right; with the rules check: {final_ok}/{len(rows)}")
    for r in rows:
        print(("  OK  " if r[1] else "  MISS"), ("final OK  " if r[2] else "final MISS"), r[0][:55], "->", r[3])
    assert raw_ok >= len(rows) // 2 and final_ok >= raw_ok
