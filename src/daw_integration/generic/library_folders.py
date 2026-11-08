"""
Library folders — group saved pieces, e.g. one folder per video.

Folders live in one file next to the entries, ``data/library/folders.yaml``::

    folders:
    - id: videos
      name: Videos
      parent: ''               # '' = top level; subfolders go one level deep
      description: ''
      items: []                # ordered library entry ids (= the track order)
      created: 2026-11-08T10:00:00
    - id: christmas-mix-1
      name: Christmas Mix 1
      parent: videos
      description: 1-hour cozy Christmas mix
      items: [Silent_Night, Jingle_Bells]
      created: 2026-11-08T10:01:00
    filed: {Silent_Night: Christmas samples}

Membership is a link, so one entry can sit in several folders; an entry in
no folder is "Unfiled" (a virtual folder, id ``unfiled``). Deleting a folder
never deletes entries, only the links.

``filed`` remembers which entry ``collection`` values have been turned into
folder memberships. Any entry whose collection isn't recorded there yet
(older data, or a client that still only sets ``collection``) is filed into
a folder of that name on the next read — once, so moving it out sticks.

Every read-modify-write holds an exclusive file lock (the API server and the
MCP stdio server are separate processes) and saves atomically.
"""

from __future__ import annotations

import fcntl
import re
import threading
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

import yaml

from . import library

UNFILED = "unfiled"
UNFILED_NAME = "Unfiled"
PATH_SEP = " / "

_thread_lock = threading.RLock()


class FolderError(ValueError):
    """A folder operation can't be done; the message says why."""


def _file() -> Path:
    return library.LIBRARY_DIR / library.FOLDERS_FILE


@contextmanager
def _locked():
    """Exclusive lock across threads and processes for a read-modify-write."""
    with _thread_lock:
        library.LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        with open(library.LIBRARY_DIR / ".folders.lock", "a") as lf:
            fcntl.flock(lf, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lf, fcntl.LOCK_UN)


def _load() -> dict:
    p = _file()
    state = library._read(p) if p.exists() else {}
    state.setdefault("folders", [])
    state.setdefault("filed", {})
    for f in state["folders"]:
        f.setdefault("parent", "")
        f.setdefault("description", "")
        f["items"] = list(f.get("items") or [])
    return state


def _save(state: dict) -> None:
    library._write(_file(), {"folders": state["folders"], "filed": state["filed"]})


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "folder"


def _clean_name(name: str) -> str:
    name = " ".join((name or "").split())
    if not name:
        raise FolderError("A folder needs a name.")
    if "/" in name:
        raise FolderError("Folder names can't contain '/'; use parent= for a subfolder.")
    if name.lower() == UNFILED:
        raise FolderError(f"{UNFILED_NAME!r} is reserved for songs that aren't in any folder.")
    return name


def _by_id(state: dict) -> dict[str, dict]:
    return {f["id"]: f for f in state["folders"]}


def _path_of(f: dict, ids: dict[str, dict]) -> str:
    parent = ids.get(f.get("parent") or "")
    return f"{parent['name']}{PATH_SEP}{f['name']}" if parent else f["name"]


def _ensure_unique(state: dict, name: str, parent: str, skip: str = "") -> None:
    for f in state["folders"]:
        if f["id"] != skip and (f.get("parent") or "") == parent and f["name"].lower() == name.lower():
            raise FolderError(f"There's already a folder named {name!r} there.")


