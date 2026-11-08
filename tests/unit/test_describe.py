"""Describe / revise (src/api/describe.py): the interpreter fallback order
(Claude via the queue → local model → rules), canned model answers for the
producer's real feedback, the HTTP routes, the Claude answerer script, and
the engine pieces the plans rely on (target_lufs, per-section arrangement)."""

import json
import sys
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import ai_requests, describe
from src.api.routes import router

FF = "funk_fusion_full"
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _queue(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_requests, "AI_REQ_DIR", tmp_path / "ai_requests")
    monkeypatch.setattr(describe, "CLAIM_TIMEOUT", 0.6)
    monkeypatch.setattr(describe, "ANSWER_TIMEOUT", 5.0)
    monkeypatch.setattr(describe, "INTERPRETERS", ("claude", "local", "rules"))


def _answer(text_or_obj):
    return lambda *a, **k: text_or_obj


def _fail(exc):
    def f(*a, **k):
        raise exc
    return f


# --- fallback order -----------------------------------------------------------
def test_no_answerer_skips_claude_fast_and_uses_local(monkeypatch):
    monkeypatch.setitem(describe.ASKERS, "local", _answer(json.dumps(
        {"plan": {"genre": FF, "tempo": 120}, "summary": "bed"})))
    monkeypatch.setattr(describe, "CLAIM_TIMEOUT", 30.0)
    t0 = time.time()
    res = describe.describe("a funk fusion bed")
    assert time.time() - t0 < 10                       # no 30 s wait for a dead queue
    assert res["interpreter"] == "local" and res["plan"]["tempo"] == 120
    assert res["attempts"][0]["interpreter"] == "claude"
    assert "no Claude answerer" in res["attempts"][0]["outcome"]
    assert ai_requests.list_requests() == []            # nothing left queued


def test_heartbeat_but_nobody_claims_withdraws_then_local(monkeypatch):
    ai_requests.beat("someone")                         # a poller that never claims
    monkeypatch.setitem(describe.ASKERS, "local", _answer({"plan": {"genre": FF}, "summary": ""}))
    res = describe.describe("funk fusion")
    assert res["interpreter"] == "local"
    assert "claimed" in res["attempts"][0]["outcome"]
    assert ai_requests.list_requests() == []            # withdrawn, not left for a late answerer


def test_claude_answers_through_the_queue():
    stop = threading.Event()

    def answerer():                                     # what scripts/claude_answerer.py does
        while not stop.is_set():
            ai_requests.beat("test", {"describe", "revise"})
            for rec in ai_requests.list_requests("pending", {"describe"}):
                assert "Song plan guide" in rec["params"]["system"]
                assert "Song description" in rec["params"]["user"]
                ai_requests.claim(rec["id"], "test")
                time.sleep(0.8)                         # slower than the claim timeout: still waited for
                ai_requests.answer(rec["id"], {"plan": {"genre": FF, "arrangement": "hits_only,calm_keys,simple_bass",
                                                        "target_lufs": -25, "tempo": 120},
                                               "summary": "Background bed."})
            time.sleep(0.05)

    ai_requests.beat("test", {"describe", "revise"})
    th = threading.Thread(target=answerer, daemon=True)
    th.start()
    try:
        res = describe.describe("background bed for a product video")
    finally:
        stop.set()
        th.join(2)
    assert res["interpreter"] == "claude"
    assert res["plan"]["arrangement"] == "hits_only,calm_keys,simple_bass"
    assert res["summary"] == "Background bed." and res["engine"] == "funk_fusion"


def test_answerer_kinds_scope_the_heartbeat():
    ai_requests.beat("lyrics-only", {"lyrics"})
    assert not ai_requests.answerer_alive("describe")
    ai_requests.beat("any")
    assert ai_requests.answerer_alive("describe")


