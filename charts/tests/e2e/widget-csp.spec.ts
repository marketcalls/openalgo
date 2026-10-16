import { expect, test, type Page } from '@playwright/test';

// Fixed only for this fixture. A deployed host supplies a fresh response nonce.
const NONCE = 'openalgo-widget-csp-test';
const SETTINGS = '.oac-topbar button[aria-label="Chart settings"]';
const DIALOG = '.oac-dialog[role="dialog"]';

type SheetMode = 'fresh' | 'placeholder' | 'placeholder-without-nonce' | 'populated';

async function mount(page: Page, mode: SheetMode = 'fresh', nonce: string | null = NONCE): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(String(error)));
  await page.addInitScript(() => {
    (window as any).__cspViolations = [];
    document.addEventListener('securitypolicyviolation', (event) => {
      (window as any).__cspViolations.push(event.effectiveDirective);
    });
  });
  await page.setViewportSize({ width: 1500, height: 700 });
  const placeholder = mode === 'placeholder' || mode === 'placeholder-without-nonce'
    ? `<style id="oac-widget-css"${mode === 'placeholder' ? ` nonce="${NONCE}"` : ''}></style>`
    : '';
  await page.route('**/widget-csp-fixture.html', (route) => route.fulfill({
    contentType: 'text/html',
    headers: {
      // A stylesheet nonce does not authorize style attributes. This policy
      // allows those separately for the host layout and widget's dynamic UI.
      'Content-Security-Policy': `default-src 'self'; script-src 'self'; style-src-elem 'nonce-${NONCE}'; style-src-attr 'unsafe-inline'; img-src 'self' data:`,
    },
    body: `<!doctype html><html><head><meta charset="utf-8">
      <style nonce="${NONCE}">body{margin:0;display:flex;background:#0d0e12}.host{width:750px;height:650px}</style>
      ${placeholder}</head><body><div id="first" class="host"></div><div id="second" class="host"></div></body></html>`,
  }));
  await page.goto('/widget-csp-fixture.html');
  if (mode === 'placeholder-without-nonce') {
    // The parser rejects even an empty unnonced style before the widget runs.
    // Hydration can apply its CSS, but cannot undo that host markup violation.
    await expect.poll(() => page.evaluate(() => (window as any).__cspViolations)).toEqual(['style-src-elem']);
    await page.evaluate(() => { (window as any).__cspViolations = []; });
  }
  await page.evaluate(async ({ mode, nonce, hostNonce }) => {
    const moduleUrl = '/dist/openalgo-charts.widget.mjs';
    const { createWidget, WIDGET_CSS, WIDGET_STYLE_ID, DIALOG_CSS, EVENT_DETAILS_CSS } = await import(moduleUrl);
    if (mode === 'populated') {
      const sheet = document.createElement('style');
      sheet.id = WIDGET_STYLE_ID;
      sheet.nonce = hostNonce;
      sheet.textContent = WIDGET_CSS + DIALOG_CSS + EVENT_DETAILS_CSS + '.oac-widget { outline: 3px solid rgb(1, 2, 3); }';
      document.head.appendChild(sheet);
    }
    (window as any).__originalSheet = document.getElementById(WIDGET_STYLE_ID);
    (window as any).__originalCSS = (window as any).__originalSheet?.textContent;
    const bars = Array.from({ length: 100 }, (_, i) => ({
      time: 1_700_000_000 + i * 300,
      open: 100 + Math.sin(i / 4), high: 103 + Math.sin(i / 4),
      low: 97 + Math.sin(i / 4), close: 101 + Math.sin(i / 4), volume: 100 + i,
    }));
    (window as any).__widgets = ['first', 'second'].map((id, index) => {
      const widget = createWidget(document.getElementById(id), {
        ...(nonce === null ? {} : { styleNonce: nonce }),
        theme: index === 0 ? 'dark' : 'light',
      });
      widget.series.setData(bars);
      widget.chart.fitContent();
      return widget;
    });
  }, { mode, nonce, hostNonce: NONCE });
  return errors;
}

