import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { BlockSpec, Family, GenerateBody, Preset, SongPlan } from "../types";
import {
  EMPTY_SESSION, type SMsg, type SVersion, type SectionEdit, type Session, laneMap, loadSession, saveSession,
  titleFrom, withSectionEdit,
} from "../session";
import SessionView from "./SessionView";
import TimelineView from "./TimelineView";
import GenerateScreen from "./GenerateScreen";
import ComposeScreen from "./ComposeScreen";

export type CreateMode = "session" | "timeline" | "advanced" | "blocks";

/**
 * Create = one song workspace. You describe the song in a thread (Session),
 * hear v1, say what to change and hear v2…; the Timeline shows the same song
 * section by section. The full Generate form ("Advanced form") and the
 * block builder ("Blocks", the old Compose screen) live here too. Every mode
 * stays mounted so switching never loses work.
 */
export default function CreateScreen({
  active, mode, setMode, editSpec, onSpecConsumed, onEditInGenerate,
}: {
  active: boolean;
  mode: CreateMode;
  setMode: (m: CreateMode) => void;
  editSpec: BlockSpec | null;
  onSpecConsumed: () => void;
  onEditInGenerate: (spec: BlockSpec) => void;
}) {
  const [session, setSession] = useState<Session>(loadSession);
  const [busy, setBusy] = useState(false);
  const [presets, setPresets] = useState<Preset[]>([]);
  const [families, setFamilies] = useState<Family[]>([]);
  const [arrOpts, setArrOpts] = useState<api.ArrangementOptions | null>(null);
  const [selected, setSelected] = useState<number | null>(null);   // version shown in the timeline
  const [advancedPlan, setAdvancedPlan] = useState<SongPlan | null>(null);
  const [blocksReq, setBlocksReq] = useState<{ title: string; blocks: string[] } | null>(null);
  const ids = useRef(0);
  const sref = useRef(session);
  sref.current = session;
  const nextN = useRef(0);
  // The next version number (unique even while state updates are in flight).
  function allocN() {
    const maxN = sref.current.versions.reduce((m, v) => Math.max(m, v.n), 0);
    nextN.current = Math.max(nextN.current, maxN) + 1;
    return nextN.current;
  }

  useEffect(() => { saveSession(session); }, [session]);
  useEffect(() => {
    api.getPresets().then(setPresets).catch(() => {});
    api.getInstruments().then(setFamilies).catch(() => {});
    api.describeOptions().then((o) => setArrOpts(o.arrangement_variants)).catch(() => {});
  }, []);

  // Versions still generating when the page was closed: pick their jobs back up.
  useEffect(() => {
    for (const v of session.versions) {
      if (v.status === "running" && v.jobId) follow(v.n, v.jobId);
      else if (v.status === "running") patchVersion(v.n, { status: "error", error: "Interrupted" });
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const newId = () => `${Date.now().toString(36)}-${ids.current++}`;
  const patchVersion = (n: number, p: Partial<SVersion>) =>
    setSession((s) => ({ ...s, versions: s.versions.map((v) => (v.n === n ? { ...v, ...p } : v)) }));
  const addMsg = (m: Omit<SMsg, "id">) => {
    const id = newId();
    setSession((s) => ({ ...s, msgs: [...s.msgs, { ...m, id }] }));
    return id;
  };
  const patchMsg = (id: string, p: Partial<SMsg>) =>
    setSession((s) => ({ ...s, msgs: s.msgs.map((m) => (m.id === id ? { ...m, ...p } : m)) }));

  const latest = session.versions[session.versions.length - 1];
  const shownN = selected ?? latest?.n ?? null;
  const shown = session.versions.find((v) => v.n === shownN) ?? latest;

  const defaultBand = (genre: string) => presets.find((p) => p.id === genre)?.default_instruments ?? [];
  const lanes = useMemo(() => laneMap(families), [families]);

  // Follow a generation job into its version.
  async function follow(n: number, jobId: string) {
    try {
      const job = await api.pollJob(jobId, (j) => patchVersion(n, { progress: j.progress, message: j.message || j.status }));
      if (job.status === "error" || !job.result) {
        patchVersion(n, { status: "error", error: job.error || "Generation failed" });
        return;
      }
      const result = job.result;
      // Keep the seed: later versions change only what you asked for.
      setSession((s) => ({
        ...s,
        versions: s.versions.map((v) => (v.n === n
          ? { ...v, status: "done", progress: 1, result, plan: { ...v.plan, seed: v.plan.seed ?? result.seed } }
          : v)),
      }));
    } catch (e) {
      patchVersion(n, { status: "error", error: String(e).includes("Unknown job") ? "Interrupted (the server restarted)" : String(e) });
    }
  }

  // Start a new version from a plan; resolves when it's done (or failed).
  async function makeVersion(plan: SongPlan, n: number) {
    setSession((s) => ({
      ...s, versions: [...s.versions, { n, plan, jobId: null, status: "running", progress: 0, message: "Starting…" }],
    }));
    setSelected(null);
    const body: GenerateBody = {
      ...plan,
      instruments: plan.instruments ?? [],
      sections: plan.sections ?? [],
      with_pdf: false, with_stems: false, master_preset: "default",
    };
    try {
      const { job_id } = await api.generate(body);
      patchVersion(n, { jobId: job_id });
      await follow(n, job_id);
    } catch (e) {
      patchVersion(n, { status: "error", error: String(e) });
    }
  }

  // The plan a revision starts from: the version on screen (with its seed).
  function basePlan(): SongPlan | null {
    const v = shown ?? latest;
    if (!v) return null;
    return { ...v.plan, ...(v.plan.seed == null && v.result ? { seed: v.result.seed } : {}) };
  }

  async function send(text: string) {
    const t = text.trim();
    if (!t || busy) return;
    setBusy(true);
    addMsg({ role: "user", text: t });
    const pid = addMsg({ role: "app", kind: "pending", text: "Reading…" });
    try {
      const base = basePlan();
      if (!base) {
        const r = await api.describeSong(t, (m) => patchMsg(pid, { text: m }));
        setSession((s) => ({ ...s, title: s.title || titleFrom(t), interpreter: r.interpreter }));
        const n = allocN();
        patchMsg(pid, { kind: "describe", text: r.summary, chips: r.understood, notes: r.notes,
          interpreter: r.interpreter, version: n });
        await makeVersion(r.plan, n);
      } else {
        const r = await api.reviseSong(base, t, (m) => patchMsg(pid, { text: m }));
        setSession((s) => ({ ...s, interpreter: r.interpreter }));
        const changes = r.changes ?? [];
        if (!changes.length) {
          patchMsg(pid, { kind: "revise", text: r.summary, changes: [], notes: r.notes, interpreter: r.interpreter });
        } else {
          const n = allocN();
          patchMsg(pid, { kind: "revise", text: r.summary, changes, notes: r.notes, interpreter: r.interpreter, version: n });
          await makeVersion(base.seed != null ? { ...r.plan, seed: base.seed } : r.plan, n);
        }
      }
    } catch (e) {
      patchMsg(pid, { kind: "error", text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  // Timeline: regenerate one section with its new options, same seed.
  async function regenerateSection(role: string, label: string, edit: SectionEdit, changes: string[]) {
    const base = basePlan();
    if (!base || busy) return;
    setBusy(true);
    const plan = withSectionEdit(base, role, edit, arrOpts, defaultBand(base.genre));
    const n = allocN();
    addMsg({ role: "user", text: `Regenerate the ${label.toLowerCase()}` });
    addMsg({ role: "app", kind: "section", changes, version: n });
    try { await makeVersion(plan, n); } finally { setBusy(false); }
  }

  async function saveVersion(v: SVersion): Promise<string> {
    if (!v.jobId) throw new Error("This version has no audio");
    const name = `${session.title || "Song"} v${v.n}`;
    const r = await api.saveBlockFromJob(v.jobId, name);
    await api.addToLibrary(r.name, { title: name });
    patchVersion(v.n, { savedAs: r.name });
    return r.name;
  }

  // Timeline → Add block: the song's sections as blocks, the chosen block
  // inserted after the selected section, opened in Blocks to render/save.
  async function addBlock(v: SVersion, afterIndex: number, block: string) {
    if (!v.jobId) throw new Error("This version has no audio");
    const r = await api.splitJob(v.jobId, `${session.title || "Song"} v${v.n}`);
    const names = [...r.section_blocks];
    names.splice(Math.min(afterIndex + 1, names.length), 0, block);
    setBlocksReq({ title: `${session.title || "Song"} v${v.n} + ${block}`, blocks: names });
    setMode("blocks");
  }

  function newSession() {
    if (busy) return;
    if (session.msgs.length && !window.confirm("Start a new song? This thread will be cleared.")) return;
    setSession(EMPTY_SESSION);
    nextN.current = 0;
    setSelected(null);
    setMode("session");
  }

  function openAdvanced() {
    const p = basePlan();
    if (p) setAdvancedPlan(p);
    setMode("advanced");
  }

  // Edits from Blocks ("Edit in Generate") land on the Advanced form.
  useEffect(() => { if (editSpec) setMode("advanced"); }, [editSpec, setMode]);

  return (
    <>
      <div className={"tab-pane" + (mode === "session" ? "" : " hidden")}>
        <SessionView session={session} busy={busy} active={active && mode === "session"}
          onSend={send} onSave={saveVersion}
          onOpenTimeline={() => setMode("timeline")} onAdvanced={openAdvanced}
          onBlocks={() => setMode("blocks")} onNew={newSession} />
      </div>
      <div className={"tab-pane" + (mode === "timeline" ? "" : " hidden")}>
        <TimelineView session={session} version={shown} busy={busy} active={active && mode === "timeline"}
          lanes={lanes} arrOpts={arrOpts} defaultBand={defaultBand}
          genreName={(g) => presets.find((p) => p.id === g)?.name ?? g}
          onPickVersion={setSelected} onBack={() => setMode("session")} onSend={send}
          onRegenerate={regenerateSection} onAddBlock={addBlock} />
      </div>
      <div className={"tab-pane" + (mode === "advanced" ? "" : " hidden")}>
        <SubHeader title="Advanced form" onBack={() => setMode("session")} />
        <GenerateScreen initialSpec={editSpec} onSpecConsumed={onSpecConsumed}
          initialPlan={advancedPlan} onPlanConsumed={() => setAdvancedPlan(null)} />
      </div>
      <div className={"tab-pane" + (mode === "blocks" ? "" : " hidden")}>
        <SubHeader title="Blocks" onBack={() => setMode("session")} />
        <ComposeScreen active={active && mode === "blocks"} onEditInGenerate={onEditInGenerate}
          requestTimeline={blocksReq} onTimelineConsumed={() => setBlocksReq(null)} />
      </div>
    </>
  );
}

function SubHeader({ title, onBack }: { title: string; onBack: () => void }) {
  return (
    <header className="ws-header sub">
      <button type="button" className="ws-icon-btn" aria-label="Back to the session" onClick={onBack}>
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
      </button>
      <div className="ws-title">
        <div className="ws-name">{title}</div>
        <div className="ws-sub">Create</div>
      </div>
    </header>
  );
}
