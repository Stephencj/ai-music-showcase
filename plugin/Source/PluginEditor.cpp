#include "PluginEditor.h"

namespace
{
    void styleLabel (juce::Label& l, const juce::String& text)
    {
        l.setText (text, juce::dontSendNotification);
        l.setFont (juce::Font (13.0f));
        l.setJustificationType (juce::Justification::centredLeft);
    }

    // A button you drag to drop its file (the item's .mid / .wav) onto a track.
    struct FileDragSource : public juce::TextButton
    {
        using juce::TextButton::TextButton;
        juce::File file;
        void mouseDrag (const juce::MouseEvent&) override
        {
            if (file.existsAsFile())
                juce::DragAndDropContainer::performExternalDragDropOfFiles (
                    { file.getFullPathName() }, false, this);
        }
    };
}

// One row in the bank: label + play/arm + drag MIDI + drag WAV + delete.
struct AIPartBankEditor::BankRow : public juce::Component
{
    juce::Label label;
    juce::TextButton playBtn;
    FileDragSource midiDrag { "MIDI" }, wavDrag { "WAV" };
    juce::TextButton delBtn { "x" };

    explicit BankRow (BankItem& item)
    {
        label.setText (item.label, juce::dontSendNotification);
        label.setFont (juce::Font (12.0f));
        addAndMakeVisible (label);
        addAndMakeVisible (playBtn);
        midiDrag.file = item.midiFile; midiDrag.setEnabled (item.midiFile.existsAsFile());
        wavDrag.file  = item.wavFile;  wavDrag.setEnabled (item.wavFile.existsAsFile());
        midiDrag.setTooltip ("Drag MIDI onto a track");
        wavDrag.setTooltip ("Drag the rendered audio onto a track");
        addAndMakeVisible (midiDrag);
        addAndMakeVisible (wavDrag);
        addAndMakeVisible (delBtn);
    }

    void resized() override
    {
        auto r = getLocalBounds().reduced (1);
        delBtn.setBounds   (r.removeFromRight (26));
        wavDrag.setBounds  (r.removeFromRight (46).reduced (1, 0));
        midiDrag.setBounds (r.removeFromRight (50).reduced (1, 0));
        playBtn.setBounds  (r.removeFromRight (48).reduced (1, 0));
        label.setBounds    (r);
    }
};

