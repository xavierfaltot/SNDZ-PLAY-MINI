#!/bin/zsh
set -e

APP_NAME="${SONO_DESKTOP_APP_NAME:-SONO PLAY MINI}"
BUNDLE_IDENTIFIER="${SONO_BUNDLE_IDENTIFIER:-com.rushoperator.sonoplaymini}"
REPO_DIR="${0:A:h:h}"
APP_DIR="$HOME/Desktop/$APP_NAME.app"

mkdir -p "$APP_DIR/Contents/MacOS" "$APP_DIR/Contents/Resources"
ICON_SOURCE="$REPO_DIR/src/sndz_play_mini/assets/sono_play_mini_logo.png"
ICON_FILE="SONO_PLAY_MINI.png"
cp "$ICON_SOURCE" "$APP_DIR/Contents/Resources/$ICON_FILE"

if command -v sips >/dev/null 2>&1 && command -v iconutil >/dev/null 2>&1; then
  ICONSET="$APP_DIR/Contents/Resources/SONO_PLAY_MINI.iconset"
  mkdir -p "$ICONSET"
  sips -z 16 16 "$ICON_SOURCE" --out "$ICONSET/icon_16x16.png" >/dev/null
  sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET/icon_16x16@2x.png" >/dev/null
  sips -z 32 32 "$ICON_SOURCE" --out "$ICONSET/icon_32x32.png" >/dev/null
  sips -z 64 64 "$ICON_SOURCE" --out "$ICONSET/icon_32x32@2x.png" >/dev/null
  sips -z 128 128 "$ICON_SOURCE" --out "$ICONSET/icon_128x128.png" >/dev/null
  sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET/icon_128x128@2x.png" >/dev/null
  sips -z 256 256 "$ICON_SOURCE" --out "$ICONSET/icon_256x256.png" >/dev/null
  sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET/icon_256x256@2x.png" >/dev/null
  sips -z 512 512 "$ICON_SOURCE" --out "$ICONSET/icon_512x512.png" >/dev/null
  sips -z 1024 1024 "$ICON_SOURCE" --out "$ICONSET/icon_512x512@2x.png" >/dev/null
  iconutil -c icns "$ICONSET" -o "$APP_DIR/Contents/Resources/SONO_PLAY_MINI.icns"
  ICON_FILE="SONO_PLAY_MINI.icns"
fi

cat > "$APP_DIR/Contents/MacOS/$APP_NAME" <<SCRIPT
#!/bin/zsh
set -e
cd "$REPO_DIR"
export PATH="/opt/homebrew/bin:/usr/local/bin:/opt/local/bin:/usr/bin:/bin:\$PATH"
if [ ! -x ".venv/bin/python" ]; then
  python3 -m venv .venv
fi
if ! ".venv/bin/python" -c "import PySide6.QtWidgets" >/dev/null 2>&1; then
  ".venv/bin/python" -m pip install -r requirements.txt
fi
exec ".venv/bin/python" run_sndz_mini.py
SCRIPT
chmod +x "$APP_DIR/Contents/MacOS/$APP_NAME"

cat > "$APP_DIR/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDisplayName</key>
  <string>$APP_NAME</string>
  <key>CFBundleExecutable</key>
  <string>$APP_NAME</string>
  <key>CFBundleIconFile</key>
  <string>$ICON_FILE</string>
  <key>CFBundleIdentifier</key>
  <string>$BUNDLE_IDENTIFIER</string>
  <key>CFBundleName</key>
  <string>$APP_NAME</string>
  <key>CFBundlePackageType</key>
  <string>APPL</string>
  <key>LSMinimumSystemVersion</key>
  <string>12.0</string>
  <key>NSHighResolutionCapable</key>
  <true/>
</dict>
</plist>
PLIST

touch "$APP_DIR"
echo "Created $APP_DIR"
