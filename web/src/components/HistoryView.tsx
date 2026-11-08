import { useEffect, useRef, useState } from "react";
import * as api from "../api";

/** Create → History: your past songs (each a whole thread). Tap one to
 *  reopen it where you left off; play its latest version; rename; delete. */
export default function HistoryView({ active, currentId, busy, onOpen, onDeleted, onRenamed }: {
  active: boolean;
  currentId?: string;
  busy: boolean;
  onOpen: (id: string) => void;
  onDeleted: (id: string) => void;
  onRenamed: (id: string, title: string) => void;
}) {
  const [rows, setRows] = useState<api.SessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [playing, setPlaying] = useState<string | null>(null);
  const audio = useRef<HTMLAudioElement>(null);

  const load = () => api.listSessions().then((r) => { setRows(r); setError(null); })
    .catch((e) => setError(String(e)));
  useEffect(() => { if (active) void load(); else audio.current?.pause(); }, [active]);

  function play(r: api.SessionSummary) {
    const el = audio.current;
    const src = r.latest?.audio_url;
    if (!el || !src) return;
    if (playing === r.id && !el.paused) { el.pause(); return; }
    el.src = api.mediaUrl(src);
    el.play().then(() => setPlaying(r.id)).catch(() => setPlaying(null));
  }
  async function rename(r: api.SessionSummary) {
    const title = window.prompt("Rename this song", r.title)?.trim();
    if (!title || title === r.title) return;
    try { await api.renameSession(r.id, title); onRenamed(r.id, title); await load(); }
    catch (e) { setError(String(e)); }
  }
  async function remove(r: api.SessionSummary) {
    if (!window.confirm(`Delete “${r.title}” and its thread? Its versions leave Practice too; `
      + "anything you saved to the library stays.")) return;
    try { await api.deleteSession(r.id); onDeleted(r.id); await load(); }
    catch (e) { setError(String(e)); }
  }

  return (
    <div className="ws-thread" data-testid="history">
      <audio ref={audio} onPause={() => setPlaying(null)} onEnded={() => setPlaying(null)} />
      {error && <div className="error">{error}</div>}
      {rows && rows.length === 0 && (
        <div className="ws-empty"><div className="meta">No songs yet. Describe one and it shows up here.</div></div>
      )}
      {(rows ?? []).map((r) => {
        const on = playing === r.id;
        return (
          <div key={r.id} className={"ws-player ws-hist" + (r.id === currentId ? " current" : "")}
            data-testid="history-row" data-session={r.id}>
            <button type="button" className="ws-play" aria-label={on ? "Pause" : `Play v${r.latest?.n ?? ""}`}
              data-testid="history-play" disabled={!r.latest?.audio_url} onClick={() => play(r)}>
              {on
                ? <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
                : <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l12-7z" /></svg>}
            </button>
            <button type="button" className="ws-hist-main" data-testid="history-open" disabled={busy}
              onClick={() => onOpen(r.id)}>
              <span className="ws-hist-t">{r.title}</span>
              <span className="ws-sub">
                {[r.updated ? new Date(r.updated).toLocaleDateString(undefined, { month: "short", day: "numeric" }) : null,
                  r.style, `${r.version_count} version${r.version_count === 1 ? "" : "s"}`,
                  r.id === currentId ? "open" : null].filter(Boolean).join(" · ")}
              </span>
            </button>
            <div className="ws-hist-btns">
              <button type="button" className="ws-link" data-testid="history-rename" onClick={() => rename(r)}>Rename</button>
              <button type="button" className="ws-link danger" data-testid="history-delete" onClick={() => remove(r)}>Delete</button>
            </div>
          </div>
        );
      })}
    </div>
  );
}
