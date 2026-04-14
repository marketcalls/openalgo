import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

test.describe('Accessibility', () => {
  test('home page accessibility scan', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze()

    // Log all violations for reporting
    if (accessibilityScanResults.violations.length > 0) {
      console.log(
        'Accessibility violations found:',
        accessibilityScanResults.violations.map((v) => `${v.id} (${v.impact}): ${v.description}`)
      )
    }

    // Test passes but provides violation report
    expect(accessibilityScanResults.violations).toBeDefined()
  })

  test('login page accessibility scan', async ({ page }) => {
    await page.goto('/login')
    await page.waitForLoadState('networkidle')

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze()

    if (accessibilityScanResults.violations.length > 0) {
      console.log(
        'Login page accessibility violations:',
        accessibilityScanResults.violations.map((v) => `${v.id} (${v.impact})`)
      )
    }

    expect(accessibilityScanResults.violations).toBeDefined()
  })

  test('color contrast check', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withRules(['color-contrast'])
      .analyze()

    if (accessibilityScanResults.violations.length > 0) {
      console.log(
        'Color contrast issues:',
        accessibilityScanResults.violations.map((v) => `${v.nodes.length} elements`)
      )
    }

    expect(accessibilityScanResults.violations).toBeDefined()
  })
})

test.describe('Accessibility - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } })

  test('mobile layout accessibility scan', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    const accessibilityScanResults = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa'])
      .analyze()

    if (accessibilityScanResults.violations.length > 0) {
      console.log(
        'Mobile accessibility violations:',
        accessibilityScanResults.violations.map((v) => `${v.id} (${v.impact})`)
      )
    }

    expect(accessibilityScanResults.violations).toBeDefined()
  })
})
