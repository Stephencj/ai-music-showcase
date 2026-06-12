#!/usr/bin/env bash
# Build the standalone, offline "Dress Up Band" Android app end to end:
#   web bundle → copy into android assets → assemble APK.
# The APK runs fully offline (no Mac, no network) — sideload it onto the
# tablet. Output: android/app/build/outputs/apk/dressup/debug/app-dressup-debug.apk
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"

echo "▸ Building the standalone dress-up web bundle…"
cd "$ROOT/web"
npm run build:dressup

echo "▸ Bundling into the Android app assets…"
rm -rf "$ROOT/android/app/src/main/assets/dressup"
mkdir -p "$ROOT/android/app/src/main/assets/dressup"
cp -r "$ROOT/web/dist-dressup/." "$ROOT/android/app/src/main/assets/dressup/"

echo "▸ Assembling the APK…"
cd "$ROOT/android"
# Android Studio's bundled JDK (no system Java required).
export JAVA_HOME="${JAVA_HOME:-/Applications/Android Studio.app/Contents/jbr/Contents/Home}"
./gradlew assembleDressupDebug

APK="$ROOT/android/app/build/outputs/apk/dressup/debug/app-dressup-debug.apk"
echo "✓ Done: $APK"
ls -lh "$APK"
