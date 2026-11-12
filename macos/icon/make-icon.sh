#!/bin/zsh
# Rebuilds macos/AppIcon.icns from icon/conn-icon.svg using AppKit's SVG
# renderer (render-svg.swift keeps transparency; Quick Look painted the
# corners white), sips and iconutil. make-app.sh copies the result.
set -euo pipefail
cd "$(dirname "$0")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
master="$work/conn-icon.png"
swift render-svg.swift conn-icon.svg "$master" 1024
[[ -s $master ]] || { echo "render failed" >&2; exit 1; }
set_dir="$work/AppIcon.iconset"
mkdir "$set_dir"
for size in 16 32 128 256 512; do
    sips -z $size $size "$master" --out "$set_dir/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z $double $double "$master" --out "$set_dir/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$set_dir" -o ../AppIcon.icns
echo "wrote macos/AppIcon.icns"
