#pragma once

#include <juce_audio_utils/juce_audio_utils.h>

#ifndef AIPG_MIDI_FX
 #define AIPG_MIDI_FX 0
#endif

/**
    AI Part Bank — a per-channel bank of generated parts.

    An EFFECT (not an instrument), so your real instrument stays on the channel.
    Each Generate calls the local backend (POST /api/generate-part) and adds an
    item to the bank (MIDI + rendered WAV + the note list, labelled by its
    settings). You can audition items, drag the MIDI/WAV onto tracks, and the
    bank saves with the project.

    Two build variants from one codebase (AIPG_MIDI_FX):
      * Audio-FX (0): insert on any channel; auditioning plays the item's WAV
        through the plugin's output (layered over the channel).
      * MIDI-FX  (1): sits before an instrument; the "armed" item's notes are
        emitted on the host timeline so they play THROUGH your instrument.
*/
struct BankNote { int pitch = 60; double startBeat = 0.0; double durBeat = 0.5; };

struct BankItem
{
    juce::String id, label, target;
    juce::File   midiFile, wavFile;
    std::vector<BankNote> notes;
    double tempo = 120.0;
    int    beatsPerBar = 4;
    int    nNotes = 0;
};

class AIPartBankProcessor : public juce::AudioProcessor
{
public:
    AIPartBankProcessor();
    ~AIPartBankProcessor() override;

    void prepareToPlay (double sampleRate, int samplesPerBlock) override;
    void releaseResources() override;
    void processBlock (juce::AudioBuffer<float>&, juce::MidiBuffer&) override;

    juce::AudioProcessorEditor* createEditor() override;
    bool hasEditor() const override { return true; }

    const juce::String getName() const override { return JucePlugin_Name; }
    bool acceptsMidi() const override  { return AIPG_MIDI_FX; }
    bool producesMidi() const override { return AIPG_MIDI_FX; }
    bool isMidiEffect() const override { return AIPG_MIDI_FX; }
    double getTailLengthSeconds() const override { return 0.0; }

    int getNumPrograms() override { return 1; }
    int getCurrentProgram() override { return 0; }
    void setCurrentProgram (int) override {}
    const juce::String getProgramName (int) override { return {}; }
    void changeProgramName (int, const juce::String&) override {}

    void getStateInformation (juce::MemoryBlock&) override;
    void setStateInformation (const void*, int) override;

    // ---- generation settings (set by editor) ------------------------------
    juce::String serverBase { "http://127.0.0.1:7860" };
    juce::String target { "melody" }, key { "C" }, scale { "major" }, genre {};
    juce::String progression {};
    double tempo { 120.0 };
    int    bars { 4 };
    juce::String voicing, chordRhythm, bassPattern, drumPattern, melodyStyle, phraseShape;
    int    octave { -1 };          // -1 = unset (engine default); chords/bass/melody/lead
    double noteDensity { -1.0 };   // -1 = unset; bass/melody/lead/drums (0–1)

    // ---- the bank (message-thread owned) ----------------------------------
    juce::OwnedArray<BankItem> bank;     // accessed only on the message thread

    struct GenResult { bool ok = false; juce::String message; std::unique_ptr<BankItem> item; };
    GenResult generate();                // blocking HTTP — call on a bg thread
    juce::var  fetchOptions();           // GET /api/part-options

    // ---- auditioning ------------------------------------------------------
    void playItem (const BankItem& item);   // audio-FX: stream its WAV
    void armItem  (const BankItem* item);    // MIDI-FX: emit its notes (nullptr = off)
    void stopPlayback();
    bool isPlaying() const;

    static juce::File bankDir();         // persistent storage for the artifacts

private:
    // audio-FX WAV playback
    juce::AudioFormatManager formatManager;
    std::unique_ptr<juce::AudioFormatReaderSource> readerSource;
    juce::AudioTransportSource transport;
    juce::AudioBuffer<float> scratch;
    double sampleRate { 44100.0 };

    // MIDI-FX emit
    struct MidiEv { double beat; bool noteOn; int pitch; };
    juce::CriticalSection emitLock;
    std::vector<MidiEv> armedEvents;     // guarded by emitLock
    double loopBeats { 0.0 };
    bool   wasPlaying { false };

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AIPartBankProcessor)
};
