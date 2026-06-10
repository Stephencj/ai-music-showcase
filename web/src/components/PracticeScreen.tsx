import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { ScoreData, ChordSpan } from "../api";
import type { Block, Preset } from "../types";
import ChordDiagram from "./ChordDiagram";
import TapeView from "./TapeView";
import NotationRoll, { type RollNote } from "./NotationRoll";
import SheetMusic from "./SheetMusic";
import TabView from "./TabView";
import { isFrettedTrack, isGuitarTrack, isKeysTrack, tuningFor, stringLabelsFor, assignFrets } from "../guitarTab";
import * as webmidi from "../webmidi";
import type { MidiOut } from "../webmidi";
import { LoopPlayer } from "../loopPlayer";
import type { BlockNotes } from "../api";
import { MODES, ALL_ROOTS, scaleToModeId, rootPc, romanFor, nashvilleFor } from "../chordLabels";

type Notation = "chord" | "nashville" | "roman";
type ChartView = "grid" | "tape" | "sheet" | "tab";
type Mode = "block" | "upload" | "scan";

const NOTATION_LABEL: Record<Notation, string> = {
  chord: "Chords",
  nashville: "Nashville",
  roman: "Roman",
};

// Open-chord-friendly keys (C D E G A). For an acoustic guitar, default the
// capo to the lowest fret that lands the song key on one of these, so the
// player can use easy open shapes.
const OPEN_KEY_PCS = [0, 2, 4, 7, 9];
function autoCapo(keyPc: number): number {
  for (let f = 0; f <= 7; f++) if (OPEN_KEY_PCS.includes(((keyPc - f) % 12 + 12) % 12)) return f;
  return 0;
}

