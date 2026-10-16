import { test, expect, type Page } from '@playwright/test';

for (const dpr of [1, 1.25, 2]) {
  test(`compact TPO paints opaque physical pixels at DPR ${dpr}`, async ({ browser }) => {
    const context = await browser.newContext({ deviceScaleFactor: dpr });
    const page = await context.newPage();
    await page.goto('/examples/market-profile/index.html');
    await page.waitForFunction(() => typeof (window as any).__mp === 'function');
    const report = await page.evaluate(async () => {
      const moduleUrl = '/dist/openalgo-charts.profile.mjs';
      const { MarketProfile, computeMarketProfile } = await import(moduleUrl);
      const t0 = Date.UTC(2026, 7, 28, 3, 45) / 1000;
      const result = computeMarketProfile([
        { time: t0, open: 100, high: 110, low: 100, close: 110, volume: 15000 },
        { time: t0 + 1800, open: 105, high: 108, low: 105, close: 108, volume: 20000 },
      ], { tickSize: 1, rowTicks: 1, session: 'day' });
      const original = JSON.stringify(result);
      const canvas = document.createElement('canvas');
      const dpr = devicePixelRatio;
      canvas.width = Math.round(320 * dpr);
      canvas.height = Math.round(160 * dpr);
      const ctx = canvas.getContext('2d')!;
      const mp = new MarketProfile(result, {
        blockDisplay: 'compact', opacity: 1, profileSpacing: 0,
        showPoc: false, showValueArea: false, fillValueArea: false,
        showInitialBalance: false, showSinglePrints: false, showTails: false,
        showSessionLabel: false,
      });
      mp.draw(ctx, {
        dpr, plotWidth: 320, plotHeight: 80,
        priceScale: { priceToY: (p: number) => 40.3 + (110 - p) * 5 },
        timeScale: { indexToX: (i: number) => 20 + i * 200 },
        dataLayer: { timeToIndex: (t: number) => t === t0 ? 0 : 1 },
      });
      const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
      let ink = 0, partial = 0, outsidePlot = 0;
      for (let i = 3; i < data.length; i += 4) {
        if (data[i]) ink++;
        if (data[i] > 0 && data[i] < 255) partial++;
        if (data[i] && Math.floor((i / 4) / canvas.width) >= 80 * dpr) outsidePlot++;
      }
      return { ink, partial, outsidePlot, unchanged: JSON.stringify(result) === original };
    });
    expect(report.ink).toBeGreaterThan(100);
    expect(report.partial, 'glyph edges must not be blurred by fractional pixels').toBe(0);
    expect(report.outsidePlot, 'compact text must not spill over the axes').toBe(0);
    expect(report.unchanged).toBe(true);
    await context.close();
  });
}

test('demo compares modes and compression without changing profile analytics', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/examples/market-profile/index.html');
  await page.waitForFunction(() => typeof (window as any).__profileResult === 'function');
  await expect(page.locator('#block')).toHaveValue('compact');
  const before = await page.evaluate(() => JSON.stringify((window as any).__profileResult()));
  await page.getByRole('button', { name: 'Compressed (5 px)', exact: true }).click();
  await expect(page.locator('#densitylabel')).toContainText('5.00 CSS px');
  await page.locator('#block').selectOption('auto');
  await page.locator('#block').selectOption('compact');
  await page.getByRole('button', { name: 'Comfortable (12 px)', exact: true }).click();
  const after = await page.evaluate(() => JSON.stringify((window as any).__profileResult()));
  expect(after).toBe(before);
  await page.getByRole('button', { name: 'Compressed (5 px)', exact: true }).click();
  const svg = await page.evaluate(() => (window as any).__chart().exportSVG());
  expect(svg).toContain('<svg');
  expect(svg).toContain('<rect');
  expect(errors).toEqual([]);
  await page.screenshot({ path: 'artifacts/compact-tpo-demo.png' });
});

async function rightClickDay(page: Page, index: number) {
  // Model changes schedule a paint; wait for the new hit-test geometry.
  await page.waitForFunction((index) => {
    const chart = (window as any).__chart();
    const session = (window as any).__profileResult().sessions[index];
    return (window as any).__mp().hoverAt(chart.timeScale.indexToX(index * 75) + 14,
      chart.panes()[0].priceScale.priceToY(session.poc))?.sessionIndex === index;
  }, index);
  const point = await page.evaluate((index) => {
    const chart = (window as any).__chart();
    const session = (window as any).__profileResult().sessions[index];
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    return {
      x: rect.left + chart.timeScale.indexToX(index * 75) + 14,
      y: rect.top + chart.panes()[0].priceScale.priceToY(session.poc),
    };
  }, index);
  await page.mouse.click(point.x, point.y, { button: 'right' });
  await expect(page.getByRole('menu')).toBeVisible();
}

