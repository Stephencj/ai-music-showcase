import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { Block } from "../types";
import {
  LANES, type LaneId, SECTION_NAME, SECTION_SHORT, type SVersion, type SectionEdit, type Session, VARIANT_UI,
  cellLabel, fmtTime, sectionVariants, splitVariants, toggleVariant, variantLabel,
} from "../session";
import Composer from "./Composer";
import PickerField from "./PickerField";

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
  session, version, busy, active, lanes, arrOpts, defaultBand, genreName,
  onPickVersion, onBack, onSend, onRegenerate, onAddBlock,
}: {
  session: Session;
  version?: SVersion;
  busy: boolean;
  active: boolean;
  lanes: Record<string, LaneId>;
  arrOpts: api.ArrangementOptions | null;
  defaultBand: (genre: string) => string[];
  genreName: (genre: string) => string;
  onPickVersion: (n: number | null) => void;
  onBack: () => void;
  onSend: (text: string) => void;
  onRegenerate: (role: string, label: string, edit: SectionEdit, changes: string[]) => Promise<void>;
  onAddBlock: (v: SVersion, afterIndex: number, block: string) => Promise<void>;
}) {
  const [sel, setSel] = useState<number | null>(null);         // selected section index
  const [lane, setLane] = useState<LaneId | null>(null);       // lane filter for the option chips
  const [draft, setDraft] = useState<SectionEdit | null>(null);
  const [more, setMore] = useState(false);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [addMsg, setAddMsg] = useState<string | null>(null);

  const plan = version?.plan;
  const result = version?.status === "done" ? version.result : undefined;
  // Sections of the version on screen (its rendered form), else the plan's.
  const sections = useMemo(() => result?.sections
    ?? (plan?.sections ?? []).map((r) => ({ role: r, label: SECTION_NAME[r] ?? r, bars: 4 })), [result, plan]);
  const totalBars = sections.reduce((s, x) => s + x.bars, 0) || 1;
  const starts = sections.reduce<number[]>((acc, _s, i) => [...acc, i ? acc[i - 1] + sections[i - 1].bars : 0], []);
  const funk = !!plan && !!arrOpts?.applies_to.includes(plan.genre);
  const band = plan ? (plan.instruments?.length ? plan.instruments : defaultBand(plan.genre)) : [];
  const laneHas = (l: LaneId) => band.some((i) => lanes[i] === l);
  const shownLanes = LANES.filter((l) => laneHas(l.id));

  const secRole = sel != null ? sections[sel]?.role : undefined;
  const secName = secRole ? SECTION_NAME[secRole] ?? secRole : "";
  // Effective variants of the selected section, and the draft being edited.
  const curVs = plan && secRole ? sectionVariants(plan, secRole, arrOpts) : [];
  const draftVs = draft?.arrangement != null ? splitVariants(draft.arrangement) : curVs;
  const curOv = (plan && secRole && plan.section_overrides?.[secRole]) || {};

  useEffect(() => { setDraft(null); setMore(false); }, [sel, version?.n]);
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (sel != null) panelRef.current?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [sel]);
  // (While a version composes it has no sections yet; keep the selection.)
  useEffect(() => { if (result && sel != null && sel >= sections.length) setSel(null); }, [result, sections.length, sel]);
  useEffect(() => { if (active) api.getBlocks().then(setBlocks).catch(() => {}); }, [active]);

  // ---- transport --------------------------------------------------------
  const audio = useRef<HTMLAudioElement>(null);
  const [playing, setPlaying] = useState(false);
  const [t, setT] = useState(0);
  const [dur, setDur] = useState(0);
  const [loop, setLoop] = useState(false);
  const audioUrl = result?.urls.audio ? api.mediaUrl(result.urls.audio) : undefined;
  const secTime = (i: number) => (dur * starts[i]) / totalBars;
  useEffect(() => { setT(0); setPlaying(false); }, [audioUrl]);
  useEffect(() => { if (!active) audio.current?.pause(); }, [active]);
  useEffect(() => {
    if (!playing) return;
    let raf = 0;
    const step = () => {
      const el = audio.current;
      if (el) {
        if (loop && sel != null && dur) {
          const a = secTime(sel), b = sel + 1 < sections.length ? secTime(sel + 1) : dur;
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
  function seek(e: React.MouseEvent<HTMLDivElement>) {
    const el = audio.current, r = e.currentTarget.getBoundingClientRect();
    if (!el || !dur) return;
    el.currentTime = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * dur;
    setT(el.currentTime);
  }
  const frac = dur ? t / dur : 0;
  // Playhead: inside the section it's in (columns aren't exactly to scale).
  const secBtns = useRef<(HTMLButtonElement | null)[]>([]);
  const atBar = frac * totalBars;
  const atSec = starts.reduce((k, b, i) => (b <= atBar ? i : k), 0);
  const btn = secBtns.current[atSec];
  const headLeft = btn ? btn.offsetLeft + btn.offsetWidth * Math.min(1, (atBar - starts[atSec]) / (sections[atSec]?.bars || 1)) : 0;

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
                    onClick={() => { setSel(sel === i && !lane ? null : i); setLane(null); }}>
                    {SECTION_SHORT[s.role] ?? s.label}
                  </button>
                ))}
              </div>
              {shownLanes.map((l) => (
                <div key={l.id} className="ws-row" data-testid={`lane-${l.id}`}>
                  <span className="ws-lane">{l.name}</span>
                  {sections.map((s, i) => {
                    const vs = plan ? sectionVariants(plan, s.role, arrOpts) : [];
                    const mask = plan?.section_overrides?.[s.role]?.instruments;
                    const inMask = !mask?.length || mask.some((id) => lanes[id] === l.id);
                    const label = plan && inMask ? cellLabel(l.id, s.role, vs, plan, laneHas, funk) : "";
                    const on = sel === i;
                    return (
                      <button key={i} type="button" data-testid={`cell-${l.id}-${i}`}
                        className={"ws-cell" + (label ? "" : " off") + (on ? " sel" : "") + (on && lane === l.id ? " lane" : "")}
                        style={label ? { background: on ? l.hueOn : l.hue } : undefined}
                        aria-label={`${l.name}, ${s.label}: ${label || "sits out"}`}
                        onClick={() => { setSel(i); setLane(lane === l.id && sel === i ? null : l.id); }}>
                        {label}
                      </button>
                    );
                  })}
                </div>
              ))}
              {dur > 0 && btn && (
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
              {addMsg && <div className={addMsg.startsWith("Error") ? "error" : "meta"}>{addMsg}</div>}
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
