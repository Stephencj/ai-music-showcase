/*
    AI Preamp — our own native channel pre-amp (a built-in Tracktion effect).

    First stage of the channel strip: an input gain driven into a soft
    (slightly asymmetric, tube-ish) saturation, with an output trim. Adds warmth
    / drive and lets you gain-stage into the EQ + Compressor that follow.

      Drive   clean .. driven   (input gain into the saturator; small even-
                                 harmonic bias for analog colour)
      Output  output trim       (make-up / level)

    On/off is the standard Plugin bypass (setEnabled).
*/

#pragma once

#include <tracktion_engine/tracktion_engine.h>
#include <cmath>

namespace tewk
{

namespace te = tracktion;

class AIPreampPlugin : public te::Plugin
{
public:
    explicit AIPreampPlugin (te::PluginCreationInfo info) : te::Plugin (info)
    {
        auto* um = getUndoManager();
        driveValue.referTo  (state, juce::Identifier ("preampDrive"),  um, 0.3f);
        outputValue.referTo (state, juce::Identifier ("preampOutput"), um, 0.5f);

        drive  = addParam ("drive",  TRANS("Drive"),  { 0.0f, 1.0f });
        output = addParam ("output", TRANS("Output"), { 0.0f, 1.0f });
        drive->attachToCurrentValue (driveValue);
        output->attachToCurrentValue (outputValue);
    }

    ~AIPreampPlugin() override
    {
        drive->detachFromCurrentValue();
        output->detachFromCurrentValue();
        notifyListenersOfDeletion();
    }

    static inline const char* xmlTypeName = "ai_preamp";

    juce::String getName() const override             { return "Preamp"; }
    juce::String getPluginType() override             { return xmlTypeName; }
    juce::String getSelectableDescription() override  { return "Preamp (built-in)"; }
    int getNumOutputChannelsGivenInputs (int n) override { return juce::jmin (n, 2); }

    void initialise (const te::PluginInitialisationInfo&) override {}
    void deinitialise() override {}

    void applyToBuffer (const te::PluginRenderContext& fc) override
    {
        if (fc.destBuffer == nullptr)
            return;

        const float d        = drive->getCurrentValue();
        const float g        = 1.0f + d * 9.0f;            // input gain 1..10
        const float comp     = 1.0f / std::sqrt (g);       // rough loudness compensation
        const float bias     = d * 0.15f;                  // a little asymmetry -> even harmonics
        const float biasT    = std::tanh (bias);
        const float outGain  = output->getCurrentValue() * 2.0f;  // 0.5 -> unity

        const int nch = juce::jmin (2, fc.destBuffer->getNumChannels());
        for (int ch = 0; ch < nch; ++ch)
        {
            auto* dPtr = fc.destBuffer->getWritePointer (ch);
            for (int i = 0; i < fc.bufferNumSamples; ++i)
            {
                const int idx = fc.bufferStartSample + i;
                const float x = dPtr[idx];
                dPtr[idx] = (std::tanh (x * g + bias) - biasT) * comp * outGain;
            }
        }
    }

    te::AutomatableParameter::Ptr drive, output;

private:
    juce::CachedValue<float> driveValue, outputValue;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AIPreampPlugin)
};

} // namespace tewk
