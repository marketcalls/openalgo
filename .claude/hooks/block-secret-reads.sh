#!/usr/bin/env bash
# PreToolUse/Bash guard: enforce the Read deny-list against shell commands.
#
# Permission rules only match the Read tool. This hook inspects the command
# itself and blocks any reference to a protected path, regardless of which
# utility is used.
# No exceptions: .env.sample and .env.example are blocked here too. Those
# are readable through the Read tool, which prompts via the "ask" rules.
#
# Design notes:
#   - Scans the ENTIRE raw stdin payload rather than extracting a field with
#     jq. No external dependency, and nothing gets through by malforming the
#     JSON or hiding a path in an unexpected field.
#   - Fails CLOSED: if stdin cannot be read at all, the call is blocked. A
#     guard that allows on error is not a guard.
#
# Exit 2 = block the tool call; stderr is shown to the model.

set -uo pipefail

payload=$(cat 2>/dev/null) || payload=""

block() {
  printf 'Blocked: command references a protected path (%s).\n' "$1" >&2
  printf 'The deny-list in .claude/settings.json covers .env files and ' >&2
  printf 'secrets/ directories. Reading them via a shell command is not ' >&2
  printf 'permitted. Use the Read tool if the file is genuinely allowed.\n' >&2
  exit 2
}

# Fail closed: an unreadable or empty payload is not a reason to allow.
if [ -z "$payload" ]; then
  block "unreadable hook input"
fi

# Any .env reference: bare .env, .env.local, foo/.env, .ENV, and the
# glob forms (.en*, .e??) a shell would expand to .env before execution.
if printf '%s' "$payload" | grep -qiE '\.e(nv|n[*?]|[*?])'; then
  block ".env"
fi

# secrets/ directories anywhere in the tree, including glob forms.
if printf '%s' "$payload" | grep -qiE 'secret[s*?]?/'; then
  block "secrets/"
fi

exit 0
