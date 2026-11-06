# CI/CD Workflows Reference

## Overview

This document details all GitHub Actions workflows in the OpenAlgo CI/CD pipeline.

## Main CI Workflow

**File:** `.github/workflows/ci.yml`

**Triggers:**
- Push to `main` branch
- Pull requests targeting `main` branch

**Concurrency:** Cancels in-progress runs when new commits are pushed to the same branch.

### Jobs Summary

| Job | Purpose |
|-----|---------|
| backend-lint | Python Ruff checks (currently informational through `continue-on-error`) |
| backend-test | Explicit credential-free pytest subset, including broker-key, transport, sandbox and regression tests |
| gunicorn-boot | Real launcher/server startup, polling/WebSocket/SSE, proxy topology and shutdown matrix |
| eventlet-fallback | Eventlet compatibility tests with eventlet installed; verifies tests did not skip |
| gthread-gates | Check-then-act and sleep source gates |
| gthread-migration | Every `test/test_gthread_*.py` migration test under Linux |
| gthread-platforms | Portable runtime/concurrency cases on Windows, macOS and Linux ARM64 |
| chart-indicator-skill | Pinned chart API export/reference and example coverage |
| frontend-lint | TypeScript/React linting |
| frontend-build | Production build and `frontend-dist` artifact |
| frontend-test | Vitest and coverage artifact |
| frontend-e2e | Chromium Playwright checks |
| security-scan | Informational Bandit and pip-audit checks |
| commit-dist | Rebuild and commit `frontend/dist` on main pushes |
| docker-build | Native amd64/arm64 image builds and PR smoke tests |
| docker-manifest | Main-push multi-arch manifest assembly and Trivy scan |

---

## Job Details

### backend-lint

Validates Python code quality using Ruff (10-100x faster than flake8+black).

```yaml
steps:
  - uv sync --dev
  - uv run ruff check .        # Linting
  - uv run ruff format --check # Formatting
```

**Failure Reasons:**
- Syntax errors
- Import sorting issues
- Code style violations
- Unused imports/variables

**Fix Locally:**
```bash
uv run ruff check . --fix
uv run ruff format .
```

### backend-test

Runs the explicit credential-free list in `.github/workflows/ci.yml`. The list includes auth/broker-key, transport, sandbox, calendar, logging, lifecycle and broker regression tests; it is larger than the original five-test subset. Read the workflow for the current file selection rather than copying that old list. The job uses a 60-second timeout.

### Production Worker Verification

The workflow separately tests the production runtimes: `gunicorn-boot` starts the real launcher with eventlet and gthread, checks Socket.IO polling/WebSocket, SSE, proxy placement, diagnostics and termination. `eventlet-fallback` installs eventlet explicitly so fallback tests run instead of skipping. `gthread-gates` runs the concurrency source gates; `gthread-migration` runs every migration test file with fake brokers and isolated databases. `gthread-platforms` runs the portable subset on Windows, macOS and native Linux ARM64.

The Linux migration job's local equivalent is:

```bash
uv sync
uv pip install "gunicorn>=25.0,<26" "eventlet==0.41.2"
.venv/bin/python -m pytest test/test_gthread_*.py -o addopts="" --timeout=120 -rs
```

Run it on Linux or WSL with the checkout on the Linux filesystem. A green Windows checkout can skip Linux production-worker tests; it is not evidence that this job passed. See the repository runtime constraints and [worker guide](../gthread/README.md).

### frontend-lint

Validates TypeScript/React code using Biome.

```yaml
steps:
  - npm ci
  - npm run lint
```

**Fix Locally:**
```bash
cd frontend
npm run lint -- --write
# or
npm run check
```

### frontend-build

Builds the production React application.

```yaml
steps:
  - npm ci
  - npm run build  # Includes TypeScript check
```

**Artifacts:**
- `frontend-dist` - Built files (7-day retention)

**Failure Reasons:**
- TypeScript type errors
- Import resolution failures
- Build configuration issues

### frontend-test

Runs React unit tests with Vitest.

```yaml
steps:
  - npm ci
  - npm run test:run
  - npm run test:coverage
```

**Artifacts:**
- `coverage-report` - HTML coverage report (7-day retention)

### frontend-e2e

Runs Playwright browser automation tests.

```yaml
steps:
  - npm ci
  - npx playwright install --with-deps chromium
  - npm run e2e -- --project=chromium
```

**Notes:**
- Only runs Chromium for speed (full browser matrix runs locally)
- Uploads report on failure only

**Artifacts (on failure):**
- `playwright-report` - HTML test report

### security-scan

Scans for security vulnerabilities.

```yaml
steps:
  - uv run bandit -r . -x .venv,test,frontend,node_modules -ll
  - uv run pip-audit
```

**Notes:**
- `continue-on-error: true` - Findings are informational
- Results visible in job logs

### docker-build And docker-manifest

Builds the Docker image natively for `linux/amd64` and `linux/arm64`.

```yaml
steps:
  - docker/build-push-action with per-architecture GHA cache
  - on pull requests, load the native image and run a Kaleido/Chromium PNG smoke test
  - on main pushes, push each architecture by digest
  - assemble the digest artifacts into `latest` and SHA-tagged manifest lists
  - run informational Trivy CRITICAL/HIGH scanning on the assembled image
```

**Caching:**
- Uses GitHub Actions cache (`type=gha`)
- Layer caching for fast rebuilds

### commit-dist

After frontend build, lint, and unit tests pass on a main push, this job rebuilds `frontend/dist`, commits a changed artifact with `[skip ci]`, and pushes it with the workflow token.

---

## Security Workflow

**File:** `.github/workflows/security.yml`

**Triggers:**
- Weekly schedule (Monday 2 AM UTC)
- Manual dispatch

### Purpose

Comprehensive security audit that runs independently of CI to:
- Generate SARIF reports for GitHub Security tab
- Audit all dependencies for known vulnerabilities
- Provide detailed security artifacts

### Jobs

```yaml
security-audit:
  - Bandit SARIF report → GitHub Security tab
  - pip-audit JSON report → Artifacts
```

**Artifacts:**
- `security-reports` - Bandit SARIF + pip-audit JSON (30-day retention)

---

## Dependabot

**File:** `.github/dependabot.yml`

Automatically creates PRs for dependency updates.

| Ecosystem | Directory | Schedule | PR Limit |
|-----------|-----------|----------|----------|
| pip | / | Weekly (Monday) | 5 |
| npm | / | Weekly (Monday) | 3 |
| npm | /frontend | Weekly (Monday) | 5 |
| github-actions | / | Weekly | 3 |

**Grouping:** Minor and patch updates are grouped to reduce PR noise.

**Commit Prefixes:**
- `deps(py):` - Python dependencies
- `deps(css):` - Root NPM (Tailwind)
- `deps(frontend):` - React dependencies
- `deps(actions):` - GitHub Actions

---

## Troubleshooting

### CI is slow

1. Check cache hit rate in job logs
2. Ensure `package-lock.json` and `uv.lock` are committed
3. Review if any jobs can be parallelized further

### backend-lint fails

```bash
# Fix automatically
uv run ruff check . --fix
uv run ruff format .
```

### frontend-build fails with type errors

```bash
cd frontend
npx tsc --noEmit  # See all type errors
```

### docker-build fails

1. Check Dockerfile syntax
2. Verify base image availability
3. Check build context (`.dockerignore`)

### Security scan shows vulnerabilities

1. Check if vulnerability has a fix available
2. Update affected dependency: `uv add package@latest`
3. If no fix, evaluate risk and document exception