def _resolve(state: dict, ref: str) -> Optional[dict]:
    """A folder by id, path ("Videos / Mix 1") or unique name. ``None`` means
    Unfiled. Raises FolderError when nothing (or more than one) matches."""
    ref = (ref or "").strip()
    if not ref or ref.lower() in (UNFILED, UNFILED_NAME.lower()):
        return None
    ids = _by_id(state)
    if ref in ids:
        return ids[ref]
    want = PATH_SEP.join(p.strip() for p in ref.split("/")).lower()
    by_path = [f for f in state["folders"] if _path_of(f, ids).lower() == want]
    if len(by_path) == 1:
        return by_path[0]
    by_name = [f for f in state["folders"] if f["name"].lower() == ref.lower()]
    if len(by_name) == 1:
        return by_name[0]
    if by_name:
        paths = ", ".join(_path_of(f, ids) for f in by_name)
        raise FolderError(f"{ref!r} matches several folders ({paths}); use the full path or id.")
    names = ", ".join(_path_of(f, ids) for f in state["folders"]) or "none yet"
    raise FolderError(f"No folder {ref!r}. Folders: {names}.")


def _sync_collections(state: dict, entries: list[dict]) -> bool:
    """File entries by their ``collection`` the first time each is seen
    (this is also the one-time migration of existing data)."""
    changed = False
    for e in sorted(entries, key=lambda e: e.get("added") or ""):
        eid, coll = e.get("id"), " ".join(str(e.get("collection") or "").split())
        if not eid or not coll or state["filed"].get(eid) == coll:
            continue
        try:
            folder = _resolve(state, coll)
        except FolderError:
            folder = _folder_for_collection(state, coll)
        if folder is not None and eid not in folder["items"]:
            folder["items"].append(eid)
        state["filed"][eid] = coll
        changed = True
    return changed


def _folder_for_collection(state: dict, coll: str) -> Optional[dict]:
    """Find or create the folder a collection names: "Mix" or "Videos/Mix"."""
    parts = [p.strip() for p in coll.split("/") if p.strip()]
    if not parts:
        return None
    names = parts if len(parts) == 1 else [parts[0], " - ".join(parts[1:])]
    parent, folder = "", None
    try:
        for name in names:
            folder = next((f for f in state["folders"] if (f.get("parent") or "") == parent
                           and f["name"].lower() == name.lower()), None) or _new_folder(state, name, parent)
            parent = folder["id"]
    except FolderError:          # e.g. a collection literally called "Unfiled"
        return None
    return folder


def _new_folder(state: dict, name: str, parent: str = "", description: str = "") -> dict:
    name = _clean_name(name)
    ids = _by_id(state)
    if parent:
        if parent not in ids:
            raise FolderError(f"No parent folder {parent!r}.")
        if ids[parent].get("parent"):
            raise FolderError("Subfolders go one level deep: the parent must be a top-level folder.")
    _ensure_unique(state, name, parent)
    base = _slug(f"{ids[parent]['name']}-{name}" if parent else name)
    fid, n = base, 2
    while fid in ids or fid == UNFILED:
        fid, n = f"{base}-{n}", n + 1
    folder = {"id": fid, "name": name, "parent": parent, "description": (description or "").strip(),
              "items": [], "created": _now()}
    state["folders"].append(folder)
    return folder


@contextmanager
def _state(write: bool = False):
    """The folder state with collections synced; saved on exit when ``write``
    (or when the sync filed something)."""
    with _locked():
        state = _load()
        entries = library.list_entries()
        synced = _sync_collections(state, entries)
        state["_entries"] = {e["id"]: e for e in entries}
        yield state
        state.pop("_entries", None)
        if write or synced:
            _save(state)


def _ordered(state: dict) -> list[dict]:
    """Top-level folders by name, each followed by its subfolders by name."""
    tops = sorted((f for f in state["folders"] if not f.get("parent")), key=lambda f: f["name"].lower())
    out = []
    for t in tops:
        out.append(t)
        out += sorted((f for f in state["folders"] if f.get("parent") == t["id"]),
                      key=lambda f: f["name"].lower())
    return out


def _live_items(state: dict, f: dict) -> list[str]:
    return [i for i in f["items"] if i in state["_entries"]]


