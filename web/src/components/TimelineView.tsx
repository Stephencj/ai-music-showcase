import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { Block, SongPlan } from "../types";
import {
  LANES, type LaneId, SECTION_NAME, SECTION_SHORT, type SVersion, type SectionEdit, type Session, VARIANT_UI,
  bandOf, cellLabel, fmtTime, sectionStarts, sectionVariants, splitVariants, toggleVariant, variantLabel,
  withInstruments, withSectionLead, withSectionSilence, withoutInstruments, withoutLeads, withoutSection,
} from "../session";
import Composer from "./Composer";
import PickerField from "./PickerField";
import { drawPeaks } from "./Sparkline";

// Section options for engines without arrangement variants (energy / solo).
const PLAIN_OPTS: { id: string; label: string; edit: SectionEdit }[] = [
  { id: "sparse", label: "Sparse", edit: { energy: 0.7 } },
  { id: "big", label: "Big", edit: { energy: 1.3 } },
  { id: "solo", label: "Solo", edit: { feature_lead: true } },
];
const SHOWN_CHIPS = 4;
const CHIP_ORDER = Object.keys(VARIANT_UI);
const chipRank = (v: string) => (CHIP_ORDER.includes(v) ? CHIP_ORDER.indexOf(v) : CHIP_ORDER.length);

