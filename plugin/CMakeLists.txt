cmake_minimum_required(VERSION 3.22)
project(AIPartGenerator VERSION 0.1.0 LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# JUCE — fetched (shallow) so there's nothing to vendor. Pin a stable 8.x tag.
include(FetchContent)
FetchContent_Declare(
    JUCE
    GIT_REPOSITORY https://github.com/juce-framework/JUCE.git
    GIT_TAG 8.0.6
    GIT_SHALLOW TRUE
)
FetchContent_MakeAvailable(JUCE)

juce_add_plugin(AIPartGenerator
    PLUGIN_MANUFACTURER_CODE Aimu
    PLUGIN_CODE Aipg
    FORMATS VST3 AU Standalone
    PRODUCT_NAME "AI Part Generator"
    COMPANY_NAME "Music Producer"
    IS_SYNTH TRUE
    NEEDS_MIDI_OUTPUT TRUE
    NEEDS_MIDI_INPUT FALSE
    EDITOR_WANTS_KEYBOARD_FOCUS TRUE
    COPY_PLUGIN_AFTER_BUILD TRUE)

target_sources(AIPartGenerator PRIVATE
    Source/PluginProcessor.cpp
    Source/PluginEditor.cpp)

target_compile_definitions(AIPartGenerator PUBLIC
    JUCE_WEB_BROWSER=0
    JUCE_USE_CURL=0
    JUCE_VST3_CAN_REPLACE_VST2=0
    JUCE_DISPLAY_SPLASH_SCREEN=0)

target_link_libraries(AIPartGenerator PRIVATE
    juce::juce_audio_utils
    juce::juce_audio_processors
    PUBLIC
    juce::juce_recommended_config_flags
    juce::juce_recommended_lto_flags
    juce::juce_recommended_warning_flags)
