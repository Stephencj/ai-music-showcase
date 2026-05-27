/*
    AI Synth — our own native software instrument, living inside Tracktion Engine
    as a built-in plugin (not an AU we host). This is the foundation for the
    "build our own instruments + ship sound packs" direction: we control the DSP
    end to end, it needs no sample data, and it ships inside the app.

    v1 is a warm polyphonic subtractive synth: two detuned anti-aliased
    (PolyBLEP) sawtooth oscillators per voice → per-voice resonant low-pass
    (TPT state-variable) with key tracking → ADSR amplitude envelope.
*/

#pragma once

#include <tracktion_engine/tracktion_engine.h>
#include <cmath>

namespace tewk
{

namespace te = tracktion;

//==============================================================================
// Zavalishin TPT state-variable low-pass — stable, cheap, sounds analog-ish.
struct TPTLowpass
{
    void setCoefs (float cutoffHz, float sampleRate, float Q) noexcept
    {
        const float wd = juce::MathConstants<float>::twoPi * cutoffHz;
        const float T  = 1.0f / sampleRate;
        const float wa = (2.0f / T) * std::tan (wd * T * 0.5f);   // prewarp
        g  = wa * T * 0.5f;
        R2 = 1.0f / juce::jmax (0.05f, Q);
        h  = 1.0f / (1.0f + R2 * g + g * g);
    }

    float processLP (float x) noexcept
    {
        const float hp = (x - (R2 + g) * s1 - s2) * h;
        const float bp = g * hp + s1;  s1 = g * hp + bp;
        const float lp = g * bp + s2;  s2 = g * bp + lp;
        return lp;
    }

    void reset() noexcept { s1 = s2 = 0.0f; }

    float g = 0.0f, R2 = 1.0f, h = 1.0f, s1 = 0.0f, s2 = 0.0f;
};

//==============================================================================
struct AISynthSound : public juce::SynthesiserSound
{
    bool appliesToNote (int) override    { return true; }
    bool appliesToChannel (int) override { return true; }
};

//==============================================================================
class AISynthVoice : public juce::SynthesiserVoice
{
public:
    bool canPlaySound (juce::SynthesiserSound* s) override
    {
        return dynamic_cast<AISynthSound*> (s) != nullptr;
    }

    void setCurrentPlaybackSampleRate (double sr) override
    {
        juce::SynthesiserVoice::setCurrentPlaybackSampleRate (sr);
        if (sr > 0)
        {
            adsr.setSampleRate (sr);
            adsr.setParameters ({ 0.006f, 0.28f, 0.72f, 0.45f });  // A D S R (seconds / level)
        }
    }

    void startNote (int midiNote, float velocity, juce::SynthesiserSound*, int) override
    {
        freq   = (float) juce::MidiMessage::getMidiNoteInHertz (midiNote);
        level  = 0.12f + 0.88f * velocity;
        phase1 = 0.0; phase2 = 0.5;            // offset phases for a wider start
        const float cutoff = juce::jlimit (220.0f, 9000.0f, 900.0f + freq * 3.5f); // key tracking
        filter.reset();
        filter.setCoefs (cutoff, (float) getSampleRate(), 0.9f);
        adsr.noteOn();
    }

    void stopNote (float, bool allowTailOff) override
    {
        if (allowTailOff)
            adsr.noteOff();
        else
        {
            adsr.reset();
            clearCurrentNote();
        }
    }

    void pitchWheelMoved (int) override {}
    void controllerMoved (int, int) override {}

