# Testing Guide

This guide covers testing practices for the OpenAlgo frontend, including unit tests, E2E tests, and accessibility testing.

## Testing Stack

| Tool | Purpose |
|------|---------|
| Vitest | Unit testing framework |
| Testing Library | React component testing |
| jest-axe | Accessibility testing (unit) |
| Playwright | End-to-end testing |
| @axe-core/playwright | Accessibility testing (E2E) |

## Running Tests

```bash
# Unit tests (watch mode)
npm run test

# Unit tests (single run)
npm run test:run

# Unit tests with coverage
npm run test:coverage

# Accessibility-focused unit tests
npm run test:a11y

# E2E tests (all browsers)
npm run e2e

# E2E tests (with UI)
npm run e2e:ui

# E2E tests (debug mode)
npm run e2e:debug

# E2E codegen (record tests)
npm run e2e:codegen
```

## Unit Testing

### File Structure

```
src/
├── components/
│   └── ui/
│       ├── button.tsx
│       └── button.test.tsx     # Test file next to component
├── config/
│   ├── navigation.ts
│   └── navigation.test.ts
└── test/
    ├── setup.ts               # Test setup
    ├── test-utils.tsx         # Custom render
    └── a11y-utils.ts          # Accessibility helpers
```

### Test Setup

The test setup file (`src/test/setup.ts`) configures:

- Testing Library DOM matchers
- Window/browser API mocks
- Cleanup after each test

```tsx
// src/test/setup.ts
import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

afterEach(() => {
  cleanup()
})

// Mock matchMedia
Object.defineProperty(window, 'matchMedia', {
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  })),
})

// Mock ResizeObserver
global.ResizeObserver = vi.fn().mockImplementation(() => ({
  observe: vi.fn(),
  unobserve: vi.fn(),
  disconnect: vi.fn(),
}))
```

### Custom Render

Use the custom render for components that need providers:

```tsx
// src/test/test-utils.tsx
import { render } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'

function AllTheProviders({ children }) {
  return <BrowserRouter>{children}</BrowserRouter>
}

function customRender(ui, options) {
  return render(ui, { wrapper: AllTheProviders, ...options })
}

export * from '@testing-library/react'
export { customRender as render }
```

### Writing Unit Tests

#### Basic Component Test

```tsx
import { describe, expect, it } from 'vitest'
import { render, screen } from '@/test/test-utils'
import { Button } from './button'

describe('Button', () => {
  it('renders with text', () => {
    render(<Button>Click me</Button>)

    expect(screen.getByRole('button', { name: /click me/i })).toBeInTheDocument()
  })

  it('applies variant classes', () => {
    render(<Button variant="destructive">Delete</Button>)

    const button = screen.getByRole('button')
    expect(button).toHaveAttribute('data-variant', 'destructive')
  })
})
```

#### Testing User Interactions

```tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen, userEvent } from '@/test/test-utils'
import { Button } from './button'

describe('Button interactions', () => {
  it('calls onClick when clicked', async () => {
    const handleClick = vi.fn()
    const user = userEvent.setup()

    render(<Button onClick={handleClick}>Click me</Button>)

    await user.click(screen.getByRole('button'))

    expect(handleClick).toHaveBeenCalledTimes(1)
  })

  it('does not call onClick when disabled', async () => {
    const handleClick = vi.fn()
    const user = userEvent.setup()

    render(<Button disabled onClick={handleClick}>Click me</Button>)

    await user.click(screen.getByRole('button'))

    expect(handleClick).not.toHaveBeenCalled()
  })
})
```

#### Testing with Router

```tsx
import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { MobileBottomNav } from './MobileBottomNav'

function renderWithRouter(initialPath: string) {
  return render(
    <MemoryRouter initialEntries={[initialPath]}>
      <MobileBottomNav />
    </MemoryRouter>
  )
}

describe('MobileBottomNav', () => {
  it('highlights active route', () => {
    renderWithRouter('/dashboard')

    const dashboardLink = screen.getByRole('link', { name: /dashboard/i })
    expect(dashboardLink).toHaveClass('text-primary')
  })
})
```

#### Testing Async Operations

```tsx
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@/test/test-utils'
import { OrderBook } from './OrderBook'

// Mock the API
vi.mock('@/api/orders', () => ({
  ordersApi: {
    getOrderBook: vi.fn().mockResolvedValue([
      { id: '1', symbol: 'RELIANCE', status: 'COMPLETE' },
    ]),
  },
}))

describe('OrderBook', () => {
  it('loads and displays orders', async () => {
    render(<OrderBook />)

    // Wait for loading to complete
    await waitFor(() => {
      expect(screen.getByText('RELIANCE')).toBeInTheDocument()
    })
  })
})
```

