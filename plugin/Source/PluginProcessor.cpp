#include "PluginProcessor.h"
#include "PluginEditor.h"

AIPartGeneratorProcessor::AIPartGeneratorProcessor()
    : juce::AudioProcessor (BusesProperties()
          .withOutput ("Output", juce::AudioChannelSet::stereo(), true))
{
}

juce::AudioProcessorEditor* AIPartGeneratorProcessor::createEditor()
{
    return new AIPartGeneratorEditor (*this);
}

// --- state (so settings persist with the project) --------------------------
void AIPartGeneratorProcessor::getStateInformation (juce::MemoryBlock& dest)
{
    auto* o = new juce::DynamicObject();
    o->setProperty ("serverBase", serverBase);
    o->setProperty ("target", target);
    o->setProperty ("key", key);
    o->setProperty ("scale", scale);
    o->setProperty ("genre", genre);
    o->setProperty ("progression", progression);
    o->setProperty ("tempo", tempo);
    o->setProperty ("bars", bars);
    o->setProperty ("voicing", voicing);
    o->setProperty ("chordRhythm", chordRhythm);
    o->setProperty ("bassPattern", bassPattern);
    o->setProperty ("drumPattern", drumPattern);
    o->setProperty ("melodyStyle", melodyStyle);
    o->setProperty ("phraseShape", phraseShape);
    const auto s = juce::JSON::toString (juce::var (o));
    dest.replaceAll (s.toRawUTF8(), s.getNumBytesAsUTF8());
}

void AIPartGeneratorProcessor::setStateInformation (const void* data, int sizeInBytes)
{
    const auto v = juce::JSON::parse (juce::String::fromUTF8 ((const char*) data, sizeInBytes));
    if (auto* o = v.getDynamicObject())
    {
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
    }
}

// --- generation ------------------------------------------------------------
static juce::File downloadTo (const juce::URL& url, const juce::File& dest)
{
    auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress)
                    .withConnectionTimeoutMs (60000);
    std::unique_ptr<juce::InputStream> in (url.createInputStream (opts));
    if (in == nullptr)
        return {};
    dest.deleteFile();
    if (auto out = std::unique_ptr<juce::FileOutputStream> (dest.createOutputStream()))
    {
        out->writeFromInputStream (*in, -1);
        out->flush();
        return dest;
    }
    return {};
}

AIPartGeneratorProcessor::GenResult AIPartGeneratorProcessor::generate()
{
    GenResult r;

    // Build the request body.
    auto* body = new juce::DynamicObject();
    body->setProperty ("target", target);
    body->setProperty ("key", key);
    body->setProperty ("scale", scale);
    body->setProperty ("tempo", tempo);
    body->setProperty ("bars", bars);
    body->setProperty ("output", "both");
    if (genre.isNotEmpty())
        body->setProperty ("genre", genre);

    // Per-part modifiers (the backend applies only those relevant to `target`).
    auto addIf = [body] (const char* k, const juce::String& v)
        { if (v.isNotEmpty()) body->setProperty (k, v); };
    addIf ("voicing", voicing);
    addIf ("chord_rhythm", chordRhythm);
    addIf ("bass_pattern", bassPattern);
    addIf ("drum_pattern", drumPattern);
    addIf ("melody_style", melodyStyle);
    addIf ("phrase_shape", phraseShape);

    juce::Array<juce::var> prog;
    for (auto& tok : juce::StringArray::fromTokens (progression, " ,", ""))
        if (tok.trim().isNotEmpty())
            prog.add (tok.trim());
    if (! prog.isEmpty())
        body->setProperty ("progression", prog);

    const auto payload = juce::JSON::toString (juce::var (body));

    juce::URL url = juce::URL (serverBase + "/api/generate-part").withPOSTData (payload);
    auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inPostData)
                    .withExtraHeaders ("Content-Type: application/json")
                    .withConnectionTimeoutMs (120000);
    std::unique_ptr<juce::InputStream> stream (url.createInputStream (opts));
    if (stream == nullptr)
    {
        r.message = "Could not reach the backend at " + serverBase
                    + " — is Music Producer running?";
        return r;
    }

    const auto response = stream->readEntireStreamAsString();
    const auto parsed = juce::JSON::parse (response);
    auto* obj = parsed.getDynamicObject();
    if (obj == nullptr || ! obj->hasProperty ("notes"))
    {
        r.message = "Unexpected response: " + response.substring (0, 200);
        return r;
    }

    r.nNotes = (int) obj->getProperty ("n_notes");

    auto tmp = juce::File::getSpecialLocation (juce::File::tempDirectory)
                   .getChildFile ("AIPartGenerator");
    tmp.createDirectory();
    const auto stamp = juce::String (juce::Time::currentTimeMillis());

    if (obj->hasProperty ("midi_url"))
    {
        const auto midiUrl = serverBase + obj->getProperty ("midi_url").toString();
        const auto f = tmp.getChildFile ("part_" + stamp + ".mid");
        r.midiFile = downloadTo (juce::URL (midiUrl), f);
    }
    if (obj->hasProperty ("wav_url"))
    {
        const auto wavUrl = serverBase + obj->getProperty ("wav_url").toString();
        const auto ext = wavUrl.endsWith (".mp3") ? ".mp3" : ".wav";
        const auto f = tmp.getChildFile ("part_" + stamp + ext);
        r.wavFile = downloadTo (juce::URL (wavUrl), f);
    }

    r.ok = r.midiFile.existsAsFile() || r.wavFile.existsAsFile();
    r.message = r.ok ? ("Generated " + juce::String (r.nNotes) + " notes — drag onto a track.")
                     : "Generation returned no artifacts.";
    return r;
}

juce::var AIPartGeneratorProcessor::fetchOptions()
{
    juce::URL url (serverBase + "/api/part-options");
    auto opts = juce::URL::InputStreamOptions (juce::URL::ParameterHandling::inAddress)
                    .withConnectionTimeoutMs (15000);
    std::unique_ptr<juce::InputStream> s (url.createInputStream (opts));
    if (s == nullptr)
        return {};
    return juce::JSON::parse (s->readEntireStreamAsString());
}

// JUCE plugin entry point.
juce::AudioProcessor* JUCE_CALLTYPE createPluginFilter()
{
    return new AIPartGeneratorProcessor();
}
