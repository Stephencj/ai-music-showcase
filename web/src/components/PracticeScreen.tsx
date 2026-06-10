import { useEffect, useMemo, useRef, useState } from "react";
import * as api from "../api";
import type { ScoreData, ChordSpan } from "../api";
import type { Block, Preset } from "../types";
import ChordDiagram, { LiveDiagram } from "./ChordDiagram";
import TapeView from "./TapeView";
import NotationRoll, { type RollNote } from "./NotationRoll";
import SheetMusic from "./SheetMusic";
import TabView from "./TabView";
import WindTabView from "./WindTabView";
import { isFrettedTrack, isGuitarTrack, isKeysTrack, stringLabelsFor, assignFrets,
  detectInstrumentId, instrumentById, instrumentFor, STRING_INSTRUMENTS } from "../guitarTab";
import type { TabNote } from "../guitarTab";
import { DrumDiagram, FingeringDiagram } from "./InstrumentDiagrams";
import CircleOfFifths from "./CircleOfFifths";
import { familyFor, voiceSpecsFor, voiceLine } from "../instruments";
import PickerField from "./PickerField";
import InstrumentIcon from "./InstrumentIcon";
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

export default function PracticeScreen({ isActive }: { isActive?: boolean }) {
  const [mode, setMode] = useState<Mode>("block");
  const [blocks, setBlocks] = useState<Block[]>([]);
  const [songs, setSongs] = useState<string[]>([]);
  // Picker value, prefixed: "block:<name>" or "song:<title>".
  const [selected, setSelected] = useState<string>("");
  const [presets, setPresets] = useState<Preset[]>([]);

  const [score, setScore] = useState<ScoreData | null>(null);
  // Per-track notes for the notation roll + real-time diagrams (blocks only).
  const [partNotes, setPartNotes] = useState<BlockNotes | null>(null);
  // Live diagrams: a dynamic list of piano / guitar-neck cards, each bound to a
  // part (channel). Defaults to one piano + one guitar; add/remove as needed.
  type LiveKind = "piano" | "neck" | "drums" | "brass" | "woodwind";
  const [liveSlots, setLiveSlots] = useState<{ id: number; kind: LiveKind; partIdx: number; instId?: string }[]>([]);
  const slotId = useRef(1);
  const [chartIdx, setChartIdx] = useState(-1);  // score section part (-1 = chords only)
  const [solo, setSolo] = useState(false);       // play just the chart part
  const [tabMember, setTabMember] = useState(0); // which ensemble member the wind tab shows
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
  const [showCircle, setShowCircle] = useState(false);

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

  // Re-pull blocks/songs when this tab becomes active, so blocks generated or
  // saved in another tab appear here (the current selection/score is kept).
  useEffect(() => {
    if (!isActive) return;
    api.getBlocks().then((bs) => setBlocks(bs.filter((b) => b.has_preview))).catch(() => {});
    api.listSongs().then((r) => setSongs(r.songs || [])).catch(() => {});
  }, [isActive]);

  useEffect(() => {
    try { localStorage.setItem("practice.panels", JSON.stringify(panels)); } catch { /* ignore */ }
  }, [panels]);

  // Block mode: load score + audio for the selected block OR song.
  useEffect(() => {
    if (mode !== "block" || !selected) return;
    setLoading(true); setScore(null); setErr(""); setT(0); setLoop("off");
    setPartNotes(null); setLiveSlots([]); setChartIdx(-1); setSolo(false);
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

  // Seed defaults once notes arrive: a piano card on the first keyboard part and
  // a guitar card on the first guitar part; chart → first fretted part.
  useEffect(() => {
    if (!partNotes) return;
    const ts = partNotes.tracks;
    const firstMel = ts.findIndex((t) => !t.is_drum);
    const firstKeys = ts.findIndex((t) => !t.is_drum && isKeysTrack(t.track));
    const firstGtr = ts.findIndex((t) => isGuitarTrack(t.track));
    const firstFret = ts.findIndex((t) => !t.is_drum && isFrettedTrack(t.track));
    setLiveSlots([
      { id: slotId.current++, kind: "piano", partIdx: firstKeys >= 0 ? firstKeys : firstMel },
      { id: slotId.current++, kind: "neck", partIdx: firstGtr >= 0 ? firstGtr : firstFret >= 0 ? firstFret : firstMel },
    ]);
    setChartIdx(firstFret >= 0 ? firstFret : firstGtr >= 0 ? firstGtr : firstMel);
  }, [partNotes]);

  function addSlot(kind: LiveKind) {
    const ts = partNotes?.tracks ?? [];
    let idx = -1;
    if (kind === "drums") idx = ts.findIndex((t) => t.is_drum);
    else if (kind === "piano") idx = ts.findIndex((t) => !t.is_drum && isKeysTrack(t.track));
    else if (kind === "neck") idx = ts.findIndex((t) => isGuitarTrack(t.track));
    else if (kind === "brass") idx = ts.findIndex((t) => !t.is_drum && familyFor(t.track, false) === "brass");
    else if (kind === "woodwind") idx = ts.findIndex((t) => !t.is_drum && familyFor(t.track, false) === "woodwind");
    if (idx < 0) idx = ts.findIndex((t) => (kind === "drums" ? t.is_drum : !t.is_drum));
    if (idx < 0) idx = ts.findIndex((t) => !t.is_drum);
    setLiveSlots((s) => [...s, { id: slotId.current++, kind, partIdx: idx }]);
  }

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
  // Drum tracks (for a drums diagram's part picker).
  const drumOptions = useMemo(
    () => (partNotes?.tracks ?? []).map((t, idx) => ({ idx, name: t.track, is_drum: t.is_drum }))
      .filter((p) => p.is_drum),
    [partNotes]);

  const chartTrack = partNotes && chartIdx >= 0 ? partNotes.tracks[chartIdx] : undefined;

  const rollFrom = (tr: typeof chartTrack): RollNote[] => {
    if (!tr || !partNotes || tr.is_drum) return [];
    const spb = 60 / (partNotes.tempo || 120);
    return tr.notes.map(([pitch, sb, db]) => ({ pitch, start: sb * spb, dur: db * spb }));
  };
  // Tab for the score-section (Tab view) — instrument-aware, gated to fretted
  // parts (the chart shows a hint otherwise).
  const tabFrom = (tr: typeof chartTrack) => {
    if (!tr || !partNotes || tr.is_drum || !isFrettedTrack(tr.track)) return null;
    const inst = instrumentFor(tr.track);
    const spb = 60 / (partNotes.tempo || 120);
    const tabNotes = assignFrets(tr.notes, inst.tuning, inst.frets).map((f) => ({ ...f, start: f.start * spb, dur: f.dur * spb }));
    return { name: inst.label, labels: stringLabelsFor(inst.tuning), tabNotes };
  };
  const rangeOf = (ns: RollNote[]): [number, number] | undefined => {
    if (!ns.length) return undefined;
    let lo = 128, hi = 0;
    for (const n of ns) { lo = Math.min(lo, n.pitch); hi = Math.max(hi, n.pitch); }
    return [lo, hi];
  };

  // Per-slot data for the live diagrams. Piano → notes + key range. Neck → the
  // exact tab positions (same as the Tab view) on the instrument's own
  // fingerboard: tuning auto-detected from the part name, overridable per card.
  const slotData = useMemo(() => liveSlots.map((s) => {
    const tr = partNotes && s.partIdx >= 0 ? partNotes.tracks[s.partIdx] : undefined;
    const spb = partNotes ? 60 / (partNotes.tempo || 120) : 0.5;
    const notes = rollFrom(tr);
    const range = s.kind === "piano" ? rangeOf(notes) : undefined;
    let tab: TabNote[] | undefined;
    let tuning: number[] | undefined;
    let frets: number | undefined;
    let instLabel: string | undefined;
    let instId: string | undefined;
    let drumNotes: RollNote[] | undefined;
    let instName: string | undefined;
    if (s.kind === "neck") {
      instId = s.instId || (tr ? detectInstrumentId(tr.track) : "guitar6");
      const inst = instrumentById(instId);
      tuning = inst.tuning; frets = inst.frets; instLabel = inst.label;
      tab = (tr && partNotes && !tr.is_drum)
        ? assignFrets(tr.notes, inst.tuning, inst.frets).map((f) => ({ ...f, start: f.start * spb, dur: f.dur * spb }))
        : [];
    } else if (s.kind === "drums") {
      drumNotes = (tr && tr.is_drum)
        ? tr.notes.map(([pitch, sb, db]) => ({ pitch, start: sb * spb, dur: db * spb }))
        : [];
    } else if (s.kind === "brass" || s.kind === "woodwind") {
      instName = tr?.track ?? "";
    }
    return { slot: s, notes, range, tab, tuning, frets, instLabel, instId, drumNotes, instName };
  }), [liveSlots, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps

  // Score section (sheet / tab / notation roll) follows the chart part.
  const chartRollNotes = useMemo(() => rollFrom(chartTrack), [chartTrack, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps
  const chartTab = useMemo(() => tabFrom(chartTrack), [chartTrack, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps

  // Default the capo from the key when a guitar diagram is on an ACOUSTIC part
  // (its shapes benefit from a capo); otherwise reset to 0. Manual changes
  // persist until the key or the diagram parts change.
  useEffect(() => {
    if (!score) { setCapo(0); return; }
    const acoustic = liveSlots.some((s) => s.kind === "neck"
      && partNotes && s.partIdx >= 0 && /acoustic/i.test(partNotes.tracks[s.partIdx]?.track || ""));
    setCapo(acoustic ? autoCapo(rootPc(score.key)) : 0);
  }, [score?.key, liveSlots, partNotes]); // eslint-disable-line react-hooks/exhaustive-deps

  // For section looping, play the WAV (sample-accurate seeks — no MP3 decoder
  // priming gap), which keeps loops tight without losing pitch-preserved speed.
  const sectionLooping = loop.startsWith("s");

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
          <button className="keymode-pick" onClick={() => setShowCircle(true)}
            title="Pick the key on the circle of fifths">
            ◷ {tonic} {(MODES.find((m) => m.id === keyMode) || MODES[0]).label.split(" ")[0]}
          </button>
          <button
            className="keymode-reset"
            onClick={() => { setTonic(ALL_ROOTS[rootPc(score.key)]); setKeyMode(scaleToModeId(score.scale)); }}
            title="Reset to the detected key"
          >↺</button>
        </div>
      )}
      {showCircle && (
        <CircleOfFifths tonic={tonic} mode={keyMode}
          onTonic={setTonic} onMode={setKeyMode} onClose={() => setShowCircle(false)} />
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

          {panels.diagrams && (partOptions.length > 0 || active?.root) && (
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
              {neckMode ? (
                // Full-neck (live): a list of instrument cards (piano, string
                // fingerboards, drum kit, brass valves/slide, woodwind keys),
                // each on its own part/channel. Add more; remove down to one.
                <>
                  <div className="diagrams diagrams-wide">
                    {slotData.map((d) => {
                      const setPart = (i: number) => setLiveSlots((s) => s.map((x) => x.id === d.slot.id ? { ...x, partIdx: i, instId: undefined } : x));
                      const remove = liveSlots.length > 1
                        ? () => setLiveSlots((s) => s.filter((x) => x.id !== d.slot.id)) : undefined;
                      if (d.slot.kind === "piano" || d.slot.kind === "neck") {
                        return (
                          <LiveDiagram key={d.slot.id} kind={d.slot.kind} notes={d.notes}
                            tab={d.tab} range={d.range}
                            tuning={d.tuning} frets={d.frets} instLabel={d.instLabel}
                            instOptions={d.slot.kind === "neck" ? STRING_INSTRUMENTS : undefined}
                            instId={d.instId}
                            onInst={(id) => setLiveSlots((s) => s.map((x) => x.id === d.slot.id ? { ...x, instId: id } : x))}
                            audioRef={playhead} parts={partOptions} partIdx={d.slot.partIdx}
                            onPartIdx={setPart} onRemove={remove} />
                        );
                      }
                      // drums / brass / woodwind: card wrapper + the figure
                      const opts = d.slot.kind === "drums" ? drumOptions : partOptions;
                      const title = d.slot.kind === "drums" ? "Drums"
                        : (d.instName || (d.slot.kind === "brass" ? "Brass" : "Woodwind"));
                      return (
                        <div key={d.slot.id} className="diagram-card">
                          <div className="diagram-title">
                            <span>{title}</span>
                            <span className="dc-head-ctl">
                              <PickerField value={String(d.slot.partIdx)} label="Part" placeholder="—"
                                fullWidth={false} className="part-pick"
                                options={opts.map((o) => ({ id: String(o.idx), label: o.name,
                                  icon: <InstrumentIcon name={o.name} size={15} /> }))}
                                onChange={(id) => setPart(Number(id))} />
                              {remove && <button className="dc-remove" onClick={remove} aria-label="Remove">✕</button>}
                            </span>
                          </div>
                          {d.slot.kind === "drums"
                            ? <DrumDiagram notes={d.drumNotes || []} audioRef={playhead} />
                            : <FingeringDiagram notes={d.notes} audioRef={playhead}
                                members={voiceSpecsFor(d.instName || "")}
                                onPickMember={blockName ? (mi) => {
                                  setChartIdx(d.slot.partIdx); setTabMember(mi); setSolo(false); setView("tab");
                                } : undefined} />}
                        </div>
                      );
                    })}
                  </div>
                  <div className="diagram-add">
                    <span className="diagram-add-label">+ Add:</span>
                    <button className="btn ghost sm" onClick={() => addSlot("piano")}>Piano</button>
                    <button className="btn ghost sm" onClick={() => addSlot("neck")}>Guitar</button>
                    <button className="btn ghost sm" onClick={() => addSlot("drums")}>Drums</button>
                    <button className="btn ghost sm" onClick={() => addSlot("brass")}>Brass</button>
                    <button className="btn ghost sm" onClick={() => addSlot("woodwind")}>Woodwind</button>
                  </div>
                </>
              ) : (
                <ChordDiagram
                  root={active?.root || "C"}
                  quality={active?.quality || "maj"}
                  capo={capo}
                />
              )}
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
              <div className="chart-part">
                <PickerField value={String(chartIdx)} label="Part to notate" placeholder="Pick a part"
                  fullWidth={false} className="part-pick"
                  options={partOptions.map((p) => ({ id: String(p.idx), label: p.name,
                    icon: <InstrumentIcon name={p.name} size={15} /> }))}
                  onChange={(id) => { setChartIdx(Number(id)); setSolo(false); }} />
                <label className="part-solo">
                  <input type="checkbox" checked={solo} onChange={(e) => setSolo(e.target.checked)} /> Solo
                </label>
              </div>
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
                : (() => {
                    // No fret tab → if it's a wind/brass part, show the wind
                    // "tab" (valve/slide/key lane). A section is an ensemble, so
                    // we tab ONE member at a time — pick which with the chooser.
                    const fam = chartTrack ? familyFor(chartTrack.track, !!chartTrack.is_drum) : null;
                    const specs = chartTrack ? voiceSpecsFor(chartTrack.track) : [];
                    if (fam === "brass" || fam === "woodwind") {
                      const isEnsemble = specs.length > 1;
                      const mi = Math.min(tabMember, specs.length - 1);
                      const ms = specs[mi];
                      // Section → extract that member's line; solo → the part as-is.
                      const lane = isEnsemble ? voiceLine(chartRollNotes, mi, specs.length) : chartRollNotes;
                      const title = (
                        <span className="wtab-title-in">
                          <InstrumentIcon name={ms.label} size={18} />
                          {isEnsemble ? `${chartTrack!.track} · ${ms.label}` : chartTrack!.track} — fingering tab
                        </span>
                      );
                      const control = isEnsemble ? (
                        <PickerField value={String(mi)} label="Tab which instrument"
                          fullWidth={false} className="tab-member"
                          options={specs.map((s, i) => ({
                            id: String(i), label: s.label,
                            icon: <InstrumentIcon name={s.label} size={16} />,
                          }))}
                          onChange={(id) => setTabMember(Number(id))} />
                      ) : null;
                      return (
                        <div className="tab-card">
                          <WindTabView notes={lane} audioRef={playhead}
                            kind={ms.kind} transpose={ms.transpose} title={title} control={control} />
                        </div>
                      );
                    }
                    return <div className="practice-hint">This part isn't a guitar or bass — pick a fretted part above to tab it.</div>;
                  })()
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
