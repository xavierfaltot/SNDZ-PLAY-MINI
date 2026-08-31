#!/bin/zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

APP_NAME="SONO PLAY MINI"
ENTRY="run_sndz_mini.py"
ICON_PNG="src/sndz_play_mini/assets/sono_play_mini_logo.png"
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

if [ ! -x "$BUILD_VENV/bin/python" ]; then
  python3 -m venv "$BUILD_VENV"
fi

"$BUILD_VENV/bin/python" -m pip install --upgrade pip
"$BUILD_VENV/bin/python" -m pip install -r requirements.txt pyinstaller

rm -rf build dist release
mkdir -p release

FFMPEG="$(command -v ffmpeg)"
FFPROBE="$(command -v ffprobe)"
FFPLAY="$(command -v ffplay)"

"$BUILD_VENV/bin/pyinstaller" \
  --noconfirm \
  --clean \
  --windowed \
  --name "$APP_NAME" \
  --osx-bundle-identifier "com.faltot.sonoplaymini" \
  --add-data="$ICON_PNG:sndz_play_mini/assets" \
  --add-binary="$FFMPEG:." \
  --add-binary="$FFPROBE:." \
  --add-binary="$FFPLAY:." \
  "$ENTRY"

APP="dist/$APP_NAME.app"
if [ ! -d "$APP" ]; then
  echo "ERROR: PyInstaller did not create $APP"
  exit 1
fi

# Ad-hoc signing reduces macOS bundle-integrity warnings. Public distribution
# without the right-click/Open flow still requires an Apple Developer ID + notarization.
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

echo ""
echo "DONE"
echo "DMG: $ROOT/$DMG"
echo "SHA256: $SHA"
echo ""
echo "Test the DMG on another Mac before publishing it."
echo "For a zero-warning public install, sign with an Apple Developer ID and notarize the app."
