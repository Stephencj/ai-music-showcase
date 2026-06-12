import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { Block, ExplainData } from "../types";
import type { RollNote } from "./NotationRoll";
import PlayAlong from "./PlayAlong";
import MixingDesk, { type MixState, type TrackSettings, cleanMix } from "./MixingDesk";
import LiveMixer from "./LiveMixer";
import DressUp from "../dressup/DressUp";
import Performance from "../dressup/Performance";
import { type Member, imageBreakdown, normalizeMember } from "../dressup/wardrobe";

// The band-career shell: name a band, then progress along whichever ROLE you
// pick — Musician (play gigs, game or real), Producer (mix & master), or
// Stylist (lineup & wardrobe). The three are independent: none is required to
// advance another, you choose where you fit in. Songcraft × production × image
// × venue all multiply a gig's payoff. Career state lives in localStorage.

type Role = "musician" | "producer" | "stylist";

interface Band {
  name: string; fans: number; money: number; gigs: number;
  produced?: Record<string, number>;   // block name → production multiplier (Producer)
  members?: Member[];                   // the lineup (Stylist)
  image?: number;                       // styling → image multiplier (Stylist)
  role?: Role;                          // last-picked track focus
}
const KEY = "aimusic.band";

const ROLES: { id: Role; icon: string; name: string; blurb: string }[] = [
  { id: "musician", icon: "🎤", name: "Musician", blurb: "Play your songs at gigs — tap the rhythm game, or play for real on MIDI/mic. Casual jams open in Practice." },
  { id: "producer", icon: "🎛", name: "Producer", blurb: "Mix & master your songs on the desk, A/B live, and train your ears. A better mix earns more fans." },
  { id: "stylist", icon: "🎨", name: "Stylist", blurb: "Choose the band's members and dress them. A fuller, on-brand look is an image multiplier on every gig." },
];

const TIERS = [
  { name: "Garage", at: 0, mult: 1 },
  { name: "Open mic", at: 40, mult: 1.6 },
  { name: "Bar gig", at: 200, mult: 2.6 },
  { name: "Club", at: 1200, mult: 4.5 },
  { name: "Theater", at: 8000, mult: 8 },
  { name: "Festival", at: 40000, mult: 14 },
  { name: "Arena", at: 200000, mult: 24 },
];
function tierFor(fans: number) {
  let t = TIERS[0], next = null as (typeof TIERS)[0] | null;
  for (let i = 0; i < TIERS.length; i++) {
    if (fans >= TIERS[i].at) { t = TIERS[i]; next = TIERS[i + 1] ?? null; }
  }
  return { tier: t, next };
}

// Songcraft 0.6–2.4: rewards form, harmonic devices, genre-mixing, modulation.
function songcraft(e: ExplainData): number {
  const sections = e.sections.length;
  const devices = new Set(e.sections.flatMap((s) => s.devices)).size;
  const progs = new Set(e.sections.map((s) => s.progression_name).filter(Boolean)).size;
  const feels = new Set(e.sections.map((s) => s.feel)).size;
  const keys = new Set(e.sections.map((s) => s.key_relation)).size;
  const s = 0.55 + sections * 0.035 + devices * 0.13 + progs * 0.07
    + (feels > 1 ? 0.3 : 0) + (keys > 1 ? 0.2 : 0);
  return Math.max(0.6, Math.min(2.4, Math.round(s * 100) / 100));
}

function loadBand(): Band | null {
  try {
    const b = JSON.parse(localStorage.getItem(KEY) || "null");
    if (b && Array.isArray(b.members)) b.members = b.members.map(normalizeMember);
    return b;
  } catch { return null; }
}

