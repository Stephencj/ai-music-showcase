/*
    AI Synth — our own native software instrument (a built-in Tracktion plugin).

    Design (Stephen's direction): a few basic TEMPLATES (Pad / Bass / Lead /
    Pluck), each driven by the SAME six "macro" knobs. Every macro moves several
    DSP params at once, so a handful of controls covers a lot of musical ground
    and it's hard to dial in a bad sound. A template is just a preset of macro
    positions plus a little hidden character (sustain, filter-env, drive, LFO
    rate). All macros are automatable Tracktion parameters (persist + automate).

    Six macros (all 0..1):
      Tone    dark .. bright          (filter cutoff, exp)
      Shape   round .. sharp          (saw<>square morph + detune width)
      Attack  instant .. slow swell   (amp + filter env attack)
      Release short .. long tail       (amp env release)
      Space   dry .. wet              (reverb mix)
      Move    still .. moving         (LFO depth -> filter + a little vibrato)
    + Level   output gain

    Voice DSP: 2 detuned PolyBLEP oscillators (saw<>square morph) -> per-voice
    TPT resonant low-pass (key-tracked, with a filter envelope) -> ADSR amp.
    Plugin FX: soft-clip drive -> juce::Reverb. Modulation: one global LFO.
*/

#pragma once

#include <tracktion_engine/tracktion_engine.h>
#include <cmath>

