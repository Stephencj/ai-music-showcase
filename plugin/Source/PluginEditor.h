#pragma once

#include "PluginProcessor.h"

class AIPartGeneratorEditor : public juce::AudioProcessorEditor
{
public:
    explicit AIPartGeneratorEditor (AIPartGeneratorProcessor&);
    ~AIPartGeneratorEditor() override = default;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void pushSettings();     // read the UI into the processor
    void runGenerate();      // kick the background round-trip

    AIPartGeneratorProcessor& proc;

    juce::Label    title;
    juce::ComboBox targetBox, genreBox;
    juce::TextEditor keyEdit, tempoEdit, barsEdit, progEdit, serverEdit;
    juce::Label    targetLbl, genreLbl, keyLbl, tempoLbl, barsLbl, progLbl, serverLbl;
    juce::TextButton generateBtn { "Generate" };
    juce::Label    status;

    // Drag handles for the generated artifacts (drag onto a track).
    struct FileDragSource;
    std::unique_ptr<FileDragSource> midiDrag, wavDrag;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AIPartGeneratorEditor)
};