export default function BandScreen({ isActive, onWriteSong, onOpenPractice }: {
  isActive: boolean; onWriteSong: () => void; onOpenPractice?: (block: string) => void;
}) {
  const [band, setBand] = useState<Band | null>(loadBand);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [nameDraft, setNameDraft] = useState("");
  const [role, setRole] = useState<Role>(loadBand()?.role || "musician");
  const [gig, setGig] = useState<string | null>(null);     // block name being played
  const [produce, setProduce] = useState<string | null>(null);  // block being produced
  const [train, setTrain] = useState<string | null>(null);      // ear-training on a block
  const [live, setLive] = useState<string | null>(null);        // live-mixing a block
  const [stylist, setStylist] = useState(false);                // stylist studio open
  const [show, setShow] = useState(false);                      // watch the band perform

  useEffect(() => { if (band) localStorage.setItem(KEY, JSON.stringify(band)); }, [band]);
  useEffect(() => { if (isActive) api.getBlocks().then(setBlocks).catch(() => {}); }, [isActive]);

  const { tier, next } = tierFor(band?.fans ?? 0);
  const image = band?.image ?? 1;
  const pickRole = (r: Role) => { setRole(r); setBand((b) => b ? { ...b, role: r } : b); };

  const award = (gained: { fans: number; money: number }) => {
    setBand((b) => b ? { ...b, fans: b.fans + gained.fans, money: b.money + gained.money, gigs: b.gigs + 1 } : b);
  };

  if (!band) {
    return (
      <div className="card band-start">
        <h2>🎸 Start your band</h2>
        <div className="meta" style={{ marginBottom: 10 }}>
          Form a band, then pick your role — play the music, produce it, or style the band. Each path earns fans on its own.
        </div>
        <div className="row">
          <input type="text" value={nameDraft} placeholder="Band name"
            onChange={(e) => setNameDraft(e.target.value)} />
          <button className="btn secondary" style={{ flex: "0 0 auto", width: "auto", padding: "12px 18px" }}
            disabled={!nameDraft.trim()}
            onClick={() => setBand({ name: nameDraft.trim(), fans: 0, money: 0, gigs: 0 })}>
            Form band
          </button>
        </div>
      </div>
    );
  }

  const songsEmpty = blocks.length === 0;

  return (
    <>
      <div className="card band-dash">
        <div className="band-name">{band.name}</div>
        <div className="band-stats">
          <span><b>{band.fans.toLocaleString()}</b> fans</span>
          <span><b>${band.money.toLocaleString()}</b></span>
          <span><b>{band.gigs}</b> gigs</span>
          {image > 1 && <span className="band-tier">🎨 image ×{image.toFixed(2)}</span>}
          <span className="band-tier">🎪 {tier.name} (×{tier.mult})</span>
        </div>
        {next && (
          <div className="band-progress" title={`${next.at - band.fans} fans to ${next.name}`}>
            <div style={{ width: `${Math.min(100, Math.round((band.fans - tier.at) / (next.at - tier.at) * 100))}%` }} />
            <span>Next: {next.name} at {next.at.toLocaleString()} fans</span>
          </div>
        )}
        <button className="btn" style={{ marginTop: 12 }} onClick={onWriteSong}>✍️ Write a new song</button>
      </div>

      {/* Role picker — choose where you fit; none requires another to advance. */}
      <div className="role-picker">
        {ROLES.map((r) => (
          <button key={r.id} type="button"
            className={"role-card" + (role === r.id ? " on" : "")} onClick={() => pickRole(r.id)}>
            <span className="role-icon">{r.icon}</span>
            <span className="role-name">{r.name}</span>
            <span className="role-blurb">{r.blurb}</span>
          </button>
        ))}
      </div>

      {/* Stylist track lives on its own (not per-song). */}
      {role === "stylist" ? (
        <div className="card">
          <h2>Stylist · the look</h2>
          <div className="meta" style={{ marginBottom: 10 }}>
            Build your lineup and dress them. A fuller, on-brand band is an <b>image ×{image.toFixed(2)}</b> multiplier on every gig.
          </div>
          <div className="band-stylist-row">
            <div className="band-roster-mini">
              {(band.members || []).length === 0
                ? <span className="meta">No members yet.</span>
                : (band.members || []).map((m) => (
                  <span key={m.id} className="roster-mini-chip">{m.name} · {m.part}</span>
                ))}
            </div>
            <button className="btn secondary" style={{ width: "auto" }} onClick={() => setStylist(true)}>
              🎨 Open stylist
            </button>
          </div>
        </div>
      ) : (
        /* Musician + Producer act on songs. */
        <div className="card">
          <h2>Your songs</h2>
          {songsEmpty
            ? <div className="meta">No songs yet — write one in Generate, save it as a block, and it'll appear here.</div>
            : (
              <div className="band-songs">
                {blocks.map((b) => (
                  <div key={b.name} className="band-song">
                    <span className="band-song-name">{b.name}</span>
                    {role === "producer" ? (
                      <>
                        <button className="btn ghost sm" style={{ width: "auto" }}
                          onClick={() => setProduce(b.name)}>🎛 Produce</button>
                        <button className="btn ghost sm" style={{ width: "auto" }}
                          onClick={() => setLive(b.name)}>🎚 Live mix</button>
                        <button className="btn ghost sm" style={{ width: "auto" }}
                          onClick={() => setTrain(b.name)}>🎧 Ear training</button>
                      </>
                    ) : (
                      <>
                        <button className="btn ghost sm" style={{ width: "auto" }}
                          onClick={() => onOpenPractice?.(b.name)}>🎶 Casual (Practice)</button>
                        <button className="btn secondary sm" style={{ width: "auto" }}
                          onClick={() => setGig(b.name)}>🎤 Play gig</button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}
        </div>
      )}

      {gig && (
        <Gig blockName={gig} tierMult={tier.mult} production={(band.produced || {})[gig] || 1} image={image}
          onDone={(g) => { award(g); }}
          onClose={() => setGig(null)} />
      )}
      {produce && (
        <Produce blockName={produce} tierMult={tier.mult}
          onDone={(g) => { award(g); }}
          onProduced={(n, prod) => setBand((b) => b ? { ...b, produced: { ...(b.produced || {}), [n]: prod } } : b)}
          onClose={() => setProduce(null)} />
      )}
      {train && (
        <EarTraining blockName={train}
          onReward={(fans) => setBand((b) => b ? { ...b, fans: b.fans + fans } : b)}
          onClose={() => setTrain(null)} />
      )}
      {live && (
        <LiveMixer blockName={live}
          onBounced={(n, prod) => setBand((b) => b ? { ...b, produced: { ...(b.produced || {}), [n]: prod } } : b)}
          onClose={() => setLive(null)} />
      )}
      {stylist && (
        <DressUp members={band.members || []}
          onChange={(members) => setBand((b) => b ? { ...b, members, image: imageBreakdown(members).image } : b)}
          onPerform={() => setShow(true)}
          onClose={() => setStylist(false)} />
      )}
      {show && (
        <Performance members={band.members || []}
          onComplete={() => award({ fans: Math.round(20 * image * tier.mult), money: 0 })}
          onClose={() => setShow(false)} />
      )}
    </>
  );
}

// ── The producer role: the mixing desk + master → boost the song's appeal ────
const MASTER_DESC: Record<string, string> = {
  default: "balanced, broadcast-ready", loud: "hot & competitive (streaming)",
  cinematic: "wide, spacious, reverby", transparent: "minimal — keeps it natural",
};

function Produce({ blockName, tierMult, onDone, onProduced, onClose }: {
  blockName: string; tierMult: number;
  onDone: (g: { fans: number; money: number }) => void;
  onProduced: (name: string, production: number) => void;
  onClose: () => void;
}) {
  const [tracks, setTracks] = useState<string[]>([]);
  const [mix, setMix] = useState<MixState>({});
  const [masters, setMasters] = useState<string[]>([]);
  const [master, setMaster] = useState("default");
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ production: number; fans: number; money: number } | null>(null);
  const [audioBust, setAudioBust] = useState(0);

  useEffect(() => {
    api.getBlockNotes(blockName).then((d) => setTracks(d.tracks.map((t) => t.track))).catch(() => {});
    api.getMasterPresets().then(setMasters).catch(() => {});
  }, [blockName]);

  const run = async () => {
    setBusy(true);
    try {
      const r = await api.produceBlock(blockName, { master_preset: master, track_mix: cleanMix(mix) });
      const fans = Math.round(12 * r.production * tierMult);
      const money = Math.round(fans * 1.3);
      setResult({ production: r.production, fans, money });
      setAudioBust((n) => n + 1);
      onProduced(r.name, r.production);   // persist so future gigs pay more
      onDone({ fans, money });
    } finally { setBusy(false); }
  };

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="gig-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">🎛 Mixing desk · {blockName}</span>
          <button className="cof-close" onClick={onClose}>✕</button>
        </div>
        <MixingDesk tracks={tracks} mix={mix} onChange={setMix} />
        <div className="prod-section" style={{ marginTop: 10 }}>
          <h4>Master</h4>
          <div className="prod-masters">
            {masters.map((m) => (
              <button key={m} className={"prod-master" + (master === m ? " on" : "")} onClick={() => setMaster(m)}>
                <b>{m}</b><span>{MASTER_DESC[m] || ""}</span>
              </button>
            ))}
          </div>
        </div>
        <audio key={audioBust} src={api.blockAudioUrl(blockName) + (audioBust ? `?v=${audioBust}` : "")}
          controls style={{ width: "100%" }} />
        <button className="btn" style={{ marginTop: 10 }} disabled={busy} onClick={run}>
          {busy ? "Bouncing the mix…" : result ? "Re-mix" : "🎚 Bounce the mix"}
        </button>
        {result && (
          <div className="gig-payout">
            Production <b>×{result.production.toFixed(2)}</b> → streams roll in:
            <b> +{result.fans.toLocaleString()} fans</b>, +${result.money.toLocaleString()}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Ear training: a target mix is generated; match it on the desk by ear ──────
interface Move { track: string; ctrl: string; value: number; label: string; }

function makeTarget(tracks: string[]): { mix: MixState; moves: Move[] } {
  // 2 obvious, audible moves on distinct tracks (pseudo-random off the catalog).
  const pool = (t: string): Move[] => [
    { track: t, ctrl: "gain", value: 6, label: `Boost ${t} +6 dB` },
    { track: t, ctrl: "gain", value: -8, label: `Pull ${t} down 8 dB` },
    { track: t, ctrl: "reverb", value: 0.6, label: `Reverb on ${t}` },
    { track: t, ctrl: "high", value: 6, label: `Brighten ${t} (high +6)` },
    { track: t, ctrl: "low", value: 6, label: `Warm up ${t} (low +6)` },
    { track: t, ctrl: "distortion", value: 0.45, label: `Add grit to ${t}` },
  ];
  const ts = [...tracks].sort(() => Math.random() - 0.5).slice(0, 2);
  const moves = ts.map((t) => { const o = pool(t); return o[Math.floor(Math.random() * o.length)]; });
  const mix: MixState = {};
  for (const m of moves) {
    const s: TrackSettings = mix[m.track] || {};
    if (m.ctrl === "gain") s.gain_db = m.value;
    else if (m.ctrl === "reverb") s.fx = { ...s.fx, reverb: m.value };
    else if (m.ctrl === "distortion") s.fx = { ...s.fx, distortion: m.value };
    else if (m.ctrl === "high") s.eq = { ...s.eq, high_db: m.value };
    else if (m.ctrl === "low") s.eq = { ...s.eq, low_db: m.value };
    mix[m.track] = s;
  }
  return { mix, moves };
}

function scoreMix(target: Move[], mine: MixState): number {
  const getter: Record<string, (s: TrackSettings) => number> = {
    gain: (s) => s.gain_db ?? 0, reverb: (s) => s.fx?.reverb ?? 0,
    distortion: (s) => s.fx?.distortion ?? 0, high: (s) => s.eq?.high_db ?? 0,
    low: (s) => s.eq?.low_db ?? 0,
  };
  const tol: Record<string, number> = { gain: 3, reverb: 0.18, distortion: 0.18, high: 3, low: 3 };
  let got = 0;
  for (const m of target) {
    const v = getter[m.ctrl](mine[m.track] || {});
    const sameDir = Math.sign(v) === Math.sign(m.value) || m.value === 0;
    const err = Math.abs(v - m.value);
    if (sameDir && err <= tol[m.ctrl]) got += 1;            // bang on
    else if (sameDir && err <= tol[m.ctrl] * 2.2) got += 0.5; // right idea, off amount
  }
  return Math.round((got / target.length) * 100);
}

function EarTraining({ blockName, onReward, onClose }: {
  blockName: string; onReward: (fans: number) => void; onClose: () => void;
}) {
  const [tracks, setTracks] = useState<string[]>([]);
  const [target, setTarget] = useState<{ mix: MixState; moves: Move[] } | null>(null);
  const [refUrl, setRefUrl] = useState<string | null>(null);
  const [mineUrl, setMineUrl] = useState<string | null>(null);
  const [mix, setMix] = useState<MixState>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ score: number; fans: number } | null>(null);

  useEffect(() => {
    api.getBlockNotes(blockName).then(async (d) => {
      const names = d.tracks.filter((t) => t.notes.length).map((t) => t.track);
      setTracks(names);
      const tg = makeTarget(names.length ? names : d.tracks.map((t) => t.track));
      setTarget(tg);
      const r = await api.mixPreview(blockName, { track_mix: cleanMix(tg.mix) });
      setRefUrl(api.mediaUrl(r.url));
    }).catch(() => {});
  }, [blockName]);

  const hearMine = async () => {
    setBusy(true);
    try { const r = await api.mixPreview(blockName, { track_mix: cleanMix(mix) }); setMineUrl(api.mediaUrl(r.url) + `?v=${Date.now()}`); }
    finally { setBusy(false); }
  };
  const check = () => {
    if (!target) return;
    const score = scoreMix(target.moves, mix);
    const fans = Math.round(score / 100 * 30);
    setResult({ score, fans });
    onReward(fans);
  };

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="gig-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">🎧 Ear training · {blockName}</span>
          <button className="cof-close" onClick={onClose}>✕</button>
        </div>
        <div className="meta" style={{ marginBottom: 8 }}>
          Listen to the <b>reference</b>, then re-create it on the desk by ear — two moves were made to it.
        </div>
        <div className="et-refs">
          <div><div className="et-lbl">Reference 🎯</div>
            {refUrl ? <audio src={refUrl} controls style={{ width: "100%" }} /> : <div className="practice-hint">Preparing…</div>}</div>
          <div><div className="et-lbl">Your mix</div>
            {mineUrl ? <audio src={mineUrl} controls style={{ width: "100%" }} />
              : <button className="btn ghost sm" style={{ width: "auto" }} disabled={busy} onClick={hearMine}>{busy ? "…" : "▶ Hear mine"}</button>}</div>
        </div>
        <MixingDesk tracks={tracks} mix={mix} onChange={(m) => { setMix(m); setMineUrl(null); }} />
        <div className="et-actions">
          <button className="btn ghost" style={{ width: "auto" }} disabled={busy} onClick={hearMine}>{busy ? "Rendering…" : "▶ Hear mine"}</button>
          <button className="btn" style={{ width: "auto" }} onClick={check}>Check my ears</button>
        </div>
        {result && target && (
          <div className="gig-payout">
            <b>{result.score}%</b> match → +{result.fans} fans.
            <div className="meta" style={{ marginTop: 6 }}>The target was: {target.moves.map((m) => m.label).join(" · ")}</div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── A gig: load the song's audio + a part's notes, play along, pay out ───────
function Gig({ blockName, tierMult, production, image = 1, onDone, onClose }: {
  blockName: string; tierMult: number; production: number; image?: number;
  onDone: (g: { fans: number; money: number }) => void;
  onClose: () => void;
}) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const [tracks, setTracks] = useState<api.BlockNotes["tracks"]>([]);
  const [tempo, setTempo] = useState(120);
  const [partIdx, setPartIdx] = useState(0);
  const [craft, setCraft] = useState(1);
  const [payout, setPayout] = useState<{ fans: number; money: number; acc: number; grade: string } | null>(null);

  useEffect(() => {
    api.getBlockNotes(blockName).then((d) => {
      setTempo(d.tempo);
      const pitched = d.tracks.map((t, i) => ({ t, i })).filter((x) => !x.t.is_drum && x.t.notes.length);
      setTracks(d.tracks);
      // default to the most melodic part (fewest simultaneous notes = a line)
      setPartIdx((pitched[0]?.i) ?? 0);
    }).catch(() => {});
    api.getExplain(blockName).then((e) => setCraft(songcraft(e))).catch(() => {});
  }, [blockName]);

  const partOptions = useMemo(
    () => tracks.map((t, i) => ({ i, name: t.track })).filter((x) => !tracks[x.i].is_drum && tracks[x.i].notes.length),
    [tracks]);

  const notes: RollNote[] = useMemo(() => {
    const t = tracks[partIdx]; if (!t) return [];
    const spb = 60 / tempo;
    return t.notes.map((n) => ({ pitch: n[0], start: n[1] * spb, dur: n[2] * spb }));
  }, [tracks, partIdx, tempo]);

  const finish = (r: { accuracy: number; grade: string }) => {
    const base = 18;
    const gradeBonus = r.grade === "S" ? 1.6 : r.grade === "A" ? 1.3 : r.grade === "B" ? 1.1 : r.grade === "C" ? 1 : 0.6;
    const fans = Math.max(1, Math.round(base * (r.accuracy / 100) * craft * production * image * tierMult * gradeBonus));
    const money = Math.round(fans * 1.5);
    setPayout({ fans, money, acc: r.accuracy, grade: r.grade });
    onDone({ fans, money });
  };

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="gig-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">Gig · {blockName}</span>
          <button className="cof-close" onClick={onClose}>✕</button>
        </div>
        <div className="gig-meta">
          Songcraft <b>×{craft.toFixed(2)}</b>{production > 1 && <> · production <b>×{production.toFixed(2)}</b></>}{image > 1 && <> · image <b>×{image.toFixed(2)}</b></>} · venue <b>×{tierMult}</b>
          {partOptions.length > 1 && (
            <select value={partIdx} onChange={(e) => setPartIdx(Number(e.target.value))}>
              {partOptions.map((p) => <option key={p.i} value={p.i}>{p.name}</option>)}
            </select>
          )}
        </div>
        <audio ref={audioRef} src={api.blockAudioUrl(blockName)} controls style={{ width: "100%" }} />
        {notes.length > 0
          ? <PlayAlong notes={notes} audioRef={audioRef} onResult={finish} />
          : <div className="practice-hint">Loading the part…</div>}
        {payout && (
          <div className="gig-payout">
            🎉 <b className={`pa-grade g${payout.grade}`}>{payout.grade}</b> · {payout.acc}% →
            <b> +{payout.fans.toLocaleString()} fans</b>, +${payout.money.toLocaleString()}
            <button className="btn sm" style={{ width: "auto", marginLeft: 10 }} onClick={onClose}>Done</button>
          </div>
        )}
      </div>
    </div>
  );
}
