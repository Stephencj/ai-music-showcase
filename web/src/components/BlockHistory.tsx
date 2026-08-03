import { useEffect, useState } from "react";
import * as api from "../api";
import type { HistoryItem } from "../api";

/**
 * Unified block timeline — every generation/edit (version) AND every sung
 * take, merged newest-first. Versions can be made active (restore, non-
 * destructive); vocal takes can be played, downloaded, or deleted. Lazy-loaded
 * on expand, and re-fetched when `reloadKey` changes (the Compose card bumps it
 * after a new take is sung). `onRestored` lets the parent refresh its audio.
 */
export default function BlockHistory({ name, reloadKey = 0, onRestored }: {
  name: string;
  reloadKey?: number;
  onRestored?: () => void;
}) {
  const [data, setData] = useState<{ history: HistoryItem[]; active: string | null; preview_take: string | null } | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = async () => {
    setError(null);
    try {
      setData(await api.getHistory(name));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  // Refresh an already-open, already-loaded timeline when a new take lands.
  useEffect(() => {
    if (open && data) void load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [reloadKey]);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && !data) await load();
  };

  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  };

  const snapshot = () => run(() => api.snapshotVersion(name));
  const restore = (id: string) => {
    if (!window.confirm("Make this the block's active version? Your current state is saved as a version first.")) return;
    run(async () => { await api.restoreVersion(name, id); onRestored?.(); });
  };
  const deleteVersion = (id: string) => run(() => api.deleteVersion(name, id));
  const deleteTake = (id: string) => run(() => api.deleteVocalTake(name, id));
  // Point the block's play button at a take's mix (or clear → instrumental).
  const setPreview = (id: string | null) =>
    run(async () => { await api.setPreviewTake(name, id); onRestored?.(); });

  const count = data?.history.length ?? 0;

  return (
    <div className="versions">
      <button className="btn ghost sm" onClick={toggle} data-testid="history-toggle">
        🕑 History{data ? ` (${count})` : ""} {open ? "▲" : "▼"}
      </button>

      {open && (
        <div className="versions-body" data-testid="history-body">
          <div className="te-note">
            Every generation, edit and sung take for this block. Make a version active to
            switch what the block plays — switching is non-destructive.
          </div>
          <button className="btn secondary sm" onClick={snapshot} disabled={busy} data-testid="snapshot-version">
            ＋ Save current as version
          </button>
          {error && <div className="error" role="alert">{error}</div>}
          {data && count === 0 && <div className="te-note">Nothing yet.</div>}

          {data?.history.map((item) =>
            item.kind === "version" ? (
              <div key={`v-${item.id}`}
                className={"version-row" + (item.active ? " active" : "")}
                data-testid="version-row" data-vid={item.id} data-active={item.active ? "1" : "0"}>
                <div className="version-info">
                  <span className="version-label">
                    {item.active && <span title="Active version">✓ </span>}
                    <span className="hist-badge">version</span> {item.label}
                  </span>
                  <span className="te-note">
                    {" · "}{item.source}{" · "}{new Date(item.created).toLocaleString()}
                    {item.summary?.n_notes != null ? ` · ${item.summary.n_notes} notes` : ""}
                  </span>
                </div>
                {item.has_preview && (
                  <audio controls preload="none" src={api.versionPreviewUrl(name, item.id)} />
                )}
                <div className="version-actions">
                  <button className="btn secondary sm" disabled={busy || item.active}
                    onClick={() => restore(item.id)} data-testid="restore-version">
                    {item.active ? "In use" : "Use"}
                  </button>
                  <button className="btn ghost sm danger" disabled={busy}
                    onClick={() => deleteVersion(item.id)} data-testid="delete-version" aria-label="Delete version">
                    🗑
                  </button>
                </div>
              </div>
            ) : (
              <div key={`t-${item.id}`}
                className={"version-row vocal-row" + (data?.preview_take === item.id ? " active" : "")}
                data-testid="vocal-row" data-vid={item.id}
                data-plays={data?.preview_take === item.id ? "1" : "0"}>
                <div className="version-info">
                  <span className="version-label">
                    {data?.preview_take === item.id && <span title="Plays on the block">🔊 </span>}
                    <span className="hist-badge vocal">take</span> {item.label}
                    {item.harmonies ? " · +harm" : ""}
                  </span>
                  <span className="te-note">{" · "}{new Date(item.created).toLocaleString()}</span>
                </div>
                {item.files.mix && (
                  <audio controls preload="none" src={api.vocalTakeUrl(name, item.id, "mix")} />
                )}
                <div className="version-actions">
                  {item.files.mix && (
                    data?.preview_take === item.id ? (
                      <button className="btn secondary sm" disabled={busy}
                        onClick={() => setPreview(null)} data-testid="clear-preview">
                        ✓ On block
                      </button>
                    ) : (
                      <button className="btn secondary sm" disabled={busy}
                        onClick={() => setPreview(item.id)} data-testid="use-for-play">
                        🔊 Use for play
                      </button>
                    )
                  )}
                  {item.files.vocal && (
                    <a className="btn ghost sm" href={api.vocalTakeUrl(name, item.id, "vocal")} download>↓ Stem</a>
                  )}
                  {item.files.score && (
                    <a className="btn ghost sm" href={api.vocalTakeUrl(name, item.id, "score")} download>↓ Score</a>
                  )}
                  <button className="btn ghost sm danger" disabled={busy}
                    onClick={() => deleteTake(item.id)} data-testid="delete-take" aria-label="Delete take">
                    🗑
                  </button>
                </div>
              </div>
            )
          )}
        </div>
      )}
    </div>
  );
}
