import { expect, test, type Page } from '@playwright/test';
import type { Widget } from '../../src/widget/widget';
import type { Bar } from '../../src/model/bar';

declare global {
  interface Window { __ui253: { widget: Widget; bars: Bar[]; first: string; second: string; rsi: string; drawings: string[] } }
}

async function mount(page: Page, width = 1440) {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 850 });
  await page.goto('/tests/e2e/widget-ui-253-fixture.html');
  await page.waitForFunction(() => !!window.__ui253 && window.__ui253.widget.chart.timeScale.width > 0);
  return errors;
}

async function chartInk(page: Page): Promise<number> {
  return page.locator('.oac-chart canvas').first().evaluate(element => {
    const canvas = element as HTMLCanvasElement;
    const values = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    for (let i = 0; i < values.length; i += 4) {
      if (Math.max(values[i], values[i + 1], values[i + 2]) - Math.min(values[i], values[i + 1], values[i + 2]) > 45) count++;
    }
    return count;
  });
}

test('changing chart type keeps the primary series, manual scale and marker drawing', async ({ page }, info) => {
  const errors = await mount(page);
  const result = await page.evaluate(() => {
    const { widget, bars } = window.__ui253;
    const source = widget.series;
    const markers = source.createMarkers();
    markers.setMarkers([{ time: bars[150].time, position: 'aboveBar', shape: 'circle', size: 'big', color: '#ffaa00', text: 'Retained' }]);
    source.applyOptions({ color: '#cc22cc', lineWidth: 4 });
    widget.chart.movePriceAxis(0, 'right', 'left');
    const scale = source.priceScale();
    const range = { min: Math.min(...bars.map(bar => bar.low)) - 10, max: Math.max(...bars.map(bar => bar.high)) + 10 };
    scale.setAutoScale(false);
    scale.setPriceRange(range);
    widget.setChartType('line');
    return {
      retained: widget.series === source && widget.series.priceScale() === scale,
      manual: !scale.autoScale,
      range: scale.priceRange(), expectedRange: range,
      style: widget.chart.primarySeriesInfo()?.style,
      saved: widget.getState().chart.series?.[0],
    };
  });
  expect(result.retained).toBe(true);
  expect(result.manual).toBe(true);
  expect(result.range).toEqual(result.expectedRange);
  expect(result.style).toMatchObject({ color: '#cc22cc', lineWidth: 4 });
  expect(result.saved).toMatchObject({ type: 'line', priceScaleId: 'left' });
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
  await page.screenshot({ path: info.outputPath('retained-type-state.png') });
  const ink = await page.locator('.oac-chart canvas').evaluateAll(elements => {
    let orange = 0, purple = 0;
    for (const element of elements) {
      const canvas = element as HTMLCanvasElement;
      const context = canvas.getContext('2d');
      if (!context) continue;
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === 255 && pixels[i + 1] === 170 && pixels[i + 2] === 0) orange++;
        if (pixels[i] === 204 && pixels[i + 1] === 34 && pixels[i + 2] === 204) purple++;
      }
    }
    return { orange, purple };
  });
  expect(ink.orange).toBeGreaterThan(20);
  expect(ink.purple).toBeGreaterThan(300);
  await page.evaluate(() => {
    const { widget } = window.__ui253;
    widget.chart.setSeriesType(widget.series, 'area');
  });
  await expect(page.locator('.oac-topbar__type')).toContainText('Area');
  expect(await page.evaluate(() => window.__ui253.widget.getState().chartType)).toBe('area');
  await page.evaluate(() => window.__ui253.widget.setChartType('candlestick'));
  await expect(page.locator('.oac-topbar__type')).toContainText('Candles');
  await expect.poll(() => chartInk(page)).toBeGreaterThan(500);
  expect(await page.evaluate(() => window.__ui253.widget.chart.priceAxisState(0, 'left')?.autoFit)).toBe(false);
  expect(errors).toEqual([]);
});

