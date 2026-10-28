#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${JWAVE_PYTHON:-${EXEC_PYTHON:-${PYTHON:-python3}}}"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    printf 'Unable to find Python interpreter: %s\n' "$PYTHON_BIN" >&2
    printf 'Set JWAVE_PYTHON to a Python >= 3.10 interpreter.\n' >&2
    exit 127
fi

exec "$PYTHON_BIN" "$ROOT/jwave_frontend/server.py" "$@"
