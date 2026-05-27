/*
    AI Drum Kit — our own native drum instrument (a built-in Tracktion synth).

    Maps General-MIDI drum notes (what the generator's drum patterns use) to
    fully synthesized percussion, so drums are a normal MIDI track like every
    other part — editable, regenerate-able, and routed through the same channel
    strip — instead of a rendered WAV.

      Kick   sine with a fast pitch drop + amp decay
      Snare  tonal body + noise, short decay
      Hats   high-passed noise (closed = tight, open = long)
      Toms   pitched sine by note
      Clap / Crash / Ride  shaped noise

    Two macros: Tone (brightness of the noise/hat content) and Decay (scales the
    hit lengths).
*/

#pragma once

#include <tracktion_engine/tracktion_engine.h>
#include <cmath>

namespace tewk
{

namespace te = tracktion;

struct DrumShared { float tone = 0.5f, decay = 0.5f; };

struct AIDrumSound : public juce::SynthesiserSound
{
    bool appliesToNote (int) override    { return true; }
    bool appliesToChannel (int) override { return true; }
};

//==============================================================================
class AIDrumVoice : public juce::SynthesiserVoice
{
public:
    explicit AIDrumVoice (const DrumShared& s) : shared (s) {}

    bool canPlaySound (juce::SynthesiserSound* s) override { return dynamic_cast<AIDrumSound*> (s) != nullptr; }

    void setCurrentPlaybackSampleRate (double sr) override { juce::SynthesiserVoice::setCurrentPlaybackSampleRate (sr); }

    void startNote (int midiNote, float velocity, juce::SynthesiserSound*, int) override
    {
        level = 0.2f + 0.8f * velocity;
        t = 0.0;
        phase = 0.0;
        hpState = 0.0f;
        active = true;
        configure (midiNote);
    }

    void stopNote (float, bool) override {}   // one-shots ignore note-off; they decay out
    void pitchWheelMoved (int) override {}
    void controllerMoved (int, int) override {}

    void renderNextBlock (juce::AudioBuffer<float>& out, int startSample, int numSamples) override
    {
        if (! active) return;
        const double sr = getSampleRate();
        const float decayScale = 0.5f + shared.decay * 1.5f;          // Decay macro
        const float ampTau = ampDecay * decayScale;
        const float hp = hpCut * (0.5f + shared.tone);                // Tone macro brightens

        auto* L = out.getWritePointer (0, startSample);
        auto* R = out.getNumChannels() > 1 ? out.getWritePointer (1, startSample) : nullptr;

        for (int i = 0; i < numSamples; ++i)
        {
            const float env = std::exp (- (float) t / juce::jmax (0.005f, ampTau));
            if (env < 0.0008f) { active = false; clearCurrentNote(); break; }

            float s = 0.0f;
            if (tonal > 0.0f)
            {
                const float f = freqEnd + (freqStart - freqEnd) * std::exp (- (float) t / juce::jmax (0.002f, pitchTau));
                phase += f / sr; if (phase >= 1.0) phase -= 1.0;
                s += tonal * std::sin (juce::MathConstants<float>::twoPi * (float) phase);
            }
            if (noiseAmt > 0.0f)
            {
                const float white = rng.nextFloat() * 2.0f - 1.0f;
                if (hp > 0.0f)
                {
                    const float a = juce::jlimit (0.0f, 0.999f, hp / (float) sr);   // crude 1-pole HP
                    hpState += a * (white - hpState);
                    s += noiseAmt * (white - hpState);
                }
                else s += noiseAmt * white;
            }

            s *= env * level * 0.6f;
            L[i] += s;
            if (R != nullptr) R[i] += s;
            t += 1.0 / sr;
        }
    }

private:
    void configure (int note)
    {
        // sensible defaults, then per-note overrides
        freqStart = 200.0f; freqEnd = 200.0f; pitchTau = 0.02f; ampDecay = 0.18f;
        tonal = 0.0f; noiseAmt = 0.0f; hpCut = 0.0f;

        switch (note)
        {
            case 35: case 36:                       // kick
                freqStart = 145.0f; freqEnd = 48.0f; pitchTau = 0.035f; ampDecay = 0.20f; tonal = 1.0f; break;
            case 37:                                 // rim
                freqStart = freqEnd = 420.0f; ampDecay = 0.05f; tonal = 0.7f; noiseAmt = 0.4f; hpCut = 3000.0f; break;
            case 38: case 40:                        // snare
                freqStart = freqEnd = 190.0f; ampDecay = 0.16f; tonal = 0.5f; noiseAmt = 0.7f; hpCut = 1200.0f; break;
            case 39:                                 // clap
                ampDecay = 0.18f; noiseAmt = 1.0f; hpCut = 1500.0f; break;
            case 42: case 44:                        // closed hat
                ampDecay = 0.045f; noiseAmt = 1.0f; hpCut = 7000.0f; break;
            case 46:                                 // open hat
                ampDecay = 0.34f; noiseAmt = 1.0f; hpCut = 6500.0f; break;
            case 49: case 52: case 55: case 57:      // crash
                ampDecay = 0.9f; noiseAmt = 1.0f; hpCut = 5000.0f; break;
            case 51: case 53: case 59:               // ride
                freqStart = freqEnd = 520.0f; ampDecay = 0.5f; tonal = 0.25f; noiseAmt = 0.8f; hpCut = 6000.0f; break;
            case 41: case 43: case 45: case 47: case 48: case 50:  // toms (low->high)
            {
                const float f = 90.0f + (float) (note - 41) * 22.0f;
                freqStart = f * 1.3f; freqEnd = f; pitchTau = 0.05f; ampDecay = 0.30f; tonal = 1.0f; noiseAmt = 0.05f; break;
            }
            default:                                 // anything else: a soft tom
                freqStart = 180.0f; freqEnd = 140.0f; ampDecay = 0.2f; tonal = 0.8f; break;
        }
    }

