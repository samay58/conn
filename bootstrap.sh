#!/bin/zsh
# Bootstrap a working Conn install on this Mac: venv, wheels, daemon
# verification, app build and install. Idempotent; rerun after any git pull.
# The steps that can never be scripted (key material, TCC grants) print at
# the end. Full reference: docs/DEPLOYMENT.md.
#
#   git clone https://github.com/samay58/conn.git ~/conn && ~/conn/bootstrap.sh
#
# Flags: --no-app skips the Swift build (daemon + web console only).
set -euo pipefail
cd "$(dirname "$0")"

BUILD_APP=1
if [[ "${1:-}" == "--no-app" ]]; then
    BUILD_APP=0
fi

# Python floor is 3.12 (pyproject). Prefer the newest interpreter present.
PY=""
for p in python3.14 python3.13 python3.12 python3; do
    if command -v "$p" >/dev/null 2>&1 \
        && "$p" -c 'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' 2>/dev/null; then
        PY="$(command -v "$p")"
        break
    fi
done
if [[ -z "$PY" ]]; then
    echo "no Python >= 3.12 on PATH; brew install python@3.14 (or uv python install 3.14), then rerun" >&2
    exit 1
fi
echo "python: $PY ($("$PY" --version))"

# Per-machine venv and wheels; gitignored, never travels.
if [[ ! -x .venv/bin/python ]]; then
    "$PY" -m venv .venv
fi
.venv/bin/python -m pip install -q -e ".[dev]"
echo "venv: $(.venv/bin/python --version) at .venv, conn installed editable"

# Machine-specific config values (the honest list lives in docs/DEPLOYMENT.md).
.venv/bin/python - <<'PYEOF'
import os
import pathlib
import shutil
import tomllib

with open("config.toml", "rb") as f:
    cfg = tomllib.load(f)
phoenix = cfg.get("phoenix", {})
vault = pathlib.Path(phoenix.get("vault_root", ""))
qmd = pathlib.Path(phoenix.get("qmd_bin", ""))
if vault.is_dir():
    print(f"vault: {vault}")
else:
    print(f"WARN config.toml [phoenix] vault_root missing on this machine: {vault}")
if qmd.is_file() and os.access(qmd, os.X_OK):
    print(f"qmd: {qmd}")
else:
    found = shutil.which("qmd")
    hint = f" (qmd is on PATH at {found}; pin that)" if found else ""
    print(f"WARN config.toml [phoenix] qmd_bin not executable here: {qmd}{hint}")
PYEOF

# Verify the daemon before touching the app.
PYTHONPATH=src .venv/bin/python -m pytest tests -q
PYTHONPATH=src .venv/bin/python -m conn --eval
PYTHONPATH=src .venv/bin/python -m conn --doctor || true

APP_STATE=skipped
if [[ $BUILD_APP -eq 1 ]]; then
    if (cd macos && ./make-app.sh install); then
        APP_STATE=ok
    else
        APP_STATE=failed
    fi
fi

echo ""
echo "== bootstrap done =="
echo "daemon: tests and evals green; doctor output above"
case $APP_STATE in
    ok)      echo "app: installed at /Applications/Conn.app" ;;
    failed)  echo "app: BUILD FAILED; daemon still works headless (see toolchain message above)" ;;
    skipped) echo "app: skipped (--no-app)" ;;
esac
cat <<'EOF'

Once per machine, by hand (these never travel):
  1. Key material, daemon-readable (or export OPENAI_API_KEY instead):
       mkdir -p ~/.config/openai
       # write the key into ~/.config/openai/key, then:
       chmod 600 ~/.config/openai/key
  2. TCC grants at the screen: open /Applications/Conn.app, run one live turn
     for the mic prompt, then menu > Enable Global Hotkey for Accessibility.
     Screen Recording only if computer_screenshot should see other apps.
  3. Recommended: the "Conn Dev Signing" keychain identity so grants survive
     rebuilds (README, Stable signing).
  4. Smoke test: hold Right Option, say "what app am I in right now."
EOF
if [[ $APP_STATE == failed ]]; then
    exit 1
fi
exit 0
