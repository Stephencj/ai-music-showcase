"""Describe / revise a song in plain English → a song plan (src/composition/
song_plan.py), interpreted by the best interpreter available:

1. **Claude**, through the AI request queue (ai_requests.py), when a Claude
   answerer is polling it (scripts/claude_answerer.py). Skipped at once when
   no answerer has polled recently; abandoned if nobody claims the request
   within ``CLAIM_TIMEOUT`` seconds.
2. **The local model** (MLX Qwen behind the gateway, OpenAI-compatible).
3. **The rules** (nl_parser + song_plan.FEEDBACK_RULES), which always work.

Every answer is validated by ``normalize_plan``; an answer that isn't a plan
falls through to the next interpreter. The result says which one was used.
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from typing import Any, Callable, Optional

from src.composition import song_plan as sp

from . import ai_requests

logger = logging.getLogger("ai_music_studio.api.describe")

LOCAL_AI_URL = os.environ.get("AI_MUSIC_LOCAL_AI_URL", "http://127.0.0.1:8800")
CLAIM_TIMEOUT = float(os.environ.get("AI_MUSIC_CLAIM_TIMEOUT", "20"))
ANSWER_TIMEOUT = float(os.environ.get("AI_MUSIC_ANSWER_TIMEOUT", "180"))
LOCAL_TIMEOUT = float(os.environ.get("AI_MUSIC_LOCAL_TIMEOUT", "180"))
# Off switches (tests, or to force a path): AI_MUSIC_INTERPRETERS=local,rules
INTERPRETERS = tuple(x.strip() for x in os.environ.get(
    "AI_MUSIC_INTERPRETERS", "claude,local,rules").split(",") if x.strip())

Progress = Callable[[str, float], None]


def _noop(_m: str, _f: float) -> None:
    pass


# --------------------------------------------------------------------------
# Interpreters. Each returns the model's raw output (dict or text) or raises
# / returns None to fall through.
# --------------------------------------------------------------------------
def ask_claude(kind: str, system: str, user: str, extra: dict, progress: Progress) -> Optional[Any]:
    if not ai_requests.answerer_alive(kind):
        raise LookupError("no Claude answerer is polling the queue")
    rec = ai_requests.enqueue(kind, "", {"system": system, "user": user, **extra})
    rid = rec["id"]
    progress("Asking Claude…", 0.1)
    deadline = time.time() + CLAIM_TIMEOUT
    while True:
        cur = ai_requests.get(rid) or {}
        status = cur.get("status")
        if status in ("answered", "error"):
            break
        if status == "pending" and time.time() > deadline:
            if ai_requests.withdraw(rid):
                raise TimeoutError(f"no Claude answerer claimed the request within {CLAIM_TIMEOUT:g}s")
            continue    # claimed at the last moment
        if status == "claimed" and time.time() > deadline + ANSWER_TIMEOUT:
            raise TimeoutError("Claude took too long to answer")
        if status not in ("pending", "claimed", "answered", "error"):
            raise LookupError("the request disappeared")
        time.sleep(0.25)
    if cur.get("status") == "error":
        raise RuntimeError(f"Claude answerer error: {cur.get('error')}")
    return cur.get("answer")


def _http_json(url: str, body: Optional[dict] = None, timeout: float = 10.0) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET",
                                 headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode() or "{}")


def ask_local(kind: str, system: str, user: str, extra: dict, progress: Progress) -> Optional[Any]:
    """The local model through the gateway: the OpenAI-compatible passthrough
    when a model is loaded, else the gateway's ``/chat`` (which loads the
    model first; it gets the guide folded into its single prompt)."""
    progress("Asking the local AI…", 0.4)
    try:
        models = _http_json(f"{LOCAL_AI_URL}/v1/models", timeout=5).get("data") or []
        model = models[0]["id"] if models else "local"
        r = _http_json(f"{LOCAL_AI_URL}/v1/chat/completions", {
            "model": model, "temperature": 0.2, "max_tokens": 1500,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }, timeout=LOCAL_TIMEOUT)
        return r["choices"][0]["message"].get("content") or ""
    except (urllib.error.URLError, OSError, KeyError, IndexError, ValueError) as exc:
        logger.info("local passthrough unavailable (%s); trying /chat", exc)
    progress("Waking the local AI…", 0.45)
    r = _http_json(f"{LOCAL_AI_URL}/chat", {
        "prompt": system + "\n\n---\n\n" + user, "max_tokens": 1500, "temperature": 0.2,
    }, timeout=LOCAL_TIMEOUT)
    return r.get("text")


ASKERS: dict[str, Callable[..., Optional[Any]]] = {"claude": ask_claude, "local": ask_local}


def transcribe(data: bytes, filename: str = "note.webm") -> str:
    """A spoken description or piece of feedback → text, by the gateway's
    speech-to-text (``/transcribe_upload``, the same one the local AI apps
    use). Raises ``OSError`` when the gateway is unreachable."""
    boundary = "----aimusic" + os.urandom(8).hex()
    safe = "".join(c for c in filename if c.isalnum() or c in "._-") or "note.webm"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{safe}\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{LOCAL_AI_URL}/transcribe_upload", data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=LOCAL_TIMEOUT) as r:
        return str(json.loads(r.read().decode() or "{}").get("text") or "").strip()


def disagrees_with_rules(base: dict, plan: dict, feedback: str) -> Optional[str]:
    """When the rules recognise a piece of feedback, does a model's revision
    do what they would — and nothing destructive besides? Returns the problem,
    or None when it agrees (or the rules don't know the phrase). The local
    model tends to drop variants nobody mentioned ("too many fills" also
    removing the pocket bass); this catches that so the rules answer instead."""
    raw = json.loads(json.dumps(base))
    if not sp.apply_feedback_rules(raw, feedback):    # only the known phrases, not the parser's guesses
        return None
    ruled, _ = sp.normalize_plan(raw, base)
    eng = sp.engine_for(ruled["genre"])
    b, r, m = (set(sp.split_variants(x.get("arrangement"))) for x in (base, ruled, plan))
    if r - b - m:
        return "missing " + ", ".join(sorted(r - b - m))
    if (b - r) & m:
        return "kept " + ", ".join(sorted((b - r) & m))
    allowed = (b - r) | {v for g in eng.exclusive if set(g) & (r - b) for v in g} | set(eng.expands)
    if (b - m) - allowed:
        return "also removed " + ", ".join(sorted((b - m) - allowed))
    for k in sp.PLAN_FIELDS:
        if k in ("arrangement", "instruments") or ruled.get(k) == base.get(k):
            continue
        if k == "tempo" and plan.get(k) and base.get(k) is not None and ruled.get(k) is not None:
            if (plan[k] - base[k]) * (ruled[k] - base[k]) <= 0:
                return "tempo went the wrong way"
        elif plan.get(k) != ruled.get(k):
            return f"{k} should be {ruled.get(k)!r}"
    bi = set(base.get("instruments") or sp._preset_band(base["genre"]))
    ri = set(ruled.get("instruments") or sp._preset_band(ruled["genre"]))
    mi = set(plan.get("instruments") or sp._preset_band(plan["genre"]))
    if (bi - ri) & mi or (ri - bi) - mi:
        return "band doesn't match the feedback"
    return None


def _interpret(kind: str, user: str, extra: dict, previous: Optional[dict],
               rules: Callable[[], tuple[dict, str, list[str]]],
               progress: Progress) -> dict:
    system = sp.system_prompt()
    attempts: list[dict] = []
    for name in INTERPRETERS:
        if name == "rules":
            break
        ask = ASKERS.get(name)
        if ask is None:
            continue
        try:
            out = ask(kind, system, user, extra, progress)
            raw, summary = sp.parse_model_output(out)
            plan, notes = sp.normalize_plan(raw, previous)
            if name == "local" and kind == "revise":
                problem = disagrees_with_rules(previous, plan, extra.get("feedback", ""))
                if problem:
                    raise ValueError(f"answer disagrees with the known mapping ({problem})")
            attempts.append({"interpreter": name, "outcome": "ok"})
            return {"plan": plan, "summary": summary, "notes": notes,
                    "interpreter": name, "attempts": attempts}
        except Exception as exc:  # noqa: BLE001 — any failure falls through
            logger.info("describe: %s interpreter failed: %s", name, exc)
            attempts.append({"interpreter": name, "outcome": str(exc)[:200]})
    progress("Reading it with the rules…", 0.9)
    raw, summary, notes = rules()
    plan, more = sp.normalize_plan(raw, previous)
    attempts.append({"interpreter": "rules", "outcome": "ok"})
    return {"plan": plan, "summary": summary, "notes": notes + more,
            "interpreter": "rules", "attempts": attempts}


def _finish(res: dict) -> dict:
    plan = res["plan"]
    res["engine"] = sp.engine_for(plan["genre"]).id
    res["understood"] = sp.plan_chips(plan)
    if not res.get("summary"):
        res["summary"] = ", ".join(res["understood"])
    return res


def describe(text: str, progress: Progress = _noop) -> dict:
    """Plain-English description → ``{plan, summary, understood, notes,
    interpreter, engine, attempts}``."""
    text = (text or "").strip()

    def rules():
        raw, understood, notes = sp.rule_describe(text)
        return raw, "", notes

    res = _interpret("describe", sp.user_prompt("describe", text), {"text": text}, None, rules, progress)
    return _finish(res)


def revise(plan: dict, feedback: str, progress: Progress = _noop) -> dict:
    """Current plan + plain-English feedback → the revised plan, plus
    ``changes`` (what actually changed, computed, not claimed)."""
    feedback = (feedback or "").strip()
    base, _ = sp.normalize_plan(plan or {"genre": "funk_fusion_full"})

    def rules():
        new, fired = sp.rule_revise(base, feedback)
        notes = [] if fired else ["Couldn't match that feedback to an option. Try naming the part "
                                  "(e.g. “bass is too busy”, “fewer fills”, “no stabs”, “background level”)."]
        return new, ("Applied: " + ", ".join(fired)) if fired else "", notes

    res = _interpret("revise", sp.user_prompt("revise", feedback, base),
                     {"feedback": feedback, "plan": base}, base, rules, progress)
    res["changes"] = sp.describe_changes(base, res["plan"])
    if not res["changes"] and not res.get("notes"):
        res["notes"] = ["Nothing changed."]
    return _finish(res)
