#!/bin/zsh
# Build Conn.app from the SwiftPM package. Signs with the persistent
# "Conn Dev Signing" identity when the keychain has one, so TCC grants
# survive rebuilds; ad hoc otherwise (grants die on every install).
set -euo pipefail
cd "$(dirname "$0")"

BETA_DEVELOPER_DIR="/Applications/Xcode-beta.app/Contents/Developer"
XCODE_DEVELOPER_DIR="/Applications/Xcode.app/Contents/Developer"

# A toolchain qualifies only when the manifest compiles AND SwiftUI macros
# expand: older Command Line Tools pass the manifest probe but lack the
# SwiftUIMacros plugin, which otherwise only surfaces as a build failure.
toolchain_ok() {
    local dir="${1:-}"
    local -a run=()
    [[ -n "$dir" ]] && run=(env "DEVELOPER_DIR=$dir")
    "${run[@]}" swift build --version >/dev/null 2>&1 || return 1
    "${run[@]}" swift package describe --type json >/dev/null 2>&1 || return 1
    local probedir
    probedir="$(mktemp -d -t conn-macro-probe)"
    printf 'import SwiftUI\nstruct P: View { @State private var n = 0; var body: some View { Text("p") } }\n' \
        > "$probedir/probe.swift"
    "${run[@]}" swiftc -typecheck "$probedir/probe.swift" >/dev/null 2>&1
    local rc=$?
    rm -rf "$probedir"
    return $rc
}

if toolchain_ok; then
    : # selected toolchain works bare
elif toolchain_ok "$BETA_DEVELOPER_DIR"; then
    export DEVELOPER_DIR="$BETA_DEVELOPER_DIR"
elif toolchain_ok "$XCODE_DEVELOPER_DIR"; then
    export DEVELOPER_DIR="$XCODE_DEVELOPER_DIR"
else
    echo "no Swift toolchain here can build SwiftUI macro code: install full Xcode, or Command Line Tools new enough to ship SwiftUIMacros"
    if [[ -d /Applications/Xcode.app ]]; then
        echo "Xcode.app is present; if its license is unaccepted that alone disqualifies it: sudo xcodebuild -license accept"
    fi
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
