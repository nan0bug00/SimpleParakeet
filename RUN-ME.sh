#!/usr/bin/env bash
# SimpleParakeet entrypoint (Linux). Open a terminal in this folder and run:
#   chmod +x RUN-ME.sh && ./RUN-ME.sh
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec "$ROOT/launch.sh" "$@"
