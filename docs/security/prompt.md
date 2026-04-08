================================================================================
OPENALGO SECURITY AUDIT - CLAUDE CODE PROMPTS
================================================================================

Branch: security/audit-phase (already created and pushed)
Codebase: Already understood by Claude Code via prior prompt
Run prompts sequentially. Each commits to docs/security/SECURITY_REPORT.md

================================================================================
CONTEXT: READ THIS BEFORE RUNNING ANY PROMPT
================================================================================

OpenAlgo is a SINGLE-USER, self-hosted algorithmic trading platform.
Understanding these constraints is critical for accurate severity assessment.

Key architectural facts:
- Single user per deployment (no multi-user, no privilege escalation)
- Self-hosted on user's own server (server access = full control)
- All official install scripts (install.sh, install-docker.sh, install-multi.sh,
  docker-run.sh, docker-run.bat, start.sh) auto-generate unique APP_KEY and
  API_KEY_PEPPER via secrets.token_hex(32)
- SEBI (Securities and Exchange Board of India) mandates static IP whitelisting
  for all transactional API orders from April 1, 2026. Delta Exchange (crypto)
  also enforces static IP. Broker-side IP whitelisting means stolen broker
  credentials CANNOT be used from an attacker's machine -- the broker rejects
  requests from non-registered IPs. However, attacks routed THROUGH the
  OpenAlgo server (which has the registered IP) are still viable.
- External platforms (TradingView, GoCharting, Chartink) send API keys in
  JSON body or URL query params -- they cannot set custom HTTP headers.
  This is an accepted architectural trade-off.
- The MCP server (mcp/mcpserver.py) is local-only, communicates via stdio
  with Claude Desktop/Cursor/Windsurf. It is NOT remotely exposed.
- Indian broker tokens expire daily at ~3:00 AM IST. Session management
  is aligned to this schedule.

Threat model priorities (in order):
1. External attackers exploiting API/webhooks to place unauthorized trades
2. XSS/CSRF attacks via malicious websites the user visits
3. OAuth flow manipulation (login CSRF, state forgery)
4. Database file theft (backup leak, directory traversal)
5. AI agent mistakes via MCP (prompt injection, hallucination)