namespace tewk
{

namespace te = tracktion;

//==============================================================================
enum class InstrTemplate { pad = 0, bass, lead, pluck, numTemplates };

// Live, already-mapped parameters the voices read each chunk.
struct SynthShared
{
    float oscShape   = 0.2f;     // 0 = saw, 1 = square
    float detune     = 8.0f;     // cents between the two oscillators
    float cutoffHz   = 2000.0f;  // base filter cutoff (pre key-track / env / LFO)
    float reso       = 0.2f;     // 0..1
    float filterEnv  = 0.0f;     // octaves of upward filter-envelope sweep
    float filterDecay = 0.3f;    // seconds for the filter envelope to fall
    float attack     = 0.01f;    // amp ADSR (seconds / 0..1)
    float decay      = 0.3f;
    float sustain    = 0.8f;
    float release    = 0.4f;
    // updated per chunk by the plugin's global LFO:
    float lfoCutoffMul = 1.0f;   // multiply cutoff
    float pitchMul     = 1.0f;   // vibrato pitch ratio
};

//==============================================================================
struct AISynthSound : public juce::SynthesiserSound
{
    bool appliesToNote (int) override    { return true; }
    bool appliesToChannel (int) override { return true; }
};

//==============================================================================
// Zavalishin TPT state-variable low-pass.
struct TPTLowpass
{
    void setCoefs (float cutoffHz, float sr, float Q) noexcept
    {
        cutoffHz = juce::jlimit (20.0f, 0.45f * sr, cutoffHz);
        const float wd = juce::MathConstants<float>::twoPi * cutoffHz;
        const float T  = 1.0f / sr;
        const float wa = (2.0f / T) * std::tan (wd * T * 0.5f);
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
class AISynthVoice : public juce::SynthesiserVoice
{
public:
    explicit AISynthVoice (const SynthShared& sharedParams) : shared (sharedParams) {}

    bool canPlaySound (juce::SynthesiserSound* s) override
    {
        return dynamic_cast<AISynthSound*> (s) != nullptr;
    }

    void setCurrentPlaybackSampleRate (double sr) override
    {
        juce::SynthesiserVoice::setCurrentPlaybackSampleRate (sr);
        if (sr > 0)
            adsr.setSampleRate (sr);
    }

    void startNote (int midiNote, float velocity, juce::SynthesiserSound*, int) override
    {
        noteHz = (float) juce::MidiMessage::getMidiNoteInHertz (midiNote);
        level  = 0.12f + 0.88f * velocity;
        phase1 = 0.0; phase2 = 0.5;
        filterEnvLevel = 1.0f;
        filter.reset();
        adsr.setParameters ({ shared.attack, shared.decay, shared.sustain, shared.release });
        adsr.noteOn();
    }

    void stopNote (float, bool allowTailOff) override
    {
        if (allowTailOff) adsr.noteOff();
        else { adsr.reset(); clearCurrentNote(); }
    }

    void pitchWheelMoved (int) override {}
    void controllerMoved (int, int) override {}

    void renderNextBlock (juce::AudioBuffer<float>& out, int startSample, int numSamples) override
    {
        if (! adsr.isActive())
            return;

        const double sr = getSampleRate();
        adsr.setParameters ({ shared.attack, shared.decay, shared.sustain, shared.release });

        auto* L = out.getWritePointer (0, startSample);
        auto* R = out.getNumChannels() > 1 ? out.getWritePointer (1, startSample) : nullptr;

        const int chunk = 32;            // keep filter/LFO modulation smooth
        int done = 0;
        while (done < numSamples)
        {
            const int n = juce::jmin (chunk, numSamples - done);

            // filter envelope (cheap exponential decay) -> cutoff in octaves
            const float fDecayPerChunk = std::exp (- (float) (n / sr) / juce::jmax (0.02f, shared.filterDecay));
            const float keyTrack = juce::jlimit (0.5f, 4.0f, noteHz / 440.0f);
            const float cutoff = shared.cutoffHz * keyTrack * shared.lfoCutoffMul
                                 * std::pow (2.0f, shared.filterEnv * filterEnvLevel);
            filter.setCoefs (cutoff, (float) sr, 0.6f + shared.reso * 6.0f);

            const double inc1 = (noteHz * shared.pitchMul) / sr;
            const double det  = std::pow (2.0, (shared.detune * 0.5) / 1200.0);
            const double inc2 = (noteHz * shared.pitchMul * det) / sr;

            for (int i = 0; i < n; ++i)
            {
                const float o1 = osc (phase1, inc1, shared.oscShape);
                const float o2 = osc (phase2, inc2, shared.oscShape);
                const float env = adsr.getNextSample();
                const float s = filter.processLP (0.5f * (o1 + o2) * env * level * 0.4f);

                L[done + i] += s;
                if (R != nullptr) R[done + i] += s;

                phase1 += inc1; if (phase1 >= 1.0) phase1 -= 1.0;
                phase2 += inc2; if (phase2 >= 1.0) phase2 -= 1.0;
            }

            filterEnvLevel *= fDecayPerChunk;
            done += n;
        }

        if (! adsr.isActive())
            clearCurrentNote();
    }

private:
    static float polyBLEP (double t, double dt) noexcept
    {
        if (t < dt)       { const double x = t / dt;         return float (x + x - x * x - 1.0); }
        if (t > 1.0 - dt) { const double x = (t - 1.0) / dt; return float (x * x + x + x + 1.0); }
        return 0.0f;
    }

    // saw<>square morph: shape 0 = saw, 1 = square (50% pulse), both anti-aliased.
    static float osc (double phase, double inc, float shape) noexcept
    {
        const float saw = float (2.0 * phase - 1.0) - polyBLEP (phase, inc);

        double p2 = phase + 0.5; if (p2 >= 1.0) p2 -= 1.0;
        const float square = (float (2.0 * phase - 1.0) - polyBLEP (phase, inc))
                           - (float (2.0 * p2    - 1.0) - polyBLEP (p2,    inc));

        return saw * (1.0f - shape) + (square * 0.5f) * shape;
    }

    const SynthShared& shared;
    juce::ADSR adsr;
    TPTLowpass filter;
    double phase1 = 0.0, phase2 = 0.0;
    float  noteHz = 440.0f, level = 0.8f, filterEnvLevel = 0.0f;
};

//==============================================================================
class AISynthPlugin : public te::Plugin
{
public:
    explicit AISynthPlugin (te::PluginCreationInfo info) : te::Plugin (info)
    {
        auto* um = getUndoManager();

        toneValue.referTo    (state, juce::Identifier ("macroTone"),    um, 0.5f);
        shapeValue.referTo   (state, juce::Identifier ("macroShape"),   um, 0.25f);
        attackValue.referTo  (state, juce::Identifier ("macroAttack"),  um, 0.2f);
        releaseValue.referTo (state, juce::Identifier ("macroRelease"), um, 0.4f);
        spaceValue.referTo   (state, juce::Identifier ("macroSpace"),   um, 0.3f);
        moveValue.referTo    (state, juce::Identifier ("macroMove"),    um, 0.2f);
        levelValue.referTo   (state, juce::Identifier ("macroLevel"),   um, 0.8f);
        templateValue.referTo (state, juce::Identifier ("instrTemplate"), um, 0);

        tone    = addParam ("tone",    TRANS("Tone"),    { 0.0f, 1.0f });
        shape   = addParam ("shape",   TRANS("Shape"),   { 0.0f, 1.0f });
        attack  = addParam ("attack",  TRANS("Attack"),  { 0.0f, 1.0f });
        release = addParam ("release", TRANS("Release"), { 0.0f, 1.0f });
        space   = addParam ("space",   TRANS("Space"),   { 0.0f, 1.0f });
        move    = addParam ("move",    TRANS("Move"),    { 0.0f, 1.0f });
        level   = addParam ("level",   TRANS("Level"),   { 0.0f, 1.0f });

        tone->attachToCurrentValue (toneValue);
        shape->attachToCurrentValue (shapeValue);
        attack->attachToCurrentValue (attackValue);
        release->attachToCurrentValue (releaseValue);
        space->attachToCurrentValue (spaceValue);
        move->attachToCurrentValue (moveValue);
        level->attachToCurrentValue (levelValue);

        for (int i = 0; i < 16; ++i)
            synth.addVoice (new AISynthVoice (shared));
        synth.addSound (new AISynthSound());
        synth.setNoteStealingEnabled (true);

        applyTemplateCharacter ((InstrTemplate) (int) templateValue);  // hidden params from saved template
    }

    ~AISynthPlugin() override
    {
        tone->detachFromCurrentValue();   shape->detachFromCurrentValue();
        attack->detachFromCurrentValue(); release->detachFromCurrentValue();
        space->detachFromCurrentValue();  move->detachFromCurrentValue();
        level->detachFromCurrentValue();
        notifyListenersOfDeletion();
    }

    static inline const char* xmlTypeName = "ai_synth";

    juce::String getName() const override             { return "AI Synth"; }
    juce::String getPluginType() override             { return xmlTypeName; }
    juce::String getSelectableDescription() override  { return "AI Synth (built-in instrument)"; }

    bool takesAudioInput() override                   { return false; }
    bool takesMidiInput() override                    { return true; }
    bool isSynth() override                           { return true; }
    bool producesAudioWhenNoAudioInput() override     { return true; }
    int  getNumOutputChannelsGivenInputs (int) override { return 2; }

    //== templates =============================================================
    static const char* templateName (int i)
    {
        static const char* names[] = { "Pad", "Bass", "Lead", "Pluck" };
        return names[juce::jlimit (0, 3, i)];
    }

    int getTemplateIndex() const { return (int) templateValue; }

    // Switch template: set the hidden character + snap the six macros to its preset.
    void selectTemplate (InstrTemplate t)
    {
        templateValue = (int) t;
        applyTemplateCharacter (t);

        const auto& m = macroPreset (t);
        tone->setParameter    (m[0], juce::sendNotification);
        shape->setParameter   (m[1], juce::sendNotification);
        attack->setParameter  (m[2], juce::sendNotification);
        release->setParameter (m[3], juce::sendNotification);
        space->setParameter   (m[4], juce::sendNotification);
        move->setParameter    (m[5], juce::sendNotification);
    }

    //== processing ============================================================
    void initialise (const te::PluginInitialisationInfo& info) override
    {
        synth.setCurrentPlaybackSampleRate (info.sampleRate);
        reverb.setSampleRate (info.sampleRate);
    }

    void deinitialise() override {}
    void reset() override { synth.allNotesOff (0, false); reverb.reset(); }

    void applyToBuffer (const te::PluginRenderContext& fc) override
    {
        if (fc.destBuffer == nullptr)
            return;

        updateSharedFromMacros();

        // advance global LFO across this buffer, write its current value into shared
        const float lfoHz = lfoRate;
        lfoPhase += (double) fc.bufferNumSamples / juce::jmax (1.0, sampleRate) * lfoHz;
        lfoPhase -= std::floor (lfoPhase);
        const float lfo = std::sin (juce::MathConstants<float>::twoPi * (float) lfoPhase);
        const float moveAmt = move->getCurrentValue();
        shared.lfoCutoffMul = std::pow (2.0f, lfo * moveAmt * 0.6f);          // up to ~0.6 octave wobble
        shared.pitchMul     = std::pow (2.0f, (lfo * moveAmt * 12.0f) / 1200.0f); // up to ~12 cents vibrato

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

        // drive (soft clip) + reverb
        const float drive = 1.0f + driveAmt * 4.0f;
        for (int ch = 0; ch < 2; ++ch)
        {
            auto* d = tmp.getWritePointer (ch);
            for (int i = 0; i < fc.bufferNumSamples; ++i)
                d[i] = std::tanh (d[i] * drive) * (1.0f / std::sqrt (drive)) * outGain;
        }

        const float wet = space->getCurrentValue();
        reverbParams.roomSize = 0.45f + 0.45f * wet;
        reverbParams.wetLevel = wet * 0.7f;
        reverbParams.dryLevel = 1.0f - wet * 0.5f;
        reverbParams.width    = 1.0f;
        reverbParams.damping  = 0.4f;
        reverb.setParameters (reverbParams);
        if (wet > 0.001f)
            reverb.processStereo (tmp.getWritePointer (0), tmp.getWritePointer (1), fc.bufferNumSamples);

        const int nch = fc.destBuffer->getNumChannels();
        if (nch >= 1) fc.destBuffer->copyFrom (0, fc.bufferStartSample, tmp, 0, 0, fc.bufferNumSamples);
        if (nch >= 2) fc.destBuffer->copyFrom (1, fc.bufferStartSample, tmp, 1, 0, fc.bufferNumSamples);
        for (int ch = 2; ch < nch; ++ch)
            fc.destBuffer->clear (ch, fc.bufferStartSample, fc.bufferNumSamples);
    }

    // exposed so the editor can build sliders + a template menu
    te::AutomatableParameter::Ptr tone, shape, attack, release, space, move, level;

private:
    using Preset = std::array<float, 6>;   // tone, shape, attack, release, space, move

    static const Preset& macroPreset (InstrTemplate t)
    {
        static const Preset presets[] = {
            /* pad   */ { 0.45f, 0.20f, 0.55f, 0.70f, 0.50f, 0.35f },
            /* bass  */ { 0.35f, 0.55f, 0.05f, 0.20f, 0.05f, 0.00f },
            /* lead  */ { 0.62f, 0.40f, 0.12f, 0.32f, 0.25f, 0.30f },
            /* pluck */ { 0.60f, 0.50f, 0.02f, 0.28f, 0.30f, 0.00f },
        };
        return presets[juce::jlimit (0, 3, (int) t)];
    }

    // hidden, non-macro character per template
    void applyTemplateCharacter (InstrTemplate t)
    {
        switch (t)
        {
            case InstrTemplate::pad:   sustain = 0.85f; baseDecay = 0.6f;  reso = 0.12f; driveAmt = 0.05f; lfoRate = 0.3f; filterEnvOct = 0.4f; filterDecaySec = 0.8f; break;
            case InstrTemplate::bass:  sustain = 0.65f; baseDecay = 0.25f; reso = 0.22f; driveAmt = 0.35f; lfoRate = 4.0f; filterEnvOct = 1.4f; filterDecaySec = 0.18f; break;
            case InstrTemplate::lead:  sustain = 0.80f; baseDecay = 0.30f; reso = 0.28f; driveAmt = 0.20f; lfoRate = 5.5f; filterEnvOct = 0.6f; filterDecaySec = 0.30f; break;
            case InstrTemplate::pluck: sustain = 0.00f; baseDecay = 0.22f; reso = 0.32f; driveAmt = 0.10f; lfoRate = 4.0f; filterEnvOct = 1.6f; filterDecaySec = 0.20f; break;
            default: break;
        }
    }

    // map the six 0..1 macros into the SynthShared the voices read
    void updateSharedFromMacros()
    {
        const float t = tone->getCurrentValue();
        shared.cutoffHz  = 80.0f * std::pow (2.0f, t * 7.6f);          // ~80 Hz .. ~16 kHz
        shared.reso      = reso + tone->getCurrentValue() * 0.0f;       // (reso fixed per template for now)
        shared.oscShape  = shape->getCurrentValue();
        shared.detune    = 4.0f + shape->getCurrentValue() * 22.0f;     // a touch of width
        shared.attack    = 0.002f * std::pow (2.0f, attack->getCurrentValue() * 11.0f);  // 2 ms .. ~4 s
        shared.release   = 0.02f  * std::pow (2.0f, release->getCurrentValue() * 8.0f);  // 20 ms .. ~5 s
        shared.decay     = baseDecay;
        shared.sustain   = sustain;
        shared.filterEnv = filterEnvOct;
        shared.filterDecay = filterDecaySec;

        outGain = juce::jlimit (0.0f, 1.2f, level->getCurrentValue());
    }

    juce::Synthesiser synth;
    SynthShared shared;

    juce::Reverb reverb;
    juce::Reverb::Parameters reverbParams;

    // hidden per-template character
    float sustain = 0.8f, baseDecay = 0.3f, reso = 0.2f, driveAmt = 0.15f;
    float lfoRate = 1.0f, filterEnvOct = 0.5f, filterDecaySec = 0.3f;
    float outGain = 0.8f;
    double lfoPhase = 0.0;

    juce::CachedValue<float> toneValue, shapeValue, attackValue, releaseValue, spaceValue, moveValue, levelValue;
    juce::CachedValue<int>   templateValue;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AISynthPlugin)
};

} // namespace tewk