def test_bad_answers_fall_through_to_rules(monkeypatch):
    monkeypatch.setitem(describe.ASKERS, "claude", _answer("I'd love to help! What genre?"))
    monkeypatch.setitem(describe.ASKERS, "local", _fail(ConnectionError("gateway down")))
    monkeypatch.setattr(ai_requests, "answerer_alive", lambda kind, max_age=30.0: True)
    res = describe.describe("funk fusion background bed, no stabs, 120 bpm")
    assert res["interpreter"] == "rules"
    assert [a["interpreter"] for a in res["attempts"]] == ["claude", "local", "rules"]
    assert res["plan"]["hits"] == [] and res["plan"]["target_lufs"] == -25


def test_interpreters_env_order_is_honored(monkeypatch):
    monkeypatch.setattr(describe, "INTERPRETERS", ("rules",))
    monkeypatch.setitem(describe.ASKERS, "local", _fail(AssertionError("must not be called")))
    assert describe.describe("jazz in Bb")["interpreter"] == "rules"


def test_local_uses_passthrough_then_chat(monkeypatch):
    calls = []

    def fake(url, body=None, timeout=10.0):
        calls.append(url.rsplit(":8800", 1)[-1])
        if url.endswith("/v1/models"):
            raise OSError("model unloaded")
        return {"text": '{"plan": {"genre": "funk_fusion_full"}, "summary": "x"}'}

    monkeypatch.setattr(describe, "_http_json", fake)
    out = describe.ask_local("describe", "SYS", "USER", {}, describe._noop)
    assert calls == ["/v1/models", "/chat"] and "funk_fusion_full" in out


# --- canned model answers for the producer's real feedback ---------------------
BED = {"genre": FF, "tempo": 120, "arrangement": "hits_only,calm_keys,pocket_bass", "target_lufs": -25,
       "hits": [3.9, 7.0, 13.0]}

# (feedback, what Claude/Qwen answered, check on the validated plan)
CANNED = [
    ("the bass is doing too much",
     '{"plan": {"genre": "funk_fusion_full", "tempo": 120, "arrangement": "hits_only,calm_keys,simple_bass,pocket_bass",'
     ' "target_lufs": -25, "hits": [3.9, 7.0, 13.0]}, "summary": "Bass down to a simple line."}',
     lambda p: "simple_bass" in p["arrangement"] and "pocket_bass" not in p["arrangement"]),
    ("too many fills",
     '```json\n{"plan": {"arrangement": "hits_only,calm_keys,pocket_bass,pocket_drums"}, "summary": "Pocket drums."}\n```',
     lambda p: "pocket_drums" in p["arrangement"] and p["tempo"] == 120 and p["hits"] == [3.9, 7.0, 13.0]),
    ("no stabs",
     '<think>remove the hits</think>{"plan": {"hits": []}, "summary": "No stabs."}',
     lambda p: p["hits"] == [] and "hits_only" in p["arrangement"]),
    ("background, lower volume",
     '{"plan": {"target_lufs": -25.5}, "summary": "Background level."}',
     lambda p: -27 <= p["target_lufs"] <= -23),
    ("the trumpet fall-off makes a serious video seem silly",
     '{"plan": {"arrangement": "hits_only,calm_keys,pocket_bass,no_falloff"}, "summary": "Held ending."}',
     lambda p: "no_falloff" in p["arrangement"]),
    ("I said NO trumpet, just end on the strings",
     '{"plan": {"instruments": ["drum_kit", "electric_bass", "electric_piano", "trombone", "synth_lead"],'
     ' "arrangement": "hits_only,calm_keys,pocket_bass,soar,no_falloff"}, "summary": "No trumpet; strings end it."}',
     lambda p: "trumpet" not in p["instruments"] and "string_section" in p["instruments"]
     and {"soar", "no_falloff"} <= set(p["arrangement"].split(","))),
    ("drums too percussive, use brushes",
     '{"plan": {"arrangement": "hits_only,calm_keys,pocket_bass,brushes"}, "summary": "Brushes."}',
     lambda p: "brushes" in p["arrangement"]),
    ("too fast",
     '{"plan": {"tempo": 105}, "summary": "Slower."}',
     lambda p: p["tempo"] == 105),
    ("calm drums + calm bass sounds like preschool hits",
     '{"plan": {"arrangement": "hits_only,calm_keys,pocket_bass,pocket_drums,bass_flare,bogus"}, "summary": "More life."}',
     lambda p: "pocket_drums" in p["arrangement"] and "bogus" not in p["arrangement"]),
]


