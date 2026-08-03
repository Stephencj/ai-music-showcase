"""
Block version control — catalog a block's different generations/edits and
restore any one as the live block.

Mirrors the vocal-takes layout. Each version is a snapshot of the block's
musical content at a point in time, stored at:

    data/blocks/<name>.versions/<version_id>/
        block.mid      copy of the block MIDI (the source of truth)
        meta.yaml      copy of the block metadata sidecar
        preview.mp3    copy of the streaming preview (when present)
        version.json   {id, created, label, source, note, summary, ...}

The block's live files (``.mid`` / ``.yaml`` / ``.mp3``) stay the working
copy. Restoring a version overwrites them — but first auto-snapshots the
current state (``source: pre-restore``) so a restore is never destructive.
The active version id (which snapshot the live block currently matches) is
tracked in the block yaml as ``active_version``.
"""

from __future__ import annotations

import datetime as _dt
import json
import re
import shutil
from pathlib import Path

import yaml

from . import blocks as block_store


def _versions_dir(name: str) -> Path:
    return block_store.BLOCKS_DIR / f"{block_store._safe_name(name)}.versions"


def _safe_version_id(vid: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", vid or "")


_SOURCE_LABELS = {
    "manual": "Saved version",
    "pre-edit": "Before edit",
    "pre-restore": "Before restore",
}


def _summary_from_meta(meta: dict) -> dict:
    return {
        "n_notes": meta.get("n_notes"),
        "bars": meta.get("bars"),
        "tempo": meta.get("tempo"),
        "instruments": [i.get("name") for i in (meta.get("instruments") or [])],
    }


def _read_meta(name: str) -> dict:
    yp = block_store._yaml_path(name)
    if not yp.exists():
        return {}
    try:
        with open(yp) as f:
            return yaml.safe_load(f) or {}
    except Exception:  # noqa: BLE001 — a corrupt sidecar shouldn't crash versioning
        return {}


def _read_active(name: str) -> str | None:
    return _read_meta(name).get("active_version")


def _set_active(name: str, version_id: str | None) -> None:
    yp = block_store._yaml_path(name)
    if not yp.exists():
        return
    meta = _read_meta(name)
    if version_id:
        meta["active_version"] = version_id
    else:
        meta.pop("active_version", None)
    with open(yp, "w") as f:
        yaml.safe_dump(meta, f, sort_keys=False, default_flow_style=False)


def snapshot_version(name: str, *, label: str = "", source: str = "manual",
                     note: str = "", make_active: bool | None = None) -> dict:
    """Copy the block's current live files into a new version and return its
    metadata. ``source`` is one of manual | pre-edit | pre-restore. A manual
    snapshot marks itself active (the live block equals it); an automatic
    capture of a state about to be replaced does not, unless ``make_active``
    forces it."""
    midi = block_store._midi_path(name)
    if not midi.exists():
        raise FileNotFoundError(f"Block not found: {name}")
    vid = _dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")[:-3]
    vdir = _versions_dir(name) / vid
    vdir.mkdir(parents=True, exist_ok=True)

    shutil.copy2(midi, vdir / "block.mid")
    meta = _read_meta(name)
    yp = block_store._yaml_path(name)
    if yp.exists():
        shutil.copy2(yp, vdir / "meta.yaml")
    mp3 = block_store._preview_path(name)
    if mp3.exists():
        shutil.copy2(mp3, vdir / "preview.mp3")

    version = {
        "id": vid,
        "created": _dt.datetime.now().isoformat(timespec="seconds"),
        "label": label.strip() or _SOURCE_LABELS.get(source, "Version"),
        "source": source,
        "note": note or "",
        "has_preview": (vdir / "preview.mp3").exists(),
        "summary": _summary_from_meta(meta),
    }
    (vdir / "version.json").write_text(json.dumps(version, indent=2))

    if make_active is None:
        make_active = source == "manual"
    if make_active:
        _set_active(name, vid)
    return version


def list_versions(name: str) -> dict:
    """All versions for a block, newest first, each flagged ``active`` if the
    live block currently matches it. Returns ``{versions, active}``."""
    base = _versions_dir(name)
    active = _read_active(name)
    versions: list[dict] = []
    if base.exists():
        for d in base.iterdir():
            vj = d / "version.json"
            if not d.is_dir() or not vj.exists():
                continue
            try:
                v = json.loads(vj.read_text())
            except (OSError, ValueError):
                continue
            v["active"] = v.get("id") == active
            v["has_preview"] = (d / "preview.mp3").exists()
            versions.append(v)
    versions.sort(key=lambda v: str(v.get("created", "")), reverse=True)
    return {"versions": versions, "active": active}


def _vocal_label(take: dict) -> str:
    engine = (take.get("engine") or "").strip()
    voice = (take.get("voice") or "").replace("tiger_", "").strip()
    bits = [b for b in ("Sung", engine, voice) if b]
    return " · ".join(bits) if len(bits) > 1 else "Sung take"


def history(name: str) -> dict:
    """Unified per-block timeline: block versions + sung vocal takes, newest
    first. Version items carry the version fields (``kind: version``, +active);
    vocal items (``kind: vocal``) carry engine/voice/lyrics/files so the client
    can play or download the take. ``active`` is the active version id."""
    vinfo = list_versions(name)
    items: list[dict] = [{"kind": "version", **v} for v in vinfo["versions"]]
    for take in block_store.list_vocal_takes(name):
        items.append({
            "kind": "vocal",
            "id": take.get("id"),
            "created": take.get("created"),
            "label": _vocal_label(take),
            "engine": take.get("engine", ""),
            "voice": take.get("voice", ""),
            "harmonies": bool(take.get("harmonies")),
            "lyrics": take.get("lyrics", ""),
            "files": take.get("files", {}),
        })
    items.sort(key=lambda x: str(x.get("created", "")), reverse=True)
    return {"history": items, "active": vinfo["active"],
            "preview_take": _read_meta(name).get("preview_take")}


def version_preview_path(name: str, version_id: str) -> Path | None:
    """The version's preview MP3 (for A/B listening before restoring), or None."""
    p = _versions_dir(name) / _safe_version_id(version_id) / "preview.mp3"
    return p if p.exists() else None


def restore_version(name: str, version_id: str, *, snapshot_current: bool = True) -> dict:
    """Make ``version_id`` the live block. First auto-snapshots the current
    state (so nothing is lost), then copies the version's files onto the live
    block and invalidates the derived WAV/peaks so they regenerate from the
    restored MIDI. Returns ``{restored, snapshot_of_previous?}``."""
    vid = _safe_version_id(version_id)
    vdir = _versions_dir(name) / vid
    vmid = vdir / "block.mid"
    if not vmid.exists():
        raise FileNotFoundError(f"No such version: {version_id}")

    result: dict = {"restored": vid}
    if snapshot_current and block_store._midi_path(name).exists():
        prev = snapshot_version(name, source="pre-restore", make_active=False)
        result["snapshot_of_previous"] = prev["id"]

    shutil.copy2(vmid, block_store._midi_path(name))
    vy = vdir / "meta.yaml"
    if vy.exists():
        shutil.copy2(vy, block_store._yaml_path(name))
    vp = vdir / "preview.mp3"
    if vp.exists():
        shutil.copy2(vp, block_store._preview_path(name))

    # The restored MP3 is correct immediately; the big WAV + cached peaks are
    # stale, so drop them — they lazily re-render from the restored MIDI.
    for p in (block_store._wav_path(name), block_store._peaks_path(name)):
        try:
            if p.exists():
                p.unlink()
        except OSError:
            pass

    _set_active(name, vid)
    return result


def delete_version(name: str, version_id: str) -> bool:
    """Remove one version. Returns True if it existed."""
    vid = _safe_version_id(version_id)
    d = _versions_dir(name) / vid
    if d.exists() and d.is_dir():
        if _read_active(name) == vid:
            _set_active(name, None)
        shutil.rmtree(d, ignore_errors=True)
        return True
    return False