### Accessibility Testing (Unit)

```tsx
import { axe, toHaveNoViolations } from 'jest-axe'
import { describe, expect, it } from 'vitest'
import { render } from '@/test/test-utils'
import { Button } from './button'

expect.extend(toHaveNoViolations)

describe('Button accessibility', () => {
  it('has no accessibility violations', async () => {
    const { container } = render(<Button>Click me</Button>)

    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })

  it('icon button needs aria-label', async () => {
    const { container } = render(
      <Button size="icon" aria-label="Close">
        X
      </Button>
    )

    const results = await axe(container)
    expect(results).toHaveNoViolations()
  })
})
```

### Snapshot Testing

```tsx
import { describe, expect, it } from 'vitest'
import { render } from '@/test/test-utils'
import { Badge } from './badge'

describe('Badge', () => {
  it('matches snapshot', () => {
    const { container } = render(<Badge>New</Badge>)
    expect(container).toMatchSnapshot()
  })
})
```

## E2E Testing

### Playwright Configuration

```tsx
// playwright.config.ts
import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  retries: process.env.CI ? 2 : 0,
  reporter: 'html',
  use: {
    baseURL: 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    { name: 'chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'firefox', use: { ...devices['Desktop Firefox'] } },
    { name: 'webkit', use: { ...devices['Desktop Safari'] } },
    { name: 'Mobile Chrome', use: { ...devices['Pixel 5'] } },
    { name: 'Mobile Safari', use: { ...devices['iPhone 12'] } },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
  },
})
```

### Writing E2E Tests

#### Basic Page Test

```tsx
// e2e/home.spec.ts
import { expect, test } from '@playwright/test'

test.describe('Home Page', () => {
  test('should load the home page', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    await expect(page.locator('body')).toBeVisible()
  })

  test('should navigate to login', async ({ page }) => {
    await page.goto('/')

    const loginLink = page.getByRole('link', { name: /login/i })
    if (await loginLink.isVisible()) {
      await loginLink.click()
      await expect(page).toHaveURL(/login/)
    }
  })
})
```

#### Testing Forms

```tsx
// e2e/auth.spec.ts
import { expect, test } from '@playwright/test'

test.describe('Authentication', () => {
  test('should show login form', async ({ page }) => {
    await page.goto('/login')

    await expect(page.locator('input[type="password"]')).toBeVisible()
  })

  test('should handle login', async ({ page }) => {
    await page.goto('/login')

    await page.fill('input[id="username"]', 'testuser')
    await page.fill('input[id="password"]', 'testpass')
    await page.click('button[type="submit"]')

    // Wait for redirect or error
    await page.waitForLoadState('networkidle')
  })
})
```

#### Mobile Testing

```tsx
// e2e/navigation.spec.ts
import { expect, test } from '@playwright/test'

test.describe('Mobile Navigation', () => {
  test.use({ viewport: { width: 375, height: 667 } })

  test('should show bottom navigation', async ({ page }) => {
    await page.goto('/dashboard')
    await page.waitForLoadState('networkidle')

    // Check for bottom nav on mobile
    const bottomNav = page.locator('nav.md\\:hidden')
    if (await bottomNav.isVisible()) {
      await expect(bottomNav).toBeVisible()
    }
  })

  test('should have touch-friendly buttons', async ({ page }) => {
    await page.goto('/dashboard')

    const navLinks = page.locator('.touch-manipulation')
    const count = await navLinks.count()
    expect(count).toBeGreaterThan(0)
  })
})
```

#### Responsive Testing

```tsx
test('should adapt to viewport changes', async ({ page }) => {
  await page.goto('/')

  // Desktop
  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(page.locator('.hidden.md\\:flex')).toBeVisible()

  // Mobile
  await page.setViewportSize({ width: 375, height: 667 })
  await expect(page.locator('.md\\:hidden')).toBeVisible()
})
```

### Accessibility Testing (E2E)

```tsx
// e2e/accessibility.spec.ts
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

test.describe('Accessibility', () => {
  test('home page accessibility scan', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze()

    // Log violations for review
    if (results.violations.length > 0) {
      console.log('Violations:', results.violations.map(v => v.id))
    }

    // Filter critical violations
    const critical = results.violations.filter(
      v => v.impact === 'critical'
    )
    expect(critical).toEqual([])
  })

  test('color contrast check', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const results = await new AxeBuilder({ page })
      .withRules(['color-contrast'])
      .analyze()

    const critical = results.violations.filter(
      v => v.impact === 'critical'
    )
    expect(critical).toEqual([])
  })
})
```

