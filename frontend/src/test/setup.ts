import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach, vi } from 'vitest'

// Cleanup after each test case
afterEach(() => {
  cleanup()
})

// Mock window.matchMedia for tests
Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: vi.fn().mockImplementation((query) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: vi.fn(),
    removeListener: vi.fn(),
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })),
})

// Mock ResizeObserver.
//
// A real class, not vi.fn().mockImplementation(). A vi.fn mock cannot be
// called with `new` here, and @floating-ui constructs one directly, so any
// test that opened a Radix dropdown, select or popover died on
// "is not a constructor" from inside autoUpdate.
class MockResizeObserver {
  observe() {}
  unobserve() {}
  disconnect() {}
}
window.ResizeObserver = MockResizeObserver as unknown as typeof ResizeObserver

// Mock IntersectionObserver.
//
// A real class, for exactly the reason ResizeObserver above is one: a
// vi.fn().mockImplementation() cannot be called with `new`, so any component
// that observes an element to find out whether it is on screen died on
// "is not a constructor" inside its mount effect, before the assertion ran.
//
// It never reports, which means a component that gates behaviour on visibility
// keeps whatever it assumed on mount. Those components assume visible, because
// a real observer reports the current state on its first callback and no
// observer at all must not leave a card mute forever.
class MockIntersectionObserver {
  readonly root = null
  readonly rootMargin = ''
  readonly thresholds: number[] = []
  observe() {}
  unobserve() {}
  disconnect() {}
  takeRecords(): IntersectionObserverEntry[] {
    return []
  }
}
window.IntersectionObserver = MockIntersectionObserver as unknown as typeof IntersectionObserver

// Mock scrollTo
window.scrollTo = vi.fn()

// Pointer-capture and scrollIntoView are used by Radix's Select, Dropdown and
// Popover primitives but are not implemented by jsdom, so without these any
// test that opens one dies with "target.hasPointerCapture is not a function"
// before the assertion runs.
window.HTMLElement.prototype.hasPointerCapture = vi.fn(() => false)
window.HTMLElement.prototype.setPointerCapture = vi.fn()
window.HTMLElement.prototype.releasePointerCapture = vi.fn()
window.HTMLElement.prototype.scrollIntoView = vi.fn()

// Mock clipboard API
Object.assign(navigator, {
  clipboard: {
    writeText: vi.fn().mockImplementation(() => Promise.resolve()),
    readText: vi.fn().mockImplementation(() => Promise.resolve('')),
  },
})
