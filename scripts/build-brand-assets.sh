#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE="$ROOT/assets/brand/source"
PORTAL="$ROOT/apps/portal/public"
APP_ICONS="$PORTAL/app-icons"
BRAND="$PORTAL/brand"
API_STATIC="$ROOT/src/ai_billing_audit/static"
MOBILE="$ROOT/apps/mobile/www"

for tool in rsvg-convert magick; do
  command -v "$tool" >/dev/null || {
    echo "missing required renderer: $tool" >&2
    exit 1
  }
done

mkdir -p "$APP_ICONS" "$BRAND"
cp "$SOURCE"/zorva-{mark,mark-dark,wordmark-light,wordmark-dark,lockup-light,lockup-dark}.svg "$BRAND"/
cp "$SOURCE/zorva-mark.svg" "$PORTAL/icon.svg"
cp "$SOURCE/zorva-mark-dark.svg" "$PORTAL/icon-dark.svg"

for size in 16 32 48; do
  rsvg-convert -w "$size" -h "$size" "$SOURCE/zorva-mark-dark.svg" -o "$PORTAL/favicon-${size}x${size}.png"
done
magick "$PORTAL/favicon-16x16.png" "$PORTAL/favicon-32x32.png" "$PORTAL/favicon-48x48.png" "$PORTAL/favicon.ico"

ios_sizes=(1024 180 167 152 120 87 80 60 58 40 29)
android_sizes=(192 512)
macos_sizes=(16 32 64 128 256 512 1024)

for size in "${ios_sizes[@]}"; do
  rsvg-convert -w "$size" -h "$size" "$SOURCE/zorva-app-icon.svg" -o "$APP_ICONS/ios-${size}.png"
done
for size in "${android_sizes[@]}"; do
  rsvg-convert -w "$size" -h "$size" "$SOURCE/zorva-app-icon.svg" -o "$APP_ICONS/android-${size}.png"
done
for size in "${macos_sizes[@]}"; do
  rsvg-convert -w "$size" -h "$size" "$SOURCE/zorva-app-icon.svg" -o "$APP_ICONS/macos-${size}.png"
done
rsvg-convert -w 432 -h 432 "$SOURCE/zorva-app-icon.svg" -o "$APP_ICONS/android-adaptive-foreground.png"
rsvg-convert -w 432 -h 432 "$SOURCE/zorva-adaptive-background.svg" -o "$APP_ICONS/android-adaptive-background.png"

cp "$SOURCE/zorva-mark-dark.svg" "$MOBILE/zorva-mark.svg"
cp "$SOURCE/zorva-mark-dark.svg" "$API_STATIC/favicon.svg"
cp "$PORTAL/favicon-32x32.png" "$API_STATIC/favicon-32.png"
cp "$PORTAL/favicon.ico" "$API_STATIC/favicon.ico"
cp "$APP_ICONS/ios-180.png" "$API_STATIC/apple-touch-icon.png"

find "$BRAND" "$APP_ICONS" -type f -exec chmod 644 {} +
chmod 644 "$PORTAL"/icon*.svg "$PORTAL"/favicon* "$MOBILE/zorva-mark.svg" "$API_STATIC"/favicon*

echo "Brand assets generated from $SOURCE"
