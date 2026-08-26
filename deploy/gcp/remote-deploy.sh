#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
LEAN_ROOT="${LEAN_ROOT:-$APP_ROOT/../Lean}"
die() { echo "remote-deploy: $*" >&2; exit 1; }

[[ -d "$APP_ROOT" ]] || die "strategy directory not found: $APP_ROOT"
[[ -d "$LEAN_ROOT" ]] || die "existing Lean installation not found: $LEAN_ROOT"
LEAN_LAUNCHER_DIR="${LEAN_LAUNCHER_DIR:-$LEAN_ROOT/Launcher/bin/Debug}"
LEAN_LAUNCHER_DLL="${LEAN_LAUNCHER_DLL:-$LEAN_LAUNCHER_DIR/QuantConnect.Lean.Launcher.dll}"

if [[ -f "$LEAN_LAUNCHER_DLL" ]]; then
  echo "Lean launcher: $LEAN_LAUNCHER_DLL"
elif command -v lean >/dev/null 2>&1; then
  echo "Lean CLI: $(command -v lean)"
  lean --version || true
else
  die "could not find Lean launcher or lean CLI under $LEAN_ROOT"
fi

if command -v jq >/dev/null 2>&1; then
  find "$APP_ROOT/config" -type f -name '*.json' -print0 | xargs -0 -n1 jq empty >/dev/null
fi
echo "Strategy code deployed at $APP_ROOT"
echo "Lean installation preserved at $LEAN_ROOT"
