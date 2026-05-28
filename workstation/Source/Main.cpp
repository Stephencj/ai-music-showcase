/*
    AI Workstation — Tracktion Engine app.

    Generate a multi-track song (Chords/Bass/Melody through our AI Synth, Drums
    through our AI Drum Kit), then mix it like a real desk: a vertical CHANNEL
    COLUMN per track, controls as rotary knobs (click-drag up/down), stacked
    Instrument -> Preamp -> EQ -> Compressor -> Volume/Pan. A timeline up top
    shows clips + a playhead (click to seek). Save/Load, per-track Regenerate.
*/

#include <juce_gui_basics/juce_gui_basics.h>
#include <tracktion_engine/tracktion_engine.h>
#include "AISynthPlugin.h"
#include "AIPreampPlugin.h"
#include "AIDrumKitPlugin.h"

namespace te = tracktion;
using namespace juce;

//==============================================================================
// A clean "faux knob": a wide circle with a single pointer from the centre to
// the current value. Nothing else.
struct KnobLookAndFeel : public LookAndFeel_V4
{
    void drawRotarySlider (Graphics& g, int x, int y, int w, int h,
                           float pos, float startAngle, float endAngle, Slider&) override
    {
        auto area = Rectangle<int> (x, y, w, h).toFloat().reduced (3.0f);
        const float d = jmin (area.getWidth(), area.getHeight());
        const float r = d * 0.5f;
        const auto centre = area.getCentre();
        const float angle = startAngle + pos * (endAngle - startAngle);

        g.setColour (Colour (0xff32363f));                                   // body
        g.fillEllipse (centre.x - r, centre.y - r, d, d);
        g.setColour (Colour (0xff5b6477));                                   // rim
        g.drawEllipse (centre.x - r, centre.y - r, d, d, 1.6f);

        const auto tip = centre.getPointOnCircumference (r - 4.0f, angle);   // value pointer
        g.setColour (Colour (0xffcdd6ff));
        g.drawLine ({ centre, tip }, 2.4f);
        g.setColour (Colour (0xff8fa0ff));
        g.fillEllipse (centre.x - 2.5f, centre.y - 2.5f, 5.0f, 5.0f);        // centre hub
    }

    Label* createSliderTextBox (Slider& s) override
    {
        auto* l = LookAndFeel_V4::createSliderTextBox (s);
        l->setFont (FontOptions (11.0f));
        l->setJustificationType (Justification::centred);
        l->setColour (Label::textColourId, Colour (0xffe3e7f4));
        l->setColour (Label::backgroundColourId, Colours::transparentBlack);
        l->setColour (Label::outlineColourId, Colours::transparentBlack);
        l->setMinimumHorizontalScale (1.0f);
        return l;
    }
};

inline KnobLookAndFeel& knobLAF() { static KnobLookAndFeel l; return l; }

// A matching vertical fader: a slim groove with a filled level + a capped thumb.
struct FaderLookAndFeel : public LookAndFeel_V4
{
    void drawLinearSlider (Graphics& g, int x, int y, int w, int h,
                           float sliderPos, float minSliderPos, float maxSliderPos,
                           const Slider::SliderStyle style, Slider& s) override
    {
        if (style != Slider::LinearVertical)
        { LookAndFeel_V4::drawLinearSlider (g, x, y, w, h, sliderPos, minSliderPos, maxSliderPos, style, s); return; }

        const float cx = x + w * 0.5f;
        const float top = (float) y, bot = (float) (y + h);
        const auto groove = Rectangle<float> (cx - 3.5f, top, 7.0f, (float) h);

        g.setColour (Colour (0xff262a31)); g.fillRoundedRectangle (groove, 3.5f);
        g.setColour (Colour (0xff3b5bdb)); g.fillRoundedRectangle (cx - 3.5f, sliderPos, 7.0f, bot - sliderPos, 3.5f);
        g.setColour (Colour (0xff5b6477)); g.drawRoundedRectangle (groove, 3.5f, 1.0f);

        const auto cap = Rectangle<float> (cx - (w - 2) * 0.5f, sliderPos - 8.0f, (float) (w - 2), 16.0f);
        g.setColour (Colour (0xff32363f)); g.fillRoundedRectangle (cap, 3.0f);
        g.setColour (Colour (0xff8fa0ff)); g.drawRoundedRectangle (cap, 3.0f, 1.4f);
        g.setColour (Colour (0xffcdd6ff)); g.fillRect (cap.getX() + 3.0f, cap.getCentreY() - 1.0f, cap.getWidth() - 6.0f, 2.0f);
    }
};

inline FaderLookAndFeel& faderLAF() { static FaderLookAndFeel l; return l; }

// A slider whose value box is type-over editable and that supports right-click
// copy / paste of its value onto any other knob (shared clipboard).
struct ValueSlider : public Slider
{
    static double& clipVal() { static double v = 0.0; return v; }
    static bool&   hasClip() { static bool b = false; return b; }