What does NOT apply to single-user:
- Multi-user privilege escalation
- User-to-user data leakage
- Session fixation (no other user to impersonate with TLS in place)
- Admin auto-assign in OAuth callbacks (only one user exists)
- User viewing their own TOTP secret (it's their own)

Severity adjustment rules for single-user self-hosted:
- Server-local risks (file permissions, log contents, memory dumps) are Low
  because server access already grants full control
- Broker credential theft via DB is mitigated by SEBI static IP (attacker
  can't use stolen tokens from their own IP) but NOT fully resolved (attacks
  route through the server)
- MCP findings are Low-Medium (local subprocess, user controls the AI)


================================================================================
PROMPT 1: SETUP REPORT AND RUN AUTOMATED SCANS
================================================================================

Create docs/security/SECURITY_REPORT.md with this structure:

# OpenAlgo Security Audit Report

Date: [today's date]
Commit: [current HEAD commit hash]
Auditor: Claude Code

## Summary

[To be filled after all phases]

| Severity | Count |
|----------|-------|
| Critical | 0 |
| High | 0 |
| Medium | 0 |
| Low | 0 |

## Critical Findings

## High Findings

## Medium Findings

## Low Findings

## Recommendations

Then run automated scans and save to docs/security/scan-results/:

1. uv run bandit -r . --exclude ./.venv,./node_modules,./frontend/node_modules,./test -f txt -o docs/security/scan-results/bandit.txt
2. uv run pip-audit > docs/security/scan-results/pip-audit.txt
3. npm audit in frontend/ if package.json exists

Do NOT analyze yet. Just collect data.
Commit as "security: initialize report and run automated scans"


================================================================================
PROMPT 2: AUTHENTICATION AND SESSION SECURITY
================================================================================

You are an expert cybersecurity researcher. OpenAlgo is a single-user
self-hosted algorithmic trading platform handling real money and broker
credentials. Read the CONTEXT section above before assessing severity.

Audit authentication and session management. Focus on:

- app.py
- blueprints/auth.py
- database/auth_db.py
- .sample.env
- All auth middleware and decorators

For each vulnerability, add to docs/security/SECURITY_REPORT.md under the
correct severity using this format:

### VULN-XXX: [Short title]

Severity: Critical / High / Medium / Low
File: path/to/file.py (line numbers)
CWE: CWE-XXX

What: [One paragraph - the vulnerability]

Risk: [One paragraph - what an attacker can do]

Fix: [Specific code change needed]

---

Check: SECRET_KEY generation (note: all install scripts auto-generate),
password hashing, session cookie flags (Secure/HttpOnly/SameSite),
brute force protection, session fixation (note: single-user with TLS),
DEBUG mode in production, HTTPS enforcement, session timeout.

Only confirmed vulnerabilities. Adjust severity per single-user context.
Update severity counts.
Commit as "security: authentication and session audit"


================================================================================
PROMPT 3: API SECURITY AND INPUT VALIDATION
================================================================================

Audit the REST API layer. This API is publicly exposed and accepts requests
from TradingView, Amibroker, Python SDKs, and AI agents. A vulnerability
means unauthorized trades on real accounts.

Note: API key in URL query params for GET endpoints is an accepted trade-off
required by TradingView/GoCharting/Chartink webhook integrations that cannot
set custom HTTP headers.

Focus on:
- restx_api/ (all endpoint handlers, especially schemas.py)
- blueprints/strategy.py and blueprints/chartink.py (webhook handlers)
- utils/

Same VULN-XXX format. Check: API key generation/storage/validation,
endpoints missing auth, input validation on order parameters (negative
quantities, extreme prices, unbounded list sizes, missing length/range
validators on symbol/strategy/position_size fields), rate limiting,
webhook authentication, error response info leakage (str(e) in responses),
CORS config, request size limits (MAX_CONTENT_LENGTH).

Update severity counts.
Commit as "security: API and input validation audit"


================================================================================
PROMPT 4: BROKER INTEGRATION SECURITY (SCOPED)
================================================================================

Audit broker credential storage and auth flows for these 8 brokers only:

- broker/zerodha/
- broker/upstox/
- broker/dhan/
- broker/fyers/
- broker/angel/
- broker/kotak/
- broker/groww/
- broker/compositedge/

Also read: database/settings_db.py, database/telegram_db.py,
database/flow_db.py, database/user_db.py, keys/ directory.

Same VULN-XXX format. Check: credentials encrypted at rest or plaintext in
SQLite (check EVERY sensitive column: secret_api_key, bot token, flow api_key,
totp_secret), OAuth state validation, redirect URI validation, token refresh
handling, what happens if SQLite file is read by attacker (note: SEBI static
IP mitigates direct broker API abuse but NOT OpenAlgo API abuse), TOTP seed
storage, credentials leaked in error logs (check logger.info and logger.debug
for tokens/secrets), hardcoded fallback encryption keys.

Note which findings apply across all brokers due to shared patterns.
Skip all other brokers in this phase.

Update severity counts.
Commit as "security: broker integration audit (8 brokers)"


================================================================================
PROMPT 5: DATABASE SECURITY
================================================================================

Audit the database layer. SQLite means the entire DB is a single file.
Note: single-user server means file permissions are Low severity.

Focus on:
- database/ (every .py file)
- db/ directory

Same VULN-XXX format. Check: SQL injection via string concatenation or
f-strings (especially DuckDB COPY TO in historify_db.py), sensitive data
in plaintext, apilog_db.py and traffic_db.py missing purge/retention
functions, pickle/yaml.load/eval on DB data, encryption key derivation
(static salts, hardcoded fallback keys in settings_db.py and telegram_db.py).

Update severity counts.
Commit as "security: database layer audit"


================================================================================
PROMPT 6: FRONTEND SECURITY
================================================================================

Audit the frontend. React 19 SPA served by Flask.

Focus on:
- frontend/src/ (especially stores/authStore.ts, pages/Login.tsx,
  pages/BrokerSelect.tsx)

Same VULN-XXX format. Check: auth token storage location (localStorage
vs memory -- check Zustand persist partialize), dangerouslySetInnerHTML,
Content Security Policy (unsafe-inline in script-src, broad connect-src),
open redirects (navigate(data.redirect) without validation), clickjacking
protection, OAuth state generation (Math.random vs crypto.randomUUID),
hardcoded OAuth state values.

Update severity counts.
Commit as "security: frontend audit"


================================================================================
PROMPT 7: INFRASTRUCTURE AND DEPLOYMENT
================================================================================

Audit deployment config and supporting services.

Note: ubuntu-ip.sh has been deleted (was deploying over plain HTTP).
The MCP server is local-only (stdio, not network-exposed).

Focus on:
- Dockerfile and docker-compose.yml
- install/ (all shell scripts)
- websocket_proxy/ (especially base_adapter.py ZMQ bind address)
- mcp/mcpserver.py
- start.sh

Same VULN-XXX format. Check: container .env file permissions (chmod 666),
secrets in image layers, exposed ports, ZMQ binding to 0.0.0.0 vs 127.0.0.1,
MCP API key in sys.argv (visible in process list -- but local-only single-user),
MCP unrestricted trading (but user controls the AI client), install scripts
writing .env with overly broad permissions, start.sh /tmp fallback.

Adjust severity per single-user and local-only MCP context.
Update severity counts.
Commit as "security: infrastructure and deployment audit"


================================================================================
PROMPT 8: DEPENDENCY AND SCAN ANALYSIS
================================================================================

Cross-reference automated scan results with actual code.

1. Read docs/security/scan-results/bandit.txt - verify each finding against
   source code. Discard false positives. Add true positives to report.

2. Read docs/security/scan-results/pip-audit.txt - check if vulnerable
   code paths are used in OpenAlgo. Add relevant ones.

3. Read npm audit results if they exist - same process.

4. Check if dependencies are pinned to exact versions.

Only confirmed issues go into the report.

Update severity counts.
Commit as "security: dependency and scan analysis"


================================================================================
PROMPT 9: FINAL REPORT
================================================================================

Finalize docs/security/SECURITY_REPORT.md:

1. Fix the Summary table with accurate counts.

2. Write Summary section - 2-3 paragraphs: what was audited, most critical
   findings with business impact, overall security posture. Include notes on
   single-user context, SEBI static IP policy, and install script mitigations.

3. Add a Tracking Status table with columns:
   VULN | Original Severity | Current Severity | Status | Notes

4. Write Recommendations:

   ### Immediate (fix before next release)
   Critical and High findings, one line each.

   ### Short-term (fix within 2-4 weeks)
   Medium findings grouped by theme.

   ### Long-term (ongoing improvements)
   Low findings and architectural improvements.

5. Verify every VULN has: Severity, File, CWE, What, Risk, Fix.
   Remove duplicates and placeholders.

6. Renumber all entries sequentially (VULN-001, VULN-002, etc.)

Commit as "security: final audit report"
Push: git push origin security/audit-phase
