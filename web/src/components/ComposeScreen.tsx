import { useEffect, useMemo, useRef, useState } from "react";
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
import type { Block, SongRenderResult } from "../types";
import Waveform from "./Waveform";

interface TLItem {
  id: string;
  block_name: string;
  repeat: number;
}

type SortKey = "name" | "created" | "tempo" | "bars" | "notes" | "duration";
const SORTS: Record<SortKey, (a: Block, b: Block) => number> = {
  name: (a, b) => a.name.localeCompare(b.name),
  created: (a, b) => String(b.created ?? "").localeCompare(String(a.created ?? "")),
  tempo: (a, b) => (b.tempo ?? 0) - (a.tempo ?? 0),
  bars: (a, b) => (b.bars ?? 0) - (a.bars ?? 0),
  notes: (a, b) => (b.n_notes ?? 0) - (a.n_notes ?? 0),
  duration: (a, b) => (b.duration_seconds ?? 0) - (a.duration_seconds ?? 0),
};

export default function ComposeScreen() {
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [timeline, setTimeline] = useState<TLItem[]>([]);
  const [songTitle, setSongTitle] = useState("Untitled Song");
  const [songs, setSongs] = useState<string[]>([]);
  const [render, setRender] = useState<SongRenderResult | null>(null);
  const [busy, setBusy] = useState(false);
  const [renderProg, setRenderProg] = useState(0);
  const [renderMsg, setRenderMsg] = useState("");
  const [err, setErr] = useState<string | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>("name");

  const counter = useRef(0);

  async function refresh() {
    try {
      setBlocks(await api.getBlocks());
      setSongs((await api.listSongs()).songs);
    } catch (e) {
      setErr(String(e));
    }
  }
  useEffect(() => {
    refresh();
  }, []);

  const add = (name: string) =>
    setTimeline((t) => [...t, { id: `${name}#${counter.current++}`, block_name: name, repeat: 1 }]);
  const removeItem = (id: string) => setTimeline((t) => t.filter((e) => e.id !== id));
  const setRepeat = (id: string, r: number) =>
    setTimeline((t) => t.map((e) => (e.id === id ? { ...e, repeat: Math.max(1, r || 1) } : e)));

  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 6 } }));
  const onDragEnd = (e: DragEndEvent) => {
    const { active, over } = e;
    if (over && active.id !== over.id) {
      setTimeline((t) => {
        const oi = t.findIndex((x) => x.id === active.id);
        const ni = t.findIndex((x) => x.id === over.id);
        return oi < 0 || ni < 0 ? t : arrayMove(t, oi, ni);
      });
    }
  };

  async function onRender() {
    if (!timeline.length) return;
    setBusy(true); setErr(null); setRender(null); setMsg(null);
    setRenderProg(0); setRenderMsg("Starting…");
    try {
      const { job_id } = await api.renderSong(
        timeline.map(({ block_name, repeat }) => ({ block_name, repeat }))
      );
      const job = await api.pollSongRender(job_id, (p, m) => {
        setRenderProg(p);
        setRenderMsg(m);
      });
      if (job.status === "error") setErr(job.error || "Render failed");
      else if (job.result) setRender(job.result);
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onSave() {
    if (!songTitle.trim() || !timeline.length) return;
    try {
      await api.saveSong(songTitle.trim(), timeline.map(({ block_name, repeat }) => ({ block_name, repeat })));
      setMsg(`Saved "${songTitle.trim()}"`);
      refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  async function onLoad(title: string) {
    if (!title) return;
    try {
      const d = await api.loadSong(title);
      setSongTitle(d.title);
      counter.current = 0;
      setTimeline(
        d.timeline.map((e) => ({
          id: `${e.block_name}#${counter.current++}`,
          block_name: e.block_name,
          repeat: e.repeat || 1,
        }))
      );
      setRender(null);
    } catch (e) {
      setErr(String(e));
    }
  }

  async function onDelete(name: string) {
    if (!window.confirm(`Delete block "${name}"?`)) return;
    try {
      await api.deleteBlock(name);
      refresh();
    } catch (e) {
      setErr(String(e));
    }
  }

  const blockByName = useMemo(() => {
    const m: Record<string, Block> = {};
    blocks.forEach((b) => (m[b.name] = b));
    return m;
  }, [blocks]);

  const totalBars = useMemo(
    () => timeline.reduce((s, e) => s + (blockByName[e.block_name]?.bars || 0) * e.repeat, 0),
    [timeline, blockByName]
  );

  const shownBlocks = useMemo(() => {
    const q = query.trim().toLowerCase();
    const arr = q ? blocks.filter((b) => b.name.toLowerCase().includes(q)) : blocks.slice();
    return arr.sort(SORTS[sortBy]);
  }, [blocks, query, sortBy]);

  return (
    <>
      <div className="card">
        <h2>Song</h2>
        <div className="row">
          <input type="text" value={songTitle} onChange={(e) => setSongTitle(e.target.value)} placeholder="Song title" />
          <button className="btn secondary" style={{ flex: "0 0 auto", width: "auto", padding: "12px 16px" }} onClick={onSave}>
            Save
          </button>
        </div>
        {songs.length > 0 && (
          <label className="field" style={{ marginTop: 12 }}>
            <span>Load saved song</span>
            <select value="" onChange={(e) => onLoad(e.target.value)}>
              <option value="">— pick —</option>
              {songs.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
        )}
        {msg && <div className="ok" style={{ marginTop: 6 }}>{msg}</div>}
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>Timeline</h2>
          <span className="meta">{timeline.length} parts · {totalBars} bars</span>
        </div>
        {timeline.length === 0 ? (
          <div className="meta" style={{ marginTop: 10 }}>
            Tap <strong>+ Timeline</strong> on a block below to add it. Drag the ≡ handle to reorder.
          </div>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={timeline.map((t) => t.id)} strategy={verticalListSortingStrategy}>
              <div className="timeline">
                {timeline.map((entry) => (
                  <TimelineItem
                    key={entry.id}
                    entry={entry}
                    bars={blockByName[entry.block_name]?.bars ?? null}
                    onRepeat={setRepeat}
                    onRemove={removeItem}
                  />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        )}

        {(busy || render || err) && (
          <div style={{ marginTop: 14 }}>
            {busy && (
              <>
                <div className="progress"><div style={{ width: `${Math.round(renderProg * 100)}%` }} /></div>
                <div className="progress-msg">{renderMsg}</div>
              </>
            )}
            {err && <div className="error">{err}</div>}
            {render && (
              <>
                {render.urls.audio && <Waveform url={api.mediaUrl(render.urls.audio)} height={64} />}
                <div className="meta">
                  {render.info.duration_seconds.toFixed(1)}s · {render.info.n_instruments} instruments · {render.info.n_notes} notes
                </div>
                <div className="links">
                  {render.urls.midi && <a href={api.mediaUrl(render.urls.midi)} download>↓ MIDI</a>}
                  {render.urls.pdf && <a href={api.mediaUrl(render.urls.pdf)} download>↓ PDF</a>}
                  {render.urls.audio_hifi && <a href={api.mediaUrl(render.urls.audio_hifi)} download>↓ WAV (HQ)</a>}
                </div>
              </>
            )}
          </div>
        )}
      </div>

      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>Block Library</h2>
          <button className="btn ghost" style={{ width: "auto" }} onClick={refresh}>↻ Refresh</button>
        </div>
        {blocks.length === 0 ? (
          <div className="meta" style={{ marginTop: 10 }}>
            No blocks yet. Generate a song and tap <strong>Save as Block</strong> (or Split into section blocks).
          </div>
        ) : (
          <>
            <div className="lib-controls">
              <input
                className="lib-search" type="text" placeholder="Search blocks…"
                value={query} onChange={(e) => setQuery(e.target.value)}
              />
              <select value={sortBy} onChange={(e) => setSortBy(e.target.value as SortKey)}>
                <option value="name">Name A–Z</option>
                <option value="created">Recent</option>
                <option value="tempo">Tempo</option>
                <option value="bars">Bars</option>
                <option value="notes">Notes</option>
                <option value="duration">Duration</option>
              </select>
            </div>
            {shownBlocks.length === 0 ? (
              <div className="meta" style={{ marginTop: 10 }}>No blocks match “{query}”.</div>
            ) : (
              <div className="block-list">
                {shownBlocks.map((b) => (
                  <BlockCard key={b.name} block={b} onAdd={add} onDelete={onDelete} />
                ))}
              </div>
            )}
          </>
        )}
      </div>

      <div className="action-bar">
        <div className="inner">
          <button className="btn" disabled={busy || timeline.length === 0} onClick={onRender}>
            {busy ? "Rendering…" : "▶ Render Song"}
          </button>
        </div>
      </div>
    </>
  );
}

// One block preview plays at a time across the whole library.
let _currentAudio: HTMLAudioElement | null = null;

function BlockCard({
  block,
  onAdd,
  onDelete,
}: {
  block: Block;
  onAdd: (name: string) => void;
  onDelete: (name: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => () => { audioRef.current?.pause(); }, []);

  function togglePlay() {
    if (!block.has_preview) return;
    let a = audioRef.current;
    if (!a) {
      a = new Audio(api.mediaUrl(block.audio_url));
      a.addEventListener("play", () => setPlaying(true));
      a.addEventListener("pause", () => setPlaying(false));
      a.addEventListener("ended", () => setPlaying(false));
      audioRef.current = a;
    }
    if (a.paused) {
      if (_currentAudio && _currentAudio !== a) _currentAudio.pause();
      _currentAudio = a;
      void a.play();
    } else {
      a.pause();
    }
  }

  const ts = block.time_signature;
  return (
    <div className={"block-card" + (open ? " open" : "")}>
      <div className="bc-row">
        <button
          className="bc-play"
          onClick={togglePlay}
          disabled={!block.has_preview}
          aria-label={playing ? "Pause" : "Play"}
        >
          {playing ? "⏸" : "▶"}
        </button>
        <span className="bc-name" onClick={() => setOpen((o) => !o)}>{block.name}</span>
        <button className="bc-add" onClick={() => onAdd(block.name)} aria-label="Add to timeline">＋</button>
        <button className="bc-gear" onClick={() => setOpen((o) => !o)} aria-label="Details">⚙</button>
      </div>
      {open && (
        <div className="bc-detail">
          <Waveform url={api.mediaUrl(block.audio_url)} height={56} />
          <div className="bc-meta-grid">
            <span>{block.bars ?? "?"} bars</span>
            <span>{block.tempo ?? "?"} BPM</span>
            <span>{ts ? `${ts[0]}/${ts[1]}` : "4/4"}</span>
            <span>{block.instruments?.length ?? 0} instr.</span>
            <span>{block.n_notes ?? 0} notes</span>
            {block.duration_seconds != null && <span>{block.duration_seconds.toFixed(1)}s</span>}
          </div>
          <div className="links">
            <a href={api.blockFileUrl(block.name, "midi")} download>↓ MIDI</a>
            <a href={api.blockFileUrl(block.name, "wav")} download>↓ WAV</a>
            <a href={api.blockFileUrl(block.name, "pdf")} download>↓ PDF</a>
            <a href={api.blockFileUrl(block.name, "stems")} download>↓ Stems</a>
          </div>
          <div className="bc-actions">
            <button className="btn secondary sm" onClick={() => onAdd(block.name)}>+ Timeline</button>
            <button className="btn ghost sm danger" onClick={() => onDelete(block.name)} aria-label="Delete">🗑 Delete</button>
          </div>
        </div>
      )}
    </div>
  );
}

function TimelineItem({
  entry,
  bars,
  onRepeat,
  onRemove,
}: {
  entry: TLItem;
  bars: number | null;
  onRepeat: (id: string, r: number) => void;
  onRemove: (id: string) => void;
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({ id: entry.id });
  const style: React.CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.6 : 1,
  };
  return (
    <div ref={setNodeRef} style={style} className="tl-item">
      <span className="tl-drag" {...attributes} {...listeners}>≡</span>
      <span className="tl-name">{entry.block_name}</span>
      <span className="tl-meta">{bars ?? "?"}b</span>
      <label className="tl-rep">
        ×<input type="number" min={1} max={32} value={entry.repeat}
          onChange={(e) => onRepeat(entry.id, Number(e.target.value))} />
      </label>
      <button className="tl-x" onClick={() => onRemove(entry.id)} aria-label="Remove">✕</button>
    </div>
  );
}
