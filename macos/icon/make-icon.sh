#!/bin/zsh
# Rebuilds macos/AppIcon.icns from icon/conn-icon.svg using AppKit's SVG
# renderer (render-svg.swift keeps transparency; Quick Look painted the
# corners white) and iconutil. make-app.sh copies the result.
# Each size is drawn from the vector itself, never shrunk from a big bitmap,
# so edges land on the pixel grid at 16 px as well as at 1024 px.
set -euo pipefail
cd "$(dirname "$0")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
swiftc -O render-svg.swift -o "$work/render-svg" 2>/dev/null
set_dir="$work/AppIcon.iconset"
mkdir "$set_dir"
for size in 16 32 128 256 512; do
    "$work/render-svg" conn-icon.svg "$set_dir/icon_${size}x${size}.png" $size
    "$work/render-svg" conn-icon.svg "$set_dir/icon_${size}x${size}@2x.png" $((size * 2))
done
for f in "$set_dir"/*.png; do [[ -s $f ]] || { echo "render failed: $f" >&2; exit 1; }; done
iconutil -c icns "$set_dir" -o ../AppIcon.icns
echo "wrote macos/AppIcon.icns"