@pytest.mark.parametrize("feedback,canned,check", CANNED, ids=[c[0][:30] for c in CANNED])
def test_canned_answers_for_history_feedback(monkeypatch, feedback, canned, check):
    monkeypatch.setattr(describe, "INTERPRETERS", ("local", "rules"))
    seen = {}

    def ask(kind, system, user, extra, progress):
        seen.update(kind=kind, user=user, extra=extra)
        return canned

    monkeypatch.setitem(describe.ASKERS, "local", ask)
    res = describe.revise(BED, feedback)
    assert res["interpreter"] == "local", res["attempts"]
    assert seen["kind"] == "revise" and feedback in seen["user"] and seen["extra"]["plan"]["genre"] == FF
    assert check(res["plan"]), res["plan"]
    assert res["changes"], "a revision reports what changed"


@pytest.mark.parametrize("feedback,canned,check", CANNED, ids=[c[0][:30] for c in CANNED])
def test_rules_alone_handle_history_feedback(monkeypatch, feedback, canned, check):
    """With no AI at all the same phrases still land on the right options."""
    monkeypatch.setattr(describe, "INTERPRETERS", ("rules",))
    res = describe.revise(BED, feedback)
    assert res["interpreter"] == "rules"
    if feedback == "too fast":
        assert res["plan"]["tempo"] < 120
    elif feedback.startswith("drums too percussive"):
        assert "brushes" in res["plan"]["arrangement"]
    else:
        assert check(res["plan"]), res["plan"]


# --- routes -------------------------------------------------------------------
@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(describe, "INTERPRETERS", ("rules",))
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_describe_and_revise_routes(client):
    r = client.post("/api/describe", json={"text": "funk fusion background bed, simple bass, 120 bpm"})
    assert r.status_code == 200
    body = r.json()
    assert body["interpreter"] == "rules" and body["engine"] == "funk_fusion"
    assert body["plan"]["arrangement"] == "simple_bass" and body["understood"]
    r = client.post("/api/revise", json={"plan": body["plan"], "feedback": "too many fills"})
    assert "pocket_drums" in r.json()["plan"]["arrangement"]
    assert client.post("/api/describe", json={"text": "  "}).status_code == 400
    assert client.post("/api/revise", json={"plan": body["plan"], "feedback": ""}).status_code == 400


def test_describe_as_job(client):
    r = client.post("/api/describe", json={"text": "jazz ballad in Bb", "wait": False})
    jid = r.json()["job_id"]
    for _ in range(100):
        j = client.get(f"/api/jobs/{jid}").json()
        if j["status"] in ("done", "error"):
            break
        time.sleep(0.05)
    assert j["status"] == "done" and j["result"]["plan"]["key"] == "Bb"


def test_queue_claim_and_heartbeat_routes(client):
    rec = ai_requests.enqueue("describe", "", {"system": "s", "user": "u"})
    assert ai_requests.list_requests("pending", {"lyrics"}) == []
    r = client.get("/api/ai/requests?status=pending&kind=describe,revise&answerer=t")
    assert [x["id"] for x in r.json()["requests"]] == [rec["id"]]
    assert ai_requests.answerer_alive("describe") and not ai_requests.answerer_alive("lyrics")
    assert client.post(f"/api/ai/requests/{rec['id']}/claim?answerer=t").json()["status"] == "claimed"
    assert client.post(f"/api/ai/requests/{rec['id']}/claim").status_code == 409
    assert not ai_requests.withdraw(rec["id"])          # claimed: stays


