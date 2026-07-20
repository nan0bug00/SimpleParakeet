#!/usr/bin/env bash
# Fetches a portable LGPL static ffmpeg into bin/ (Linux x64).
# Source: BtbN/FFmpeg-Builds linux64-lgpl (no GPL-only codecs).
# Does NOT start servers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/bin"
TMP="$ROOT/build/ffmpeg-dl"
URL="${1:-https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-linux64-lgpl.tar.xz}"

mkdir -p "$BIN" "$TMP"
ARCHIVE="$TMP/ffmpeg.tar.xz"

echo "Downloading ffmpeg (BtbN linux64-lgpl)..."
echo "  $URL"
curl -fsSL --retry 3 -o "$ARCHIVE" "$URL"

rm -rf "$TMP/extract"
mkdir -p "$TMP/extract"
tar -xJf "$ARCHIVE" -C "$TMP/extract"

FFMPEG="$(find "$TMP/extract" -type f -name ffmpeg | head -n 1 || true)"
if [[ -z "$FFMPEG" || ! -f "$FFMPEG" ]]; then
  echo "ffmpeg not found inside archive" >&2
  exit 1
fi

cp -f "$FFMPEG" "$BIN/ffmpeg"
chmod +x "$BIN/ffmpeg"

LICENSE_DIR="$ROOT/licenses"
mkdir -p "$LICENSE_DIR"
# Best-effort license texts from the tarball
while IFS= read -r -d '' f; do
  base="$(basename "$f")"
  cp -f "$f" "$LICENSE_DIR/ffmpeg-$base" 2>/dev/null || true
done < <(find "$TMP/extract" -type f \( -iname 'LICENSE*' -o -iname 'COPYING*' -o -iname 'README*' \) -print0 2>/dev/null | head -z -n 8)

cat >"$LICENSE_DIR/NOTICE-ffmpeg.txt" <<'EOF'
This folder may include a portable FFmpeg binary (ffmpeg) from
BtbN/FFmpeg-Builds linux64-lgpl (static LGPL build).

FFmpeg is licensed under the LGPL (and optionally GPL for some builds).
The lgpl variant omits GPL-only libraries. Keep FFmpeg as a separate
executable (mere aggregation with the MIT-licensed shim / parakeet.cpp).

Upstream: https://ffmpeg.org/
Linux builds used by the fetch script: https://github.com/BtbN/FFmpeg-Builds
EOF

echo "Installed $BIN/ffmpeg"