/** Create → Timeline: the song's sections across, its parts down. */
export default function TimelineView({
  session, version, busy, active, lanes, instNames, arrOpts, defaultBand, genreName,
  onPickVersion, onBack, onSend, onRegenerate, onEdit, onAddBlock,
}: {
  session: Session;
  version?: SVersion;
  busy: boolean;
  active: boolean;
  lanes: Record<string, LaneId>;
  instNames: Record<string, string>;
  arrOpts: api.ArrangementOptions | null;
  defaultBand: (genre: string) => string[];
  genreName: (genre: string) => string;
  onPickVersion: (n: number | null) => void;
  onBack: () => void;
  onSend: (text: string) => void;
  onRegenerate: (role: string, label: string, edit: SectionEdit, changes: string[]) => Promise<void>;
  /** A new version from the plan on screen, changed by ``edit``, same seed. */
  onEdit: (edit: (plan: SongPlan) => SongPlan, said: string, changes: string[]) => Promise<void>;
  onAddBlock: (v: SVersion, afterIndex: number, block: string) => Promise<void>;
}) {
  const [sel, setSel] = useState<number | null>(null);         // selected section index
  const [laneSel, setLaneSel] = useState<LaneId | null>(null); // lane whose name was tapped (whole-song options)
  const [lane, setLane] = useState<LaneId | null>(null);       // lane filter for the option chips
  const [draft, setDraft] = useState<SectionEdit | null>(null);
  const [more, setMore] = useState(false);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [addMsg, setAddMsg] = useState<string | null>(null);
  // Silencing / removing a part that has the tune: where to move it first.
  const [moving, setMoving] = useState<LaneId | null>(null);

  const plan = version?.plan;
  const result = version?.status === "done" ? version.result : undefined;
  // Sections of the version on screen (its rendered form), else the plan's.
  const sections = useMemo(() => result?.sections
    ?? (plan?.sections ?? []).map((r) => ({ role: r, label: SECTION_NAME[r] ?? r, bars: 4 })), [result, plan]);
  const totalBars = sections.reduce((s, x) => s + x.bars, 0) || 1;
  const starts = sections.reduce<number[]>((acc, _s, i) => [...acc, i ? acc[i - 1] + sections[i - 1].bars : 0], []);
  const funk = !!plan && !!arrOpts?.applies_to.includes(plan.genre);
  const band = plan ? bandOf(plan, defaultBand(plan.genre)) : [];
  const laneHas = (l: LaneId) => band.some((i) => lanes[i] === l);
  const laneIds = (l: LaneId) => band.filter((i) => lanes[i] === l);
  // Parts removed from the song (in an earlier version) stay as muted lanes,
  // so they can come back.
  const removedIds = (l: LaneId) => [...new Set(session.versions.flatMap((v) => bandOf(v.plan, defaultBand(v.plan.genre))))]
    .filter((i) => lanes[i] === l && !band.includes(i));
  const shownLanes = LANES.filter((l) => laneHas(l.id) || removedIds(l.id).length);
  const done = version?.status === "done";

  const secRole = sel != null ? sections[sel]?.role : undefined;
  const secName = secRole ? SECTION_NAME[secRole] ?? secRole : "";
  // Effective variants of the selected section, and the draft being edited.
  const curVs = plan && secRole ? sectionVariants(plan, secRole, arrOpts) : [];
  const draftVs = draft?.arrangement != null ? splitVariants(draft.arrangement) : curVs;
  const curOv = (plan && secRole && plan.section_overrides?.[secRole]) || {};

  useEffect(() => { setDraft(null); setMore(false); }, [sel, version?.n]);
  useEffect(() => { setMoving(null); }, [sel, lane, laneSel, version?.n]);
  useEffect(() => { if (sel != null) setLaneSel(null); }, [sel]);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (sel != null || laneSel) panelRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [sel, laneSel]);
  // (While a version composes it has no sections yet; keep the selection.)
  useEffect(() => { if (result && sel != null && sel >= sections.length) setSel(null); }, [result, sections.length, sel]);
  useEffect(() => { if (active) api.getBlocks().then(setBlocks).catch(() => {}); }, [active]);

  // ---- transport --------------------------------------------------------
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [loop, setLoop] = useState(false);
  const [wave, setWave] = useState<{ peaks: number[]; duration: number; section_starts: number[] } | null>(null);
  const audioUrl = result?.urls.audio ? api.mediaUrl(result.urls.audio) : undefined;
  const length = dur || wave?.duration || 0;
  // Where each section starts and ends, in seconds (the last runs to the end).
  const secStarts = useMemo(() => (result
    ? sectionStarts(sections.map((s) => s.bars), result.tempo, result.time_signature, wave?.section_starts)
    : starts.map((b) => (length * b) / totalBars)), [result, sections, wave, length]); // eslint-disable-line react-hooks/exhaustive-deps
  const secTime = (i: number) => secStarts[i] ?? 0;
  const secEnd = (i: number) => (i + 1 < sections.length ? secTime(i + 1) : Math.max(length, secTime(i)));
  useEffect(() => { setT(0); setPlaying(false); }, [audioUrl]);
  useEffect(() => {
    setWave(null);
    if (!done || !version?.jobId) return;
    let live = true;
    api.jobPeaks(version.jobId).then((w) => { if (live) setWave(w); }).catch(() => {});
    return () => { live = false; };
  }, [done, version?.jobId]);
  useEffect(() => { if (!active) audio.current?.pause(); }, [active]);
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const step = () => {
      const el = audio.current;
      if (el) {
        if (loop && sel != null && dur) {
          const a = secTime(sel), b = secEnd(sel);
          if (el.currentTime >= b - 0.02 || el.currentTime < a - 0.25) el.currentTime = a;
        }
        setT(el.currentTime);
      }
      raf = requestAnimationFrame(step);
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }); // eslint-disable-line react-hooks/exhaustive-deps
  function playPause() {
    const el = audio.current;
    if (!el) return;
    if (el.paused) {
      if (loop && sel != null && dur) el.currentTime = secTime(sel);
      el.play().catch(() => {});
    } else el.pause();
  }
  function seekTo(time: number, play = false) {
    const el = audio.current;
    if (!el || !length) return;
    el.currentTime = Math.max(0, Math.min(length, time));
    setT(el.currentTime);
    if (play && el.paused) el.play().catch(() => {});
  }
  function seek(e: React.MouseEvent<HTMLDivElement>) {
    const r = e.currentTarget.getBoundingClientRect();
    seekTo(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * length);
  }
  const frac = length ? t / length : 0;
  // Playhead: inside the section it's in (columns aren't exactly to scale).
  const secBtns = useRef<(HTMLButtonElement | null)[]>([]);
  const secFrac = (i: number, time: number) => {
    const a = secTime(i), b = secEnd(i);
    return b > a ? Math.max(0, Math.min(1, (time - a) / (b - a))) : 0;
  };
  const atSec = secStarts.reduce((k, s, i) => (s <= t ? i : k), 0);
  const btn = secBtns.current[atSec];
  const headLeft = btn ? btn.offsetLeft + btn.offsetWidth * secFrac(atSec, t) : 0;
  // The waveform under the section headers: tap or drag to scrub. A point
  // in a column is that far through that section.
  const scrubbing = useRef(false);
  function timeAtX(x: number) {
    const rects = secBtns.current.slice(0, sections.length).map((b) => b?.getBoundingClientRect());
    let i = rects.findIndex((r, k) => r && (k === rects.length - 1 || x < (r.right + (rects[k + 1]?.left ?? r.right)) / 2));
    if (i < 0) i = 0;
    const r = rects[i];
    if (!r) return 0;
    const f = Math.max(0, Math.min(1, (x - r.left) / r.width));
    return secTime(i) + f * (secEnd(i) - secTime(i));
  }
  function scrub(e: React.PointerEvent<HTMLDivElement>) {
    if (e.type === "pointerdown") {
      scrubbing.current = true;
      try { e.currentTarget.setPointerCapture(e.pointerId); } catch { /* not capturable */ }
    } else if (!scrubbing.current) return;
    seekTo(timeAtX(e.clientX));
  }
  const endScrub = () => { scrubbing.current = false; };
  const waveRow = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const row = waveRow.current;
    if (!row || !wave || !length) return;
    const draw = () => {
      const n = wave.peaks.length;
      row.querySelectorAll<HTMLCanvasElement>("canvas[data-sec]").forEach((cv) => {
        const i = Number(cv.dataset.sec);
        const a = Math.floor((secTime(i) / length) * n), b = Math.max(a + 1, Math.floor((secEnd(i) / length) * n));
        const dpr = window.devicePixelRatio || 1;
        cv.width = Math.max(1, Math.round(cv.clientWidth * dpr));
        cv.height = Math.max(1, Math.round(cv.clientHeight * dpr));
        drawPeaks(cv, wave.peaks.slice(a, b), "#5b6080");
      });
    };
    draw();
    const ro = new ResizeObserver(draw);
    ro.observe(row);
    return () => ro.disconnect();
  }, [wave, length, secStarts, sections.length]); // eslint-disable-line react-hooks/exhaustive-deps

  // ---- section options ----------------------------------------------------
  const variantChips = funk
    ? (arrOpts?.variants ?? []).map((v) => v.name).filter((n) => !arrOpts?.expands?.[n])
      .sort((a, b) => chipRank(a) - chipRank(b))
      .filter((n) => !lane || VARIANT_UI[n]?.lane === lane)
    : [];
  const shownChips = more || lane ? variantChips : variantChips.slice(0, SHOWN_CHIPS);
  const plainOn = (id: string) => {
    const e = draft && ("energy" in draft || "feature_lead" in draft) ? { ...curOv, ...draft } : curOv;
    return id === "solo" ? !!e.feature_lead : id === "sparse" ? e.energy != null && e.energy < 0.85
      : e.energy != null && e.energy > 1.1;
  };
  function togglePlain(id: string) {
    const d = { ...(draft || {}) };
    if (id === "solo") d.feature_lead = !plainOn("solo");
    else d.energy = plainOn(id) ? null : PLAIN_OPTS.find((o) => o.id === id)!.edit.energy;
    setDraft(d);
  }
  const changes: string[] = [];
  if (secRole) {
    const add = draftVs.filter((v) => !curVs.includes(v)), rem = curVs.filter((v) => !draftVs.includes(v));
    if (add.length || rem.length) {
      changes.push(`${secName} arrangement: ` + [...add.map((v) => `+${v}`), ...rem.map((v) => `−${v}`)].join(", "));
    }
    if (draft && "energy" in draft && (draft.energy ?? null) !== (curOv.energy ?? null)) {
      changes.push(`${secName}: energy ${curOv.energy ?? "default"} → ${draft.energy ?? "default"}`);
    }
    if (draft && "feature_lead" in draft && !!draft.feature_lead !== !!curOv.feature_lead) {
      changes.push(`${secName}: ${draft.feature_lead ? "lead solo" : "no lead solo"}`);
    }
  }
  async function regenerate() {
    if (!secRole || !draft || !changes.length) return;
    const edit: SectionEdit = { ...draft };
    if (draft.arrangement != null) edit.arrangement = draftVs.join(",");
    await onRegenerate(secRole, secName, edit, changes);
  }
  // ---- silencing: a part everywhere, a part in this section, a section ----
  const laneName = (l: LaneId) => LANES.find((x) => x.id === l)?.name ?? l;
  const maskOf = (role: string) => plan?.section_overrides?.[role]?.instruments;
  const restsIn = (l: LaneId, role: string) => {
    const m = maskOf(role);
    return !!m?.length && laneHas(l) && !m.some((id) => lanes[id] === l);
  };
  // Where the arrangement itself leaves a part out (the render says who
  // played in each section; null = not known, e.g. still composing).
  const playsIn = (l: LaneId, i: number): boolean | null => {
    const p = result?.sections?.[i]?.plays;
    return p ? laneIds(l).some((id) => p.includes(id)) : null;
  };
  const idleIn = (l: LaneId, i: number) => laneHas(l) && playsIn(l, i) === false;
  const idleEvery = (l: LaneId, role: string) => {
    const at = sections.map((s, i) => (s.role === role ? i : -1)).filter((i) => i >= 0);
    return at.length > 0 && at.every((i) => idleIn(l, i));
  };
  // Sections (of a role, or all) where a part has the tune, and who else in
  // the band could carry it there (playing in that role, in its range).
  const tuneIn = (l: LaneId, role?: string) => (result?.sections ?? [])
    .filter((s) => (!role || s.role === role) && s.melody && laneIds(l).includes(s.melody));
  const moveTargets = (l: LaneId, role?: string) => {
    const secs = tuneIn(l, role);
    if (!secs.length) return [];
    return band.filter((id) => lanes[id] !== l
      && secs.every((s) => (s.melody_options ?? []).includes(id) && (!maskOf(s.role)?.length || maskOf(s.role)!.includes(id))));
  };
  const instName = (id: string) => instNames[id] ?? id.replace(/_/g, " ");
  const roleNames = (secs: { role: string }[]) => [...new Set(secs.map((s) => (SECTION_NAME[s.role] ?? s.role).toLowerCase()))]
    .join(" and ");
  const editable = !busy && done;
  const soundingLanes = shownLanes.filter((l) => laneHas(l.id)).length;
  /** Remove a part; ``moveTo``: who takes the tune where it had it
   *  (undefined: ask first when it has the tune; null: the arrangement picks). */
  async function removeLane(l: LaneId, moveTo?: string | null) {
    if (!plan) return;
    const ids = laneIds(l), name = laneName(l);
    const tuned = tuneIn(l);
    if (moveTo === undefined && tuned.length && moveTargets(l).length) { setMoving(l); return; }
    const roles = [...new Set(tuned.map((s) => s.role))];
    const dropped = withoutInstruments(plan, ids, arrOpts, defaultBand(plan.genre)).dropped;
    setLaneSel(null);
    await onEdit((p) => roles.reduce((q, r) => withSectionLead(q, r, moveTo ?? null),
      withoutInstruments(p, ids, arrOpts, defaultBand(p.genre)).plan),
    `Remove the ${name.toLowerCase()} from the song` + (moveTo ? `; the ${instName(moveTo).toLowerCase()} takes the tune` : ""),
    [`${name}: removed from the song`, ...dropped.map((v) => `Arrangement: −${variantLabel(v)} (needs ${name.toLowerCase()})`),
      ...(moveTo ? [`Tune (${roleNames(tuned)}): ${name.toLowerCase()} → ${instName(moveTo).toLowerCase()}`] : [])]);
  }
  async function restoreLane(l: LaneId) {
    const ids = removedIds(l), name = laneName(l);
    const moved = Object.values(plan?.section_overrides || {}).some((o) => o.lead);
    setLaneSel(null);
    // The tune goes back to whoever the arrangement gives it.
    await onEdit((p) => withoutLeads(withInstruments(p, ids, defaultBand(p.genre))),
      `Bring the ${name.toLowerCase()} back`, [`${name}: back in the song`, ...(moved ? ["Tune: back to its own parts"] : [])]);
  }
  /** Silence (or bring back) a part in this section's role; ``moveTo`` as
   *  for removeLane. */
  async function silenceHere(l: LaneId, silent: boolean, moveTo?: string | null) {
    if (!secRole) return;
    const ids = laneIds(l), name = laneName(l).toLowerCase(), sec = secName.toLowerCase();
    if (silent && moveTo === undefined && tuneIn(l, secRole).length && moveTargets(l, secRole).length) {
      setMoving(l);
      return;
    }
    // Bringing back the part the tune was moved off gives it the tune back.
    const back = !silent && !!curOv.lead && (result?.sections ?? [])
      .some((s) => s.role === secRole && !!s.melody_default && ids.includes(s.melody_default));
    await onEdit((p) => {
      const q = withSectionSilence(p, secRole, ids, silent, defaultBand(p.genre));
      return moveTo !== undefined || back ? withSectionLead(q, secRole, moveTo ?? null) : q;
    },
    silent ? `Silence the ${name} in the ${sec}` + (moveTo ? `; the ${instName(moveTo).toLowerCase()} takes the tune` : "")
      : `Bring the ${name} back in the ${sec}`,
    [`${secName}: ${name} ${silent ? "rests" : "plays again"}`,
      ...(moveTo ? [`${secName}: tune ${name} → ${instName(moveTo).toLowerCase()}`] : back ? [`${secName}: tune back to its own part`] : [])]);
  }
  /** Who should take the tune: a chip per band member that can, or none. */
  const moveRow = (l: LaneId, targets: string[], where: string, pick: (to: string | null) => void, none: string) => (
    <div className="ws-move" data-testid="move-tune">
      <div className="ws-panel-note">The {laneName(l).toLowerCase()} has the tune {where}. Move it to:</div>
      <div className="ws-opts">
        {targets.map((id) => (
          <button key={id} type="button" className="ws-opt" data-testid={`move-tune-${id}`} disabled={!editable}
            onClick={() => pick(id)}>{instName(id)}</button>
        ))}
        <button type="button" className="ws-opt" data-testid="move-tune-none" disabled={!editable}
          onClick={() => pick(null)}>{none}</button>
        <button type="button" className="ws-link" data-testid="move-tune-cancel" onClick={() => setMoving(null)}>Cancel</button>
      </div>
    </div>
  );
  async function removeSection(i: number) {
    const s = sections[i];
    if (!s) return;
    setSel(null);
    await onEdit((p) => withoutSection(p, i), `Remove the ${s.label.toLowerCase()}`,
      [`Removed the ${s.label.toLowerCase()} (bars ${starts[i] + 1}–${starts[i] + s.bars})`]);
  }
  function tapSection(i: number) {
    setSel(sel === i && !lane ? null : i);
    setLane(null);
    // While it plays, a section header also jumps there.
    if (playing) seekTo(secTime(i));
  }

  async function addBlock(name: string) {
    if (!version || sel == null || !name) return;
    setAddMsg("Splitting the song into section blocks…");
    try { await onAddBlock(version, sel, name); setAddMsg(null); }
    catch (e) { setAddMsg(`Error: ${e}`); }
  }

  const cols = `46px ${sections.map((s) => `minmax(44px, ${s.bars}fr)`).join(" ")}`;
  const info = result
    ? [genreName(plan?.genre ?? result.genre),
      `${Math.round(result.tempo)} BPM`, `${result.key} ${result.scale.replace(/_/g, " ")}`,
      dur ? fmtTime(dur) : null].filter(Boolean).join(" · ")
    : version?.status === "running" ? "Composing…" : "";

  return (
    <div className="ws-timeline" data-testid="timeline">
      <header className="ws-header">
        <button type="button" className="ws-icon-btn" aria-label="Back to the session" data-testid="timeline-back" onClick={onBack}>
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
        </button>
        <div className="ws-title">
          <div className="ws-name">{session.title || "New song"}</div>
          <div className="ws-sub" data-testid="timeline-info">{info}</div>
        </div>
        {version?.from != null && session.versions.some((v) => v.n === version.from) && (
          <button type="button" className="ws-pill" data-testid="timeline-undo"
            title={`Back to v${version.from}`} onClick={() => onPickVersion(version.from!)}>Undo</button>
        )}
        {session.versions.length > 0 && (
          <PickerField value={String(version?.n ?? "")} label="Version" fullWidth={false} className="ws-pill ws-vpick"
            options={[...session.versions].reverse().map((v) => ({
              id: String(v.n), label: `v${v.n}`,
              sub: v.status === "running" ? "composing…" : v.status === "error" ? "failed" : undefined,
            }))}
            onChange={(id) => onPickVersion(Number(id) === session.versions[session.versions.length - 1]?.n ? null : Number(id))} />
        )}
      </header>

      {!version && <div className="ws-empty"><div className="meta">Describe a song first — its timeline shows up here.</div></div>}

      {version && (
        <>
          <div className="ws-transport">
            <audio ref={audio} src={audioUrl} preload="metadata"
              onLoadedMetadata={(e) => setDur(e.currentTarget.duration || 0)}
              onPlay={() => setPlaying(true)} onPause={() => setPlaying(false)} onEnded={() => setPlaying(false)} />
            <button type="button" className="ws-play big" aria-label={playing ? "Pause" : "Play"}
              data-testid="timeline-play" disabled={!audioUrl} onClick={playPause}>
              {playing
                ? <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5h4v14H7zM13 5h4v14h-4z" /></svg>
                : <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M7 5v14l12-7z" /></svg>}
            </button>
            <div className="ws-tr-mid">
              <div className="ws-track seek" onClick={seek} data-testid="timeline-progress"><div style={{ width: `${frac * 100}%` }} /></div>
              <div className="ws-times"><span>{fmtTime(t)}</span><span>{fmtTime(dur)}</span></div>
            </div>
            <button type="button" className={"ws-icon-btn" + (loop ? " on" : "")} aria-label="Loop selected section"
              aria-pressed={loop} disabled={sel == null} onClick={() => setLoop((l) => !l)}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M17 2l4 4-4 4" /><path d="M3 11V9a3 3 0 0 1 3-3h15" /><path d="M7 22l-4-4 4-4" /><path d="M21 13v2a3 3 0 0 1-3 3H3" /></svg>
            </button>
          </div>
          {version.status === "running" && (
            <div className="ws-tl-status"><div className="progress"><div style={{ width: `${Math.round(version.progress * 100)}%` }} /></div>
              <div className="ws-player-msg">v{version.n}: {version.message || "Composing…"}</div></div>
          )}
          {version.status === "error" && <div className="error ws-tl-status">v{version.n}: {version.error}</div>}

          <div className="ws-grid-card">
            <div className="ws-grid" style={{ "--ws-cols": cols } as React.CSSProperties}>
              <div className="ws-row head">
                <span />
                {sections.map((s, i) => (
                  <button key={i} type="button" className={"ws-sec" + (sel === i ? " on" : "")}
                    ref={(el) => { secBtns.current[i] = el; }}
                    data-testid={`sec-${i}`} aria-pressed={sel === i} title={s.label}
                    onClick={() => tapSection(i)}>
                    {SECTION_SHORT[s.role] ?? s.label}
                  </button>
                ))}
              </div>
              {result && (
                <div className="ws-row ws-wave" ref={waveRow} data-testid="timeline-wave"
                  aria-label="Waveform: tap or drag to move the playhead"
                  onPointerDown={scrub} onPointerMove={scrub} onPointerUp={endScrub} onPointerCancel={endScrub}>
                  <span />
                  {sections.map((_s, i) => (
                    <div key={i} className="ws-wave-sec">
                      <canvas data-sec={i} />
                      {atSec >= i && t > 0 && <div className="ws-wave-played" style={{ width: `${atSec > i ? 100 : secFrac(i, t) * 100}%` }} />}
                    </div>
                  ))}
                </div>
              )}
              {shownLanes.map((l) => (
                <div key={l.id} className={"ws-row" + (laneHas(l.id) ? "" : " muted")} data-testid={`lane-${l.id}`}>
                  <button type="button" className={"ws-lane" + (laneSel === l.id ? " on" : "")}
                    data-testid={`lane-name-${l.id}`} aria-pressed={laneSel === l.id}
                    aria-label={`${l.name}${laneHas(l.id) ? "" : " (removed)"}: options for the whole song`}
                    onClick={() => { setLaneSel(laneSel === l.id ? null : l.id); setSel(null); setLane(null); }}>
                    {l.name}
                  </button>
                  {sections.map((s, i) => {
                    const vs = plan ? sectionVariants(plan, s.role, arrOpts) : [];
                    const rests = restsIn(l.id, s.role) || idleIn(l.id, i);
                    const label = plan && !rests ? cellLabel(l.id, s.role, vs, plan, laneHas, funk) : "";
                    const on = sel === i;
                    return (
                      <button key={i} type="button" data-testid={`cell-${l.id}-${i}`}
                        className={"ws-cell" + (label || rests ? "" : " off") + (rests ? " rest" : "") + (on ? " sel" : "") + (on && lane === l.id ? " lane" : "")}
                        style={label || rests ? { background: on ? l.hueOn : l.hue } : undefined}
                        aria-label={`${l.name}, ${s.label}: ${label || (rests ? "rests" : "sits out")}`}
                        onClick={() => { setSel(i); setLane(lane === l.id && sel === i ? null : l.id); }}>
                        {rests ? "rests" : label}
                      </button>
                    );
                  })}
                </div>
              ))}
              {length > 0 && btn && (
                <div className="ws-playhead" aria-hidden="true" data-testid="playhead" style={{ left: headLeft }} />
              )}
            </div>
          </div>

          {sel != null && secRole && (
            <div className="ws-panel" data-testid="section-panel" ref={panelRef}>
              <div className="ws-panel-h">
                <div className="ws-panel-t">{sections[sel].label} · bars {starts[sel] + 1}–{starts[sel] + sections[sel].bars}</div>
                <div className="ws-panel-hint">
                  {lane ? <button type="button" className="ws-link" onClick={() => setLane(null)}>
                    {LANES.find((x) => x.id === lane)?.name} only · show all</button> : funk ? "tap a lane to edit one part" : ""}
                </div>
              </div>
              <div className="ws-opts" data-testid="section-chips">
                {funk ? shownChips.map((n) => (
                  <button key={n} type="button" className={"ws-opt" + (draftVs.includes(n) ? " on" : "")}
                    aria-pressed={draftVs.includes(n)} data-testid={`opt-${n}`}
                    title={arrOpts?.variants.find((v) => v.name === n)?.description}
                    onClick={() => setDraft({ ...(draft || {}), arrangement: toggleVariant(draftVs, n, arrOpts).join(",") })}>
                    {variantLabel(n)}
                  </button>
                )) : PLAIN_OPTS.map((o) => (
                  <button key={o.id} type="button" className={"ws-opt" + (plainOn(o.id) ? " on" : "")}
                    aria-pressed={plainOn(o.id)} data-testid={`opt-${o.id}`} onClick={() => togglePlain(o.id)}>
                    {o.label}
                  </button>
                ))}
                {funk && !lane && variantChips.length > SHOWN_CHIPS && (
                  <button type="button" className="ws-opt" data-testid="opt-more" onClick={() => setMore((m) => !m)}>
                    {more ? "− less" : "+ more"}
                  </button>
                )}
              </div>
              {sections.filter((s) => s.role === secRole).length > 1 && (
                <div className="ws-panel-note">Applies to every {secName.toLowerCase()}.</div>
              )}
              <div className="ws-panel-btns">
                <button type="button" className="ws-primary" data-testid="regenerate-section"
                  disabled={busy || !changes.length || !version || version.status !== "done"} onClick={regenerate}>
                  Regenerate {secName.toLowerCase()}
                </button>
                <PickerField value="" placeholder="Add block" label={`Add a block after the ${secName.toLowerCase()}`}
                  fullWidth={false} className="ws-secondary" searchable disabled={busy || version.status !== "done"}
                  options={blocks.map((b) => ({ id: b.name, label: b.name,
                    sub: [b.bars ? `${b.bars} bars` : "", b.tempo ? `${Math.round(b.tempo)} BPM` : ""].filter(Boolean).join(" · ") }))}
                  onChange={addBlock} />
              </div>
              <div className="ws-actions">
                <button type="button" className="ws-act" data-testid="play-from-section" disabled={!audioUrl || !length}
                  onClick={() => seekTo(secTime(sel), true)}>▶ From here</button>
                {lane && laneHas(lane) && (restsIn(lane, secRole) || !idleEvery(lane, secRole) ? (
                  <button type="button" className={"ws-act" + (moving === lane ? " on" : "")} data-testid="silence-here"
                    disabled={!editable} onClick={() => silenceHere(lane, !restsIn(lane, secRole))}>
                    {restsIn(lane, secRole) ? `Bring ${laneName(lane).toLowerCase()} back here` : `Silence ${laneName(lane).toLowerCase()} here`}
                  </button>
                ) : (
                  // The arrangement already leaves it out here: nothing to silence.
                  <button type="button" className="ws-act" data-testid="silence-here" disabled>
                    {laneName(lane)} rests here
                  </button>
                ))}
                <button type="button" className="ws-act" data-testid="remove-section"
                  disabled={!editable || sections.length < 2} onClick={() => removeSection(sel)}>Remove section</button>
              </div>
              {moving && moving === lane && moveRow(moving, moveTargets(moving, secRole), `in the ${secName.toLowerCase()}`,
                (to) => silenceHere(moving, true, to), "Leave it out")}
              {addMsg && <div className={addMsg.startsWith("Error") ? "error" : "meta"}>{addMsg}</div>}
            </div>
          )}

          {laneSel && sel == null && (
            <div className="ws-panel" data-testid="lane-panel" ref={panelRef}>
              <div className="ws-panel-h">
                <div className="ws-panel-t">{laneName(laneSel)} · whole song</div>
                <div className="ws-panel-hint">{laneHas(laneSel) ? "tap a cell to silence one section" : "removed from this version"}</div>
              </div>
              <div className="ws-panel-btns">
                {laneHas(laneSel) ? (
                  <button type="button" className="ws-primary" data-testid="lane-remove"
                    disabled={!editable || soundingLanes < 2 || moving === laneSel} onClick={() => removeLane(laneSel)}>
                    Remove {laneName(laneSel).toLowerCase()} from the song
                  </button>
                ) : (
                  <button type="button" className="ws-primary" data-testid="lane-restore"
                    disabled={!editable} onClick={() => restoreLane(laneSel)}>
                    Bring {laneName(laneSel).toLowerCase()} back
                  </button>
                )}
              </div>
              {moving && moving === laneSel && moveRow(moving, moveTargets(moving), `in the ${roleNames(tuneIn(moving))}`,
                (to) => removeLane(moving, to), "Let the band choose")}
            </div>
          )}
        </>
      )}

      <Composer testid="timeline-input" label="What should change?" busy={busy}
        placeholder="What should change? e.g. bass is doing too much" voice={false}
        onSend={(t) => { onSend(t); }} />
    </div>
  );
}