# --- the Claude answerer script ------------------------------------------------
def _load_answerer():
    import importlib.util
    spec = importlib.util.spec_from_file_location("claude_answerer", ROOT / "scripts" / "claude_answerer.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_answerer_runs_claude_and_posts_plan(tmp_path, monkeypatch):
    mod = _load_answerer()
    stub = tmp_path / "fake_claude.py"
    stub.write_text(
        "import json, sys\n"
        "args = sys.argv[1:]\n"
        "assert '-p' in args and '--system-prompt' in args and args[args.index('--tools') + 1] == ''\n"
        "user = sys.stdin.read()\n"
        "plan = {'genre': 'funk_fusion_full', 'arrangement': 'simple_bass'}\n"
        "print(json.dumps({'type': 'result', 'is_error': False,\n"
        "  'result': 'Here you go:\\n' + json.dumps({'plan': plan, 'summary': 'got: ' + user[:20]})}))\n")
    posted = []

    def fake_call(api, path, body=None, method=None, timeout=15):
        posted.append((path, body))
        return {}

    monkeypatch.setattr(mod, "_call", fake_call)
    rec = {"id": "abc", "kind": "describe", "params": {"system": "GUIDE", "user": "Song description: x"}}
    out = mod.handle("http://x", rec, [sys.executable, str(stub)], None, 30)
    assert out == "answered"
    assert posted[0][0].startswith("/api/ai/requests/abc/claim")
    assert posted[1][1]["answer"]["plan"]["arrangement"] == "simple_bass"


def test_answerer_reports_errors(tmp_path, monkeypatch):
    mod = _load_answerer()
    stub = tmp_path / "bad.py"
    stub.write_text("print('{\"result\": \"no idea\", \"is_error\": false}')\n")
    posted = []
    monkeypatch.setattr(mod, "_call", lambda api, path, body=None, method=None, timeout=15: posted.append(body) or {})
    out = mod.handle("http://x", {"id": "z", "params": {"system": "s", "user": "u"}}, [sys.executable, str(stub)], None, 30)
    assert out.startswith("error") and posted[-1]["error"]


# --- engine pieces the plans use ------------------------------------------------
def test_normalize_wav_hits_target_lufs(tmp_path):
    import soundfile as sf
    from src.api.service import _normalize_wav
    from src.audio_processing.render.loudness import integrated_lufs
    sr = 44100
    t = np.arange(sr * 3) / sr
    x = (0.5 * np.sin(2 * np.pi * 220 * t)).astype("float32")
    p = tmp_path / "mix.wav"
    sf.write(str(p), np.stack([x, x], 1), sr, subtype="PCM_24")
    got = _normalize_wav(p, -25.0)
    audio, _ = sf.read(str(p), always_2d=True)
    assert abs(got + 25) < 0.2 and abs(integrated_lufs(audio.T, sr) + 25) < 0.2
    assert sf.info(str(p)).subtype == "PCM_24"


def test_section_override_arrangement_reaches_sections():
    from src.api.arrangement import build_sections
    secs = build_sections(FF, [], None, {"intro": {"arrangement": "calm"}})
    assert [s.get("arrangement") for s in secs if s["role"] == "intro"] == ["calm"]
    assert all("arrangement" not in s for s in secs if s["role"] != "intro")


def test_generate_request_takes_target_lufs():
    from src.api.schemas import GenerateRequest
    assert GenerateRequest(genre=FF, target_lufs=-25).target_lufs == -25


def test_local_revision_that_drops_unrelated_variants_falls_to_rules(monkeypatch):
    monkeypatch.setattr(describe, "INTERPRETERS", ("local", "rules"))
    # "too many fills" but the model also removed the pocket bass and calm keys.
    monkeypatch.setitem(describe.ASKERS, "local", _answer(
        '{"plan": {"arrangement": "hits_only,pocket_drums"}, "summary": "x"}'))
    res = describe.revise(BED, "too many fills")
    assert res["interpreter"] == "rules" and "also removed" in res["attempts"][0]["outcome"]
    assert res["plan"]["arrangement"] == "hits_only,calm_keys,pocket_bass,pocket_drums"


def test_local_revision_of_unknown_feedback_is_trusted(monkeypatch):
    monkeypatch.setattr(describe, "INTERPRETERS", ("local", "rules"))
    monkeypatch.setitem(describe.ASKERS, "local", _answer('{"plan": {"lead_patch": "guitar_stack"}}'))
    res = describe.revise(BED, "the lead sounds a bit thin")
    assert res["interpreter"] == "local" and res["plan"]["lead_patch"] == "guitar_stack"