AIPartBankEditor::AIPartBankEditor (AIPartBankProcessor& p)
    : juce::AudioProcessorEditor (&p), proc (p)
{
    title.setText (proc.getName(), juce::dontSendNotification);
    title.setFont (juce::Font (17.0f, juce::Font::bold));
    addAndMakeVisible (title);

    targetBox.addItemList ({ "chords", "bass", "melody", "lead", "drums" }, 1);
    targetBox.setText (proc.target.isNotEmpty() ? proc.target : "melody", juce::dontSendNotification);
    targetBox.onChange = [this] { updateModifiers(); };
    addAndMakeVisible (targetBox);

    genreBox.addItemList ({ "(auto)", "pop_full_song", "rock_anthem_full", "funk_full_song",
                            "soul_motown_full", "blues_12bar_full", "hip_hop_full",
                            "country_full", "disco_full" }, 1);
    genreBox.setSelectedItemIndex (0, juce::dontSendNotification);
    addAndMakeVisible (genreBox);

    addAndMakeVisible (mod1Box); addAndMakeVisible (mod2Box);
    styleLabel (mod1Lbl, ""); styleLabel (mod2Lbl, "");
    addAndMakeVisible (mod1Lbl); addAndMakeVisible (mod2Lbl);

    octaveSlider.setRange (1, 5, 1);
    octaveSlider.setValue (3, juce::dontSendNotification);
    octaveSlider.setSliderStyle (juce::Slider::IncDecButtons);
    octaveSlider.setTextBoxStyle (juce::Slider::TextBoxLeft, false, 42, 20);
    addAndMakeVisible (octaveSlider);
    densitySlider.setRange (0.2, 1.0, 0.05);
    densitySlider.setValue (0.6, juce::dontSendNotification);
    densitySlider.setTextBoxStyle (juce::Slider::TextBoxLeft, false, 46, 20);
    addAndMakeVisible (densitySlider);
    styleLabel (octaveLbl, "Octave"); styleLabel (densityLbl, "Density");
    addAndMakeVisible (octaveLbl); addAndMakeVisible (densityLbl);

    keyEdit.setText (proc.key.isNotEmpty() ? proc.key : "C"); addAndMakeVisible (keyEdit);
    tempoEdit.setText (juce::String (proc.tempo > 0 ? proc.tempo : 120.0, 1)); addAndMakeVisible (tempoEdit);
    barsEdit.setText (juce::String (proc.bars > 0 ? proc.bars : 4)); addAndMakeVisible (barsEdit);
    progEdit.setText (proc.progression);
    progEdit.setTextToShowWhenEmpty ("e.g. I V vi IV  (blank = key default)", juce::Colours::grey);
    addAndMakeVisible (progEdit);
    serverEdit.setText (proc.serverBase); addAndMakeVisible (serverEdit);

    styleLabel (targetLbl, "Part");   addAndMakeVisible (targetLbl);
    styleLabel (genreLbl,  "Style");  addAndMakeVisible (genreLbl);
    styleLabel (keyLbl,    "Key");    addAndMakeVisible (keyLbl);
    styleLabel (tempoLbl,  "Tempo");  addAndMakeVisible (tempoLbl);
    styleLabel (barsLbl,   "Bars");   addAndMakeVisible (barsLbl);
    styleLabel (progLbl,   "Chords"); addAndMakeVisible (progLbl);
    styleLabel (serverLbl, "Server"); addAndMakeVisible (serverLbl);

    generateBtn.onClick = [this] { runGenerate(); };
    addAndMakeVisible (generateBtn);

    status.setFont (juce::Font (12.0f));
    status.setJustificationType (juce::Justification::topLeft);
    status.setText ("Set the part + context, then Generate to add to the bank.", juce::dontSendNotification);
    addAndMakeVisible (status);

    bankTitle.setText ("Bank", juce::dontSendNotification);
    bankTitle.setFont (juce::Font (13.0f, juce::Font::bold));
    addAndMakeVisible (bankTitle);
    clearBtn.onClick = [this] { clearBank(); };
    addAndMakeVisible (clearBtn);
    bankViewport.setViewedComponent (&bankContainer, false);
    bankViewport.setScrollBarsShown (true, false);
    addAndMakeVisible (bankViewport);

    setSize (470, 620);
    rebuildBankList();
    fetchOptions();
    startTimerHz (8);
}

AIPartBankEditor::~AIPartBankEditor() { stopTimer(); }

void AIPartBankEditor::pushSettings()
{
    proc.target = targetBox.getText();
    proc.genre  = (genreBox.getSelectedItemIndex() <= 0) ? juce::String() : genreBox.getText();
    proc.key    = keyEdit.getText().trim();
    proc.tempo  = tempoEdit.getText().getDoubleValue(); if (proc.tempo <= 0) proc.tempo = 120.0;
    proc.bars   = juce::jmax (1, barsEdit.getText().getIntValue());
    proc.progression = progEdit.getText();
    proc.serverBase  = serverEdit.getText().trim().trimCharactersAtEnd ("/");

    proc.voicing = proc.chordRhythm = proc.bassPattern
        = proc.drumPattern = proc.melodyStyle = proc.phraseShape = {};
    const auto m1 = mod1Box.getText(), m2 = mod2Box.getText();
    if      (proc.target == "chords") { proc.voicing = m1; proc.chordRhythm = m2; }
    else if (proc.target == "bass")   { proc.bassPattern = m1; }
    else if (proc.target == "drums")  { proc.drumPattern = m1; }
    else                              { proc.melodyStyle = m1; proc.phraseShape = m2; }

    proc.octave      = octaveSlider.isVisible()  ? (int) octaveSlider.getValue() : -1;
    proc.noteDensity = densitySlider.isVisible() ? densitySlider.getValue()      : -1.0;
}

