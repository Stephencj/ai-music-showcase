import { useEffect, useRef, useState } from "react";
import * as api from "../api";
import { INTERPRETER_NAME, type SMsg, type SVersion, type Session, prettyChange } from "../session";
import Waveform from "./Waveform";
import Composer from "./Composer";

const QUICK = ["Quieter", "Simpler bass", "Bigger chorus", "Slower"];

/** Create → Session: describe the song, hear a version, say what to change. */
export default function SessionView({
  session, busy, active, onSend, onSave, onOpenTimeline, onAdvanced, onBlocks, onNew,
}: {
  session: Session;
  busy: boolean;
  active: boolean;
  onSend: (text: string) => void;
  onSave: (v: SVersion) => Promise<string>;
  onOpenTimeline: () => void;
  onAdvanced: () => void;
  onBlocks: () => void;
  onNew: () => void;
}) {
  const [menu, setMenu] = useState(false);
  const { msgs, versions } = session;
  const byN = (n?: number) => versions.find((v) => v.n === n);
  const latest = versions[versions.length - 1];
  const lastWithVersion = [...msgs].reverse().find((m) => m.version != null)?.id;
  const hasDone = versions.some((v) => v.status === "done");

  // Keep the newest message in view.
  const endRef = useRef<HTMLDivElement>(null);
  const tick = msgs.length + ":" + versions.map((v) => v.status).join();
  useEffect(() => {
    if (active && msgs.length) endRef.current?.scrollIntoView({ block: "end", behavior: "smooth" });
  }, [tick, active, msgs.length]);

  const sub = versions.length
    ? `${versions.length} version${versions.length === 1 ? "" : "s"}`
      + (session.interpreter ? ` · interpreted by ${INTERPRETER_NAME[session.interpreter] ?? session.interpreter}` : "")
    : "Describe it, hear it, say what to change";

  return (
    <div className="ws-session" data-testid="session">
      <header className="ws-header">
        <div className="ws-title">
          <div className="ws-name" data-testid="session-title">{session.title || "New song"}</div>
          <div className="ws-sub">{sub}</div>
        </div>
        <button type="button" className="ws-pill" data-testid="open-timeline"
          disabled={!versions.length} onClick={onOpenTimeline}>Open timeline</button>
        <div className="ws-menu-wrap">
          <button type="button" className="ws-icon-btn" aria-label="More" aria-expanded={menu}
            data-testid="create-menu" onClick={() => setMenu((m) => !m)}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="2" /><circle cx="12" cy="12" r="2" /><circle cx="19" cy="12" r="2" /></svg>
          </button>
          {menu && (
            <>
              <div className="ws-menu-scrim" onClick={() => setMenu(false)} />
              <div className="ws-menu" role="menu">
                <button role="menuitem" data-testid="menu-advanced" onClick={() => { setMenu(false); onAdvanced(); }}>
                  Advanced form<span>Every setting, by hand</span></button>
                <button role="menuitem" data-testid="menu-blocks" onClick={() => { setMenu(false); onBlocks(); }}>
                  Blocks<span>Build a song from saved blocks</span></button>
                <button role="menuitem" data-testid="menu-new" disabled={busy} onClick={() => { setMenu(false); onNew(); }}>
                  New song<span>Start a fresh thread</span></button>
              </div>
            </>
          )}
        </div>
      </header>

      <div className="ws-thread">
        {msgs.length === 0 && (
          <div className="ws-empty">
            <div className="ws-empty-h">Describe your song</div>
            <div className="meta">
              Genre, mood, tempo, instruments, what it's for — in plain English. You'll hear a first
              version, then just say what to change.
            </div>
            <div className="meta ws-empty-eg">e.g. “Background bed for a product video. 70s funk feel but serious,
              horns and strings, sits quietly under narration.”</div>
            <div className="ws-empty-links">
              <button type="button" className="ws-pill" onClick={onAdvanced}>Advanced form</button>
              <button type="button" className="ws-pill" onClick={onBlocks}>Blocks</button>
            </div>
          </div>
        )}
        {msgs.map((m) => (
          <Message key={m.id} m={m} v={byN(m.version)} latestN={latest?.n}
            prev={m.version != null ? [...versions].reverse().find((x) => x.n < m.version! && x.status === "done") : undefined}
            showActions={m.id === lastWithVersion} onSave={onSave} />
        ))}
        <div ref={endRef} className="ws-end" />
      </div>

      <Composer testid="session-input" label="Describe or say what to change" busy={busy}
        placeholder={versions.length ? "Say what to change…" : "Describe your song…"}
        chips={QUICK} chipsEnabled={hasDone} onSend={onSend} />
    </div>
  );
}

