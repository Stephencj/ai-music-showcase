/*
    AI Workstation — Tracktion Engine app with our own native instrument.

    Phase 1 (done): engine boots, Edit + track, our built-in AI Synth plays live
    and renders. This screen now exposes the instrument the way Stephen wants it:
    a Template menu (Pad / Bass / Lead / Pluck) + six simple "macro" knobs.
    Phase 2 will wire /api/generate-arrangement into a multi-track Edit.
*/

#include <juce_gui_basics/juce_gui_basics.h>
#include <tracktion_engine/tracktion_engine.h>
#include "AISynthPlugin.h"

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

        engine.getDeviceManager().initialise (0, 2);     // open output so live play is audible

        edit = te::Edit::createSingleTrackEdit (engine);
        buildInstrumentAndPhrase();

        header.setText ("AI Workstation — AI Synth (our own instrument)", dontSendNotification);
        header.setFont (FontOptions (20.0f, Font::bold));
        addAndMakeVisible (header);

        status.setJustificationType (Justification::topLeft);
        addAndMakeVisible (status);

        // Template menu
        templateLbl.setText ("Template", dontSendNotification);
        addAndMakeVisible (templateLbl);
        for (int i = 0; i < 4; ++i)
            templateBox.addItem (tewk::AISynthPlugin::templateName (i), i + 1);
        templateBox.setSelectedId ((synth != nullptr ? synth->getTemplateIndex() : 0) + 1, dontSendNotification);
        templateBox.onChange = [this]
        {
            if (synth != nullptr)
            {
                synth->selectTemplate ((tewk::InstrTemplate) (templateBox.getSelectedId() - 1));
                syncMacrosToUI();
            }
        };
        addAndMakeVisible (templateBox);

        // Six macros + level
        const char* names[NumMacros] = { "Tone", "Shape", "Attack", "Release", "Space", "Move", "Level" };
        for (int i = 0; i < NumMacros; ++i)
        {
            macroLbl[i].setText (names[i], dontSendNotification);
            macroLbl[i].setJustificationType (Justification::centredRight);
            addAndMakeVisible (macroLbl[i]);

            auto& s = macroSlider[i];
            s.setSliderStyle (Slider::LinearHorizontal);
            s.setRange (0.0, 1.0, 0.001);
            s.setTextBoxStyle (Slider::TextBoxRight, false, 52, 22);
            s.onValueChange = [this, i]
            {
                if (auto p = paramFor (i))
                    p->setParameter ((float) macroSlider[i].getValue(), sendNotification);
            };
            addAndMakeVisible (s);
        }
        syncMacrosToUI();

        auto button = [this] (TextButton& b, const String& t, std::function<void()> fn)
        { b.setButtonText (t); b.onClick = std::move (fn); addAndMakeVisible (b); };
        button (playButton,   "Play",        [this] { playPhrase(); });
        button (stopButton,   "Stop",        [this] { stopPlayback(); });
        button (renderButton, "Render WAV",  [this] { renderWav(); });
        button (scanButton,   "Scan AU",     [this] { startScan(); });

        info.setMultiLine (true);
        info.setReadOnly (true);
        info.setFont (FontOptions (Font::getDefaultMonospacedFontName(), 13.0f, Font::plain));
        info.setText ("Pick a template, tweak the macros, and press Play to hear the 2-bar phrase.\n"
                      "Each macro moves several parameters under the hood.", dontSendNotification);
        addAndMakeVisible (info);

        refreshStatus();
        setSize (860, 640);
    }

    ~MainComponent() override
    {
        stopThread (5000);
        if (edit != nullptr)
            edit->getTransport().stop (false, false);
    }

    void resized() override
    {
        auto r = getLocalBounds().reduced (16);
        header.setBounds (r.removeFromTop (30));
        r.removeFromTop (4);
        status.setBounds (r.removeFromTop (40));
        r.removeFromTop (8);

        auto top = r.removeFromTop (28);
        templateLbl.setBounds (top.removeFromLeft (70));
        templateBox.setBounds (top.removeFromLeft (160));
        top.removeFromLeft (16);
        for (auto* b : { &playButton, &stopButton, &renderButton, &scanButton })
        { b->setBounds (top.removeFromLeft (96)); top.removeFromLeft (6); }

        r.removeFromTop (12);
        for (int i = 0; i < NumMacros; ++i)
        {
            auto row = r.removeFromTop (30);
            macroLbl[i].setBounds (row.removeFromLeft (70));
            row.removeFromLeft (8);
            macroSlider[i].setBounds (row);
            r.removeFromTop (4);
        }

        r.removeFromTop (10);
        info.setBounds (r);
    }

    void paint (Graphics& g) override
    {
        g.fillAll (getLookAndFeel().findColour (ResizableWindow::backgroundColourId));
    }