    void renderNextBlock (juce::AudioBuffer<float>& out, int startSample, int numSamples) override
    {
        if (! adsr.isActive())
            return;

        const double sr    = getSampleRate();
        const double inc1  = freq / sr;
        const double detune = std::pow (2.0, 7.0 / 1200.0);   // +7 cents
        const double inc2  = freq * detune / sr;

        auto* L = out.getWritePointer (0, startSample);
        auto* R = out.getNumChannels() > 1 ? out.getWritePointer (1, startSample) : nullptr;

        for (int i = 0; i < numSamples; ++i)
        {
            const float saw = 0.5f * (polyblepSaw (phase1, inc1) + polyblepSaw (phase2, inc2));
            const float env = adsr.getNextSample();
            const float s   = filter.processLP (saw * env * level * 0.4f);

            L[i] += s;
            if (R != nullptr) R[i] += s;

            phase1 += inc1; if (phase1 >= 1.0) phase1 -= 1.0;
            phase2 += inc2; if (phase2 >= 1.0) phase2 -= 1.0;
        }

        if (! adsr.isActive())
            clearCurrentNote();
    }

private:
    static float polyBLEP (double t, double dt) noexcept
    {
        if (t < dt)           { const double x = t / dt;          return float (x + x - x * x - 1.0); }
        if (t > 1.0 - dt)     { const double x = (t - 1.0) / dt;  return float (x * x + x + x + 1.0); }
        return 0.0f;
    }

    static float polyblepSaw (double phase, double inc) noexcept
    {
        return float (2.0 * phase - 1.0) - polyBLEP (phase, inc);
    }

    juce::ADSR adsr;
    TPTLowpass filter;
    double phase1 = 0.0, phase2 = 0.0;
    float  freq = 440.0f, level = 0.8f;
};

//==============================================================================
class AISynthPlugin : public te::Plugin
{
public:
    explicit AISynthPlugin (te::PluginCreationInfo info) : te::Plugin (info)
    {
        for (int i = 0; i < 16; ++i)
            synth.addVoice (new AISynthVoice());
        synth.addSound (new AISynthSound());
        synth.setNoteStealingEnabled (true);
    }

    ~AISynthPlugin() override { notifyListenersOfDeletion(); }

    static inline const char* xmlTypeName = "ai_synth";

    juce::String getName() const override                { return "AI Synth"; }
    juce::String getPluginType() override                { return xmlTypeName; }
    juce::String getSelectableDescription() override     { return "AI Synth (built-in instrument)"; }

    bool takesAudioInput() override                      { return false; }
    bool takesMidiInput() override                       { return true; }
    bool isSynth() override                              { return true; }
    bool producesAudioWhenNoAudioInput() override        { return true; }
    int  getNumOutputChannelsGivenInputs (int) override  { return 2; }

    void initialise (const te::PluginInitialisationInfo& info) override
    {
        synth.setCurrentPlaybackSampleRate (info.sampleRate);
    }

    void deinitialise() override {}

    void reset() override
    {
        synth.allNotesOff (0, false);
    }

    void applyToBuffer (const te::PluginRenderContext& fc) override
    {
        if (fc.destBuffer == nullptr)
            return;

        juce::MidiBuffer midi;
        if (fc.bufferForMidiMessages != nullptr)
        {
            if (fc.bufferForMidiMessages->isAllNotesOff)
                synth.allNotesOff (0, false);

            for (auto m : *fc.bufferForMidiMessages)
            {
                const int sp = juce::roundToInt (m.getTimeStamp() * sampleRate) - fc.bufferStartSample;
                if (sp >= 0 && sp < fc.bufferNumSamples)
                    midi.addEvent (m, sp);
            }
        }

        juce::AudioBuffer<float> tmp (2, fc.bufferNumSamples);
        tmp.clear();
        synth.renderNextBlock (tmp, midi, 0, fc.bufferNumSamples);

        const int nch = fc.destBuffer->getNumChannels();
        if (nch >= 1) fc.destBuffer->copyFrom (0, fc.bufferStartSample, tmp, 0, 0, fc.bufferNumSamples);
        if (nch >= 2) fc.destBuffer->copyFrom (1, fc.bufferStartSample, tmp, 1, 0, fc.bufferNumSamples);
        for (int ch = 2; ch < nch; ++ch)
            fc.destBuffer->clear (ch, fc.bufferStartSample, fc.bufferNumSamples);
    }

private:
    juce::Synthesiser synth;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AISynthPlugin)
};

} // namespace tewk
