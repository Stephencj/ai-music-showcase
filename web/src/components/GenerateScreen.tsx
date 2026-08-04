import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { BlockSpec, Family, GenerateBody, GenreFamily, Job, JobResult, Preset } from "../types";
import CircleOfFifths from "./CircleOfFifths";
import PickerField from "./PickerField";
import GenreWheel from "./GenreWheel";

const SCALES = [
  "major", "minor", "dorian", "phrygian", "lydian", "mixolydian", "locrian",
  "harmonic_minor", "melodic_minor", "pentatonic_major", "pentatonic_minor", "blues",
];
const SECTION_LABELS: Record<string, string> = {
  intro: "Intro", buildup: "Buildup", verse: "Verse", prechorus: "Pre-chorus",
  chorus: "Chorus", drop: "Drop", bridge: "Bridge", breakdown: "Breakdown",
  solo: "Solo", outro: "Outro",
};

// Mirror of the backend's relative-degree key resolution so the form can SHOW
// the key/mode a section will actually compose in (a funk section of a C-major
// song reads as D dorian — the ii — not C major).
const _NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
const _FLAT_TO_SHARP: Record<string, string> = {
  Db: "C#", Eb: "D#", Gb: "F#", Ab: "G#", Bb: "A#",
};
const _PARENT_OFFSET: Record<string, number> = {
  major: 0, ionian: 0, dorian: 2, phrygian: 4, lydian: 5, mixolydian: 7,
  minor: 9, aeolian: 9, natural_minor: 9, locrian: 11, harmonic_minor: 9,
  melodic_minor: 9, pentatonic_minor: 9, blues: 9, pentatonic_major: 0,
};
function _pc(k: string): number {
  const i = _NOTES.indexOf(_FLAT_TO_SHARP[k] || k);
  return i < 0 ? 0 : i;
}
function relativeDegreeKey(gKey: string, gScale: string, secScale: string): string {
  const parent = ((_pc(gKey) - (_PARENT_OFFSET[(gScale || "major").toLowerCase()] ?? 0)) % 12 + 12) % 12;
  const t = ((parent + (_PARENT_OFFSET[(secScale || "major").toLowerCase()] ?? 0)) % 12 + 12) % 12;
  return _NOTES[t];
}

