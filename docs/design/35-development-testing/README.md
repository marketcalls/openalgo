# 35 - Development & Testing Guide

## Overview

This guide covers running OpenAlgo in development and production modes using the uv package manager, along with comprehensive testing strategies including unit tests, E2E tests, accessibility tests, and linting.

## Running the Application

### Development Mode

```bash
# Navigate to project directory
cd /path/to/openalgo

# Copy environment file (first time only)
cp .sample.env .env

# Generate secure keys
uv run python -c "import secrets; print(secrets.token_hex(32))"
# Copy output to APP_KEY and API_KEY_PEPPER in .env

# Run in development mode
uv run app.py
```

**Development Features:**
- Auto-reload on code changes
- Debug mode enabled (if `FLASK_DEBUG=True`)
- Detailed error messages
- SocketIO development server

### Production Mode (Linux with Gunicorn)

```bash
# Install production dependencies
uv sync

# Run with Gunicorn + Eventlet
uv run gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:5000 app:app

# IMPORTANT: Use -w 1 (single worker) for WebSocket compatibility
```

**Production Configuration:**
```bash
# .env settings for production
FLASK_DEBUG=False
FLASK_ENV=production
HOST_SERVER=https://yourdomain.com
```

### Docker Mode

```bash
# Build and run
docker-compose up -d

# View logs
docker-compose logs -f
```

## Frontend Development (React)

### Setup

```bash
cd frontend

# Install dependencies
npm install
```

### Development Server

```bash
# Start Vite dev server with hot reload
npm run dev

# Access at http://localhost:5173
# Proxies API requests to Flask backend
```

### Build for Production

```bash
# TypeScript compile + Vite build
npm run build

# Preview production build locally
npm run preview
```

## Testing Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                        Testing Architecture                                   │
└──────────────────────────────────────────────────────────────────────────────┘

┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐
│   Unit Tests    │  │  E2E Tests      │  │ Accessibility   │  │   Linting    │
│   (Vitest)      │  │  (Playwright)   │  │ (axe-core)      │  │   (Biome)    │
└────────┬────────┘  └────────┬────────┘  └────────┬────────┘  └──────┬───────┘
         │                    │                    │                   │
         ▼                    ▼                    ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                           React Frontend                                     │
│                         (frontend/src/)                                      │
└─────────────────────────────────────────────────────────────────────────────┘
         │                    │                    │                   │
         ▼                    ▼                    ▼                   ▼
┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  ┌──────────────┐
│  Components     │  │  Full Pages     │  │   WCAG 2.1      │  │  Code Style  │
│  Functions      │  │  User Flows     │  │   Compliance    │  │  Formatting  │
│  Hooks          │  │  API Mocks      │  │                 │  │              │
└─────────────────┘  └─────────────────┘  └─────────────────┘  └──────────────┘
```

## Unit Testing (Vitest)

### Running Tests

```bash
cd frontend

# Run all tests
npm test

# Run tests once (CI mode)
npm run test:run

# Run with coverage report
npm run test:coverage

# Run with UI
npm run test:ui
```

### Test File Structure

```
frontend/
├── src/
│   ├── components/
│   │   ├── Button.tsx
│   │   └── Button.test.tsx      # Component tests
│   ├── hooks/
│   │   ├── useAuth.ts
│   │   └── useAuth.test.ts      # Hook tests
│   └── utils/
│       ├── format.ts
│       └── format.test.ts       # Utility tests
└── vitest.config.ts
```

### Example Test

```typescript
// src/components/Button.test.tsx
import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { Button } from './Button';

describe('Button', () => {
  it('renders with text', () => {
    render(<Button>Click me</Button>);
    expect(screen.getByText('Click me')).toBeInTheDocument();
  });

  it('calls onClick when clicked', () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Click</Button>);
    fireEvent.click(screen.getByText('Click'));
    expect(handleClick).toHaveBeenCalledTimes(1);
  });
});
```

## E2E Testing (Playwright)

### Running E2E Tests

```bash
cd frontend

# Run all E2E tests
npm run e2e

# Run with UI mode (visual debugging)
npm run e2e:ui

# Run in debug mode
npm run e2e:debug

# Generate test code interactively
npm run e2e:codegen
```

### E2E Test Structure

```
frontend/
├── e2e/
│   ├── login.spec.ts        # Login flow tests
│   ├── dashboard.spec.ts    # Dashboard tests
│   └── orders.spec.ts       # Order placement tests
└── playwright.config.ts
```

### Example E2E Test

```typescript
// e2e/login.spec.ts
import { test, expect } from '@playwright/test';

