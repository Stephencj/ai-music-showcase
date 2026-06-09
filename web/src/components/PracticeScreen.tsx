import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { ScoreData, ChordSpan } from "../api";
import type { Block, Preset } from "../types";
import ChordDiagram from "./ChordDiagram";
import TapeView from "./TapeView";
import NotationRoll, { type RollNote } from "./NotationRoll";
import SheetMusic from "./SheetMusic";
import type { BlockNotes } from "../api";
import { MODES, ALL_ROOTS, scaleToModeId, rootPc, romanFor, nashvilleFor } from "../chordLabels";

type Notation = "chord" | "nashville" | "roman";
type ChartView = "grid" | "tape" | "sheet";
type Mode = "block" | "upload" | "scan";

const NOTATION_LABEL: Record<Notation, string> = {
  chord: "Chords",
  nashville: "Nashville",
  roman: "Roman",
};

export default function PracticeScreen() {
  const [mode, setMode] = useState<Mode>("block");
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [songs, setSongs] = useState<string[]>([]);
  // Picker value, prefixed: "block:<name>" or "song:<title>".
  const [selected, setSelected] = useState<string>("");
  const [presets, setPresets] = useState<Preset[]>([]);

  const [score, setScore] = useState<ScoreData | null>(null);
  // Per-track notes for the notation roll + real-time diagrams (blocks only).
  const [partNotes, setPartNotes] = useState<BlockNotes | null>(null);
  const [partIdx, setPartIdx] = useState(-1);   // -1 = no part selected
  const [solo, setSolo] = useState(false);      // play just the selected part
  // Which panels show in the practice space (gear), persisted.
  const [panels, setPanels] = useState<Record<string, boolean>>(() => {
    try {
      return { nowPlaying: true, diagrams: true, roll: true, chart: true,
               ...JSON.parse(localStorage.getItem("practice.panels") || "{}") };
    } catch { return { nowPlaying: true, diagrams: true, roll: true, chart: true }; }
  });
  const [showSettings, setShowSettings] = useState(false);
  // Diagram mode: chord-shape (practice) vs full neck (what's on the page).
  const [neckMode, setNeckMode] = useState(() => localStorage.getItem("practice.neck") === "1");
  const [audioSrc, setAudioSrc] = useState<string>("");
  const [progression, setProgression] = useState<string[]>([]);

  const [err, setErr] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [notation, setNotation] = useState<Notation>("chord");
  const [view, setView] = useState<ChartView>("grid");
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  // Loop: "off" | "all" | "s<sectionIndex>" (loop a single section).
  const [loop, setLoop] = useState("off");
  // Tonic + mode the Roman/Nashville numbers are computed against. Seeded from
  // the detected key, but fully selectable across the modal range for learning.
  const [tonic, setTonic] = useState("C");
  const [keyMode, setKeyMode] = useState("major");

  const audioRef = useRef<HTMLAudioElement | null>(null);

  // "Generate similar" (upload mode)
  const [simGenre, setSimGenre] = useState<string>("");
  const [simMsg, setSimMsg] = useState<string>("");
  const [simBusy, setSimBusy] = useState(false);

  // "Scan sheet music" (scan mode)
  const [scanMsg, setScanMsg] = useState<string>("");
  const [scanBusy, setScanBusy] = useState(false);

  const activeRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.getBlocks()
      .then((bs) => {
        const playable = bs.filter((b) => b.has_preview);
        setBlocks(playable);
        setSelected((cur) => cur || (playable.length ? `block:${playable[0].name}` : ""));
      })
      .catch((e) => setErr(String(e)));
    api.listSongs().then((r) => setSongs(r.songs || [])).catch(() => {});
    api.getPresets().then((ps) => {
      setPresets(ps);
      if (ps.length) setSimGenre(ps[0].id);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try { localStorage.setItem("practice.panels", JSON.stringify(panels)); } catch { /* ignore */ }
  }, [panels]);

  // Block mode: load score + audio for the selected block OR song.
  useEffect(() => {
    if (mode !== "block" || !selected) return;
    setLoading(true); setScore(null); setErr(""); setT(0); setLoop("off");
    setPartNotes(null); setPartIdx(-1); setSolo(false);
    if (selected.startsWith("song:")) {
      const title = selected.slice(5);
      setAudioSrc(api.songAudioUrl(title));
      api.getSongScoreData(title)
        .then((s) => { setScore(s); setProgression([]); })
        .catch((e) => setErr(String(e)))
        .finally(() => setLoading(false));
    } else {
      const nm = selected.replace(/^block:/, "");
      const block = blocks.find((b) => b.name === nm);
      if (block) setAudioSrc(api.mediaUrl(block.audio_url));
      api.getScoreData(nm)
        .then((s) => { setScore(s); setProgression([]); })
        .catch((e) => setErr(String(e)))
        .finally(() => setLoading(false));
      api.getBlockNotes(nm).then(setPartNotes).catch(() => setPartNotes(null));
    }
  }, [mode, selected, blocks]);

  async function onUpload(file: File) {
    setLoading(true); setScore(null); setErr(""); setT(0); setSimMsg("");
    setAudioSrc(URL.createObjectURL(file));
    try {
      const a = await api.analyzeAudio(file);
      setScore(a);
      setProgression(a.progression || []);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }

  async function generateSimilar() {
    if (!score) return;
    setSimBusy(true); setSimMsg("Composing…");
    try {
      const { job_id } = await api.generate({
        genre: simGenre,
        key: score.key,
        scale: score.scale,
        tempo: Math.round(score.tempo),
        progression,
        instruments: [],
        sections: [],
        with_pdf: false,
        with_stems: false,
        master_preset: "default",
        save_as_block: true,
        block_name: `Similar ${score.key} ${Math.round(score.tempo)}bpm`,
      });
      for (;;) {
        const job = await api.getJob(job_id);
        setSimMsg(job.message || "Composing…");
        if (job.status === "done") {
          const b = job.result?.saved_block;
          setSimMsg(b ? `Saved block "${b}" — open it in Compose.` : "Done.");
          api.getBlocks().then((bs) => setBlocks(bs.filter((x) => x.has_preview)));
          break;
        }
        if (job.status === "error") { setSimMsg(`Error: ${job.error || "failed"}`); break; }
        await new Promise((r) => setTimeout(r, 500));
      }
    } catch (e) {
      setSimMsg(`Error: ${e}`);
    } finally {
      setSimBusy(false);
    }
  }

  async function scanSheet(file: File) {
    setScanBusy(true); setScanMsg("Uploading…"); setErr("");
    try {
      const { job_id } = await api.scanSheet(file);
      for (;;) {
        const job = await api.getJob(job_id);
        setScanMsg(job.message || "Scanning…");
        if (job.status === "done") {
          const b = job.result?.saved_block;
          if (b) {
            const bs = (await api.getBlocks()).filter((x) => x.has_preview);
            setBlocks(bs);
            // The saved name may be normalised (spaces → underscores) in the
            // block store; match it back to the actual listed block.
            const norm = (s: string) => s.replace(/[^a-z0-9]+/gi, "_").toLowerCase();
            const hit = bs.find((x) => x.name === b) || bs.find((x) => norm(x.name) === norm(b));
            setMode("block");
            setSelected(`block:${hit ? hit.name : b}`);
            setScanMsg("");
          } else {
            setScanMsg("Scan finished but produced no notes.");
          }
          break;
        }
        if (job.status === "error") {
          setScanMsg(`Couldn't read the score: ${job.error || "failed"}`);
          break;
        }
        await new Promise((r) => setTimeout(r, 800));
      }
    } catch (e) {
      setScanMsg(`Error: ${e}`);
    } finally {
      setScanBusy(false);
    }
  }

  const activeSpanIdx = useMemo(() => {
    if (!score) return -1;
    return score.chord_spans.findIndex((s) => t >= s.start_time && t < s.end_time);
  }, [score, t]);

  const active = activeSpanIdx >= 0 ? score!.chord_spans[activeSpanIdx] : null;
  const next =
    score && activeSpanIdx >= 0 && activeSpanIdx + 1 < score.chord_spans.length
      ? score.chord_spans[activeSpanIdx + 1]
      : null;

  const beatsToNext = useMemo(() => {
    if (!score || !active) return null;
    const beatSec = score.bar_seconds / score.beats_per_bar;
    return Math.max(0, Math.ceil((active.end_time - t) / beatSec));
  }, [score, active, t]);

  // Follow the song by scrolling ONLY the chart container (grid view) — the
  // now-playing header + diagrams stay pinned above and don't move.
  useEffect(() => {
    if (view !== "grid") return;
    const box = chartRef.current, cell = activeRef.current;
    if (!box || !cell) return;
    const b = box.getBoundingClientRect(), c = cell.getBoundingClientRect();
    box.scrollTo({ top: box.scrollTop + (c.top - b.top) - b.height / 2 + c.height / 2, behavior: "smooth" });
  }, [activeSpanIdx, view]);

  // Apply the practice speed to the audio element. Set preservesPitch BEFORE
  // playbackRate (and across all vendor prefixes) so changing speed never
  // shifts the key — important on iOS WKWebView.
  function applyRate(a: HTMLAudioElement | null) {
    if (!a) return;
    a.preservesPitch = true;
    (a as unknown as { webkitPreservesPitch?: boolean }).webkitPreservesPitch = true;
    (a as unknown as { mozPreservesPitch?: boolean }).mozPreservesPitch = true;
    a.playbackRate = speed;
  }
  useEffect(() => { applyRate(audioRef.current); }, [speed, audioSrc, score]);

  // Seed the tonic/mode selectors from the detected key whenever a new score
  // loads (the user can then override them across the full modal range).
  useEffect(() => {
    if (!score) return;
    setTonic(ALL_ROOTS[rootPc(score.key)]);
    setKeyMode(scaleToModeId(score.scale));
  }, [score]);

  const modeIntervals = (MODES.find((m) => m.id === keyMode) || MODES[0]).intervals;
  const sourceIsSong = selected.startsWith("song:");
  const blockName = selected.startsWith("block:") ? selected.slice(6) : "";

  const selectedTrack = partNotes && partIdx >= 0 ? partNotes.tracks[partIdx] : null;

  // The notation roll follows the selected part only.
  const partRollNotes: RollNote[] = useMemo(() => {
    if (!selectedTrack || !partNotes) return [];
    const spb = 60 / (partNotes.tempo || 120);
    return selectedTrack.notes.map(([pitch, sb, db]) => ({ pitch, start: sb * spb, dur: db * spb }));
  }, [selectedTrack, partNotes]);

  // The piano/guitar light up the actual notes being hit: the selected part if
  // one is chosen, otherwise every musical (non-drum) part.
  const diagramNotes: RollNote[] = useMemo(() => {
    if (!partNotes) return [];
    const spb = 60 / (partNotes.tempo || 120);
    // Pitched diagrams: the selected part if it's melodic, else all musical
    // (non-drum) parts — a selected DRUM part isn't pitched, so fall back.
    const tracks = selectedTrack && !selectedTrack.is_drum
      ? [selectedTrack] : partNotes.tracks.filter((t) => !t.is_drum);
    const out: RollNote[] = [];
    for (const tr of tracks)
      for (const [pitch, sb, db] of tr.notes) out.push({ pitch, start: sb * spb, dur: db * spb });
    return out;
  }, [partNotes, selectedTrack]);

  // (The neck-mode diagrams drive their own highlights via rAF + DOM toggling
  // from `diagramNotes` + audioRef, so no per-note React state is needed here.)

  // For section looping, play the WAV (sample-accurate seeks — no MP3 decoder
  // priming gap), which keeps loops tight without losing pitch-preserved speed.
  const sectionLooping = loop.startsWith("s");
  // Real pitch range of what's driving the diagrams, for the wide piano span.
  const partRange = useMemo(() => {
    if (!diagramNotes.length) return undefined;
    let lo = 128, hi = 0;
    for (const n of diagramNotes) { lo = Math.min(lo, n.pitch); hi = Math.max(hi, n.pitch); }
    return [lo, hi] as [number, number];
  }, [diagramNotes]);

  const playSrc = (solo && selectedTrack && blockName)
    ? api.partAudioUrl(blockName, partIdx)
    : sectionLooping
      ? (blockName ? api.blockFileUrl(blockName, "wav")
         : sourceIsSong ? api.songWavUrl(selected.slice(5)) : audioSrc)
      : audioSrc;

  // Section looping driven by rAF (60fps) instead of timeupdate (~4Hz), and
  // seeking back a hair BEFORE the section end so the element never fires
  // 'ended' (which would stop playback on the last section) and there's no
  // quarter-second overshoot — tight, snappy loops.
  useEffect(() => {
    if (!loop.startsWith("s") || !score) return;
    const sec = score.sections[Number(loop.slice(1))];
    if (!sec) return;
    let raf = 0;
    const tick = () => {
      const a = audioRef.current;
      if (a && a.currentTime >= sec.end_time - 0.06) {
        a.currentTime = sec.start_time;
        if (a.paused && playing) a.play().catch(() => {});
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [loop, score, playing]);

  // Seek playback to a chord's start (tap a cell to jump there).
  function seekTo(time: number) {
    const a = audioRef.current;
    if (a) { a.currentTime = time; setT(time); }
  }

  // All three labels for a chord, with the selected notation emphasized
  // (primary) and the others shown small (secondary) — switching notation
  // changes emphasis rather than hiding the rest.
  type Labels = { primary: string; secondary: string };
  function labelParts(c: { symbol: string; root: string | null; quality: string | null }): Labels {
    if (c.symbol === "N.C." || !c.root || !c.quality) {
      return { primary: c.symbol === "N.C." ? "—" : c.symbol, secondary: "" };
    }
    const chord = c.symbol;
    const roman = romanFor(c.root, c.quality, tonic, modeIntervals);
    const nash = nashvilleFor(c.root, c.quality, tonic, modeIntervals);
    if (notation === "roman") return { primary: roman, secondary: `${chord} · ${nash}` };
    if (notation === "nashville") return { primary: nash, secondary: `${chord} · ${roman}` };
    return { primary: chord, secondary: `${roman} · ${nash}` };
  }

  const activeSection = useMemo(() => {
    if (!score) return null;
    return score.sections.find((s) => t >= s.start_time && t < s.end_time) || null;
  }, [score, t]);

  return (
    <div className="practice">
      <div className="seg seg-mode">
        <button className={mode === "block" ? "on" : ""} onClick={() => { setMode("block"); setScore(null); }}>
          My blocks
        </button>
        <button className={mode === "upload" ? "on" : ""} onClick={() => { setMode("upload"); setScore(null); setAudioSrc(""); }}>
          Analyze a song
        </button>
        <button className={mode === "scan" ? "on" : ""} onClick={() => { setMode("scan"); setScore(null); setAudioSrc(""); }}>
          Scan sheet
        </button>
      </div>

      <div className="practice-controls">
        {mode === "block" ? (
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {blocks.length === 0 && songs.length === 0 && <option value="">Nothing to play yet</option>}
            {songs.length > 0 && (
              <optgroup label="Songs">
                {songs.map((s) => <option key={`song:${s}`} value={`song:${s}`}>{s}</option>)}
              </optgroup>
            )}
            <optgroup label="Blocks">
              {blocks.map((b) => (
                <option key={`block:${b.name}`} value={`block:${b.name}`}>{b.name}</option>
              ))}
            </optgroup>
          </select>
        ) : mode === "upload" ? (
          <label className="upload-btn">
            <input
              type="file"
              accept="audio/*,.mp3,.wav,.m4a,.aac,.ogg,.flac"
              onChange={(e) => { const f = e.target.files?.[0]; if (f) onUpload(f); }}
            />
            <span>🎧 Choose a song…</span>
          </label>
        ) : (
          <label className="upload-btn">
            <input
              type="file"
              accept="image/png,image/jpeg,image/*"
              disabled={scanBusy}
              onChange={(e) => { const f = e.target.files?.[0]; if (f) scanSheet(f); }}
            />
            <span>{scanBusy ? "Scanning…" : "📄 Choose a sheet-music photo…"}</span>
          </label>
        )}
        <div className="seg">
          {(Object.keys(NOTATION_LABEL) as Notation[]).map((n) => (
            <button key={n} className={notation === n ? "on" : ""} onClick={() => setNotation(n)}>
              {NOTATION_LABEL[n]}
            </button>
          ))}
        </div>
      </div>

      {score && notation !== "chord" && (
        <div className="keymode-row">
          <span className="keymode-label">Numbers vs</span>
          <select value={tonic} onChange={(e) => setTonic(e.target.value)}>
            {ALL_ROOTS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={keyMode} onChange={(e) => setKeyMode(e.target.value)}>
            {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <button
            className="keymode-reset"
            onClick={() => { setTonic(ALL_ROOTS[rootPc(score.key)]); setKeyMode(scaleToModeId(score.scale)); }}
            title="Reset to the detected key"
          >↺</button>
        </div>
      )}

      {err && <div className="practice-err">{err}</div>}
      {mode === "scan" && scanMsg && <div className="practice-hint">{scanMsg}</div>}
      {mode === "scan" && !score && !scanMsg && (
        <div className="practice-hint">Upload a clear photo or scan of printed sheet music. Recognition takes a minute or two and works best on clean, well-lit pages.</div>
      )}
      {loading && <div className="practice-hint">{mode === "upload" ? "Listening & detecting chords…" : "Analyzing chords…"}</div>}

      {score && (
        <>
          <div className="practice-head">
          {audioSrc && (
            <audio
              ref={audioRef}
              src={playSrc}
              controls
              loop={loop === "all"}
              onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onLoadedMetadata={(e) => {
                applyRate(e.currentTarget);
                if (loop.startsWith("s")) {
                  const sec = score.sections[Number(loop.slice(1))];
                  if (sec) e.currentTarget.currentTime = sec.start_time;
                }
              }}
              style={{ width: "100%" }}
            />
          )}

          {/* Practice speed — change playback rate without dropping pitch. The
              chord chart tracks the media timeline, so it stays in sync at any
              speed. Effective tempo shown for reference. */}
          <div className="speed-row">
            <span className="speed-label">Speed</span>
            <input
              className="speed-slider"
              type="range" min={0.5} max={1.5} step={0.05}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            />
            <button className="speed-reset" onClick={() => setSpeed(1)} title="Reset to 1×">{speed.toFixed(2)}×</button>
            <span className="speed-bpm">{Math.round(score.tempo * speed)} BPM</span>
          </div>

          <div className="loop-row">
            <span className="speed-label">🔁 Loop</span>
            <select
              value={loop}
              onChange={(e) => {
                const v = e.target.value;
                setLoop(v);
                if (v.startsWith("s")) seekTo(score.sections[Number(v.slice(1))].start_time);
              }}
            >
              <option value="off">Off</option>
              <option value="all">Whole {sourceIsSong ? "song" : "block"}</option>
              {score.sections.map((s, i) => (
                <option key={`${s.label}-${s.start_bar}`} value={`s${i}`}>{s.label}</option>
              ))}
            </select>
          </div>

          {!sourceIsSong && partNotes && partNotes.tracks.length > 0 && (
            <div className="part-row">
              <span className="speed-label">🎯 Part</span>
              <select value={partIdx} onChange={(e) => { setPartIdx(Number(e.target.value)); setSolo(false); }}>
                <option value={-1}>Off — chords only</option>
                {partNotes.tracks.map((tr, i) => (
                  <option key={i} value={i}>{tr.track}{tr.is_drum ? " (drums)" : ""}</option>
                ))}
              </select>
              {partIdx >= 0 && (
                <label className="part-solo">
                  <input type="checkbox" checked={solo} onChange={(e) => setSolo(e.target.checked)} /> Solo
                </label>
              )}
            </div>
          )}

          {mode === "upload" && (
            <div className="gen-similar">
              <select value={simGenre} onChange={(e) => setSimGenre(e.target.value)} disabled={simBusy}>
                {presets.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
              <button className="btn" onClick={generateSimilar} disabled={simBusy || !progression.length}>
                {simBusy ? "Composing…" : "Generate similar"}
              </button>
              {simMsg && <span className="gen-msg">{simMsg}</span>}
            </div>
          )}

          {panels.nowPlaying && (
            <div className="now-playing">
              <div className="np-meta">
                <span className="np-key">{score.key} {score.scale}</span>
                <span className="np-sec">{activeSection?.label || ""}</span>
                <span className="np-tempo">{Math.round(score.tempo)} BPM</span>
              </div>
              <div className="np-chords">
                <div className="np-current">
                  <div className="np-big">{active ? labelParts(active).primary : "—"}</div>
                  {active && labelParts(active).secondary && (
                    <div className="np-alt">{labelParts(active).secondary}</div>
                  )}
                </div>
                <div className="np-count">
                  {playing && beatsToNext != null ? `${beatsToNext}` : "·"}
                  <span>beats</span>
                </div>
                <div className="np-next">
                  <div className="np-next-label">next</div>
                  <div className="np-next-chord">{next ? labelParts(next).primary : "—"}</div>
                </div>
              </div>
            </div>
          )}

          {panels.diagrams && (diagramNotes.length > 0 || active?.root) && (
            <div className="diagram-block">
              <div className="seg diagram-mode">
                <button className={!neckMode ? "on" : ""}
                  onClick={() => { setNeckMode(false); localStorage.setItem("practice.neck", "0"); }}>Chord</button>
                <button className={neckMode ? "on" : ""}
                  onClick={() => { setNeckMode(true); localStorage.setItem("practice.neck", "1"); }}>Full neck</button>
              </div>
              <ChordDiagram
                root={active?.root || "C"}
                quality={active?.quality || "maj"}
                notes={partNotes ? diagramNotes : []}
                audioRef={audioRef}
                range={partRange}
                neck={neckMode}
              />
            </div>
          )}

          {panels.roll && partRollNotes.length > 0 && (
            <div className="roll-card">
              <div className="diagram-title">{selectedTrack?.track} — notation roll</div>
              <NotationRoll notes={partRollNotes} audioRef={audioRef} />
            </div>
          )}

          <div className="head-controls">
            <div className="seg view-toggle">
              <button className={view === "grid" ? "on" : ""} onClick={() => setView("grid")}>Grid</button>
              <button className={view === "tape" ? "on" : ""} onClick={() => setView("tape")}>Tape ▶</button>
              {!sourceIsSong && (
                <button className={view === "sheet" ? "on" : ""} onClick={() => setView("sheet")}>Sheet ♪</button>
              )}
            </div>
            <button className="gear-btn" onClick={() => setShowSettings((s) => !s)} title="Practice settings">⚙</button>
          </div>
          {showSettings && (
            <div className="settings-panel">
              {([["nowPlaying", "Now playing"], ["diagrams", "Piano / guitar"],
                 ["roll", "Notation roll"], ["chart", "Chord chart"]] as [string, string][]).map(([k, lbl]) => (
                <label key={k}>
                  <input type="checkbox" checked={!!panels[k]}
                    onChange={(e) => setPanels((p) => ({ ...p, [k]: e.target.checked }))} /> {lbl}
                </label>
              ))}
            </div>
          )}
          </div>

          {panels.chart && (view === "sheet" ? (
            blockName
              ? <SheetMusic blockName={blockName} audioRef={audioRef} trackIndex={partIdx} />
              : <div className="practice-hint">Sheet view is available for blocks (songs show the chart).</div>
          ) : view === "tape" ? (
            <TapeView score={score} labelParts={labelParts} audioRef={audioRef} onSeek={seekTo} />
          ) : (
            <div className="chart" ref={chartRef}>
              {score.sections.length > 0
                ? score.sections.map((sec) => (
                    <div key={`${sec.label}-${sec.start_bar}`} className="chart-section">
                      <div className="chart-section-label">{sec.label}</div>
                      <div className="chart-grid">
                        {score.chord_spans
                          .filter((s) => s.start_bar >= sec.start_bar && s.start_bar <= sec.end_bar)
                          .map((s) => (
                            <Cell key={s.start_bar} span={s} {...labelParts(s)}
                              active={s === active} cellRef={s === active ? activeRef : undefined}
                              onSeek={() => seekTo(s.start_time)} />
                          ))}
                      </div>
                    </div>
                  ))
                : (
                  <div className="chart-grid">
                    {score.chord_spans.map((s) => (
                      <Cell key={s.start_bar} span={s} {...labelParts(s)}
                        active={s === active} cellRef={s === active ? activeRef : undefined}
                        onSeek={() => seekTo(s.start_time)} />
                    ))}
                  </div>
                )}
            </div>
          ))}
        </>
      )}
    </div>
  );
}

function Cell({
  span, primary, secondary, active, cellRef, onSeek,
}: {
  span: ChordSpan;
  primary: string;
  secondary: string;
  active: boolean;
  cellRef?: React.RefObject<HTMLDivElement | null>;
  onSeek?: () => void;
}) {
  const bars = span.end_bar - span.start_bar + 1;
  return (
    <div ref={cellRef} className={`chart-cell${active ? " active" : ""}`} data-bars={bars}
      onClick={onSeek} role="button" tabIndex={0}>
      <div className="cell-chord">{primary}</div>
      {secondary && <div className="cell-sub">{secondary}</div>}
      {bars > 1 && <div className="cell-bars">{bars} bars</div>}
    </div>
  );
}
