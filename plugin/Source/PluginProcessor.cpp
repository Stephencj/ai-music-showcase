#include "PluginProcessor.h"
#include "PluginEditor.h"

AIPartBankProcessor::AIPartBankProcessor()
#if AIPG_MIDI_FX
    : juce::AudioProcessor (BusesProperties())          // MIDI effect: no audio buses
#else
    : juce::AudioProcessor (BusesProperties()
          .withInput  ("In",  juce::AudioChannelSet::stereo(), true)
          .withOutput ("Out", juce::AudioChannelSet::stereo(), true))
#endif
{
    formatManager.registerBasicFormats();
}

AIPartBankProcessor::~AIPartBankProcessor()
{
    transport.setSource (nullptr);
}

juce::File AIPartBankProcessor::bankDir()
{
    auto d = juce::File::getSpecialLocation (juce::File::userApplicationDataDirectory)
                 .getChildFile ("AI Part Bank");
    d.createDirectory();
    return d;
}

juce::AudioProcessorEditor* AIPartBankProcessor::createEditor()
{
    return new AIPartBankEditor (*this);
}

// --- audio plumbing --------------------------------------------------------
void AIPartBankProcessor::prepareToPlay (double sr, int samplesPerBlock)
{
    sampleRate = sr;
    transport.prepareToPlay (samplesPerBlock, sr);
    scratch.setSize (2, samplesPerBlock);
}

void AIPartBankProcessor::releaseResources()
{
    transport.releaseResources();
}

void AIPartBankProcessor::processBlock (juce::AudioBuffer<float>& buffer, juce::MidiBuffer& midi)
{
    if (auto* ph = getPlayHead())
        if (auto p = ph->getPosition())
        {
            if (p->getBpm().hasValue() && *p->getBpm() > 0.0) hostBpmA.store (*p->getBpm());
            if (auto tsig = p->getTimeSignature())
                { hostNumA.store (tsig->numerator); hostDenomA.store (tsig->denominator); }
        }
#if AIPG_MIDI_FX
    juce::ignoreUnused (buffer);
    auto* ph = getPlayHead();
    auto pos = ph != nullptr ? ph->getPosition() : juce::Optional<juce::AudioPlayHead::PositionInfo>();
    const bool playing = pos.hasValue() && pos->getIsPlaying();
    if (playing && loopBeats > 0.0)
    {
        const double bpm = (pos->getBpm().hasValue() && *pos->getBpm() > 0) ? *pos->getBpm() : tempo;
        const double ppq = pos->getPpqPosition().hasValue() ? *pos->getPpqPosition() : 0.0;
        const double beatsPerSec = bpm / 60.0;
        const int n = buffer.getNumSamples();
        const double b0 = ppq, b1 = ppq + (n / sampleRate) * beatsPerSec;
        const juce::ScopedLock sl (emitLock);
        for (const auto& ev : armedEvents)
        {
            double k = std::floor ((b0 - ev.beat) / loopBeats);
            for (;; ++k)
            {
                const double t = ev.beat + k * loopBeats;
                if (t >= b1) break;
                if (t >= b0)
                {
                    const int off = juce::jlimit (0, n - 1, (int) ((t - b0) / beatsPerSec * sampleRate));
                    midi.addEvent (ev.noteOn ? juce::MidiMessage::noteOn (1, ev.pitch, (juce::uint8) 100)
                                             : juce::MidiMessage::noteOff (1, ev.pitch), off);
                }
            }
        }
    }
    else if (wasPlaying)
    {
        midi.addEvent (juce::MidiMessage::allNotesOff (1), 0);   // clean up on stop
    }
    wasPlaying = playing;
#else
    // Audio-FX: pass the channel's audio through; layer the auditioned WAV on top.
    if (transport.isPlaying())
    {
        const int n = buffer.getNumSamples();
        scratch.setSize (2, n, false, false, true);
        scratch.clear();
        juce::AudioSourceChannelInfo info (&scratch, 0, n);
        transport.getNextAudioBlock (info);
        for (int ch = 0; ch < buffer.getNumChannels(); ++ch)
            buffer.addFrom (ch, 0, scratch, juce::jmin (ch, scratch.getNumChannels() - 1), 0, n);
    }
    juce::ignoreUnused (midi);
#endif
}

// --- auditioning -----------------------------------------------------------
void AIPartBankProcessor::playItem (const BankItem& item)
{
    stopPlayback();
    if (! item.wavFile.existsAsFile())
        return;
    if (auto* reader = formatManager.createReaderFor (item.wavFile))
    {
        readerSource = std::make_unique<juce::AudioFormatReaderSource> (reader, true);
        transport.setSource (readerSource.get(), 0, nullptr, reader->sampleRate);
        transport.setPosition (0.0);
        transport.start();
    }
}

