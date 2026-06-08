import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { ScoreData, ChordSpan } from "../api";
import type { Block, Preset } from "../types";
import ChordDiagram from "./ChordDiagram";

type Notation = "chord" | "nashville" | "roman";
type Mode = "block" | "upload" | "scan";

const NOTATION_LABEL: Record<Notation, string> = {
  chord: "Chords",
  nashville: "Nashville",
  roman: "Roman",
};

function label(c: { symbol: string; nashville: string; roman: string }, n: Notation): string {
  if (c.symbol === "N.C.") return "—";
  if (n === "nashville") return c.nashville || c.symbol;
  if (n === "roman") return c.roman || c.symbol;
  return c.symbol;
}

export default function PracticeScreen() {
  const [mode, setMode] = useState<Mode>("block");
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [name, setName] = useState<string>("");
  const [presets, setPresets] = useState<Preset[]>([]);

  const [score, setScore] = useState<ScoreData | null>(null);
  const [audioSrc, setAudioSrc] = useState<string>("");
  const [progression, setProgression] = useState<string[]>([]);

  const [err, setErr] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [notation, setNotation] = useState<Notation>("chord");
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);

  // "Generate similar" (upload mode)
  const [simGenre, setSimGenre] = useState<string>("");
  const [simMsg, setSimMsg] = useState<string>("");
  const [simBusy, setSimBusy] = useState(false);

  // "Scan sheet music" (scan mode)
  const [scanMsg, setScanMsg] = useState<string>("");
  const [scanBusy, setScanBusy] = useState(false);

  const activeRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.getBlocks()
      .then((bs) => {
        const playable = bs.filter((b) => b.has_preview);
        setBlocks(playable);
        if (playable.length && !name) setName(playable[0].name);
      })
      .catch((e) => setErr(String(e)));
    api.getPresets().then((ps) => {
      setPresets(ps);
      if (ps.length) setSimGenre(ps[0].id);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Block mode: load score + audio for the selected block.
  useEffect(() => {
    if (mode !== "block" || !name) return;
    setLoading(true); setScore(null); setErr(""); setT(0);
    const block = blocks.find((b) => b.name === name);
    if (block) setAudioSrc(api.mediaUrl(block.audio_url));
    api.getScoreData(name)
      .then((s) => { setScore(s); setProgression([]); })
      .catch((e) => setErr(String(e)))
      .finally(() => setLoading(false));
  }, [mode, name, blocks]);

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
            setName(hit ? hit.name : b);
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

  useEffect(() => {
    activeRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [activeSpanIdx]);

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
          <select value={name} onChange={(e) => setName(e.target.value)}>
            {blocks.length === 0 && <option value="">No playable blocks</option>}
            {blocks.map((b) => (
              <option key={b.name} value={b.name}>{b.name}</option>
            ))}
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

      {err && <div className="practice-err">{err}</div>}
      {mode === "scan" && scanMsg && <div className="practice-hint">{scanMsg}</div>}
      {mode === "scan" && !score && !scanMsg && (
        <div className="practice-hint">Upload a clear photo or scan of printed sheet music. Recognition takes a minute or two and works best on clean, well-lit pages.</div>
      )}
      {loading && <div className="practice-hint">{mode === "upload" ? "Listening & detecting chords…" : "Analyzing chords…"}</div>}

      {score && (
        <>
          {audioSrc && (
            <audio
              src={audioSrc}
              controls
              onTimeUpdate={(e) => setT(e.currentTarget.currentTime)}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              style={{ width: "100%" }}
            />
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

          <div className="now-playing">
            <div className="np-meta">
              <span className="np-key">{score.key} {score.scale}</span>
              <span className="np-sec">{activeSection?.label || ""}</span>
              <span className="np-tempo">{Math.round(score.tempo)} BPM</span>
            </div>
            <div className="np-chords">
              <div className="np-current">
                <div className="np-big">{active ? label(active, notation) : "—"}</div>
                {notation !== "chord" && active && active.symbol !== "N.C." && (
                  <div className="np-alt">{active.symbol}</div>
                )}
              </div>
              <div className="np-count">
                {playing && beatsToNext != null ? `${beatsToNext}` : "·"}
                <span>beats</span>
              </div>
              <div className="np-next">
                <div className="np-next-label">next</div>
                <div className="np-next-chord">{next ? label(next, notation) : "—"}</div>
              </div>
            </div>
          </div>

          {active && active.root && (
            <ChordDiagram root={active.root} quality={active.quality || "maj"} />
          )}

          <div className="chart">
            {score.sections.length > 0
              ? score.sections.map((sec) => (
                  <div key={`${sec.label}-${sec.start_bar}`} className="chart-section">
                    <div className="chart-section-label">{sec.label}</div>
                    <div className="chart-grid">
                      {score.chord_spans
                        .filter((s) => s.start_bar >= sec.start_bar && s.start_bar <= sec.end_bar)
                        .map((s) => (
                          <Cell key={s.start_bar} span={s} notation={notation}
                            active={s === active} cellRef={s === active ? activeRef : undefined} />
                        ))}
                    </div>
                  </div>
                ))
              : (
                <div className="chart-grid">
                  {score.chord_spans.map((s) => (
                    <Cell key={s.start_bar} span={s} notation={notation}
                      active={s === active} cellRef={s === active ? activeRef : undefined} />
                  ))}
                </div>
              )}
          </div>
        </>
      )}
    </div>
  );
}

function Cell({
  span, notation, active, cellRef,
}: {
  span: ChordSpan;
  notation: Notation;
  active: boolean;
  cellRef?: React.RefObject<HTMLDivElement | null>;
}) {
  const bars = span.end_bar - span.start_bar + 1;
  return (
    <div ref={cellRef} className={`chart-cell${active ? " active" : ""}`} data-bars={bars}>
      <div className="cell-chord">{label(span, notation)}</div>
      {bars > 1 && <div className="cell-bars">{bars} bars</div>}
    </div>
  );
}
