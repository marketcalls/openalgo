---
name: security-audit
description: Run OpenAlgo's periodic security audit across backend, frontend, database, cache, routes and dependencies, producing a dated xlsx report. Use for the monthly or twice-monthly review, before a release, after a dependency bump, or when the user asks for a security check, vulnerability scan, or audit report.
---

# OpenAlgo security audit

Run monthly (or twice monthly), and additionally before any release and after
any dependency bump.

```bash
uv run --with openpyxl python .claude/skills/security-audit/audit.py
```

Writes `tmp/security-audits/<YYYY-MM>/security_audit_<date>_<time>.xlsx`.
`tmp/` is gitignored and holds reports only — the script keeps its own scratch
files in the OS temp dir. Exit code is 0 when no CRITICAL/HIGH check is failing,
1 otherwise, so it drops into CI unchanged.

The script is **read-only**. It never rotates a key, edits config, or touches
the database, and the report never contains a secret value — only pass/fail, a
`sha256:` fingerprint, and a remediation pointer. That means the xlsx is safe to
share with someone helping you triage.

## What it covers

| Area | Checks |
| --- | --- |
| **Secrets** | `APP_KEY`/`API_KEY_PEPPER` present, full-entropy, and not one of the publicly-known leaked values shipped before v2.0.0.6; no credentials tracked in git; `detect-secrets` sweep |
| **Runtime posture** | `FLASK_DEBUG` off; remote MCP never with debug; CSRF on; CSP enforcing (not report-only); CORS not wildcard-with-credentials; HTTPS; ngrok off; rate limits set |
| **Routes** | All 461 blueprint routes checked for `@check_session_validity` / rate limiting against an allowlist of intentionally-public paths; state-changing routes reported separately; test/debug surfaces flagged |
| **Database** | File permissions; Fernet encryption of broker tokens; peppered API keys; NullPool (never StaticPool); engines created via `engine_factory`; backup presence |
| **Cache** | Credential caches must have an explicit bounded TTL; auth-change invalidation available; the ZMQ invalidation publisher must `connect()`, never `bind()` |
| **Backend code** | eval/exec, `shell=True`, pickle/yaml deserialization, raw-SQL f-strings, path traversal, SSRF, open redirect, weak hashes, `verify=False`, missing HTTP timeouts |
| **Frontend** | `dangerouslySetInnerHTML`, `innerHTML`, `eval`/`new Function`, credentials in browser storage, hardcoded key literals, plain-http endpoints, source maps in `dist/`, `npm audit` |
| **Dependencies** | `pip-audit` (Python) and `npm audit` (JS) — two separate ecosystems, both required |
| **Static analysis** | `bandit`, triaged rather than dumped |

## Reading the report

Six sheets: **Summary**, **Findings** (colour-coded by status), **Code
patterns**, **Frontend patterns**, **Routes (unprotected)**, **Bandit
(triaged)**, **Manual review**.

Statuses mean different things and should be worked in this order:

- **FAIL** — a control is objectively wrong. Fix it.
- **ERROR** — a check could not run (usually a missing tool). Fix the tooling; an unrun check is not a pass.
- **REVIEW** — a pattern that is *often* fine and sometimes catastrophic. A human must look. This is where the real findings live.
- **WARN** — weaker posture, defensible depending on deployment.
- **PASS / SKIP** — no action.

**Do not treat counts as scores.** Bandit produces ~930 raw findings on this
repo and roughly 5 matter; the rest are asserts and `try/except/pass`. The
script does that triage for you and reports all three numbers so you can see the
ratio. Same for the route check: 461 routes, ~119 without decorators, and almost
all of those are legitimately public — which is why the allowlist exists.

## Triage guidance for the recurring REVIEW items

**Raw SQL f-strings.** All current hits interpolate *table and column names*
(SQLite cannot parameterize those) from module-level literals in migration code,
e.g. `_migrate_mode_unique(ScalpingSLState, "scalping_sl_state")`. That is safe.
The check exists to catch the day someone interpolates a request value. Trace
each new hit to its source; if it is not a developer-controlled constant, it is
a real injection.

**Direct `create_engine` calls.** Mostly in broker `database/master_contract_db.py`
modules. These bypass `engine_factory` and therefore the NullPool guarantee — an
FD-hygiene and availability issue rather than a breach. Worth converging over
time; see the `fd-audit` skill.

**Credential caches.** `database/telegram_db.py` holds
`_user_credentials_cache` with a 30-minute TTL. Broker tokens roll over at
~3 AM IST, so confirm no auth cache outlives that boundary and that logout or
revoke invalidates it.

**Unprotected routes.** Genuinely public ones (React SPA shells, `/login`,
`.well-known`, broker callbacks, token-authenticated webhooks and postbacks) are
on `PUBLIC_ROUTE_ALLOWLIST` in the script. When you add a legitimately public
route, add it there **with a reason** — that keeps the check meaningful instead
of noisy.

**detect-secrets candidates.** High false-positive rate on this repo. Triage
once, then commit a `.secrets.baseline` so subsequent audits only surface
*new* candidates.

**Credentials in browser storage.** The current hit is
`localStorage.setItem('pocketful_oauth_state', ...)`, which is an OAuth CSRF
state token — the correct use of localStorage. An auth token or API key there
would not be.

## Manual checks the script cannot do

The **Manual review** sheet lists twelve items that need a human and an
authenticated session — they are part of the audit, not optional extras. The
ones most specific to this platform:

- **Static IP whitelisting.** Confirm the broker portal still lists only this server's IP. Under the SEBI mandate stolen keys are unusable off-IP, but anything routed *through* this server still works — so server compromise, not key theft, is the threat that matters.
- **API keys.** Revoke keys for integrations no longer in use. TradingView/Chartink send keys in the body or query string and cannot set headers, so a stale key is a standing grant.
- **Network exposure.** Ports 5000/8765/**5555** must not be internet-reachable. ZMQ 5555 carries the raw tick feed with no authentication.
- **Webhook tokens.** Flow and strategy webhook URLs are bearer credentials — anyone holding the URL can trigger the strategy.
- **Pepper discipline.** Never hand-edit `API_KEY_PEPPER` on a populated database; it invalidates every password hash and encrypted token. Use `upgrade/rotate_pepper.py`.

## Threat model this is calibrated to

OpenAlgo is **single-user and self-hosted**: one user, one broker session per
instance, no privilege escalation and no SaaS component. Server access equals
full control, which is why filesystem permissions, secret hygiene and network
exposure carry more weight here than classic multi-tenant concerns like IDOR or
role bypass. Weight your triage accordingly.

## Maintaining the script

Add a check by writing one function that calls
`add(check, severity, status, detail, remediation, evidence)` and wiring it into
`main()`. Keep three properties:

1. **Never print a secret** — use `fingerprint()`.
2. **Never write outside `tmp/security-audits/`** — scratch goes to `tempfile`.
3. **Give every finding a remediation**, not just a description. A finding
   nobody knows how to fix gets skipped next month.

When a REVIEW item is confirmed benign and will stay benign, encode that as an
allowlist entry or a narrowed pattern rather than re-triaging it every month.