function Message({ m, v, prev, latestN, showActions, onSave }: {
  m: SMsg; v?: SVersion; prev?: SVersion; latestN?: number; showActions: boolean;
  onSave: (v: SVersion) => Promise<string>;
}) {
  if (m.role === "user") return <div className="ws-bubble" data-testid="msg-user">{m.text}</div>;
  if (m.kind === "pending") {
    return <div className="ws-reply"><div className="ws-reply-h ws-pending" data-testid="msg-pending">{m.text || "Reading…"}</div></div>;
  }
  if (m.kind === "error") {
    return <div className="ws-reply"><div className="error" data-testid="msg-error">{m.text}</div></div>;
  }
  const changes = m.changes ?? [];
  return (
    <div className="ws-reply" data-testid={`msg-${m.kind}`}>
      {m.kind === "describe" ? (
        <>
          <div className="ws-reply-h">Here's what I understood</div>
          <div className="ws-chips" data-testid="plan-chips">
            {(m.chips ?? []).map((c, i) => <span key={i} className="ws-chip">{c.replace(/_/g, " ")}</span>)}
          </div>
        </>
      ) : (
        <>
          <div className="ws-reply-h" data-testid="changed-heading">
            {changes.length
              ? `Changed ${changes.length} thing${changes.length === 1 ? "" : "s"}`
              : m.kind === "section" ? "Regenerating with your section options" : "Nothing changed"}
          </div>
          {changes.length > 0 && (
            <ul className="ws-changes" data-testid="change-list">
              {changes.map((c, i) => <li key={i}>{prettyChange(c)}</li>)}
            </ul>
          )}
        </>
      )}
      {(m.notes ?? []).map((n, i) => <div key={i} className="dr-note">{n}</div>)}
      {v && <VersionCard v={v} current={v.n === latestN} />}
      {showActions && v?.status === "done" && <VersionActions v={v} prev={prev} onSave={onSave} />}
    </div>
  );
}

export function VersionCard({ v, current }: { v: SVersion; current: boolean }) {
  return (
    <div className={"ws-player" + (current ? " current" : "")} data-testid={`version-${v.n}`}
      data-status={v.status}>
      {v.status === "running" && (
        <div className="ws-player-prog">
          <div className="progress"><div style={{ width: `${Math.round(v.progress * 100)}%` }} /></div>
          <div className="ws-player-msg">{v.message || "Composing…"}</div>
        </div>
      )}
      {v.status === "error" && <div className="error ws-player-prog">{v.error}</div>}
      {v.status === "done" && v.result?.urls.audio && (
        <div className="ws-player-wave"><Waveform url={api.mediaUrl(v.result.urls.audio)} height={32} /></div>
      )}
      <span className="ws-vlabel">v{v.n}</span>
    </div>
  );
}

function VersionActions({ v, prev, onSave }: { v: SVersion; prev?: SVersion; onSave: (v: SVersion) => Promise<string> }) {
  const [compare, setCompare] = useState(false);
  const [saving, setSaving] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  async function save() {
    setSaving(true); setMsg(null);
    try { setMsg(`Saved “${await onSave(v)}” to your library`); }
    catch (e) { setMsg(`Error: ${e}`); }
    finally { setSaving(false); }
  }
  return (
    <>
      <div className="ws-actions">
        {prev && (
          <button type="button" className={"ws-act" + (compare ? " on" : "")} data-testid="compare"
            aria-pressed={compare} onClick={() => setCompare((c) => !c)}>Compare v{prev.n} / v{v.n}</button>
        )}
        <button type="button" className="ws-act" data-testid="save-library" disabled={saving || !!v.savedAs}
          onClick={save}>{v.savedAs ? "Saved to library" : saving ? "Saving…" : "Save to library"}</button>
      </div>
      {msg && <div className={msg.startsWith("Error") ? "error" : "ok"} data-testid="save-msg">{msg}</div>}
      {compare && prev && <CompareAB a={prev} b={v} />}
    </>
  );
}

/** A/B two versions: one transport, switch between them at the same spot. */
function CompareAB({ a, b }: { a: SVersion; b: SVersion }) {
  const refs = { a: useRef<HTMLAudioElement>(null), b: useRef<HTMLAudioElement>(null) };
  const [which, setWhich] = useState<"a" | "b">("b");
  const [playing, setPlaying] = useState(false);
  const [pos, setPos] = useState(0);
  const cur = () => refs[which].current;

  useEffect(() => () => { refs.a.current?.pause(); refs.b.current?.pause(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  function pick(w: "a" | "b") {
    if (w === which) return;
    const from = cur(), to = refs[w].current;
    if (from && to) {
      to.currentTime = Math.min(from.currentTime, isFinite(to.duration) ? to.duration : from.currentTime);
      if (!from.paused) { from.pause(); to.play().catch(() => {}); }
    }
    setWhich(w);
  }
  function toggle() {
    const el = cur();
    if (!el) return;
    if (el.paused) el.play().catch(() => {}); else el.pause();
  }
  const url = (v: SVersion) => (v.result?.urls.audio ? api.mediaUrl(v.result.urls.audio) : undefined);
  const onTime = (w: "a" | "b") => (e: React.SyntheticEvent<HTMLAudioElement>) => {
    if (w !== which) return;
    const el = e.currentTarget;
    setPos(el.duration ? el.currentTime / el.duration : 0);
  };
  return (
    <div className="ws-compare" data-testid="compare-panel">
      {(["a", "b"] as const).map((w) => (
        <audio key={w} ref={refs[w]} src={url(w === "a" ? a : b)} preload="auto"
          onTimeUpdate={onTime(w)} onPlay={() => w === which && setPlaying(true)}
          onPause={() => w === which && setPlaying(false)} onEnded={() => setPlaying(false)} />
      ))}
      <button type="button" className="ws-play" aria-label={playing ? "Pause" : "Play"} onClick={toggle}>
        {playing
          ? <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
          : <svg width="16" height="16" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l12-7z" /></svg>}
      </button>
      <div className="ws-ab" role="group" aria-label="Which version">
        <button type="button" className={which === "a" ? "on" : ""} aria-pressed={which === "a"}
          data-testid="compare-a" onClick={() => pick("a")}>v{a.n}</button>
        <button type="button" className={which === "b" ? "on" : ""} aria-pressed={which === "b"}
          data-testid="compare-b" onClick={() => pick("b")}>v{b.n}</button>
      </div>
      <div className="ws-track"><div style={{ width: `${pos * 100}%` }} /></div>
    </div>
  );
}
