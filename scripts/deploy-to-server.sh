#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SSH_TARGET="${1:-${DEPLOY_SSH_TARGET:-}}"
REMOTE_APP_ROOT="${REMOTE_APP_ROOT:-/opt/lean-strategies}"
REMOTE_LEAN_ROOT="${REMOTE_LEAN_ROOT:-/opt/Lean}"
REMOTE_BUILD_LEAN="${REMOTE_BUILD_LEAN:-false}"

if [[ -z "$SSH_TARGET" ]]; then
  echo "Usage: $0 <ssh-user@server> [strategy-path] [algorithm-class]" >&2
  exit 2
fi

STRATEGY_PATH="${2:-${DEPLOY_STRATEGY_PATH:-}}"
ALGORITHM_TYPE_NAME="${3:-${DEPLOY_ALGORITHM_TYPE_NAME:-}}"
command -v rsync >/dev/null 2>&1 || { echo "Error: rsync is required" >&2; exit 1; }
command -v ssh >/dev/null 2>&1 || { echo "Error: ssh is required" >&2; exit 1; }

SSH_PORT="${DEPLOY_SSH_PORT:-22}"
SSH_OPTS=(-p "$SSH_PORT" -o BatchMode=yes -o StrictHostKeyChecking=accept-new)
if [[ -n "${DEPLOY_SSH_KEY:-}" ]]; then
  SSH_OPTS+=(-i "$DEPLOY_SSH_KEY")
fi

ssh "${SSH_OPTS[@]}" "$SSH_TARGET" "mkdir -p '$REMOTE_APP_ROOT'"
rsync -az --exclude '.git/' --exclude '.env' --exclude '.tmp/' \
  --exclude 'results/runs/' --exclude '**/__pycache__/' \
  -e "ssh ${SSH_OPTS[*]}" "$REPO_ROOT/" "$SSH_TARGET:$REMOTE_APP_ROOT/"
ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
  "cd '$REMOTE_APP_ROOT' && APP_ROOT='$REMOTE_APP_ROOT' LEAN_ROOT='$REMOTE_LEAN_ROOT' REMOTE_BUILD_LEAN='$REMOTE_BUILD_LEAN' ./deploy/gcp/remote-deploy.sh"

if [[ -n "$STRATEGY_PATH" ]]; then
  [[ -n "$ALGORITHM_TYPE_NAME" ]] || ALGORITHM_TYPE_NAME="$(basename "$STRATEGY_PATH" .py)"
  ssh "${SSH_OPTS[@]}" "$SSH_TARGET" \
    "cd '$REMOTE_APP_ROOT' && APP_ROOT='$REMOTE_APP_ROOT' LEAN_ROOT='$REMOTE_LEAN_ROOT' ./deploy/gcp/remote-run.sh '$STRATEGY_PATH' '$ALGORITHM_TYPE_NAME'"
fi