export default function PracticeScreen() {
  const [mode, setMode] = useState<Mode>("block");
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [songs, setSongs] = useState<string[]>([]);
  // Picker value, prefixed: "block:<name>" or "song:<title>".
  const [selected, setSelected] = useState<string>("");
  const [presets, setPresets] = useState<Preset[]>([]);

  const [score, setScore] = useState<ScoreData | null>(null);
  // Per-track notes for the notation roll + real-time diagrams (blocks only).
  const [partNotes, setPartNotes] = useState<BlockNotes | null>(null);
  // Independent part selectors: the piano diagram, the guitar neck diagram, and
  // the score section (sheet / tab / notation roll) each pick their own part.
  const [pianoIdx, setPianoIdx] = useState(-1);
  const [guitarIdx, setGuitarIdx] = useState(-1);
  const [chartIdx, setChartIdx] = useState(-1);  // -1 = chords only (no part)
  const [solo, setSolo] = useState(false);       // play just the chart part
  const [capo, setCapo] = useState(0);           // chord-shape capo (teaching)
  // Real-time MIDI out: stream this block's notes to a hardware/virtual port.
  const [midiOuts, setMidiOuts] = useState<MidiOut[]>([]);
  const [midiOutId, setMidiOutId] = useState("");
  const [midiOn, setMidiOn] = useState(false);
  const [midiErr, setMidiErr] = useState("");
  const [midiReady, setMidiReady] = useState(false);
  // Which panels show in the practice space (gear), persisted.
  const [panels, setPanels] = useState<Record<string, boolean>>(() => {
    try {
      return { nowPlaying: true, diagrams: true, roll: true, chart: true,
               ...JSON.parse(localStorage.getItem("practice.panels") || "{}") };
    } catch { return { nowPlaying: true, diagrams: true, roll: true, chart: true }; }
  });
  const [showSettings, setShowSettings] = useState(false);
  // Diagram mode: chord-shape (practice) vs full neck (what's on the page).
  const [neckMode, setNeckMode] = useState(() => localStorage.getItem("practice.neck") === "1");
  const [audioSrc, setAudioSrc] = useState<string>("");
  const [progression, setProgression] = useState<string[]>([]);

  const [err, setErr] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [notation, setNotation] = useState<Notation>("chord");
  const [view, setView] = useState<ChartView>("grid");
  const [t, setT] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState(1);
  // Loop: "off" | "all" | "s<sectionIndex>" (loop a single section).
  const [loop, setLoop] = useState("off");
  // Tonic + mode the Roman/Nashville numbers are computed against. Seeded from
  // the detected key, but fully selectable across the modal range for learning.
  const [tonic, setTonic] = useState("C");
  const [keyMode, setKeyMode] = useState("major");

  const audioRef = useRef<HTMLAudioElement | null>(null);
  // Seamless/pitch-preserved section-loop engine (Web Audio + SoundTouch).
  // Only engaged for the section-loop case; ordinary playback stays native.
  const engineRef = useRef<LoopPlayer | null>(null);
  const [engPlaying, setEngPlaying] = useState(false);
  const [engErr, setEngErr] = useState("");

  // "Generate similar" (upload mode)
  const [simGenre, setSimGenre] = useState<string>("");
  const [simMsg, setSimMsg] = useState<string>("");
  const [simBusy, setSimBusy] = useState(false);

  // "Scan sheet music" (scan mode)
  const [scanMsg, setScanMsg] = useState<string>("");
  const [scanBusy, setScanBusy] = useState(false);

  const activeRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    api.getBlocks()
      .then((bs) => {
        const playable = bs.filter((b) => b.has_preview);
        setBlocks(playable);
        setSelected((cur) => cur || (playable.length ? `block:${playable[0].name}` : ""));
      })
      .catch((e) => setErr(String(e)));
    api.listSongs().then((r) => setSongs(r.songs || [])).catch(() => {});
    api.getPresets().then((ps) => {
      setPresets(ps);
      if (ps.length) setSimGenre(ps[0].id);
    }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    try { localStorage.setItem("practice.panels", JSON.stringify(panels)); } catch { /* ignore */ }
  }, [panels]);

  // Block mode: load score + audio for the selected block OR song.
  useEffect(() => {
    if (mode !== "block" || !selected) return;
    setLoading(true); setScore(null); setErr(""); setT(0); setLoop("off");
    setPartNotes(null); setPianoIdx(-1); setGuitarIdx(-1); setChartIdx(-1); setSolo(false);
    if (selected.startsWith("song:")) {
      const title = selected.slice(5);
      setAudioSrc(api.songAudioUrl(title));
      api.getSongScoreData(title)
        .then((s) => { setScore(s); setProgression([]); })
        .catch((e) => setErr(String(e)))
        .finally(() => setLoading(false));
    } else {
      const nm = selected.replace(/^block:/, "");
      const block = blocks.find((b) => b.name === nm);
      if (block) setAudioSrc(api.mediaUrl(block.audio_url));
      api.getScoreData(nm)
        .then((s) => { setScore(s); setProgression([]); })
        .catch((e) => setErr(String(e)))
        .finally(() => setLoading(false));
      api.getBlockNotes(nm).then(setPartNotes).catch(() => setPartNotes(null));
    }
  }, [mode, selected, blocks]);

  // Default each selector to the first relevant part once notes arrive: piano →
  // first keyboard part, guitar → first guitar part, chart → first fretted part.
  useEffect(() => {
    if (!partNotes) return;
    const ts = partNotes.tracks;
    const firstMel = ts.findIndex((t) => !t.is_drum);
    const firstKeys = ts.findIndex((t) => !t.is_drum && isKeysTrack(t.track));
    const firstGtr = ts.findIndex((t) => isGuitarTrack(t.track));
    const firstFret = ts.findIndex((t) => !t.is_drum && isFrettedTrack(t.track));
    setPianoIdx(firstKeys >= 0 ? firstKeys : firstMel);
    setGuitarIdx(firstGtr >= 0 ? firstGtr : firstFret >= 0 ? firstFret : firstMel);
    setChartIdx(firstFret >= 0 ? firstFret : firstGtr >= 0 ? firstGtr : firstMel);
  }, [partNotes]);

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
            setSelected(`block:${hit ? hit.name : b}`);
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

  // Follow the song by scrolling ONLY the chart container (grid view) — the
  // now-playing header + diagrams stay pinned above and don't move.
  useEffect(() => {
    if (view !== "grid") return;
    const box = chartRef.current, cell = activeRef.current;
    if (!box || !cell) return;
    const b = box.getBoundingClientRect(), c = cell.getBoundingClientRect();
    box.scrollTo({ top: box.scrollTop + (c.top - b.top) - b.height / 2 + c.height / 2, behavior: "smooth" });
  }, [activeSpanIdx, view]);

  // Apply the practice speed to the audio element. Set preservesPitch BEFORE
  // playbackRate (and across all vendor prefixes) so changing speed never
  // shifts the key — important on iOS WKWebView.
  function applyRate(a: HTMLAudioElement | null) {
    if (!a) return;
    a.preservesPitch = true;
    (a as unknown as { webkitPreservesPitch?: boolean }).webkitPreservesPitch = true;
    (a as unknown as { mozPreservesPitch?: boolean }).mozPreservesPitch = true;
    a.playbackRate = speed;
  }
  useEffect(() => { applyRate(audioRef.current); }, [speed, audioSrc, score]);

  // Seed the tonic/mode selectors from the detected key whenever a new score
  // loads (the user can then override them across the full modal range).
  useEffect(() => {
    if (!score) return;
    setTonic(ALL_ROOTS[rootPc(score.key)]);
    setKeyMode(scaleToModeId(score.scale));
  }, [score]);

  const modeIntervals = (MODES.find((m) => m.id === keyMode) || MODES[0]).intervals;
  const sourceIsSong = selected.startsWith("song:");
  const blockName = selected.startsWith("block:") ? selected.slice(6) : "";

  // Parts available to the selectors (pitched, non-drum). Drums can't be tabbed
  // or shown on the piano/neck, so they're excluded.
  const partOptions = useMemo(
    () => (partNotes?.tracks ?? []).map((t, idx) => ({ idx, name: t.track, is_drum: t.is_drum }))
      .filter((p) => !p.is_drum),
    [partNotes]);

  const pianoTrack = partNotes && pianoIdx >= 0 ? partNotes.tracks[pianoIdx] : undefined;
  const guitarTrack = partNotes && guitarIdx >= 0 ? partNotes.tracks[guitarIdx] : undefined;
  const chartTrack = partNotes && chartIdx >= 0 ? partNotes.tracks[chartIdx] : undefined;

  const rollFrom = (tr: typeof pianoTrack): RollNote[] => {
    if (!tr || !partNotes || tr.is_drum) return [];
    const spb = 60 / (partNotes.tempo || 120);
    return tr.notes.map(([pitch, sb, db]) => ({ pitch, start: sb * spb, dur: db * spb }));
  };
  const tabFrom = (tr: typeof pianoTrack) => {
    if (!tr || !partNotes || tr.is_drum || !isFrettedTrack(tr.track)) return null;
    const tuning = tuningFor(tr.track);
    const spb = 60 / (partNotes.tempo || 120);
    const tabNotes = assignFrets(tr.notes, tuning).map((f) => ({ ...f, start: f.start * spb, dur: f.dur * spb }));
    return { name: tr.track, labels: stringLabelsFor(tuning), tabNotes };
  };

  // Piano diagram follows its part (by pitch). Guitar neck follows its part — by
  // exact fret (tab) when it's a guitar, else by pitch (bass uses a guitar neck).
  const pianoNotes = useMemo(() => rollFrom(pianoTrack), [pianoTrack, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps
  const guitarNotes = useMemo(() => rollFrom(guitarTrack), [guitarTrack, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps
  const guitarTab = useMemo(
    () => (guitarTrack && isGuitarTrack(guitarTrack.track) ? tabFrom(guitarTrack) : null),
    [guitarTrack, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps

  // Score section (sheet / tab / notation roll) follows the chart part.
  const chartRollNotes = useMemo(() => rollFrom(chartTrack), [chartTrack, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps
  const chartTab = useMemo(() => tabFrom(chartTrack), [chartTrack, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps

  // Default the capo from the key when the guitar part is an ACOUSTIC (its
  // shapes benefit from a capo); other guitars / re-selections reset to 0.
  // Manual changes persist until the key or the selected guitar changes.
  useEffect(() => {
    if (!score) { setCapo(0); return; }
    const acoustic = !!guitarTrack && /acoustic/i.test(guitarTrack.track);
    setCapo(acoustic ? autoCapo(rootPc(score.key)) : 0);
  }, [score?.key, guitarIdx, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps

  // For section looping, play the WAV (sample-accurate seeks — no MP3 decoder
  // priming gap), which keeps loops tight without losing pitch-preserved speed.
  const sectionLooping = loop.startsWith("s");
  // Real pitch range of the piano part, for the wide piano key span.
  const pianoRange = useMemo(() => {
    if (!pianoNotes.length) return undefined;
    let lo = 128, hi = 0;
    for (const n of pianoNotes) { lo = Math.min(lo, n.pitch); hi = Math.max(hi, n.pitch); }
    return [lo, hi] as [number, number];
  }, [pianoNotes]);

  const playSrc = (solo && chartTrack && blockName)
    ? api.partAudioUrl(blockName, chartIdx)
    : sectionLooping
      ? (blockName ? api.blockFileUrl(blockName, "wav")
         : sourceIsSong ? api.songWavUrl(selected.slice(5)) : audioSrc)
      : audioSrc;

  // Section looping runs on the SoundTouch engine (seamless, in-memory loop;
  // pitch locked while speed time-stretches) rather than the native element —
  // a decoder reseek on <audio> always leaves a gap at the seam.
  const sectionLoopingRef = useRef(sectionLooping);
  sectionLoopingRef.current = sectionLooping;

  // A unified playhead all the visual consumers (chart, roll, diagrams, sheet)
  // read via `.current.currentTime` / `.current.paused`. It transparently
  // reflects the engine while a section loop is active and the native element
  // otherwise, so none of the children need to know which is driving.
  const playhead = useMemo(() => ({
    get current() {
      const e = engineRef.current;
      if (sectionLoopingRef.current && e) {
        return { currentTime: e.getTime(), paused: !e.playing } as unknown as HTMLAudioElement;
      }
      return audioRef.current;
    },
  }), []) as unknown as React.RefObject<HTMLAudioElement | null>;

  // Engage / tear down the loop engine when entering / leaving a section loop,
  // or when the loop section or audio source changes. Native audio is paused
  // while the engine drives; on exit we hand the position back to it.
  useEffect(() => {
    if (!sectionLooping || !score) return;
    const sec = score.sections[Number(loop.slice(1))];
    if (!sec) return;
    const a = audioRef.current;
    const startAt = a ? a.currentTime : sec.start_time;
    if (a) a.pause();
    const eng = engineRef.current || (engineRef.current = new LoopPlayer());
    let cancelled = false;
    // Resume here at the position within THIS section, else from its start.
    const from = startAt >= sec.start_time && startAt < sec.end_time ? startAt : sec.start_time;
    setEngErr("");
    (async () => {
      try {
        await eng.load(playSrc);
        if (cancelled) return;
        // Bounds + tempo BEFORE play so the freshly-built shifter loops the
        // right region (avoids inheriting the previous section's bounds).
        eng.setTempo(speed);
        eng.setLoop(sec.start_time, sec.end_time);
        await eng.play(from);
        if (cancelled) { eng.pause(); return; }
        setEngPlaying(true);
      } catch (e) {
        console.warn("section-loop engine failed:", e);
        setEngErr(String((e as Error)?.message || e));
        setEngPlaying(false);
      }
    })();
    return () => {
      cancelled = true;
      const t0 = eng.getTime();
      eng.pause();
      setEngPlaying(false);
      // Hand the position back to the native element for seamless resume.
      const el = audioRef.current;
      if (el) { try { el.currentTime = Math.min(t0, (el.duration || t0)); } catch { /* not ready */ } }
    };
    // playing intentionally excluded: engine owns transport during loop.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sectionLooping, loop, score, playSrc]);

  // Live tempo changes while looping (no rebuild — SoundTouch retimes in place).
  useEffect(() => {
    if (sectionLooping && engineRef.current) engineRef.current.setTempo(speed);
  }, [speed, sectionLooping]);

  // Drive the chart timeline `t` from the engine clock while looping (the
  // native element is paused, so its timeupdate won't fire).
  useEffect(() => {
    if (!sectionLooping) return;
    let raf = 0;
    const tick = () => {
      const e = engineRef.current;
      if (e) setT(e.getTime());
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [sectionLooping]);

  // Release the audio context when the screen unmounts.
  useEffect(() => () => { engineRef.current?.destroy(); engineRef.current = null; }, []);

  function toggleEngine() {
    const e = engineRef.current;
    if (!e) return;
    if (e.playing) { e.pause(); setEngPlaying(false); return; }
    // Resume from where we are, but if that's outside the section (e.g. after
    // an error) fall back to the section start. This press is a user gesture,
    // so it reliably resumes a suspended AudioContext.
    setEngErr("");
    e.play().then(() => setEngPlaying(true)).catch((err) => {
      setEngErr(String((err as Error)?.message || err));
    });
  }

  // Unified "is something playing" for the now-playing beat counter.
  const isPlaying = sectionLooping ? engPlaying : playing;

  // Seek playback to a chord's start (tap a cell to jump there).
  function seekTo(time: number) {
    if (sectionLoopingRef.current && engineRef.current) {
      engineRef.current.seek(time); setT(time); return;
    }
    const a = audioRef.current;
    if (a) { a.currentTime = time; setT(time); }
  }

  // Unified transport (works whether the native <audio> or the loop engine is
  // driving) for the compact mid-screen controls.
  function togglePlayback() {
    if (sectionLooping) { toggleEngine(); return; }
    const a = audioRef.current;
    if (!a) return;
    if (a.paused) a.play().catch(() => {}); else a.pause();
  }
  // Ask for MIDI access (user gesture) and populate the output list.
  async function enableMidi() {
    setMidiErr("");
    try {
      const outs = await webmidi.initMidi();
      setMidiOuts(outs);
      setMidiOutId((cur) => cur || outs[0]?.id || "");
      webmidi.onStateChange(() => setMidiOuts(webmidi.listOutputs()));
      setMidiReady(true);
      if (!outs.length) setMidiErr("No MIDI outputs found — connect a device or a virtual port.");
    } catch (e) {
      setMidiErr(String(e instanceof Error ? e.message : e));
    }
  }

  // Jump to bar boundaries: forward → next downbeat; back → start of the
  // current bar (or the previous one if we're right at the start).
  function skipBar(dir: number) {
    const bs = score?.bar_seconds || 0;
    if (!bs) return;
    const cur = playhead.current?.currentTime ?? t;
    const curBar = Math.floor(cur / bs + 1e-6);
    const target = dir > 0
      ? (curBar + 1) * bs
      : (cur - curBar * bs > 0.2 ? curBar * bs : (curBar - 1) * bs);
    seekTo(Math.max(0, target));
  }

  // All three labels for a chord, with the selected notation emphasized
  // (primary) and the others shown small (secondary) — switching notation
  // changes emphasis rather than hiding the rest.
  type Labels = { primary: string; secondary: string };
  function labelParts(c: { symbol: string; root: string | null; quality: string | null }): Labels {
    if (c.symbol === "N.C." || !c.root || !c.quality) {
      return { primary: c.symbol === "N.C." ? "—" : c.symbol, secondary: "" };
    }
    const chord = c.symbol;
    const roman = romanFor(c.root, c.quality, tonic, modeIntervals);
    const nash = nashvilleFor(c.root, c.quality, tonic, modeIntervals);
    if (notation === "roman") return { primary: roman, secondary: `${chord} · ${nash}` };
    if (notation === "nashville") return { primary: nash, secondary: `${chord} · ${roman}` };
    return { primary: chord, secondary: `${roman} · ${nash}` };
  }

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
          <select value={selected} onChange={(e) => setSelected(e.target.value)}>
            {blocks.length === 0 && songs.length === 0 && <option value="">Nothing to play yet</option>}
            {songs.length > 0 && (
              <optgroup label="Songs">
                {songs.map((s) => <option key={`song:${s}`} value={`song:${s}`}>{s}</option>)}
              </optgroup>
            )}
            <optgroup label="Blocks">
              {blocks.map((b) => (
                <option key={`block:${b.name}`} value={`block:${b.name}`}>{b.name}</option>
              ))}
            </optgroup>
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

      {score && notation !== "chord" && (
        <div className="keymode-row">
          <span className="keymode-label">Numbers vs</span>
          <select value={tonic} onChange={(e) => setTonic(e.target.value)}>
            {ALL_ROOTS.map((r) => <option key={r} value={r}>{r}</option>)}
          </select>
          <select value={keyMode} onChange={(e) => setKeyMode(e.target.value)}>
            {MODES.map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
          </select>
          <button
            className="keymode-reset"
            onClick={() => { setTonic(ALL_ROOTS[rootPc(score.key)]); setKeyMode(scaleToModeId(score.scale)); }}
            title="Reset to the detected key"
          >↺</button>
        </div>
      )}

      {err && <div className="practice-err">{err}</div>}
      {mode === "scan" && scanMsg && <div className="practice-hint">{scanMsg}</div>}
      {mode === "scan" && !score && !scanMsg && (
        <div className="practice-hint">Upload a clear photo or scan of printed sheet music. Recognition takes a minute or two and works best on clean, well-lit pages.</div>
      )}
      {loading && <div className="practice-hint">{mode === "upload" ? "Listening & detecting chords…" : "Analyzing chords…"}</div>}

      {score && (
        <>
          <div className="practice-head">
          {audioSrc && (
            <audio
              ref={audioRef}
              src={playSrc}
              controls
              loop={loop === "all"}
              onTimeUpdate={(e) => { if (!sectionLooping) setT(e.currentTarget.currentTime); }}
              onPlay={() => setPlaying(true)}
              onPause={() => setPlaying(false)}
              onLoadedMetadata={(e) => {
                applyRate(e.currentTarget);
                if (loop.startsWith("s")) {
                  const sec = score.sections[Number(loop.slice(1))];
                  if (sec) e.currentTarget.currentTime = sec.start_time;
                }
              }}
              style={{ width: "100%", display: sectionLooping ? "none" : "block" }}
            />
          )}
          {/* During a section loop the SoundTouch engine is the audio source;
              give it its own transport (the native controls are hidden). */}
          {sectionLooping && (
            <div className="engine-transport">
              <button className="engine-play" onClick={toggleEngine}>
                {engPlaying ? "⏸" : "▶"}
              </button>
              <span className="engine-label">
                {engErr
                  ? `⚠ Loop engine: ${engErr}`
                  : `🔁 Looping ${score.sections[Number(loop.slice(1))]?.label || "section"} — seamless, pitch-locked`}
              </span>
            </div>
          )}

          {/* Practice speed — change playback rate without dropping pitch. The
              chord chart tracks the media timeline, so it stays in sync at any
              speed. Effective tempo shown for reference. */}
          <div className="speed-row">
            <span className="speed-label">Speed</span>
            <input
              className="speed-slider"
              type="range" min={0.5} max={1.5} step={0.05}
              value={speed}
              onChange={(e) => setSpeed(Number(e.target.value))}
            />
            <button className="speed-reset" onClick={() => setSpeed(1)} title="Reset to 1×">{speed.toFixed(2)}×</button>
            <span className="speed-bpm">{Math.round(score.tempo * speed)} BPM</span>
          </div>

          <div className="loop-row">
            <span className="speed-label">🔁 Loop</span>
            <select
              value={loop}
              onChange={(e) => {
                // Section loops are positioned by the engine effect; "off" /
                // "all" stay on the native element wherever it already is.
                setLoop(e.target.value);
              }}
            >
              <option value="off">Off</option>
              <option value="all">Whole {sourceIsSong ? "song" : "block"}</option>
              {score.sections.map((s, i) => (
                <option key={`${s.label}-${s.start_bar}`} value={`s${i}`}>{s.label}</option>
              ))}
            </select>
          </div>

          {/* Real-time MIDI out: stream this block's notes to a hardware/virtual
              port as it plays (one channel per track; drums → ch 10). */}
          {partNotes && partNotes.tracks.length > 0 && webmidi.midiSupported() && (
            <div className="midi-row">
              <span className="speed-label">🎹 MIDI out</span>
              {!midiReady ? (
                <button className="btn ghost sm" onClick={enableMidi}>Enable</button>
              ) : (
                <>
                  <select value={midiOutId} onChange={(e) => setMidiOutId(e.target.value)}>
                    {midiOuts.length === 0 && <option value="">no outputs</option>}
                    {midiOuts.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                  </select>
                  <button className={"chip" + (midiOn ? " on" : "")} disabled={!midiOutId}
                    onClick={() => setMidiOn((v) => !v)}
                    title="Stream notes to the selected output while playing">
                    {midiOn ? "● sending" : "send"}</button>
                </>
              )}
              {midiErr && <span className="midi-err">{midiErr}</span>}
            </div>
          )}
          {midiOn && midiOutId && partNotes && (
            <MidiStreamer tracks={partNotes.tracks} tempo={partNotes.tempo}
              outputId={midiOutId} audioRef={playhead} />
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

          {panels.nowPlaying && (
            <div className="now-playing">
              <div className="np-meta">
                <span className="np-key">{score.key} {score.scale}</span>
                <span className="np-sec">{activeSection?.label || ""}</span>
                <span className="np-tempo">{Math.round(score.tempo)} BPM</span>
              </div>
              <div className="np-chords">
                <div className="np-current">
                  <div className="np-big">{active ? labelParts(active).primary : "—"}</div>
                  {active && labelParts(active).secondary && (
                    <div className="np-alt">{labelParts(active).secondary}</div>
                  )}
                </div>
                <div className="np-count">
                  {isPlaying && beatsToNext != null ? `${beatsToNext}` : "·"}
                  <span>beats</span>
                </div>
                <div className="np-next">
                  <div className="np-next-label">next</div>
                  <div className="np-next-chord">{next ? labelParts(next).primary : "—"}</div>
                </div>
              </div>
            </div>
          )}

          {panels.diagrams && (pianoNotes.length > 0 || guitarNotes.length > 0 || active?.root) && (
            <div className="diagram-block">
              <div className="diagram-bar">
                <div className="diagram-bar-left">
                  <div className="seg diagram-mode">
                    <button className={!neckMode ? "on" : ""}
                      onClick={() => { setNeckMode(false); localStorage.setItem("practice.neck", "0"); }}>Chord</button>
                    <button className={neckMode ? "on" : ""}
                      onClick={() => { setNeckMode(true); localStorage.setItem("practice.neck", "1"); }}>Full neck</button>
                  </div>
                  {/* Compact transport: same as the top player, snug beside the toggle. */}
                  {audioSrc && (
                    <div className="mini-transport">
                      <button onClick={() => skipBar(-1)} title="Back a bar" aria-label="Back one bar">⏮</button>
                      <button onClick={togglePlayback} className="mt-play" title="Play / pause"
                        aria-label="Play or pause">{isPlaying ? "⏸" : "▶"}</button>
                      <button onClick={() => skipBar(1)} title="Forward a bar" aria-label="Forward one bar">⏭</button>
                    </div>
                  )}
                  {audioSrc && (
                    <div className="mini-speed">
                      {[0.5, 0.75, 1].map((s) => (
                        <button key={s} className={Math.abs(speed - s) < 0.01 ? "on" : ""}
                          onClick={() => setSpeed(s)} title={`${s}× speed`}>{s}×</button>
                      ))}
                    </div>
                  )}
                </div>
                {/* Capo (chord shapes): default auto-set for acoustic guitar, adjustable. */}
                {!neckMode && (
                  <div className="capo-ctl" title="Capo fret — shows the easier shapes you'd finger with a capo">
                    <span>Capo</span>
                    <button onClick={() => setCapo((c) => Math.max(0, c - 1))} aria-label="Capo down">–</button>
                    <span className="capo-val">{capo === 0 ? "off" : capo}</span>
                    <button onClick={() => setCapo((c) => Math.min(11, c + 1))} aria-label="Capo up">+</button>
                  </div>
                )}
              </div>
              <ChordDiagram
                root={active?.root || "C"}
                quality={active?.quality || "maj"}
                audioRef={playhead}
                neck={neckMode}
                capo={capo}
                // In Full-neck mode the piano and guitar each follow their own
                // selected part: piano lights by pitch, the neck lights the exact
                // fret being played (tab) — or by pitch for a bass part.
                pianoNotes={pianoNotes}
                pianoRange={pianoRange}
                guitarTab={guitarTab ? guitarTab.tabNotes : undefined}
                guitarNotes={guitarNotes}
                parts={partOptions}
                pianoIdx={pianoIdx}
                guitarIdx={guitarIdx}
                onPianoIdx={setPianoIdx}
                onGuitarIdx={setGuitarIdx}
              />
            </div>
          )}

          {panels.roll && chartRollNotes.length > 0 && (
            <div className="roll-card">
              <div className="diagram-title">{chartTrack?.track} — notation roll</div>
              <NotationRoll notes={chartRollNotes} audioRef={playhead} />
            </div>
          )}

          <div className="head-controls">
            <div className="seg view-toggle">
              <button className={view === "grid" ? "on" : ""} onClick={() => setView("grid")}>Grid</button>
              <button className={view === "tape" ? "on" : ""} onClick={() => setView("tape")}>Tape ▶</button>
              {!sourceIsSong && (
                <button className={view === "sheet" ? "on" : ""} onClick={() => setView("sheet")}>Sheet ♪</button>
              )}
              {!sourceIsSong && (
                <button className={view === "tab" ? "on" : ""} onClick={() => setView("tab")}>Tab 🎸</button>
              )}
            </div>
            {/* The score section (Sheet / Tab / notation roll) picks its part. */}
            {!sourceIsSong && partOptions.length > 0 && (view === "sheet" || view === "tab") && (
              <label className="chart-part">
                <select value={chartIdx} onChange={(e) => { setChartIdx(Number(e.target.value)); setSolo(false); }}>
                  {partOptions.map((p) => <option key={p.idx} value={p.idx}>{p.name}</option>)}
                </select>
                <span className="part-solo">
                  <input type="checkbox" checked={solo} onChange={(e) => setSolo(e.target.checked)} /> Solo
                </span>
              </label>
            )}
            <button className="gear-btn" onClick={() => setShowSettings((s) => !s)} title="Practice settings">⚙</button>
          </div>
          {showSettings && (
            <div className="settings-panel">
              {([["nowPlaying", "Now playing"], ["diagrams", "Piano / guitar"],
                 ["roll", "Notation roll"], ["chart", "Chord chart"]] as [string, string][]).map(([k, lbl]) => (
                <label key={k}>
                  <input type="checkbox" checked={!!panels[k]}
                    onChange={(e) => setPanels((p) => ({ ...p, [k]: e.target.checked }))} /> {lbl}
                </label>
              ))}
            </div>
          )}
          </div>

          {panels.chart && (<>
            {/* Pre-warmed, always-mounted sheet: AlphaTab stays engraved and
                cursor-synced in the background, so switching to Sheet from any
                other view is instant (no reload/engrave flash). Hidden via CSS
                — kept full-width so AlphaTab still measures/lays out correctly. */}
            {blockName && (
              <div className={"sheet-host" + (view === "sheet" ? "" : " sheet-hidden")}
                aria-hidden={view !== "sheet"}>
                <SheetMusic blockName={blockName} audioRef={playhead} trackIndex={chartIdx} />
              </div>
            )}

            {view === "tab" ? (
            !blockName
              ? <div className="practice-hint">Tab view is available for blocks (songs show the chart).</div>
              : chartTab && chartTab.tabNotes.length
                ? (
                  <div className="tab-card">
                    <div className="diagram-title">{chartTab.name} — tab</div>
                    <TabView tabNotes={chartTab.tabNotes} stringLabels={chartTab.labels} audioRef={playhead} />
                  </div>
                )
                : <div className="practice-hint">This part isn't a guitar or bass — pick a fretted part above to tab it.</div>
          ) : view === "sheet" ? (
            blockName
              ? null /* shown by the pre-warmed sheet-host above */
              : <div className="practice-hint">Sheet view is available for blocks (songs show the chart).</div>
          ) : view === "tape" ? (
            <TapeView score={score} labelParts={labelParts} audioRef={playhead} onSeek={seekTo} />
          ) : (
            <div className="chart" ref={chartRef}>
              {score.sections.length > 0
                ? score.sections.map((sec) => (
                    <div key={`${sec.label}-${sec.start_bar}`} className="chart-section">
                      <div className="chart-section-label">{sec.label}</div>
                      <div className="chart-grid">
                        {score.chord_spans
                          .filter((s) => s.start_bar >= sec.start_bar && s.start_bar <= sec.end_bar)
                          .map((s) => (
                            <Cell key={s.start_bar} span={s} {...labelParts(s)}
                              active={s === active} cellRef={s === active ? activeRef : undefined}
                              onSeek={() => seekTo(s.start_time)} />
                          ))}
                      </div>
                    </div>
                  ))
                : (
                  <div className="chart-grid">
                    {score.chord_spans.map((s) => (
                      <Cell key={s.start_bar} span={s} {...labelParts(s)}
                        active={s === active} cellRef={s === active ? activeRef : undefined}
                        onSeek={() => seekTo(s.start_time)} />
                    ))}
                  </div>
                )}
            </div>
          )}</>)}
        </>
      )}
    </div>
  );
}

// Streams the block's notes to a MIDI output, following the playhead. On each
// frame it computes which (channel,pitch) should sound and diffs against what's
// currently on — sending note-on/off. Handles seek, loop and pause (notes that
// fall out of the sounding set, or everything when paused, get note-off).
function MidiStreamer({ tracks, tempo, outputId, audioRef }: {
  tracks: BlockNotes["tracks"];
  tempo: number;
  outputId: string;
  audioRef: React.RefObject<HTMLAudioElement | null>;
}) {
  useEffect(() => {
    const spb = 60 / (tempo || 120);
    const chans = webmidi.channelsFor(tracks.map((t) => t.is_drum));
    const events = tracks.flatMap((t, ti) =>
      t.notes.map(([p, sb, db]) => ({ ch: chans[ti], pitch: p, start: sb * spb, end: (sb + db) * spb })));
    const active = new Set<string>();
    let raf = 0;
    const tick = () => {
      const a = audioRef.current;
      const playing = !!a && !a.paused;
      const t = a?.currentTime ?? 0;
      const want = new Set<string>();
      if (playing) {
        for (const e of events) if (t >= e.start && t < e.end) want.add(`${e.ch}:${e.pitch}`);
      }
      for (const k of active) {
        if (!want.has(k)) { const [ch, p] = k.split(":").map(Number); webmidi.noteOff(outputId, ch, p); active.delete(k); }
      }
      for (const k of want) {
        if (!active.has(k)) { const [ch, p] = k.split(":").map(Number); webmidi.noteOn(outputId, ch, p); active.add(k); }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(raf); webmidi.allOff(outputId); };
  }, [tracks, tempo, outputId, audioRef]);
  return null;
}

function Cell({
  span, primary, secondary, active, cellRef, onSeek,
}: {
  span: ChordSpan;
  primary: string;
  secondary: string;
  active: boolean;
  cellRef?: React.RefObject<HTMLDivElement | null>;
  onSeek?: () => void;
}) {
  const bars = span.end_bar - span.start_bar + 1;
  return (
    <div ref={cellRef} className={`chart-cell${active ? " active" : ""}`} data-bars={bars}
      onClick={onSeek} role="button" tabIndex={0}>
      <div className="cell-chord">{primary}</div>
      {secondary && <div className="cell-sub">{secondary}</div>}
      {bars > 1 && <div className="cell-bars">{bars} bars</div>}
    </div>
  );
}
