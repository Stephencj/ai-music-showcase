#pragma once

#include <juce_audio_processors/juce_audio_processors.h>

/**
    AI Part Generator — a thin bridge plugin.

    It doesn't synthesize anything itself; it calls the local Music Producer
    backend (POST /api/generate-part) to generate ONE part that fits the
    musical context you set, then exposes the resulting MIDI + rendered WAV so
    you can drag them onto the channel (works in every DAW). The heavy lifting
    (composition, soundfont render) stays in the Python backend on :7860.
*/
class AIPartGeneratorProcessor : public juce::AudioProcessor
{
public:
    AIPartGeneratorProcessor();
    ~AIPartGeneratorProcessor() override = default;

    void prepareToPlay (double, int) override {}
    void releaseResources() override {}
    void processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer&) override
    {
        buffer.clear();   // v1: generation is offline; delivery is via drag-out
    }

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return "AI Part Generator"; }
    bool acceptsMidi() const override { return false; }
    bool producesMidi() const override { return true; }
    bool isMidiEffect() const override { return false; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock&) override;
    void setStateInformation (const void*, int) override;

    // ---- generation -------------------------------------------------------
    struct GenResult
    {
        bool ok = false;
        juce::String message;
        juce::File midiFile;     // downloaded .mid for drag-out
        juce::File wavFile;      // downloaded .wav/.mp3 for drag-out
        int nNotes = 0;
    };

    // Generation settings (set by the editor). Kept plain (not host-automated).
    juce::String serverBase { "http://127.0.0.1:7860" };
    juce::String target { "melody" };   // chords|bass|melody|lead|drums
    juce::String key { "C" };
    juce::String scale { "major" };
    juce::String genre {};              // optional style preset id
    juce::String progression {};        // e.g. "I V vi IV" ("" = key default)
    double tempo { 120.0 };
    int bars { 4 };

    // Blocking HTTP round-trip — call from a background thread.
    GenResult generate();

private:
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AIPartGeneratorProcessor)
};