test('data dock follows candles, resizes the chart, and restores saved panel state', async ({ page }, info) => {
  const errors = await mount(page);
  const before = await page.locator('.oac-chart').boundingBox();
  await page.locator('.oac-topbar').getByRole('button', { name: 'Data', exact: true }).click();
  const dock = page.locator('.oac-panel-dock');
  await expect(dock).toBeVisible();
  await expect(dock).toContainText('NSE:NOVA');
  await expect.poll(async () => (await page.locator('.oac-chart').boundingBox())!.width).toBeLessThan(before!.width - 200);
  const point = await page.evaluate(() => {
    const { widget, bars } = window.__ui253;
    const rect = widget.root.querySelector('.oac-chart')!.getBoundingClientRect();
    const bar = bars[150];
    return { x: rect.left + widget.chart.timeToCoordinate(bar.time)!, y: rect.top + widget.chart.priceToCoordinate(bar.close)!, close: bar.close.toFixed(widget.series.priceScale().precision()) };
  });
  await page.mouse.move(point.x, point.y);
  await expect(dock.locator('[data-key="close"]')).toContainText(point.close);
  await expect(dock.locator('[data-key="oi"]')).toContainText('Unavailable');
  const grip = dock.getByRole('separator');
  await grip.focus(); await grip.press('ArrowLeft');
  expect(await page.evaluate(() => window.__ui253.widget.getState().panels?.width)).toBe(310);
  await expect.poll(() => chartInk(page)).toBeGreaterThan(500);
  await page.screenshot({ path: info.outputPath('data-dock-dark.png') });
  await page.evaluate(() => window.__ui253.widget.setTheme('light'));
  await expect.poll(() => chartInk(page)).toBeGreaterThan(500);
  await page.screenshot({ path: info.outputPath('data-dock-light.png') });
  await dock.getByRole('button', { name: 'Close', exact: true }).click();
  await expect(dock).toBeHidden();
  expect(errors).toEqual([]);
});

test('mobile information sheet returns to a correctly placed desktop dock', async ({ page }) => {
  const errors = await mount(page, 390);
  await page.evaluate(() => window.__ui253.widget.openDataWindow());
  await expect(page.locator('.oac-panel-dock')).toHaveAttribute('data-sheet', 'true');
  await page.setViewportSize({ width: 1440, height: 850 });
  await expect(page.locator('.oac-panel-dock')).toHaveAttribute('data-sheet', 'false');
  await expect.poll(async () => {
    const dock = (await page.locator('.oac-panel-dock').boundingBox())!;
    return Math.abs(dock.x + dock.width - 1440);
  }).toBeLessThanOrEqual(1);
  await expect.poll(() => chartInk(page)).toBeGreaterThan(500);
  await page.locator('.oac-chart').click({ position: { x: 180, y: 140 } });
  await page.setViewportSize({ width: 390, height: 850 });
  await expect(page.locator('.oac-panel-dock')).toHaveAttribute('data-sheet', 'true');
  await expect.poll(() => page.locator('.oac-panel-dock').evaluate(node => node.contains(document.activeElement))).toBe(true);
  expect(errors).toEqual([]);
});

test('symbol categories and contract selection preserve exchange, direct typing respects editors', async ({ page }) => {
  const errors = await mount(page);
  const input = page.locator('.oac-topbar input').first();
  await input.fill('NOVA');
  const picker = page.locator('.oac-symbol-picker');
  await expect(picker.getByRole('button', { name: 'Futures', exact: true })).toBeVisible();
  await picker.getByRole('button', { name: 'Futures', exact: true }).click();
  await picker.getByRole('option').click();
  await picker.getByRole('option').filter({ hasText: 'NOVA26OCT' }).click();
  expect(await page.evaluate(() => window.__ui253.widget.context.symbol())).toEqual({ symbol: 'NOVA26OCT', exchange: 'NFO' });
  await page.locator('.oac-chart').click({ position: { x: 200, y: 180 } });
  await page.keyboard.press('1');
  const quick = page.getByRole('dialog', { name: 'Enter interval', exact: true });
  await expect(quick).toBeVisible();
  await quick.getByRole('textbox').fill('15'); await quick.getByRole('textbox').press('Enter');
  expect(await page.evaluate(() => window.__ui253.widget.interval())).toBe('15m');
  await page.getByLabel('Outside editor').fill('123');
  await expect(page.locator('.oac-quick-entry')).toHaveCount(0);
  expect(errors).toEqual([]);
});

