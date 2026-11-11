#!/bin/zsh
# Rebuilds macos/AppIcon.icns from icon/conn-icon.svg using macOS's own SVG
# renderer (Quick Look), sips and iconutil. make-app.sh copies the result.
set -euo pipefail
cd "$(dirname "$0")"
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
qlmanage -t -s 1024 -o "$work" conn-icon.svg >/dev/null 2>&1
master="$work/conn-icon.svg.png"
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
