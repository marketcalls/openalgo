#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/lean-strategies}"
LEAN_ROOT="${LEAN_ROOT:-/opt/Lean}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-master}"

die() {
  echo "deploy: $*" >&2
  exit 1
}

[[ -d "$APP_ROOT/.git" ]] || die "strategy repository is not a git checkout: $APP_ROOT"
[[ -z "$(git -C "$APP_ROOT" status --porcelain)" ]] || die "working tree is dirty: $APP_ROOT"

git -C "$APP_ROOT" fetch --prune origin "$DEPLOY_BRANCH"
git -C "$APP_ROOT" checkout "$DEPLOY_BRANCH"
git -C "$APP_ROOT" pull --ff-only origin "$DEPLOY_BRANCH"

if [[ "${UPDATE_LEAN:-false}" == "true" ]]; then
  [[ -d "$LEAN_ROOT/.git" ]] || die "Lean repository is not a git checkout: $LEAN_ROOT"
  [[ -z "$(git -C "$LEAN_ROOT" status --porcelain)" ]] || die "working tree is dirty: $LEAN_ROOT"
  git -C "$LEAN_ROOT" fetch --prune origin "$DEPLOY_BRANCH"
  git -C "$LEAN_ROOT" checkout "$DEPLOY_BRANCH"
  git -C "$LEAN_ROOT" pull --ff-only origin "$DEPLOY_BRANCH"
  dotnet restore "$LEAN_ROOT/QuantConnect.Lean.sln"
  dotnet build "$LEAN_ROOT/QuantConnect.Lean.sln" -c "${LEAN_CONFIGURATION:-Debug}" --no-restore
fi

if command -v jq >/dev/null 2>&1; then
  find "$APP_ROOT/config" -type f -name '*.json' -print0 | xargs -0 -n1 jq empty >/dev/null
fi

echo "Code deployment completed at $APP_ROOT. No strategy process was started or restarted."
