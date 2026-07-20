#!/usr/bin/env bash
# Builds bin/SimpleParakeet/SimpleParakeet with PyInstaller --onedir (no UPX).
# Does NOT start servers. Does NOT download the GGUF.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/src"
BIN="$ROOT/bin"
WORK="$ROOT/build"
OUT_DIR="$BIN/SimpleParakeet"
PYTHON="${1:-${PYTHON:-python3}}"

if ! command -v "$PYTHON" >/dev/null 2>&1 && [[ ! -x "$PYTHON" ]]; then
  echo "Python not found. Pass path as first arg or set PYTHON=." >&2
  exit 1
fi

echo "Using $PYTHON"
"$PYTHON" -m pip install -r "$SRC/requirements.txt"
"$PYTHON" -m pip install "pyinstaller>=6.0"

mkdir -p "$BIN" "$WORK"
rm -rf "$OUT_DIR"

ENTRY="$SRC/server.py"
(
  cd "$SRC"
  "$PYTHON" -m PyInstaller \
    --noconfirm \
    --clean \
    --onedir \
    --noupx \
    --name SimpleParakeet \
    --distpath "$BIN" \
    --workpath "$WORK" \
    --specpath "$WORK" \
    --hidden-import uvicorn.logging \
    --hidden-import uvicorn.loops \
    --hidden-import uvicorn.loops.auto \
    --hidden-import uvicorn.protocols \
    --hidden-import uvicorn.protocols.http \
    --hidden-import uvicorn.protocols.http.auto \
    --hidden-import uvicorn.protocols.websockets.auto \
    --hidden-import uvicorn.lifespan.on \
    --collect-all uvicorn \
    --collect-all fastapi \
    --collect-all starlette \
    --collect-all httpx \
    "$ENTRY"
)

OUT="$OUT_DIR/SimpleParakeet"
if [[ ! -f "$OUT" ]]; then
  echo "Build finished but $OUT missing" >&2
  exit 1
fi
chmod +x "$OUT"
echo "Built $OUT"
echo "(_internal/ lives next to it under bin/SimpleParakeet/)"