def _summary(state: dict, f: dict) -> dict:
    ids = _by_id(state)
    return {"id": f["id"], "name": f["name"], "path": _path_of(f, ids), "parent": f.get("parent") or "",
            "description": f.get("description") or "", "item_count": len(_live_items(state, f)),
            "subfolders": [c["id"] for c in _ordered(state) if c.get("parent") == f["id"]],
            "created": f.get("created")}


def _unfiled_ids(state: dict) -> list[str]:
    filed = {i for f in state["folders"] for i in f["items"]}
    entries = sorted(state["_entries"].values(), key=lambda e: e.get("added") or "", reverse=True)
    return [e["id"] for e in entries if e["id"] not in filed]


def _unfiled_summary(state: dict) -> dict:
    return {"id": UNFILED, "name": UNFILED_NAME, "path": UNFILED_NAME, "parent": "",
            "description": "Songs that aren't in any folder.", "item_count": len(_unfiled_ids(state)),
            "subfolders": [], "created": None, "virtual": True}


def _check_entries(state: dict, entry_ids: Iterable[str]) -> list[str]:
    out = []
    for eid in entry_ids:
        if eid not in state["_entries"]:
            raise FolderError(f"No library entry {eid!r}.")
        if eid not in out:
            out.append(eid)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_folders() -> dict:
    """Every folder (top level by name, subfolders after their parent) with
    item counts, plus the virtual Unfiled folder."""
    with _state() as state:
        return {"folders": [_summary(state, f) for f in _ordered(state)],
                "unfiled": _unfiled_summary(state)}


def get_folder(ref: str) -> dict:
    """One folder with its entries in order (``items``) and subfolders."""
    with _state() as state:
        f = _resolve(state, ref)
        if f is None:
            return {**_unfiled_summary(state), "items": [state["_entries"][i] for i in _unfiled_ids(state)]}
        return {**_summary(state, f), "items": [state["_entries"][i] for i in _live_items(state, f)]}


def create_folder(name: str, parent: str = "", description: str = "") -> dict:
    with _state(write=True) as state:
        parent_id = _resolve(state, parent)["id"] if parent and parent.strip() else ""
        return _summary(state, _new_folder(state, name, parent_id, description))


def update_folder(ref: str, *, name: Optional[str] = None, description: Optional[str] = None,
                  parent: Optional[str] = None) -> dict:
    """Rename, re-describe, or re-parent a folder (``parent=''`` → top level)."""
    with _state(write=True) as state:
        f = _resolve(state, ref)
        if f is None:
            raise FolderError(f"{UNFILED_NAME} can't be changed.")
        new_parent = f.get("parent") or ""
        if parent is not None:
            p = _resolve(state, parent) if parent.strip() else None
            new_parent = p["id"] if p else ""
            if new_parent == f["id"]:
                raise FolderError("A folder can't be inside itself.")
            if new_parent and _by_id(state)[new_parent].get("parent"):
                raise FolderError("Subfolders go one level deep: the parent must be a top-level folder.")
            if new_parent and any(c.get("parent") == f["id"] for c in state["folders"]):
                raise FolderError("This folder has subfolders, so it has to stay top level.")
        new_name = _clean_name(name) if name is not None else f["name"]
        _ensure_unique(state, new_name, new_parent, skip=f["id"])
        f["name"], f["parent"] = new_name, new_parent
        if description is not None:
            f["description"] = description.strip()
        return _summary(state, f)


def delete_folder(ref: str) -> dict:
    """Delete a folder. Its songs stay in the library (in no other folder →
    Unfiled); its subfolders move up to the top level."""
    with _state(write=True) as state:
        f = _resolve(state, ref)
        if f is None:
            raise FolderError(f"{UNFILED_NAME} can't be deleted.")
        state["folders"].remove(f)
        promoted = []
        for c in state["folders"]:
            if c.get("parent") == f["id"]:
                c["parent"] = ""
                base, n = c["name"], 2
                while any(o is not c and not o.get("parent") and o["name"].lower() == c["name"].lower()
                          for o in state["folders"]):
                    c["name"], n = f"{base} ({n})", n + 1
                promoted.append(c["id"])
        now_unfiled = [i for i in _live_items(state, f) if i in _unfiled_ids(state)]
        return {"deleted": f["id"], "name": f["name"], "now_unfiled": now_unfiled, "promoted": promoted}


