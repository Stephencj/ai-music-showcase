import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { BlockSpec, Family, GenerateBody, Preset, SongPlan } from "../types";
import {
  EMPTY_SESSION, type SMsg, type SVersion, type SectionEdit, type Session, forgetLegacySession, laneMap,
  loadCurrentId, mergeServer, saveCurrentId, takeLegacySession, titleFrom, withSectionEdit,
} from "../session";
import SessionView from "./SessionView";
import TimelineView from "./TimelineView";
import GenerateScreen from "./GenerateScreen";
import ComposeScreen from "./ComposeScreen";
import HistoryView from "./HistoryView";

export type CreateMode = "session" | "timeline" | "advanced" | "blocks" | "history";

// What the server keeps of a session: the thread without "Reading…"
// placeholders, and versions without their moment-to-moment progress.
function persistable(s: Session) {
  return {
    title: s.title, interpreter: s.interpreter,
    msgs: s.msgs.filter((m) => m.kind !== "pending"),
    versions: s.versions.map(({ progress: _p, message: _m, ...v }) => v),
  };
}

/**
 * Create = one song workspace. You describe the song in a thread (Session),
 * hear v1, say what to change and hear v2…; the Timeline shows the same song
 * section by section. The thread lives on the server: "New song" archives it
 * into History, where any past song reopens where you left off. The full
 * Generate form ("Advanced form") and the block builder ("Blocks", the old
 * Compose screen) live here too. Every mode stays mounted so switching never
 * loses work.
 */