test.describe('Login Flow', () => {
  test('successful login redirects to dashboard', async ({ page }) => {
    await page.goto('/auth/login');

    await page.fill('[name="username"]', 'admin');
    await page.fill('[name="password"]', 'password123');
    await page.click('button[type="submit"]');

    await expect(page).toHaveURL('/dashboard');
    await expect(page.locator('h1')).toContainText('Dashboard');
  });

  test('invalid credentials shows error', async ({ page }) => {
    await page.goto('/auth/login');

    await page.fill('[name="username"]', 'wrong');
    await page.fill('[name="password"]', 'wrong');
    await page.click('button[type="submit"]');

    await expect(page.locator('.error-message')).toBeVisible();
  });
});
```

## Accessibility Testing (axe-core)

### Running A11y Tests

```bash
cd frontend

# Run accessibility-specific tests
npm run test:a11y
```

### A11y Test Libraries

| Library | Purpose |
|---------|---------|
| `@axe-core/react` | Runtime a11y checking in dev |
| `@axe-core/playwright` | E2E a11y testing |
| `jest-axe` | Unit test a11y assertions |
| `vitest-axe` | Vitest a11y matchers |

### Example A11y Test

```typescript
// src/components/Dialog.test.tsx
import { render } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';
import { Dialog } from './Dialog';

expect.extend(toHaveNoViolations);

describe('Dialog accessibility', () => {
  it('should have no accessibility violations', async () => {
    const { container } = render(
      <Dialog open={true} title="Test Dialog">
        <p>Dialog content</p>
      </Dialog>
    );

    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
```

### Playwright A11y Test

```typescript
// e2e/accessibility.spec.ts
import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

test.describe('Page accessibility', () => {
  test('dashboard has no a11y violations', async ({ page }) => {
    await page.goto('/dashboard');

    const results = await new AxeBuilder({ page }).analyze();

    expect(results.violations).toEqual([]);
  });
});
```

## Linting & Formatting (Biome)

### Running Biome

```bash
cd frontend

# Lint code
npm run lint

# Format code
npm run format

# Lint + format in one command
npm run check
```

### Biome Configuration

**Location:** `frontend/biome.json`

```json
{
  "formatter": {
    "enabled": true,
    "indentStyle": "tab",
    "lineWidth": 100
  },
  "linter": {
    "enabled": true,
    "rules": {
      "recommended": true,
      "complexity": {
        "noForEach": "warn"
      },
      "style": {
        "noNonNullAssertion": "warn"
      }
    }
  }
}
```

### Biome vs ESLint/Prettier

| Feature | Biome | ESLint + Prettier |
|---------|-------|-------------------|
| Speed | 10-100x faster | Slower |
| Config | Single file | Multiple configs |
| Memory | Low | Higher |
| Setup | Zero config | Complex setup |

## Backend Testing (Python)

### Running Backend Tests

```bash
# Run all tests
uv run pytest test/ -v

# Run specific test file
uv run pytest test/test_broker.py -v

# Run single test function
uv run pytest test/test_broker.py::test_function_name -v

# Run with coverage
uv run pytest test/ --cov
```

### Test Structure

```
openalgo/
└── test/
    ├── test_broker.py            # Broker integration tests
    ├── test_rate_limits_simple.py # Rate limit tests
    ├── test_api.py               # API endpoint tests
    └── conftest.py               # Shared fixtures
```

## CI/CD Pipeline Example

```yaml
# .github/workflows/test.yml
name: Test

on: [push, pull_request]

jobs:
  frontend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Node
        uses: actions/setup-node@v4
        with:
          node-version: '20'

      - name: Install dependencies
        run: cd frontend && npm ci

      - name: Lint
        run: cd frontend && npm run lint

      - name: Unit tests
        run: cd frontend && npm run test:run

      - name: Build
        run: cd frontend && npm run build

      - name: E2E tests
        run: cd frontend && npm run e2e

  backend:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'

      - name: Install uv
        run: pip install uv

      - name: Run tests
        run: uv run pytest test/ -v
```

## Command Reference

### Backend Commands

| Command | Description |
|---------|-------------|
| `uv run app.py` | Start development server |
| `uv run pytest test/ -v` | Run all tests |
| `uv add package_name` | Add new dependency |
| `uv sync` | Sync dependencies |

### Frontend Commands

| Command | Description |
|---------|-------------|
| `npm run dev` | Start dev server |
| `npm run build` | Production build |
| `npm test` | Run unit tests |
| `npm run e2e` | Run E2E tests |
| `npm run test:a11y` | Run accessibility tests |
| `npm run lint` | Lint code |
| `npm run format` | Format code |
| `npm run check` | Lint + format |

## Key Files Reference

| File | Purpose |
|------|---------|
| `frontend/package.json` | Frontend scripts and dependencies |
| `frontend/vitest.config.ts` | Unit test configuration |
| `frontend/playwright.config.ts` | E2E test configuration |
| `frontend/biome.json` | Linting/formatting rules |
| `pyproject.toml` | Python dependencies |
| `test/` | Backend test files |
