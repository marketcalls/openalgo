import { test, expect, type Page, type Request } from '@playwright/test';

// The widget's parts that load on first use, fetched by the browser itself
// from the files the build writes beside the tier, in all three engines. The
// unit suite holds the parts back in memory; here a plain widget is shown to
// fetch none of them, a part is slowed and failed on the wire, and a grid's
// bar arrives into a strip that already has its height.

// A part's file name carries a content hash (rollup.config.js), so a request
// is routed and recorded by the part's name, whatever its hash in this build.
const PART = /\/dist\/openalgo-charts\.widget\.([a-z-]+)-[\w-]{8}\.mjs$/;
const part = (name: string): string => `**/dist/openalgo-charts.widget.${name}-*.mjs`;
const DIALOG = '.oac-keys-dialog';

async function mount(page: Page, path: string): Promise<{ errors: string[]; parts: string[] }> {
  const errors: string[] = [];
  const parts: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  page.on('request', (r: Request) => { const name = PART.exec(new URL(r.url()).pathname)?.[1]; if (name) parts.push(name); });
  await page.setViewportSize({ width: 1180, height: 760 });
  // Not "load": a part held back on purpose is a fetch some engines count toward it.
  await page.goto(path, { waitUntil: 'domcontentloaded' });
  return { errors, parts };
}

async function mountWidget(page: Page): Promise<{ errors: string[]; parts: string[] }> {
  const seen = await mount(page, '/tests/e2e/widget-keymap-fixture.html');
  await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0);
  // The pointer over the chart, which is where the widget's chords apply.
  const box = await page.locator('.oac-widget .oac-chart').boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  return seen;
}

test('a plain widget fetches no part, and ? fetches the shortcuts panel once', async ({ page }) => {
  const { errors, parts } = await mountWidget(page);
  await page.waitForTimeout(300);
  expect(parts).toEqual([]);
  await page.keyboard.press('Shift+Slash');
  await expect(page.locator(DIALOG)).toBeVisible();
  // Its editor rules joined the widget's one sheet.
  await expect(page.locator(`${DIALOG}`)).toHaveCSS('width', '880px');
  expect(await page.locator('style#oac-widget-css').count()).toBe(1);
  await page.keyboard.press('Escape');
  await expect(page.locator(DIALOG)).toHaveCount(0);
  await page.keyboard.press('Shift+Slash');
  await expect(page.locator(DIALOG)).toBeVisible();
  expect(parts).toEqual(['keymap-editor']);
  expect(errors).toEqual([]);
});

test('a slow part opens once it arrives, once however often ? is pressed meanwhile', async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route(part('keymap-editor'), async (route) => { await held; await route.continue(); });
  const { errors } = await mountWidget(page);
  await page.keyboard.press('Shift+Slash');
  await page.keyboard.press('Shift+Slash');
  await page.waitForTimeout(400);
  await expect(page.locator(DIALOG)).toHaveCount(0);
  release();
  await expect(page.locator(DIALOG)).toBeVisible();
  await page.waitForTimeout(200);
  await expect(page.locator(DIALOG)).toHaveCount(1);
  expect(errors).toEqual([]);
});

test('a part that cannot load says so on each press, and the widget goes on working', async ({ page }) => {
  let fail = true;
  await page.route(part('keymap-editor'), (route) => (fail ? route.abort('failed') : route.continue()));
  const { errors } = await mountWidget(page);
  await page.keyboard.press('Shift+Slash');
  const toast = page.locator('.oac-toast', { hasText: 'Keyboard shortcuts could not load' });
  await expect(toast).toHaveCount(1);
  await expect(page.locator(DIALOG)).toHaveCount(0);
  // A chord that needs no part still answers.
  await page.keyboard.press('Alt+KeyT');
  expect(await page.evaluate(() => (window as any).__widget.draw.activeTool())).toBe('trend-line');
  await page.keyboard.press('Escape');
  // The widget asks again; a browser keeps a failed module fetch for the
  // life of the page, so the next press is told the same, not left waiting.
  fail = false;
  await page.keyboard.press('Shift+Slash');
  await expect(toast).toHaveCount(2);
  // A reload fetches it.
  await page.reload();
  await page.waitForFunction(() => (window as any).__ready === true && (window as any).__loaded > 0);
  const box = await page.locator('.oac-widget .oac-chart').boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.keyboard.press('Shift+Slash');
  await expect(page.locator(DIALOG)).toBeVisible();
  expect(errors).toEqual([]);
});

test('a grid bar arrives into a strip that already has its height, so the charts do not move', async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route(part('grid-bar'), async (route) => { await held; await route.continue(); });
  const { errors, parts } = await mount(page, '/tests/e2e/widget-grid-fixture.html?toolbar=1&preset=2x2');
  const strip = page.locator('.oac-grid__bar');
  await expect(strip).toHaveAttribute('role', 'toolbar');
  await expect(page.locator('.oac-grid__cell').first()).toBeVisible();
  const before = await page.locator('.oac-grid__cells').boundingBox();
  const height = (await strip.boundingBox())!.height;
  expect(height).toBeGreaterThan(30);
  await expect(strip.locator('.oac-grid__layout')).toHaveCount(0);
  release();
  await expect(strip.locator('.oac-grid__layout')).toBeVisible();
  expect((await strip.boundingBox())!.height).toBeCloseTo(height, 0);
  expect(await page.locator('.oac-grid__cells').boundingBox()).toEqual(before);
  await strip.locator('.oac-grid__layout').click();
  await expect(page.locator('.oac-grid__picker')).toBeVisible();
  expect(parts).toEqual(['grid-bar', 'grid-menus']);
  expect(errors).toEqual([]);
});

test('a part the user moved on from while it loaded opens nothing, and leaves the focus where they put it', async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route(part('keymap-editor'), async (route) => { await held; await route.continue(); });
  const { errors } = await mountWidget(page);
  // Asked for, then Escape: what a bundled panel would have been closed by.
  await page.keyboard.press('Shift+Slash');
  await page.keyboard.press('Escape');
  // Asked for again, then the user turns to the symbol field and types.
  await page.keyboard.press('Shift+Slash');
  const field = page.locator('.oac-topbar .oac-sym__input');
  await field.click();
  await page.keyboard.type('RE');
  release();
  await page.waitForTimeout(400);
  await expect(page.locator(DIALOG)).toHaveCount(0);
  expect(await field.evaluate((node) => node === document.activeElement)).toBe(true);
  // Arrived now, so the next ? opens it at once.
  await page.keyboard.press('Escape');
  await field.evaluate((node: HTMLElement) => node.blur());
  const box = await page.locator('.oac-widget .oac-chart').boundingBox();
  await page.mouse.move(box!.x + box!.width / 2, box!.y + box!.height / 2);
  await page.keyboard.press('Shift+Slash');
  await expect(page.locator(DIALOG)).toBeVisible();
  expect(errors).toEqual([]);
});

test('the grid opens the menu pressed last while its menus load', async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route(part('grid-menus'), async (route) => { await held; await route.continue(); });
  const { errors } = await mount(page, '/tests/e2e/widget-grid-fixture.html?toolbar=1&preset=2x2');
  const strip = page.locator('.oac-grid__bar');
  await expect(strip.locator('.oac-grid__layout')).toBeVisible();
  await strip.locator('.oac-grid__layout').click();
  await strip.locator('.oac-grid__link').click();
  release();
  await expect(page.locator('.oac-grid__menu')).toBeVisible();
  await expect(page.locator('.oac-grid__picker')).toHaveCount(0);
  expect(errors).toEqual([]);
});
