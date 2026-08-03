import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import type { LibraryEntry, ScorePart } from "../api";

/**
 * Sheet-music library — the saved pieces, backend is the source of truth.
 *
 * Each entry reuses the block's existing assets: inline audio playback, a
 * "View PDF" link that opens the bare full-score PDF (the native iOS shell
 * intercepts application/pdf and shows it in a PDFKit viewer), and an
 * "open" action that jumps to the Practice screen where the piano-roll,
 * tab/notation and playback already live — no viewer is reimplemented here.
 */
export default function LibraryScreen({ isActive, onOpen }: {
  isActive: boolean;
  onOpen: (block: string) => void;
}) {
  const [entries, setEntries] = useState<LibraryEntry[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      setEntries(await api.getLibrary());
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }, []);

  // Refresh whenever the tab becomes active so newly-saved pieces appear.
  useEffect(() => { if (isActive) load(); }, [isActive, load]);

  const toggleFav = async (e: LibraryEntry) => {
    try {
      await api.setLibraryFavorite(e.id, !e.favorite);
      setEntries((cur) => cur?.map((x) => (x.id === e.id ? { ...x, favorite: !e.favorite } : x)) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const remove = async (e: LibraryEntry) => {
    if (!window.confirm(`Remove "${e.title}" from the library?`)) return;
    try {
      await api.removeFromLibrary(e.id);
      setEntries((cur) => cur?.filter((x) => x.id !== e.id) ?? null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  // Favorites first, then newest.
  const sorted = (entries ?? []).slice().sort(
    (a, b) => Number(b.favorite) - Number(a.favorite) || (b.added || "").localeCompare(a.added || ""));

  return (
    <div className="library-screen" data-testid="library-screen">
      <div className="library-head">
        <h2>Sheet Music Library</h2>
        <button className="btn ghost sm" onClick={load} disabled={busy} aria-label="Refresh library">
          {busy ? "…" : "↻"}
        </button>
      </div>

      {error && <div className="error" role="alert">{error}</div>}
      {entries === null && !error && <div className="progress-msg">Loading…</div>}

      {entries !== null && sorted.length === 0 && !error && (
        <div className="library-empty" data-testid="library-empty">
          <p>No saved sheet music yet.</p>
          <p className="te-note">
            Save a piece from the <strong>Compose</strong> tab — tap <strong>★ Save to Library</strong>
            {" "}on any block — and it will appear here with its score, playback, piano-roll and tab.
          </p>
        </div>
      )}

      <div className="library-list">
        {sorted.map((e) => (
          <LibraryCard key={e.id} entry={e}
            onOpen={onOpen} onToggleFav={toggleFav} onRemove={remove} />
        ))}
      </div>
    </div>
  );
}

/**
 * One saved piece. The instrument picker lets you choose which part's sheet
 * music to open *before* opening the PDF; the parts list is fetched lazily
 * (engraving is expensive) the first time the picker is touched. The chosen
 * part drives the "View PDF" link, which the native iOS shell opens in its
 * PDFKit viewer (and where an in-viewer toggle will also live).
 */
function LibraryCard({ entry, onOpen, onToggleFav, onRemove }: {
  entry: LibraryEntry;
  onOpen: (block: string) => void;
  onToggleFav: (e: LibraryEntry) => void;
  onRemove: (e: LibraryEntry) => void;
}) {
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
    <div className="card library-card" data-testid="library-card" data-block={entry.block_name}>
      <div className="library-card-head">
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
            {entry.collection && <span className="pill">{entry.collection}</span>}
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
        <button className="btn ghost sm danger" onClick={() => onRemove(entry)} data-testid="remove-entry" aria-label="Remove">
          🗑 Remove
        </button>
      </div>
    </div>
  );
}
