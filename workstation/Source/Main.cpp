/*
    AI Workstation — Tracktion Engine app: generate a song, see/select each
    track, and shape it with our own instrument + a channel strip (EQ + Comp).

    "Generate Song" -> /api/generate-arrangement:
      * melodic parts (Chords/Bass/Melody) come back as MIDI -> our AI Synth,
      * Drums are rendered to a WAV on their own audio track.
    Each track carries an EqualiserPlugin + CompressorPlugin (off by default).
    The Tracks panel lists every track (name · template · notes, mute/solo);
    selecting one binds the right-hand channel strip (instrument macros + EQ +
    Compressor) to THAT track.
*/

#include <juce_gui_basics/juce_gui_basics.h>
#include <tracktion_engine/tracktion_engine.h>
#include "AISynthPlugin.h"
#include "AIPreampPlugin.h"

namespace te = tracktion;
using namespace juce;

//==============================================================================
class MainComponent : public Component,
                      private Thread
{
public:
    MainComponent() : Thread ("au-scan")
    {
        auto& pm = engine.getPluginManager();
        pm.initialise();
        pm.createBuiltInType<tewk::AISynthPlugin>();
        pm.createBuiltInType<tewk::AIPreampPlugin>();
        engine.getDeviceManager().initialise (0, 2);

        edit = te::Edit::createSingleTrackEdit (engine);

        header.setText ("AI Workstation", dontSendNotification);
        header.setFont (FontOptions (19.0f, Font::bold));
        addAndMakeVisible (header);
        status.setJustificationType (Justification::topLeft);
        addAndMakeVisible (status);

        // --- generation row ---
        auto field = [this] (TextEditor& e, Label& l, const String& name, const String& val)
        {
            l.setText (name, dontSendNotification); l.setJustificationType (Justification::centredRight); addAndMakeVisible (l);
            e.setText (val, dontSendNotification); addAndMakeVisible (e);
        };
        field (keyEdit, keyLbl, "Key", "C");
        field (tempoEdit, tempoLbl, "Tempo", "120");
        field (barsEdit, barsLbl, "Bars", "8");
        field (genreEdit, genreLbl, "Genre", "pop_full_song");
        generateButton.setButtonText ("Generate Song");
        generateButton.onClick = [this] { generateSong(); };
        addAndMakeVisible (generateButton);

        // --- tracks panel ---
        tracksTitle.setText ("Tracks", dontSendNotification);
        tracksTitle.setFont (FontOptions (15.0f, Font::bold));
        addAndMakeVisible (tracksTitle);
        tracksViewport.setViewedComponent (&tracksContainer, false);
        tracksViewport.setScrollBarsShown (true, false);
        addAndMakeVisible (tracksViewport);

        // --- channel strip (scrollable) lives in stripContent ---
        addAndMakeVisible (stripViewport);
        stripViewport.setViewedComponent (&stripContent, false);
        stripViewport.setScrollBarsShown (true, false);

        instrTitle.setText ("Instrument", dontSendNotification);
        instrTitle.setFont (FontOptions (15.0f, Font::bold));
        stripContent.addAndMakeVisible (instrTitle);
        templateLbl.setText ("Template", dontSendNotification);
        templateLbl.setJustificationType (Justification::centredRight);
        stripContent.addAndMakeVisible (templateLbl);
        for (int i = 0; i < 4; ++i) templateBox.addItem (tewk::AISynthPlugin::templateName (i), i + 1);
        templateBox.onChange = [this]
        {
            if (synth != nullptr) { synth->selectTemplate ((tewk::InstrTemplate) (templateBox.getSelectedId() - 1)); syncMacrosToUI(); updateRowText (selected); }
        };
        stripContent.addAndMakeVisible (templateBox);

        const char* mn[NumMacros] = { "Tone", "Shape", "Attack", "Release", "Space", "Move", "Level" };
        for (int i = 0; i < NumMacros; ++i)
            makeSlider (macroSlider[i], macroLbl[i], mn[i], 0.0, 1.0, 0.001,
                        [this, i] { if (auto p = paramFor (i)) p->setParameter ((float) macroSlider[i].getValue(), sendNotification); });

        // Channel section (volume + pan) at the very top of the strip
        chanTitle.setText ("Channel", dontSendNotification);
        chanTitle.setFont (FontOptions (15.0f, Font::bold));
        stripContent.addAndMakeVisible (chanTitle);
        makeSlider (volSlider, volLbl, "Volume dB", -48.0, 6.0, 0.1,
                    [this] { if (auto* t = curTrack()) if (auto* v = t->getVolumePlugin()) v->setVolumeDb ((float) volSlider.getValue()); });
        makeSlider (panSlider, panLbl, "Pan", -1.0, 1.0, 0.01,
                    [this] { if (auto* t = curTrack()) if (auto* v = t->getVolumePlugin()) v->setPan ((float) panSlider.getValue()); });

        // Master volume (lives by the transport, not in the per-track strip)
        masterLbl.setText ("Master", dontSendNotification);
        masterLbl.setJustificationType (Justification::centredRight);
        addAndMakeVisible (masterLbl);
        masterSlider.setSliderStyle (Slider::LinearHorizontal);
        masterSlider.setRange (-48.0, 6.0, 0.1);
        masterSlider.setTextBoxStyle (Slider::TextBoxRight, false, 50, 22);
        masterSlider.onValueChange = [this] { if (auto m = edit->getMasterVolumePlugin()) m->setVolumeDb ((float) masterSlider.getValue()); };
        addAndMakeVisible (masterSlider);

        // Preamp section (first in the chain) — toggle doubles as header / on-off
        preampOn.setButtonText ("Preamp");
        preampOn.onClick = [this] { if (auto* pp = curPreamp()) pp->setEnabled (preampOn.getToggleState()); };
        stripContent.addAndMakeVisible (preampOn);
        makeSlider (preampSlider[0], preampLbl[0], "Drive",  0.0, 1.0, 0.001, [this] { applyPreamp(); });
        makeSlider (preampSlider[1], preampLbl[1], "Output", 0.0, 1.0, 0.001, [this] { applyPreamp(); });

        // EQ section (the toggle doubles as the section header / on-off)
        eqOn.setButtonText ("EQ");
        eqOn.onClick = [this] { if (auto* e = curEq()) e->setEnabled (eqOn.getToggleState()); };
        stripContent.addAndMakeVisible (eqOn);
        const char* en[3] = { "Low dB", "Mid dB", "High dB" };
        for (int i = 0; i < 3; ++i)
            makeSlider (eqSlider[i], eqLbl[i], en[i], -20.0, 20.0, 0.1, [this, i] { applyEq (i); });

        // Compressor section
        compOn.setButtonText ("Compressor");
        compOn.onClick = [this] { if (auto* c = curComp()) c->setEnabled (compOn.getToggleState()); };
        stripContent.addAndMakeVisible (compOn);
        makeSlider (compSlider[0], compLbl[0], "Thresh dB", -40.0, 0.0, 0.5, [this] { applyComp(); });
        makeSlider (compSlider[1], compLbl[1], "Ratio",       1.0, 20.0, 0.1, [this] { applyComp(); });
        makeSlider (compSlider[2], compLbl[2], "Attack ms",   0.3, 200.0, 0.5, [this] { applyComp(); });
        makeSlider (compSlider[3], compLbl[3], "Release ms", 10.0, 300.0, 1.0, [this] { applyComp(); });

        // --- transport + info ---
        auto button = [this] (TextButton& b, const String& t, std::function<void()> fn)
        { b.setButtonText (t); b.onClick = std::move (fn); addAndMakeVisible (b); };
        button (playButton, "Play", [this] { playFromStart(); });
        button (stopButton, "Stop", [this] { stopPlayback(); });
        button (renderButton, "Render", [this] { renderWav(); });
        button (saveButton, "Save", [this] { saveProject(); });
        button (loadButton, "Load", [this] { loadProject(); });
        button (scanButton, "Scan AU", [this] { startScan(); });

        info.setMultiLine (true); info.setReadOnly (true);
        info.setFont (FontOptions (Font::getDefaultMonospacedFontName(), 12.0f, Font::plain));
        info.setText ("Press \"Generate Song\" to build a multi-track arrangement. Click a track to edit its instrument + EQ + Compressor.",
                      dontSendNotification);
        addAndMakeVisible (info);

        timeline.getEdit = [this] { return edit.get(); };
        addAndMakeVisible (timeline);

        buildInstrumentAndPhrase();
        setSize (980, 820);
    }

    ~MainComponent() override
    {
        stopThread (5000);
        if (edit != nullptr) edit->getTransport().stop (false, false);
    }

    void resized() override
    {
        auto r = getLocalBounds().reduced (16);
        header.setBounds (r.removeFromTop (26));
        status.setBounds (r.removeFromTop (40));
        r.removeFromTop (6);

        auto genRow = r.removeFromTop (28);
        auto fb = [&genRow] (Label& l, TextEditor& e, int lw, int ew)
        { l.setBounds (genRow.removeFromLeft (lw)); e.setBounds (genRow.removeFromLeft (ew)); genRow.removeFromLeft (8); };
        fb (keyLbl, keyEdit, 30, 44); fb (tempoLbl, tempoEdit, 44, 50);
        fb (barsLbl, barsEdit, 34, 44); fb (genreLbl, genreEdit, 44, 150);
        generateButton.setBounds (genRow.removeFromLeft (130));
        r.removeFromTop (10);

        timeline.setBounds (r.removeFromTop (120));
        r.removeFromTop (10);

        auto bottom = r.removeFromBottom (150);
        auto transport = bottom.removeFromTop (30);
        for (auto* b : { &playButton, &stopButton, &renderButton, &saveButton, &loadButton, &scanButton })
        { b->setBounds (transport.removeFromLeft (80)); transport.removeFromLeft (5); }
        masterSlider.setBounds (transport.removeFromRight (150));
        masterLbl.setBounds (transport.removeFromRight (56));
        bottom.removeFromTop (8);
        info.setBounds (bottom);

        auto left = r.removeFromLeft (340);
        tracksTitle.setBounds (left.removeFromTop (22));
        tracksViewport.setBounds (left);
        layoutTrackRows();

        r.removeFromLeft (16);
        stripViewport.setBounds (r);
        layoutStrip();
    }

    void paint (Graphics& g) override { g.fillAll (getLookAndFeel().findColour (ResizableWindow::backgroundColourId)); }

private:
    enum { NumMacros = 7 };
    const String serverBase { "http://127.0.0.1:7860" };

    struct TrackEntry
    {
        te::AudioTrack* track = nullptr;
        tewk::AISynthPlugin* synth = nullptr;
        tewk::AIPreampPlugin* preamp = nullptr;
        te::EqualiserPlugin* eq = nullptr;
        te::CompressorPlugin* comp = nullptr;
        String role; int notes = 0;
    };

    void makeSlider (Slider& s, Label& l, const String& name, double lo, double hi, double step, std::function<void()> onChange)
    {
        l.setText (name, dontSendNotification); l.setJustificationType (Justification::centredRight);
        stripContent.addAndMakeVisible (l);
        s.setSliderStyle (Slider::LinearHorizontal);
        s.setRange (lo, hi, step);
        s.setTextBoxStyle (Slider::TextBoxRight, false, 56, 22);
        s.onValueChange = std::move (onChange);
        stripContent.addAndMakeVisible (s);
    }

    //== selectable track row ==================================================
    struct TrackRow : public Component
    {
        TrackRow (int i, std::function<void(int)> onSel) : index (i), select (std::move (onSel))
        {
            mute.setButtonText ("M");  mute.setClickingTogglesState (true);  addAndMakeVisible (mute);
            solo.setButtonText ("S");  solo.setClickingTogglesState (true);  addAndMakeVisible (solo);
            regen.setButtonText ("Regen"); addAndMakeVisible (regen);
        }
        void mouseDown (const MouseEvent&) override { if (select) select (index); }
        void resized() override
        {
            auto a = getLocalBounds().reduced (4);
            solo.setBounds (a.removeFromRight (26)); a.removeFromRight (4);
            mute.setBounds (a.removeFromRight (26)); a.removeFromRight (6);
            regen.setBounds (a.removeFromRight (54));
            textArea = a;
        }
        void paint (Graphics& g) override
        {
            g.fillAll (selected ? Colour (0xff3b5bdb) : Colour (0xff343434));
            g.setColour (Colours::white); g.setFont (FontOptions (14.0f));
            g.drawText (text, textArea.reduced (6, 0), Justification::centredLeft);
        }
        int index; std::function<void(int)> select;
        bool selected = false; String text; Rectangle<int> textArea;
        TextButton mute, solo, regen;
    };

    //== timeline: lanes + clips + moving playhead =============================
    struct Timeline : public Component, private Timer
    {
        std::function<te::Edit*()> getEdit;
        Timeline() { startTimerHz (30); }
        ~Timeline() override { stopTimer(); }
        void timerCallback() override { repaint(); }

        void paint (Graphics& g) override
        {
            g.fillAll (Colour (0xff1b1b1b));
            auto* edit = getEdit ? getEdit() : nullptr;
            if (edit == nullptr) return;
            auto tracks = tracktion::getAudioTracks (*edit);
            const int n = tracks.size();
            if (n == 0) return;

            const double bpm = edit->tempoSequence.getTempo (0) != nullptr ? edit->tempoSequence.getTempo (0)->getBpm() : 120.0;
            auto secToBeat = [bpm] (double s) { return s * bpm / 60.0; };

            double totalBeats = 8.0;
            for (auto* t : tracks)
                for (auto* c : t->getClips())
                    totalBeats = juce::jmax (totalBeats, secToBeat (c->getPosition().getEnd().inSeconds()));

            const int labelW = 72;
            const float laneH = (float) getHeight() / (float) n;
            const float trackW = (float) (getWidth() - labelW);
            auto beatToX = [&] (double b) { return labelW + (float) (b / juce::jmax (1.0, totalBeats)) * trackW; };

            for (int i = 0; i < n; ++i)
            {
                const float y = i * laneH;
                g.setColour ((i % 2) ? Colour (0xff242424) : Colour (0xff1f1f1f));
                g.fillRect (0.0f, y, (float) getWidth(), laneH);
                g.setColour (Colours::lightgrey); g.setFont (FontOptions (12.0f));
                g.drawText (tracks[i]->getName(), 5, (int) y, labelW - 8, (int) laneH, Justification::centredLeft);
                g.setColour (Colour (0xff3b5bdb));
                for (auto* clip : tracks[i]->getClips())
                {
                    const auto pos = clip->getPosition();
                    const float x1 = beatToX (secToBeat (pos.getStart().inSeconds()));
                    const float x2 = beatToX (secToBeat (pos.getEnd().inSeconds()));
                    g.fillRoundedRectangle (x1 + 1.0f, y + 3.0f, juce::jmax (2.0f, x2 - x1 - 2.0f), laneH - 6.0f, 3.0f);
                }
            }

            const float px = beatToX (secToBeat (edit->getTransport().getPosition().inSeconds()));
            g.setColour (Colours::yellow);
            g.drawLine (px, 0.0f, px, (float) getHeight(), 1.5f);
        }

        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (Timeline)
    };

    void rebuildTrackList()
    {
        trackRows.clear();
        tracksContainer.removeAllChildren();
        for (int i = 0; i < (int) entries.size(); ++i)
        {
            auto* row = new TrackRow (i, [this] (int idx) { selectTrack (idx); });
            auto* tr = entries[(size_t) i].track;
            row->mute.setToggleState (tr->isMuted (false), dontSendNotification);
            row->mute.onClick = [tr, row] { tr->setMute (row->mute.getToggleState()); };
            row->solo.setToggleState (tr->isSolo (false), dontSendNotification);
            row->solo.onClick = [tr, row] { tr->setSolo (row->solo.getToggleState()); };
            row->regen.onClick = [this, i] { regenerateTrack (i); };
            row->selected = (i == selected);
            tracksContainer.addAndMakeVisible (row);
            trackRows.add (row);
            updateRowText (i);
        }
        layoutTrackRows();
    }

    void layoutTrackRows()
    {
        const int h = 36, gap = 3;
        const int w = jmax (40, tracksViewport.getWidth() - (tracksViewport.isVerticalScrollBarShown() ? 14 : 2));
        for (int i = 0; i < trackRows.size(); ++i) trackRows[i]->setBounds (0, i * (h + gap), w, h);
        tracksContainer.setSize (w, jmax (1, (int) trackRows.size()) * (h + gap));
    }

    void updateRowText (int i)
    {
        if (i < 0 || i >= (int) entries.size() || i >= trackRows.size()) return;
        auto& e = entries[(size_t) i];
        const String tmpl = e.synth ? String (tewk::AISynthPlugin::templateName (e.synth->getTemplateIndex())) : String ("audio");
        const String detail = e.notes < 0 ? String ("WAV") : (String (e.notes) + " notes");
        trackRows[i]->text = e.role + "    " + tmpl + "    " + detail;
        trackRows[i]->repaint();
    }

    void selectTrack (int i)
    {
        if (i < 0 || i >= (int) entries.size()) return;
        selected = i;
        synth = entries[(size_t) i].synth;
        for (int k = 0; k < trackRows.size(); ++k) { trackRows[k]->selected = (k == i); trackRows[k]->repaint(); }

        const bool hasSynth = (synth != nullptr);
        templateBox.setEnabled (hasSynth);
        for (int m = 0; m < NumMacros; ++m) macroSlider[m].setEnabled (hasSynth);
        if (hasSynth) templateBox.setSelectedId (synth->getTemplateIndex() + 1, dontSendNotification);
        syncMacrosToUI();

        if (auto* t = curTrack())
            if (auto* v = t->getVolumePlugin())
            {
                volSlider.setValue (v->getVolumeDb(), dontSendNotification);
                panSlider.setValue (v->getPan(), dontSendNotification);
            }
        if (auto* pp = curPreamp())
        {
            preampOn.setToggleState (pp->isEnabled(), dontSendNotification);
            preampSlider[0].setValue (pp->drive->getCurrentValue(), dontSendNotification);
            preampSlider[1].setValue (pp->output->getCurrentValue(), dontSendNotification);
        }
        if (auto* e = curEq())
        {
            eqOn.setToggleState (e->isEnabled(), dontSendNotification);
            eqSlider[0].setValue (e->loGain->getCurrentValue(), dontSendNotification);
            eqSlider[1].setValue (e->midGain1->getCurrentValue(), dontSendNotification);
            eqSlider[2].setValue (e->hiGain->getCurrentValue(), dontSendNotification);
        }
        if (auto* c = curComp())
        {
            compOn.setToggleState (c->isEnabled(), dontSendNotification);
            compSlider[0].setValue (Decibels::gainToDecibels (c->thresholdGain.getCurrentValue()), dontSendNotification);
            compSlider[1].setValue (1.0 / jmax (0.05f, c->ratio.getCurrentValue()), dontSendNotification);
            compSlider[2].setValue (c->attackMs.getCurrentValue(), dontSendNotification);
            compSlider[3].setValue (c->releaseMs.getCurrentValue(), dontSendNotification);
        }
        refreshStatus();
    }

    bool selValid() const { return selected >= 0 && selected < (int) entries.size(); }
    te::AudioTrack*       curTrack()  { return selValid() ? entries[(size_t) selected].track  : nullptr; }
    tewk::AIPreampPlugin* curPreamp() { return selValid() ? entries[(size_t) selected].preamp : nullptr; }
    te::EqualiserPlugin*  curEq()     { return selValid() ? entries[(size_t) selected].eq   : nullptr; }
    te::CompressorPlugin* curComp()   { return selValid() ? entries[(size_t) selected].comp : nullptr; }

    void applyPreamp()
    {
        if (auto* pp = curPreamp())
        {
            pp->drive->setParameter ((float) preampSlider[0].getValue(), sendNotification);
            pp->output->setParameter ((float) preampSlider[1].getValue(), sendNotification);
        }
    }

    void applyEq (int band)
    {
        if (auto* e = curEq())
        {
            const float v = (float) eqSlider[band].getValue();
            if (band == 0) e->setLowGain (v); else if (band == 1) e->setMidGain1 (v); else e->setHighGain (v);
        }
    }

    void applyComp()
    {
        if (auto* c = curComp())
        {
            c->thresholdGain.setParameter (jlimit (0.01f, 1.0f, Decibels::decibelsToGain ((float) compSlider[0].getValue())), sendNotification);
            c->ratio.setParameter (jlimit (0.0f, 0.95f, 1.0f / jmax (1.0f, (float) compSlider[1].getValue())), sendNotification);
            c->attackMs.setParameter ((float) compSlider[2].getValue(), sendNotification);
            c->releaseMs.setParameter ((float) compSlider[3].getValue(), sendNotification);
        }
    }

    //== instrument plumbing ===================================================
    te::AutomatableParameter::Ptr paramFor (int i) const
    {
        if (synth == nullptr) return {};
        switch (i)
        {
            case 0: return synth->tone;   case 1: return synth->shape;
            case 2: return synth->attack; case 3: return synth->release;
            case 4: return synth->space;  case 5: return synth->move;
            case 6: return synth->level;  default: return {};
        }
    }

    void syncMacrosToUI()
    {
        for (int i = 0; i < NumMacros; ++i)
            if (auto p = paramFor (i)) macroSlider[i].setValue (p->getCurrentValue(), dontSendNotification);
    }

    void refreshStatus()
    {
        auto* dev = engine.getDeviceManager().deviceManager.getCurrentAudioDevice();
        String s;
        s << "Engine up    |    Tracks: " << (int) entries.size()
          << "    |    Selected: " << (selected >= 0 && selected < (int) entries.size() ? entries[(size_t) selected].role : String ("-")) << "\n";
        s << "Audio out: " << (dev != nullptr ? dev->getName() : String ("(none)"));
        status.setText (s, dontSendNotification);
    }

    void reloadMaster()
    {
        if (auto m = edit->getMasterVolumePlugin()) masterSlider.setValue (m->getVolumeDb(), dontSendNotification);
    }

    //== edit building =========================================================
    te::AudioTrack* getOrInsertAudioTrackAt (int index)
    {
        edit->ensureNumberOfAudioTracks (index + 1);
        return te::getAudioTracks (*edit)[index];
    }

    template <typename T>
    T* insertPluginOfType (te::AudioTrack* track, const char* type, int index)
    {
        if (auto p = edit->getPluginCache().createNewPlugin (type, {}))
        {
            auto* tp = dynamic_cast<T*> (p.get());
            track->pluginList.insertPlugin (p, index, nullptr);
            return tp;
        }
        return nullptr;
    }

    // Every track gets Preamp -> EQ -> Compressor (off by default) after its source.
    void addChannelStrip (TrackEntry& e, int baseIndex)
    {
        e.preamp = insertPluginOfType<tewk::AIPreampPlugin> (e.track, tewk::AIPreampPlugin::xmlTypeName, baseIndex);
        e.eq     = insertPluginOfType<te::EqualiserPlugin>  (e.track, te::EqualiserPlugin::xmlTypeName,  baseIndex + 1);
        e.comp   = insertPluginOfType<te::CompressorPlugin> (e.track, te::CompressorPlugin::xmlTypeName, baseIndex + 2);
        if (e.preamp != nullptr) e.preamp->setEnabled (false);
        if (e.eq     != nullptr) e.eq->setEnabled (false);
        if (e.comp   != nullptr) e.comp->setEnabled (false);
    }

    int addNotes (te::AudioTrack* track, const String& name, const var& notes, double minLenBeats)
    {
        auto* arr = notes.getArray();
        if (arr == nullptr || arr->isEmpty()) return 0;
        double maxEnd = minLenBeats;
        for (auto& n : *arr)
            if (auto* a = n.getArray()) if (a->size() >= 3) maxEnd = jmax (maxEnd, (double) (*a)[1] + (double) (*a)[2]);
        const auto range = edit->tempoSequence.toTime ({ te::BeatPosition::fromBeats (0.0), te::BeatPosition::fromBeats (maxEnd) });
        int count = 0;
        if (auto* clip = dynamic_cast<te::MidiClip*> (track->insertNewClip (te::TrackItem::Type::midi, name, range, nullptr)))
        {
            auto& seq = clip->getSequence(); auto* um = &edit->getUndoManager();
            for (auto& n : *arr)
                if (auto* a = n.getArray()) if (a->size() >= 3)
                { seq.addNote ((int) (*a)[0], te::BeatPosition::fromBeats ((double) (*a)[1]),
                               te::BeatDuration::fromBeats (jmax (0.05, (double) (*a)[2])), 92, 0, um); ++count; }
        }
        return count;
    }

    void buildInstrumentAndPhrase()
    {
        entries.clear();
        auto* track = getOrInsertAudioTrackAt (0);
        track->setName ("Demo");
        auto* sp = insertPluginOfType<tewk::AISynthPlugin> (track, tewk::AISynthPlugin::xmlTypeName, 0);
        if (sp != nullptr) sp->selectTemplate (tewk::InstrTemplate::pad);

        Array<var> arr;
        auto add = [&] (int p, double s, double l) { arr.add (var (Array<var> { p, s, l })); };
        for (double bar = 0.0; bar < 8.0; bar += 4.0) { add (48, bar, 4.0); add (51, bar, 4.0); add (55, bar, 4.0); }
        const int a[] = { 60, 63, 67, 70, 67, 63, 67, 70 };
        for (int i = 0; i < 8; ++i) add (a[i], (double) i, 0.9);
        int n = addNotes (track, "Demo", var (arr), 8.0);

        TrackEntry e { track, sp, nullptr, nullptr, nullptr, "Demo", n };
        addChannelStrip (e, 1);
        entries.push_back (e);
        selected = 0; synth = sp;
        rebuildTrackList();
        selectTrack (0);
        reloadMaster();
    }

    //== generation ============================================================
    static tewk::InstrTemplate templateForRole (const String& role)
    {
        if (role.equalsIgnoreCase ("Bass"))   return tewk::InstrTemplate::bass;
        if (role.equalsIgnoreCase ("Melody")) return tewk::InstrTemplate::lead;
        if (role.equalsIgnoreCase ("Chords")) return tewk::InstrTemplate::pad;
        return tewk::InstrTemplate::pluck;
    }

    String makeBody (const StringArray& parts, const String& output, int seed) const
    {
        DynamicObject::Ptr b = new DynamicObject();
        b->setProperty ("key",   keyEdit.getText().trim().isEmpty() ? "C" : keyEdit.getText().trim());
        b->setProperty ("scale", "major");
        b->setProperty ("tempo", jlimit (40, 240, tempoEdit.getText().getIntValue()));
        b->setProperty ("bars",  jlimit (1, 64, barsEdit.getText().getIntValue()));
        b->setProperty ("genre", genreEdit.getText().trim());
        b->setProperty ("output", output);
        b->setProperty ("seed", seed);
        Array<var> pj; for (auto& p : parts) pj.add (p);
        b->setProperty ("parts", var (pj));
        return JSON::toString (var (b.get()));
    }

    void generateSong()
    {
        genSeed = Random::getSystemRandom().nextInt (1000000);
        generateButton.setEnabled (false);
        info.setText ("Generating arrangement (melodic parts)...", dontSendNotification);

        const auto url = serverBase + "/api/generate-arrangement";
        const auto payload = makeBody ({ "chords", "bass", "melody" }, "midi", genSeed);
        Component::SafePointer<MainComponent> safe (this);
        Thread::launch ([safe, url, payload]
        {
            var resp;
            juce::URL u = juce::URL (url).withPOSTData (payload);
            auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inPostData)
                            .withExtraHeaders ("Content-Type: application/json").withConnectionTimeoutMs (120000);
            if (auto s = u.createInputStream (opts)) resp = JSON::parse (s->readEntireStreamAsString());
            MessageManager::callAsync ([safe, resp] { if (safe != nullptr) safe->onArrangement (resp); });
        });
    }

    void onArrangement (const var& resp)
    {
        if (! resp.isObject() || ! resp.hasProperty ("tracks"))
        {
            info.setText ("Generation failed (backend on " + serverBase + " not reachable).", dontSendNotification);
            generateButton.setEnabled (true);
            return;
        }

        stopPlayback();
        const double tempo = (double) resp.getProperty ("tempo", 120.0);
        genBars = (int) resp.getProperty ("bars", 8);

        edit = te::Edit::createSingleTrackEdit (engine);
        if (auto* t0 = edit->tempoSequence.getTempo (0)) t0->setBpm (tempo);

        entries.clear();
        synth = nullptr;
        StringArray built;
        if (auto* tracks = resp.getProperty ("tracks", var()).getArray())
        {
            for (auto& tv : *tracks)
            {
                const String role = tv.getProperty ("track", "").toString();
                if (role.equalsIgnoreCase ("Drums")) continue;     // drums come back as audio (pass 2)

                auto* track = getOrInsertAudioTrackAt ((int) entries.size());
                track->setName (role);
                auto* sp = insertPluginOfType<tewk::AISynthPlugin> (track, tewk::AISynthPlugin::xmlTypeName, 0);
                if (sp != nullptr) sp->selectTemplate (templateForRole (role));
                int n = addNotes (track, role, tv.getProperty ("notes", var()), genBars * 4.0);
                TrackEntry e { track, sp, nullptr, nullptr, nullptr, role, n };
                addChannelStrip (e, 1);
                entries.push_back (e);
                built.add (role);
            }
        }

        selected = 0;
        synth = entries.empty() ? nullptr : entries[0].synth;
        rebuildTrackList();
        if (! entries.empty()) selectTrack (0);
        reloadMaster();
        refreshStatus();
        info.setText ("Built " + built.joinIntoString (", ") + " @ " + String (tempo, 0) + " bpm. Rendering drums...", dontSendNotification);

        fetchDrums();
    }

    void fetchDrums()
    {
        const auto url     = serverBase + "/api/generate-arrangement";
        const auto payload = makeBody ({ "drums" }, "wav", genSeed);
        const auto base    = serverBase;
        Component::SafePointer<MainComponent> safe (this);
        Thread::launch ([safe, url, payload, base]
        {
            File wavFile;
            juce::URL u = juce::URL (url).withPOSTData (payload);
            auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inPostData)
                            .withExtraHeaders ("Content-Type: application/json").withConnectionTimeoutMs (120000);
            if (auto s = u.createInputStream (opts))
            {
                auto resp = JSON::parse (s->readEntireStreamAsString());
                const String pid = resp.getProperty ("part_id", "").toString();
                if (pid.isNotEmpty())
                {
                    juce::URL wu (base + "/api/parts/" + pid + "/part.wav");
                    auto f = File::getSpecialLocation (File::tempDirectory).getChildFile ("ai_ws_drums_" + pid + ".wav");
                    if (auto ws = wu.createInputStream (juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress).withConnectionTimeoutMs (120000)))
                    {
                        MemoryBlock mb; ws->readIntoMemoryBlock (mb);
                        if (mb.getSize() > 0 && f.replaceWithData (mb.getData(), mb.getSize())) wavFile = f;
                    }
                }
            }
            MessageManager::callAsync ([safe, wavFile] { if (safe != nullptr) safe->addDrumsTrack (wavFile); });
        });
    }

    void addDrumsTrack (const File& wav)
    {
        if (wav.existsAsFile() && wav.getSize() > 0)
        {
            auto* track = getOrInsertAudioTrackAt ((int) entries.size());
            track->setName ("Drums");
            const auto range = edit->tempoSequence.toTime ({ te::BeatPosition::fromBeats (0.0), te::BeatPosition::fromBeats (genBars * 4.0) });
            track->insertWaveClip ("Drums", wav, te::ClipPosition { range }, false);
            TrackEntry e { track, nullptr, nullptr, nullptr, nullptr, "Drums", -1 };
            addChannelStrip (e, 0);   // no instrument, Preamp+EQ+Comp at the front
            entries.push_back (e);
            rebuildTrackList();
        }

        refreshStatus();
        edit->getTransport().ensureContextAllocated();
        edit->getTransport().playFromStart (true);
        generateButton.setEnabled (true);
        info.setText ("Full arrangement: " + String ((int) entries.size())
                      + " tracks (drums = rendered audio). Click a track for its instrument + EQ + Compressor.", dontSendNotification);
    }

    //== regenerate a single track =============================================
    void clearTrackClips (te::AudioTrack* track)
    {
        juce::Array<te::Clip*> clips (track->getClips());   // copy — we mutate while iterating
        for (auto* c : clips) c->removeFromParent();
    }

    void regenerateTrack (int i)
    {
        if (i < 0 || i >= (int) entries.size()) return;
        auto* track = entries[(size_t) i].track;
        const String role = entries[(size_t) i].role;
        const int seed = Random::getSystemRandom().nextInt (1000000);
        info.setText ("Regenerating " + role + "...", dontSendNotification);

        if (role.equalsIgnoreCase ("Drums"))
        {
            const auto url = serverBase + "/api/generate-arrangement";
            const auto payload = makeBody ({ "drums" }, "wav", seed);
            const auto base = serverBase;
            Component::SafePointer<MainComponent> safe (this);
            Thread::launch ([safe, url, payload, base, track]
            {
                File wavFile;
                juce::URL u = juce::URL (url).withPOSTData (payload);
                auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inPostData)
                                .withExtraHeaders ("Content-Type: application/json").withConnectionTimeoutMs (120000);
                if (auto s = u.createInputStream (opts))
                {
                    auto resp = JSON::parse (s->readEntireStreamAsString());
                    const String pid = resp.getProperty ("part_id", "").toString();
                    if (pid.isNotEmpty())
                    {
                        juce::URL wu (base + "/api/parts/" + pid + "/part.wav");
                        auto f = File::getSpecialLocation (File::tempDirectory).getChildFile ("ai_ws_drums_" + pid + ".wav");
                        if (auto ws = wu.createInputStream (juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress).withConnectionTimeoutMs (120000)))
                        { MemoryBlock mb; ws->readIntoMemoryBlock (mb); if (mb.getSize() > 0 && f.replaceWithData (mb.getData(), mb.getSize())) wavFile = f; }
                    }
                }
                MessageManager::callAsync ([safe, wavFile, track] { if (safe != nullptr) safe->applyDrumRegen (track, wavFile); });
            });
        }
        else
        {
            const auto url = serverBase + "/api/generate-arrangement";
            const auto payload = makeBody ({ role.toLowerCase() }, "midi", seed);
            Component::SafePointer<MainComponent> safe (this);
            Thread::launch ([safe, url, payload, track, role]
            {
                var resp;
                juce::URL u = juce::URL (url).withPOSTData (payload);
                auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inPostData)
                                .withExtraHeaders ("Content-Type: application/json").withConnectionTimeoutMs (120000);
                if (auto s = u.createInputStream (opts)) resp = JSON::parse (s->readEntireStreamAsString());
                MessageManager::callAsync ([safe, resp, track, role] { if (safe != nullptr) safe->applyMelodicRegen (track, role, resp); });
            });
        }
    }

    void applyMelodicRegen (te::AudioTrack* track, const String& role, const var& resp)
    {
        if (! resp.isObject()) { info.setText ("Regen failed.", dontSendNotification); return; }
        var notes;
        if (auto* tracks = resp.getProperty ("tracks", var()).getArray())
            if (! tracks->isEmpty()) notes = (*tracks)[0].getProperty ("notes", var());

        clearTrackClips (track);
        const int n = addNotes (track, role, notes, genBars * 4.0);
        for (size_t k = 0; k < entries.size(); ++k)
            if (entries[k].track == track) { entries[k].notes = n; updateRowText ((int) k); }
        info.setText ("Regenerated " + role + " (" + String (n) + " notes).", dontSendNotification);
    }

    void applyDrumRegen (te::AudioTrack* track, const File& wav)
    {
        if (wav.existsAsFile() && wav.getSize() > 0)
        {
            clearTrackClips (track);
            const auto range = edit->tempoSequence.toTime ({ te::BeatPosition::fromBeats (0.0), te::BeatPosition::fromBeats (genBars * 4.0) });
            track->insertWaveClip ("Drums", wav, te::ClipPosition { range }, false);
            info.setText ("Regenerated Drums.", dontSendNotification);
        }
        else info.setText ("Drum regen failed.", dontSendNotification);
    }

    //== transport / render ====================================================
    void playFromStart() { auto& t = edit->getTransport(); t.ensureContextAllocated(); t.playFromStart (true); }
    void stopPlayback()  { if (edit) edit->getTransport().stop (false, false); }

    void renderWav()
    {
        stopPlayback();
        auto out = File::getSpecialLocation (File::userDesktopDirectory).getChildFile ("AI Workstation.wav");
        const bool ok = te::Renderer::renderToFile (*edit, out, false);
        info.setText (ok ? ("Rendered: " + out.getFullPathName()) : "Render failed.", dontSendNotification);
    }

    //== save / load ===========================================================
    void saveProject()
    {
        auto fc = std::make_shared<FileChooser> ("Save project",
                      File::getSpecialLocation (File::userDocumentsDirectory).getChildFile ("song.tracktionedit"),
                      "*.tracktionedit");
        fc->launchAsync (FileBrowserComponent::saveMode | FileBrowserComponent::warnAboutOverwriting,
            [this, fc] (const FileChooser& c)
            {
                auto f = c.getResult();
                if (f == File()) return;
                const bool ok = te::EditFileOperations (*edit).writeToFile (f, false);
                info.setText (ok ? ("Saved: " + f.getFullPathName()) : "Save failed.", dontSendNotification);
            });
    }

    void loadProject()
    {
        auto fc = std::make_shared<FileChooser> ("Load project",
                      File::getSpecialLocation (File::userDocumentsDirectory), "*.tracktionedit");
        fc->launchAsync (FileBrowserComponent::openMode | FileBrowserComponent::canSelectFiles,
            [this, fc] (const FileChooser& c)
            {
                auto f = c.getResult();
                if (f == File() || ! f.existsAsFile()) return;
                stopPlayback();
                if (auto loaded = te::loadEditFromFile (engine, f))
                {
                    edit = std::move (loaded);
                    rebuildEntriesFromEdit();
                    info.setText ("Loaded: " + f.getFullPathName(), dontSendNotification);
                }
                else info.setText ("Load failed.", dontSendNotification);
            });
    }

    // After loading, re-discover each track's instrument + channel-strip plugins.
    void rebuildEntriesFromEdit()
    {
        entries.clear();
        for (auto* track : te::getAudioTracks (*edit))
        {
            TrackEntry e;
            e.track  = track;
            e.synth  = track->pluginList.findFirstPluginOfType<tewk::AISynthPlugin>();
            e.preamp = track->pluginList.findFirstPluginOfType<tewk::AIPreampPlugin>();
            e.eq     = track->pluginList.findFirstPluginOfType<te::EqualiserPlugin>();
            e.comp   = track->pluginList.findFirstPluginOfType<te::CompressorPlugin>();
            e.role   = track->getName();
            int n = 0; bool midi = false;
            for (auto* clip : track->getClips())
                if (auto* mc = dynamic_cast<te::MidiClip*> (clip)) { midi = true; n += mc->getSequence().getNumNotes(); }
            e.notes = midi ? n : -1;
            entries.push_back (e);
        }
        selected = 0;
        synth = entries.empty() ? nullptr : entries[0].synth;
        rebuildTrackList();
        if (! entries.empty()) selectTrack (0);
        reloadMaster();
        refreshStatus();
    }

    //== AU scan ===============================================================
    void startScan()
    {
        if (isThreadRunning()) return;
        scanButton.setEnabled (false);
        info.setText ("Scanning Audio Units...\n", dontSendNotification);
        startThread();
    }

    void run() override
    {
        auto& pm = engine.getPluginManager();
        AudioPluginFormat* au = nullptr;
        for (auto* f : pm.pluginFormatManager.getFormats())
            if (f->getName().containsIgnoreCase ("AudioUnit")) au = f;
        if (au != nullptr)
        {
            auto dead = engine.getTemporaryFileManager().getTempDirectory().getChildFile ("dead_plugins.txt");
            PluginDirectoryScanner scanner (pm.knownPluginList, *au, au->getDefaultLocationsToSearch(), true, dead, false);
            String nm; while (! threadShouldExit() && scanner.scanNextFile (true, nm)) {}
        }
        StringArray ins;
        for (const auto& d : pm.knownPluginList.getTypes()) if (d.isInstrument) ins.add (d.name + "  [" + d.pluginFormatName + "]");
        ins.sort (true);
        Component::SafePointer<MainComponent> safe (this);
        MessageManager::callAsync ([safe, ins]
        {
            if (safe == nullptr) return;
            safe->info.setText (ins.isEmpty() ? String ("No AU instruments found.")
                : String (ins.size()) + " AU instrument(s):\n\n" + ins.joinIntoString ("\n"), dontSendNotification);
            safe->scanButton.setEnabled (true);
        });
    }

    //== channel-strip layout ==================================================
    void layoutStrip()
    {
        const int w = jmax (80, stripViewport.getWidth() - (stripViewport.isVerticalScrollBarShown() ? 16 : 2));
        const int rh = 26, gap = 4, lblW = 70, sec = 12;
        int y = 0;
        auto row = [&] (Component& l, Component& c) { l.setBounds (0, y, lblW, rh); c.setBounds (lblW + 6, y, w - lblW - 6, rh); y += rh + gap; };

        chanTitle.setBounds (0, y, w, 22); y += 24;
        row (volLbl, volSlider);
        row (panLbl, panSlider);

        y += sec;
        instrTitle.setBounds (0, y, w, 22); y += 24;
        templateLbl.setBounds (0, y, lblW, rh); templateBox.setBounds (lblW + 6, y, jmin (160, w - lblW - 6), rh); y += rh + gap;
        for (int i = 0; i < NumMacros; ++i) row (macroLbl[i], macroSlider[i]);

        y += sec;
        preampOn.setBounds (0, y, w, 22); y += 26;
        for (int i = 0; i < 2; ++i) row (preampLbl[i], preampSlider[i]);

        y += sec;
        eqOn.setBounds (0, y, w, 22); y += 26;
        for (int i = 0; i < 3; ++i) row (eqLbl[i], eqSlider[i]);

        y += sec;
        compOn.setBounds (0, y, w, 22); y += 26;
        for (int i = 0; i < 4; ++i) row (compLbl[i], compSlider[i]);

        stripContent.setSize (w, y + 8);
    }

    te::Engine engine { "AI Workstation" };
    std::unique_ptr<te::Edit> edit;
    std::vector<TrackEntry> entries;
    tewk::AISynthPlugin* synth = nullptr;
    int selected = 0;
    int genSeed = 1, genBars = 8;

    Label      header, status, tracksTitle, instrTitle;
    Label      keyLbl, tempoLbl, barsLbl, genreLbl, templateLbl;
    TextEditor keyEdit, tempoEdit, barsEdit, genreEdit;
    TextButton generateButton;

    Timeline   timeline;
    Viewport   tracksViewport;     Component tracksContainer;
    OwnedArray<TrackRow> trackRows;

    Viewport   stripViewport;      Component stripContent;
    Label      chanTitle, volLbl, panLbl;  Slider volSlider, panSlider;
    Label      masterLbl;          Slider masterSlider;
    ComboBox   templateBox;
    Label      macroLbl[NumMacros]; Slider macroSlider[NumMacros];
    ToggleButton preampOn; Label preampLbl[2]; Slider preampSlider[2];
    ToggleButton eqOn;   Label eqLbl[3];   Slider eqSlider[3];
    ToggleButton compOn; Label compLbl[4]; Slider compSlider[4];

    TextButton playButton, stopButton, renderButton, saveButton, loadButton, scanButton;
    TextEditor info;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MainComponent)
};

//==============================================================================
class AIWorkstationApplication : public JUCEApplication
{
public:
    const String getApplicationName() override     { return "AI Workstation"; }
    const String getApplicationVersion() override  { return "0.1.0"; }
    bool moreThanOneInstanceAllowed() override      { return true; }

    void initialise (const String&) override { mainWindow.reset (new MainWindow (getApplicationName())); }
    void shutdown() override                  { mainWindow = nullptr; }
    void systemRequestedQuit() override       { quit(); }

    class MainWindow : public DocumentWindow
    {
    public:
        explicit MainWindow (const String& name)
            : DocumentWindow (name, Desktop::getInstance().getDefaultLookAndFeel().findColour (ResizableWindow::backgroundColourId),
                              DocumentWindow::allButtons)
        {
            setUsingNativeTitleBar (true);
            setContentOwned (new MainComponent(), true);
            setResizable (true, true);
            centreWithSize (getWidth(), getHeight());
            setVisible (true);
        }
        void closeButtonPressed() override { JUCEApplication::getInstance()->systemRequestedQuit(); }
        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MainWindow)
    };

private:
    std::unique_ptr<MainWindow> mainWindow;
};

START_JUCE_APPLICATION (AIWorkstationApplication)
