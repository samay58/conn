#!/bin/zsh
# One gate for every change: Python tests (which include all 14 harness
# evals), then the Swift tests. --python-only skips Swift for daemon-only work.
# No live model calls, no lab VMs, nothing written outside tmp dirs and macos/.build.
set -euo pipefail
cd "$(dirname "$0")"

PYTHON="${CONN_PYTHON:-.venv/bin/python}"
RUN_SWIFT=1
for arg in "$@"; do
    case "$arg" in
        --python-only) RUN_SWIFT=0 ;;
        *) echo "usage: ./verify.sh [--python-only]" >&2; exit 2 ;;
    esac
done

echo "== python tests + harness evals =="
PYTHONPATH=src "$PYTHON" -m pytest tests -q

if [[ $RUN_SWIFT -eq 1 ]]; then
    echo "== swift tests =="
    BETA_DEVELOPER_DIR="/Applications/Xcode-beta.app/Contents/Developer"
    if [[ -z "${DEVELOPER_DIR:-}" && -d "$BETA_DEVELOPER_DIR" ]]; then
        # CLAUDE.md: bare swift may need the beta toolchain on this machine.
        export DEVELOPER_DIR="$BETA_DEVELOPER_DIR"
    fi
    (cd macos && swift test)
fi

echo "== verify passed =="
