import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { BlockSpec, Family, GenerateBody, Job, JobResult, Preset } from "../types";
import CircleOfFifths from "./CircleOfFifths";
import PickerField from "./PickerField";

const SCALES = [
  "major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "locrian",
  "harmonic_minor", "melodic_minor", "pentatonic_major", "pentatonic_minor", "blues",
];
const SECTION_LABELS: Record<string, string> = {
  intro: "Intro", verse: "Verse", chorus: "Chorus", bridge: "Bridge", outro: "Outro",
};

// Short playing-style tags for a section's override (shown on the section row).
function overrideBadges(o: import("../types").SectionOverride | undefined): string[] {
  if (!o) return [];
  const tags: string[] = [];
  if (o.key) tags.push(`♪ ${o.key} ${(o.scale || "major").replace(/_/g, " ")}`);
  if (o.tempo != null) tags.push(`${Math.round(o.tempo)} BPM`);
  if (o.feature_lead) tags.push("🎸 solo");
  if (o.energy != null) tags.push(o.energy < 0.85 ? "↓ sparse" : "↑ big");
  if (o.knobs?.drum_fill && o.knobs.drum_fill > 1) tags.push("fills");
  return tags;
}

export default function GenerateScreen({
  initialSpec,
  onSpecConsumed,
}: {
  initialSpec?: BlockSpec | null;
  onSpecConsumed?: () => void;
}) {
  const [presets, setPresets] = useState<Preset[]>([]);
  const [families, setFamilies] = useState<Family[]>([]);
  const [masters, setMasters] = useState<string[]>([]);
  const [loadErr, setLoadErr] = useState<string | null>(null);

  const [presetId, setPresetId] = useState("");
  const [key, setKey] = useState("C");
  const [scale, setScale] = useState("major");
  const [showKey, setShowKey] = useState(false);
  const [tempo, setTempo] = useState(120);
  const [seed, setSeed] = useState("");
  const [swing, setSwing] = useState<number | null>(null);
  const [sections, setSections] = useState<Set<string>>(new Set());
  const [sectionPresets, setSectionPresets] = useState<Record<string, string>>({});  // role → preset id
  const [sectionOverrides, setSectionOverrides] =
    useState<Record<string, import("../types").SectionOverride>>({});  // role → playing-style
  const [advRole, setAdvRole] = useState<string | null>(null);     // section whose key/tempo editor is open
  const [secKeyRole, setSecKeyRole] = useState<string | null>(null); // section whose circle-of-fifths is open
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

  // Natural-language "Describe your song" box → parses to a SongPlan that
  // pre-fills the form (default), or composes immediately.
  const [describeText, setDescribeText] = useState("");
  const [describing, setDescribing] = useState(false);
  const [plan, setPlan] = useState<import("../types").SongPlan | null>(null);
  const [describeErr, setDescribeErr] = useState<string | null>(null);
  const composeReq = useRef(false);

  const [blockName, setBlockName] = useState("");
  const [saveMsg, setSaveMsg] = useState<string | null>(null);
  const [splitMsg, setSplitMsg] = useState<string | null>(null);

  const preset = useMemo(() => presets.find((p) => p.id === presetId), [presets, presetId]);
  const specApplied = useRef(false);

  // Load presets/instruments/masters. If a block was opened via "Edit in
  // Generate", apply its exact spec here — synchronously, with the freshly
  // loaded presets/families — so the default-preset load can't clobber it.
  useEffect(() => {
    (async () => {
      try {
        const [p, fRaw, m] = await Promise.all([
          api.getPresets(), api.getInstruments(), api.getMasterPresets(),
        ]);
        // Generation is instrumental — vocals are added later in Compose
        // (write lyrics → compose melody), so hide the vocal family here.
        const f = fRaw.filter((fam) => fam.family !== "vocal");
        setPresets(p); setFamilies(f); setMasters(m);
        if (initialSpec && !specApplied.current) {
          specApplied.current = true;
          applySpec(initialSpec, p, f);
          onSpecConsumed?.();
        } else if (p.length) {
          applyPreset(p[0], f);
        }
      } catch (e) {
        setLoadErr(String(e));
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Safety net for when the spec arrives after presets are already loaded
  // (GenerateScreen already mounted). Applies exactly once.
  useEffect(() => {
    if (!initialSpec || !presets.length || specApplied.current) return;
    specApplied.current = true;
    applySpec(initialSpec, presets, families);
    onSpecConsumed?.();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialSpec, presets]);

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
    const def = (p.default_instruments?.length ? p.default_instruments : defaultTrio(fams))
      .filter((id) => id !== "vocal_lead" && id !== "vocal_harmony");  // instrumental-first
    const defSet = new Set(def);
    setInstruments(new Set(def));
    setOpenFams(new Set(
      fams.filter((f) => f.instruments.some((i) => defSet.has(i.id))).map((f) => f.family)
    ));
  }

  // Apply a saved block's spec to the form so regenerating reproduces it.
  // Vocals are dropped here — generation is instrumental; the vocal melody is
  // (re)composed from the lyrics in Compose.
  function applySpec(spec: BlockSpec, ps: Preset[] = presets, fams: Family[] = families) {
    const p = ps.find((x) => x.id === spec.genre);
    if (p) applyPreset(p, fams);          // sets genre + preset defaults first
    if (spec.key) setKey(spec.key);
    if (spec.scale) setScale(spec.scale);
    if (spec.tempo) setTempo(spec.tempo);
    setSeed(spec.seed != null ? String(spec.seed) : "");
    setSwing(spec.swing ?? null);
    if (spec.instruments?.length) {
      const ids = new Set(spec.instruments.filter((id) => id !== "vocal_lead" && id !== "vocal_harmony"));
      setInstruments(ids);
      setOpenFams(new Set(fams.filter((f) => f.instruments.some((i) => ids.has(i.id))).map((f) => f.family)));
    }
    if (spec.sections?.length) setSections(new Set(spec.sections.map((s) => s.role)));
    // Restore per-section presets (from the map, or recovered off the sections).
    const sp: Record<string, string> = { ...(spec.section_presets || {}) };
    for (const s of spec.sections || []) if (s.preset_id) sp[s.role] = s.preset_id;
    setSectionPresets(sp);
    setSectionOverrides({ ...(spec.section_overrides || {}) });
  }

  function toggle(set: Set<string>, v: string, setter: (s: Set<string>) => void) {
    const n = new Set(set);
    n.has(v) ? n.delete(v) : n.add(v);
    setter(n);
  }

  // Patch one section's override; null-valued keys are removed, and an empty
  // override drops the section entry entirely.
  function setSecOv(role: string, patch: Record<string, unknown>) {
    setSectionOverrides((prev) => {
      const cur: Record<string, unknown> = { ...(prev[role] || {}), ...patch };
      for (const k of Object.keys(patch)) if (patch[k] == null) delete cur[k];
      const n = { ...prev };
      if (Object.keys(cur).length) n[role] = cur as import("../types").SectionOverride;
      else delete n[role];
      return n;
    });
  }

  // Apply a parsed SongPlan onto the form: seed the preset's defaults, then
  // layer the plan's explicit overrides (key/scale/tempo/swing/per-section
  // presets) and merge any called-out instruments over the preset's defaults.
  function applyPlan(pl: import("../types").SongPlan) {
    const p = presets.find((x) => x.id === pl.genre);
    if (p) applyPreset(p);
    if (pl.key) setKey(pl.key);
    if (pl.scale) setScale(pl.scale);
    if (pl.tempo) setTempo(pl.tempo);
    if (pl.swing != null) setSwing(pl.swing);
    setSectionPresets(pl.section_presets || {});
    setSectionOverrides(pl.section_overrides || {});
    if (pl.instruments?.length) {
      setInstruments((prev) => {
        const n = new Set(prev);
        for (const id of pl.instruments) n.add(id);
        return n;
      });
      setOpenFams((prev) => {
        const n = new Set(prev);
        for (const f of families) {
          if (f.instruments.some((i) => pl.instruments.includes(i.id))) n.add(f.family);
        }
        return n;
      });
    }
  }

  async function runDescribe(compose: boolean) {
    const text = describeText.trim();
    if (!text) return;
    setDescribing(true); setDescribeErr(null);
    try {
      const pl = await api.parsePrompt(text);
      setPlan(pl);
      applyPlan(pl);
      // "Compose now": fire generation once the applied state has committed
      // (the effect below runs after this render flushes the setState calls).
      if (compose) composeReq.current = true;
    } catch (e) {
      setDescribeErr(String(e));
    } finally {
      setDescribing(false);
    }
  }

  // Compose-after-apply: when runDescribe(true) set the flag, the plan's state
  // is now committed, so kick off generation with the resolved form values.
  useEffect(() => {
    if (composeReq.current && preset && !busy) {
      composeReq.current = false;
      onGenerate();
    }
  });

  async function onGenerate() {
    if (!preset) return;
    setBusy(true); setErr(null); setResult(null);
    setSaveMsg(null); setSplitMsg(null);
    setProgress(0); setMessage("Starting…");
    try {
      const body: GenerateBody = {
        genre: preset.id, key, scale, tempo: Number(tempo),
        seed: seed.trim() ? Number(seed) : null,
        swing,
        instruments: [...instruments], sections: [...sections],
        section_presets: sectionPresets,
        section_overrides: sectionOverrides,
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
      <div className="card describe-card">
        <h2>✍️ Describe your song</h2>
        <div className="meta" style={{ marginBottom: 8 }}>
          Plain English — genre(s), key, tempo, sections, instruments. We fill the form so you can tweak before generating.
        </div>
        <textarea className="describe-input" rows={2} value={describeText}
          onChange={(e) => setDescribeText(e.target.value)}
          placeholder="e.g. a pop song with a funky verse and a big hip-hop chorus in G minor, ~95 bpm, add 808s" />
        <div className="describe-actions">
          <button className="btn" disabled={describing || !describeText.trim()}
            onClick={() => runDescribe(false)}>
            {describing ? "Reading…" : "✨ Fill the form"}
          </button>
          <button className="btn ghost" disabled={describing || !describeText.trim()}
            onClick={() => runDescribe(true)}>⚡ Compose now</button>
        </div>
        {describeErr && <div className="error" style={{ marginTop: 6 }}>{describeErr}</div>}
        {plan && (
          <div className="describe-report">
            <div className="dr-understood">
              {plan.understood.map((u, i) => <span key={i} className="dr-chip">{u}</span>)}
            </div>
            {plan.notes.map((n, i) => <div key={i} className="dr-note">ℹ {n}</div>)}
          </div>
        )}
      </div>

      <div className="card">
        <h2>Preset</h2>
        <PickerField value={presetId} label="Preset" placeholder="Pick a preset" icon="🎛" searchable
          options={presets.map((p) => ({ id: p.id, label: p.name }))}
          onChange={(id) => { const p = presets.find((x) => x.id === id); if (p) applyPreset(p); }} />
      </div>

      <div className="card">
        <h2>Song</h2>
        <div className="row">
          <label className="field"><span>Key / scale</span>
            <button type="button" className="keypick" onClick={() => setShowKey(true)}
              title="Pick the key on the circle of fifths">
              ◷ {key} {scale.replace(/_/g, " ")}
            </button>
          </label>
        </div>
        {showKey && (
          <CircleOfFifths tonic={key} mode={scale} sharps
            options={SCALES.map((s) => ({ id: s, label: s.replace(/_/g, " ") }))}
            onTonic={setKey} onMode={setScale} onClose={() => setShowKey(false)} />
        )}
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
        <div className="meta" style={{ marginBottom: 10 }}>
          Each section can use its own preset — mix genres in one song (e.g. a funk verse, a hip-hop chorus).
        </div>
        <div className="section-rows">
          {(preset?.sections || []).map((s) => {
            const on = sections.has(s.role);
            const cur = sectionPresets[s.role] || "";
            return (
              <div key={s.role} className={"section-row" + (on ? "" : " off")}>
                <button
                  className={"chip" + (on ? " on" : "")}
                  onClick={() => toggle(sections, s.role, setSections)}>
                  {SECTION_LABELS[s.role] || s.role}
                  {!s.native && <span className="dot">+</span>}
                </button>
                {on && (
                  <PickerField value={cur} label={`${SECTION_LABELS[s.role] || s.role} preset`}
                    icon="🎚" fullWidth={false} className="section-preset" searchable
                    options={[{ id: "", label: `Song default (${preset?.name || "—"})` },
                      ...presets.map((p) => ({ id: p.id, label: p.name }))]}
                    onChange={(id) => setSectionPresets((prev) => {
                      const n = { ...prev };
                      if (id) n[s.role] = id; else delete n[s.role];
                      return n;
                    })} />
                )}
                {on && overrideBadges(sectionOverrides[s.role]).map((b) => (
                  <span key={b} className="section-badge">{b}</span>
                ))}
                {on && (
                  <button className={"sec-adv-btn" + (advRole === s.role ? " on" : "")}
                    title="Key / mode / tempo for this section"
                    onClick={() => setAdvRole(advRole === s.role ? null : s.role)}>⋯</button>
                )}
                {on && advRole === s.role && (
                  <div className="section-adv">
                    <button type="button" className="keypick sm" onClick={() => setSecKeyRole(s.role)}>
                      ◷ {sectionOverrides[s.role]?.key || key}{" "}
                      {(sectionOverrides[s.role]?.scale || scale).replace(/_/g, " ")}
                      {sectionOverrides[s.role]?.key ? "" : " · song"}
                    </button>
                    <label className="sec-adv-tempo">Tempo
                      <input type="number" min={40} max={240}
                        placeholder={`${Math.round(tempo)}`}
                        value={sectionOverrides[s.role]?.tempo ?? ""}
                        onChange={(e) => setSecOv(s.role,
                          { tempo: e.target.value ? Number(e.target.value) : null })} />
                    </label>
                    {(sectionOverrides[s.role]?.key || sectionOverrides[s.role]?.tempo != null) && (
                      <button className="btn ghost sm" style={{ width: "auto" }}
                        onClick={() => setSecOv(s.role, { key: null, scale: null, tempo: null })}>
                        Clear</button>
                    )}
                  </div>
                )}
                {secKeyRole === s.role && (
                  <CircleOfFifths tonic={sectionOverrides[s.role]?.key || key}
                    mode={sectionOverrides[s.role]?.scale || scale} sharps
                    options={SCALES.map((sc) => ({ id: sc, label: sc.replace(/_/g, " ") }))}
                    onTonic={(t) => setSecOv(s.role, { key: t, scale: sectionOverrides[s.role]?.scale || scale })}
                    onMode={(mo) => setSecOv(s.role, { key: sectionOverrides[s.role]?.key || key, scale: mo })}
                    onClose={() => setSecKeyRole(null)} />
                )}
              </div>
            );
          })}
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
          <PickerField value={master} label="Master preset" icon="🎚"
            options={masters.map((m) => ({ id: m, label: m }))} onChange={setMaster} />
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

      <div className="action-bar">
        <div className="inner">
          <button className="btn" disabled={busy || !preset} onClick={onGenerate}>
            {busy ? "Generating…" : "🎲 Generate Song"}
          </button>
        </div>
      </div>
    </>
  );
}
