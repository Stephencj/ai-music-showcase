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
    targetBox.onChange = [this] { updateModifiers(); };
    addAndMakeVisible (targetBox);

    genreBox.addItemList ({ "(auto)", "pop_full_song", "rock_anthem_full",
                            "funk_full_song", "soul_motown_full", "blues_12bar_full",
                            "hip_hop_full", "country_full", "disco_full" }, 1);
    genreBox.setSelectedItemIndex (0, juce::dontSendNotification);
    addAndMakeVisible (genreBox);

    // Smart per-part modifier dropdowns — contents fetched from the backend,
    // re-shaped by updateModifiers() when the Part changes.
    addAndMakeVisible (mod1Box);
    addAndMakeVisible (mod2Box);
    styleLabel (mod1Lbl, "");
    styleLabel (mod2Lbl, "");
    addAndMakeVisible (mod1Lbl);
    addAndMakeVisible (mod2Lbl);

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

    setSize (420, 380);
    fetchOptions();        // populate the smart dropdowns for the current part
}

void AIPartGeneratorEditor::fetchOptions()
{
    auto* pp = &proc;
    juce::Component::SafePointer<AIPartGeneratorEditor> safe (this);
    juce::Thread::launch ([pp, safe]() mutable
    {
        auto opts = pp->fetchOptions();
        juce::MessageManager::callAsync ([safe, opts]() mutable
        {
            if (auto* e = safe.getComponent())
            {
                e->partOptions = opts;
                e->updateModifiers();
            }
        });
    });
}

// Re-shape the two modifier dropdowns for the selected part, populating their
// contents from the fetched options. chords → Voicing + Rhythm; bass/drums →
// Pattern (one box); melody/lead → Style + Phrase.
void AIPartGeneratorEditor::updateModifiers()
{
    auto fill = [] (juce::ComboBox& box, juce::Label& lbl, const juce::var& modObj,
                    const juce::String& labelText, const juce::String& current)
    {
        lbl.setText (labelText, juce::dontSendNotification);
        box.clear (juce::dontSendNotification);
        box.setVisible (true);
        lbl.setVisible (true);
        if (auto* o = modObj.getDynamicObject())
        {
            int id = 1;
            if (auto* arr = o->getProperty ("options").getArray())
                for (auto& v : *arr)
                    box.addItem (v.toString(), id++);
            const auto want = current.isNotEmpty() ? current : o->getProperty ("default").toString();
            for (int i = 0; i < box.getNumItems(); ++i)
                if (box.getItemText (i) == want) { box.setSelectedItemIndex (i, juce::dontSendNotification); break; }
            if (box.getSelectedId() == 0 && box.getNumItems() > 0)
                box.setSelectedItemIndex (0, juce::dontSendNotification);
        }
    };
    auto hide = [] (juce::ComboBox& box, juce::Label& lbl)
        { box.setVisible (false); lbl.setVisible (false); };

    const auto target = targetBox.getText();
    auto* root = partOptions.getDynamicObject();
    const juce::var t = (root != nullptr) ? root->getProperty (target) : juce::var();
    auto* to = t.getDynamicObject();
    if (to == nullptr) { hide (mod1Box, mod1Lbl); hide (mod2Box, mod2Lbl); return; }

    if (target == "chords")
    {
        fill (mod1Box, mod1Lbl, to->getProperty ("voicing"), "Voicing", proc.voicing);
        fill (mod2Box, mod2Lbl, to->getProperty ("rhythm"),  "Rhythm",  proc.chordRhythm);
    }
    else if (target == "bass")
    {
        fill (mod1Box, mod1Lbl, to->getProperty ("pattern"), "Pattern", proc.bassPattern);
        hide (mod2Box, mod2Lbl);
    }
    else if (target == "drums")
    {
        fill (mod1Box, mod1Lbl, to->getProperty ("pattern"), "Pattern", proc.drumPattern);
        hide (mod2Box, mod2Lbl);
    }
    else // melody / lead
    {
        fill (mod1Box, mod1Lbl, to->getProperty ("style"),        "Style",  proc.melodyStyle);
        fill (mod2Box, mod2Lbl, to->getProperty ("phrase_shape"), "Phrase", proc.phraseShape);
    }
    resized();   // visibility changed → relayout so the rows show/hide
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

    // Per-part modifiers from the smart dropdowns (blank if options not loaded
    // → backend uses defaults). Only the ones for this target are populated.
    proc.voicing = proc.chordRhythm = proc.bassPattern
        = proc.drumPattern = proc.melodyStyle = proc.phraseShape = {};
    const auto m1 = mod1Box.getText(), m2 = mod2Box.getText();
    if      (proc.target == "chords") { proc.voicing = m1; proc.chordRhythm = m2; }
    else if (proc.target == "bass")   { proc.bassPattern = m1; }
    else if (proc.target == "drums")  { proc.drumPattern = m1; }
    else                              { proc.melodyStyle = m1; proc.phraseShape = m2; }
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
    if (mod1Box.isVisible()) row (mod1Lbl, mod1Box);
    if (mod2Box.isVisible()) row (mod2Lbl, mod2Box);
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
