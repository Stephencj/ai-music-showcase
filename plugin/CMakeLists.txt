cmake_minimum_required(VERSION 3.22)
project(AIPartBank VERSION 0.2.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

include(FetchContent)
FetchContent_Declare(
    JUCE
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG 8.0.6
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(JUCE)

set(AIPB_SOURCES Source/PluginProcessor.cpp Source/PluginEditor.cpp)
set(AIPB_DEFS
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)
set(AIPB_LIBS
    juce::juce_audio_utils
    juce::juce_audio_processors)

# --- Audio-FX variant: insert on any channel; WAV playback + drag-out ---------
juce_add_plugin(AIPartBank
    PLUGIN_MANUFACTURER_CODE Aimu
    PLUGIN_CODE Aipb
    FORMATS VST3 AU Standalone
    PRODUCT_NAME "AI Part Bank"
    COMPANY_NAME "Music Producer"
    IS_SYNTH FALSE
    IS_MIDI_EFFECT FALSE
    NEEDS_MIDI_OUTPUT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    COPY_PLUGIN_AFTER_BUILD TRUE)
target_sources(AIPartBank PRIVATE ${AIPB_SOURCES})
target_compile_definitions(AIPartBank PUBLIC ${AIPB_DEFS} AIPG_MIDI_FX=0)
target_link_libraries(AIPartBank PRIVATE ${AIPB_LIBS}
    PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)

# --- MIDI-FX variant: before the instrument; emits notes to play it live ------
juce_add_plugin(AIPartBankMidi
    PLUGIN_MANUFACTURER_CODE Aimu
    PLUGIN_CODE Aipm
    FORMATS VST3 AU
    PRODUCT_NAME "AI Part Bank (MIDI FX)"
    COMPANY_NAME "Music Producer"
    IS_SYNTH FALSE
    IS_MIDI_EFFECT TRUE
    NEEDS_MIDI_INPUT TRUE
    NEEDS_MIDI_OUTPUT TRUE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    COPY_PLUGIN_AFTER_BUILD TRUE)
target_sources(AIPartBankMidi PRIVATE ${AIPB_SOURCES})
target_compile_definitions(AIPartBankMidi PUBLIC ${AIPB_DEFS} AIPG_MIDI_FX=1)
target_link_libraries(AIPartBankMidi PRIVATE ${AIPB_LIBS}
    PUBLIC juce::juce_recommended_config_flags juce::juce_recommended_warning_flags)