test('running indicator controls remove just one duplicate instance', async ({ page }) => {
  const errors = await mount(page);
  await page.locator('.oac-topbar').getByRole('button', { name: 'Indicators', exact: true }).click();
  const rows = page.locator('.oac-pick__running-row');
  await expect(rows).toHaveCount(3);
  await rows.first().getByRole('button', { name: /^Remove / }).click();
  await expect(rows).toHaveCount(2);
  const result = await page.evaluate(() => ({ ids: window.__ui253.widget.chart.indicators().map(i => i.id), first: window.__ui253.first, second: window.__ui253.second }));
  expect(result.ids).not.toContain(result.first); expect(result.ids).toContain(result.second);
  expect(errors).toEqual([]);
});

test('mobile data sheet fits the host and Escape returns focus', async ({ page }, info) => {
  const errors = await mount(page, 390);
  await page.evaluate(() => window.__ui253.widget.openDataWindow());
  const dock = page.locator('.oac-panel-dock');
  await expect(dock).toHaveAttribute('data-sheet', 'true');
  const rect = (await dock.boundingBox())!;
  expect(rect.x).toBeGreaterThanOrEqual(0); expect(rect.x + rect.width).toBeLessThanOrEqual(391);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(390);
  await page.screenshot({ path: info.outputPath('data-sheet-mobile.png') });
  await page.keyboard.press('Escape'); await expect(dock).toBeHidden();
  expect(errors).toEqual([]);
});

test('object groups and study movement keep the same live instances', async ({ page }, info) => {
  const errors = await mount(page);
  await page.locator('.oac-topbar').getByRole('button', { name: 'Objects', exact: true }).click();
  const dock = page.locator('.oac-panel-dock');
  const drawings = dock.locator('[data-object-id^="drawing:"]');
  await drawings.nth(0).locator('[data-action="add-selection"]').click();
  await drawings.nth(1).locator('[data-action="add-selection"]').click();
  await dock.getByLabel('Group name').fill('Session levels');
  await dock.getByRole('button', { name: 'Group selected', exact: true }).click();
  await expect(dock.locator('[data-object-id^="group:"]')).toContainText('Session levels');
  const id = await page.evaluate(() => window.__ui253.rsi);
  const study = dock.locator(`[data-object-id="indicator:${id}"]`);
  await study.locator('select').selectOption('0');
  expect(await page.evaluate(() => window.__ui253.widget.chart.indicators().find(i => i.id === window.__ui253.rsi)?.paneIndex)).toBe(0);
  expect(await page.evaluate(() => window.__ui253.widget.draw.toJSON().groups?.[0].members.length)).toBe(2);
  await page.screenshot({ path: info.outputPath('objects-grouped.png') });
  expect(errors).toEqual([]);
});

test('colour palette escapes settings scroll and Escape closes only the palette', async ({ page }, info) => {
  const errors = await mount(page);
  await page.evaluate(() => window.__ui253.widget.openSettings());
  const dialog = page.locator('.oac-settings');
  const swatch = dialog.locator('.oac-color__trigger').last();
  await swatch.click();
  const palette = page.locator('.oac-color__popover:visible');
  await expect(palette).toBeVisible();
  expect(await palette.evaluate(node => node.closest('.oac-settings__pane') === null)).toBe(true);
  const rect = (await palette.boundingBox())!;
  expect(rect.y).toBeGreaterThanOrEqual(0); expect(rect.y + rect.height).toBeLessThanOrEqual(701);
  await page.screenshot({ path: info.outputPath('colour-palette.png') });
  await page.keyboard.press('Escape');
  await expect(palette).toHaveCount(0); await expect(dialog).toBeVisible(); await expect(swatch).toBeFocused();
  await swatch.click();
  await page.evaluate(() => window.__ui253.widget.destroy());
  await expect(page.locator('.oac-color__popover:visible')).toHaveCount(0);
  expect(errors).toEqual([]);
});
