#!/bin/zsh
# Build Conn.app from the SwiftPM package. Ad-hoc signed so TCC grants stick.
set -euo pipefail
cd "$(dirname "$0")"

BETA_DEVELOPER_DIR="/Applications/Xcode-beta.app/Contents/Developer"

if swift build --version >/dev/null 2>&1 && swift package describe --type json >/dev/null 2>&1; then
    : # current toolchain works bare (manifest actually compiles)
elif DEVELOPER_DIR="$BETA_DEVELOPER_DIR" swift build --version >/dev/null 2>&1 \
    && DEVELOPER_DIR="$BETA_DEVELOPER_DIR" swift package describe --type json >/dev/null 2>&1; then
    export DEVELOPER_DIR="$BETA_DEVELOPER_DIR"
else
    echo "no working Swift toolchain: install/select Xcode-beta at $BETA_DEVELOPER_DIR or repair Command Line Tools (xcode-select --install)"
    exit 1
fi

swift build -c release

APP="Conn.app"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp .build/release/Conn "$APP/Contents/MacOS/Conn"
cp Info.plist "$APP/Contents/Info.plist"
[[ -f AppIcon.icns ]] && cp AppIcon.icns "$APP/Contents/Resources/AppIcon.icns"
codesign --force --sign - "$APP"

if [[ "${1:-}" == "install" ]]; then
    rm -rf /Applications/Conn.app
    ditto "$APP" /Applications/Conn.app
    echo "installed /Applications/Conn.app"
else
    echo "built $PWD/$APP"
    echo "./make-app.sh install   puts it in /Applications"
fi
