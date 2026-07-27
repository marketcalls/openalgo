import { configureAxe, toHaveNoViolations } from 'jest-axe'
import { expect } from 'vitest'

// Extend Vitest's expect with accessibility matchers
expect.extend(toHaveNoViolations)

// Configure axe with rules appropriate for our app
export const axe = configureAxe({
  rules: {
    // Disable rules that may not apply to all components
    region: { enabled: false }, // Components may not have landmarks
    'color-contrast': { enabled: true },
    'aria-allowed-attr': { enabled: true },
    'aria-required-attr': { enabled: true },
    'aria-valid-attr': { enabled: true },
    'button-name': { enabled: true },
    'image-alt': { enabled: true },
    label: { enabled: true },
    'link-name': { enabled: true },
  },
})

// Helper to run accessibility tests
export async function checkA11y(container: Element) {
  const results = await axe(container)
  expect(results).toHaveNoViolations()
}
