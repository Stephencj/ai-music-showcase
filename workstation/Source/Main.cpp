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
        engine.getDeviceManager().initialise (0, 2);   // output-only; mic input is opt-in via Settings

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

        loadBlockButton.setButtonText ("Load Block");        // pull a saved/scanned block into editable clips
        loadBlockButton.onClick = [this] { pickAndLoadBlock(); };
        addAndMakeVisible (loadBlockButton);

        timeline.getEdit = [this] { return edit.get(); };
        timeline.onSeek  = [this] (double sec) { if (edit) edit->getTransport().setPosition (te::TimePosition::fromSeconds (sec)); };
        addAndMakeVisible (timeline);

        addAndMakeVisible (mixerViewport);
        mixerViewport.setViewedComponent (&mixerContainer, false);
        mixerViewport.setScrollBarsShown (false, true);   // columns fill height; scroll horizontally
        mixerContainer.addChildComponent (busDivider);    // separator before the bus channels
        mixerContainer.onPopupRequested = [this] { showAddMenu(); };   // right-click empty mixer → Add menu

        addChildComponent (pianoRoll);                    // note editor overlay (hidden until Edit)
        pianoRoll.onClose = [this] { pianoRoll.setVisible (false); };

        auto button = [this] (TextButton& b, const String& t, std::function<void()> fn)
        { b.setButtonText (t); b.onClick = std::move (fn); addAndMakeVisible (b); };
        button (saveButton, "Save", [this] { saveProject(); });
        button (loadButton, "Load", [this] { loadProject(); });
        button (settingsButton, "Settings", [this] { showSettings(); });
        button (addBtn, "+ Add", [this] { showAddMenu(); });   // add channel / bus (mixer toolbar)

        // VCR-style transport, placed above the timeline
        auto vcr = [this] (TextButton& b, const char* sym, std::function<void()> fn)
        { b.setButtonText (String (CharPointer_UTF8 (sym))); b.onClick = std::move (fn); addAndMakeVisible (b); };
        vcr (playButton,   "\xe2\x96\xb6", [this] { transportPlay(); });   // play
        vcr (pauseButton,  "\xe2\x8f\xb8", [this] { transportPause(); });  // pause
        vcr (stopButton,   "\xe2\x8f\xb9", [this] { transportStop(); });   // stop
        vcr (recordButton, "\xe2\x8f\xba", [this] { transportRecord(); }); // record
        recordButton.setColour (TextButton::textColourOffId, Colours::red);

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
        genRow.removeFromLeft (8);
        loadBlockButton.setBounds (genRow.removeFromLeft (110));
        r.removeFromTop (8);

        auto tr = r.removeFromTop (28);                        // VCR transport above the timeline
        playButton.setBounds   (tr.removeFromLeft (42)); tr.removeFromLeft (4);
        pauseButton.setBounds  (tr.removeFromLeft (42)); tr.removeFromLeft (4);
        stopButton.setBounds   (tr.removeFromLeft (42)); tr.removeFromLeft (4);
        recordButton.setBounds (tr.removeFromLeft (42));
        r.removeFromTop (6);

        timeline.setBounds (r.removeFromTop (110));
        r.removeFromTop (8);

        auto mixTop = r.removeFromTop (24);                    // mixer toolbar
        addBtn.setBounds (mixTop.removeFromLeft (90));
        r.removeFromTop (4);

        mixerViewport.setBounds (r);
        layoutColumns();

        if (pianoRoll.isVisible()) pianoRoll.setBounds (getLocalBounds());
    }

    void openPianoRoll (te::AudioTrack* track)
    {
        if (track == nullptr) return;
        te::MidiClip* mc = nullptr;
        for (auto* c : track->getClips()) if (auto* m = dynamic_cast<te::MidiClip*> (c)) { mc = m; break; }
        if (mc == nullptr)   // empty channel: give it a clip to edit
        {
            const auto range = edit->tempoSequence.toTime ({ te::BeatPosition::fromBeats (0.0), te::BeatPosition::fromBeats (genBars * 4.0) });
            mc = dynamic_cast<te::MidiClip*> (track->insertNewClip (te::TrackItem::Type::midi, track->getName(), range, nullptr));
        }
        pianoRoll.setClip (mc, &edit->getUndoManager(), genKey, genScale, genProg, genBars, track->getName());
        pianoRoll.setBounds (getLocalBounds());
        pianoRoll.setVisible (true);
        pianoRoll.toFront (true);
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
        te::LevelMeterPlugin* meter = nullptr;         // output level meter
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
            for (int i = 0; i < n; ++i)                              // lane backgrounds + names
            {
                const float y = i * laneH;
                g.setColour ((i % 2) ? Colour (0xff242424) : Colour (0xff1f1f1f));
                g.fillRect (0.0f, y, (float) getWidth(), laneH);
                g.setColour (Colours::lightgrey); g.setFont (FontOptions (12.0f));
                g.drawText (tracks[i]->getName(), 5, (int) y, labelW - 8, (int) laneH, Justification::centredLeft);
            }
            // bar / beat subdivision lines across the lanes
            for (int b = 0; b <= (int) std::ceil (totalBeats); ++b)
            {
                const float x = beatToX ((double) b);
                const bool barLine = (b % 4) == 0;
                g.setColour (Colours::white.withAlpha (barLine ? 0.18f : 0.06f));
                g.drawVerticalLine ((int) x, 0.0f, (float) getHeight());
            }
            for (int i = 0; i < n; ++i)                              // clip blocks (on top of lines)
            {
                const float y = i * laneH;
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
    // vertical level meter (L/R peak) with the compressor threshold drawn across it
    struct LevelMeter : public Component, private Timer
    {
        te::LevelMeterPlugin* meter = nullptr;
        te::CompressorPlugin* comp = nullptr;
        te::LevelMeasurer::Client client;
        float lvlL = -100.0f, lvlR = -100.0f;

        LevelMeter() { startTimerHz (30); }
        ~LevelMeter() override { stopTimer(); detach(); }
        void detach() { if (meter != nullptr) meter->measurer.removeClient (client); meter = nullptr; }
        void attach (te::LevelMeterPlugin* m, te::CompressorPlugin* c)
        {
            detach(); meter = m; comp = c;
            if (meter != nullptr) meter->measurer.addClient (client);
        }
        void timerCallback() override
        {
            lvlL = jmax (lvlL - 1.8f, client.getAndClearAudioLevel (0).dB);
            lvlR = jmax (lvlR - 1.8f, client.getAndClearAudioLevel (1).dB);
            repaint();
        }
        void paint (Graphics& g) override
        {
            auto r = getLocalBounds().toFloat();
            g.setColour (Colour (0xff1a1c20)); g.fillRoundedRectangle (r, 2.0f);
            const float labelW = 16.0f;
            auto bars  = r.withTrimmedRight (labelW);
            auto scale = Rectangle<float> (bars.getRight(), r.getY(), labelW, r.getHeight());
            auto dbToY = [&] (float db) { return bars.getBottom() - (jlimit (-60.0f, 6.0f, db) + 60.0f) / 66.0f * bars.getHeight(); };
            const float w2 = bars.getWidth() * 0.5f;
            auto bar = [&] (float db, float x, float w)
            {
                const float y = dbToY (db);
                g.setColour (db > -1.0f ? Colours::red : (db > -8.0f ? Colour (0xffe2c044) : Colour (0xff3bdb6c)));
                g.fillRect (x, y, w, bars.getBottom() - y);
            };
            bar (lvlL, bars.getX() + 1.0f,        w2 - 1.5f);
            bar (lvlR, bars.getX() + w2 + 0.5f,   w2 - 1.5f);
            if (comp != nullptr && comp->isEnabled())          // compressor threshold marker
            {
                const float y = dbToY (Decibels::gainToDecibels (comp->thresholdGain.getCurrentValue()));
                g.setColour (Colours::orange);
                g.drawLine (bars.getX(), y, bars.getRight(), y, 1.4f);
            }
            g.setColour (Colour (0xff8893a8));                 // dB tick scale
            g.setFont (FontOptions (8.5f));
            for (int db : { 0, -6, -12, -24, -48 })
            {
                const float y = dbToY ((float) db);
                g.drawLine (bars.getRight() - 3.0f, y, bars.getRight(), y, 1.0f);
                g.drawText (String (db), (int) scale.getX(), (int) y - 6, (int) labelW, 12, Justification::centredLeft);
            }
        }
        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (LevelMeter)
    };

    // Roman-numeral (e.g. "vi") in a key/scale -> chord name (e.g. "Am").
    static String chordName (const String& key, const String& scale, const String& roman)
    {
        if (roman.trim().isEmpty()) return {};
        static const char* names[] = { "C","C#","D","Eb","E","F","F#","G","Ab","A","Bb","B" };
        auto noteIdx = [] (const String& k) -> int
        {
            static const std::pair<const char*, int> m[] = { {"C",0},{"C#",1},{"DB",1},{"D",2},{"D#",3},{"EB",3},{"E",4},
                {"F",5},{"F#",6},{"GB",6},{"G",7},{"G#",8},{"AB",8},{"A",9},{"A#",10},{"BB",10},{"B",11} };
            const auto u = k.toUpperCase();
            for (auto& e : m) if (u == e.first) return e.second;
            return 0;
        };
        const String core = roman.toUpperCase().retainCharacters ("IV");
        int degree = 0;
        if      (core.startsWith ("VII")) degree = 7;
        else if (core.startsWith ("VI"))  degree = 6;
        else if (core.startsWith ("IV"))  degree = 4;
        else if (core.startsWith ("V"))   degree = 5;
        else if (core.startsWith ("III")) degree = 3;
        else if (core.startsWith ("II"))  degree = 2;
        else if (core.startsWith ("I"))   degree = 1;
        if (degree == 0) return {};
        const int major[] = { 0,2,4,5,7,9,11 }, minor[] = { 0,2,3,5,7,8,10 };
        const int* deg = scale.equalsIgnoreCase ("minor") ? minor : major;
        const int rootSemi = (noteIdx (key) + deg[degree - 1]) % 12;
        String suffix;
        if (roman.containsIgnoreCase ("dim") || roman.contains (String::fromUTF8 ("\xc2\xb0"))) suffix = "dim";
        else if (roman.toLowerCase() == roman) suffix = "m";
        if (roman.contains ("7")) suffix += "7";
        return names[rootSemi] + suffix;
    }

    // Piano-roll editor for one MIDI clip, with the generator's chord changes as headers.
    struct PianoRoll : public Component
    {
        std::function<void()> onClose;
        te::MidiClip* clip = nullptr;
        juce::UndoManager* um = nullptr;
        String key = "C", scale = "major", trackName; StringArray prog; int bars = 8;
        int loPitch = 48, hiPitch = 72;
        TextButton closeBtn { "Close" };
        Label title;
        static constexpr int topBar = 30, chordH = 22, keyW = 32;

        PianoRoll()
        {
            title.setFont (FontOptions (15.0f, Font::bold)); title.setColour (Label::textColourId, Colours::white);
            addAndMakeVisible (title);
            closeBtn.onClick = [this] { if (onClose) onClose(); };
            addAndMakeVisible (closeBtn);
        }
        void setClip (te::MidiClip* c, juce::UndoManager* u, const String& k, const String& sc, const StringArray& p, int b, const String& nm)
        {
            clip = c; um = u; key = k; scale = sc; prog = p; bars = jmax (1, b);
            title.setText ("Edit  -  " + nm, dontSendNotification);
            loPitch = 48; hiPitch = 72;
            if (clip != nullptr)
                for (auto* n : clip->getSequence().getNotes()) { loPitch = jmin (loPitch, n->getNoteNumber() - 3); hiPitch = jmax (hiPitch, n->getNoteNumber() + 3); }
            loPitch = jlimit (0, 116, loPitch); hiPitch = jlimit (loPitch + 12, 127, hiPitch);
            repaint();
        }
        int totalBeats() const { return jmax (1, bars * 4); }
        float beatW() const   { return (float) (getWidth() - keyW) / (float) totalBeats(); }
        float rowH() const    { return (float) (getHeight() - topBar - chordH) / (float) jmax (1, hiPitch - loPitch); }
        float gridTop() const { return (float) (topBar + chordH); }
        float beatToX (double b) const { return keyW + (float) b * beatW(); }
        float pitchToY (int p) const   { return gridTop() + (float) (hiPitch - p) * rowH(); }

        void resized() override { title.setBounds (10, 4, getWidth() - 110, 22); closeBtn.setBounds (getWidth() - 84, 4, 74, 22); }

        void paint (Graphics& g) override
        {
            g.fillAll (Colour (0xff1b1d22));
            g.setColour (Colour (0xff232733)); g.fillRect (0, 0, getWidth(), topBar);
            const float bw = beatW(), rh = rowH();

            for (int p = loPitch; p < hiPitch; ++p)            // key rows
            {
                const float y = pitchToY (p + 1);
                const bool black = juce::Array<int> { 1,3,6,8,10 }.contains (p % 12);
                g.setColour (black ? Colour (0xff202329) : Colour (0xff262a31)); g.fillRect ((float) keyW, y, (float) (getWidth() - keyW), rh);
                if (p % 12 == 0) { g.setColour (Colour (0xff8893a8)); g.setFont (FontOptions (9.0f)); g.drawText ("C" + String (p / 12 - 1), 1, (int) y, keyW - 3, (int) rh, Justification::centredRight); }
            }
            for (int b = 0; b <= totalBeats(); ++b)            // bar/beat lines
            { const float x = beatToX (b); g.setColour (Colours::white.withAlpha (b % 4 == 0 ? 0.22f : 0.06f)); g.drawVerticalLine ((int) x, gridTop(), (float) getHeight()); }

            for (int bar = 0; bar < bars; ++bar)               // chord headers
            {
                const float x = keyW + bar * 4 * bw;
                g.setColour ((bar % 2) ? Colour (0xff2b3140) : Colour (0xff262b37)); g.fillRect (x, (float) topBar, 4 * bw, (float) chordH);
                g.setColour (Colours::white.withAlpha (0.15f)); g.drawVerticalLine ((int) x, (float) topBar, gridTop());
                g.setColour (Colour (0xffe2c044)); g.setFont (FontOptions (13.0f, Font::bold));
                g.drawText (prog.isEmpty() ? String() : chordName (key, scale, prog[bar % prog.size()]), (int) x + 5, topBar, (int) (4 * bw) - 7, chordH, Justification::centredLeft);
            }

            if (clip != nullptr)                               // notes
                for (auto* n : clip->getSequence().getNotes())
                {
                    const float x = beatToX (n->getStartBeat().inBeats());
                    const float w = jmax (3.0f, (float) n->getLengthBeats().inBeats() * bw);
                    const float y = pitchToY (n->getNoteNumber());
                    g.setColour (Colour (0xff5a7bff)); g.fillRoundedRectangle (x + 1.0f, y + 1.0f, w - 2.0f, rh - 2.0f, 2.0f);
                    g.setColour (Colour (0xff1b2a6b)); g.drawRoundedRectangle (x + 1.0f, y + 1.0f, w - 2.0f, rh - 2.0f, 2.0f, 1.0f);
                }
        }

        void mouseDown (const MouseEvent& e) override          // click empty = add note, click note = delete
        {
            if (clip == nullptr || um == nullptr || (float) e.y < gridTop() || e.x < keyW) return;
            const float bw = beatW(), rh = rowH();
            double beat = jmax (0.0, std::floor (((double) e.x - keyW) / bw * 2.0) / 2.0);   // snap 1/2 beat
            const int pitch = jlimit (0, 127, hiPitch - (int) (((float) e.y - gridTop()) / rh));
            auto& seq = clip->getSequence();
            for (auto* n : seq.getNotes())
                if (n->getNoteNumber() == pitch && beat >= n->getStartBeat().inBeats() - 1.0e-4 && beat < n->getEndBeat().inBeats())
                { seq.removeNote (*n, um); repaint(); return; }
            seq.addNote (pitch, te::BeatPosition::fromBeats (beat), te::BeatDuration::fromBeats (1.0), 90, 0, um);
            repaint();
        }

        JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR (PianoRoll)
    };

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
            {
                regen.setButtonText ("Regen"); regen.onClick = onRegen; addAndMakeVisible (regen);
                editBtn.setButtonText ("Edit"); editBtn.onClick = [this] { if (onEdit) onEdit(); }; addAndMakeVisible (editBtn);
            }

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

            // footer: Audio / MIDI routing (tracks only; populated later via setOutputs / setInputs / setMidiInputs / setMidiOutputs)
            if (isTrack)
            {
                auto label = [] (Label& l, const char* t) { l.setText (t, dontSendNotification); l.setFont (FontOptions (11.0f)); };
                label (inLbl,  "Audio In");   addAndMakeVisible (inLbl);
                label (outLbl, "Audio Out");  addAndMakeVisible (outLbl);
                label (midiInLbl,  "MIDI In");  addAndMakeVisible (midiInLbl);
                label (midiOutLbl, "MIDI Out"); addAndMakeVisible (midiOutLbl);
                for (auto* c : { &inBox, &outBox, &midiInBox, &midiOutBox })
                { c->addItem ("None", 1); c->setSelectedId (1, dontSendNotification); addAndMakeVisible (*c); }
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

            meterComp.attach (e.meter, e.comp);
            addAndMakeVisible (meterComp);

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

        // Populate the Input menu (tracks only): None + other channels + hardware input devices.
        void setInputs (const StringArray& names, int currentIndex, std::function<void(int)> cb)
        {
            inBox.clear (dontSendNotification);
            for (int i = 0; i < names.size(); ++i) inBox.addItem (names[i], i + 1);
            inBox.setSelectedId (currentIndex + 1, dontSendNotification);
            inBox.onChange = [this, cb] { if (cb) cb (inBox.getSelectedId() - 1); };
        }

        // MIDI routing (tracks only): mirror MIDI between channels — symmetric "In ← X" / "Out → X" views of the same link.
        void setMidiInputs (const StringArray& names, int currentIndex, std::function<void(int)> cb)
        {
            midiInBox.clear (dontSendNotification);
            for (int i = 0; i < names.size(); ++i) midiInBox.addItem (names[i], i + 1);
            midiInBox.setSelectedId (currentIndex + 1, dontSendNotification);
            midiInBox.onChange = [this, cb] { if (cb) cb (midiInBox.getSelectedId() - 1); };
        }
        void setMidiOutputs (const StringArray& names, int currentIndex, std::function<void(int)> cb)
        {
            midiOutBox.clear (dontSendNotification);
            for (int i = 0; i < names.size(); ++i) midiOutBox.addItem (names[i], i + 1);
            midiOutBox.setSelectedId (currentIndex + 1, dontSendNotification);
            midiOutBox.onChange = [this, cb] { if (cb) cb (midiOutBox.getSelectedId() - 1); };
        }

        std::function<void()> onRender;   // master only: render the mix
        std::function<void()> onEdit;     // open the piano roll for this track

        void resized() override
        {
            auto r = getLocalBounds().reduced (6, 4);
            name.setBounds (r.removeFromTop (24));
            if (! entry.isMaster && ! entry.isBus)
            {
                auto br = r.removeFromTop (22);
                regen.setBounds (br.removeFromLeft (br.getWidth() / 2 - 2)); br.removeFromLeft (4);
                editBtn.setBounds (br);
            }

            // pinned footer at the bottom; effects scroll in between
            // tracks: mute/solo + 4 routing rows (audio in/out + MIDI in/out) + pan/meter/fader
            const bool isTrackKind = (! entry.isMaster && ! entry.isBus);
            const int footerH = entry.isMaster ? 170 : (isTrackKind ? 290 : 200);
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
            }
            const bool isTrackKind = (! entry.isMaster && ! entry.isBus);
            if (isTrackKind)
            {
                const int labW = 58;
                auto row = [&] (Label& l, ComboBox& c) {
                    auto r2 = footer.removeFromTop (22);
                    l.setBounds (r2.removeFromLeft (labW));
                    c.setBounds (r2.reduced (1, 1));
                };
                row (inLbl, inBox);
                row (outLbl, outBox);
                row (midiInLbl, midiInBox);
                row (midiOutLbl, midiOutBox);
                footer.removeFromTop (4);
            }
            auto panCol = footer.removeFromLeft (64);
            panLbl.setBounds (panCol.removeFromTop (12));
            panKnob.setBounds (panCol.withSizeKeepingCentre (jmin (54, panCol.getWidth()), jmin (54, panCol.getHeight())));
            volLbl.setBounds (footer.removeFromTop (12));
            auto meterCol = footer.removeFromRight (30);   // level meter + dB scale beside the fader
            meterComp.setBounds (meterCol.reduced (2, 2));
            volFader.setBounds (footer.withSizeKeepingCentre (36, footer.getHeight()));
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
        TextButton mute, solo, regen, renderBtn, editBtn;
        Label inLbl, outLbl, midiInLbl, midiOutLbl;
        ComboBox inBox, outBox, midiInBox, midiOutBox;
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
        LevelMeter meterComp;
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

    // Find one of our audio tracks by its EditItemID, encoded as a string in track state.
    te::AudioTrack* findTrackByItemID (const String& s)
    {
        if (s.isEmpty()) return nullptr;
        for (auto* tr : te::getAudioTracks (*edit)) if (tr->itemID.toString() == s) return tr;
        return nullptr;
    }

    // --- Audio Out picker: Master, then buses, then other channels ----------
    StringArray audioOutNamesFor (te::AudioTrack* self)
    {
        StringArray n; n.add ("Master");
        for (auto& b : buses)   n.add (juce::String::fromUTF8 ("→ ") + b.role);
        for (auto& e : entries) if (e.track != self) n.add (juce::String::fromUTF8 ("→ ") + e.role);
        return n;
    }
    int audioOutIdxFor (te::AudioTrack* self)
    {
        if (self == nullptr) return 0;
        auto* dest = self->getOutput().getDestinationTrack();
        if (dest == nullptr) return 0;
        int idx = 1;
        for (auto& b : buses)   { if (b.track == dest) return idx; ++idx; }
        for (auto& e : entries) if (e.track != self) { if (e.track == dest) return idx; ++idx; }
        return 0;
    }
    void routeAudioOut (te::AudioTrack* self, int idx)
    {
        if (self == nullptr) return;
        if (idx <= 0) { self->getOutput().setOutputToDefaultDevice (false); return; }
        int j = 1;
        for (auto& b : buses)   { if (j == idx) { self->getOutput().setOutputToTrack (b.track); rebuildColumns(); return; } ++j; }
        for (auto& e : entries) if (e.track != self) { if (j == idx) { self->getOutput().setOutputToTrack (e.track); rebuildColumns(); return; } ++j; }
    }

    void addChannel()
    {
        auto* track = getOrInsertAudioTrackAt (te::getAudioTracks (*edit).size());
        TrackEntry e; e.track = track;
        e.role = "Channel " + String ((int) entries.size() + 1);
        track->setName (e.role);
        e.synth = insertPluginOfType<tewk::AISynthPlugin> (track, tewk::AISynthPlugin::xmlTypeName, 0);
        if (e.synth) e.synth->selectTemplate (tewk::InstrTemplate::lead);
        addChannelStrip (e, 1);
        e.volPlugin = track->getVolumePlugin();
        entries.push_back (e);
        rebuildColumns();                       // empty channel — use its Regen button to fill it
    }

    void addBus()
    {
        auto* track = getOrInsertAudioTrackAt (te::getAudioTracks (*edit).size());
        TrackEntry b; b.isBus = true; b.track = track;
        b.role = "Bus " + String ((int) buses.size() + 1);
        track->setName (b.role);
        track->state.setProperty (juce::Identifier ("mpBus"), true, nullptr);   // persists; identifies buses on load
        addChannelStrip (b, 0);
        b.volPlugin = track->getVolumePlugin();
        track->getOutput().setOutputToDefaultDevice (false);   // bus -> master
        buses.push_back (b);
        rebuildColumns();
    }

    void rebuildColumns()
    {
        columns.clear();

        for (int i = 0; i < (int) entries.size(); ++i)         // track channels (left)
        {
            auto* col = new ChannelColumn (entries[(size_t) i], [this, i] { regenerateTrack (i); });
            auto* track = entries[(size_t) i].track;
            col->onEdit = [this, track] { openPianoRoll (track); };
            col->setOutputs    (audioOutNamesFor (track),         audioOutIdxFor (track),    [this, track] (int idx) { routeAudioOut (track, idx); });
            col->setInputs     (audioInNamesFor (track),          audioInIdxFor (track),     [this, track] (int idx) { assignAudioIn (track, idx); });
            col->setMidiOutputs(midiPickerNamesFor (track, false), midiOutIdxFor (track),     [this, track] (int idx) { setMidiOutLink (track, idx); });
            col->setMidiInputs (midiPickerNamesFor (track, true),  midiInIdxFor (track),      [this, track] (int idx) { setMidiInLink  (track, idx); });
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
        m.meter  = ensureMasterPlugin<te::LevelMeterPlugin> (mpl, te::LevelMeterPlugin::xmlTypeName);
        if (m.meter) m.meter->setEnabled (true);
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
        e.meter  = insertPluginOfType<te::LevelMeterPlugin> (e.track, te::LevelMeterPlugin::xmlTypeName, 999); // append: post-fader
        if (e.preamp) e.preamp->setEnabled (false);
        if (e.eq)     e.eq->setEnabled (false);
        if (e.comp)   e.comp->setEnabled (false);   // meter stays enabled so it measures
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
        genKey  = resp.getProperty ("key", "C").toString();
        genScale = resp.getProperty ("scale", "major").toString();
        genProg.clear();
        if (auto* pa = resp.getProperty ("progression", var()).getArray())
            for (auto& pv : *pa) genProg.add (pv.toString());
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

    //== load a saved/scanned block into editable clips =======================
    // The backend's /api/blocks/{name}/notes returns the SAME shape as
    // /api/generate-arrangement (tempo/bars/key/scale/tracks[{track,notes}]),
    // so we can reuse onArrangement() to build the editable MIDI clips — that's
    // how a scanned score lands in the piano-roll for hand-correction.
    void pickAndLoadBlock()
    {
        const auto url = serverBase + "/api/blocks";
        Component::SafePointer<MainComponent> safe (this);
        status.setText ("Fetching blocks...", dontSendNotification);
        Thread::launch ([safe, url]
        {
            var resp;
            auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress)
                            .withConnectionTimeoutMs (30000);
            if (auto s = juce::URL (url).createInputStream (opts)) resp = JSON::parse (s->readEntireStreamAsString());
            MessageManager::callAsync ([safe, resp] { if (safe != nullptr) safe->showBlockMenu (resp); });
        });
    }

    void showBlockMenu (const var& resp)
    {
        auto* arr = resp.getArray();
        if (arr == nullptr || arr->isEmpty())
        { status.setText ("No blocks found (is the backend running on " + serverBase + "?).", dontSendNotification); return; }
        StringArray names;
        for (auto& bv : *arr) { auto nm = bv.getProperty ("name", "").toString(); if (nm.isNotEmpty()) names.add (nm); }
        names.sort (true);
        PopupMenu m;
        for (int i = 0; i < names.size(); ++i) m.addItem (i + 1, names[i]);
        Component::SafePointer<MainComponent> safe (this);
        m.showMenuAsync (PopupMenu::Options().withTargetComponent (&loadBlockButton),
            [safe, names] (int r) { if (safe != nullptr && r > 0) safe->loadBlock (names[r - 1]); });
    }

    void loadBlock (const String& name)
    {
        status.setText ("Loading " + name + "...", dontSendNotification);
        const auto url = serverBase + "/api/blocks/" + juce::URL::addEscapeChars (name, false) + "/notes";
        Component::SafePointer<MainComponent> safe (this);
        Thread::launch ([safe, url]
        {
            var resp;
            auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress)
                            .withConnectionTimeoutMs (60000);
            if (auto s = juce::URL (url).createInputStream (opts)) resp = JSON::parse (s->readEntireStreamAsString());
            MessageManager::callAsync ([safe, resp] { if (safe != nullptr) safe->onArrangement (resp); });
        });
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
        String part = role.toLowerCase();                      // custom channels -> a melody part
        if (part != "chords" && part != "bass" && part != "melody" && part != "drums") part = "melody";
        const auto url = serverBase + "/api/generate-arrangement";
        const auto payload = makeBody ({ part }, "midi", seed);
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
        syncAllMidiLinks();        // refresh any tracks mirroring MIDI from this one
        status.setText ("Regenerated " + role + " (" + String (n) + " notes).", dontSendNotification);
    }

    //== transport / render / save / load ======================================
    void transportPlay()   { auto& t = edit->getTransport(); t.ensureContextAllocated(); t.play (false); }     // from current position
    void transportPause()  { if (edit) edit->getTransport().stop (false, false); }                             // hold position
    void transportStop()   { if (edit) { auto& t = edit->getTransport(); t.stop (false, false); t.setPosition (te::TimePosition()); } }
    void transportRecord()
    {
        // If any channel has an internal record source ("Audio In ← Channel X"), bounce that
        // source into a wave clip on the destination instead of using hardware input.
        bool didBounce = false;
        stopPlayback();
        for (auto& e : entries)
        {
            const String srcId = e.track->state.getProperty (mpRecSrcId, {}).toString();
            if (srcId.isNotEmpty())
                if (auto* src = findTrackByItemID (srcId))
                { bounceSourceToTrack (src, e.track); didBounce = true; }
        }
        if (didBounce) { status.setText ("Bounced internal sources.", dontSendNotification); rebuildColumns(); return; }
        // Otherwise: normal hardware-input record.
        auto& t = edit->getTransport(); t.ensureContextAllocated(); t.record (false, false);
    }
    void stopPlayback()    { if (edit) edit->getTransport().stop (false, false); }

    //== Audio In picker: None, other channels/buses (internal), then hardware inputs =======
    // An internal source pipes that channel's output here AND arms a "bounce on Record" capture.
    static inline const juce::Identifier mpRecSrcId { "mpRecSrcId" };

    StringArray audioInNamesFor (te::AudioTrack* self)
    {
        StringArray n; n.add ("None");
        for (auto& e : entries) if (e.track != self) n.add (juce::String::fromUTF8 ("← ") + e.role);
        for (auto& b : buses)   if (b.track != self) n.add (juce::String::fromUTF8 ("← ") + b.role);
        for (auto* inst : edit->getAllInputDevices()) n.add (inst->getInputDevice().getName());
        return n;
    }
    int audioInIdxFor (te::AudioTrack* self)
    {
        if (self == nullptr) return 0;
        const String srcId = self->state.getProperty (mpRecSrcId, {}).toString();
        if (srcId.isNotEmpty())
        {
            int idx = 1;
            for (auto& e : entries) if (e.track != self) { if (e.track->itemID.toString() == srcId) return idx; ++idx; }
            for (auto& b : buses)   if (b.track != self) { if (b.track->itemID.toString() == srcId) return idx; ++idx; }
        }
        int hwBase = 1;
        for (auto& e : entries) if (e.track != self) ++hwBase;
        for (auto& b : buses)   if (b.track != self) ++hwBase;
        int j = hwBase;
        for (auto* inst : edit->getAllInputDevices()) { if (inst->getTargets().contains (self->itemID)) return j; ++j; }
        return 0;
    }
    void assignAudioIn (te::AudioTrack* self, int idx)
    {
        if (self == nullptr) return;
        auto* um = &edit->getUndoManager();
        edit->getEditInputDevices().clearAllInputs (*self, um);
        self->state.removeProperty (mpRecSrcId, nullptr);
        if (idx <= 0) { rebuildColumns(); return; }

        int j = 1;
        auto bindInternal = [&] (te::AudioTrack* src) {
            src->getOutput().setOutputToTrack (self);
            self->state.setProperty (mpRecSrcId, src->itemID.toString(), nullptr);
            rebuildColumns();
        };
        for (auto& e : entries) if (e.track != self) { if (j == idx) { bindInternal (e.track); return; } ++j; }
        for (auto& b : buses)   if (b.track != self) { if (j == idx) { bindInternal (b.track); return; } ++j; }

        const int hwIdx = idx - j;
        auto insts = edit->getAllInputDevices();
        if (hwIdx >= 0 && hwIdx < insts.size())
        {
            auto* inst = insts[hwIdx];
            inst->getInputDevice().setEnabled (true);
            [[ maybe_unused ]] auto r = inst->setTarget (self->itemID, true, um, 0);
            inst->setRecordingEnabled (self->itemID, true);
        }
        rebuildColumns();
    }

    //== MIDI link picker: mirror MIDI clips from a source channel into a destination ========
    // Stored as "mpMidiSrcId" on the destination track (the one whose MIDI mirrors a source).
    static inline const juce::Identifier mpMidiSrcId { "mpMidiSrcId" };

    StringArray midiPickerNamesFor (te::AudioTrack* self, bool isIn)
    {
        StringArray n; n.add ("None");
        const auto prefix = isIn ? juce::String::fromUTF8 ("← ") : juce::String::fromUTF8 ("→ ");
        for (auto& e : entries) if (e.track != self) n.add (prefix + e.role);
        return n;
    }
    // "Where do MY MIDI clips get mirrored TO?" — look for another track whose source = me.
    int midiOutIdxFor (te::AudioTrack* self)
    {
        int idx = 1;
        for (auto& e : entries) if (e.track != self)
        {
            if (e.track->state.getProperty (mpMidiSrcId, {}).toString() == self->itemID.toString()) return idx;
            ++idx;
        }
        return 0;
    }
    // "Where do MY MIDI clips come FROM?" — read our own mpMidiSrcId.
    int midiInIdxFor (te::AudioTrack* self)
    {
        const String src = self->state.getProperty (mpMidiSrcId, {}).toString();
        if (src.isEmpty()) return 0;
        int idx = 1;
        for (auto& e : entries) if (e.track != self)
        {
            if (e.track->itemID.toString() == src) return idx;
            ++idx;
        }
        return 0;
    }
    void clearMidiClipsOn (te::AudioTrack* tr)
    {
        if (tr == nullptr) return;
        juce::Array<te::Clip*> mids;
        for (auto* c : tr->getClips()) if (dynamic_cast<te::MidiClip*> (c)) mids.add (c);
        for (auto* c : mids) c->removeFromParent();
    }
    void syncMidiClips (te::AudioTrack* src, te::AudioTrack* dst)
    {
        if (src == nullptr || dst == nullptr || src == dst) return;
        clearMidiClipsOn (dst);
        auto* um = &edit->getUndoManager();
        for (auto* c : src->getClips()) if (auto* smc = dynamic_cast<te::MidiClip*> (c))
        {
            const auto pos = smc->getPosition();
            const te::TimeRange range (pos.getStart(), pos.getEnd());
            if (auto dmc = dst->insertMIDIClip ("MIDI Link", range, nullptr))
            {
                auto& dseq = dmc->getSequence();
                for (auto* note : smc->getSequence().getNotes())
                    dseq.addNote (note->getNoteNumber(), note->getStartBeat(), note->getLengthBeats(),
                                  note->getVelocity(), 0, um);
            }
        }
    }
    void syncAllMidiLinks()
    {
        for (auto& e : entries)
        {
            const String s = e.track->state.getProperty (mpMidiSrcId, {}).toString();
            if (s.isNotEmpty()) if (auto* src = findTrackByItemID (s)) syncMidiClips (src, e.track);
        }
    }
    // Set "self's MIDI goes to channel idx" — symmetric to setting that channel's MIDI In ← self.
    void setMidiOutLink (te::AudioTrack* self, int idx)
    {
        // Clear any existing MIDI link FROM self (other tracks whose src is self).
        for (auto& e : entries) if (e.track != self)
        {
            if (e.track->state.getProperty (mpMidiSrcId, {}).toString() == self->itemID.toString())
            {
                e.track->state.removeProperty (mpMidiSrcId, nullptr);
                clearMidiClipsOn (e.track);
            }
        }
        if (idx <= 0) { rebuildColumns(); return; }
        int j = 1;
        for (auto& e : entries) if (e.track != self)
        {
            if (j == idx)
            {
                e.track->state.setProperty (mpMidiSrcId, self->itemID.toString(), nullptr);
                syncMidiClips (self, e.track);
                rebuildColumns();
                return;
            }
            ++j;
        }
    }
    // Set "self's MIDI comes from channel idx" — stores src on self.
    void setMidiInLink (te::AudioTrack* self, int idx)
    {
        self->state.removeProperty (mpMidiSrcId, nullptr);
        clearMidiClipsOn (self);
        if (idx <= 0) { rebuildColumns(); return; }
        int j = 1;
        for (auto& e : entries) if (e.track != self)
        {
            if (j == idx)
            {
                self->state.setProperty (mpMidiSrcId, e.track->itemID.toString(), nullptr);
                syncMidiClips (e.track, self);
                rebuildColumns();
                return;
            }
            ++j;
        }
    }

    //== Bounce-on-Record: offline-render source channel to a wave clip on destination =======
    void bounceSourceToTrack (te::AudioTrack* src, te::AudioTrack* dst)
    {
        if (src == nullptr || dst == nullptr) return;
        auto dir = juce::File::getSpecialLocation (juce::File::tempDirectory).getChildFile ("MusicProducer/Bounces");
        dir.createDirectory();
        auto outFile = dir.getChildFile ("bounce_" + String ((juce::int64) Time::currentTimeMillis()) + ".wav");

        const double len = jmax (1.0, edit->getLength().inSeconds());
        juce::WavAudioFormat wav;
        te::Renderer::Parameters p (*edit);
        p.destFile = outFile;
        p.audioFormat = &wav;
        p.time = te::TimeRange (te::TimePosition(), te::TimePosition::fromSeconds (len));
        p.tracksToDo = te::toBitSet (juce::Array<te::Track*> { src });
        p.bitDepth = 24; p.sampleRateForAudio = 44100.0;
        p.usePlugins = true; p.useMasterPlugins = false;

        auto rendered = te::Renderer::renderToFile ("Bounce", p);
        if (! rendered.existsAsFile()) { status.setText ("Bounce render failed.", dontSendNotification); return; }

        auto clip = dst->insertWaveClip ("Bounce of " + src->getName(), rendered,
                                         { { te::TimePosition(), te::TimePosition::fromSeconds (len) } }, false);
        if (clip == nullptr) status.setText ("Bounce: could not insert clip.", dontSendNotification);
    }

    void showSettings()
    {
        PopupMenu m;
        m.addItem (1, "Export Stems...");
        m.addItem (2, "Enable Audio Input (for recording)");
        m.addItem (3, "Scan AU instruments");
        m.showMenuAsync (PopupMenu::Options().withTargetComponent (&settingsButton),
            [this] (int r) {
                if (r == 1) exportStems();
                else if (r == 2) { engine.getDeviceManager().initialise (2, 2); rebuildColumns(); status.setText ("Audio input enabled (grant mic permission if asked).", dontSendNotification); }
                else if (r == 3) startScan();
            });
    }

    void showAddMenu()
    {
        PopupMenu m;
        m.addItem (1, "Add Channel");
        m.addItem (2, "Add Bus");
        m.showMenuAsync (PopupMenu::Options().withTargetComponent (&addBtn),
            [this] (int r) { if (r == 1) addChannel(); else if (r == 2) addBus(); });
    }

    void renderWav()
    {
        stopPlayback();
        auto out = File::getSpecialLocation (File::userDesktopDirectory).getChildFile ("Music Producer.wav");
        const bool ok = te::Renderer::renderToFile (*edit, out, false);
        status.setText (ok ? ("Rendered: " + out.getFullPathName()) : "Render failed.", dontSendNotification);
    }

    void exportStems()
    {
        auto fc = std::make_shared<FileChooser> ("Export stems to folder...", File::getSpecialLocation (File::userDesktopDirectory));
        fc->launchAsync (FileBrowserComponent::openMode | FileBrowserComponent::canSelectDirectories,
            [this, fc] (const FileChooser& c)
            {
                auto dir = c.getResult();
                if (dir == File()) return;
                stopPlayback();
                juce::WavAudioFormat wav;
                const auto range = te::TimeRange (te::TimePosition(), te::TimePosition::fromSeconds (jmax (1.0, edit->getLength().inSeconds())));
                int done = 0;
                auto renderOne = [&] (te::AudioTrack* tr, const String& nm)
                {
                    if (tr == nullptr) return;
                    te::Renderer::Parameters p (*edit);
                    p.destFile = dir.getChildFile (File::createLegalFileName (nm) + ".wav");
                    p.audioFormat = &wav;
                    p.time = range;
                    p.tracksToDo = te::toBitSet (juce::Array<te::Track*> { tr });
                    p.bitDepth = 24; p.sampleRateForAudio = 44100.0;
                    p.usePlugins = true; p.useMasterPlugins = false;
                    if (te::Renderer::renderToFile ("Stem", p).existsAsFile()) ++done;
                };
                for (auto& e : entries) renderOne (e.track, e.role);
                for (auto& b : buses)   renderOne (b.track, b.role);
                te::Renderer::renderToFile (*edit, dir.getChildFile ("Master Mix.wav"), false);
                status.setText ("Exported " + String (done) + " stems + mix → " + dir.getFullPathName(), dontSendNotification);
            });
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
            e.meter  = track->pluginList.findFirstPluginOfType<te::LevelMeterPlugin>();
            e.volPlugin = track->getVolumePlugin();
            e.role   = track->getName();
            int n = 0; bool midi = false;
            for (auto* clip : track->getClips()) if (auto* mc = dynamic_cast<te::MidiClip*> (clip)) { midi = true; n += mc->getSequence().getNumNotes(); }
            e.notes = midi ? n : -1;
            if ((bool) track->state.getProperty (juce::Identifier ("mpBus"), false))
            { e.isBus = true; buses.push_back (e); }
            else
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
    String genKey = "C", genScale = "major";
    StringArray genProg { "I", "V", "vi", "IV" };
        Label      header, status;
    Label      keyLbl, tempoLbl, barsLbl, genreLbl;
    TextEditor keyEdit, tempoEdit, barsEdit, genreEdit;
    TextButton generateButton, loadBlockButton;
    Timeline   timeline;
    struct MixerArea : public Component
    {
        std::function<void()> onPopupRequested;
        void mouseDown (const MouseEvent& e) override { if (e.mods.isPopupMenu() && onPopupRequested) onPopupRequested(); }
    };
    Viewport   mixerViewport;  MixerArea mixerContainer;
    OwnedArray<ChannelColumn> columns;
    struct Divider : public Component { void paint (Graphics& g) override { g.fillAll (Colour (0xff3c4250)); } };
    Divider    busDivider;
    PianoRoll  pianoRoll;
    TextButton playButton, pauseButton, stopButton, recordButton, saveButton, loadButton, settingsButton, scanButton, addBtn;

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