def add_items(ref: str, entry_ids: list[str], position: Optional[int] = None) -> dict:
    """Link entries into a folder (a copy: other memberships stay). Entries
    already there keep their place. ``position`` is 0-based; default = end."""
    with _state(write=True) as state:
        f = _resolve(state, ref)
        if f is None:
            raise FolderError(f"Use move_to_folder to send songs to {UNFILED_NAME}.")
        new = [i for i in _check_entries(state, entry_ids) if i not in f["items"]]
        _insert(f, new, position)
        return _summary(state, f)


def _insert(f: dict, ids: list[str], position: Optional[int]) -> None:
    at = len(f["items"]) if position is None else max(0, min(int(position), len(f["items"])))
    f["items"][at:at] = ids


def remove_item(ref: str, entry_id: str) -> dict:
    """Unlink an entry from one folder (the song stays in the library)."""
    with _state(write=True) as state:
        f = _resolve(state, ref)
        if f is None:
            raise FolderError(f"Songs leave {UNFILED_NAME} by being added to a folder.")
        if entry_id not in f["items"]:
            raise FolderError(f"{entry_id!r} isn't in {f['name']!r}.")
        f["items"].remove(entry_id)
        return _summary(state, f)


def move_item(entry_id: str, to: str, from_: str = "", position: Optional[int] = None) -> dict:
    """Move an entry into folder ``to``: out of ``from_`` if given, else out
    of every other folder. ``to`` = Unfiled just takes it out."""
    with _state(write=True) as state:
        _check_entries(state, [entry_id])
        dest = _resolve(state, to)
        sources = ([_resolve(state, from_)] if from_ and from_.strip()
                   else [f for f in state["folders"] if f is not dest])
        for s in sources:
            if s is not None and s is not dest and entry_id in s["items"]:
                s["items"].remove(entry_id)
        if dest is not None and entry_id not in dest["items"]:
            _insert(dest, [entry_id], position)
        elif dest is not None and position is not None:
            dest["items"].remove(entry_id)
            _insert(dest, [entry_id], position)
        return {"entry_id": entry_id, "folders": _paths_for(state, entry_id)}


def reorder(ref: str, entry_ids: list[str]) -> dict:
    """Set a folder's track order. Listed entries go first in that order; any
    left out keep their relative order after them."""
    with _state(write=True) as state:
        f = _resolve(state, ref)
        if f is None:
            raise FolderError(f"{UNFILED_NAME} has no order of its own (newest first).")
        unknown = [i for i in entry_ids if i not in f["items"]]
        if unknown:
            raise FolderError(f"Not in {f['name']!r}: {unknown}. It holds: {f['items']}.")
        listed = list(dict.fromkeys(entry_ids))
        f["items"] = listed + [i for i in f["items"] if i not in listed]
        return {**_summary(state, f), "items": _live_items(state, f)}


def _paths_for(state: dict, entry_id: str) -> list[dict]:
    ids = _by_id(state)
    return [{"id": f["id"], "path": _path_of(f, ids)} for f in _ordered(state) if entry_id in f["items"]]


def folders_by_entry() -> dict[str, list[dict]]:
    """``{entry_id: [{id, path}, ...]}`` for decorating library listings."""
    with _state() as state:
        return {eid: _paths_for(state, eid) for eid in state["_entries"]}


def forget_entry(entry_id: str) -> None:
    """Drop a deleted entry from every folder (and the collection record)."""
    with _locked():
        state = _load()
        changed = state["filed"].pop(entry_id, None) is not None
        for f in state["folders"]:
            if entry_id in f["items"]:
                f["items"].remove(entry_id)
                changed = True
        if changed:
            _save(state)