private:
    enum { NumMacros = 7 };

    te::AutomatableParameter::Ptr paramFor (int i) const
    {
        if (synth == nullptr) return {};
        switch (i)
        {
            case 0: return synth->tone;    case 1: return synth->shape;
            case 2: return synth->attack;  case 3: return synth->release;
            case 4: return synth->space;   case 5: return synth->move;
            case 6: return synth->level;   default: return {};
        }
    }

    void syncMacrosToUI()
    {
        for (int i = 0; i < NumMacros; ++i)
            if (auto p = paramFor (i))
                macroSlider[i].setValue (p->getCurrentValue(), dontSendNotification);
    }

    void refreshStatus()
    {
        auto* dev = engine.getDeviceManager().deviceManager.getCurrentAudioDevice();
        String s;
        s << "Engine up    |    Instrument: AI Synth ("
          << (synth != nullptr ? tewk::AISynthPlugin::templateName (synth->getTemplateIndex()) : "?") << ")\n";
        s << "Audio out: " << (dev != nullptr ? dev->getName() : String ("(none)"));
        status.setText (s, dontSendNotification);
    }

    te::AudioTrack* getOrInsertAudioTrackAt (int index)
    {
        edit->ensureNumberOfAudioTracks (index + 1);
        return te::getAudioTracks (*edit)[index];
    }

    void buildInstrumentAndPhrase()
    {
        auto* track = getOrInsertAudioTrackAt (0);

        if (auto p = edit->getPluginCache().createNewPlugin (tewk::AISynthPlugin::xmlTypeName, {}))
        {
            synth = dynamic_cast<tewk::AISynthPlugin*> (p.get());
            track->pluginList.insertPlugin (p, 0, nullptr);
        }

        const auto range = edit->tempoSequence.toTime ({ te::BeatPosition::fromBeats (0.0),
                                                          te::BeatPosition::fromBeats (8.0) });
        if (auto* clip = dynamic_cast<te::MidiClip*> (
                track->insertNewClip (te::TrackItem::Type::midi, "AI Phrase", range, nullptr)))
        {
            auto& seq = clip->getSequence();
            auto* um  = &edit->getUndoManager();
            auto add  = [&] (int pitch, double startBeat, double lenBeats, int vel)
            {
                seq.addNote (pitch, te::BeatPosition::fromBeats (startBeat),
                             te::BeatDuration::fromBeats (lenBeats), vel, 0, um);
            };
            for (double bar = 0.0; bar < 8.0; bar += 4.0)
            {
                add (48, bar, 4.0, 80); add (51, bar, 4.0, 78); add (55, bar, 4.0, 78);  // Cm
            }
            const int arp[] = { 60, 63, 67, 70, 67, 63, 67, 70 };
            for (int i = 0; i < 8; ++i)
                add (arp[i], (double) i, 0.9, 100);
        }
    }

    void playPhrase()
    {
        auto& t = edit->getTransport();
        t.ensureContextAllocated();
        t.playFromStart (true);
        info.setText ("Playing the 2-bar phrase through the AI Synth.", dontSendNotification);
    }

    void stopPlayback() { if (edit) edit->getTransport().stop (false, false); }

    void renderWav()
    {
        stopPlayback();
        auto out = File::getSpecialLocation (File::userDesktopDirectory)
                       .getChildFile (String ("AI Workstation - ") +
                                      (synth ? tewk::AISynthPlugin::templateName (synth->getTemplateIndex()) : "Synth") + ".wav");
        const bool ok = te::Renderer::renderToFile (*edit, out, false);
        info.setText (ok ? ("Rendered: " + out.getFullPathName()) : "Render failed.", dontSendNotification);
    }

    //== AU scan (capability check) ============================================
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
        StringArray instruments;
        for (const auto& d : pm.knownPluginList.getTypes())
            if (d.isInstrument) instruments.add (d.name + "  [" + d.pluginFormatName + "]");
        instruments.sort (true);
        Component::SafePointer<MainComponent> safe (this);
        MessageManager::callAsync ([safe, instruments]
        {
            if (safe == nullptr) return;
            safe->info.setText (instruments.isEmpty() ? String ("No AU instruments found.")
                : String (instruments.size()) + " AU instrument(s):\n\n" + instruments.joinIntoString ("\n"),
                dontSendNotification);
            safe->scanButton.setEnabled (true);
        });
    }

    te::Engine engine { "AI Workstation" };
    std::unique_ptr<te::Edit> edit;
    tewk::AISynthPlugin* synth = nullptr;

    Label      header, status, templateLbl;
    ComboBox   templateBox;
    Label      macroLbl[NumMacros];
    Slider     macroSlider[NumMacros];
    TextButton playButton, stopButton, renderButton, scanButton;
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
            : DocumentWindow (name,
                              Desktop::getInstance().getDefaultLookAndFeel().findColour (ResizableWindow::backgroundColourId),
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
