import { useEffect, useMemo, useState } from "react";
import * as api from "../api";
import type { Family, GenerateBody, Job, JobResult, Preset } from "../types";

const KEYS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const SCALES = [
  "major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "locrian",
  "harmonic_minor", "melodic_minor", "pentatonic_major", "pentatonic_minor", "blues",
];
const SECTION_LABELS: Record<string, string> = {
  intro: "Intro", verse: "Verse", chorus: "Chorus", bridge: "Bridge", outro: "Outro",
};

export default function GenerateScreen() {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [families, setFamilies] = useState<Family[]>([]);
  const [masters, setMasters] = useState<string[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [presetId, setPresetId] = useState("");
  const [key, setKey] = useState("C");
  const [scale, setScale] = useState("major");
  const [tempo, setTempo] = useState(120);
  const [seed, setSeed] = useState("");
  const [sections, setSections] = useState<Set<string>>(new Set());
  const [instruments, setInstruments] = useState<Set<string>>(new Set());
  const [openFams, setOpenFams] = useState<Set<string>>(new Set());
  const [master, setMaster] = useState("default");
  const [withPdf, setWithPdf] = useState(true);
  const [withStems, setWithStems] = useState(false);

  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState(0);
  const [message, setMessage] = useState("");
  const [result, setResult] = useState<JobResult | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);

  const [blockName, setBlockName] = useState("");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [splitMsg, setSplitMsg] = useState<string | null>(null);

  const preset = useMemo(() => presets.find((p) => p.id === presetId), [presets, presetId]);

  useEffect(() => {
    (async () => {
      try {
        const [p, f, m] = await Promise.all([
          api.getPresets(), api.getInstruments(), api.getMasterPresets(),
        ]);
        setPresets(p); setFamilies(f); setMasters(m);
        if (p.length) applyPreset(p[0], f);
      } catch (e) {
        setLoadErr(String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function defaultTrio(fams: Family[]): string[] {
    const ids = fams.flatMap((f) => f.instruments).filter((i) => i.default).map((i) => i.id);
    return ids.length ? ids : ["drum_kit", "electric_bass", "piano"];
  }

  function applyPreset(p: Preset, fams: Family[] = families) {
    setPresetId(p.id);
    setKey(p.key || "C");
    setScale(p.scale || "major");
    setTempo(p.tempo || 120);
    const native = p.sections.filter((s) => s.native).map((s) => s.role);
    setSections(new Set(native.length ? native : p.sections.map((s) => s.role)));
    const def = p.default_instruments?.length ? p.default_instruments : defaultTrio(fams);
    const defSet = new Set(def);
    setInstruments(new Set(def));
    setOpenFams(new Set(
      fams.filter((f) => f.instruments.some((i) => defSet.has(i.id))).map((f) => f.family)
    ));
  }

  function toggle(set: Set<string>, v: string, setter: (s: Set<string>) => void) {
    const n = new Set(set);
    n.has(v) ? n.delete(v) : n.add(v);
    setter(n);
  }

  async function onGenerate() {
    if (!preset) return;
    setBusy(true); setErr(null); setResult(null);
    setSaveMsg(null); setSplitMsg(null);
    setProgress(0); setMessage("Starting…");
    try {
      const body: GenerateBody = {
        genre: preset.id, key, scale, tempo: Number(tempo),
        seed: seed.trim() ? Number(seed) : null,
        instruments: [...instruments], sections: [...sections],
        with_pdf: withPdf, with_stems: withStems, master_preset: master,
      };
      const { job_id } = await api.generate(body);
      setJobId(job_id);
      const job: Job = await api.pollJob(job_id, (j) => {
        setProgress(j.progress);
        setMessage(j.message || j.status);
      });
      if (job.status === "error") setErr(job.error || "Generation failed");
      else if (job.result) {
        setResult(job.result);
        setBlockName(`${preset.name} ${job.result.seed}`);
      }
    } catch (e) {
      setErr(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function onSaveBlock() {
    if (!jobId || !blockName.trim()) return;
    setSaveMsg("Saving…");
    try {
      const r = await api.saveBlockFromJob(jobId, blockName.trim());
      setSaveMsg(`Saved block "${r.name}"`);
    } catch (e) {
      setSaveMsg(`Error: ${e}`);
    }
  }

  async function onSplit() {
    if (!jobId) return;
    setSplitMsg("Splitting…");
    try {
      const r = await api.splitJob(jobId);
      setSplitMsg(
        r.section_blocks.length
          ? `Created blocks: ${r.section_blocks.join(", ")}`
          : "No sections to split"
      );
    } catch (e) {
      setSplitMsg(`Error: ${e}`);
    }
  }

  if (loadErr) {
    return (
      <div className="card">
        <div className="error">Couldn't reach the engine: {loadErr}</div>
        <div className="meta" style={{ marginTop: 8 }}>
          Make sure the Python server is running (run.command), then reload.
        </div>
      </div>
    );
  }

  return (
    <>
      <div className="card">
        <h2>Preset</h2>
        <select
          value={presetId}
          onChange={(e) => {
            const p = presets.find((x) => x.id === e.target.value);
            if (p) applyPreset(p);
          }}
        >
          {presets.map((p) => (
            <option key={p.id} value={p.id}>{p.name}</option>
          ))}
        </select>
      </div>

      <div className="card">
        <h2>Song</h2>
        <div className="row">
          <label className="field"><span>Key</span>
            <select value={key} onChange={(e) => setKey(e.target.value)}>
              {KEYS.map((k) => <option key={k}>{k}</option>)}
            </select>
          </label>
          <label className="field"><span>Mode / scale</span>
            <select value={scale} onChange={(e) => setScale(e.target.value)}>
              {SCALES.map((s) => <option key={s} value={s}>{s.replace(/_/g, " ")}</option>)}
            </select>
          </label>
        </div>
        <div className="row">
          <label className="field"><span>Tempo (BPM)</span>
            <input type="number" min={40} max={240} value={tempo}
              onChange={(e) => setTempo(Number(e.target.value))} />
          </label>
          <label className="field"><span>Seed (blank = random)</span>
            <input type="text" inputMode="numeric" placeholder="random" value={seed}
              onChange={(e) => setSeed(e.target.value)} />
          </label>
        </div>
      </div>

      <div className="card">
        <h2>Sections to generate</h2>
        <div className="chips">
          {(preset?.sections || []).map((s) => (
            <button key={s.role}
              className={"chip" + (sections.has(s.role) ? " on" : "")}
              onClick={() => toggle(sections, s.role, setSections)}>
              {SECTION_LABELS[s.role] || s.role}
              {!s.native && <span className="dot">+</span>}
            </button>
          ))}
        </div>
      </div>

      <div className="card">
        <h2>Instruments</h2>
        {families.map((f) => {
          const on = f.instruments.filter((i) => instruments.has(i.id)).length;
          return (
            <details className="family" key={f.family} open={openFams.has(f.family)}
              onToggle={(e) => {
                const o = (e.target as HTMLDetailsElement).open;
                setOpenFams((prev) => {
                  const n = new Set(prev);
                  o ? n.add(f.family) : n.delete(f.family);
                  return n;
                });
              }}>
              <summary>{f.label}<span className="count">{on}/{f.instruments.length}</span></summary>
              <div className="chips">
                {f.instruments.map((i) => (
                  <button key={i.id}
                    className={"chip" + (instruments.has(i.id) ? " on" : "")}
                    onClick={() => toggle(instruments, i.id, setInstruments)}>
                    {i.label}
                  </button>
                ))}
              </div>
            </details>
          );
        })}
      </div>

      <div className="card">
        <h2>Output</h2>
        <label className="field"><span>Master preset</span>
          <select value={master} onChange={(e) => setMaster(e.target.value)}>
            {masters.map((m) => <option key={m}>{m}</option>)}
          </select>
        </label>
        <div className="chips">
          <button className={"chip" + (withPdf ? " on" : "")} onClick={() => setWithPdf(!withPdf)}>PDF score</button>
          <button className={"chip" + (withStems ? " on" : "")} onClick={() => setWithStems(!withStems)}>Stems</button>
        </div>
      </div>

      {(busy || result || err) && (
        <div className="card">
          <h2>Result</h2>
          {busy && (
            <>
              <div className="progress"><div style={{ width: `${Math.round(progress * 100)}%` }} /></div>
              <div className="progress-msg">{message}</div>
            </>
          )}
          {err && <div className="error">{err}</div>}
          {result && (
            <>
              {result.urls.audio && <audio controls src={api.mediaUrl(result.urls.audio)} />}
              <div className="section-pills">
                {result.sections.map((s, idx) => (
                  <span className="pill" key={idx}>{s.label} · {s.bars}b</span>
                ))}
              </div>
              <div className="meta">
                {result.key} {result.scale.replace(/_/g, " ")} · {result.tempo} BPM · {result.bars} bars · seed {result.seed}
              </div>
              <div className="links">
                {result.urls.midi && <a href={api.mediaUrl(result.urls.midi)} download>↓ MIDI</a>}
                {result.urls.pdf && <a href={api.mediaUrl(result.urls.pdf)} download>↓ PDF</a>}
                {result.urls.audio_hifi && <a href={api.mediaUrl(result.urls.audio_hifi)} download>↓ WAV (HQ)</a>}
              </div>

              <div style={{ marginTop: 14 }} className="row">
                <input type="text" value={blockName}
                  onChange={(e) => setBlockName(e.target.value)} placeholder="Block name" />
                <button className="btn secondary"
                  style={{ flex: "0 0 auto", width: "auto", padding: "12px 16px" }}
                  onClick={onSaveBlock}>Save as Block</button>
              </div>
              {saveMsg && <div className={saveMsg.startsWith("Error") ? "error" : "ok"} style={{ marginTop: 6 }}>{saveMsg}</div>}

              <button className="btn ghost" style={{ marginTop: 8 }} onClick={onSplit}>
                Split into section blocks ↪
              </button>
              {splitMsg && <div className={splitMsg.startsWith("Error") ? "error" : "ok"}>{splitMsg}</div>}

              {result.summary && (
                <details style={{ marginTop: 10 }}>
                  <summary className="meta">Composition detail</summary>
                  <div className="summary">{result.summary}</div>
                </details>
              )}
            </>
          )}
        </div>
      )}

      <div className="generate-bar">
        <div className="inner">
          <button className="btn" disabled={busy || !preset} onClick={onGenerate}>
            {busy ? "Generating…" : "🎲 Generate Song"}
          </button>
        </div>
      </div>
    </>
  );
}