test('right-click splits and unsplits only the chosen day and preserves its choice', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/examples/market-profile/index.html');
  await page.waitForFunction(() => typeof (window as any).__profileResult === 'function');
  await page.getByRole('button', { name: 'Fit sessions', exact: true }).click();
  const before = await page.evaluate(() => JSON.stringify((window as any).__profileResult()));
  const states = () => page.evaluate(() => (window as any).__profileResult().sessions
    .map((_: unknown, index: number) => (window as any).__mp().isSessionSplit(index)));
  await rightClickDay(page, 2);
  await expect(page.locator('#profile-menu-title')).toHaveText('1 Sept 2026');
  await page.getByRole('menuitem', { name: 'Split this day', exact: true }).click();
  await expect(page.getByRole('menu')).toBeHidden();
  expect(await states()).toEqual([false, false, true, false, false, false]);
  expect(await page.locator('#split').evaluate((el: HTMLInputElement) => el.indeterminate)).toBe(true);
  expect(await page.evaluate(() => JSON.stringify((window as any).__profileResult()))).toBe(before);
  await page.locator('#color').selectOption('valueArea');
  await page.locator('#period').selectOption('15');
  expect(await states()).toEqual([false, false, true, false, false, false]);
  await rightClickDay(page, 2);
  await page.getByRole('menuitem', { name: 'Unsplit this day', exact: true }).click();
  expect(await states()).toEqual([false, false, false, false, false, false]);
  await page.locator('#split').check();
  await rightClickDay(page, 4);
  await page.getByRole('menuitem', { name: 'Unsplit this day', exact: true }).click();
  expect(await states()).toEqual([true, true, true, true, false, true]);
  await rightClickDay(page, 4);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('menu')).toBeHidden();
  expect(await states()).toEqual([true, true, true, true, false, true]);
  await rightClickDay(page, 3);
  await page.locator('.brand').click();
  await expect(page.getByRole('menu')).toBeHidden();
  // Mixed state first selects all; the next click packs every day again.
  await page.locator('#split').check();
  await page.locator('#split').uncheck();
  expect(await states()).toEqual([false, false, false, false, false, false]);
  expect(errors).toEqual([]);
});

test('theme switching preserves split choices, markers and analytics', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto('/examples/market-profile/index.html');
  await page.waitForFunction(() => typeof (window as any).__mp === 'function');
  const before = await page.evaluate(() => {
    (window as any).__mp().setSessionSplit(4, true);
    return JSON.stringify((window as any).__profileResult());
  });
  await expect(page.locator('#theme option')).toHaveText(['Dark', 'Blue', 'Graphite', 'Emerald', 'Ivory']);
  const backgrounds = {
    blue: 'rgb(0, 0, 38)', graphite: 'rgb(20, 22, 25)', emerald: 'rgb(7, 27, 23)',
    ivory: 'rgb(246, 244, 238)', dark: 'rgb(13, 14, 18)',
  };
  for (const [name, background] of Object.entries(backgrounds)) {
    await page.locator('#theme').selectOption(name);
    await expect(page.locator('#chart')).toHaveCSS('background-color', background);
    const display = await page.evaluate(() => {
      const mp = (window as any).__mp();
      return { split: mp.isSessionSplit(4), options: mp.options(), result: JSON.stringify((window as any).__profileResult()) };
    });
    expect(display.split).toBe(true);
    expect(display.result).toBe(before);
    expect(display.options.showSessionOpen).toBe(true);
    expect(display.options.showLastPrice).toBe(true);
    expect(display.options.showSinglePrints).toBe(false);
  }
  // Links open directly in each theme; unknown names safely use the default.
  for (const name of [...Object.keys(backgrounds), 'unknown']) {
    await page.goto(`/examples/market-profile/index.html?theme=${name}`);
    await expect(page.locator('#theme')).toHaveValue(name === 'unknown' ? 'dark' : name);
    await expect(page.locator('#chart')).toHaveCSS('background-color', backgrounds[name as keyof typeof backgrounds] ?? backgrounds.dark);
  }
  expect(errors).toEqual([]);
});
