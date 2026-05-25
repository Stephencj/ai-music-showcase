#include "PluginEditor.h"

// A button you drag to drop its file (the generated .mid / .wav) onto a track.
struct AIPartGeneratorEditor::FileDragSource : public juce::TextButton
{
    using juce::TextButton::TextButton;
    juce::File file;

    void mouseDrag (const juce::MouseEvent&) override
    {
        if (file.existsAsFile())
            juce::DragAndDropContainer::performExternalDragDropOfFiles (
                { file.getFullPathName() }, /*canMove*/ false, this);
    }
};

namespace
{
    void styleLabel (juce::Label& l, const juce::String& text)
    {
        l.setText (text, juce::dontSendNotification);
        l.setFont (juce::Font (13.0f));
        l.setJustificationType (juce::Justification::centredLeft);
    }
}

AIPartGeneratorEditor::AIPartGeneratorEditor (AIPartGeneratorProcessor& p)
    : juce::AudioProcessorEditor (&p), proc (p)
{
    title.setText ("AI Part Generator", juce::dontSendNotification);
    title.setFont (juce::Font (18.0f, juce::Font::bold));
    addAndMakeVisible (title);

    targetBox.addItemList ({ "chords", "bass", "melody", "lead", "drums" }, 1);
    targetBox.setText (proc.target, juce::dontSendNotification);
    addAndMakeVisible (targetBox);

    genreBox.addItemList ({ "(auto)", "pop_full_song", "rock_anthem_full",
                            "funk_full_song", "soul_motown_full", "blues_12bar_full",
                            "hip_hop_full", "country_full", "disco_full" }, 1);
    genreBox.setSelectedItemIndex (0, juce::dontSendNotification);
    addAndMakeVisible (genreBox);

    keyEdit.setText (proc.key);          addAndMakeVisible (keyEdit);
    tempoEdit.setText (juce::String (proc.tempo, 1)); addAndMakeVisible (tempoEdit);
    barsEdit.setText (juce::String (proc.bars)); addAndMakeVisible (barsEdit);
    progEdit.setText (proc.progression); progEdit.setTextToShowWhenEmpty ("e.g. I V vi IV  (blank = key default)", juce::Colours::grey);
    addAndMakeVisible (progEdit);
    serverEdit.setText (proc.serverBase); addAndMakeVisible (serverEdit);

    styleLabel (targetLbl, "Part");      addAndMakeVisible (targetLbl);
    styleLabel (genreLbl,  "Style");     addAndMakeVisible (genreLbl);
    styleLabel (keyLbl,    "Key");       addAndMakeVisible (keyLbl);
    styleLabel (tempoLbl,  "Tempo");     addAndMakeVisible (tempoLbl);
    styleLabel (barsLbl,   "Bars");      addAndMakeVisible (barsLbl);
    styleLabel (progLbl,   "Chords");    addAndMakeVisible (progLbl);
    styleLabel (serverLbl, "Server");    addAndMakeVisible (serverLbl);

    generateBtn.onClick = [this] { runGenerate(); };
    addAndMakeVisible (generateBtn);

    midiDrag = std::make_unique<FileDragSource> ("MIDI");
    wavDrag  = std::make_unique<FileDragSource> ("WAV");
    midiDrag->setEnabled (false);
    wavDrag->setEnabled (false);
    midiDrag->setTooltip ("Drag onto a track to drop the generated MIDI");
    wavDrag->setTooltip ("Drag onto a track to drop the rendered audio");
    addAndMakeVisible (*midiDrag);
    addAndMakeVisible (*wavDrag);

    status.setText ("Set the part + context, then Generate. Needs Music Producer running.",
                    juce::dontSendNotification);
    status.setFont (juce::Font (12.0f));
    status.setJustificationType (juce::Justification::topLeft);
    addAndMakeVisible (status);

    setSize (420, 320);
}

void AIPartGeneratorEditor::pushSettings()
{
    proc.target = targetBox.getText();
    proc.genre  = (genreBox.getSelectedItemIndex() <= 0) ? juce::String() : genreBox.getText();
    proc.key    = keyEdit.getText().trim();
    proc.tempo  = tempoEdit.getText().getDoubleValue();
    if (proc.tempo <= 0) proc.tempo = 120.0;
    proc.bars   = juce::jmax (1, barsEdit.getText().getIntValue());
    proc.progression = progEdit.getText();
    proc.serverBase  = serverEdit.getText().trim().trimCharactersAtEnd ("/");
}

void AIPartGeneratorEditor::runGenerate()
{
    pushSettings();
    generateBtn.setEnabled (false);
    midiDrag->setEnabled (false);
    wavDrag->setEnabled (false);
    status.setText ("Generating…", juce::dontSendNotification);

    auto* pp = &proc;                                   // processor outlives the editor
    juce::Component::SafePointer<AIPartGeneratorEditor> safe (this);
    juce::Thread::launch ([pp, safe]() mutable
    {
        auto res = pp->generate();
        juce::MessageManager::callAsync ([safe, res]() mutable
        {
            if (auto* e = safe.getComponent())
            {
                e->status.setText (res.message, juce::dontSendNotification);
                e->midiDrag->file = res.midiFile;
                e->wavDrag->file  = res.wavFile;
                e->midiDrag->setEnabled (res.midiFile.existsAsFile());
                e->wavDrag->setEnabled (res.wavFile.existsAsFile());
                e->generateBtn.setEnabled (true);
            }
        });
    });
}

void AIPartGeneratorEditor::paint (juce::Graphics& g)
{
    g.fillAll (getLookAndFeel().findColour (juce::ResizableWindow::backgroundColourId));
}

void AIPartGeneratorEditor::resized()
{
    auto r = getLocalBounds().reduced (12);
    title.setBounds (r.removeFromTop (28));
    r.removeFromTop (6);

    auto row = [&r] (juce::Label& lbl, juce::Component& field)
    {
        auto line = r.removeFromTop (26);
        lbl.setBounds (line.removeFromLeft (64));
        field.setBounds (line);
        r.removeFromTop (4);
    };
    row (targetLbl, targetBox);
    row (genreLbl,  genreBox);
    row (keyLbl,    keyEdit);
    row (tempoLbl,  tempoEdit);
    row (barsLbl,   barsEdit);
    row (progLbl,   progEdit);
    row (serverLbl, serverEdit);

    r.removeFromTop (6);
    generateBtn.setBounds (r.removeFromTop (30));
    r.removeFromTop (6);

    auto drags = r.removeFromTop (28);
    midiDrag->setBounds (drags.removeFromLeft (drags.getWidth() / 2).reduced (2, 0));
    wavDrag->setBounds (drags.reduced (2, 0));
    r.removeFromTop (6);
    status.setBounds (r);
}