    void mouseDown (const MouseEvent& e) override
    {
        if (e.mods.isPopupMenu())
        {
            PopupMenu m;
            m.addItem (1, "Copy value");
            m.addItem (2, "Paste value", hasClip());
            m.showMenuAsync (PopupMenu::Options().withTargetComponent (this),
                [safe = Component::SafePointer<ValueSlider> (this)] (int r)
                {
                    if (safe == nullptr) return;
                    if (r == 1) { clipVal() = safe->getValue(); hasClip() = true; }
                    else if (r == 2 && hasClip()) safe->setValue (clipVal(), sendNotification);
                });
            return;
        }
        Slider::mouseDown (e);
    }
};

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
        pm.createBuiltInType<tewk::AIDrumKitPlugin>();
        engine.getDeviceManager().initialise (0, 2);

        edit = te::Edit::createSingleTrackEdit (engine);

        header.setText ("Music Producer", dontSendNotification);
        header.setFont (FontOptions (19.0f, Font::bold));
        addAndMakeVisible (header);
        status.setJustificationType (Justification::centredLeft);
        addAndMakeVisible (status);

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

        timeline.getEdit = [this] { return edit.get(); };
        timeline.onSeek  = [this] (double sec) { if (edit) edit->getTransport().setPosition (te::TimePosition::fromSeconds (sec)); };
        addAndMakeVisible (timeline);

        addAndMakeVisible (mixerViewport);
        mixerViewport.setViewedComponent (&mixerContainer, false);
        mixerViewport.setScrollBarsShown (false, true);   // columns fill height; scroll horizontally
        mixerContainer.addChildComponent (busDivider);    // separator before the bus channels

        auto button = [this] (TextButton& b, const String& t, std::function<void()> fn)
        { b.setButtonText (t); b.onClick = std::move (fn); addAndMakeVisible (b); };
        button (saveButton, "Save", [this] { saveProject(); });
        button (loadButton, "Load", [this] { loadProject(); });
        button (settingsButton, "Settings", [this] { showSettings(); });

        // VCR-style transport, placed above the timeline
        auto vcr = [this] (TextButton& b, const char* sym, std::function<void()> fn)
        { b.setButtonText (String (CharPointer_UTF8 (sym))); b.onClick = std::move (fn); addAndMakeVisible (b); };
        vcr (playButton,  "\xe2\x96\xb6", [this] { transportPlay(); });    // play
        vcr (pauseButton, "\xe2\x8f\xb8", [this] { transportPause(); });   // pause
        vcr (stopButton,  "\xe2\x8f\xb9", [this] { transportStop(); });    // stop

        buildInstrumentAndPhrase();
        setSize (1120, 940);
    }

    ~MainComponent() override
    {
        stopThread (5000);
        if (edit != nullptr) edit->getTransport().stop (false, false);
    }

    void resized() override
    {
        auto r = getLocalBounds().reduced (14);

        auto top = r.removeFromTop (30);
        header.setBounds (top.removeFromLeft (168));
        saveButton.setBounds (top.removeFromLeft (58)); top.removeFromLeft (4);
        loadButton.setBounds (top.removeFromLeft (58)); top.removeFromLeft (8);
        settingsButton.setBounds (top.removeFromLeft (80));
        status.setBounds (top.reduced (12, 4));
        r.removeFromTop (6);

        auto genRow = r.removeFromTop (28);
        auto fb = [&genRow] (Label& l, TextEditor& e, int lw, int ew)
        { l.setBounds (genRow.removeFromLeft (lw)); e.setBounds (genRow.removeFromLeft (ew)); genRow.removeFromLeft (8); };
        fb (keyLbl, keyEdit, 30, 44); fb (tempoLbl, tempoEdit, 44, 50);
        fb (barsLbl, barsEdit, 34, 44); fb (genreLbl, genreEdit, 44, 150);
        generateButton.setBounds (genRow.removeFromLeft (130));
        r.removeFromTop (8);

        auto tr = r.removeFromTop (28);                        // VCR transport above the timeline
        playButton.setBounds  (tr.removeFromLeft (42)); tr.removeFromLeft (4);
        pauseButton.setBounds (tr.removeFromLeft (42)); tr.removeFromLeft (4);
        stopButton.setBounds  (tr.removeFromLeft (42));
        r.removeFromTop (6);

        timeline.setBounds (r.removeFromTop (110));
        r.removeFromTop (8);

        mixerViewport.setBounds (r);
        layoutColumns();
    }

    void paint (Graphics& g) override { g.fillAll (getLookAndFeel().findColour (ResizableWindow::backgroundColourId)); }

