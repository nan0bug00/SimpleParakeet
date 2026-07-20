#!/usr/bin/env bash
# Downloads mudler/parakeet.cpp Linux CPU x64 release and installs
# parakeet-server (+ sibling shared libs) into bin/.
# Does NOT start servers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN="$ROOT/bin"
REL="${PARAKEET_CPP_RELEASE:-${1:-v0.4.0}}"
API="https://api.github.com/repos/mudler/parakeet.cpp/releases/tags/${REL}"

mkdir -p "$BIN" "$ROOT/build"
TMP="$ROOT/build/parakeet-dl"
rm -rf "$TMP"
mkdir -p "$TMP"

echo "Querying mudler/parakeet.cpp $REL ..."
JSON="$(curl -fsSL -H "User-Agent: SimpleParakeet-CI" "$API")"

# Prefer linux + cpu + x64/amd64 + .tar.gz
PICK_URL="$(python3 -c '
import json,sys,re
data=json.loads(sys.stdin.read())
assets=data.get("assets") or []
print("Assets:", file=sys.stderr)
for a in assets:
    print(" ", a.get("name"), file=sys.stderr)

def score(name: str) -> int:
    n=name.lower()
    if not n.endswith(".tar.gz"):
        return -1
    s=0
    if "linux" in n: s+=10
    if "cpu" in n: s+=10
    if "x64" in n or "amd64" in n or "x86_64" in n: s+=10
    if "cuda" in n or "vulkan" in n: s-=50
    if "arm" in n: s-=50
    return s

best=None
best_s=-1
for a in assets:
    sc=score(a.get("name") or "")
    if sc>best_s:
        best_s=sc
        best=a
if not best or best_s<20:
    sys.exit("No Linux CPU x64 tar.gz found — set PARAKEET_CPP_RELEASE")
print(best["browser_download_url"])
print(best["name"], file=sys.stderr)
' <<<"$JSON")"

echo "Downloading $PICK_URL"
ARCHIVE="$TMP/parakeet.tar.gz"
curl -fsSL --retry 3 -o "$ARCHIVE" "$PICK_URL"
tar -xzf "$ARCHIVE" -C "$TMP"

SERVER="$(find "$TMP" -type f -name parakeet-server | head -n 1 || true)"
if [[ -z "$SERVER" || ! -f "$SERVER" ]]; then
  echo "parakeet-server not found inside archive" >&2
  exit 1
fi

SERVER_DIR="$(dirname "$SERVER")"
cp -f "$SERVER" "$BIN/parakeet-server"
chmod +x "$BIN/parakeet-server"

# Copy sibling shared libraries the binary may need at runtime
shopt -s nullglob
for lib in "$SERVER_DIR"/*.so "$SERVER_DIR"/*.so.*; do
  cp -f "$lib" "$BIN/"
done
shopt -u nullglob

echo "Installed $BIN/parakeet-server"
ls -la "$BIN/parakeet-server" "$BIN"/*.so* 2>/dev/null || true