void AIPartBankProcessor::armItem (const BankItem* item)
{
    std::vector<MidiEv> evs;
    double loop = 0.0;
    if (item != nullptr)
    {
        for (const auto& n : item->notes)
        {
            evs.push_back ({ n.startBeat, true,  n.pitch });
            evs.push_back ({ n.startBeat + n.durBeat, false, n.pitch });
            loop = juce::jmax (loop, n.startBeat + n.durBeat);
        }
        // round the loop length up to a whole bar so it repeats musically
        const double bar = juce::jmax (1, item->beatsPerBar);
        loop = std::ceil (loop / bar) * bar;
    }
    const juce::ScopedLock sl (emitLock);
    armedEvents = std::move (evs);
    loopBeats = loop;
}

void AIPartBankProcessor::stopPlayback()
{
    transport.stop();
    transport.setSource (nullptr);
    readerSource.reset();
}

bool AIPartBankProcessor::isPlaying() const { return transport.isPlaying(); }

// --- generation ------------------------------------------------------------
static juce::File downloadTo (const juce::URL& url, const juce::File& dest)
{
    auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress)
                    .withConnectionTimeoutMs (60000);
    std::unique_ptr<juce::InputStream> in (url.createInputStream (opts));
    if (in == nullptr) return {};
    dest.deleteFile();
    if (auto out = std::unique_ptr<juce::FileOutputStream> (dest.createOutputStream()))
    {
        out->writeFromInputStream (*in, -1);
        out->flush();
        return dest;
    }
    return {};
}

AIPartBankProcessor::GenResult AIPartBankProcessor::generate()
{
    GenResult r;
    auto* body = new juce::DynamicObject();
    body->setProperty ("target", target);
    body->setProperty ("key", key);
    body->setProperty ("scale", scale);
    body->setProperty ("tempo", tempo);
    body->setProperty ("bars", bars);
    body->setProperty ("output", "both");
    body->setProperty ("time_signature", juce::Array<juce::var> { tsNum, tsDenom });
    if (genre.isNotEmpty()) body->setProperty ("genre", genre);
    auto addIf = [body] (const char* k, const juce::String& v) { if (v.isNotEmpty()) body->setProperty (k, v); };
    addIf ("voicing", voicing);       addIf ("chord_rhythm", chordRhythm);
    addIf ("bass_pattern", bassPattern); addIf ("drum_pattern", drumPattern);
    addIf ("melody_style", melodyStyle); addIf ("phrase_shape", phraseShape);
    if (octave > 0)       body->setProperty ("octave", octave);
    if (noteDensity > 0.0) body->setProperty ("note_density", noteDensity);
    juce::Array<juce::var> prog;
    for (auto& tok : juce::StringArray::fromTokens (progression, " ,", ""))
        if (tok.trim().isNotEmpty()) prog.add (tok.trim());
    if (! prog.isEmpty()) body->setProperty ("progression", prog);

    const juce::String endpoint = (target == "arrangement") ? "/api/generate-arrangement"
                                                            : "/api/generate-part";
    juce::URL url = juce::URL (serverBase + endpoint).withPOSTData (juce::JSON::toString (juce::var (body)));
    auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inPostData)
                    .withExtraHeaders ("Content-Type: application/json").withConnectionTimeoutMs (120000);
    std::unique_ptr<juce::InputStream> stream (url.createInputStream (opts));
    if (stream == nullptr)
    {
        r.message = "Can't reach the backend at " + serverBase + " — is Music Producer running?";
        return r;
    }
    const auto parsed = juce::JSON::parse (stream->readEntireStreamAsString());
    auto* obj = parsed.getDynamicObject();
    if (obj == nullptr || ! obj->hasProperty ("notes")) { r.message = "Unexpected response from backend."; return r; }

    auto item = std::make_unique<BankItem>();
    item->id = juce::String (juce::Time::currentTimeMillis());
    item->target = target;
    item->tempo = obj->hasProperty ("tempo") ? (double) obj->getProperty ("tempo") : tempo;
    if (auto* ts = obj->getProperty ("time_signature").getArray(); ts != nullptr && ts->size() >= 1)
        item->beatsPerBar = (int) (*ts)[0];
    item->nNotes = (int) obj->getProperty ("n_notes");
    if (auto* arr = obj->getProperty ("notes").getArray())
        for (auto& v : *arr)
            if (auto* na = v.getArray(); na != nullptr && na->size() >= 3)
                item->notes.push_back ({ (int) (*na)[0], (double) (*na)[1], (double) (*na)[2] });

    const auto modifier = (target == "chords") ? (voicing + "/" + chordRhythm)
                        : (target == "bass")   ? bassPattern
                        : (target == "drums")  ? drumPattern
                        : (melodyStyle + "/" + phraseShape);
    item->label = target + " · " + key + " " + scale + " · " + juce::String (bars) + "bar"
                + (modifier.isNotEmpty() && modifier != "/" ? " · " + modifier : juce::String())
                + " · " + juce::String (item->nNotes) + "n";

    if (obj->hasProperty ("midi_url"))
        item->midiFile = downloadTo (juce::URL (serverBase + obj->getProperty ("midi_url").toString()),
                                     bankDir().getChildFile (item->id + ".mid"));
    if (obj->hasProperty ("wav_url"))
    {
        const auto u = serverBase + obj->getProperty ("wav_url").toString();
        item->wavFile = downloadTo (juce::URL (u), bankDir().getChildFile (item->id + (u.endsWith (".mp3") ? ".mp3" : ".wav")));
    }
    r.ok = item->midiFile.existsAsFile() || item->wavFile.existsAsFile();
    r.message = r.ok ? "Added to bank." : "Generation returned no artifacts.";
    r.item = std::move (item);
    return r;
}

