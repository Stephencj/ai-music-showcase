"""POST /api/transcribe: a voice note → text through the gateway's
speech-to-text (src/api/describe.transcribe), stubbed here."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api import describe
from src.api.routes import router


def _client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_transcribe_forwards_the_upload(monkeypatch):
    seen = {}

    def fake(data, filename="note.webm"):
        seen.update(data=data, filename=filename)
        return "make the bass simpler"

    monkeypatch.setattr(describe, "transcribe", fake)
    r = _client().post("/api/transcribe", files={"file": ("note.m4a", b"abc", "audio/mp4")})
    assert r.status_code == 200 and r.json() == {"text": "make the bass simpler"}
    assert seen == {"data": b"abc", "filename": "note.m4a"}


def test_transcribe_unavailable_is_503(monkeypatch):
    def down(*_a, **_k):
        raise OSError("connection refused")

    monkeypatch.setattr(describe, "transcribe", down)
    r = _client().post("/api/transcribe", files={"file": ("note.webm", b"abc", "audio/webm")})
    assert r.status_code == 503


def test_transcribe_empty_is_400():
    r = _client().post("/api/transcribe", files={"file": ("note.webm", b"", "audio/webm")})
    assert r.status_code == 400


def test_transcribe_multipart_reaches_the_gateway(monkeypatch):
    captured = {}

    class Resp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return b'{"text": " Slower please. "}'

    def fake_urlopen(req, timeout=0):
        captured.update(url=req.full_url, ctype=req.headers.get("Content-type"), body=req.data)
        return Resp()

    monkeypatch.setattr(describe.urllib.request, "urlopen", fake_urlopen)
    assert describe.transcribe(b"RIFFdata", "my note.wav") == "Slower please."
    assert captured["url"].endswith("/transcribe_upload")
    assert captured["ctype"].startswith("multipart/form-data; boundary=")
    assert b'filename="mynote.wav"' in captured["body"] and b"RIFFdata" in captured["body"]
