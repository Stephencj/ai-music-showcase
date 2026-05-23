import { useEffect, useMemo, useRef, useState } from "react";
import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCenter,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
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
import Sparkline from "./Sparkline";

interface TLItem {
  id: string;
  block_name: string;
  repeat: number;
}

type SortKey = "name" | "created" | "tempo" | "bars" | "notes" | "duration";
const SORTS: Record<SortKey, (a: Block, b: Block) => number> = {
  // all ascending; sortDir flips
  name: (a, b) => a.name.localeCompare(b.name),
  created: (a, b) => String(a.created ?? "").localeCompare(String(b.created ?? "")),
  tempo: (a, b) => (a.tempo ?? 0) - (b.tempo ?? 0),
  bars: (a, b) => (a.bars ?? 0) - (b.bars ?? 0),
  notes: (a, b) => (a.n_notes ?? 0) - (b.n_notes ?? 0),
  duration: (a, b) => (a.duration_seconds ?? 0) - (b.duration_seconds ?? 0),
};
const DEFAULT_DIR: Record<SortKey, "asc" | "desc"> = {
  name: "asc", created: "desc", tempo: "desc", bars: "desc", notes: "desc", duration: "desc",
};
const ROLE_RE = /\b(intro|verse|chorus|bridge|outro)\b/i;
const roleOf = (n: string): string | null => {
  const m = n.match(ROLE_RE);
  return m ? m[1].toLowerCase() : null;
};
const meterOf = (b: Block): string | null =>
  b.time_signature ? `${b.time_signature[0]}/${b.time_signature[1]}` : null;

const ls = {
  get<T>(k: string, fallback: T): T {
    try { const v = localStorage.getItem(k); return v ? (JSON.parse(v) as T) : fallback; }
    catch { return fallback; }
  },
  set(k: string, v: unknown) {
    try { localStorage.setItem(k, JSON.stringify(v)); } catch { /* ignore */ }
  },
};