// Short playing-style tags for a section's override (shown on the section row).
function overrideBadges(o: import("../types").SectionOverride | undefined): string[] {
  if (!o) return [];
  const tags: string[] = [];
  if (o.key) tags.push(`♪ ${o.key} ${(o.scale || "major").replace(/_/g, " ")}`);
  if (o.bars != null) tags.push(`${o.bars} bars`);
  if (o.tempo != null) tags.push(`${Math.round(o.tempo)} BPM`);
  if (o.feature_lead) tags.push("🎸 solo");
  if (o.energy != null) tags.push(o.energy < 0.85 ? "↓ sparse" : "↑ big");
  if (o.knobs?.drum_fill && o.knobs.drum_fill > 1) tags.push("fills");
  if (o.progression?.length) tags.push(`🎼 ${o.progression.join("-")}`);
  if (o.instruments?.length) tags.push(`🎛 ${o.instruments.length} instr`);
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
  const [genreFamilies, setGenreFamilies] = useState<GenreFamily[]>([]);   // genre wheel catalog
  const [showGenre, setShowGenre] = useState(false);
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

  // The current genre's display name + family colour (for the wheel trigger).
  const curGenre = useMemo(() => {
    for (const f of genreFamilies) {
      for (const g of f.genres) {
        if (g.id === presetId) return { name: g.name, color: f.color, family: f.family };
      }
    }
    return { name: preset?.name || presetId || "—", color: "#7c8aa5", family: "" };
  }, [genreFamilies, presetId, preset]);

  // Per-section "feel" options (the lighter section presets), grouped by family
  // and de-duplicated — used by the per-section preset picker.
  const sectionFeels = useMemo(() => {
    const seen = new Set<string>();
    const opts: { id: string; label: string; group: string }[] = [];
    for (const f of genreFamilies) {
      for (const g of f.genres) {
        if (seen.has(g.section)) continue;
        seen.add(g.section);
        opts.push({ id: g.section, label: g.name, group: f.family });
      }
    }
    return opts;
  }, [genreFamilies]);

  // Load presets/instruments/masters. If a block was opened via "Edit in
  // Generate", apply its exact spec here — synchronously, with the freshly
  // loaded presets/families — so the default-preset load can't clobber it.
  useEffect(() => {
    (async () => {
      try {
        const [p, fRaw, m, gen] = await Promise.all([
          api.getPresets(), api.getInstruments(), api.getMasterPresets(), api.getGenres(),
        ]);
        // Generation is instrumental — vocals are added later in Compose
        // (write lyrics → compose melody), so hide the vocal family here.
        const f = fRaw.filter((fam) => fam.family !== "vocal");
        setPresets(p); setFamilies(f); setMasters(m); setGenreFamilies(gen.families);
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

  // The key/mode a section will actually compose in: an explicit override, or
  // (for a section preset in a different mode) the relative degree of the song
  // key, or the song key itself.
  function secKeyInfo(role: string): { key: string; scale: string; src: "set" | "genre" | "song" } {
    const ov = sectionOverrides[role];
    if (ov?.key) return { key: ov.key, scale: ov.scale || "major", src: "set" };
    const pid = sectionPresets[role];
    if (pid) {
      const p = presets.find((x) => x.id === pid);
      if (p?.scale && p.scale !== scale) {
        return { key: relativeDegreeKey(key, scale, p.scale), scale: p.scale, src: "genre" };
      }
    }
    return { key, scale, src: "song" };
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
      <div className="gen-row">
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
        <h2>Output</h2>
        <label className="field"><span>Master preset</span>
          <PickerField value={master} label="Master preset" icon="🎚"
            options={masters.map((m) => ({ id: m, label: m }))} onChange={setMaster} />
        </label>
        <div className="chips">
          <button type="button" className={"chip" + (withPdf ? " on" : "")} onClick={() => setWithPdf(!withPdf)}>PDF score</button>
          <button type="button" className={"chip" + (withStems ? " on" : "")} onClick={() => setWithStems(!withStems)}>Stems</button>
        </div>
      </div>
      </div>

      <div className="gen-row">
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
        <h2>Genre</h2>
        <button type="button" className="genre-pick" onClick={() => setShowGenre(true)}
          title="Pick a genre on the wheel">
          <span className="genre-dot" style={{ background: curGenre.color }} />
          <span className="genre-name">{curGenre.name}</span>
          {curGenre.family && <span className="genre-fam">{curGenre.family}</span>}
          <span className="pf-caret">▾</span>
        </button>
        {showGenre && genreFamilies.length > 0 && (
          <GenreWheel families={genreFamilies} value={presetId}
            onChange={(id) => { const p = presets.find((x) => x.id === id); if (p) applyPreset(p); }}
            onClose={() => setShowGenre(false)} />
        )}
        {preset && (
          <div className="gen-genre-detail">
            {(preset.sections?.length ?? 0) > 0 && (
              <div className="gen-detail-block">
                <div className="gen-detail-label">Parts</div>
                <div className="gen-parts">
                  {preset.sections.map((s) => (
                    <span key={s.role} className="gen-part">{SECTION_LABELS[s.role] || s.role}</span>
                  ))}
                </div>
              </div>
            )}
            {(preset.progression?.length ?? 0) > 0 && (
              <div className="gen-detail-block">
                <div className="gen-detail-label">Chord progression</div>
                <div className="gen-prog">
                  {preset.progression!.map((r, i) => (
                    <span key={i} className="gen-chord">{r}</span>
                  ))}
                </div>
              </div>
            )}
          </div>
        )}
      </div>
      </div>

      <div className="gen-row">
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
                <button type="button"
                  className={"chip" + (on ? " on" : "")}
                  onClick={() => toggle(sections, s.role, setSections)}>
                  {SECTION_LABELS[s.role] || s.role}
                  {!s.native && <span className="dot">+</span>}
                </button>
                {on && (
                  <PickerField value={cur} label={`${SECTION_LABELS[s.role] || s.role} feel`}
                    icon="🎚" fullWidth={false} className="section-preset" searchable
                    options={[{ id: "", label: `Song default (${curGenre.name})` }, ...sectionFeels]}
                    onChange={(id) => setSectionPresets((prev) => {
                      const n = { ...prev };
                      if (id) n[s.role] = id; else delete n[s.role];
                      return n;
                    })} />
                )}
                {on && overrideBadges(sectionOverrides[s.role]).map((b) => (
                  <span key={b} className="section-badge">{b}</span>
                ))}
                {on && (() => { const ki = secKeyInfo(s.role); return ki.src === "genre" ? (
                  <span className="section-badge key" title="Key the section's genre lands on, relative to the song key">
                    ♪ {ki.key} {ki.scale.replace(/_/g, " ")}
                  </span>
                ) : null; })()}
                {on && (
                  <span className="sec-adv-wrap">
                  <button type="button" className={"sec-adv-btn" + (advRole === s.role ? " on" : "")}
                    data-testid={"sec-adv-" + s.role}
                    title="Key / mode / tempo / chords / instruments for this section"
                    onClick={() => setAdvRole(advRole === s.role ? null : s.role)}>⋯</button>
                  {advRole === s.role && (
                  <div className="section-adv">
                    {(() => { const ki = secKeyInfo(s.role); return (
                      <button type="button" className="keypick sm" onClick={() => setSecKeyRole(s.role)}
                        title={ki.src === "genre" ? "Auto-set from the section's genre — relative to the song key. Click to override." : "Section key"}>
                        ◷ {ki.key} {ki.scale.replace(/_/g, " ")}
                        {ki.src === "song" ? " · song" : ki.src === "genre" ? " · from genre" : ""}
                      </button>
                    ); })()}
                    <label className="sec-adv-tempo">Bars
                      <input type="number" min={1} max={64} placeholder="auto"
                        value={sectionOverrides[s.role]?.bars ?? ""}
                        onChange={(e) => setSecOv(s.role,
                          { bars: e.target.value ? Number(e.target.value) : null })} />
                    </label>
                    <label className="sec-adv-tempo">Tempo
                      <input type="number" min={40} max={240}
                        placeholder={`${Math.round(tempo)}`}
                        value={sectionOverrides[s.role]?.tempo ?? ""}
                        onChange={(e) => setSecOv(s.role,
                          { tempo: e.target.value ? Number(e.target.value) : null })} />
                    </label>
                    {/* Per-section chord progression (from the genre's pools + forms). */}
                    {(() => {
                      const pool = preset?.progressions?.sections?.[s.role] || [];
                      const variants = preset?.progressions?.variants || [];
                      const opts = [
                        ...pool.map((o) => ({ key: `p${o.index}`, symbols: o.symbols, name: "" })),
                        ...variants.map((v) => ({ key: `v:${v.name}`, symbols: v.symbols, name: v.name })),
                      ];
                      if (!opts.length) return null;
                      const curProg = (sectionOverrides[s.role]?.progression || []).join(" ");
                      return (
                        <label className="sec-adv-tempo" style={{ minWidth: 150 }}>Chords
                          <select value={curProg} data-testid={"sec-prog-" + s.role}
                            onChange={(e) => {
                              const found = opts.find((o) => o.symbols.join(" ") === e.target.value);
                              setSecOv(s.role, { progression: found ? found.symbols : null });
                            }}>
                            <option value="">Auto</option>
                            {opts.map((o) => (
                              <option key={o.key} value={o.symbols.join(" ")}>
                                {o.name ? o.name + ": " : ""}{o.symbols.join("-")}
                              </option>
                            ))}
                          </select>
                        </label>
                      );
                    })()}
                    {/* Per-section instrument subset — which enabled instruments play here. */}
                    {(() => {
                      const enabled = families.flatMap((f) => f.instruments)
                        .filter((i) => instruments.has(i.id));
                      if (enabled.length < 2) return null;
                      const sel = new Set(sectionOverrides[s.role]?.instruments || []);
                      const active = (id: string) => sel.size === 0 || sel.has(id);
                      return (
                        <div data-testid={"sec-plays-" + s.role}
                          style={{ display: "flex", flexWrap: "wrap", gap: 4,
                          alignItems: "center", flexBasis: "100%", marginTop: 2 }}>
                          <span className="meta" style={{ marginRight: 2 }}>Plays</span>
                          {enabled.map((i) => (
                            <button type="button" key={i.id}
                              className={"chip" + (active(i.id) ? " on" : "")}
                              style={{ fontSize: 11, padding: "2px 8px" }}
                              onClick={() => {
                                const base = sel.size ? new Set(sel)
                                  : new Set(enabled.map((x) => x.id));
                                base.has(i.id) ? base.delete(i.id) : base.add(i.id);
                                const arr = [...base];
                                setSecOv(s.role, {
                                  instruments: arr.length === enabled.length ? null : arr,
                                });
                              }}>
                              {i.label}
                            </button>
                          ))}
                        </div>
                      );
                    })()}
                    {(sectionOverrides[s.role]?.key || sectionOverrides[s.role]?.tempo != null
                      || sectionOverrides[s.role]?.bars != null
                      || sectionOverrides[s.role]?.progression
                      || sectionOverrides[s.role]?.instruments) && (
                      <button type="button" className="btn ghost sm" style={{ width: "auto" }}
                        onClick={() => setSecOv(s.role, { key: null, scale: null, tempo: null,
                          bars: null, progression: null, instruments: null })}>
                        Clear</button>
                    )}
                  </div>
                  )}
                  </span>
                )}
                {secKeyRole === s.role && (() => { const ki = secKeyInfo(s.role); return (
                  <CircleOfFifths tonic={ki.key} mode={ki.scale} sharps
                    options={SCALES.map((sc) => ({ id: sc, label: sc.replace(/_/g, " ") }))}
                    onTonic={(t) => setSecOv(s.role, { key: t, scale: ki.scale })}
                    onMode={(mo) => setSecOv(s.role, { key: ki.key, scale: mo })}
                    onClose={() => setSecKeyRole(null)} />
                ); })()}
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