async function expectStyledWidgets(page: Page): Promise<void> {
  await expect(page.locator('style#oac-widget-css')).toHaveCount(1);
  await expect(page.locator('style#oac-event-details-style')).toHaveCount(0);
  // The content attribute may be hidden or absent; the IDL property is authoritative.
  expect(await page.locator('style#oac-widget-css').evaluate((node: HTMLStyleElement) => node.nonce)).toBe(NONCE);
  for (const id of ['first', 'second']) {
    const host = page.locator(`#${id}`);
    await expect(host.locator('.oac-widget')).toHaveCSS('display', 'grid');
    await expect(host.locator('.oac-rail')).toBeVisible();
    expect((await host.locator('.oac-rail').boundingBox())!.width).toBeGreaterThan(20);
    await host.locator(SETTINGS).click();
    await expect(host.locator(DIALOG)).toBeVisible();
    await expect(host.locator(DIALOG)).toHaveCSS('display', 'flex');
    // These rules come from DIALOG_CSS, so testing only the shell is insufficient.
    await expect(host.locator('.oac-settings__main')).toHaveCSS('display', 'grid');
    await expect(host.locator('.oac-form')).toHaveCSS('display', 'grid');
    await host.locator(`${DIALOG} button[aria-label="Close"]`).click();
  }
  await expect.poll(() => page.evaluate(() => (window as any).__cspViolations)).toEqual([]);
}

test('styleNonce authorizes one shared stylesheet and both widgets dialogs', async ({ page }, testInfo) => {
  const errors = await mount(page);
  await expectStyledWidgets(page);
  await page.locator('#first').locator(SETTINGS).click();
  await page.screenshot({ path: testInfo.outputPath('widget-csp.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('hydrates a nonced SSR placeholder while preserving its original nonce', async ({ page }) => {
  const errors = await mount(page, 'placeholder', 'different-nonce');
  await expectStyledWidgets(page);
  expect(await page.evaluate(() => document.getElementById('oac-widget-css') === (window as any).__originalSheet)).toBe(true);
  expect(errors).toEqual([]);
});

test('sets the nonce before filling a connected SSR placeholder', async ({ page }) => {
  const errors = await mount(page, 'placeholder-without-nonce');
  await expectStyledWidgets(page);
  expect(await page.evaluate(() => document.getElementById('oac-widget-css') === (window as any).__originalSheet)).toBe(true);
  expect(errors).toEqual([]);
});

test('preserves populated host CSS and its nonce across widget creation', async ({ page }) => {
  const errors = await mount(page, 'populated', 'different-nonce');
  await expectStyledWidgets(page);
  await expect(page.locator('#first .oac-widget')).toHaveCSS('outline-color', 'rgb(1, 2, 3)');
  expect(await page.evaluate(() => {
    const sheet = document.getElementById('oac-widget-css');
    return sheet === (window as any).__originalSheet && sheet!.textContent === (window as any).__originalCSS;
  })).toBe(true);
  expect(errors).toEqual([]);
});

test('a part that loads on first use runs under the script policy and styles itself through the nonced sheet', async ({ page }) => {
  const errors = await mount(page);
  const chart = await page.locator('#first .oac-chart').boundingBox();
  await page.mouse.move(chart!.x + chart!.width / 2, chart!.y + chart!.height / 2);
  // The shortcuts panel is not in the tier file: `script-src 'self'` lets its
  // file load, and its rules join the one sheet, whose nonce still covers them.
  await page.keyboard.press('Shift+Slash');
  await expect(page.locator('#first .oac-keys-dialog')).toBeVisible();
  await expect(page.locator('#first .oac-keys__acts').first()).toHaveCSS('min-width', '118px');
  await expect(page.locator('style')).toHaveCount(2);
  expect(await page.locator('style#oac-widget-css').evaluate((node: HTMLStyleElement) => node.nonce)).toBe(NONCE);
  await expect.poll(() => page.evaluate(() => (window as any).__cspViolations)).toEqual([]);
  expect(errors).toEqual([]);
});

test('the strict stylesheet policy blocks the widget when no nonce is supplied', async ({ page }) => {
  const errors = await mount(page, 'fresh', null);
  await expect(page.locator('#first .oac-widget')).toHaveCSS('display', 'block');
  await expect.poll(() => page.evaluate(() => (window as any).__cspViolations)).toEqual(['style-src-elem']);
  expect(errors).toEqual([]);
});
