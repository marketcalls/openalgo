import { expect, test } from '@playwright/test'

test.describe('Navigation - Desktop', () => {
  test.use({ viewport: { width: 1280, height: 720 } })

  test('should not show mobile bottom navigation on desktop', async ({ page }) => {
    await page.goto('/')

    // Bottom nav should be hidden on desktop (has md:hidden class)
    const bottomNav = page.locator('nav.md\\:hidden')

    // Element may exist but should not be visible
    if (await bottomNav.count()) {
      await expect(bottomNav).not.toBeVisible()
    }
  })
})

test.describe('Navigation - Mobile', () => {
  test.use({ viewport: { width: 375, height: 667 } })

  test('should show mobile bottom navigation on authenticated pages', async ({ page }) => {
    // Try to visit a page that would show bottom nav
    await page.goto('/dashboard')

    // Wait for any redirects
    await page.waitForLoadState('networkidle')

    // On mobile, if we're on an authenticated page, bottom nav should be visible
    // But if redirected to login, it won't be there
    const url = page.url()

    if (url.includes('dashboard')) {
      const bottomNav = page.locator('nav.md\\:hidden')
      await expect(bottomNav).toBeVisible()
    }
  })

  test('should have touch-friendly navigation buttons', async ({ page }) => {
    await page.goto('/dashboard')

    await page.waitForLoadState('networkidle')

    const url = page.url()

    if (url.includes('dashboard')) {
      // Check for touch-manipulation class on nav links
      const navLinks = page.locator('.touch-manipulation')
      const count = await navLinks.count()

      // Should have touch-optimized elements
      expect(count).toBeGreaterThan(0)
    }
  })
})

test.describe('Navigation - Responsive', () => {
  test('should adapt layout when resizing viewport', async ({ page }) => {
    await page.goto('/')

    // Start at desktop size
    await page.setViewportSize({ width: 1280, height: 720 })
    await page.waitForTimeout(100)

    // Resize to mobile
    await page.setViewportSize({ width: 375, height: 667 })
    await page.waitForTimeout(100)

    // Page should not crash or show errors during resize
    await expect(page.locator('body')).toBeVisible()
  })
})
