/*
    AI Workstation — Phase 1 foundation + first native instrument.

    Proves the "build our own on Tracktion Engine" direction end to end:
      * the engine builds/links/runs on this Mac,
      * we can boot it, create an Edit and add tracks,
      * we host OUR OWN software instrument (AISynthPlugin, a built-in synth —
        no AU, no sample data) on a track,
      * we can play a MIDI phrase through it and render it to a WAV.

    The AU scan is kept as a capability check. Generation wiring
    (/api/generate-arrangement → a track per part) is Phase 2.
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
        pm.createBuiltInType<tewk::AISynthPlugin>();      // register our own instrument

        edit = te::Edit::createSingleTrackEdit (engine);

        header.setText ("AI Workstation — Tracktion Engine + native AI Synth", dontSendNotification);
        header.setFont (FontOptions (20.0f, Font::bold));
        addAndMakeVisible (header);

        status.setJustificationType (Justification::topLeft);
        addAndMakeVisible (status);

        auto setupButton = [this] (TextButton& b, const String& text, std::function<void()> fn)
        {
            b.setButtonText (text);
            b.onClick = std::move (fn);
            addAndMakeVisible (b);
        };
        setupButton (playButton,   "Play AI Synth phrase", [this] { playDemo(); });
        setupButton (stopButton,   "Stop",                 [this] { stopPlayback(); });
        setupButton (renderButton, "Render WAV",           [this] { renderWav(); });
        setupButton (scanButton,   "Scan AU instruments",  [this] { startScan(); });

        info.setMultiLine (true);
        info.setReadOnly (true);
        info.setFont (FontOptions (Font::getDefaultMonospacedFontName(), 13.0f, Font::plain));
        info.setText ("Press \"Play AI Synth phrase\" to build a track with our built-in synth and play a few bars.",
                      dontSendNotification);
        addAndMakeVisible (info);

        refreshStatus();
        setSize (820, 600);
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
        header.setBounds (r.removeFromTop (32));
        r.removeFromTop (6);
        status.setBounds (r.removeFromTop (64));
        auto row = r.removeFromTop (34);
        for (auto* b : { &playButton, &stopButton, &renderButton, &scanButton })
        {
            b->setBounds (row.removeFromLeft (190));
            row.removeFromLeft (8);
        }
        r.removeFromTop (10);
        info.setBounds (r);
    }

    void paint (Graphics& g) override
    {
        g.fillAll (getLookAndFeel().findColour (ResizableWindow::backgroundColourId));
    }

private:
    //== status =================================================================
    void refreshStatus()
    {
        auto* dev = engine.getDeviceManager().deviceManager.getCurrentAudioDevice();
        String s;
        s << "Engine: up    |    Edit: " << (edit != nullptr ? "ready" : "FAILED")
          << "    |    Our instrument: AI Synth (built-in)\n";
        s << "Audio out: " << (dev != nullptr ? dev->getName() : String ("(none open)"))
          << "    |    Tracks: " << (edit != nullptr ? te::getAudioTracks (*edit).size() : 0);
        status.setText (s, dontSendNotification);
    }

    te::AudioTrack* getOrInsertAudioTrackAt (int index)
    {
        edit->ensureNumberOfAudioTracks (index + 1);
        return te::getAudioTracks (*edit)[index];
    }

    //== build the demo: a track, our synth on it, a short MIDI phrase ==========
    void buildDemoIfNeeded()
    {
        if (builtDemo)
            return;

        auto* track = getOrInsertAudioTrackAt (0);
        jassert (track != nullptr);

        // Insert OUR synth as the track's instrument.
        if (auto p = edit->getPluginCache().createNewPlugin (tewk::AISynthPlugin::xmlTypeName, {}))
            track->pluginList.insertPlugin (p, 0, nullptr);

        // 8 beats (2 bars of 4/4) of a Cm chord stab + a little arpeggio on top.
        const auto range = edit->tempoSequence.toTime ({ te::BeatPosition::fromBeats (0.0),
                                                          te::BeatPosition::fromBeats (8.0) });
        if (auto* clip = dynamic_cast<te::MidiClip*> (
                track->insertNewClip (te::TrackItem::Type::midi, "AI Phrase", range, nullptr)))
        {
            auto& seq = clip->getSequence();
            auto* um  = &edit->getUndoManager();

            auto add = [&] (int pitch, double startBeat, double lenBeats, int vel)
            {
                seq.addNote (pitch, te::BeatPosition::fromBeats (startBeat),
                             te::BeatDuration::fromBeats (lenBeats), vel, 0, um);
            };

            // Cm pad (C3 Eb3 G3) held across each bar
            for (double bar = 0.0; bar < 8.0; bar += 4.0)
            {
                add (48, bar, 4.0, 80);   // C3
                add (51, bar, 4.0, 78);   // Eb3
                add (55, bar, 4.0, 78);   // G3
            }
            // arpeggio on top: C4 Eb4 G4 Bb4 ...
            const int arp[] = { 60, 63, 67, 70, 67, 63, 67, 70 };
            for (int i = 0; i < 8; ++i)
                add (arp[i], (double) i, 0.9, 100);
        }

        builtDemo = true;
        refreshStatus();
    }

    void playDemo()
    {
        buildDemoIfNeeded();
        auto& transport = edit->getTransport();
        transport.ensureContextAllocated();
        transport.playFromStart (true);
        info.setText ("Playing 2 bars through the AI Synth. Press Stop to halt.", dontSendNotification);
    }

    void stopPlayback()
    {
        if (edit != nullptr)
            edit->getTransport().stop (false, false);
    }

    void renderWav()
    {
        buildDemoIfNeeded();
        stopPlayback();

        auto out = File::getSpecialLocation (File::userDesktopDirectory)
                       .getChildFile ("AI Workstation - AI Synth.wav");

        const bool ok = te::Renderer::renderToFile (*edit, out, false);

        info.setText (ok ? ("Rendered to: " + out.getFullPathName())
                         : "Render failed.", dontSendNotification);
    }

    //== AU scan (capability check) ============================================
    void startScan()
    {
        if (isThreadRunning())
            return;
        scanButton.setEnabled (false);
        info.setText ("Scanning Audio Units... this can take a moment.\n", dontSendNotification);
        startThread();
    }

    void run() override
    {
        auto& pm = engine.getPluginManager();
        AudioPluginFormat* au = nullptr;
        for (auto* f : pm.pluginFormatManager.getFormats())
            if (f->getName().containsIgnoreCase ("AudioUnit"))
                au = f;

        if (au != nullptr)
        {
            auto dead = engine.getTemporaryFileManager().getTempDirectory().getChildFile ("dead_plugins.txt");
            PluginDirectoryScanner scanner (pm.knownPluginList, *au, au->getDefaultLocationsToSearch(), true, dead, false);
            String nm;
            while (! threadShouldExit() && scanner.scanNextFile (true, nm)) {}
        }

        StringArray instruments;
        for (const auto& d : pm.knownPluginList.getTypes())
            if (d.isInstrument)
                instruments.add (d.name + "   —   " + d.manufacturerName + "   [" + d.pluginFormatName + "]");
        instruments.sort (true);

        Component::SafePointer<MainComponent> safe (this);
        MessageManager::callAsync ([safe, instruments]
        {
            if (safe == nullptr) return;
            safe->info.setText (instruments.isEmpty()
                ? String ("Scan complete — no AU instruments found.")
                : String (instruments.size()) + " AU instrument(s) found:\n\n" + instruments.joinIntoString ("\n"),
                dontSendNotification);
            safe->scanButton.setEnabled (true);
        });
    }

    te::Engine engine { "AI Workstation" };
    std::unique_ptr<te::Edit> edit;
    bool builtDemo = false;

    Label      header, status;
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
