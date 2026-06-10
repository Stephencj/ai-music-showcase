// Minimal Web MIDI wrapper: stream a block's notes to a hardware/virtual MIDI
// output in real time. Web MIDI works in Chrome/Edge (incl. Windows); Safari
// has no Web MIDI. Requires a user gesture to request access.

export interface MidiOut { id: string; name: string }

// Minimal shapes (Web MIDI types aren't in every TS lib target).
type RawOutput = { id: string; name: string | null; send: (data: number[]) => void };
type Access = {
  outputs: Map<string, RawOutput>;
  onstatechange: ((e: unknown) => void) | null;
};

let access: Access | null = null;

export function midiSupported(): boolean {
  return typeof navigator !== "undefined" && "requestMIDIAccess" in navigator;
}

/** Request MIDI access (prompts the user the first time) and return outputs. */
export async function initMidi(): Promise<MidiOut[]> {
  if (!midiSupported()) {
    throw new Error("Web MIDI isn't available in this browser — use Chrome or Edge.");
  }
  if (!access) {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    access = await (navigator as any).requestMIDIAccess({ sysex: false });
  }
  return listOutputs();
}

export function listOutputs(): MidiOut[] {
  if (!access) return [];
  return Array.from(access.outputs.values()).map((o) => ({ id: o.id, name: o.name || o.id }));
}

export function onStateChange(cb: () => void) {
  if (access) access.onstatechange = () => cb();
}

function out(id: string): RawOutput | null {
  return access?.outputs.get(id) ?? null;
}

export function noteOn(id: string, ch: number, pitch: number, vel = 100) {
  out(id)?.send([0x90 | (ch & 0x0f), pitch & 0x7f, vel & 0x7f]);
}
export function noteOff(id: string, ch: number, pitch: number) {
  out(id)?.send([0x80 | (ch & 0x0f), pitch & 0x7f, 0]);
}
/** Panic: all-notes-off + all-sound-off on every channel. */
export function allOff(id: string) {
  const o = out(id);
  if (!o) return;
  for (let ch = 0; ch < 16; ch++) {
    o.send([0xb0 | ch, 123, 0]); // All Notes Off
    o.send([0xb0 | ch, 120, 0]); // All Sound Off
  }
}

/**
 * Assign each track a MIDI channel: drums → channel 10 (index 9, GM standard),
 * the rest fill 1,2,3… skipping the drum channel, wrapping at 16.
 */
export function channelsFor(isDrum: boolean[]): number[] {
  let next = 0;
  return isDrum.map((d) => {
    if (d) return 9;
    let c = next++;
    if (c === 9) c = next++;
    return c % 16;
  });
}