    const DrumShared& shared;
    juce::Random rng;
    double t = 0.0, phase = 0.0;
    float level = 1.0f, hpState = 0.0f;
    float freqStart = 200, freqEnd = 200, pitchTau = 0.02f, ampDecay = 0.18f, tonal = 0, noiseAmt = 0, hpCut = 0;
    bool active = false;
};

//==============================================================================
class AIDrumKitPlugin : public te::Plugin
{
public:
    explicit AIDrumKitPlugin (te::PluginCreationInfo info) : te::Plugin (info)
    {
        auto* um = getUndoManager();
        toneValue.referTo  (state, juce::Identifier ("drumTone"),  um, 0.5f);
        decayValue.referTo (state, juce::Identifier ("drumDecay"), um, 0.5f);
        tone  = addParam ("tone",  TRANS("Tone"),  { 0.0f, 1.0f });
        decay = addParam ("decay", TRANS("Decay"), { 0.0f, 1.0f });
        tone->attachToCurrentValue (toneValue);
        decay->attachToCurrentValue (decayValue);

        for (int i = 0; i < 12; ++i) synth.addVoice (new AIDrumVoice (shared));
        synth.addSound (new AIDrumSound());
        synth.setNoteStealingEnabled (true);
    }

    ~AIDrumKitPlugin() override
    {
        tone->detachFromCurrentValue();
        decay->detachFromCurrentValue();
        notifyListenersOfDeletion();
    }

    static inline const char* xmlTypeName = "ai_drumkit";

    juce::String getName() const override             { return "AI Drum Kit"; }
    juce::String getPluginType() override             { return xmlTypeName; }
    juce::String getSelectableDescription() override  { return "AI Drum Kit (built-in instrument)"; }
    bool takesAudioInput() override                   { return false; }
    bool takesMidiInput() override                    { return true; }
    bool isSynth() override                           { return true; }
    bool producesAudioWhenNoAudioInput() override     { return true; }
    int  getNumOutputChannelsGivenInputs (int) override { return 2; }

    void initialise (const te::PluginInitialisationInfo& info) override { synth.setCurrentPlaybackSampleRate (info.sampleRate); }
    void deinitialise() override {}
    void reset() override { synth.allNotesOff (0, false); }

    void applyToBuffer (const te::PluginRenderContext& fc) override
    {
        if (fc.destBuffer == nullptr) return;
        shared.tone  = tone->getCurrentValue();
        shared.decay = decay->getCurrentValue();

        juce::MidiBuffer midi;
        if (fc.bufferForMidiMessages != nullptr)
            for (auto m : *fc.bufferForMidiMessages)
            {
                const int sp = juce::roundToInt (m.getTimeStamp() * sampleRate) - fc.bufferStartSample;
                if (sp >= 0 && sp < fc.bufferNumSamples) midi.addEvent (m, sp);
            }

        juce::AudioBuffer<float> tmp (2, fc.bufferNumSamples);
        tmp.clear();
        synth.renderNextBlock (tmp, midi, 0, fc.bufferNumSamples);

        const int nch = fc.destBuffer->getNumChannels();
        if (nch >= 1) fc.destBuffer->copyFrom (0, fc.bufferStartSample, tmp, 0, 0, fc.bufferNumSamples);
        if (nch >= 2) fc.destBuffer->copyFrom (1, fc.bufferStartSample, tmp, 1, 0, fc.bufferNumSamples);
        for (int ch = 2; ch < nch; ++ch) fc.destBuffer->clear (ch, fc.bufferStartSample, fc.bufferNumSamples);
    }

    te::AutomatableParameter::Ptr tone, decay;

private:
    juce::Synthesiser synth;
    DrumShared shared;
    juce::CachedValue<float> toneValue, decayValue;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AIDrumKitPlugin)
};

} // namespace tewk
