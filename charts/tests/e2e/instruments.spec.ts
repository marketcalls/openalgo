import { test, expect } from '@playwright/test';

test('instrument example applies broker and crypto metadata to real rendered charts', async ({ page }, info) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/examples/instruments.html');
  await expect(page.locator('#instrument-summary')).toContainText('NSE:CASH');
  await expect(page.locator('#session-status')).toContainText('04:30:00');
  expect(await page.evaluate(() => (window as any).__instrumentExample.chart.primaryBars()[0].time)).toBe(Date.parse('2026-01-27T04:30:00Z') / 1000);
  await page.locator('#profile').selectOption('futures');
  await expect(page.locator('#instrument-summary')).toContainText('quantity step 75');
  await expect(page.locator('#oi-status')).toContainText('Supported');
  await page.locator('#quantity').fill('100');
  await expect(page.locator('#quantity-status')).toContainText('not a multiple');
  await page.locator('#quantity').fill('150');
  await expect(page.locator('#quantity-status')).toContainText('Valid');
  await page.screenshot({ path: info.outputPath('instrument-futures.png') });
  await page.locator('#profile').selectOption('crypto');
  await expect(page.locator('#instrument-summary')).toContainText('UTC');
  await page.locator('#quantity').fill('0.003');
  await expect(page.locator('#quantity-status')).toContainText('Valid');
  const actual = await page.evaluate(() => {
    const { chart } = (window as any).__instrumentExample;
    return { format: chart.primarySeries().priceScale().format(0.12345678), bars: chart.primaryBars().length,
      oi: chart.hasOpenInterest, timezone: chart.timezone() };
  });
  expect(actual).toMatchObject({ format: '0.12345678', oi: true, timezone: 'UTC' });
  expect(actual.bars).toBeGreaterThan(30);
  await page.setViewportSize({ width: 390, height: 740 });
  await expect.poll(() => page.evaluate(() => {
    const container = document.querySelector<HTMLElement>('#chart');
    const canvas = document.querySelector<HTMLCanvasElement>('#chart canvas');
    const context = canvas?.getContext('2d');
    if (!container || !canvas || !context || !canvas.width || !canvas.height) return 0;
    // The old wide bitmap can remain painted until the resize observer runs.
    // Require the resized pane surfaces before accepting their pixel content.
    const width = container.getBoundingClientRect().width;
    if (Array.from(container.querySelectorAll('canvas')).some(surface => {
      const rect = surface.getBoundingClientRect();
      return Math.abs(rect.width - width) > 0.5
        || surface.width !== Math.round(width * devicePixelRatio)
        || surface.height !== Math.round(rect.height * devicePixelRatio);
    })) return 0;
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let painted = 0;
    for (let offset = 0; offset < pixels.length; offset += 4) {
      const r = pixels[offset], g = pixels[offset + 1], b = pixels[offset + 2];
      if ((g > 90 && r < 100 && b > r * 1.2) || (r > 150 && g < 150 && b < 150)) painted++;
    }
    return painted;
  })).toBeGreaterThan(100);
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  // A WebKit full-page capture taken during resize omitted the chart surface.
  // Record both the settled viewport and the chart scrolled fully into view.
  await page.screenshot({ path: info.outputPath('instrument-crypto-narrow.png') });
  await page.locator('#chart').screenshot({ path: info.outputPath('instrument-crypto-chart.png') });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  expect(errors).toEqual([]);
});

test('instrument example displays closures and rejects unsupported intervals without replacing the source', async ({ page }) => {
  await page.goto('/examples/instruments.html');
  await expect(page.locator('#instrument-summary')).toContainText('NSE:CASH');
  const state = await page.evaluate(() => {
    const example = (window as any).__instrumentExample;
    const before = example.chart.primaryBars(); example.setInterval('5m');
    return { before, after: example.chart.primaryBars(), interval: example.chart.getDataContext().interval };
  });
  expect(state.after).toEqual(state.before); expect(state.interval).toBe('1m');
  await expect(page.locator('#error')).toContainText('unsupported interval');
  await page.locator('#observation').fill('2026-01-26T05:00:00Z');
  await page.getByRole('button', { name: 'Apply time' }).click();
  await expect(page.locator('#session-status')).toContainText('Closed');
  expect(await page.evaluate(() => (window as any).__instrumentExample.chart.primaryBars().length)).toBe(0);
  await page.locator('#profile').selectOption('crypto');
  await expect(page.locator('#session-status')).toContainText('00:00:00');
  expect(await page.evaluate(() => (window as any).__instrumentExample.chart.primaryBars().length)).toBeGreaterThan(0);
});
