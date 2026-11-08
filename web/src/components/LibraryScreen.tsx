import { useCallback, useEffect, useState } from "react";
import {
  DndContext,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import * as api from "../api";
import type { LibraryEntry, LibraryFolder, ScorePart } from "../api";

const ALL = "";                 // the "All songs" view (not a folder)
const UNFILED = "unfiled";

/**
 * Sheet-music library — the saved pieces, backend is the source of truth.
 *
 * Each entry reuses the block's existing assets: inline audio playback, a
 * "View PDF" link that opens the bare full-score PDF (the native iOS shell
 * intercepts application/pdf and shows it in a PDFKit viewer), and an
 * "open" action that jumps to the Practice screen where the piano-roll,
 * tab/notation and playback already live — no viewer is reimplemented here.
 *
 * Folders (one per video) sit above the list: pick one to see its songs in
 * track order and drag the ≡ handle to reorder; "Move to folder…" on a card
 * files it. Unfiled is every song in no folder.
 */
export default function LibraryScreen({ isActive, onOpen }: {
  isActive: boolean;
  onOpen: (block: string) => void;
}) {
  const [entries, setEntries] = useState<LibraryEntry[] | null>(null);
  const [folders, setFolders] = useState<LibraryFolder[]>([]);
  const [unfiled, setUnfiled] = useState<LibraryFolder | null>(null);
  const [current, setCurrent] = useState<string>(ALL);
  const [folderItems, setFolderItems] = useState<LibraryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const fail = (err: unknown) => setError(err instanceof Error ? err.message : String(err));

  const load = useCallback(async (folder: string = current) => {
    setBusy(true);
    setError(null);
    try {
      const [lib, fl] = await Promise.all([api.getLibrary(), api.getFolders()]);
      setEntries(lib);
      setFolders(fl.folders);
      setUnfiled(fl.unfiled);
      const exists = folder === ALL || folder === UNFILED || fl.folders.some((f) => f.id === folder);
      const target = exists ? folder : ALL;
      setCurrent(target);
      setFolderItems(target === ALL ? null : (await api.getFolder(target)).items);
    } catch (e) {
      fail(e);
    } finally {
      setBusy(false);
    }
  }, [current]);

  // Refresh whenever the tab becomes active so newly-saved pieces appear.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(() => { if (isActive) load(); }, [isActive]);

  const open = (id: string) => { setFolderItems(null); load(id); };

  const toggleFav = async (e: LibraryEntry) => {
    try {
      await api.setLibraryFavorite(e.id, !e.favorite);
      const flip = (cur: LibraryEntry[] | null) =>
        cur?.map((x) => (x.id === e.id ? { ...x, favorite: !e.favorite } : x)) ?? null;
      setEntries(flip);
      setFolderItems(flip);
    } catch (err) {
      fail(err);
    }
  };

  // Inside a folder, Remove only takes the song out of that folder; deleting
  // from the whole library is only offered in All songs / Unfiled.
  const inFolder = current !== ALL && current !== UNFILED;
  const remove = async (e: LibraryEntry) => {
    try {
      if (inFolder) {
        await api.removeFromFolder(current, e.id);
        await load();
        return;
      }
      if (!window.confirm(`Delete "${e.title}" from the library? This removes it from every folder.`)) return;
      await api.removeFromLibrary(e.id);
      await load();
    } catch (err) {
      fail(err);
    }
  };

  const move = async (e: LibraryEntry, to: string) => {
    try {
      // Inside a folder, move out of that one; elsewhere, out of every folder.
      const from = current !== ALL && current !== UNFILED ? current : "";
      await api.moveLibraryEntry(e.id, to, from);
      await load();
    } catch (err) {
      fail(err);
    }
  };

  const newFolder = async (parent = "") => {
    const name = window.prompt(parent ? "New subfolder name" : "New folder name (e.g. a video)");
    if (!name || !name.trim()) return;
    try {
      const f = await api.createFolder(name.trim(), parent);
      await load(f.id);
    } catch (err) {
      fail(err);
    }
  };

  const folder = folders.find((f) => f.id === current) ?? null;

  const renameFolder = async () => {
    if (!folder) return;
    const name = window.prompt("Rename folder", folder.name);
    if (!name || !name.trim() || name.trim() === folder.name) return;
    try { await api.updateFolder(folder.id, { name: name.trim() }); await load(); } catch (err) { fail(err); }
  };

  const describeFolder = async () => {
    if (!folder) return;
    const description = window.prompt("Folder note (e.g. what the video is)", folder.description);
    if (description === null) return;
    try { await api.updateFolder(folder.id, { description }); await load(); } catch (err) { fail(err); }
  };

  const removeFolder = async () => {
    if (!folder) return;
    const subs = folder.subfolders.length ? " Its subfolders move to the top level." : "";
    if (!window.confirm(`Delete the folder "${folder.path}"? Its songs stay in the library.${subs}`)) return;
    try { await api.deleteFolder(folder.id); await load(ALL); } catch (err) { fail(err); }
  };

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const onDragEnd = async (ev: DragEndEvent) => {
    if (!folder || !folderItems || !ev.over || ev.active.id === ev.over.id) return;
    const ids = folderItems.map((x) => x.id);
    const next = arrayMove(folderItems, ids.indexOf(String(ev.active.id)), ids.indexOf(String(ev.over.id)));
    setFolderItems(next);
    try { await api.reorderFolder(folder.id, next.map((x) => x.id)); } catch (err) { fail(err); load(); }
  };

  // All songs: favorites first, then newest. A folder: its own track order.
  const sorted = (entries ?? []).slice().sort(
    (a, b) => Number(b.favorite) - Number(a.favorite) || (b.added || "").localeCompare(a.added || ""));
  const shown = current === ALL ? sorted : folderItems ?? [];
  const sortable = folder !== null && shown.length > 1;

  const cards = shown.map((e) => (
    <LibraryCard key={e.id} entry={e} folders={folders} current={current} sortable={sortable}
      onOpen={onOpen} onToggleFav={toggleFav} onRemove={remove} onMove={move} />
  ));

  return (
    <div className="library-screen" data-testid="library-screen">
      <div className="library-head">
        <h2>Sheet Music Library</h2>
        <div className="library-head-actions">
          <button className="btn ghost sm" onClick={() => newFolder()} data-testid="new-folder">+ Folder</button>
          <button className="btn ghost sm" onClick={() => load()} disabled={busy} aria-label="Refresh library">
            {busy ? "…" : "↻"}
          </button>
        </div>
      </div>

      {error && <div className="error" role="alert">{error}</div>}
      {entries === null && !error && <div className="progress-msg">Loading…</div>}

      {entries !== null && (
        <div className="card folder-tree" data-testid="folder-tree">
          <FolderRow label="All songs" count={entries.length} on={current === ALL} onClick={() => open(ALL)} id="all" />
          {folders.map((f) => (
            <FolderRow key={f.id} id={f.id} label={f.name} count={f.item_count} sub={!!f.parent}
              on={current === f.id} onClick={() => open(f.id)} />
          ))}
          {unfiled && (
            <FolderRow id={UNFILED} label="Unfiled" count={unfiled.item_count} muted
              on={current === UNFILED} onClick={() => open(UNFILED)} />
          )}
        </div>
      )}

      {folder && (
        <div className="folder-head" data-testid="folder-head">
          <div className="lib-title">{folder.path}</div>
          {folder.description && <div className="te-note" data-testid="folder-note">{folder.description}</div>}
          <div className="links library-actions">
            <button className="btn ghost sm" onClick={renameFolder} data-testid="rename-folder">Rename</button>
            <button className="btn ghost sm" onClick={describeFolder} data-testid="describe-folder">Note</button>
            {!folder.parent && (
              <button className="btn ghost sm" onClick={() => newFolder(folder.id)} data-testid="new-subfolder">
                + Subfolder
              </button>
            )}
            <button className="btn ghost sm danger" onClick={removeFolder} data-testid="delete-folder">Delete</button>
          </div>
        </div>
      )}

      {entries !== null && entries.length === 0 && !error && (
        <div className="library-empty" data-testid="library-empty">
          <p>No saved sheet music yet.</p>
          <p className="te-note">
            Save a piece from the <strong>Compose</strong> tab — tap <strong>★ Save to Library</strong>
            {" "}on any block — and it will appear here with its score, playback, piano-roll and tab.
          </p>
        </div>
      )}

      {entries !== null && entries.length > 0 && current !== ALL && folderItems !== null && shown.length === 0 && (
        <div className="library-empty" data-testid="folder-empty">
          <p>{current === UNFILED ? "Every song is in a folder." : "No songs in this folder yet."}</p>
          {current !== UNFILED && (
            <p className="te-note">Use <strong>Move to folder…</strong> on a song to add it here.</p>
          )}
        </div>
      )}

      <div className="library-list">
        {sortable ? (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={shown.map((e) => e.id)} strategy={verticalListSortingStrategy}>
              {cards}
            </SortableContext>
          </DndContext>
        ) : cards}
      </div>
    </div>
  );
}

function FolderRow({ id, label, count, on, sub, muted, onClick }: {
  id: string; label: string; count: number; on: boolean; sub?: boolean; muted?: boolean; onClick: () => void;
}) {
  return (
    <button className={"folder-row" + (on ? " on" : "") + (sub ? " sub" : "") + (muted ? " muted" : "")}
      onClick={onClick} data-testid="folder-row" data-folder={id} aria-pressed={on}>
      <span className="folder-name">{sub ? "↳ " : ""}{label}</span>
      <span className="count">{count}</span>
    </button>
  );
}

/**
 * One saved piece. The instrument picker lets you choose which part's sheet
 * music to open *before* opening the PDF; the parts list is fetched lazily
 * (engraving is expensive) the first time the picker is touched. The chosen
 * part drives the "View PDF" link, which the native iOS shell opens in its
 * PDFKit viewer (and where an in-viewer toggle will also live).
 */
function LibraryCard({ entry, folders, current, sortable, onOpen, onToggleFav, onRemove, onMove }: {
  entry: LibraryEntry;
  folders: LibraryFolder[];
  current: string;
  sortable: boolean;
  onOpen: (block: string) => void;
  onToggleFav: (e: LibraryEntry) => void;
  onRemove: (e: LibraryEntry) => void;
  onMove: (e: LibraryEntry, to: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: entry.id, disabled: !sortable });
  const dragStyle: React.CSSProperties = sortable
    ? { transform: CSS.Transform.toString(transform), transition, opacity: isDragging ? 0.6 : 1,
        position: "relative", zIndex: isDragging ? 5 : undefined }
    : {};
  const fullOption: ScorePart = { id: "full", name: "Full score", url: entry.pdf_url };
  const [parts, setParts] = useState<ScorePart[] | null>(null);
  const [selected, setSelected] = useState("full");
  const [loadingParts, setLoadingParts] = useState(false);

  const ensureParts = async () => {
    if (parts || loadingParts) return;
    setLoadingParts(true);
    try {
      setParts(await api.getParts(entry.block_name));
    } catch {
      setParts([fullOption]); // fall back to full-score only
    } finally {
      setLoadingParts(false);
    }
  };

  const options = parts ?? [fullOption];
  const pdfUrl = options.find((p) => p.id === selected)?.url ?? entry.pdf_url;

  return (
    <div ref={setNodeRef} style={dragStyle} className="card library-card" data-testid="library-card"
      data-block={entry.block_name} data-entry={entry.id}>
      <div className="library-card-head">
        {sortable && (
          <span className="tl-drag lib-drag" {...attributes} {...listeners} data-testid="drag-handle"
            aria-label="Drag to reorder">≡</span>
        )}
        <button
          className={"fav-btn" + (entry.favorite ? " on" : "")}
          onClick={() => onToggleFav(entry)}
          aria-pressed={entry.favorite}
          aria-label={entry.favorite ? "Unfavorite" : "Favorite"}
          title={entry.favorite ? "Unfavorite" : "Favorite"}
        >{entry.favorite ? "★" : "☆"}</button>
        <div className="library-card-title">
          <div className="lib-title">{entry.title}</div>
          <div className="te-note">
            {(entry.folders ?? []).filter((f) => f.id !== current).map((f) => (
              <span key={f.id} className="pill">{f.path}</span>
            ))}
            {entry.added && <span> saved {new Date(entry.added).toLocaleDateString()}</span>}
          </div>
        </div>
      </div>

      <audio controls preload="none" src={api.mediaUrl(entry.audio_url)} />

      <div className="library-part-row">
        <label className="te-note" htmlFor={`part-${entry.id}`}>Sheet music</label>
        <select
          id={`part-${entry.id}`}
          className="part-select"
          data-testid="part-select"
          value={selected}
          onFocus={ensureParts}
          onMouseDown={ensureParts}
          onChange={(ev) => setSelected(ev.target.value)}
        >
          {options.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
        {loadingParts && <span className="te-note">loading parts…</span>}
      </div>

      <div className="links library-actions">
        <a className="btn secondary sm" href={api.mediaUrl(pdfUrl)} data-testid="view-pdf">📄 View PDF</a>
        <button className="btn secondary sm" onClick={() => onOpen(entry.block_name)} data-testid="open-practice">
          🎹 Roll · Tab · Play
        </button>
        <a className="btn ghost sm" href={api.mediaUrl(entry.pdf_zip_url)} download>↓ All parts</a>
        <select
          className="part-select move-select"
          data-testid="move-to-folder"
          aria-label="Move to folder"
          value=""
          onChange={(ev) => { if (ev.target.value) onMove(entry, ev.target.value); }}
        >
          <option value="">Move to folder…</option>
          {folders.filter((f) => f.id !== current).map((f) => (
            <option key={f.id} value={f.id}>{f.path}</option>
          ))}
          {(entry.folders ?? []).length > 0 && <option value={UNFILED}>Unfiled (out of folders)</option>}
        </select>
        {current !== ALL && current !== UNFILED ? (
          <button className="btn ghost sm" onClick={() => onRemove(entry)} data-testid="remove-from-folder"
            aria-label="Remove from this folder">
            Remove from folder
          </button>
        ) : (
          <button className="btn ghost sm danger" onClick={() => onRemove(entry)} data-testid="remove-entry"
            aria-label="Delete from library">
            🗑 Delete
          </button>
        )}
      </div>
    </div>
  );
}