void AIPartBankEditor::runGenerate()
{
    pushSettings();
    generateBtn.setEnabled (false);
    status.setText ("Generating…", juce::dontSendNotification);

    auto* pp = &proc;
    juce::Component::SafePointer<AIPartBankEditor> safe (this);
    juce::Thread::launch ([pp, safe]() mutable
    {
        auto res = pp->generate();
        std::shared_ptr<BankItem> item (res.ok ? res.item.release() : nullptr);
        const auto msg = res.message;
        juce::MessageManager::callAsync ([safe, item, msg]() mutable
        {
            if (auto* e = safe.getComponent())
            {
                if (item != nullptr)
                {
                    e->proc.bank.add (new BankItem (*item));
                    e->rebuildBankList();
                }
                e->status.setText (msg, juce::dontSendNotification);
                e->generateBtn.setEnabled (true);
            }
        });
    });
}

void AIPartBankEditor::fetchOptions()
{
    auto* pp = &proc;
    juce::Component::SafePointer<AIPartBankEditor> safe (this);
    juce::Thread::launch ([pp, safe]() mutable
    {
        auto opts = pp->fetchOptions();
        juce::MessageManager::callAsync ([safe, opts]() mutable
        {
            if (auto* e = safe.getComponent()) { e->partOptions = opts; e->updateModifiers(); }
        });
    });
}

void AIPartBankEditor::updateModifiers()
{
    auto fill = [] (juce::ComboBox& box, juce::Label& lbl, const juce::var& modObj,
                    const juce::String& labelText, const juce::String& current)
    {
        lbl.setText (labelText, juce::dontSendNotification);
        box.clear (juce::dontSendNotification);
        box.setVisible (true); lbl.setVisible (true);
        if (auto* o = modObj.getDynamicObject())
        {
            int id = 1;
            if (auto* arr = o->getProperty ("options").getArray())
                for (auto& v : *arr) box.addItem (v.toString(), id++);
            const auto want = current.isNotEmpty() ? current : o->getProperty ("default").toString();
            for (int i = 0; i < box.getNumItems(); ++i)
                if (box.getItemText (i) == want) { box.setSelectedItemIndex (i, juce::dontSendNotification); break; }
            if (box.getSelectedId() == 0 && box.getNumItems() > 0)
                box.setSelectedItemIndex (0, juce::dontSendNotification);
        }
    };
    auto hide = [] (juce::ComboBox& box, juce::Label& lbl) { box.setVisible (false); lbl.setVisible (false); };

    const auto target = targetBox.getText();
    octaveLbl.setVisible (target != "drums");   octaveSlider.setVisible (target != "drums");
    densityLbl.setVisible (target != "chords"); densitySlider.setVisible (target != "chords");
    auto* root = partOptions.getDynamicObject();
    const juce::var t = (root != nullptr) ? root->getProperty (target) : juce::var();
    auto* to = t.getDynamicObject();
    if (to == nullptr) { hide (mod1Box, mod1Lbl); hide (mod2Box, mod2Lbl); resized(); return; }

    if (target == "chords")
    {
        fill (mod1Box, mod1Lbl, to->getProperty ("voicing"), "Voicing", proc.voicing);
        fill (mod2Box, mod2Lbl, to->getProperty ("rhythm"),  "Rhythm",  proc.chordRhythm);
    }
    else if (target == "bass")  { fill (mod1Box, mod1Lbl, to->getProperty ("pattern"), "Pattern", proc.bassPattern); hide (mod2Box, mod2Lbl); }
    else if (target == "drums") { fill (mod1Box, mod1Lbl, to->getProperty ("pattern"), "Pattern", proc.drumPattern); hide (mod2Box, mod2Lbl); }
    else
    {
        fill (mod1Box, mod1Lbl, to->getProperty ("style"),        "Style",  proc.melodyStyle);
        fill (mod2Box, mod2Lbl, to->getProperty ("phrase_shape"), "Phrase", proc.phraseShape);
    }
    resized();
}

void AIPartBankEditor::rebuildBankList()
{
    rows.clear();
    for (int i = 0; i < proc.bank.size(); ++i)
    {
        auto* row = new BankRow (*proc.bank[i]);
        row->playBtn.onClick = [this, i] { toggleRow (i); };
        row->delBtn.onClick  = [this, i] { deleteRow (i); };
        bankContainer.addAndMakeVisible (row);
        rows.add (row);
    }
    const int rowH = 26;
    bankContainer.setSize (juce::jmax (10, bankViewport.getWidth() - 8), juce::jmax (1, rows.size() * rowH));
    for (int i = 0; i < rows.size(); ++i)
        rows[i]->setBounds (0, i * rowH, bankContainer.getWidth(), rowH);
    refreshGlyphs();
}