juce::var AIPartBankProcessor::fetchOptions()
{
    juce::URL url (serverBase + "/api/part-options");
    std::unique_ptr<juce::InputStream> s (url.createInputStream (
        juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress).withConnectionTimeoutMs (15000)));
    return s == nullptr ? juce::var() : juce::JSON::parse (s->readEntireStreamAsString());
}

// --- state (settings + the bank persist with the project) ------------------
void AIPartBankProcessor::getStateInformation (juce::MemoryBlock& dest)
{
    auto* o = new juce::DynamicObject();
    o->setProperty ("serverBase", serverBase);
    o->setProperty ("target", target);   o->setProperty ("key", key);
    o->setProperty ("scale", scale);     o->setProperty ("genre", genre);
    o->setProperty ("progression", progression);
    o->setProperty ("tempo", tempo);     o->setProperty ("bars", bars);
    o->setProperty ("voicing", voicing); o->setProperty ("chordRhythm", chordRhythm);
    o->setProperty ("bassPattern", bassPattern); o->setProperty ("drumPattern", drumPattern);
    o->setProperty ("melodyStyle", melodyStyle); o->setProperty ("phraseShape", phraseShape);

    juce::Array<juce::var> items;
    for (auto* it : bank)
    {
        auto* io = new juce::DynamicObject();
        io->setProperty ("id", it->id);    io->setProperty ("label", it->label);
        io->setProperty ("target", it->target); io->setProperty ("tempo", it->tempo);
        io->setProperty ("beatsPerBar", it->beatsPerBar); io->setProperty ("nNotes", it->nNotes);
        io->setProperty ("midi", it->midiFile.getFullPathName());
        io->setProperty ("wav", it->wavFile.getFullPathName());
        juce::Array<juce::var> ns;
        for (auto& n : it->notes) ns.add (juce::Array<juce::var> { n.pitch, n.startBeat, n.durBeat });
        io->setProperty ("notes", ns);
        items.add (juce::var (io));
    }
    o->setProperty ("bank", items);
    const auto s = juce::JSON::toString (juce::var (o));
    dest.replaceAll (s.toRawUTF8(), s.getNumBytesAsUTF8());
}

void AIPartBankProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    const auto v = juce::JSON::parse (juce::String::fromUTF8 ((const char*) data, sizeInBytes));
    auto* o = v.getDynamicObject();
    if (o == nullptr) return;
    serverBase  = o->getProperty ("serverBase").toString();
    target      = o->getProperty ("target").toString();
    key         = o->getProperty ("key").toString();
    scale       = o->getProperty ("scale").toString();
    genre       = o->getProperty ("genre").toString();
    progression = o->getProperty ("progression").toString();
    tempo       = (double) o->getProperty ("tempo");
    bars        = (int) o->getProperty ("bars");
    voicing     = o->getProperty ("voicing").toString();
    chordRhythm = o->getProperty ("chordRhythm").toString();
    bassPattern = o->getProperty ("bassPattern").toString();
    drumPattern = o->getProperty ("drumPattern").toString();
    melodyStyle = o->getProperty ("melodyStyle").toString();
    phraseShape = o->getProperty ("phraseShape").toString();

    bank.clear();
    if (auto* arr = o->getProperty ("bank").getArray())
        for (auto& iv : *arr)
            if (auto* io = iv.getDynamicObject())
            {
                auto it = std::make_unique<BankItem>();
                it->id = io->getProperty ("id").toString();
                it->label = io->getProperty ("label").toString();
                it->target = io->getProperty ("target").toString();
                it->tempo = (double) io->getProperty ("tempo");
                it->beatsPerBar = (int) io->getProperty ("beatsPerBar");
                it->nNotes = (int) io->getProperty ("nNotes");
                it->midiFile = juce::File (io->getProperty ("midi").toString());
                it->wavFile  = juce::File (io->getProperty ("wav").toString());
                if (auto* ns = io->getProperty ("notes").getArray())
                    for (auto& nv : *ns)
                        if (auto* na = nv.getArray(); na != nullptr && na->size() >= 3)
                            it->notes.push_back ({ (int) (*na)[0], (double) (*na)[1], (double) (*na)[2] });
                bank.add (it.release());
            }
}

juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new AIPartBankProcessor();
}
