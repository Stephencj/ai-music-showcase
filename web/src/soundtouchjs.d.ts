// Minimal type surface for the bits of soundtouchjs we use. The package
// ships an ESM dist with no .d.ts; we only touch PitchShifter.
declare module "soundtouchjs" {
  export class PitchShifter {
    constructor(context: BaseAudioContext, buffer: AudioBuffer, bufferSize?: number);
    tempo: number;
    pitch: number;
    pitchSemitones: number;
    rate: number;
    percentagePlayed: number;
    readonly duration: number;
    readonly node: AudioNode;
    readonly timePlayed: number;
    connect(node: AudioNode): void;
    disconnect(): void;
    on(event: string, cb: (detail: { timePlayed: number; percentagePlayed: number }) => void): void;
    off(event?: string): void;
  }
}