void AIPartBankEditor::toggleRow (int index)
{
    if (! juce::isPositiveAndBelow (index, proc.bank.size())) return;
    auto* item = proc.bank[index];
#if AIPG_MIDI_FX
    if (activeIndex == index) { proc.armItem (nullptr); activeIndex = -1; }
    else                      { proc.armItem (item);    activeIndex = index; }
#else
    if (activeIndex == index && proc.isPlaying()) { proc.stopPlayback(); activeIndex = -1; }
    else                                          { proc.playItem (*item); activeIndex = index; }
#endif
    refreshGlyphs();
}

void AIPartBankEditor::deleteRow (int index)
{
    if (! juce::isPositiveAndBelow (index, proc.bank.size())) return;
    if (activeIndex == index)
    {
       #if AIPG_MIDI_FX
        proc.armItem (nullptr);
       #else
        proc.stopPlayback();
       #endif
        activeIndex = -1;
    }
    proc.bank.remove (index);   // OwnedArray deletes the item
    rebuildBankList();
}

void AIPartBankEditor::clearBank()
{
   #if AIPG_MIDI_FX
    proc.armItem (nullptr);
   #else
    proc.stopPlayback();
   #endif
    activeIndex = -1;
    for (auto* it : proc.bank) { it->midiFile.deleteFile(); it->wavFile.deleteFile(); }
    proc.bank.clear();
    rebuildBankList();
    status.setText ("Bank cleared.", juce::dontSendNotification);
}

void AIPartBankEditor::refreshGlyphs()
{
    for (int i = 0; i < rows.size(); ++i)
    {
       #if AIPG_MIDI_FX
        rows[i]->playBtn.setButtonText (i == activeIndex ? "On" : "Arm");
       #else
        rows[i]->playBtn.setButtonText (i == activeIndex ? "Stop" : "Play");
       #endif
    }
}

void AIPartBankEditor::timerCallback()
{
#if ! AIPG_MIDI_FX
    if (activeIndex >= 0 && ! proc.isPlaying()) { activeIndex = -1; refreshGlyphs(); }
#endif
}

void AIPartBankEditor::paint (juce::Graphics& g)
{
    g.fillAll (getLookAndFeel().findColour (juce::ResizableWindow::backgroundColourId));
}

void AIPartBankEditor::resized()
{
    auto r = getLocalBounds().reduced (12);
    title.setBounds (r.removeFromTop (26));
    r.removeFromTop (4);

    auto row = [&r] (juce::Label& lbl, juce::Component& field)
    {
        auto line = r.removeFromTop (24);
        lbl.setBounds (line.removeFromLeft (60));
        field.setBounds (line);
        r.removeFromTop (3);
    };
    row (targetLbl, targetBox);
    row (genreLbl,  genreBox);
    if (mod1Box.isVisible()) row (mod1Lbl, mod1Box);
    if (mod2Box.isVisible()) row (mod2Lbl, mod2Box);
    if (octaveSlider.isVisible())  row (octaveLbl, octaveSlider);
    if (densitySlider.isVisible()) row (densityLbl, densitySlider);
    row (keyLbl,    keyEdit);
    row (tempoLbl,  tempoEdit);
    row (barsLbl,   barsEdit);
    row (progLbl,   progEdit);
    row (serverLbl, serverEdit);

    r.removeFromTop (4);
    generateBtn.setBounds (r.removeFromTop (28));
    status.setBounds (r.removeFromTop (32));
    r.removeFromTop (4);
    auto bt = r.removeFromTop (22);
    clearBtn.setBounds (bt.removeFromRight (90));
    bankTitle.setBounds (bt);
    bankViewport.setBounds (r);

    // keep the bank rows sized to the viewport width
    const int rowH = 26;
    bankContainer.setSize (juce::jmax (10, bankViewport.getWidth() - 8), juce::jmax (1, rows.size() * rowH));
    for (int i = 0; i < rows.size(); ++i)
        rows[i]->setBounds (0, i * rowH, bankContainer.getWidth(), rowH);
}
