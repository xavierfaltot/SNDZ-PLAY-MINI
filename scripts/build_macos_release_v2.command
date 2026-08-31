#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="SONO PLAY MINI"
ENTRY="run_sndz_mini.py"
ICON_PNG="src/sndz_play_mini/assets/sono_play_mini_logo.png"
ICONSET=".build-sono-icon.iconset"
ICON_ICNS=".build-sono-icon.icns"
BUILD_VENV=".build-venv"

export PATH="/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:/usr/bin:/bin:$PATH"

echo "==> SONO PLAY MINI — macOS release"

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 is required."
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 || ! command -v ffprobe >/dev/null 2>&1 || ! command -v ffplay >/dev/null 2>&1; then
  echo "ERROR: ffmpeg, ffprobe and ffplay are required to build the standalone app."
  echo "Install FFmpeg first (for example with Homebrew: brew install ffmpeg), then run this script again."
  exit 1
fi

if [ ! -f "$ICON_PNG" ]; then
  echo "ERROR: missing SONO PLAY MINI logo: $ICON_PNG"
  exit 1
fi

if [ ! -x "$BUILD_VENV/bin/python" ]; then
  python3 -m venv "$BUILD_VENV"
fi

"$BUILD_VENV/bin/python" -m pip install --upgrade pip
"$BUILD_VENV/bin/python" -m pip install -r requirements.txt pyinstaller

rm -rf build dist release "$ICONSET" "$ICON_ICNS"
mkdir -p release "$ICONSET"

# Build a native macOS .icns from the exact SONO PLAY MINI logo used in-app.
sips -z 16 16 "$ICON_PNG" --out "$ICONSET/icon_16x16.png" >/dev/null
sips -z 32 32 "$ICON_PNG" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
sips -z 32 32 "$ICON_PNG" --out "$ICONSET/icon_32x32.png" >/dev/null
sips -z 64 64 "$ICON_PNG" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
sips -z 128 128 "$ICON_PNG" --out "$ICONSET/icon_128x128.png" >/dev/null
sips -z 256 256 "$ICON_PNG" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
sips -z 256 256 "$ICON_PNG" --out "$ICONSET/icon_256x256.png" >/dev/null
sips -z 512 512 "$ICON_PNG" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
sips -z 512 512 "$ICON_PNG" --out "$ICONSET/icon_512x512.png" >/dev/null
sips -z 1024 1024 "$ICON_PNG" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
iconutil -c icns "$ICONSET" -o "$ICON_ICNS"

FFMPEG="$(command -v ffmpeg)"
FFPROBE="$(command -v ffprobe)"
FFPLAY="$(command -v ffplay)"

"$BUILD_VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "com.faltot.sonoplaymini" \
  --icon "$ICON_ICNS" \
  --paths "$ROOT/src" \
  --collect-submodules sndz_play_mini \
  --collect-data sndz_play_mini \
  --hidden-import sndz_play_mini.global_bpm \
  --add-binary="$FFMPEG:." \
  --add-binary="$FFPROBE:." \
  --add-binary="$FFPLAY:." \
  "$ENTRY"

APP="dist/$APP_NAME.app"
if [ ! -d "$APP" ]; then
  echo "ERROR: PyInstaller did not create $APP"
  exit 1
fi

codesign --force --deep --sign - "$APP"

DMG="release/SONO-PLAY-MINI-macOS.dmg"
rm -f "$DMG"
hdiutil create \
  -volname "$APP_NAME" \
  -srcfolder "$APP" \
  -ov \
  -format UDZO \
  "$DMG"

SHA="$(shasum -a 256 "$DMG" | awk '{print $1}')"
printf "%s  %s\n" "$SHA" "$(basename "$DMG")" > release/SHA256.txt

rm -rf "$ICONSET" "$ICON_ICNS"

echo ""
echo "DONE"
echo "DMG: $ROOT/$DMG"
echo "SHA256: $SHA"
echo ""
echo "The app now bundles the SONO PLAY MINI logo and uses it as the macOS app icon."
echo "Test the DMG on another Mac before publishing it."
echo "For a zero-warning public install, sign with an Apple Developer ID and notarize the app."
