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

| Job | Runtime | Purpose |
|-----|---------|---------|
| backend-lint | ~30s | Python code quality |
| backend-test | ~60s | Python unit tests |
| frontend-lint | ~30s | TypeScript/React linting |
| frontend-build | ~90s | Production build verification |
| frontend-test | ~45s | React unit tests |
| frontend-e2e | ~120s | Browser automation tests |
| security-scan | ~45s | Vulnerability detection |
| docker-build | ~180s | Container build + scan |
| root-css-build | ~30s | Tailwind CSS compilation |

**Total Runtime:** ~3-4 minutes (all jobs run in parallel)

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

Runs a minimal CI-safe subset of Python tests that don't require broker credentials.

```yaml
steps:
  - uv sync
  - uv run pytest test/test_log_location.py test/test_navigation_update.py \
      test/test_python_editor.py test/test_rate_limits_simple.py \
      test/test_logout_csrf.py -v --timeout=60
```

**CI-Safe Tests:**
- `test_log_location.py` - Log file path validation
- `test_navigation_update.py` - Navigation structure tests
- `test_python_editor.py` - Editor functionality tests
- `test_rate_limits_simple.py` - Rate limiter configuration tests
- `test_logout_csrf.py` - CSRF protection tests

**Notes:**
- Only runs tests that don't need broker credentials or running app
- Full test suite available locally: `uv run pytest test/ -v`
- 60-second timeout per test

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

### docker-build

Builds and scans the Docker image.

```yaml
steps:
  - docker/build-push-action (with GHA cache)
  - trivy scan for CRITICAL,HIGH vulnerabilities
```

**Caching:**
- Uses GitHub Actions cache (`type=gha`)
- Layer caching for fast rebuilds

### root-css-build

Builds the Tailwind CSS for Jinja templates.

```yaml
steps:
  - npm ci
  - npm run build  # PostCSS + Tailwind
```

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
