#!/bin/zsh
set -euo pipefail

ROOT="${0:A:h}"
CONFIGURATION="${1:-debug}"

cd "$ROOT"
swift build --configuration "$CONFIGURATION" --product ConnActionFixture
BIN_DIR="$(swift build --configuration "$CONFIGURATION" --show-bin-path)"
APP="$ROOT/.build/fixture/ConnActionFixture.app"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"
cp "$BIN_DIR/ConnActionFixture" "$APP/Contents/MacOS/ConnActionFixture"
cp "$ROOT/Sources/ConnActionFixture/Info.plist" "$APP/Contents/Info.plist"
codesign --force --sign - "$APP"
echo "$APP"
