# AI Part Generator — VST3 / AU plugin

A thin **bridge** plugin: it doesn't synthesize anything itself — it calls the
local Music Producer backend (`POST /api/generate-part` on `:7860`) to generate
**one part that fits** the musical context you set, then lets you **drag the
resulting MIDI and rendered WAV onto a track**. The composition + render stay in
the Python backend; the plugin is just UI + DAW I/O.

Loads in **Ableton Live (incl. Intro), Logic Pro (AU), and Cakewalk (VST3)** —
the common-denominator path, since those DAWs don't let a plugin read other
tracks' MIDI. (The richer "read every track" version needs Ableton **Suite**'s
Max for Live — deferred.)

## Build (macOS)
Requires CMake ≥ 3.22 and a C++ toolchain (Xcode command-line tools). JUCE is
fetched automatically.

```bash
cd plugin
cmake -B build -DCMAKE_BUILD_TYPE=Release
cmake --build build --config Release -j
```

Outputs (copied to your user plugin folders automatically via
`COPY_PLUGIN_AFTER_BUILD`):
- VST3 → `~/Library/Audio/Plug-Ins/VST3/AI Part Generator.vst3`
- AU   → `~/Library/Audio/Plug-Ins/Components/AI Part Generator.component`
- a Standalone app under `build/` for quick testing without a DAW.

In Logic/Live you may need to rescan plugins (Live trusts new VST3/AU after a
restart; Logic runs `auval` on first launch).

## Use
1. Make sure **Music Producer is running** (the backend on `http://127.0.0.1:7860`).
2. Insert **AI Part Generator** on a track (as an instrument).
3. Pick the **Part** (chords / bass / melody / lead / drums), set **Key**,
   **Tempo**, **Bars**, an optional **Style**, and a **Chords** progression in
   roman numerals (e.g. `I V vi IV`; blank = a sensible default for the key).
4. Hit **Generate**. When it finishes, the **MIDI** and **WAV** buttons light
   up — **drag** either onto a track to drop the part in.

`Server` defaults to `http://127.0.0.1:7860`; change it if your backend runs
elsewhere. Settings persist with the project.

## Notes / roadmap
- v1 delivers parts by **drag-out** (universal across DAWs). Live MIDI playthrough
  and host tempo/key auto-fill are planned follow-ups.
- Reading the *other* channels for richer style-fit isn't possible from a generic
  plugin (DAW API limitation); that's the Ableton-Suite / Max-for-Live path.
- The backend endpoint (`/api/generate-part`) is host-agnostic and fully tested,
  so this plugin, a future M4L device, and any script all share the same brain.
