# CI/CD Local Development Guide

## Overview

This guide explains how to run the same checks locally that run in CI, ensuring your code passes before pushing.

## Prerequisites

- Python 3.12+
- Node.js 20+ (22 recommended)
- uv package manager (`pip install uv`)
- Git

---

## Quick Start

```bash
# One-time setup: Install pre-commit hooks
pip install pre-commit
pre-commit install

# Run all checks before committing
pre-commit run --all-files

# Run backend tests
uv run pytest test/ -v

# Run frontend tests
cd frontend && npm test
```

---

## Pre-commit Hooks

Pre-commit hooks run automatically before each commit, catching issues early.

### Installation

```bash
# Install pre-commit tool
pip install pre-commit

# Install hooks for this repository
pre-commit install

# Verify installation
pre-commit --version
```

### What Runs on Commit

| Hook | Purpose | Auto-fix |
|------|---------|----------|
| Ruff check | Python linting | Yes |
| Ruff format | Python formatting | Yes |
| Biome check | TypeScript/React linting | Yes |
| detect-secrets | Secrets detection | No |
| trailing-whitespace | Remove trailing whitespace | Yes |
| end-of-file-fixer | Ensure newline at EOF | Yes |
| check-yaml | Validate YAML syntax | No |
| check-json | Validate JSON syntax | No |
| check-added-large-files | Prevent >1MB files | No |

### Manual Execution

```bash
# Run all hooks on all files
pre-commit run --all-files

# Run specific hook
pre-commit run ruff --all-files

# Run on specific files
pre-commit run --files src/app.py

# Skip hooks (emergency only)
git commit --no-verify -m "message"
```

### Updating Hooks

```bash
# Update to latest versions
pre-commit autoupdate

# Test updated hooks
pre-commit run --all-files
```

---

## Backend Development

### Python Linting with Ruff

Ruff is 10-100x faster than flake8+black combined.

```bash
# Check for issues
uv run ruff check .

# Auto-fix issues
uv run ruff check . --fix

# Check formatting
uv run ruff format --check .

# Auto-format
uv run ruff format .
```

### Running Tests

```bash
# Run all tests
uv run pytest test/ -v

# Run with timeout (matches CI)
uv run pytest test/ -v --timeout=60

# Run specific test file
uv run pytest test/test_broker.py -v

# Run single test
uv run pytest test/test_broker.py::test_function_name -v

# Run with coverage
uv run pytest test/ --cov

# Skip sandbox tests (require running app)
uv run pytest test/ -v --ignore=test/sandbox
```

### Security Scanning

```bash
# Bandit static analysis
uv run bandit -r . -x .venv,test,frontend,node_modules -ll

# pip-audit vulnerability check
uv run pip-audit
```

---

## Frontend Development

### TypeScript/React Linting with Biome

```bash
cd frontend

# Check for issues
npm run lint

# Auto-fix issues
npm run lint -- --write

# Full check (lint + format)
npm run check
```

### Running Tests

```bash
cd frontend

# Run unit tests (watch mode)
npm test

# Run once (CI mode)
npm run test:run

# Run with coverage
npm run test:coverage

# Run E2E tests
npm run e2e

# Run E2E with UI
npm run e2e -- --ui

# Run specific E2E project
npm run e2e -- --project=chromium
```

### Building

```bash
cd frontend

# Development build
npm run dev

# Production build
npm run build

# Preview production build
npm run preview
```

---

## Root CSS Development

For Jinja2 templates (not React frontend).

```bash
# From repository root (not frontend/)

# Development mode (watch for changes)
npm run dev

# Production build
npm run build

# NEVER edit static/css/main.css directly!
# Edit src/css/styles.css instead
```

---

## IDE Integration

### VS Code

**Recommended Extensions:**
- Python (Microsoft)
- Ruff (Astral Software)
- Biome (biomejs.biome)
- Tailwind CSS IntelliSense

**Settings (.vscode/settings.json):**
```json
{
  "editor.formatOnSave": true,
  "[python]": {
    "editor.defaultFormatter": "charliermarsh.ruff",
    "editor.codeActionsOnSave": {
      "source.fixAll.ruff": "explicit",
      "source.organizeImports.ruff": "explicit"
    }
  },
  "[typescript][typescriptreact]": {
    "editor.defaultFormatter": "biomejs.biome"
  },
  "python.testing.pytestEnabled": true,
  "python.testing.pytestArgs": ["test/"]
}
```

### PyCharm / WebStorm

1. **Ruff:** Settings > Tools > File Watchers > Add Ruff
2. **Biome:** Install Biome plugin from marketplace
3. **pytest:** Settings > Tools > Python Integrated Tools > pytest

---

## Common Issues

### Pre-commit hook fails

```bash
# Update hooks
pre-commit autoupdate

# Clear cache
pre-commit clean

# Reinstall hooks
pre-commit uninstall
pre-commit install
```

### Ruff not finding config

Ensure you're running from repository root where `pyproject.toml` exists.

### Frontend tests fail with module errors

```bash
cd frontend
rm -rf node_modules
npm ci
npm test
```

### E2E tests fail - browser not found

```bash
cd frontend
npx playwright install --with-deps
```

### Python import errors

```bash
# Sync dependencies
uv sync

# Verify Python version
uv run python --version  # Should be 3.12+
```

---

## CI Parity Checklist

Before pushing, verify locally:

- [ ] `pre-commit run --all-files` passes
- [ ] `uv run pytest test/ -v --ignore=test/sandbox` passes
- [ ] `cd frontend && npm run lint` passes
- [ ] `cd frontend && npm run build` succeeds
- [ ] `cd frontend && npm run test:run` passes
- [ ] `npm run build` (root CSS) succeeds

If all pass locally, CI should pass too.