private:
    const String serverBase { "http://127.0.0.1:7860" };

    struct TrackEntry
    {
        te::AudioTrack* track = nullptr;
        tewk::AISynthPlugin* synth = nullptr;
        tewk::AIDrumKitPlugin* drum = nullptr;
        tewk::AIPreampPlugin* preamp = nullptr;
        te::EqualiserPlugin* eq = nullptr;
        te::CompressorPlugin* comp = nullptr;
        te::VolumeAndPanPlugin* volPlugin = nullptr;   // track or master/bus fader/pan
        String role; int notes = 0;
        bool isMaster = false;                         // the Master bus channel
        bool isBus = false;                            // a user submix bus
    };

    //== timeline ==============================================================
    struct Timeline : public Component, private Timer
    {
        std::function<te::Edit*()> getEdit;
        std::function<void(double)> onSeek;
        Timeline() { startTimerHz (30); }
        ~Timeline() override { stopTimer(); }
        void timerCallback() override { repaint(); }

        void mouseDown (const MouseEvent& e) override
        {
            if (e.x <= labelW || lastBeats <= 0.0 || onSeek == nullptr) return;
            const double beat = (double) (e.x - labelW) / (double) jmax (1, getWidth() - labelW) * lastBeats;
            onSeek (lastBpm > 0.0 ? beat * 60.0 / lastBpm : 0.0);
        }

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
            lastBpm = bpm; lastBeats = totalBeats;

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

        static constexpr int labelW = 72;
        double lastBpm = 120.0, lastBeats = 8.0;
        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (Timeline)
    };

    //== a per-track channel column (all controls as knobs) ====================
    struct ChannelColumn : public Component
    {
        static constexpr int SH = 22, colW = 172, DPH = 82, DTH = 82;

        ChannelColumn (TrackEntry e, std::function<void()> onRegen) : entry (e)
        {
            // editable channel name
            name.setText (e.isMaster ? "Master" : e.role, dontSendNotification);
            name.setJustificationType (Justification::centred);
            name.setFont (FontOptions (15.0f, Font::bold));
            if (! e.isMaster)
            {
                name.setEditable (false, true, false);   // double-click to rename
                name.onTextChange = [this] { if (entry.track) entry.track->setName (name.getText()); };
            }
            addAndMakeVisible (name);

            addChildComponent (fxView);                  // scrolling effects rack (above the pinned footer)
            fxView.setViewedComponent (&fxContent, false);
            fxView.setScrollBarsShown (true, false);
            fxView.setVisible (true);

            const bool isTrack = (! e.isMaster && ! e.isBus);

            if (isTrack)
            { regen.setButtonText ("Regen"); regen.onClick = onRegen; addAndMakeVisible (regen); }

            // Instrument (tracks only)
            if (e.synth != nullptr || e.drum != nullptr)
            {
                hasInstr = true;
                setupDisclosure (instrDisc, instrOpen);
                if (e.synth != nullptr)
                {
                    for (int i = 0; i < 4; ++i) templateBox.addItem (tewk::AISynthPlugin::templateName (i), i + 1);
                    templateBox.setSelectedId (e.synth->getTemplateIndex() + 1, dontSendNotification);
                    templateBox.onChange = [this] { entry.synth->selectTemplate ((tewk::InstrTemplate) (templateBox.getSelectedId() - 1)); loadInstrumentKnobs(); };
                    fxContent.addAndMakeVisible (templateBox);
                    const char* mn[6] = { "Tone", "Shape", "Attack", "Release", "Space", "Move" };
                    te::AutomatableParameter::Ptr mp[6] = { e.synth->tone, e.synth->shape, e.synth->attack, e.synth->release, e.synth->space, e.synth->move };
                    nInstr = 6;
                    for (int i = 0; i < nInstr; ++i) { instrParam[i] = mp[i]; bindParamKnob (i, mn[i]); }
                }
                else
                {
                    const char* mn[2] = { "Tone", "Decay" };
                    te::AutomatableParameter::Ptr mp[2] = { e.drum->tone, e.drum->decay };
                    nInstr = 2;
                    for (int i = 0; i < nInstr; ++i) { instrParam[i] = mp[i]; bindParamKnob (i, mn[i]); }
                }
            }

            // Preamp / EQ / Compressor — present on tracks, buses AND the master.
            if (e.preamp != nullptr)
            {
                setupDisclosure (preampDisc, preampOpen);
                preampOn.onClick = [this] { if (entry.preamp) entry.preamp->setEnabled (preampOn.getToggleState()); };
                preampOn.setToggleState (e.preamp->isEnabled(), dontSendNotification);
                fxContent.addAndMakeVisible (preampOn);
                addGroupKnob (preampKnob[0], preampLbl[0], "Drive",  0, 1, 0.001, [this] { if (entry.preamp) entry.preamp->drive->setParameter  ((float) preampKnob[0].getValue(), sendNotification); });
                addGroupKnob (preampKnob[1], preampLbl[1], "Output", 0, 1, 0.001, [this] { if (entry.preamp) entry.preamp->output->setParameter ((float) preampKnob[1].getValue(), sendNotification); });
                preampKnob[0].setValue (e.preamp->drive->getCurrentValue(), dontSendNotification);
                preampKnob[1].setValue (e.preamp->output->getCurrentValue(), dontSendNotification);
                if (e.synth != nullptr)
                {
                    addGroupKnob (levelKnob, levelLbl, "Level", 0, 1, 0.001, [this] { entry.synth->level->setParameter ((float) levelKnob.getValue(), sendNotification); });
                    levelKnob.setValue (e.synth->level->getCurrentValue(), dontSendNotification);
                }
            }
            if (e.eq != nullptr)
            {
                setupDisclosure (eqDisc, eqOpen);
                eqOn.onClick = [this] { if (entry.eq) entry.eq->setEnabled (eqOn.getToggleState()); };
                eqOn.setToggleState (e.eq->isEnabled(), dontSendNotification);
                fxContent.addAndMakeVisible (eqOn);
                addGroupKnob (eqKnob[0], eqLbl[0], "Low",  -20, 20, 0.1, [this] { if (entry.eq) entry.eq->setLowGain  ((float) eqKnob[0].getValue()); });
                addGroupKnob (eqKnob[1], eqLbl[1], "Mid",  -20, 20, 0.1, [this] { if (entry.eq) entry.eq->setMidGain1 ((float) eqKnob[1].getValue()); });
                addGroupKnob (eqKnob[2], eqLbl[2], "High", -20, 20, 0.1, [this] { if (entry.eq) entry.eq->setHighGain ((float) eqKnob[2].getValue()); });
                eqKnob[0].setValue (e.eq->loGain->getCurrentValue(), dontSendNotification); eqKnob[1].setValue (e.eq->midGain1->getCurrentValue(), dontSendNotification); eqKnob[2].setValue (e.eq->hiGain->getCurrentValue(), dontSendNotification);
            }
            if (e.comp != nullptr)
            {
                setupDisclosure (compDisc, compOpen);
                compOn.onClick = [this] { if (entry.comp) entry.comp->setEnabled (compOn.getToggleState()); };
                compOn.setToggleState (e.comp->isEnabled(), dontSendNotification);
                fxContent.addAndMakeVisible (compOn);
                addGroupKnob (compKnob[0], compLbl[0], "Thresh", -40, 0, 0.5, [this] { applyComp(); });
                addGroupKnob (compKnob[1], compLbl[1], "Ratio",   1, 20, 0.1, [this] { applyComp(); });
                addGroupKnob (compKnob[2], compLbl[2], "Attack", 0.3, 200, 0.5, [this] { applyComp(); });
                addGroupKnob (compKnob[3], compLbl[3], "Release", 10, 300, 1, [this] { applyComp(); });
                compKnob[0].setValue (Decibels::gainToDecibels (e.comp->thresholdGain.getCurrentValue()), dontSendNotification);
                compKnob[1].setValue (1.0 / jmax (0.05f, e.comp->ratio.getCurrentValue()), dontSendNotification);
                compKnob[2].setValue (e.comp->attackMs.getCurrentValue(), dontSendNotification);
                compKnob[3].setValue (e.comp->releaseMs.getCurrentValue(), dontSendNotification);
            }

            // footer: Mute / Solo (tracks + buses)
            if (! e.isMaster)
            {
                mute.setButtonText ("M"); mute.setClickingTogglesState (true);
                mute.setToggleState (e.track && e.track->isMuted (false), dontSendNotification);
                mute.onClick = [this] { if (entry.track) entry.track->setMute (mute.getToggleState()); };
                solo.setButtonText ("S"); solo.setClickingTogglesState (true);
                solo.setToggleState (e.track && e.track->isSolo (false), dontSendNotification);
                solo.onClick = [this] { if (entry.track) entry.track->setSolo (solo.getToggleState()); };
                addAndMakeVisible (mute); addAndMakeVisible (solo);
            }

            // footer: Input / Output (tracks only; outBox filled later via setOutputs)
            if (isTrack)
            {
                inLbl.setText ("In", dontSendNotification);   inLbl.setFont (FontOptions (11.0f));  addAndMakeVisible (inLbl);
                outLbl.setText ("Out", dontSendNotification); outLbl.setFont (FontOptions (11.0f)); addAndMakeVisible (outLbl);
                inBox.addItem ("None", 1); inBox.setSelectedId (1, dontSendNotification); addAndMakeVisible (inBox);
                addAndMakeVisible (outBox);
            }

            // footer: Channel label + Pan + Volume fader (all channel types)
            chanLbl.setText (e.isMaster ? "Master" : (e.isBus ? "Bus" : "Channel"), dontSendNotification); section (chanLbl);
            addKnob (panKnob, panLbl, "Pan", -1, 1, 0.01, [this] { if (entry.volPlugin) entry.volPlugin->setPan ((float) panKnob.getValue()); });
            volLbl.setText ("Vol", dontSendNotification); volLbl.setJustificationType (Justification::centred); volLbl.setFont (FontOptions (11.0f)); addAndMakeVisible (volLbl);
            volFader.setSliderStyle (Slider::LinearVertical);
            volFader.setRange (-48.0, 6.0, 0.1);
            volFader.setTextBoxStyle (Slider::TextBoxBelow, false, 60, 14);
            volFader.setColour (Slider::textBoxOutlineColourId, Colours::transparentBlack);
            volFader.setLookAndFeel (&faderLAF());
            volFader.onValueChange = [this] { if (entry.volPlugin) entry.volPlugin->setVolumeDb ((float) volFader.getValue()); };
            addAndMakeVisible (volFader);
            if (e.volPlugin) { volFader.setValue (e.volPlugin->getVolumeDb(), dontSendNotification); panKnob.setValue (e.volPlugin->getPan(), dontSendNotification); }

            if (e.isMaster)
            {
                renderBtn.setButtonText ("Render WAV");
                renderBtn.onClick = [this] { if (onRender) onRender(); };
                addAndMakeVisible (renderBtn);
            }

            updateVisibility();
        }

        // Populate the Output routing menu (tracks only): Master + buses.
        void setOutputs (const StringArray& names, int currentIndex, std::function<void(int)> cb)
        {
            outBox.clear (dontSendNotification);
            for (int i = 0; i < names.size(); ++i) outBox.addItem (names[i], i + 1);
            outBox.setSelectedId (currentIndex + 1, dontSendNotification);
            outBox.onChange = [this, cb] { if (cb) cb (outBox.getSelectedId() - 1); };
        }

        std::function<void()> onRender;   // master only: render the mix

        void resized() override
        {
            auto r = getLocalBounds().reduced (6, 4);
            name.setBounds (r.removeFromTop (24));
            if (! entry.isMaster)
                regen.setBounds (r.removeFromTop (22).reduced (1, 1));

            // pinned footer at the bottom; effects scroll in between
            const int footerH = entry.isMaster ? 170 : 244;
            auto footer = r.removeFromBottom (footerH);
            footerTop = footer.getY();
            layoutFooter (footer);

            fxView.setBounds (r.reduced (0, 2));
            layoutFx();
        }

        void paint (Graphics& g) override
        {
            g.setColour (Colour (0xff2a2a2a)); g.fillRoundedRectangle (getLocalBounds().toFloat().reduced (2), 4.0f);
            g.setColour (Colour (0xff444444)); g.drawRoundedRectangle (getLocalBounds().toFloat().reduced (2), 4.0f, 1.0f);
            g.setColour (Colour (0xff3c4250));                      // divider above the pinned footer
            g.drawHorizontalLine (footerTop, 4.0f, (float) getWidth() - 4.0f);
        }

    private:
        void section (Label& l) { l.setJustificationType (Justification::centredLeft); l.setFont (FontOptions (12.0f, Font::bold)); l.setColour (Label::textColourId, Colour (0xff8fa0ff)); addAndMakeVisible (l); }

        void layoutFooter (Rectangle<int> footer)
        {
            footer.reduce (2, 2);
            chanLbl.setBounds (footer.removeFromTop (16));
            if (entry.isMaster)
            {
                renderBtn.setBounds (footer.removeFromTop (26).reduced (2, 1));
                footer.removeFromTop (6);
            }
            if (! entry.isMaster)
            {
                auto ms = footer.removeFromTop (24);
                mute.setBounds (ms.removeFromLeft (ms.getWidth() / 2 - 2)); ms.removeFromLeft (4); solo.setBounds (ms);
                auto inR = footer.removeFromTop (22); inLbl.setBounds (inR.removeFromLeft (28)); inBox.setBounds (inR.reduced (1, 1));
                auto outR = footer.removeFromTop (22); outLbl.setBounds (outR.removeFromLeft (28)); outBox.setBounds (outR.reduced (1, 1));
                footer.removeFromTop (4);
            }
            auto panCol = footer.removeFromLeft (64);
            panLbl.setBounds (panCol.removeFromTop (12));
            panKnob.setBounds (panCol.withSizeKeepingCentre (jmin (54, panCol.getWidth()), jmin (54, panCol.getHeight())));
            volLbl.setBounds (footer.removeFromTop (12));
            volFader.setBounds (footer.withSizeKeepingCentre (46, footer.getHeight()));
        }

        // lay the effect sections into fxContent (scrolling area)
        void layoutFx()
        {
            const int w = jmax (40, fxView.getWidth() - (fxView.isVerticalScrollBarShown() ? 12 : 2));
            Rectangle<int> r (0, 0, w, 4000);

            if (hasInstr)
            {
                headerRow (r, instrDisc, nullptr);
                if (instrOpen)
                {
                    if (entry.synth) templateBox.setBounds (r.removeFromTop (24).reduced (2, 1));
                    if (entry.synth)
                    {
                        auto row1 = r.removeFromTop (DPH); const int half = row1.getWidth() / 2;
                        diagPair (row1.removeFromLeft (half), instrKnob[0], instrLbl_[0], instrKnob[1], instrLbl_[1]);
                        diagPair (row1,                       instrKnob[2], instrLbl_[2], instrKnob[3], instrLbl_[3]);
                        auto row2 = r.removeFromTop (DPH);
                        diagPair (row2.removeFromLeft (half), instrKnob[4], instrLbl_[4], instrKnob[5], instrLbl_[5]);
                    }
                    else
                        diagPair (r.removeFromTop (DPH).removeFromLeft (w / 2), instrKnob[0], instrLbl_[0], instrKnob[1], instrLbl_[1]);
                }
            }
            if (entry.preamp != nullptr)
            {
                headerRow (r, preampDisc, &preampOn);
                if (preampOpen)
                {
                    auto area = r.removeFromTop (DTH);
                    if (entry.synth) { ValueSlider* k[3] = { &preampKnob[0], &preampKnob[1], &levelKnob }; Label* l[3] = { &preampLbl[0], &preampLbl[1], &levelLbl }; diagN (area, k, l, 3); }
                    else diagPair (area, preampKnob[0], preampLbl[0], preampKnob[1], preampLbl[1]);
                }
            }
            if (entry.eq != nullptr)
            {
                headerRow (r, eqDisc, &eqOn);
                if (eqOpen) { auto area = r.removeFromTop (DTH); ValueSlider* k[3] = { &eqKnob[0], &eqKnob[1], &eqKnob[2] }; Label* l[3] = { &eqLbl[0], &eqLbl[1], &eqLbl[2] }; diagN (area, k, l, 3); }
            }
            if (entry.comp != nullptr)
            {
                headerRow (r, compDisc, &compOn);
                if (compOpen)
                {
                    auto row = r.removeFromTop (DPH); const int half = row.getWidth() / 2;
                    diagPair (row.removeFromLeft (half), compKnob[0], compLbl[0], compKnob[1], compLbl[1]);
                    diagPair (row,                       compKnob[2], compLbl[2], compKnob[3], compLbl[3]);
                }
            }
            fxContent.setSize (w, r.getY() + 4);
        }

        void setupDisclosure (TextButton& b, bool& openFlag)
        {
            b.setColour (TextButton::buttonColourId, Colours::transparentBlack);
            b.setColour (TextButton::buttonOnColourId, Colours::transparentBlack);
            b.setColour (TextButton::textColourOffId, Colour (0xff8fa0ff));
            b.setColour (TextButton::textColourOnId,  Colour (0xff8fa0ff));
            b.onClick = [this, &openFlag] { openFlag = ! openFlag; updateVisibility(); layoutFx(); };
            fxContent.addAndMakeVisible (b);
        }

        void headerRow (Rectangle<int>& r, TextButton& disc, ToggleButton* enable)
        {
            auto row = r.removeFromTop (SH);
            if (enable != nullptr) enable->setBounds (row.removeFromRight (24));
            disc.setBounds (row);
        }

        void updateVisibility()
        {
            auto arrow = [] (bool open) { return open ? String (CharPointer_UTF8 ("\xe2\x96\xbe  ")) : String (CharPointer_UTF8 ("\xe2\x96\xb8  ")); };
            if (hasInstr)
            {
                instrDisc.setButtonText (arrow (instrOpen) + (entry.drum ? "Drum Kit" : "Instrument"));
                if (entry.synth) templateBox.setVisible (instrOpen);
                for (int i = 0; i < nInstr; ++i) { instrKnob[i].setVisible (instrOpen); instrLbl_[i].setVisible (instrOpen); }
            }
            if (entry.preamp != nullptr)
            {
                preampDisc.setButtonText (arrow (preampOpen) + "Preamp");
                for (int i = 0; i < 2; ++i) { preampKnob[i].setVisible (preampOpen); preampLbl[i].setVisible (preampOpen); }
                if (entry.synth) { levelKnob.setVisible (preampOpen); levelLbl.setVisible (preampOpen); }
            }
            if (entry.eq != nullptr)
            {
                eqDisc.setButtonText (arrow (eqOpen) + "EQ");
                for (int i = 0; i < 3; ++i) { eqKnob[i].setVisible (eqOpen); eqLbl[i].setVisible (eqOpen); }
            }
            if (entry.comp != nullptr)
            {
                compDisc.setButtonText (arrow (compOpen) + "Comp");
                for (int i = 0; i < 4; ++i) { compKnob[i].setVisible (compOpen); compLbl[i].setVisible (compOpen); }
            }
        }

        void addKnob (ValueSlider& s, Label& l, const String& nm, double lo, double hi, double step, std::function<void()> cb)
        {
            l.setText (nm, dontSendNotification); l.setJustificationType (Justification::centred); l.setFont (FontOptions (11.0f)); addAndMakeVisible (l);
            s.setSliderStyle (Slider::RotaryVerticalDrag);
            s.setRange (lo, hi, step);
            s.setNumDecimalPlacesToDisplay (decimalsFor (hi - lo));
            s.setTextBoxStyle (Slider::TextBoxBelow, false, 64, 14);
            s.setColour (Slider::textBoxOutlineColourId, Colours::transparentBlack);
            s.setLookAndFeel (&knobLAF());
            s.onValueChange = std::move (cb);
            addAndMakeVisible (s);
        }

        void addGroupKnob (ValueSlider& s, Label& l, const String& nm, double lo, double hi, double step, std::function<void()> cb)
        {
            l.setText (nm, dontSendNotification); l.setJustificationType (Justification::centred); l.setFont (FontOptions (10.0f)); l.setColour (Label::textColourId, Colour (0xffaab2c8)); fxContent.addAndMakeVisible (l);
            s.setSliderStyle (Slider::RotaryVerticalDrag);
            s.setRange (lo, hi, step);
            s.setNumDecimalPlacesToDisplay (decimalsFor (hi - lo));
            s.setTextBoxStyle (Slider::TextBoxBelow, false, 52, 13);
            s.setColour (Slider::textBoxOutlineColourId, Colours::transparentBlack);
            s.setLookAndFeel (&knobLAF());
            s.onValueChange = std::move (cb);
            fxContent.addAndMakeVisible (s);
        }

        static int decimalsFor (double span) { return span <= 2.0 ? 2 : (span <= 30.0 ? 1 : 0); }

        void bindParamKnob (int i, const String& nm)
        {
            addGroupKnob (instrKnob[i], instrLbl_[i], nm, 0, 1, 0.001, [this, i] { if (instrParam[i] != nullptr) instrParam[i]->setParameter ((float) instrKnob[i].getValue(), sendNotification); });
            if (instrParam[i] != nullptr) instrKnob[i].setValue (instrParam[i]->getCurrentValue(), dontSendNotification);
        }

        void loadInstrumentKnobs()
        {
            for (int i = 0; i < nInstr; ++i) if (instrParam[i] != nullptr) instrKnob[i].setValue (instrParam[i]->getCurrentValue(), dontSendNotification);
            if (entry.synth) levelKnob.setValue (entry.synth->level->getCurrentValue(), dontSendNotification);
        }

        void applyComp()
        {
            if (entry.comp == nullptr) return;
            entry.comp->thresholdGain.setParameter (jlimit (0.01f, 1.0f, Decibels::decibelsToGain ((float) compKnob[0].getValue())), sendNotification);
            entry.comp->ratio.setParameter (jlimit (0.0f, 0.95f, 1.0f / jmax (1.0f, (float) compKnob[1].getValue())), sendNotification);
            entry.comp->attackMs.setParameter ((float) compKnob[2].getValue(), sendNotification);
            entry.comp->releaseMs.setParameter ((float) compKnob[3].getValue(), sendNotification);
        }

        void diagN (Rectangle<int> r, ValueSlider** k, Label** l, int count)
        {
            const int lblH = 11, valH = 13, stackExtra = lblH + valH;
            int ks = (count <= 2) ? jmin (r.getWidth() * 50 / 100, r.getHeight() - stackExtra - 16)
                                  : jmin (r.getWidth() * 36 / 100, r.getHeight() - stackExtra - 16);
            ks = jmax (20, ks);
            const int stack = ks + stackExtra, boxW = ks + 18;
            for (int i = 0; i < count; ++i)
            {
                const double t = (count <= 1) ? 0.0 : (double) i / (count - 1);
                const int cx = r.getX() + roundToInt (t * (r.getWidth() - ks)) + ks / 2;
                const int yTop = r.getY() + roundToInt (t * (r.getHeight() - stack));
                const int bx = cx - boxW / 2;
                l[i]->setBounds (bx, yTop, boxW, lblH);
                k[i]->setBounds (bx, yTop + lblH, boxW, ks + valH);
            }
        }
        void diagPair (Rectangle<int> r, ValueSlider& a, Label& al, ValueSlider& b, Label& bl)
        { ValueSlider* k[2] = { &a, &b }; Label* l[2] = { &al, &bl }; diagN (r, k, l, 2); }

        TrackEntry entry;
        int footerTop = 0;
        bool hasInstr = false;
        Label name, chanLbl;
        Viewport fxView; Component fxContent;
        TextButton mute, solo, regen, renderBtn;
        Label inLbl, outLbl; ComboBox inBox, outBox;
        TextButton instrDisc, preampDisc, eqDisc, compDisc;
        bool instrOpen = true, preampOpen = false, eqOpen = false, compOpen = false;
        ComboBox templateBox;
        te::AutomatableParameter::Ptr instrParam[6];
        ValueSlider instrKnob[6]; Label instrLbl_[6]; int nInstr = 0;
        ValueSlider levelKnob; Label levelLbl;
        ToggleButton preampOn; ValueSlider preampKnob[2]; Label preampLbl[2];
        ToggleButton eqOn;     ValueSlider eqKnob[3];     Label eqLbl[3];
        ToggleButton compOn;   ValueSlider compKnob[4];   Label compLbl[4];
        ValueSlider volFader, panKnob; Label volLbl, panLbl;
        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ChannelColumn)
    };

    //== columns ===============================================================
    template <typename T>
    T* ensureMasterPlugin (te::PluginList& mpl, const char* type)
    {
        if (auto* existing = mpl.findFirstPluginOfType<T>()) return existing;
        if (auto p = edit->getPluginCache().createNewPlugin (type, {}))
        { auto* tp = dynamic_cast<T*> (p.get()); mpl.insertPlugin (p, -1, nullptr); if (tp) tp->setEnabled (false); return tp; }
        return nullptr;
    }

    int outputIndexOf (te::AudioTrack* track)
    {
        if (track != nullptr)
            if (auto* dest = track->getOutput().getDestinationTrack())
                for (int i = 0; i < (int) buses.size(); ++i) if (buses[(size_t) i].track == dest) return i + 1;
        return 0;   // Master / default
    }

    void routeTrackOutput (te::AudioTrack* track, int idx)
    {
        if (track == nullptr) return;
        if (idx <= 0) track->getOutput().setOutputToDefaultDevice (false);
        else if (idx - 1 < (int) buses.size()) track->getOutput().setOutputToTrack (buses[(size_t) (idx - 1)].track);
    }

    void addBus()
    {
        auto* track = getOrInsertAudioTrackAt (te::getAudioTracks (*edit).size());
        TrackEntry b; b.isBus = true; b.track = track;
        b.role = "Bus " + String ((int) buses.size() + 1);
        track->setName (b.role);
        addChannelStrip (b, 0);
        b.volPlugin = track->getVolumePlugin();
        track->getOutput().setOutputToDefaultDevice (false);   // bus -> master
        buses.push_back (b);
        rebuildColumns();
    }

    void rebuildColumns()
    {
        columns.clear();

        StringArray outNames; outNames.add ("Master");
        for (auto& b : buses) outNames.add (b.role);

        for (int i = 0; i < (int) entries.size(); ++i)         // track channels (left)
        {
            auto* col = new ChannelColumn (entries[(size_t) i], [this, i] { regenerateTrack (i); });
            auto* track = entries[(size_t) i].track;
            col->setOutputs (outNames, outputIndexOf (track), [this, track] (int idx) { routeTrackOutput (track, idx); });
            mixerContainer.addAndMakeVisible (col);
            columns.add (col);
        }
        for (auto& b : buses)                                  // submix buses (right group)
        {
            auto* col = new ChannelColumn (b, [] {});
            mixerContainer.addAndMakeVisible (col);
            columns.add (col);
        }
        // Master bus with its own FX rack (on the edit master plugin list)
        TrackEntry m; m.isMaster = true; m.role = "Master";
        if (auto mv = edit->getMasterVolumePlugin()) m.volPlugin = mv.get();
        auto& mpl = edit->getMasterPluginList();
        m.preamp = ensureMasterPlugin<tewk::AIPreampPlugin> (mpl, tewk::AIPreampPlugin::xmlTypeName);
        m.eq     = ensureMasterPlugin<te::EqualiserPlugin>  (mpl, te::EqualiserPlugin::xmlTypeName);
        m.comp   = ensureMasterPlugin<te::CompressorPlugin> (mpl, te::CompressorPlugin::xmlTypeName);
        auto* mc = new ChannelColumn (m, [] {});
        mc->onRender = [this] { renderWav(); };
        mixerContainer.addAndMakeVisible (mc);
        columns.add (mc);

        layoutColumns();
        refreshStatus();
    }

    void layoutColumns()
    {
        const int w = ChannelColumn::colW;
        const int h = jmax (260, mixerViewport.getHeight() - 2);   // columns fill the mixer height
        const int nTracks = jmin ((int) entries.size(), columns.size());
        const int nBuses  = jmax (0, columns.size() - nTracks);
        const int gap = 30;

        int x = 0;
        for (int i = 0; i < nTracks; ++i) { columns[i]->setBounds (x, 0, w, h); x += w; }

        const int busesW = nBuses * w;
        const int busStart = jmax (x + gap, mixerViewport.getWidth() - busesW - 2);   // right-align buses
        for (int j = 0; j < nBuses; ++j) columns[nTracks + j]->setBounds (busStart + j * w, 0, w, h);

        busDivider.setVisible (nBuses > 0 && nTracks > 0);
        busDivider.setBounds (busStart - gap / 2 - 1, 4, 2, h - 8);

        mixerContainer.setSize (jmax (mixerViewport.getWidth(), busStart + busesW), h);
    }

    void refreshStatus()
    {
        auto* dev = engine.getDeviceManager().deviceManager.getCurrentAudioDevice();
        String s;
        s << "Engine up    |    Tracks: " << (int) entries.size()
          << "    |    Audio out: " << (dev != nullptr ? dev->getName() : String ("(none)"));
        status.setText (s, dontSendNotification);
    }

    //== edit building =========================================================
    te::AudioTrack* getOrInsertAudioTrackAt (int index) { edit->ensureNumberOfAudioTracks (index + 1); return te::getAudioTracks (*edit)[index]; }

    template <typename T>
    T* insertPluginOfType (te::AudioTrack* track, const char* type, int index)
    {
        if (auto p = edit->getPluginCache().createNewPlugin (type, {}))
        { auto* tp = dynamic_cast<T*> (p.get()); track->pluginList.insertPlugin (p, index, nullptr); return tp; }
        return nullptr;
    }

    void addChannelStrip (TrackEntry& e, int baseIndex)
    {
        e.preamp = insertPluginOfType<tewk::AIPreampPlugin> (e.track, tewk::AIPreampPlugin::xmlTypeName, baseIndex);
        e.eq     = insertPluginOfType<te::EqualiserPlugin>  (e.track, te::EqualiserPlugin::xmlTypeName,  baseIndex + 1);
        e.comp   = insertPluginOfType<te::CompressorPlugin> (e.track, te::CompressorPlugin::xmlTypeName, baseIndex + 2);
        if (e.preamp) e.preamp->setEnabled (false);
        if (e.eq)     e.eq->setEnabled (false);
        if (e.comp)   e.comp->setEnabled (false);
    }

    int addNotes (te::AudioTrack* track, const String& name, const var& notes, double minLenBeats)
    {
        auto* arr = notes.getArray();
        if (arr == nullptr || arr->isEmpty()) return 0;
        double maxEnd = minLenBeats;
        for (auto& nv : *arr) if (auto* a = nv.getArray()) if (a->size() >= 3) maxEnd = jmax (maxEnd, (double) (*a)[1] + (double) (*a)[2]);
        const auto range = edit->tempoSequence.toTime ({ te::BeatPosition::fromBeats (0.0), te::BeatPosition::fromBeats (maxEnd) });
        int count = 0;
        if (auto* clip = dynamic_cast<te::MidiClip*> (track->insertNewClip (te::TrackItem::Type::midi, name, range, nullptr)))
        {
            auto& seq = clip->getSequence(); auto* um = &edit->getUndoManager();
            for (auto& nv : *arr) if (auto* a = nv.getArray()) if (a->size() >= 3)
            { seq.addNote ((int) (*a)[0], te::BeatPosition::fromBeats ((double) (*a)[1]), te::BeatDuration::fromBeats (jmax (0.05, (double) (*a)[2])), 92, 0, um); ++count; }
        }
        return count;
    }

    static tewk::InstrTemplate templateForRole (const String& role)
    {
        if (role.equalsIgnoreCase ("Bass"))   return tewk::InstrTemplate::bass;
        if (role.equalsIgnoreCase ("Melody")) return tewk::InstrTemplate::lead;
        if (role.equalsIgnoreCase ("Chords")) return tewk::InstrTemplate::pad;
        return tewk::InstrTemplate::pluck;
    }

    void buildTrack (int idx, const String& role, const var& notes)
    {
        auto* track = getOrInsertAudioTrackAt (idx);
        track->setName (role);
        TrackEntry e; e.track = track;
        if (role.equalsIgnoreCase ("Drums"))
            e.drum = insertPluginOfType<tewk::AIDrumKitPlugin> (track, tewk::AIDrumKitPlugin::xmlTypeName, 0);
        else
        {
            e.synth = insertPluginOfType<tewk::AISynthPlugin> (track, tewk::AISynthPlugin::xmlTypeName, 0);
            if (e.synth) e.synth->selectTemplate (templateForRole (role));
        }
        e.role = role;
        e.notes = addNotes (track, role, notes, genBars * 4.0);
        addChannelStrip (e, 1);
        e.volPlugin = track->getVolumePlugin();
        entries.push_back (e);
    }

    void buildInstrumentAndPhrase()
    {
        entries.clear();
        buses.clear();
        genBars = 2;
        Array<var> arr;
        auto add = [&] (int p, double s, double l) { arr.add (var (Array<var> { p, s, l })); };
        for (double bar = 0.0; bar < 8.0; bar += 4.0) { add (48, bar, 4.0); add (51, bar, 4.0); add (55, bar, 4.0); }
        const int a[] = { 60, 63, 67, 70, 67, 63, 67, 70 };
        for (int i = 0; i < 8; ++i) add (a[i], (double) i, 0.9);
        buildTrack (0, "Chords", var (arr));
        rebuildColumns();
    }

    //== generation ============================================================
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
        status.setText ("Generating arrangement...", dontSendNotification);
        const auto url = serverBase + "/api/generate-arrangement";
        const auto payload = makeBody ({ "chords", "bass", "melody", "drums" }, "midi", genSeed);
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
        { status.setText ("Generation failed (backend on " + serverBase + " not reachable).", dontSendNotification); generateButton.setEnabled (true); return; }

        stopPlayback();
        columns.clear();                         // drop old columns before the edit goes away
        const double tempo = (double) resp.getProperty ("tempo", 120.0);
        genBars = (int) resp.getProperty ("bars", 8);
        edit = te::Edit::createSingleTrackEdit (engine);
        if (auto* t0 = edit->tempoSequence.getTempo (0)) t0->setBpm (tempo);

        entries.clear();
        buses.clear();
        StringArray built;
        if (auto* tracks = resp.getProperty ("tracks", var()).getArray())
            for (auto& tv : *tracks)
            { const String role = tv.getProperty ("track", "").toString(); buildTrack ((int) entries.size(), role, tv.getProperty ("notes", var())); built.add (role); }

        rebuildColumns();
        edit->getTransport().ensureContextAllocated();   // ready to play, but don't auto-start
        generateButton.setEnabled (true);
        status.setText ("Generated " + String ((int) entries.size()) + " tracks: " + built.joinIntoString (", ") + " @ " + String (tempo, 0) + " bpm. Press Play.", dontSendNotification);
    }

    //== regenerate one track ==================================================
    void clearTrackClips (te::AudioTrack* track) { juce::Array<te::Clip*> clips (track->getClips()); for (auto* c : clips) c->removeFromParent(); }

    void regenerateTrack (int i)
    {
        if (i < 0 || i >= (int) entries.size()) return;
        auto* track = entries[(size_t) i].track;
        const String role = entries[(size_t) i].role;
        const int seed = Random::getSystemRandom().nextInt (1000000);
        status.setText ("Regenerating " + role + "...", dontSendNotification);
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
            MessageManager::callAsync ([safe, resp, track, role] { if (safe != nullptr) safe->applyRegen (track, role, resp); });
        });
    }

    void applyRegen (te::AudioTrack* track, const String& role, const var& resp)
    {
        if (! resp.isObject()) { status.setText ("Regen failed.", dontSendNotification); return; }
        var notes;
        if (auto* tracks = resp.getProperty ("tracks", var()).getArray()) if (! tracks->isEmpty()) notes = (*tracks)[0].getProperty ("notes", var());
        clearTrackClips (track);
        const int n = addNotes (track, role, notes, genBars * 4.0);
        status.setText ("Regenerated " + role + " (" + String (n) + " notes).", dontSendNotification);
    }

    //== transport / render / save / load ======================================
    void transportPlay()  { auto& t = edit->getTransport(); t.ensureContextAllocated(); t.play (false); }      // from current position
    void transportPause() { if (edit) edit->getTransport().stop (false, false); }                              // hold position
    void transportStop()  { if (edit) { auto& t = edit->getTransport(); t.stop (false, false); t.setPosition (te::TimePosition()); } }
    void stopPlayback()   { if (edit) edit->getTransport().stop (false, false); }

    void showSettings()
    {
        PopupMenu m;
        m.addItem (1, "Add Bus");
        m.addItem (2, "Scan AU instruments");
        m.showMenuAsync (PopupMenu::Options().withTargetComponent (&settingsButton),
            [this] (int r) { if (r == 1) addBus(); else if (r == 2) startScan(); });
    }

    void renderWav()
    {
        stopPlayback();
        auto out = File::getSpecialLocation (File::userDesktopDirectory).getChildFile ("Music Producer.wav");
        const bool ok = te::Renderer::renderToFile (*edit, out, false);
        status.setText (ok ? ("Rendered: " + out.getFullPathName()) : "Render failed.", dontSendNotification);
    }

    void saveProject()
    {
        auto fc = std::make_shared<FileChooser> ("Save project",
                      File::getSpecialLocation (File::userDocumentsDirectory).getChildFile ("song.tracktionedit"), "*.tracktionedit");
        fc->launchAsync (FileBrowserComponent::saveMode | FileBrowserComponent::warnAboutOverwriting,
            [this, fc] (const FileChooser& c) { auto f = c.getResult(); if (f == File()) return;
                const bool ok = te::EditFileOperations (*edit).writeToFile (f, false);
                status.setText (ok ? ("Saved: " + f.getFullPathName()) : "Save failed.", dontSendNotification); });
    }

    void loadProject()
    {
        auto fc = std::make_shared<FileChooser> ("Load project", File::getSpecialLocation (File::userDocumentsDirectory), "*.tracktionedit");
        fc->launchAsync (FileBrowserComponent::openMode | FileBrowserComponent::canSelectFiles,
            [this, fc] (const FileChooser& c) { auto f = c.getResult(); if (f == File() || ! f.existsAsFile()) return;
                stopPlayback(); columns.clear();
                if (auto loaded = te::loadEditFromFile (engine, f)) { edit = std::move (loaded); rebuildEntriesFromEdit(); status.setText ("Loaded: " + f.getFullPathName(), dontSendNotification); }
                else status.setText ("Load failed.", dontSendNotification); });
    }

    void rebuildEntriesFromEdit()
    {
        entries.clear();
        buses.clear();
        for (auto* track : te::getAudioTracks (*edit))
        {
            TrackEntry e; e.track = track;
            e.synth  = track->pluginList.findFirstPluginOfType<tewk::AISynthPlugin>();
            e.drum   = track->pluginList.findFirstPluginOfType<tewk::AIDrumKitPlugin>();
            e.preamp = track->pluginList.findFirstPluginOfType<tewk::AIPreampPlugin>();
            e.eq     = track->pluginList.findFirstPluginOfType<te::EqualiserPlugin>();
            e.comp   = track->pluginList.findFirstPluginOfType<te::CompressorPlugin>();
            e.volPlugin = track->getVolumePlugin();
            e.role   = track->getName();
            int n = 0; bool midi = false;
            for (auto* clip : track->getClips()) if (auto* mc = dynamic_cast<te::MidiClip*> (clip)) { midi = true; n += mc->getSequence().getNumNotes(); }
            e.notes = midi ? n : -1;
            entries.push_back (e);
        }
        rebuildColumns();
    }

    //== AU scan ===============================================================
    void startScan() { if (isThreadRunning()) return; scanButton.setEnabled (false); status.setText ("Scanning Audio Units...\n", dontSendNotification); startThread(); }

    void run() override
    {
        auto& pm = engine.getPluginManager();
        AudioPluginFormat* au = nullptr;
        for (auto* f : pm.pluginFormatManager.getFormats()) if (f->getName().containsIgnoreCase ("AudioUnit")) au = f;
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
        MessageManager::callAsync ([safe, ins] { if (safe == nullptr) return;
            AlertWindow::showMessageBoxAsync (MessageBoxIconType::NoIcon, "Audio Units",
                ins.isEmpty() ? String ("No AU instruments found.") : String (ins.size()) + " found:\n\n" + ins.joinIntoString ("\n"));
            safe->scanButton.setEnabled (true); });
    }

    te::Engine engine { "Music Producer" };
    std::unique_ptr<te::Edit> edit;
    std::vector<TrackEntry> entries;
    std::vector<TrackEntry> buses;
    int genSeed = 1, genBars = 8;
        Label      header, status;
    Label      keyLbl, tempoLbl, barsLbl, genreLbl;
    TextEditor keyEdit, tempoEdit, barsEdit, genreEdit;
    TextButton generateButton;
    Timeline   timeline;
    Viewport   mixerViewport;  Component mixerContainer;
    OwnedArray<ChannelColumn> columns;
    struct Divider : public Component { void paint (Graphics& g) override { g.fillAll (Colour (0xff3c4250)); } };
    Divider    busDivider;
    TextButton playButton, pauseButton, stopButton, saveButton, loadButton, settingsButton, scanButton;

    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (MainComponent)
};

//==============================================================================
class AIWorkstationApplication : public JUCEApplication
{
public:
    const String getApplicationName() override     { return "Music Producer"; }
    const String getApplicationVersion() override  { return "0.1.0"; }
    bool moreThanOneInstanceAllowed() override      { return true; }

    void initialise (const String&) override { mainWindow.reset (new MainWindow (getApplicationName())); }
    void shutdown() override                  { mainWindow = nullptr; }
    void systemRequestedQuit() override       { quit(); }

    class MainWindow : public DocumentWindow
    {
    public:
        explicit MainWindow (const String& name)
            : DocumentWindow (name, Desktop::getInstance().getDefaultLookAndFeel().findColour (ResizableWindow::backgroundColourId), DocumentWindow::allButtons)
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
