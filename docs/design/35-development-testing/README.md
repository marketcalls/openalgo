# 35 - Development And Testing

## Toolchain

| Area | Current tool |
|---|---|
| Python environment | uv, Python >=3.12 |
| Python lint/format | Ruff |
| Python tests | pytest 9.1 with 60-second default timeout |
| Frontend install | npm with `frontend/package-lock.json` |
| Frontend lint/format | Biome |
| Frontend unit/a11y | Vitest 4, Testing Library, axe |
| Browser tests | Playwright |
| Security | Bandit, pip-audit, Trivy, detect-secrets tooling |

## Backend Commands

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run pytest
```

The default pytest configuration discovers `test/test_*.py` and applies verbose output plus `--timeout=60`. Some tests require a configured/running application or broker-like state; CI therefore runs an explicit credential-free subset rather than the entire tree.

Focused example:

```bash
uv run pytest test/test_scalping_risk_monitor.py -v
```

## Frontend Commands

Run from `frontend/`:

```bash
npm ci
npm run lint
npm run test:run
npm run test:coverage
npm run build
npm run e2e -- --project=chromium
```

Playwright starts Vite on port 5173. Its local configuration defines Chromium, Firefox, WebKit, Mobile Chrome, and Mobile Safari; CI currently invokes Chromium only.

## Main CI Workflow

`.github/workflows/ci.yml` currently runs:

- Backend Ruff checks (marked continue-on-error for existing broker warnings).
- A small CI-safe backend pytest subset.
- Frontend Biome lint, TypeScript/Vite build, Vitest, coverage, and Chromium E2E.
- Bandit and pip-audit (also continue-on-error in main CI).
- Production frontend bundle upload and main-branch auto-commit.
- Native amd64 and arm64 Docker builds, Kaleido/Chromium smoke test on PRs, manifest assembly and Trivy scan on main.

A green workflow does not prove the full backend suite, all broker adapters, or all security findings are clean because several checks are intentionally non-blocking.

## Scheduled Security Workflow

`.github/workflows/security.yml` runs weekly and on demand. It uploads Bandit SARIF/JSON and pip-audit JSON. A fallback creates valid empty SARIF when Bandit's formatter fails, while the JSON artifact retains actual findings.

## Test Selection By Change

| Change | Minimum evidence |
|---|---|
| REST schema/resource | Validation, invalid key, success/service mock, mode behavior |
| Broker adapter | Common broker integration runner plus adapter-specific mapping/stream tests |
| Order service | Live/analyzer/semi-auto paths and event publication |
| Database schema | Fresh initialization and upgrade from a partial/existing file |
| WebSocket | Protocol/unit tests plus connection cleanup and subscription behavior |
| React page | Unit interaction test, build, and relevant Playwright flow |
| Long-lived worker | Start/stop/restart, failure isolation, resource cleanup |
| Documentation route change | REST inventory parity and local-link check |

## Broker Integration Testing

Broker behavior cannot be proven by generic service tests alone. Use `test/test_broker_integration.py`, `test/test_broker_protocol.py`, and the common runner/documentation introduced for adapters, then exercise authenticated broker paths in an appropriate environment without committing credentials.

## Generated Output

Do not hand-edit `frontend/dist`. Build source changes with `npm run build`; main CI owns the committed production bundle update.
