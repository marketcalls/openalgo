#!/usr/bin/env bash
set -euo pipefail

APP_ROOT="${APP_ROOT:-/opt/lean-strategies}"
LEAN_ROOT="${LEAN_ROOT:-/opt/Lean}"
DEPLOY_BRANCH="${DEPLOY_BRANCH:-master}"
SERVICE_NAME="${SERVICE_NAME:-lean-strategy}"

die() {
  echo "deploy: $*" >&2
  exit 1
}

[[ -d "$APP_ROOT/.git" ]] || die "strategy repository is not a git checkout: $APP_ROOT"
[[ -d "$LEAN_ROOT/.git" ]] || die "Lean repository is not a git checkout: $LEAN_ROOT"

for repo in "$APP_ROOT" "$LEAN_ROOT"; do
  [[ -z "$(git -C "$repo" status --porcelain)" ]] || die "working tree is dirty: $repo"
done

git -C "$APP_ROOT" fetch --prune origin "$DEPLOY_BRANCH"
git -C "$APP_ROOT" checkout "$DEPLOY_BRANCH"
git -C "$APP_ROOT" pull --ff-only origin "$DEPLOY_BRANCH"

if [[ "${UPDATE_LEAN:-true}" == "true" ]]; then
  git -C "$LEAN_ROOT" fetch --prune origin "$DEPLOY_BRANCH"
  git -C "$LEAN_ROOT" checkout "$DEPLOY_BRANCH"
  git -C "$LEAN_ROOT" pull --ff-only origin "$DEPLOY_BRANCH"
fi

dotnet restore "$LEAN_ROOT/QuantConnect.Lean.sln"
dotnet build "$LEAN_ROOT/QuantConnect.Lean.sln" -c "${LEAN_CONFIGURATION:-Debug}" --no-restore

if command -v jq >/dev/null 2>&1; then
  find "$APP_ROOT/config" -type f -name '*.json' -print0 | xargs -0 -n1 jq empty >/dev/null
fi

if [[ "${INSTALL_SERVICE:-false}" == "true" ]]; then
  [[ "$(id -u)" -eq 0 ]] || die "INSTALL_SERVICE=true requires root"
  install -d -m 0750 /etc/lean-strategy
  install -m 0644 "$APP_ROOT/deploy/gcp/lean-strategy.service" "/etc/systemd/system/$SERVICE_NAME.service"
  systemctl daemon-reload
  systemctl enable "$SERVICE_NAME.service"
fi

if systemctl list-unit-files "$SERVICE_NAME.service" --no-legend 2>/dev/null | grep -q .; then
  systemctl restart "$SERVICE_NAME.service"
  systemctl --no-pager --full status "$SERVICE_NAME.service" || true
else
  echo "Deployment completed. Service $SERVICE_NAME.service is not installed; configure deploy/gcp/lean-strategy.service before starting live mode."
fi
