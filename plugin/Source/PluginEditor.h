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
    void fetchOptions();     // load smart-dropdown choices from the backend
    void updateModifiers();  // re-shape the modifier dropdowns for the part

    AIPartGeneratorProcessor& proc;

    juce::Label    title;
    juce::ComboBox targetBox, genreBox, mod1Box, mod2Box;
    juce::TextEditor keyEdit, tempoEdit, barsEdit, progEdit, serverEdit;
    juce::Label    targetLbl, genreLbl, keyLbl, tempoLbl, barsLbl, progLbl, serverLbl;
    juce::Label    mod1Lbl, mod2Lbl;
    juce::TextButton generateBtn { "Generate" };
    juce::Label    status;

    juce::var partOptions;   // GET /api/part-options result (per target)

    // Drag handles for the generated artifacts (drag onto a track).
    struct FileDragSource;
    std::unique_ptr<FileDragSource> midiDrag, wavDrag;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AIPartGeneratorEditor)
};