### Visual Regression Testing

```tsx
test('visual regression', async ({ page }) => {
  await page.goto('/dashboard')
  await page.waitForLoadState('networkidle')

  // Full page screenshot
  await expect(page).toHaveScreenshot('dashboard.png', {
    fullPage: true,
    maxDiffPixels: 100,
  })

  // Component screenshot
  const card = page.locator('.card').first()
  await expect(card).toHaveScreenshot('card.png')
})
```

### Test Fixtures

```tsx
// e2e/fixtures.ts
import { test as base } from '@playwright/test'

// Custom fixture with authenticated user
export const test = base.extend({
  authenticatedPage: async ({ page }, use) => {
    // Login before test
    await page.goto('/login')
    await page.fill('#username', 'testuser')
    await page.fill('#password', 'testpass')
    await page.click('button[type="submit"]')
    await page.waitForURL('/dashboard')

    await use(page)
  },
})

// Usage
test('authenticated test', async ({ authenticatedPage }) => {
  await authenticatedPage.goto('/positions')
  // User is already logged in
})
```

## Test Coverage

### Running Coverage

```bash
npm run test:coverage
```

### Coverage Report

Coverage reports are generated in `coverage/` directory:
- `coverage/index.html` - HTML report
- `coverage/lcov.info` - LCOV format

### Coverage Thresholds

Configure in `vitest.config.ts`:

```tsx
export default defineConfig({
  test: {
    coverage: {
      provider: 'v8',
      reporter: ['text', 'json', 'html'],
      exclude: [
        'node_modules/',
        'src/test/',
        '**/*.d.ts',
        '**/*.config.*',
      ],
      // Thresholds (optional)
      // thresholds: {
      //   statements: 80,
      //   branches: 80,
      //   functions: 80,
      //   lines: 80,
      // },
    },
  },
})
```

## Best Practices

### Test Organization

```tsx
describe('ComponentName', () => {
  describe('rendering', () => {
    it('renders with default props', () => {})
    it('renders with custom props', () => {})
  })

  describe('interactions', () => {
    it('handles click', () => {})
    it('handles keyboard', () => {})
  })

  describe('accessibility', () => {
    it('has no violations', () => {})
    it('supports keyboard navigation', () => {})
  })
})
```

### Naming Conventions

```tsx
// Good - describes behavior
it('disables submit button when form is invalid', () => {})
it('shows error message when API fails', () => {})

// Avoid - implementation details
it('sets isDisabled to true', () => {})
it('calls setError with message', () => {})
```

### Testing User Behavior

```tsx
// Good - test what user sees
await user.click(screen.getByRole('button', { name: /submit/i }))
expect(screen.getByText(/success/i)).toBeInTheDocument()

// Avoid - testing implementation
expect(component.state.isSubmitting).toBe(true)
```

### Async Best Practices

```tsx
// Good - use waitFor for async assertions
await waitFor(() => {
  expect(screen.getByText('Loaded')).toBeInTheDocument()
})

// Good - use findBy for async queries
const element = await screen.findByText('Loaded')

// Avoid - arbitrary waits
await new Promise(r => setTimeout(r, 1000))
```

### Mocking Guidelines

```tsx
// Mock at the module level
vi.mock('@/api/orders', () => ({
  ordersApi: {
    getOrders: vi.fn(),
  },
}))

// Reset mocks between tests
beforeEach(() => {
  vi.clearAllMocks()
})

// Provide specific return values per test
it('handles error', async () => {
  vi.mocked(ordersApi.getOrders).mockRejectedValueOnce(
    new Error('Network error')
  )
  // ...
})
```

## Debugging Tests

### Unit Tests

```bash
# Run specific test file
npm run test -- button.test.tsx

# Run tests matching pattern
npm run test -- --grep "accessibility"

# Debug in VS Code
# Add breakpoints and run "Debug Test" from VS Code
```

### E2E Tests

```bash
# Debug mode (step through)
npm run e2e:debug

# UI mode (visual debugging)
npm run e2e:ui

# Record new test
npm run e2e:codegen

# Run specific test
npm run e2e -- --grep "login"

# Headed mode (see browser)
npm run e2e -- --headed
```

### Trace Viewer

```bash
# View trace after failure
npx playwright show-trace test-results/*/trace.zip
```
