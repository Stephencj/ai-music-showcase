#pragma once

#include "PluginProcessor.h"

class AIPartBankEditor : public juce::AudioProcessorEditor,
                         private juce::Timer
{
public:
    explicit AIPartBankEditor (AIPartBankProcessor&);
    ~AIPartBankEditor() override;

    void paint (juce::Graphics&) override;
    void resized() override;

private:
    void pushSettings();      // read the UI into the processor
    void runGenerate();       // background round-trip → add a bank item
    void fetchOptions();      // smart-dropdown choices
    void updateModifiers();   // re-shape modifier dropdowns for the part
    void rebuildBankList();   // sync the row components to proc.bank
    void toggleRow (int index);
    void deleteRow (int index);
    void clearBank();
    void refreshGlyphs();
    void timerCallback() override;

    AIPartBankProcessor& proc;

    juce::Label    title;
    juce::ComboBox targetBox, genreBox, mod1Box, mod2Box;
    juce::TextEditor keyEdit, tempoEdit, barsEdit, progEdit, serverEdit;
    juce::ToggleButton syncBtn { "Host" };   // tempo/meter follow the DAW
    juce::Label    targetLbl, genreLbl, keyLbl, tempoLbl, barsLbl, progLbl, serverLbl, mod1Lbl, mod2Lbl;
    juce::Slider   octaveSlider, densitySlider;
    juce::Label    octaveLbl, densityLbl;
    juce::TextButton generateBtn { "Generate" };
    juce::Label    status, bankTitle;
    juce::TextButton clearBtn { "Clear bank" };

    juce::var partOptions;

    struct BankRow;
    juce::Viewport bankViewport;
    juce::Component bankContainer;
    juce::OwnedArray<BankRow> rows;
    int activeIndex { -1 };   // auditioning (audio-FX) / armed (MIDI-FX)

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (AIPartBankEditor)
};
