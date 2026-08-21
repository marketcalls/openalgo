#!/usr/bin/env bash
set -euo pipefail

# macOS wrapper for QuantConnect.IBAutomater.
# Do not use Xvfb, Linux ps flags, or broad Java process termination.

if [[ $# -lt 1 ]]; then
  echo "Usage: $0 <ib-gateway-executable> [java-options] [gateway-options...]" >&2
  exit 64
fi

ibgateway_executable="$1"
java_tool_options="${2:-}"

if [[ ! -x "$ibgateway_executable" ]]; then
  echo "IB Gateway executable is not executable: $ibgateway_executable" >&2
  exit 127
fi

export JAVA_TOOL_OPTIONS="$java_tool_options"
shift

exec "$ibgateway_executable" "$@"
