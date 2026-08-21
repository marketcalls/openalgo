#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LEAN_REPO="${LEAN_REPO:-$REPO_ROOT/../Lean}"
LAUNCHER_DIR="${LEAN_LAUNCHER_DIR:-$LEAN_REPO/Launcher/bin/Debug}"
SOURCE="$REPO_ROOT/deploy/macos/IBAutomater.sh"
TARGET="$LAUNCHER_DIR/IBAutomater.sh"
GATEWAY_SOURCE="$REPO_ROOT/deploy/macos/ibgateway"
GATEWAY_DIR="${IB_GATEWAY_DIR:-$HOME/ibgateway}"
GATEWAY_TARGET="$GATEWAY_DIR/ibgateway"
LEGACY_GATEWAY_TARGET="$GATEWAY_DIR/ibgateway1"
VMOPTIONS_SOURCE="$GATEWAY_DIR/ibgateway1.vmoptions"
VMOPTIONS_TARGET="$GATEWAY_DIR/ibgateway.vmoptions"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "This installer is for macOS only." >&2
  exit 1
fi
if [[ ! -f "$SOURCE" ]]; then
  echo "Wrapper source not found: $SOURCE" >&2
  exit 1
fi
if [[ ! -d "$LAUNCHER_DIR" ]]; then
  echo "LEAN launcher directory not found: $LAUNCHER_DIR" >&2
  exit 1
fi
if [[ ! -d "$GATEWAY_DIR" ]]; then
  echo "IB Gateway directory not found: $GATEWAY_DIR" >&2
  exit 1
fi
if [[ ! -f "$GATEWAY_SOURCE" ]]; then
  echo "macOS Gateway bridge not found: $GATEWAY_SOURCE" >&2
  exit 1
fi

if [[ -e "$LEGACY_GATEWAY_TARGET" ]]; then
  backup_target="$LEGACY_GATEWAY_TARGET.before-macos-bridge-fix"
  backup_index=1
  while [[ -e "$backup_target" ]]; do
    backup_index=$((backup_index + 1))
    backup_target="$LEGACY_GATEWAY_TARGET.before-macos-bridge-fix.$backup_index"
  done
  mv "$LEGACY_GATEWAY_TARGET" "$backup_target"
fi

if [[ -e "$VMOPTIONS_SOURCE" ]]; then
  backup_vmoptions="$VMOPTIONS_SOURCE.before-macos-bridge-fix"
  backup_index=1
  while [[ -e "$backup_vmoptions" ]]; do
    backup_index=$((backup_index + 1))
    backup_vmoptions="$VMOPTIONS_SOURCE.before-macos-bridge-fix.$backup_index"
  done
  mv "$VMOPTIONS_SOURCE" "$backup_vmoptions"
fi

install -m 755 "$SOURCE" "$TARGET"
install -m 755 "$GATEWAY_SOURCE" "$GATEWAY_TARGET"
if [[ ! -e "$VMOPTIONS_TARGET" && -e "$VMOPTIONS_SOURCE" ]]; then
  install -m 644 "$VMOPTIONS_SOURCE" "$VMOPTIONS_TARGET"
fi
echo "Installed macOS IBAutomater wrapper: $TARGET"
echo "Installed macOS Gateway bridge: $GATEWAY_TARGET"
