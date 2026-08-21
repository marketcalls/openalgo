#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ENV_FILE="$REPO_ROOT/.env"

touch "$ENV_FILE"

set_env_key() {
  local key="$1"
  local value="$2"
  local escaped
  escaped="$(printf '%s' "$value" | sed -e 's/[\/&\\]/\\&/g')"

  if grep -q "^${key}=" "$ENV_FILE"; then
    sed -i.bak "s/^${key}=.*/${key}=${escaped}/" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$value" >> "$ENV_FILE"
  fi
}

printf 'IB account id (U... or DU...): '
IFS= read -r ib_account
printf 'IB login username: '
IFS= read -r ib_user_name
printf 'IB password: '
stty -echo
IFS= read -r ib_password
stty echo
printf '\n'

if [[ -z "$ib_account" || -z "$ib_user_name" || -z "$ib_password" ]]; then
  echo "Error: account, username, and password are required."
  exit 1
fi

if [[ "$ib_user_name" =~ ^(U|DU)[0-9]+$ ]]; then
  echo "Error: IB login username looks like an account id."
  echo "Use the username you type on the IB Gateway login screen."
  exit 1
fi

set_env_key "IB_ACCOUNT" "$ib_account"
set_env_key "IB_USER_NAME" "$ib_user_name"
set_env_key "IB_PASSWORD" "$ib_password"
set_env_key "IB_USE_EXISTING_GATEWAY" "false"
set_env_key "IB_TRADING_MODE" "${IB_TRADING_MODE:-paper}"
set_env_key "IB_HOST" "${IB_HOST:-127.0.0.1}"
set_env_key "IB_PORT" "${IB_PORT:-4002}"
set_env_key "IB_TWS_DIR" "${IB_TWS_DIR:-$HOME/Jts}"
set_env_key "IB_VERSION" "${IB_VERSION:-1046}"

rm -f "$ENV_FILE.bak"
echo "Updated IB credentials in $ENV_FILE"
