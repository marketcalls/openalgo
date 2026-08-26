#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SSH_TARGET="${1:-${DEPLOY_SSH_TARGET:-}}"
REMOTE_LEAN_ROOT="${REMOTE_LEAN_ROOT:-/opt/Lean}"
PYTHON_ENV_PREFIX="${PYTHON_ENV_PREFIX:-$REMOTE_LEAN_ROOT/.conda/lean-py311}"

if [[ -z "$SSH_TARGET" ]]; then
  echo "Usage: $0 <ssh-user@server>" >&2
  exit 2
fi

command -v ssh >/dev/null 2>&1 || { echo "Error: ssh is required" >&2; exit 1; }
SSH_PORT="${DEPLOY_SSH_PORT:-22}"
SSH_OPTS=(-p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${DEPLOY_SSH_KEY:-}" ]]; then
  SSH_OPTS+=(-i "$DEPLOY_SSH_KEY")
fi

ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
  "LEAN_ROOT='$REMOTE_LEAN_ROOT' PYTHON_ENV_PREFIX='$PYTHON_ENV_PREFIX' bash -s" \
  < "$REPO_ROOT/deploy/gcp/setup-python.sh"
