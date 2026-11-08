import { useRef, useState } from "react";
import * as api from "../api";

const canRecord = () =>
  typeof navigator !== "undefined" && !!navigator.mediaDevices?.getUserMedia
  && typeof window !== "undefined" && "MediaRecorder" in window;

/**
 * The Create input: a text box, an optional voice note (transcribed by the
 * gateway's speech-to-text into the box, so you can check it before
 * sending) and send. Quick-change chips above it send their phrase as
 * feedback. Pinned above the tab bar.
 */
export default function Composer({
  placeholder, label, busy, onSend, chips, chipsEnabled, voice = true, testid,
}: {
  placeholder: string;
  label: string;
  busy: boolean;
  onSend: (text: string) => void;
  chips?: string[];
  chipsEnabled?: boolean;
  voice?: boolean;
  testid: string;
}) {
  const [text, setText] = useState("");
  const [recording, setRecording] = useState(false);
  const [transcribing, setTranscribing] = useState(false);
  const [voiceErr, setVoiceErr] = useState<string | null>(null);
  const rec = useRef<MediaRecorder | null>(null);
  const chunks = useRef<Blob[]>([]);

  function submit() {
    const t = text.trim();
    if (!t || busy) return;
    onSend(t);
    setText("");
  }

  async function toggleVoice() {
    setVoiceErr(null);
    if (recording) { rec.current?.stop(); setRecording(false); return; }
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mr = new MediaRecorder(stream);
      chunks.current = [];
      mr.ondataavailable = (e) => { if (e.data.size) chunks.current.push(e.data); };
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop());
        const blob = new Blob(chunks.current, { type: mr.mimeType || "audio/webm" });
        if (!blob.size) return;
        setTranscribing(true);
        try {
          const said = await api.transcribe(blob);
          if (said) setText((cur) => (cur.trim() ? cur.trim() + " " : "") + said);
          else setVoiceErr("Didn't catch that — try again.");
        } catch (e) {
          setVoiceErr(String(e).includes("503") || String(e).includes("unavailable")
            ? "Speech-to-text isn't available right now." : String(e));
        } finally {
          setTranscribing(false);
        }
      };
      mr.start();
      rec.current = mr;
      setRecording(true);
    } catch (e) {
      setVoiceErr("Microphone access failed: " + String(e));
    }
  }

  return (
    <div className="ws-composer">
      <div className="inner">
        {chips && chips.length > 0 && (
          <div className="ws-quick" role="group" aria-label="Quick changes">
            {chips.map((c) => (
              <button key={c} type="button" className="ws-quick-chip" disabled={!chipsEnabled || busy}
                data-testid={`quick-${c.toLowerCase().replace(/\s+/g, "-")}`}
                onClick={() => onSend(c)}>{c}</button>
            ))}
          </div>
        )}
        {(voiceErr || recording || transcribing) && (
          <div className={"ws-voice-note" + (voiceErr ? " err" : "")} role="status">
            {voiceErr ?? (recording ? "Listening… tap the mic again to stop" : "Transcribing…")}
          </div>
        )}
        <form className="ws-input-row" onSubmit={(e) => { e.preventDefault(); submit(); }}>
          <label className="sr-only" htmlFor={testid}>{label}</label>
          <input id={testid} data-testid={testid} className="ws-input" value={text}
            placeholder={placeholder} autoComplete="off" enterKeyHint="send"
            onChange={(e) => setText(e.target.value)} />
          {voice && canRecord() && (
            <button type="button" className={"ws-round" + (recording ? " rec" : "")}
              aria-label={recording ? "Stop recording" : "Record voice note"} aria-pressed={recording}
              disabled={transcribing} data-testid="voice-note" onClick={toggleVoice}>
              <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3" /><path d="M5 11a7 7 0 0 0 14 0M12 18v3" /></svg>
            </button>
          )}
          <button type="submit" className="ws-round send" aria-label="Send"
            disabled={busy || !text.trim()} data-testid={testid + "-send"}>
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true"><path d="M12 19V5" /><path d="M5 12l7-7 7 7" /></svg>
          </button>
        </form>
      </div>
    </div>
  );
}
