cmake_minimum_required(VERSION 3.22)
project(AIWorkstation VERSION 0.1.0 LANGUAGES C CXX)

# The AI music workstation: our own DAW on Tracktion Engine, so generation is
# native (full read/write of every track) and it hosts the user's AU sounds.
# The engine + its pinned JUCE are vendored (gitignored) under _engine/.

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

if (APPLE)
    set(CMAKE_OSX_DEPLOYMENT_TARGET "10.13" CACHE INTERNAL "")
endif()

set_property(GLOBAL PROPERTY USE_FOLDERS YES)
option(JUCE_ENABLE_MODULE_SOURCE_GROUPS "Enable Module Source Groups" ON)

# Bring in Tracktion's pinned JUCE first, then the tracktion modules (which add
# the tracktion::tracktion_engine / _core / _graph targets via ALIAS_NAMESPACE).
add_subdirectory(_engine/modules/juce ./_juce_build)
add_subdirectory(_engine/modules     ./_tracktion_build)

juce_add_gui_app(AIWorkstation
    PRODUCT_NAME "Music Producer"
    BUNDLE_ID "com.musicproducer.workstation"
    PLUGINHOST_AU TRUE
    MICROPHONE_PERMISSION_ENABLED TRUE
    MICROPHONE_PERMISSION_TEXT "Audio input for recording")

juce_generate_juce_header(AIWorkstation)

target_sources(AIWorkstation PRIVATE Source/Main.cpp)
target_compile_features(AIWorkstation PRIVATE cxx_std_20)

target_compile_definitions(AIWorkstation PRIVATE
    JUCE_PLUGINHOST_AU=1
    JUCE_PLUGINHOST_VST3=1
    JUCE_USE_CURL=0
    JUCE_WEB_BROWSER=0
    JUCE_MODAL_LOOPS_PERMITTED=1
    JUCE_STRICT_REFCOUNTEDPOINTER=1
    TRACKTION_ENABLE_TIMESTRETCH_SOUNDTOUCH=1)

target_link_libraries(AIWorkstation PRIVATE
    tracktion::tracktion_core
    tracktion::tracktion_engine
    tracktion::tracktion_graph
    juce::juce_audio_devices
    juce::juce_audio_processors
    juce::juce_audio_utils
    juce::juce_gui_basics
    juce::juce_recommended_config_flags
    juce::juce_recommended_warning_flags)

if (APPLE)
    target_compile_options(AIWorkstation PRIVATE "-fno-aligned-allocation")
endif()
