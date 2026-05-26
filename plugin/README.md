# AI Part Bank — VST3 / AU plugin

A per-channel **bank of generated parts**. It's an **effect**, not an instrument,
so your real instrument stays on the channel. Each **Generate** calls the local
Music Producer backend (`POST /api/generate-part`) and adds an item to the bank
— MIDI + a rendered WAV + the note list, labelled by its settings. You can
audition items, **drag** the MIDI/WAV onto tracks, and the bank **saves with the
project**.

Two variants are built from one codebase:

| | **AI Part Bank** (Audio-FX) | **AI Part Bank (MIDI FX)** |
|---|---|---|
| Where it goes | Insert on **any** channel — instrument or audio | MIDI-FX slot, **before** an instrument |
| Audition | Plays the item's **WAV** through the plugin (layered) | **Arms** the item; its notes play **through your instrument** on the host timeline |
| Drag MIDI / WAV out | ✅ | ✅ (MIDI is the point; WAV still draggable) |
| Your real instrument | untouched | the one this feeds |

## Build (macOS)
CMake ≥ 3.22 + Xcode command-line tools. JUCE is fetched automatically.
```bash
cd plugin
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j
```
Both variants auto-install to `~/Library/Audio/Plug-Ins/` (VST3 + AU). The
Audio-FX variant also builds a Standalone app for quick testing.

For **Cakewalk (Windows)**, build the same project on Windows (the source is
cross-platform → Windows VST3).

## Use
1. Make sure **Music Producer is running** (`http://127.0.0.1:7860`).
2. Insert the plugin on a track:
   - **Audio-FX** → an insert/audio-FX slot (any track). Your instrument stays.
   - **MIDI-FX** → the MIDI-FX slot *before* the instrument.
3. Set **Part** (chords/bass/melody/lead/drums) + **Key/Tempo/Bars**, optional
   **Style**, the per-part modifier dropdowns (Voicing/Rhythm/Pattern/Style/
   Phrase), and a **Chords** progression (`I V vi IV`; blank = key default).
4. **Generate** → a new item appears in the **Bank**.
5. Per bank item:
   - **Audio-FX:** **Play** auditions its WAV. Drag **MIDI** onto your
     instrument track / **WAV** onto an audio track. **x** deletes.
   - **MIDI-FX:** **Arm** it, then press play in your DAW — its notes drive the
     instrument on this channel, looping to a whole bar. Drag still works.

`Server` defaults to `http://127.0.0.1:7860`. The bank's artifacts live under
`~/Library/Application Support/AI Part Bank/` and are referenced from the saved
project state.

## Notes
- MIDI-FX live emit is timed to the host transport and loops to the part's bar
  length — the newer, less-tested path; the drag-out works regardless.
- Reading the *other* channels for richer style-fit needs Ableton Suite's Max
  for Live (deferred). The backend `/api/generate-part` is host-agnostic and
  tested, so every front-end shares the same brain.
