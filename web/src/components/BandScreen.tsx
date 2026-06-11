import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { Block, ExplainData } from "../types";
import type { RollNote } from "./NotationRoll";
import PlayAlong from "./PlayAlong";

// The band-career shell: name a band, write songs (the generator), then play
// gigs (the scored play-along) to earn fans and climb venues. Songcraft — the
// musical richness the engine + Explain expose — multiplies your gig payoff, so
// better songwriting literally pays off. Career state lives in localStorage.

interface Band { name: string; fans: number; money: number; gigs: number; }
const KEY = "aimusic.band";

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
  try { return JSON.parse(localStorage.getItem(KEY) || "null"); } catch { return null; }
}

export default function BandScreen({ isActive, onWriteSong }: {
  isActive: boolean; onWriteSong: () => void;
}) {
  const [band, setBand] = useState<Band | null>(loadBand);
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [nameDraft, setNameDraft] = useState("");
  const [gig, setGig] = useState<string | null>(null);     // block name being played
  const [produce, setProduce] = useState<string | null>(null);  // block being produced

  useEffect(() => { if (band) localStorage.setItem(KEY, JSON.stringify(band)); }, [band]);
  useEffect(() => { if (isActive) api.getBlocks().then(setBlocks).catch(() => {}); }, [isActive]);

  const { tier, next } = tierFor(band?.fans ?? 0);

  const award = (gained: { fans: number; money: number }) => {
    setBand((b) => b ? { ...b, fans: b.fans + gained.fans, money: b.money + gained.money, gigs: b.gigs + 1 } : b);
  };

  if (!band) {
    return (
      <div className="card band-start">
        <h2>🎸 Start your band</h2>
        <div className="meta" style={{ marginBottom: 10 }}>
          Form a band, write songs, and play gigs to earn fans. The richer your songwriting, the bigger the payoff.
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

  return (
    <>
      <div className="card band-dash">
        <div className="band-name">{band.name}</div>
        <div className="band-stats">
          <span><b>{band.fans.toLocaleString()}</b> fans</span>
          <span><b>${band.money.toLocaleString()}</b></span>
          <span><b>{band.gigs}</b> gigs</span>
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

      <div className="card">
        <h2>Your songs</h2>
        {blocks.length === 0
          ? <div className="meta">No songs yet — write one in Generate, save it as a block, and it'll appear here.</div>
          : (
            <div className="band-songs">
              {blocks.map((b) => (
                <div key={b.name} className="band-song">
                  <span className="band-song-name">{b.name}</span>
                  <button className="btn ghost sm" style={{ width: "auto" }}
                    onClick={() => setProduce(b.name)}>🎛 Produce</button>
                  <button className="btn secondary sm" style={{ width: "auto" }}
                    onClick={() => setGig(b.name)}>🎤 Play gig</button>
                </div>
              ))}
            </div>
          )}
      </div>

      {gig && (
        <Gig blockName={gig} tierMult={tier.mult}
          onDone={(g) => { award(g); }}
          onClose={() => setGig(null)} />
      )}
      {produce && (
        <Produce blockName={produce} tierMult={tier.mult}
          onDone={(g) => { award(g); }}
          onClose={() => setProduce(null)} />
      )}
    </>
  );
}

// ── The producer role: arrange + master a song to boost its appeal ───────────
function Produce({ blockName, tierMult, onDone, onClose }: {
  blockName: string; tierMult: number;
  onDone: (g: { fans: number; money: number }) => void;
  onClose: () => void;
}) {
  const [tracks, setTracks] = useState<string[]>([]);
  const [muted, setMuted] = useState<Set<string>>(new Set());
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
      const r = await api.produceBlock(blockName, { mute: [...muted], master_preset: master });
      const fans = Math.round(12 * r.production * tierMult);
      const money = Math.round(fans * 1.3);
      setResult({ production: r.production, fans, money });
      setAudioBust((n) => n + 1);   // refetch the re-mastered preview
      onDone({ fans, money });
    } finally { setBusy(false); }
  };

  const MASTER_DESC: Record<string, string> = {
    default: "balanced, broadcast-ready", loud: "hot & competitive (streaming)",
    cinematic: "wide, spacious, reverby", transparent: "minimal — keeps it natural",
  };

  return (
    <div className="cof-backdrop" onClick={onClose}>
      <div className="gig-modal" onClick={(e) => e.stopPropagation()}>
        <div className="cof-head">
          <span className="cof-title">🎛 Produce · {blockName}</span>
          <button className="cof-close" onClick={onClose}>✕</button>
        </div>
        <div className="prod-section">
          <h4>Arrangement <span className="meta">— mute tracks to shape the mix</span></h4>
          <div className="prod-tracks">
            {tracks.map((t) => (
              <button key={t} className={"prod-track" + (muted.has(t) ? " muted" : "")}
                onClick={() => setMuted((s) => { const n = new Set(s); n.has(t) ? n.delete(t) : n.add(t); return n; })}>
                {muted.has(t) ? "🔇" : "🔊"} {t}
              </button>
            ))}
          </div>
        </div>
        <div className="prod-section">
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
          {busy ? "Mixing…" : result ? "Re-produce" : "🎚 Produce it"}
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

// ── A gig: load the song's audio + a part's notes, play along, pay out ───────
function Gig({ blockName, tierMult, onDone, onClose }: {
  blockName: string; tierMult: number;
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
    const fans = Math.max(1, Math.round(base * (r.accuracy / 100) * craft * tierMult * gradeBonus));
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
          Songcraft <b>×{craft.toFixed(2)}</b> · venue <b>×{tierMult}</b>
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
