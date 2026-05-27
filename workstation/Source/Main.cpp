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

        header.setText ("AI Workstation", dontSendNotification);
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
        mixerViewport.setScrollBarsShown (true, true);

        auto button = [this] (TextButton& b, const String& t, std::function<void()> fn)
        { b.setButtonText (t); b.onClick = std::move (fn); addAndMakeVisible (b); };
        button (playButton, "Play", [this] { playFromStart(); });
        button (stopButton, "Stop", [this] { stopPlayback(); });
        button (renderButton, "Render", [this] { renderWav(); });
        button (saveButton, "Save", [this] { saveProject(); });
        button (loadButton, "Load", [this] { loadProject(); });
        button (scanButton, "Scan AU", [this] { startScan(); });

        masterLbl.setText ("Master", dontSendNotification);
        masterLbl.setJustificationType (Justification::centredRight);
        addAndMakeVisible (masterLbl);
        masterKnob.setSliderStyle (Slider::RotaryVerticalDrag);
        masterKnob.setRange (-48.0, 6.0, 0.1);
        masterKnob.setTextBoxStyle (Slider::TextBoxRight, false, 50, 22);
        masterKnob.setLookAndFeel (&knobLAF());
        masterKnob.onValueChange = [this] { if (auto m = edit->getMasterVolumePlugin()) m->setVolumeDb ((float) masterKnob.getValue()); };
        addAndMakeVisible (masterKnob);

        info.setMultiLine (true); info.setReadOnly (true);
        info.setFont (FontOptions (Font::getDefaultMonospacedFontName(), 12.0f, Font::plain));
        info.setText ("Press \"Generate Song\" to build a multi-track arrangement. Each track gets a channel column.",
                      dontSendNotification);
        addAndMakeVisible (info);

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
        header.setBounds (r.removeFromTop (26));
        status.setBounds (r.removeFromTop (22));
        r.removeFromTop (6);

        auto genRow = r.removeFromTop (28);
        auto fb = [&genRow] (Label& l, TextEditor& e, int lw, int ew)
        { l.setBounds (genRow.removeFromLeft (lw)); e.setBounds (genRow.removeFromLeft (ew)); genRow.removeFromLeft (8); };
        fb (keyLbl, keyEdit, 30, 44); fb (tempoLbl, tempoEdit, 44, 50);
        fb (barsLbl, barsEdit, 34, 44); fb (genreLbl, genreEdit, 44, 150);
        generateButton.setBounds (genRow.removeFromLeft (130));
        r.removeFromTop (10);

        timeline.setBounds (r.removeFromTop (110));
        r.removeFromTop (10);

        auto transport = r.removeFromBottom (34);
        for (auto* b : { &playButton, &stopButton, &renderButton, &saveButton, &loadButton, &scanButton })
        { b->setBounds (transport.removeFromLeft (80)); transport.removeFromLeft (5); }
        masterKnob.setBounds (transport.removeFromRight (150));
        masterLbl.setBounds (transport.removeFromRight (56));

        auto infoArea = r.removeFromBottom (78);
        info.setBounds (infoArea);
        r.removeFromBottom (6);

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
        String role; int notes = 0;
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
        // Diagonal group sizes: a PAIR fits one cell, a TRIPLE spans two cells.
        static constexpr int SH = 20, perRow = 3, colW = 232, DPH = 92, DTH = 104, CHAN = 210;

        ChannelColumn (TrackEntry e, std::function<void()> onRegen) : entry (e)
        {
            name.setText (e.role, dontSendNotification);
            name.setJustificationType (Justification::centred);
            name.setFont (FontOptions (15.0f, Font::bold));
            addAndMakeVisible (name);

            mute.setButtonText ("M");  mute.setClickingTogglesState (true);
            mute.setToggleState (e.track->isMuted (false), dontSendNotification);
            mute.onClick = [this] { entry.track->setMute (mute.getToggleState()); };
            solo.setButtonText ("S");  solo.setClickingTogglesState (true);
            solo.setToggleState (e.track->isSolo (false), dontSendNotification);
            solo.onClick = [this] { entry.track->setSolo (solo.getToggleState()); };
            regen.setButtonText ("Regen");
            regen.onClick = onRegen;
            addAndMakeVisible (mute); addAndMakeVisible (solo); addAndMakeVisible (regen);

            setupDisclosure (instrDisc,  instrOpen);
            setupDisclosure (preampDisc, preampOpen);
            setupDisclosure (eqDisc,     eqOpen);
            setupDisclosure (compDisc,   compOpen);

            // Instrument — synth: Tone/Shape, Attack/Release, Space/Move (Level moves to Preamp). Drum: Tone/Decay.
            instrLbl.setText (e.drum ? "Drum Kit" : "Instrument", dontSendNotification);
            section (instrLbl);
            if (e.synth != nullptr)
            {
                for (int i = 0; i < 4; ++i) templateBox.addItem (tewk::AISynthPlugin::templateName (i), i + 1);
                templateBox.setSelectedId (e.synth->getTemplateIndex() + 1, dontSendNotification);
                templateBox.onChange = [this] { entry.synth->selectTemplate ((tewk::InstrTemplate) (templateBox.getSelectedId() - 1)); loadInstrumentKnobs(); };
                addAndMakeVisible (templateBox);

                const char* mn[6] = { "Tone", "Shape", "Attack", "Release", "Space", "Move" };
                te::AutomatableParameter::Ptr mp[6] = { e.synth->tone, e.synth->shape, e.synth->attack, e.synth->release, e.synth->space, e.synth->move };
                nInstr = 6;
                for (int i = 0; i < nInstr; ++i) { instrParam[i] = mp[i]; bindParamKnob (i, mn[i]); }
            }
            else if (e.drum != nullptr)
            {
                const char* mn[2] = { "Tone", "Decay" };
                te::AutomatableParameter::Ptr mp[2] = { e.drum->tone, e.drum->decay };
                nInstr = 2;
                for (int i = 0; i < nInstr; ++i) { instrParam[i] = mp[i]; bindParamKnob (i, mn[i]); }
            }

            // Preamp — Drive/Output, plus the instrument Level lumped in (synth only) as a 3-tier group.
            preampOn.setButtonText ("Preamp"); preampOn.onClick = [this] { if (entry.preamp) entry.preamp->setEnabled (preampOn.getToggleState()); };
            if (e.preamp) preampOn.setToggleState (e.preamp->isEnabled(), dontSendNotification);
            addAndMakeVisible (preampOn);
            addGroupKnob (preampKnob[0], preampLbl[0], "Drive",  0, 1, 0.001, [this] { if (entry.preamp) entry.preamp->drive->setParameter  ((float) preampKnob[0].getValue(), sendNotification); });
            addGroupKnob (preampKnob[1], preampLbl[1], "Output", 0, 1, 0.001, [this] { if (entry.preamp) entry.preamp->output->setParameter ((float) preampKnob[1].getValue(), sendNotification); });
            if (e.preamp) { preampKnob[0].setValue (e.preamp->drive->getCurrentValue(), dontSendNotification); preampKnob[1].setValue (e.preamp->output->getCurrentValue(), dontSendNotification); }
            if (e.synth)
            {
                addGroupKnob (levelKnob, levelLbl, "Level", 0, 1, 0.001, [this] { entry.synth->level->setParameter ((float) levelKnob.getValue(), sendNotification); });
                levelKnob.setValue (e.synth->level->getCurrentValue(), dontSendNotification);
            }

            // EQ — Low/Mid/High as one 3-tier diagonal group.
            eqOn.setButtonText ("EQ"); eqOn.onClick = [this] { if (entry.eq) entry.eq->setEnabled (eqOn.getToggleState()); };
            if (e.eq) eqOn.setToggleState (e.eq->isEnabled(), dontSendNotification);
            addAndMakeVisible (eqOn);
            addGroupKnob (eqKnob[0], eqLbl[0], "Low",  -20, 20, 0.1, [this] { if (entry.eq) entry.eq->setLowGain  ((float) eqKnob[0].getValue()); });
            addGroupKnob (eqKnob[1], eqLbl[1], "Mid",  -20, 20, 0.1, [this] { if (entry.eq) entry.eq->setMidGain1 ((float) eqKnob[1].getValue()); });
            addGroupKnob (eqKnob[2], eqLbl[2], "High", -20, 20, 0.1, [this] { if (entry.eq) entry.eq->setHighGain ((float) eqKnob[2].getValue()); });
            if (e.eq) { eqKnob[0].setValue (e.eq->loGain->getCurrentValue(), dontSendNotification); eqKnob[1].setValue (e.eq->midGain1->getCurrentValue(), dontSendNotification); eqKnob[2].setValue (e.eq->hiGain->getCurrentValue(), dontSendNotification); }

            // Compressor — Thresh/Ratio and Attack/Release as two diagonal pairs.
            compOn.setButtonText ("Comp"); compOn.onClick = [this] { if (entry.comp) entry.comp->setEnabled (compOn.getToggleState()); };
            if (e.comp) compOn.setToggleState (e.comp->isEnabled(), dontSendNotification);
            addAndMakeVisible (compOn);
            addGroupKnob (compKnob[0], compLbl[0], "Thresh", -40, 0, 0.5, [this] { applyComp(); });
            addGroupKnob (compKnob[1], compLbl[1], "Ratio",   1, 20, 0.1, [this] { applyComp(); });
            addGroupKnob (compKnob[2], compLbl[2], "Attack", 0.3, 200, 0.5, [this] { applyComp(); });
            addGroupKnob (compKnob[3], compLbl[3], "Release", 10, 300, 1, [this] { applyComp(); });
            if (e.comp)
            {
                compKnob[0].setValue (Decibels::gainToDecibels (e.comp->thresholdGain.getCurrentValue()), dontSendNotification);
                compKnob[1].setValue (1.0 / jmax (0.05f, e.comp->ratio.getCurrentValue()), dontSendNotification);
                compKnob[2].setValue (e.comp->attackMs.getCurrentValue(), dontSendNotification);
                compKnob[3].setValue (e.comp->releaseMs.getCurrentValue(), dontSendNotification);
            }

            // Channel — Pan over the Volume fader.
            chanLbl.setText ("Channel", dontSendNotification); section (chanLbl);
            addKnob (panKnob, panLbl, "Pan", -1, 1, 0.01, [this] { if (auto* v = entry.track->getVolumePlugin()) v->setPan ((float) panKnob.getValue()); });
            volLbl.setText ("Vol", dontSendNotification); volLbl.setJustificationType (Justification::centred); volLbl.setFont (FontOptions (11.0f)); addAndMakeVisible (volLbl);
            volFader.setSliderStyle (Slider::LinearVertical);
            volFader.setRange (-48.0, 6.0, 0.1);
            volFader.setTextBoxStyle (Slider::TextBoxBelow, false, 60, 14);
            volFader.setColour (Slider::textBoxOutlineColourId, Colours::transparentBlack);
            volFader.setLookAndFeel (&faderLAF());
            volFader.onValueChange = [this] { if (auto* v = entry.track->getVolumePlugin()) v->setVolumeDb ((float) volFader.getValue()); };
            addAndMakeVisible (volFader);
            if (auto* v = e.track->getVolumePlugin()) { volFader.setValue (v->getVolumeDb(), dontSendNotification); panKnob.setValue (v->getPan(), dontSendNotification); }

            updateVisibility();
        }

        std::function<void()> onLayout;

        int preferredHeight() const
        {
            int h = 6 + 22 /*name*/ + 26 /*btns*/;
            h += SH + (instrOpen  ? ((entry.synth ? 24 : 0) + DPH) : 0);   // synth: 3 pairs row; drum: 1 pair
            h += SH + (preampOpen ? (entry.synth ? DTH : DPH) : 0);        // synth: Drive/Output/Level triple
            h += SH + (eqOpen     ? DTH : 0);                              // Low/Mid/High triple
            h += SH + (compOpen   ? DPH : 0);                              // two pairs in one row
            h += SH + CHAN;                                                // pan + fader
            return h + 8;
        }

        void resized() override
        {
            auto r = getLocalBounds().reduced (6, 4);
            name.setBounds (r.removeFromTop (22));
            auto btns = r.removeFromTop (24);
            regen.setBounds (btns.removeFromLeft (60)); btns.removeFromLeft (6);
            solo.setBounds (btns.removeFromRight (26)); btns.removeFromRight (4);
            mute.setBounds (btns.removeFromRight (26));

            headerRow (r, instrDisc, &instrLbl, nullptr);
            if (instrOpen)
            {
                if (entry.synth) templateBox.setBounds (r.removeFromTop (24).reduced (2, 1));
                auto row = r.removeFromTop (DPH);
                const int cw = row.getWidth() / perRow;
                if (entry.synth)
                {
                    diagPair (row.removeFromLeft (cw), instrKnob[0], instrLbl_[0], instrKnob[1], instrLbl_[1]);
                    diagPair (row.removeFromLeft (cw), instrKnob[2], instrLbl_[2], instrKnob[3], instrLbl_[3]);
                    diagPair (row.removeFromLeft (cw), instrKnob[4], instrLbl_[4], instrKnob[5], instrLbl_[5]);
                }
                else if (entry.drum)
                    diagPair (row.removeFromLeft (cw), instrKnob[0], instrLbl_[0], instrKnob[1], instrLbl_[1]);
            }

            headerRow (r, preampDisc, nullptr, &preampOn);
            if (preampOpen)
            {
                const int cw = (r.getWidth()) / perRow;
                if (entry.synth)
                {
                    auto area = r.removeFromTop (DTH).removeFromLeft (cw * 2);
                    Slider* k[3] = { &preampKnob[0], &preampKnob[1], &levelKnob };
                    Label*  l[3] = { &preampLbl[0],  &preampLbl[1],  &levelLbl  };
                    diagN (area, k, l, 3);
                }
                else
                    diagPair (r.removeFromTop (DPH).removeFromLeft (cw), preampKnob[0], preampLbl[0], preampKnob[1], preampLbl[1]);
            }

            headerRow (r, eqDisc, nullptr, &eqOn);
            if (eqOpen)
            {
                const int cw = r.getWidth() / perRow;
                auto area = r.removeFromTop (DTH).removeFromLeft (cw * 2);
                Slider* k[3] = { &eqKnob[0], &eqKnob[1], &eqKnob[2] };
                Label*  l[3] = { &eqLbl[0],  &eqLbl[1],  &eqLbl[2]  };
                diagN (area, k, l, 3);
            }

            headerRow (r, compDisc, nullptr, &compOn);
            if (compOpen)
            {
                auto row = r.removeFromTop (DPH);
                const int cw = row.getWidth() / perRow;
                diagPair (row.removeFromLeft (cw), compKnob[0], compLbl[0], compKnob[1], compLbl[1]);
                diagPair (row.removeFromLeft (cw), compKnob[2], compLbl[2], compKnob[3], compLbl[3]);
            }

            chanLbl.setBounds (r.removeFromTop (SH));
            auto chan = r.removeFromTop (CHAN);
            auto panArea = chan.removeFromTop (66);
            panLbl.setBounds (panArea.removeFromTop (12));
            panKnob.setBounds (panArea.withSizeKeepingCentre (jmin (54, panArea.getWidth()), jmin (54, panArea.getHeight())));
            volLbl.setBounds (chan.removeFromTop (12));
            volFader.setBounds (chan.withSizeKeepingCentre (46, chan.getHeight()));
        }

        void paint (Graphics& g) override
        {
            g.setColour (Colour (0xff2a2a2a)); g.fillRoundedRectangle (getLocalBounds().toFloat().reduced (2), 4.0f);
            g.setColour (Colour (0xff444444)); g.drawRoundedRectangle (getLocalBounds().toFloat().reduced (2), 4.0f, 1.0f);
        }

    private:
        void section (Label& l) { l.setJustificationType (Justification::centredLeft); l.setFont (FontOptions (12.0f, Font::bold)); l.setColour (Label::textColourId, Colour (0xff8fa0ff)); addAndMakeVisible (l); }

        void setupDisclosure (TextButton& b, bool& openFlag)
        {
            b.onClick = [this, &openFlag] { openFlag = ! openFlag; updateVisibility(); if (onLayout) onLayout(); };
            addAndMakeVisible (b);
        }

        void headerRow (Rectangle<int>& r, TextButton& disc, Label* lbl, ToggleButton* tog)
        {
            auto row = r.removeFromTop (SH);
            disc.setBounds (row.removeFromLeft (20)); row.removeFromLeft (2);
            if (lbl) lbl->setBounds (row);
            if (tog) tog->setBounds (row);
        }

        void updateVisibility()
        {
            instrDisc.setButtonText  (instrOpen  ? "v" : ">");
            preampDisc.setButtonText (preampOpen ? "v" : ">");
            eqDisc.setButtonText     (eqOpen     ? "v" : ">");
            compDisc.setButtonText   (compOpen   ? "v" : ">");
            if (entry.synth) templateBox.setVisible (instrOpen);
            for (int i = 0; i < nInstr; ++i) { instrKnob[i].setVisible (instrOpen); instrLbl_[i].setVisible (instrOpen); }
            for (int i = 0; i < 2; ++i) { preampKnob[i].setVisible (preampOpen); preampLbl[i].setVisible (preampOpen); }
            if (entry.synth) { levelKnob.setVisible (preampOpen); levelLbl.setVisible (preampOpen); }
            for (int i = 0; i < 3; ++i) { eqKnob[i].setVisible (eqOpen); eqLbl[i].setVisible (eqOpen); }
            for (int i = 0; i < 4; ++i) { compKnob[i].setVisible (compOpen); compLbl[i].setVisible (compOpen); }
        }

        // a normal knob (rotary + value box) — used for Pan
        void addKnob (Slider& s, Label& l, const String& nm, double lo, double hi, double step, std::function<void()> cb)
        {
            l.setText (nm, dontSendNotification); l.setJustificationType (Justification::centred); l.setFont (FontOptions (11.0f)); addAndMakeVisible (l);
            s.setSliderStyle (Slider::RotaryVerticalDrag);
            s.setRange (lo, hi, step);
            s.setTextBoxStyle (Slider::TextBoxBelow, false, 64, 14);
            s.setColour (Slider::textBoxOutlineColourId, Colours::transparentBlack);
            s.setLookAndFeel (&knobLAF());
            s.onValueChange = std::move (cb);
            addAndMakeVisible (s);
        }

        // a compact knob for diagonal groups (no value box; just the faux knob + a small name)
        void addGroupKnob (Slider& s, Label& l, const String& nm, double lo, double hi, double step, std::function<void()> cb)
        {
            l.setText (nm, dontSendNotification); l.setJustificationType (Justification::centred); l.setFont (FontOptions (10.0f)); l.setColour (Label::textColourId, Colour (0xffaab2c8)); addAndMakeVisible (l);
            s.setSliderStyle (Slider::RotaryVerticalDrag);
            s.setRange (lo, hi, step);
            s.setTextBoxStyle (Slider::NoTextBox, false, 0, 0);
            s.setLookAndFeel (&knobLAF());
            s.onValueChange = std::move (cb);
            addAndMakeVisible (s);
        }

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

        // ----- the reusable "diagonal group": N knobs from top-left to bottom-right,
        //       slightly overlapping, labelled above each. 2 knobs fit one cell, 3 fit two.
        void diagN (Rectangle<int> r, Slider** k, Label** l, int count)
        {
            const int lblH = 11;
            const int ks = (count <= 2) ? jmin (r.getWidth() * 64 / 100, r.getHeight() * 58 / 100)
                                        : jmin (r.getWidth() * 40 / 100, r.getHeight() * 58 / 100);
            for (int i = 0; i < count; ++i)
            {
                const double t = (count <= 1) ? 0.0 : (double) i / (count - 1);
                const int x = r.getX() + roundToInt (t * (r.getWidth() - ks));
                const int y = r.getY() + lblH + roundToInt (t * (r.getHeight() - lblH - ks));
                l[i]->setBounds (x, y - lblH, ks, lblH);
                k[i]->setBounds (x, y, ks, ks);
            }
        }
        void diagPair (Rectangle<int> r, Slider& a, Label& al, Slider& b, Label& bl)
        {
            Slider* k[2] = { &a, &b }; Label* l[2] = { &al, &bl };
            diagN (r, k, l, 2);
        }

        TrackEntry entry;
        Label name, instrLbl, chanLbl;
        TextButton mute, solo, regen;
        TextButton instrDisc, preampDisc, eqDisc, compDisc;
        bool instrOpen = true, preampOpen = false, eqOpen = false, compOpen = false;
        ComboBox templateBox;
        te::AutomatableParameter::Ptr instrParam[6];
        Slider instrKnob[6]; Label instrLbl_[6]; int nInstr = 0;
        Slider levelKnob; Label levelLbl;
        ToggleButton preampOn; Slider preampKnob[2]; Label preampLbl[2];
        ToggleButton eqOn;     Slider eqKnob[3];     Label eqLbl[3];
        ToggleButton compOn;   Slider compKnob[4];   Label compLbl[4];
        Slider volFader, panKnob; Label volLbl, panLbl;
        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (ChannelColumn)
    };

    //== columns ===============================================================
    void rebuildColumns()
    {
        columns.clear();
        for (int i = 0; i < (int) entries.size(); ++i)
        {
            auto* col = new ChannelColumn (entries[(size_t) i], [this, i] { regenerateTrack (i); });
            col->onLayout = [this] { layoutColumns(); };
            mixerContainer.addAndMakeVisible (col);
            columns.add (col);
        }
        layoutColumns();
        refreshStatus();
    }

    void layoutColumns()
    {
        const int w = ChannelColumn::colW;
        int maxH = 200;
        for (auto* c : columns) maxH = jmax (maxH, c->preferredHeight());   // collapsing a section changes this
        columnHeight = maxH;
        for (int i = 0; i < columns.size(); ++i)
            columns[i]->setBounds (i * w, 0, w, columnHeight);
        mixerContainer.setSize (jmax (mixerViewport.getWidth(), columns.size() * w),
                                jmax (mixerViewport.getHeight() - 2, columnHeight));
    }

    void refreshStatus()
    {
        auto* dev = engine.getDeviceManager().deviceManager.getCurrentAudioDevice();
        String s;
        s << "Engine up    |    Tracks: " << (int) entries.size()
          << "    |    Audio out: " << (dev != nullptr ? dev->getName() : String ("(none)"));
        status.setText (s, dontSendNotification);
    }

    void reloadMaster() { if (auto m = edit->getMasterVolumePlugin()) masterKnob.setValue (m->getVolumeDb(), dontSendNotification); }

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
        entries.push_back (e);
    }

    void buildInstrumentAndPhrase()
    {
        entries.clear();
        genBars = 2;
        Array<var> arr;
        auto add = [&] (int p, double s, double l) { arr.add (var (Array<var> { p, s, l })); };
        for (double bar = 0.0; bar < 8.0; bar += 4.0) { add (48, bar, 4.0); add (51, bar, 4.0); add (55, bar, 4.0); }
        const int a[] = { 60, 63, 67, 70, 67, 63, 67, 70 };
        for (int i = 0; i < 8; ++i) add (a[i], (double) i, 0.9);
        buildTrack (0, "Chords", var (arr));
        rebuildColumns();
        reloadMaster();
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
        info.setText ("Generating arrangement...", dontSendNotification);
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
        { info.setText ("Generation failed (backend on " + serverBase + " not reachable).", dontSendNotification); generateButton.setEnabled (true); return; }

        stopPlayback();
        columns.clear();                         // drop old columns before the edit goes away
        const double tempo = (double) resp.getProperty ("tempo", 120.0);
        genBars = (int) resp.getProperty ("bars", 8);
        edit = te::Edit::createSingleTrackEdit (engine);
        if (auto* t0 = edit->tempoSequence.getTempo (0)) t0->setBpm (tempo);

        entries.clear();
        StringArray built;
        if (auto* tracks = resp.getProperty ("tracks", var()).getArray())
            for (auto& tv : *tracks)
            { const String role = tv.getProperty ("track", "").toString(); buildTrack ((int) entries.size(), role, tv.getProperty ("notes", var())); built.add (role); }

        rebuildColumns();
        reloadMaster();
        edit->getTransport().ensureContextAllocated();   // ready to play, but don't auto-start
        generateButton.setEnabled (true);
        info.setText ("Generated " + String ((int) entries.size()) + " tracks: " + built.joinIntoString (", ") + " @ " + String (tempo, 0) + " bpm. Press Play.", dontSendNotification);
    }

    //== regenerate one track ==================================================
    void clearTrackClips (te::AudioTrack* track) { juce::Array<te::Clip*> clips (track->getClips()); for (auto* c : clips) c->removeFromParent(); }

    void regenerateTrack (int i)
    {
        if (i < 0 || i >= (int) entries.size()) return;
        auto* track = entries[(size_t) i].track;
        const String role = entries[(size_t) i].role;
        const int seed = Random::getSystemRandom().nextInt (1000000);
        info.setText ("Regenerating " + role + "...", dontSendNotification);
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
        if (! resp.isObject()) { info.setText ("Regen failed.", dontSendNotification); return; }
        var notes;
        if (auto* tracks = resp.getProperty ("tracks", var()).getArray()) if (! tracks->isEmpty()) notes = (*tracks)[0].getProperty ("notes", var());
        clearTrackClips (track);
        const int n = addNotes (track, role, notes, genBars * 4.0);
        info.setText ("Regenerated " + role + " (" + String (n) + " notes).", dontSendNotification);
    }

    //== transport / render / save / load ======================================
    void playFromStart() { auto& t = edit->getTransport(); t.ensureContextAllocated(); t.playFromStart (true); }
    void stopPlayback()  { if (edit) edit->getTransport().stop (false, false); }

    void renderWav()
    {
        stopPlayback();
        auto out = File::getSpecialLocation (File::userDesktopDirectory).getChildFile ("AI Workstation.wav");
        const bool ok = te::Renderer::renderToFile (*edit, out, false);
        info.setText (ok ? ("Rendered: " + out.getFullPathName()) : "Render failed.", dontSendNotification);
    }

    void saveProject()
    {
        auto fc = std::make_shared<FileChooser> ("Save project",
                      File::getSpecialLocation (File::userDocumentsDirectory).getChildFile ("song.tracktionedit"), "*.tracktionedit");
        fc->launchAsync (FileBrowserComponent::saveMode | FileBrowserComponent::warnAboutOverwriting,
            [this, fc] (const FileChooser& c) { auto f = c.getResult(); if (f == File()) return;
                const bool ok = te::EditFileOperations (*edit).writeToFile (f, false);
                info.setText (ok ? ("Saved: " + f.getFullPathName()) : "Save failed.", dontSendNotification); });
    }

    void loadProject()
    {
        auto fc = std::make_shared<FileChooser> ("Load project", File::getSpecialLocation (File::userDocumentsDirectory), "*.tracktionedit");
        fc->launchAsync (FileBrowserComponent::openMode | FileBrowserComponent::canSelectFiles,
            [this, fc] (const FileChooser& c) { auto f = c.getResult(); if (f == File() || ! f.existsAsFile()) return;
                stopPlayback(); columns.clear();
                if (auto loaded = te::loadEditFromFile (engine, f)) { edit = std::move (loaded); rebuildEntriesFromEdit(); info.setText ("Loaded: " + f.getFullPathName(), dontSendNotification); }
                else info.setText ("Load failed.", dontSendNotification); });
    }

    void rebuildEntriesFromEdit()
    {
        entries.clear();
        for (auto* track : te::getAudioTracks (*edit))
        {
            TrackEntry e; e.track = track;
            e.synth  = track->pluginList.findFirstPluginOfType<tewk::AISynthPlugin>();
            e.drum   = track->pluginList.findFirstPluginOfType<tewk::AIDrumKitPlugin>();
            e.preamp = track->pluginList.findFirstPluginOfType<tewk::AIPreampPlugin>();
            e.eq     = track->pluginList.findFirstPluginOfType<te::EqualiserPlugin>();
            e.comp   = track->pluginList.findFirstPluginOfType<te::CompressorPlugin>();
            e.role   = track->getName();
            int n = 0; bool midi = false;
            for (auto* clip : track->getClips()) if (auto* mc = dynamic_cast<te::MidiClip*> (clip)) { midi = true; n += mc->getSequence().getNumNotes(); }
            e.notes = midi ? n : -1;
            entries.push_back (e);
        }
        rebuildColumns();
        reloadMaster();
    }

    //== AU scan ===============================================================
    void startScan() { if (isThreadRunning()) return; scanButton.setEnabled (false); info.setText ("Scanning Audio Units...\n", dontSendNotification); startThread(); }

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
            safe->info.setText (ins.isEmpty() ? String ("No AU instruments found.") : String (ins.size()) + " AU instrument(s):\n\n" + ins.joinIntoString ("\n"), dontSendNotification);
            safe->scanButton.setEnabled (true); });
    }

    te::Engine engine { "AI Workstation" };
    std::unique_ptr<te::Edit> edit;
    std::vector<TrackEntry> entries;
    int genSeed = 1, genBars = 8, columnHeight = 600;

    Label      header, status, masterLbl;
    Label      keyLbl, tempoLbl, barsLbl, genreLbl;
    TextEditor keyEdit, tempoEdit, barsEdit, genreEdit;
    TextButton generateButton;
    Timeline   timeline;
    Viewport   mixerViewport;  Component mixerContainer;
    OwnedArray<ChannelColumn> columns;
    Slider     masterKnob;
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
