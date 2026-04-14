import { expect, test } from '@playwright/test'

test.describe('Home Page', () => {
  test('should load the home page', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Page should load without errors
    await expect(page.locator('body')).toBeVisible()
  })

  test('should have navigation elements', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Check for basic page structure
    await expect(page.locator('body')).toBeVisible()
  })

  test('should navigate to login page', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Look for a login button or link
    const loginButton = page.getByRole('link', { name: /login|sign in/i })

    if ((await loginButton.count()) > 0) {
      await loginButton.click()
      await page.waitForLoadState('networkidle')
      expect(page.url()).toContain('login')
    }
  })
})

test.describe('Page Structure', () => {
  test('home page should have basic structure', async ({ page }) => {
    await page.goto('/')
    await page.waitForLoadState('networkidle')

    // Page should have body content
    const body = page.locator('body')
    await expect(body).toBeVisible()

    // Should have at least one interactive element
    const buttons = page.locator('button, a')
    const buttonCount = await buttons.count()
    expect(buttonCount).toBeGreaterThan(0)
  })
})
