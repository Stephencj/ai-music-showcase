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
import type { Block, BlockSpec, SectionVoice, SongRenderResult } from "../types";
import Waveform from "./Waveform";
import Sparkline from "./Sparkline";

interface TLItem {
  id: string;
  block_name: string;
  repeat: number;
}

type SortKey = "name" | "created" | "tempo" | "bars" | "notes" | "duration" | "vocals";
const SORTS: Record<SortKey, (a: Block, b: Block) => number> = {
  // all ascending; sortDir flips
  name: (a, b) => a.name.localeCompare(b.name),
  created: (a, b) => String(a.created ?? "").localeCompare(String(b.created ?? "")),
  tempo: (a, b) => (a.tempo ?? 0) - (b.tempo ?? 0),
  bars: (a, b) => (a.bars ?? 0) - (b.bars ?? 0),
  notes: (a, b) => (a.n_notes ?? 0) - (b.n_notes ?? 0),
  duration: (a, b) => (a.duration_seconds ?? 0) - (b.duration_seconds ?? 0),
  vocals: (a, b) => (a.vocal_takes ?? 0) - (b.vocal_takes ?? 0),
};
const DEFAULT_DIR: Record<SortKey, "asc" | "desc"> = {
  name: "asc", created: "desc", tempo: "desc", bars: "desc", notes: "desc", duration: "desc", vocals: "desc",
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

export default function ComposeScreen({
  onEditInGenerate,
}: {
  onEditInGenerate: (spec: BlockSpec) => void;
}) {
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
  const [vocalsOnly, setVocalsOnly] = useState(false);
  const [fMeters, setFMeters] = useState<Set<string>>(new Set());
  const [fRoles, setFRoles] = useState<Set<string>>(new Set());
  const [fTags, setFTags] = useState<Set<string>>(new Set());
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [voices, setVoices] = useState<string[]>([]);
  const [studioVoices, setStudioVoices] = useState<string[]>([]);
  const [engines, setEngines] = useState<string[]>(["rough"]);

  const counter = useRef(0);

  useEffect(() => {
    api.getVoices().then((v) => {
      setVoices(v.voices); setEngines(v.engines); setStudioVoices(v.studio_voices ?? []);
    }).catch(() => {});
  }, []);

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
    setTimeline((t) => t.map((e) => (e.id === id ? { ...e, repeat: Math.max(0.25, Math.min(32, Math.round(r * 100) / 100)) } : e)));

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
  async function onEditBlock(name: string, body: { mute: string[]; regenerate: string[]; save_as?: string | null }) {
    const r = await api.editBlock(name, body);
    await refresh();
    setMsg(`Updated "${r.name}"`);
    return r.name;
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
    () => timeline.reduce((s, e) => s + Math.round((blockByName[e.block_name]?.bars || 0) * e.repeat), 0),
    [timeline, blockByName]
  );
  const allTags = useMemo(() => [...new Set(blocks.flatMap((b) => b.tags ?? []))].sort(), [blocks]);
  const anyVocals = useMemo(() => blocks.some((b) => (b.vocal_takes ?? 0) > 0), [blocks]);
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
    if (vocalsOnly) arr = arr.filter((b) => (b.vocal_takes ?? 0) > 0);
    if (fMeters.size) arr = arr.filter((b) => { const m = meterOf(b); return !!m && fMeters.has(m); });
    if (fRoles.size) arr = arr.filter((b) => { const r = roleOf(b.name); return !!r && fRoles.has(r); });
    if (fTags.size) arr = arr.filter((b) => (b.tags ?? []).some((t) => fTags.has(t)));
    const cmp = SORTS[sortBy];
    arr.sort((a, b) => (sortDir === "asc" ? cmp(a, b) : -cmp(a, b)));
    return arr;
  }, [blocks, query, favOnly, vocalsOnly, favs, fMeters, fRoles, fTags, sortBy, sortDir]);

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
                <option value="vocals">Vocals</option>
              </select>
              <button className="btn ghost" style={{ width: "auto" }} title="Sort direction"
                onClick={() => setSortDir((d) => (d === "asc" ? "desc" : "asc"))}>
                {sortDir === "asc" ? "▲" : "▼"}
              </button>
            </div>

            {(favs.size > 0 || anyVocals || allMeters.length > 1 || allRoles.length > 0 || allTags.length > 0) && (
              <div className="filter-row">
                {favs.size > 0 && (
                  <button className={"chip" + (favOnly ? " on" : "")} onClick={() => setFavOnly((v) => !v)}>★ Favorites</button>
                )}
                {anyVocals && (
                  <button className={"chip" + (vocalsOnly ? " on" : "")} onClick={() => setVocalsOnly((v) => !v)} title="Only blocks with generated vocals">🎤 Has vocals</button>
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
                    onEdit={onEditBlock}
                    onEditInGenerate={onEditInGenerate}
                    onChanged={refresh}
                    voices={voices}
                    studioVoices={studioVoices}
                    engines={engines}
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
  onAdd, onDelete, onRename, onTags, onEdit, onEditInGenerate, onChanged, voices, studioVoices, engines,
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
  onEdit: (name: string, body: { mute: string[]; regenerate: string[]; save_as?: string | null }) => Promise<string>;
  onEditInGenerate: (spec: BlockSpec) => void;
  onChanged: () => void;
  voices: string[];
  studioVoices: string[];
  engines: string[];
}) {
  const [open, setOpen] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [rename, setRename] = useState(block.name);
  const [newTag, setNewTag] = useState("");
  const [muteSet, setMuteSet] = useState<Set<string>>(new Set());
  const [regenSet, setRegenSet] = useState<Set<string>>(new Set());
  const [editBusy, setEditBusy] = useState(false);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Vocals panel state
  const [lyrics, setLyrics] = useState(block.lyrics ?? "");
  const [theme, setTheme] = useState("");
  const [voice, setVoice] = useState("");
  const [engine, setEngine] = useState("");
  const [harmonies, setHarmonies] = useState(true);
  const [clarity, setClarity] = useState(false);
  const [phonetic, setPhonetic] = useState("");
  const [showPhonetic, setShowPhonetic] = useState(false);
  const [phonBusy, setPhonBusy] = useState(false);
  const [sectionVoices, setSectionVoices] = useState<SectionVoice[] | null>(null);
  const [sectionEngines, setSectionEngines] = useState<string[]>([]);
  const [drafting, setDrafting] = useState(false);
  const [composing, setComposing] = useState(false);
  const [vocBusy, setVocBusy] = useState(false);
  const [vocProg, setVocProg] = useState(0);
  const [vocMsg, setVocMsg] = useState("");
  const [vocUrls, setVocUrls] = useState<{ audio: string | null; vocal?: string | null; pdf?: string | null } | null>(null);
  const [noteCount, setNoteCount] = useState<number | null>(null);
  const [takes, setTakes] = useState<api.VocalTake[]>([]);

  const voiceOptions = engine === "studio" ? studioVoices : voices;

  const loadTakes = () =>
    api.listVocalTakes(block.name).then((r) => setTakes(r.takes)).catch(() => setTakes([]));
  async function onDeleteTake(id: string) {
    try {
      await api.deleteVocalTake(block.name, id);
      setTakes((ts) => ts.filter((t) => t.id !== id));
    } catch (e) { setVocMsg(String(e)); }
  }

  useEffect(() => {
    if (open && noteCount === null) {
      api.getMelodyInfo(block.name).then((m) => setNoteCount(m.total_notes)).catch(() => setNoteCount(0));
    }
    if (open && !engine && engines.length) setEngine(engines.includes("studio") ? "studio" : engines[0]);
    if (open && sectionVoices === null) {
      api.getSectionVoices(block.name)
        .then((r) => { setSectionVoices(r.sections); setSectionEngines(r.sections.map((s) => s.suggested)); })
        .catch(() => setSectionVoices([]));
    }
    if (open) loadTakes();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, engines]);

  // Per-section switching only makes sense when there are multiple sections and
  // the studio SVS is available (otherwise everything is the rough engine).
  const perSection = !!sectionVoices && sectionVoices.length >= 2 && engines.length > 1;

  // Pick a sensible default voice for the current engine.
  useEffect(() => {
    if (!open || !voiceOptions.length || voiceOptions.includes(voice)) return;
    const preferred = engine === "studio" ? "tiger_fresh" : "Samantha";
    setVoice(voiceOptions.includes(preferred) ? preferred : voiceOptions[0]);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, engine, voiceOptions]);

  async function onDraft() {
    setDrafting(true); setVocMsg("Asking Claude Code to draft lyrics…");
    try {
      const { request_id } = await api.requestLyrics(block.name, theme);
      const r = await api.pollAiRequest(request_id);
      if (r.status === "error" || typeof r.answer !== "string") setVocMsg(r.error || "Lyric draft failed");
      else { setLyrics(r.answer); setVocMsg(""); }
    } catch (e) { setVocMsg(String(e)); }
    finally { setDrafting(false); }
  }
  async function onComposeMelody() {
    if (!lyrics.trim()) return;
    setComposing(true); setVocMsg("Asking Claude Code to compose a melody for these lyrics…");
    try {
      const { request_id } = await api.composeMelody(block.name, lyrics);
      const r = await api.pollAiRequest(request_id, { timeoutMs: 240000 });
      if (r.status === "error") setVocMsg(r.error || "Melody compose failed");
      else { setVocMsg("Melody composed — block updated. Hit 🎤 Sing it."); setNoteCount(null); onChanged(); }
    } catch (e) { setVocMsg(String(e)); }
    finally { setComposing(false); }
  }
  async function onPhonetic() {
    if (!lyrics.trim()) return;
    setPhonBusy(true); setShowPhonetic(true);
    try { setPhonetic((await api.getPhonetic(lyrics)).phonetic); }
    catch (e) { setVocMsg(String(e)); }
    finally { setPhonBusy(false); }
  }
  async function onSing() {
    if (!lyrics.trim()) return;
    setVocBusy(true); setVocUrls(null); setVocProg(0); setVocMsg("Starting…");
    try {
      // only send the phonetic override when the editor is open and filled
      const phon = showPhonetic && phonetic.trim() ? phonetic : "";
      // when per-section is active, send each section's engine (default to studio)
      const section_engines = perSection && sectionVoices
        ? sectionVoices.map((s, i) => ({ start_bar: s.start_bar, end_bar: s.end_bar, engine: sectionEngines[i] || "studio" }))
        : undefined;
      const { job_id } = await api.renderVocals(block.name, { lyrics, voice, engine: engine || "rough", harmonies, clarity, phonetic: phon, section_engines });
      const job = await api.pollVocal(job_id, (p, m) => { setVocProg(p); setVocMsg(m); });
      if (job.status === "error") setVocMsg(job.error || "Vocal render failed");
      else if (job.result) { setVocUrls({ audio: job.result.urls.audio, vocal: job.result.urls.vocal, pdf: job.result.urls.pdf }); loadTakes(); }
    } catch (e) { setVocMsg(String(e)); }
    finally { setVocBusy(false); }
  }

  const dirty = muteSet.size > 0 || regenSet.size > 0;
  const toggleIn = (s: Set<string>, v: string, setter: (x: Set<string>) => void) => {
    const n = new Set(s); n.has(v) ? n.delete(v) : n.add(v); setter(n);
  };
  async function applyEdit(saveAs: string | null) {
    setEditBusy(true);
    try {
      await onEdit(block.name, { mute: [...muteSet], regenerate: [...regenSet], save_as: saveAs });
      setMuteSet(new Set()); setRegenSet(new Set());
    } catch { /* surfaced by parent */ }
    finally { setEditBusy(false); }
  }

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
        <span
          className="bc-name"
          {...(selectMode ? {} : drag.listeners)}
          {...(selectMode ? {} : drag.attributes)}
          onClick={() => (selectMode ? onToggleSel(block.name) : setOpen((o) => !o))}
        >
          {block.name}
        </span>
        {selectMode ? (
          <label className="bc-check">
            <input type="checkbox" checked={selected} onChange={() => onToggleSel(block.name)} />
          </label>
        ) : (
          <button className={"bc-star" + (isFav ? " on" : "")} onClick={() => onToggleFav(block.name)} aria-label="Favorite">
            {isFav ? "★" : "☆"}
          </button>
        )}
      </div>

      {!selectMode && (
        <div className="bc-controls">
          <button className="bc-play" onClick={togglePlay} disabled={!block.has_preview} aria-label={playing ? "Pause" : "Play"}>
            {playing ? "⏸" : "▶"}
          </button>
          {block.has_preview ? <Sparkline name={block.name} /> : <div className="spark-empty" />}
          <button className="bc-add" onClick={() => onAdd(block.name)} aria-label="Add to timeline">＋</button>
          <button className="bc-gear" onClick={() => setOpen((o) => !o)} aria-label="Details">⚙</button>
        </div>
      )}

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

          {/* Channel editor: mute / regenerate instruments */}
          <div className="track-edit">
            <div className="te-head">
              <span className="te-title">Channels</span>
              {block.spec
                ? <button className="te-ineditor" onClick={() => onEditInGenerate(block.spec!)}>✎ Edit in Generate</button>
                : <span className="te-note">no generation info</span>}
            </div>
            {block.spec?.inferred && (
              <div className="te-note">Estimated info — regenerate disabled; “Edit in Generate” is a starting point.</div>
            )}
            {(block.instruments ?? []).map((inst) => {
              const canRegen = !!block.spec && !block.spec.inferred;
              return (
                <div className="te-row" key={inst.name}>
                  <span className="te-name">{inst.name}</span>
                  <button
                    className={"te-btn" + (muteSet.has(inst.name) ? " on" : "")}
                    onClick={() => toggleIn(muteSet, inst.name, setMuteSet)}
                  >🔇 mute</button>
                  <button
                    className={"te-btn" + (regenSet.has(inst.name) ? " on" : "")}
                    disabled={!canRegen}
                    title={canRegen ? "Re-roll this part" : "Needs full generation info"}
                    onClick={() => toggleIn(regenSet, inst.name, setRegenSet)}
                  >↻ regen</button>
                </div>
              );
            })}
            <div className="te-actions">
              <button className="btn secondary sm" disabled={editBusy || !dirty} onClick={() => applyEdit(null)}>
                {editBusy ? "Working…" : "Apply"}
              </button>
              <button className="btn ghost sm" disabled={editBusy || !dirty}
                onClick={() => { const nm = window.prompt("New block name", `${block.name} edit`); if (nm) applyEdit(nm); }}>
                Save as new
              </button>
            </div>
          </div>

          {/* Vocals */}
          <div className="vocals">
            <div className="te-head">
              <span className="te-title">Vocals</span>
              {noteCount != null && noteCount > 0 && <span className="te-note">~{noteCount} notes to sing</span>}
            </div>
            <textarea className="lyrics-area" rows={3} value={lyrics}
              onChange={(e) => setLyrics(e.target.value)} placeholder="Lyrics… (or draft with AI)" />
            <div className="voc-row">
              <input className="voc-theme" type="text" placeholder="theme (e.g. summer night)"
                value={theme} onChange={(e) => setTheme(e.target.value)} />
              <button className="btn ghost sm" disabled={drafting} onClick={onDraft}>{drafting ? "…" : "✨ Draft"}</button>
              <button className="btn ghost sm" disabled={composing || !lyrics.trim()} onClick={onComposeMelody}
                title="Claude Code composes a vocal melody + harmony for these lyrics (replaces any existing vocal line)">
                {composing ? "…" : "🎼 Compose melody"}</button>
            </div>
            <div className="voc-row">
              {engines.length > 1 && !perSection && (
                <select value={engine} onChange={(e) => setEngine(e.target.value)} title="Voice engine">
                  {engines.map((en) => (
                    <option key={en} value={en}>{en === "studio" ? "Studio (real SVS)" : "Rough (demo)"}</option>
                  ))}
                </select>
              )}
              <select value={voice} onChange={(e) => setVoice(e.target.value)} title="Voice">
                {voiceOptions.length === 0 && <option value="">default</option>}
                {voiceOptions.map((v) => (
                  <option key={v} value={v}>{v.replace(/^tiger_/, "")}</option>
                ))}
              </select>
              <button className={"chip" + (harmonies ? " on" : "")} onClick={() => setHarmonies((h) => !h)} title="Stack harmony/backing lines">＋harmonies</button>
              <button className={"chip" + (clarity ? " on" : "")} onClick={() => setClarity((c) => !c)} title="Clarity mode: cap high notes, gap words, de-melisma for clearer diction (trades a little melody)">✦clarity</button>
              <button className={"chip" + (showPhonetic ? " on" : "")} onClick={() => setShowPhonetic((s) => !s)} title="Edit how each word is pronounced (ARPABET) to fix the voice's diction">🗣 phonetic</button>
              <button className="btn secondary sm" disabled={vocBusy || !lyrics.trim()} onClick={onSing}>
                {vocBusy ? "Singing…" : "🎤 Sing it"}
              </button>
            </div>
            {perSection && sectionVoices && (
              <div className="section-voices">
                <div className="te-note">Voice per section — rap dense verses (TTS), sing the rest (SVS). ✦clarity still applies to Sing sections.</div>
                {sectionVoices.map((s, i) => (
                  <div key={`${s.start_bar}-${i}`} className="sv-row">
                    <span className="sv-label">
                      {s.label} <span className="sv-role">({s.role}) · bars {s.start_bar}–{s.end_bar}</span>
                      {s.dense && <span className="sv-hint" title="Fast/dense vocal line — reads better as Rap"> · dense</span>}
                    </span>
                    <span className="sv-toggle">
                      <button
                        className={"chip" + (sectionEngines[i] !== "rough" ? " on" : "")}
                        onClick={() => setSectionEngines((a) => a.map((e, j) => (j === i ? "studio" : e)))}
                      >🎤 Sing</button>
                      <button
                        className={"chip" + (sectionEngines[i] === "rough" ? " on" : "")}
                        onClick={() => setSectionEngines((a) => a.map((e, j) => (j === i ? "rough" : e)))}
                      >🗣 Rap</button>
                    </span>
                  </div>
                ))}
              </div>
            )}
            {showPhonetic && (
              <div className="phonetic-editor">
                <div className="te-note">
                  Phonetic version (ARPABET, one [group] per word) — overrides how the voice pronounces each word.
                  <button className="btn ghost sm" disabled={phonBusy || !lyrics.trim()} onClick={onPhonetic}>
                    {phonBusy ? "Generating…" : phonetic.trim() ? "↻ regenerate from lyrics" : "✨ generate from lyrics"}
                  </button>
                </div>
                <textarea
                  className="phonetic-text"
                  rows={4}
                  spellCheck={false}
                  placeholder="e.g.  [y uw] [b r ow k] [m ay] [hh aa r t]   — click “generate from lyrics” to start, then tweak."
                  value={phonetic}
                  onChange={(e) => setPhonetic(e.target.value)}
                />
              </div>
            )}
            {vocBusy && <div className="progress"><div style={{ width: `${Math.round(vocProg * 100)}%` }} /></div>}
            {vocMsg && !vocUrls && <div className={vocMsg.startsWith("Error") || vocMsg.includes("OPENAI") ? "error" : "progress-msg"}>{vocMsg}</div>}
            {takes.length > 0 && (
              <div className="takes">
                <div className="te-note">Saved takes ({takes.length})</div>
                {takes.map((t) => (
                  <div key={t.id} className="take-row">
                    <audio controls src={api.vocalTakeUrl(block.name, t.id, "mix")} />
                    <div className="take-info">
                      <span className="te-note">
                        {new Date(t.created).toLocaleString()} · {t.engine}
                        {t.voice ? ` / ${t.voice.replace(/^tiger_/, "")}` : ""}
                        {t.harmonies ? " · +harm" : ""}
                        {t.clarity ? " · ✦clarity" : ""}
                        {t.phonetic ? " · 🗣" : ""}
                        {(() => { const n = (t.section_engines ?? []).filter((s) => s.engine === "rough").length; return n ? ` · rap×${n}` : ""; })()}
                      </span>
                      <div className="links">
                        {t.files.vocal && <a href={api.vocalTakeUrl(block.name, t.id, "vocal")} download>↓ Stem</a>}
                        {t.files.score && <a href={api.vocalTakeUrl(block.name, t.id, "score")} download>↓ Score</a>}
                        <button className="btn ghost sm" onClick={() => onDeleteTake(t.id)} title="Delete this take">🗑 Delete</button>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
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
      <div className="tl-rep">
        <button
          onClick={() => onRepeat(entry.id, entry.repeat > 1 ? entry.repeat - 1 : entry.repeat - 0.25)}
          disabled={entry.repeat <= 0.25} aria-label="Shorter">−</button>
        <span className="tl-rep-n">
          {bars ? `${Math.max(1, Math.round(entry.repeat * bars))}b` : `×${entry.repeat}`}
        </span>
        <button
          onClick={() => onRepeat(entry.id, entry.repeat < 1 ? entry.repeat + 0.25 : entry.repeat + 1)}
          disabled={entry.repeat >= 32} aria-label="Longer">+</button>
      </div>
      <button className="tl-x" onClick={() => onRemove(entry.id)} aria-label="Remove">✕</button>
    </div>
  );
}