// One block preview plays at a time across the whole library.
let _currentAudio: HTMLAudioElement | null = null;

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

  // library navigation
  const [query, setQuery] = useState("");
  const [sortBy, setSortBy] = useState<SortKey>(() => ls.get<SortKey>("compose.sortBy", "name"));
  const [sortDir, setSortDir] = useState<"asc" | "desc">(() => ls.get("compose.sortDir", "asc"));
  const [favs, setFavs] = useState<Set<string>>(() => new Set(ls.get<string[]>("compose.favs", [])));
  const [favOnly, setFavOnly] = useState(false);
  const [fMeters, setFMeters] = useState<Set<string>>(new Set());
  const [fRoles, setFRoles] = useState<Set<string>>(new Set());
  const [fTags, setFTags] = useState<Set<string>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const counter = useRef(0);

  useEffect(() => { ls.set("compose.sortBy", sortBy); }, [sortBy]);
  useEffect(() => { ls.set("compose.sortDir", sortDir); }, [sortDir]);
  useEffect(() => { ls.set("compose.favs", [...favs]); }, [favs]);

  async function refresh() {
    try {
      setBlocks(await api.getBlocks());
      setSongs((await api.listSongs()).songs);
    } catch (e) { setErr(String(e)); }
  }
  useEffect(() => { refresh(); }, []);

  // timeline ops
  const add = (name: string) =>
    setTimeline((t) => [...t, { id: `${name}#${counter.current++}`, block_name: name, repeat: 1 }]);
  const addMany = (names: string[]) =>
    setTimeline((t) => [...t, ...names.map((n) => ({ id: `${n}#${counter.current++}`, block_name: n, repeat: 1 }))]);
  const removeItem = (id: string) => setTimeline((t) => t.filter((e) => e.id !== id));
  const setRepeat = (id: string, r: number) =>
    setTimeline((t) => t.map((e) => (e.id === id ? { ...e, repeat: Math.max(1, r || 1) } : e)));

  // drag-and-drop (library → timeline add, and timeline reorder)
  const sensors = useSensors(useSensor(PointerSensor, { activationConstraint: { distance: 8 } }));
  const [dragName, setDragName] = useState<string | null>(null);
  const tlDrop = useDroppable({ id: "tl-zone" });

  const onDragStart = (e: DragStartEvent) => {
    const id = String(e.active.id);
    setDragName(id.startsWith("lib:") ? id.slice(4) : null);
  };
  const onDragEnd = (e: DragEndEvent) => {
    setDragName(null);
    const { active, over } = e;
    if (!over) return;
    const aid = String(active.id);
    const oid = String(over.id);
    if (aid.startsWith("lib:")) {
      const name = aid.slice(4);
      setTimeline((t) => {
        const item = { id: `${name}#${counter.current++}`, block_name: name, repeat: 1 };
        const idx = t.findIndex((x) => x.id === oid);
        return idx < 0 ? [...t, item] : [...t.slice(0, idx), item, ...t.slice(idx)];
      });
      return;
    }
    if (aid !== oid) {
      setTimeline((t) => {
        const oi = t.findIndex((x) => x.id === aid);
        const ni = t.findIndex((x) => x.id === oid);
        return oi < 0 || ni < 0 ? t : arrayMove(t, oi, ni);
      });
    }
  };

  // render / save / load
  async function onRender() {
    if (!timeline.length) return;
    setBusy(true); setErr(null); setRender(null); setMsg(null);
    setRenderProg(0); setRenderMsg("Starting…");
    try {
      const { job_id } = await api.renderSong(timeline.map(({ block_name, repeat }) => ({ block_name, repeat })));
      const job = await api.pollSongRender(job_id, (p, m) => { setRenderProg(p); setRenderMsg(m); });
      if (job.status === "error") setErr(job.error || "Render failed");
      else if (job.result) setRender(job.result);
    } catch (e) { setErr(String(e)); }
    finally { setBusy(false); }
  }
  async function onSave() {
    if (!songTitle.trim() || !timeline.length) return;
    try {
      await api.saveSong(songTitle.trim(), timeline.map(({ block_name, repeat }) => ({ block_name, repeat })));
      setMsg(`Saved "${songTitle.trim()}"`); refresh();
    } catch (e) { setErr(String(e)); }
  }
  async function onLoad(title: string) {
    if (!title) return;
    try {
      const d = await api.loadSong(title);
      setSongTitle(d.title);
      counter.current = 0;
      setTimeline(d.timeline.map((e) => ({ id: `${e.block_name}#${counter.current++}`, block_name: e.block_name, repeat: e.repeat || 1 })));
      setRender(null);
    } catch (e) { setErr(String(e)); }
  }

  // block ops
  async function onDelete(name: string) {
    if (!window.confirm(`Delete block "${name}"?`)) return;
    try { await api.deleteBlock(name); refresh(); } catch (e) { setErr(String(e)); }
  }
  async function onRename(oldName: string, newName: string) {
    if (!newName.trim() || newName.trim() === oldName) return;
    try {
      const r = await api.renameBlock(oldName, newName.trim());
      setFavs((s) => { if (!s.has(oldName)) return s; const n = new Set(s); n.delete(oldName); n.add(r.name); return n; });
      refresh();
    } catch (e) { setErr(String(e)); }
  }
  async function onTags(name: string, tags: string[]) {
    try { await api.setTags(name, tags); refresh(); } catch (e) { setErr(String(e)); }
  }
  async function bulkDelete() {
    if (!selected.size || !window.confirm(`Delete ${selected.size} block(s)?`)) return;
    for (const n of selected) { try { await api.deleteBlock(n); } catch { /* ignore */ } }
    setSelected(new Set()); setSelectMode(false); refresh();
  }
  const toggleFav = (name: string) =>
    setFavs((s) => { const n = new Set(s); n.has(name) ? n.delete(name) : n.add(name); return n; });
  const toggleSel = (name: string) =>
    setSelected((s) => { const n = new Set(s); n.has(name) ? n.delete(name) : n.add(name); return n; });

  // derived
  const blockByName = useMemo(() => {
    const m: Record<string, Block> = {};
    blocks.forEach((b) => (m[b.name] = b));
    return m;
  }, [blocks]);
  const totalBars = useMemo(
    () => timeline.reduce((s, e) => s + (blockByName[e.block_name]?.bars || 0) * e.repeat, 0),
    [timeline, blockByName]
  );
  const allTags = useMemo(() => [...new Set(blocks.flatMap((b) => b.tags ?? []))].sort(), [blocks]);
  const allMeters = useMemo(
    () => [...new Set(blocks.map(meterOf).filter((m): m is string => !!m))].sort(),
    [blocks]
  );
  const allRoles = useMemo(
    () => ["intro", "verse", "chorus", "bridge", "outro"].filter((r) => blocks.some((b) => roleOf(b.name) === r)),
    [blocks]
  );

  const shownBlocks = useMemo(() => {
    const q = query.trim().toLowerCase();
    let arr = blocks.slice();
    if (q) arr = arr.filter((b) => b.name.toLowerCase().includes(q));
    if (favOnly) arr = arr.filter((b) => favs.has(b.name));
    if (fMeters.size) arr = arr.filter((b) => { const m = meterOf(b); return !!m && fMeters.has(m); });
    if (fRoles.size) arr = arr.filter((b) => { const r = roleOf(b.name); return !!r && fRoles.has(r); });
    if (fTags.size) arr = arr.filter((b) => (b.tags ?? []).some((t) => fTags.has(t)));
    const cmp = SORTS[sortBy];
    arr.sort((a, b) => (sortDir === "asc" ? cmp(a, b) : -cmp(a, b)));
    return arr;
  }, [blocks, query, favOnly, favs, fMeters, fRoles, fTags, sortBy, sortDir]);

  function changeSort(k: SortKey) { setSortBy(k); setSortDir(DEFAULT_DIR[k]); }
  const chipToggle = (set: Set<string>, v: string, setter: (s: Set<string>) => void) => {
    const n = new Set(set); n.has(v) ? n.delete(v) : n.add(v); setter(n);
  };

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragStart={onDragStart} onDragEnd={onDragEnd}>
      {/* Song */}
      <div className="card">
        <h2>Song</h2>
        <div className="row">
          <input type="text" value={songTitle} onChange={(e) => setSongTitle(e.target.value)} placeholder="Song title" />
          <button className="btn secondary" style={{ flex: "0 0 auto", width: "auto", padding: "12px 16px" }} onClick={onSave}>Save</button>
        </div>
        {songs.length > 0 && (
          <label className="field" style={{ marginTop: 12 }}>
            <span>Load saved song</span>
            <select value="" onChange={(e) => onLoad(e.target.value)}>
              <option value="">— pick —</option>
              {songs.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </label>
        )}
        {msg && <div className="ok" style={{ marginTop: 6 }}>{msg}</div>}
      </div>

      {/* Timeline */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>Timeline</h2>
          <span className="meta">{timeline.length} parts · {totalBars} bars</span>
        </div>
        <div ref={tlDrop.setNodeRef} className={"tl-zone" + (tlDrop.isOver ? " over" : "")}>
          {timeline.length === 0 ? (
            <div className="meta" style={{ marginTop: 10 }}>
              Tap <strong>＋</strong> on a block (or drag it here) to add it. Drag the ≡ handle to reorder.
            </div>
          ) : (
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
          )}
        </div>

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

      {/* Library */}
      <div className="card">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 style={{ margin: 0 }}>Block Library</h2>
          <div style={{ display: "flex", gap: 8 }}>
            <button className="btn ghost" style={{ width: "auto" }}
              onClick={() => { setSelectMode((s) => !s); setSelected(new Set()); }}>
              {selectMode ? "Done" : "Select"}
            </button>
            <button className="btn ghost" style={{ width: "auto" }} onClick={refresh}>↻</button>
          </div>
        </div>

        {blocks.length === 0 ? (
          <div className="meta" style={{ marginTop: 10 }}>
            No blocks yet. Generate a song and tap <strong>Save as Block</strong> (or Split into section blocks).
          </div>
        ) : (
          <>
            <div className="lib-controls">
              <input className="lib-search" type="text" placeholder="Search blocks…" value={query} onChange={(e) => setQuery(e.target.value)} />
              <select value={sortBy} onChange={(e) => changeSort(e.target.value as SortKey)}>
                <option value="name">Name</option>
                <option value="created">Recent</option>
                <option value="tempo">Tempo</option>
                <option value="bars">Bars</option>
                <option value="notes">Notes</option>
                <option value="duration">Duration</option>
              </select>
              <button className="btn ghost" style={{ width: "auto" }} title="Sort direction"
                onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}>
                {sortDir === "asc" ? "▲" : "▼"}
              </button>
            </div>

            {(favs.size > 0 || allMeters.length > 1 || allRoles.length > 0 || allTags.length > 0) && (
              <div className="filter-row">
                {favs.size > 0 && (
                  <button className={"chip" + (favOnly ? " on" : "")} onClick={() => setFavOnly((v) => !v)}>★ Favorites</button>
                )}
                {allMeters.length > 1 && allMeters.map((m) => (
                  <button key={m} className={"chip" + (fMeters.has(m) ? " on" : "")} onClick={() => chipToggle(fMeters, m, setFMeters)}>{m}</button>
                ))}
                {allRoles.map((r) => (
                  <button key={r} className={"chip" + (fRoles.has(r) ? " on" : "")} onClick={() => chipToggle(fRoles, r, setFRoles)}>{r}</button>
                ))}
                {allTags.map((t) => (
                  <button key={t} className={"chip" + (fTags.has(t) ? " on" : "")} onClick={() => chipToggle(fTags, t, setFTags)}>#{t}</button>
                ))}
              </div>
            )}

            {selectMode && (
              <div className="bulk-bar">
                <span>{selected.size} selected</span>
                <button className="btn sm" disabled={!selected.size} onClick={() => { addMany([...selected]); }}>+ Timeline</button>
                <button className="btn sm danger" disabled={!selected.size} onClick={bulkDelete}>Delete</button>
              </div>
            )}
            {!selectMode && query && shownBlocks.length > 1 && (
              <button className="btn ghost sm" style={{ marginTop: 6 }} onClick={() => addMany(shownBlocks.map((b) => b.name))}>
                + Add all {shownBlocks.length} matching
              </button>
            )}

            {shownBlocks.length === 0 ? (
              <div className="meta" style={{ marginTop: 10 }}>No blocks match your filters.</div>
            ) : (
              <div className="block-list">
                {shownBlocks.map((b) => (
                  <BlockCard
                    key={b.name}
                    block={b}
                    selectMode={selectMode}
                    selected={selected.has(b.name)}
                    onToggleSel={toggleSel}
                    isFav={favs.has(b.name)}
                    onToggleFav={toggleFav}
                    onAdd={add}
                    onDelete={onDelete}
                    onRename={onRename}
                    onTags={onTags}
                  />
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

      <DragOverlay>{dragName ? <div className="drag-pill">{dragName}</div> : null}</DragOverlay>
    </DndContext>
  );
}

function BlockCard({
  block, selectMode, selected, onToggleSel, isFav, onToggleFav,
  onAdd, onDelete, onRename, onTags,
}: {
  block: Block;
  selectMode: boolean;
  selected: boolean;
  onToggleSel: (name: string) => void;
  isFav: boolean;
  onToggleFav: (name: string) => void;
  onAdd: (name: string) => void;
  onDelete: (name: string) => void;
  onRename: (oldName: string, newName: string) => void;
  onTags: (name: string, tags: string[]) => void;
}) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [rename, setRename] = useState(block.name);
  const [newTag, setNewTag] = useState("");
  const audioRef = useRef<HTMLAudioElement | null>(null);

  const drag = useDraggable({ id: `lib:${block.name}`, disabled: selectMode });

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
    } else { a.pause(); }
  }

  const ts = block.time_signature;
  const tags = block.tags ?? [];

  return (
    <div ref={drag.setNodeRef} className={"block-card" + (open ? " open" : "") + (drag.isDragging ? " dragging" : "")}>
      <div className="bc-row">
        {selectMode ? (
          <label className="bc-check">
            <input type="checkbox" checked={selected} onChange={() => onToggleSel(block.name)} />
          </label>
        ) : (
          <button className="bc-play" onClick={togglePlay} disabled={!block.has_preview} aria-label={playing ? "Pause" : "Play"}>
            {playing ? "⏸" : "▶"}
          </button>
        )}
        <span
          className="bc-name"
          {...(selectMode ? {} : drag.listeners)}
          {...(selectMode ? {} : drag.attributes)}
          onClick={() => (selectMode ? onToggleSel(block.name) : setOpen((o) => !o))}
        >
          {block.name}
        </span>
        {!selectMode && (
          <>
            <button className={"bc-star" + (isFav ? " on" : "")} onClick={() => onToggleFav(block.name)} aria-label="Favorite">
              {isFav ? "★" : "☆"}
            </button>
            <button className="bc-add" onClick={() => onAdd(block.name)} aria-label="Add to timeline">＋</button>
            <button className="bc-gear" onClick={() => setOpen((o) => !o)} aria-label="Details">⚙</button>
          </>
        )}
      </div>

      {block.has_preview && <Sparkline name={block.name} />}

      {open && !selectMode && (
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

          <div className="tag-edit">
            {tags.map((t) => (
              <span key={t} className="tag-chip">
                #{t}<button onClick={() => onTags(block.name, tags.filter((x) => x !== t))} aria-label="Remove tag">×</button>
              </span>
            ))}
            <input
              className="tag-input" type="text" placeholder="+ tag" value={newTag}
              onChange={(e) => setNewTag(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && newTag.trim()) {
                  onTags(block.name, [...tags, newTag.trim()]);
                  setNewTag("");
                }
              }}
            />
          </div>

          <div className="links">
            <a href={api.blockFileUrl(block.name, "midi")} download>↓ MIDI</a>
            <a href={api.blockFileUrl(block.name, "wav")} download>↓ WAV</a>
            <a href={api.blockFileUrl(block.name, "pdf")} download>↓ PDF</a>
            <a href={api.blockFileUrl(block.name, "stems")} download>↓ Stems</a>
          </div>

          <div className="row">
            <input type="text" value={rename} onChange={(e) => setRename(e.target.value)} placeholder="Rename block" />
            <button className="btn secondary" style={{ flex: "0 0 auto", width: "auto", padding: "12px 16px" }}
              onClick={() => onRename(block.name, rename)} disabled={!rename.trim() || rename.trim() === block.name}>
              Rename
            </button>
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
  entry, bars, onRepeat, onRemove,
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
