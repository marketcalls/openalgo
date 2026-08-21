# Repository Copilot Instructions

## Lean credential policy

- Do not add, request, parse, or inject any Lean API credentials.
- Do not use `~/.lean/credentials`.
- Do not add `job-user-id`, `api-access-token`, or `job-organization-id` into generated config files.
- Keep local scripts and templates free of QuantConnect cloud auth fields.

## Runtime policy

- Prefer local-only workflows (backtests and local visualization) that do not require Lean cloud API auth.
- If Lean live runtime enforces subscription checks internally, do not work around by adding credentials automatically.
- Instead, report the runtime limitation clearly and suggest local alternatives.
