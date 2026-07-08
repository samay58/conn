#!/bin/zsh
# Build Conn.app from the SwiftPM package. Signs with the persistent
# "Conn Dev Signing" identity when the keychain has one, so TCC grants
# survive rebuilds; ad hoc otherwise (grants die on every install).
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
SIGN_IDENTITY="Conn Dev Signing"
if security find-identity -v -p codesigning 2>/dev/null | grep -q "$SIGN_IDENTITY"; then
    codesign --force --sign "$SIGN_IDENTITY" "$APP"
    echo "signed with $SIGN_IDENTITY (TCC grants survive reinstalls)"
else
    codesign --force --sign - "$APP"
    >&2 echo "WARNING: ad hoc signature; macOS resets Conn.app's TCC grants on every install."
    >&2 echo "Create the persistent identity once (see README, Stable signing):"
    >&2 echo "  Keychain Access > Certificate Assistant > Create a Certificate,"
    >&2 echo "  name '$SIGN_IDENTITY', type Code Signing, then rerun make-app.sh"
fi

if [[ "${1:-}" == "install" ]]; then
    rm -rf /Applications/Conn.app
    ditto "$APP" /Applications/Conn.app
    echo "installed /Applications/Conn.app"
else
    echo "built $PWD/$APP"
    echo "./make-app.sh install   puts it in /Applications"
fi