export default function CreateScreen({
  active, mode, setMode, editSpec, onSpecConsumed, onEditInGenerate, openBlock, onOpenBlockConsumed, onPractice,
}: {
  active: boolean;
  mode: CreateMode;
  setMode: (m: CreateMode) => void;
  editSpec: BlockSpec | null;
  onSpecConsumed: () => void;
  onEditInGenerate: (spec: BlockSpec) => void;
  /** A block to open in the Timeline (Library / Practice → Open in Timeline). */
  openBlock: string | null;
  onOpenBlockConsumed: () => void;
  /** Practice a version's block (switches to the Practice tab). */
  onPractice: (block: string) => void;
}) {
  const [session, setSession] = useState<Session>(EMPTY_SESSION);
  const [loaded, setLoaded] = useState(false);
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
  // Which session the screen holds: bumped whenever another one opens, so
  // work for the previous one (a job finishing, a save) never lands here.
  const gen = useRef(0);
  const nextN = useRef(0);
  // The next version number (unique even while state updates are in flight).
  function allocN() {
    const maxN = sref.current.versions.reduce((m, v) => Math.max(m, v.n), 0);
    nextN.current = Math.max(nextN.current, maxN) + 1;
    return nextN.current;
  }

  // ---- the server copy -----------------------------------------------------
  const sync = useRef<{ timer?: ReturnType<typeof setTimeout>; creating?: Promise<string>; sent?: string }>({});
  // The open session's server id, creating it on the first message.
  function ensureId(): Promise<string> {
    const cur = sref.current;
    if (cur.id) return Promise.resolve(cur.id);
    if (!sync.current.creating) {
      const g = gen.current;
      const body = persistable(cur);
      sync.current.creating = api.createSession(body).then((srv) => {
        if (gen.current === g) {
          sync.current.sent = JSON.stringify(body);
          setSession((x) => mergeServer({ ...x, id: srv.id }, srv));
          sref.current = { ...sref.current, id: srv.id };
          saveCurrentId(srv.id);
        }
        return srv.id as string;
      }).finally(() => { sync.current.creating = undefined; });
    }
    return sync.current.creating;
  }
  async function persist() {
    const g = gen.current;
    const s = sref.current;
    if (!s.msgs.length && !s.id) return;
    const body = persistable(s);
    const sig = JSON.stringify(body);
    if (sig === sync.current.sent && s.id) return;
    try {
      const id = await ensureId();
      if (gen.current !== g) return;
      const srv = await api.updateSession(id, body);
      sync.current.sent = sig;
      if (gen.current === g) setSession((x) => mergeServer(x, srv));
    } catch { /* offline: the next change tries again */ }
  }
  async function flush() {
    clearTimeout(sync.current.timer);
    sync.current.timer = undefined;
    await persist();
  }
  // Save at most every 0.7 s (a composing version changes it constantly, so
  // waiting for a pause could wait the whole render).
  useEffect(() => {
    if (!loaded || sync.current.timer) return;
    sync.current.timer = setTimeout(() => { sync.current.timer = undefined; void persist(); }, 700);
  }, [session, loaded]); // eslint-disable-line react-hooks/exhaustive-deps

  // Open the session you had (or bring over a thread this browser kept
  // before sessions lived on the server).
  useEffect(() => {
    (async () => {
      try {
        const legacy = takeLegacySession();
        if (legacy) {
          const srv = await api.createSession({ ...persistable(legacy) });
          forgetLegacySession();
          show(srv);
        } else {
          const id = loadCurrentId();
          if (id) show(await api.getSession(id));
        }
      } catch {
        saveCurrentId(null);
      } finally {
        setLoaded(true);
      }
    })();
    api.getPresets().then(setPresets).catch(() => {});
    api.getInstruments().then(setFamilies).catch(() => {});
    api.describeOptions().then((o) => setArrOpts(o.arrangement_variants)).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Put a session on screen and pick up any versions still generating.
  function show(s: Session, version?: number | null) {
    gen.current++;
    clearTimeout(sync.current.timer);
    sync.current = { sent: JSON.stringify(persistable(s)) };
    sref.current = s;
    setSession(s);
    saveCurrentId(s.id);
    nextN.current = 0;
    const last = s.versions[s.versions.length - 1]?.n;
    setSelected(version != null && version !== last ? version : null);
    for (const v of s.versions) {
      if (v.status === "running" && v.jobId) void follow(v.n, v.jobId);
      else if (v.status === "running") patchVersion(v.n, { status: "error", error: "Interrupted" });
    }
  }

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

  // Follow a generation job into its version; once done the server saves it
  // as a block (the Practice pool) and caches its render.
  async function follow(n: number, jobId: string) {
    const g = gen.current;
    const live = () => gen.current === g;
    try {
      const job = await api.pollJob(jobId, (j) => {
        if (live()) patchVersion(n, { progress: j.progress, message: j.message || j.status });
      });
      if (!live()) return;
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
      await finalize(n, g);
    } catch (e) {
      if (live()) patchVersion(n, { status: "error", error: String(e).includes("Unknown job") ? "Interrupted (the server restarted)" : String(e) });
    }
  }
  async function finalize(n: number, g: number) {
    for (let tries = 0; tries < 3 && gen.current === g; tries++) {
      try {
        await flush();
        const id = await ensureId();
        const v = await api.finalizeVersion(id, n);
        if (gen.current !== g) return;
        if (v.block) {
          patchVersion(n, { block: v.block, seed: v.seed, savedAs: v.savedAs, audio: v.audio });
          return;
        }
      } catch { /* the server's own watcher finishes it */ }
      await new Promise((r) => setTimeout(r, 1500));
    }
  }

  // Start a new version from a plan; resolves when it's done (or failed).
  async function makeVersion(plan: SongPlan, n: number, from?: number) {
    setSession((s) => ({
      ...s, versions: [...s.versions, { n, plan, from, jobId: null, status: "running", progress: 0, message: "Starting…" }],
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
          await makeVersion(base.seed != null ? { ...r.plan, seed: base.seed } : r.plan, n, (shown ?? latest)?.n);
        }
      }
    } catch (e) {
      patchMsg(pid, { kind: "error", text: String(e) });
    } finally {
      setBusy(false);
    }
  }

  // Timeline edits: a new version from the plan on screen, same seed.
  async function editPlan(edit: (plan: SongPlan) => SongPlan, said: string, changes: string[]) {
    const base = basePlan();
    if (!base || busy) return;
    setBusy(true);
    const plan = edit(base);
    const n = allocN();
    addMsg({ role: "user", text: said });
    addMsg({ role: "app", kind: "section", changes, version: n });
    try { await makeVersion(plan, n, (shown ?? latest)?.n); } finally { setBusy(false); }
  }
  // Timeline: regenerate one section with its new options.
  const regenerateSection = (role: string, label: string, edit: SectionEdit, changes: string[]) =>
    editPlan((base) => withSectionEdit(base, role, edit, arrOpts, defaultBand(base.genre)),
      `Regenerate the ${label.toLowerCase()}`, changes);

  // Save to library: the version's block (already in Practice) joins the
  // library, linked to this session.
  async function saveVersion(v: SVersion): Promise<string> {
    const id = await ensureId();
    await flush();
    const r = await api.saveVersionToLibrary(id, v.n);
    patchVersion(v.n, { savedAs: r.version.savedAs, block: r.version.block });
    return r.entry.block_name;
  }

  // A version whose audio is gone: render it again from its plan + seed.
  async function renderAgain(v: SVersion) {
    const id = await ensureId();
    const nv = await api.renderVersion(id, v.n);
    patchVersion(v.n, { jobId: nv.jobId, status: nv.status, progress: 0, message: nv.message, audio: nv.audio,
      error: undefined });
    if (nv.status === "running" && nv.jobId) await follow(v.n, nv.jobId);
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

  // New song: the current thread is already in History; start a fresh one.
  async function newSession() {
    if (busy) return;
    await flush();
    show(EMPTY_SESSION);
    setMode("session");
  }

  // History → reopen a song exactly where you left off.
  async function openSession(id: string) {
    if (busy) return;
    if (id !== sref.current.id) {
      await flush();
      show(await api.getSession(id));
    }
    setMode("session");
  }

  // Library / Practice → Open in Timeline: the block's session (or a new one
  // whose v1 is the block), on the Timeline.
  useEffect(() => {
    if (!openBlock) return;
    onOpenBlockConsumed();
    (async () => {
      try {
        if (busy) throw new Error("Wait for the version that's composing to finish first.");
        const r = await api.sessionFromBlock(openBlock);
        await flush();
        show(r.session, r.version);
        setMode("timeline");
      } catch (e) {
        window.alert(String(e instanceof Error ? e.message : e).replace(/^\{"detail":"(.*)"\}$/, "$1"));
      }
    })();
  }, [openBlock]); // eslint-disable-line react-hooks/exhaustive-deps

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
          onSend={send} onSave={saveVersion} onPractice={(v) => v.block && onPractice(v.block)}
          onRender={renderAgain}
          onOpenTimeline={() => setMode("timeline")} onAdvanced={openAdvanced}
          onBlocks={() => setMode("blocks")} onNew={() => { void newSession(); }}
          onHistory={() => setMode("history")} />
      </div>
      <div className={"tab-pane" + (mode === "timeline" ? "" : " hidden")}>
        <TimelineView session={session} version={shown} busy={busy} active={active && mode === "timeline"}
          lanes={lanes} arrOpts={arrOpts} defaultBand={defaultBand}
          genreName={(g) => presets.find((p) => p.id === g)?.name ?? g}
          onPickVersion={setSelected} onBack={() => setMode("session")} onSend={send}
          onRegenerate={regenerateSection} onEdit={editPlan} onAddBlock={addBlock} />
      </div>
      <div className={"tab-pane" + (mode === "history" ? "" : " hidden")}>
        <SubHeader title="History" onBack={() => setMode("session")} />
        <HistoryView active={active && mode === "history"} currentId={session.id} busy={busy}
          onOpen={(id) => { void openSession(id); }}
          onDeleted={(id) => { if (id === sref.current.id) show(EMPTY_SESSION); }}
          onRenamed={(id, title) => { if (id === sref.current.id) setSession((s) => ({ ...s, title })); }} />
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
