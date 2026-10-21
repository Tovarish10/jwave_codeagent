#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec conda run --no-capture-output -n jw python "$ROOT/jwave_frontend/server.py" "$@"
