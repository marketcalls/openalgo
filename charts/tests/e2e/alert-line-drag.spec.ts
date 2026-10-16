import { expect, test, type Page } from '@playwright/test';
import type { AlertController, AlertSource, Bar, Chart, IndicatorApi, SeriesApi } from '../../src/index';

declare global {
  interface Window {
    __alertDrag: {
      chart: Chart; series: SeriesApi; alerts: AlertController; bars: Bar[]; study: IndicatorApi;
      events: { type: string; id?: string; price?: number }[];
      pointerId: number;
      setupIndependentStudy(): void;
      startReplay(): void; stopReplay(): void;
    };
  }
}

const pageErrors = new WeakMap<Page, string[]>();
test.use({ viewport: { width: 1200, height: 900 } });
test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  pageErrors.set(page, errors);
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('/tests/e2e/alert-line-drag-fixture.html');
  await page.waitForFunction(() => !!window.__alertDrag);
  await paint(page);
});
test.afterEach(async ({ page }, info) => {
  const errors = pageErrors.get(page) ?? [];
  if (info.status !== info.expectedStatus || errors.length) await page.screenshot({ path: info.outputPath('failure.png') });
  expect(errors).toEqual([]);
});

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function point(page: Page, price: number, pane = 0): Promise<{ x: number; y: number; price: number }> {
  return page.evaluate(({ price, pane }) => {
    const { chart } = window.__alertDrag;
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    // Integer CSS coordinates give every engine the same physical pointer target.
    const y = Math.round(rect.top + chart.priceToCoordinate(price, pane)!);
    return { x: Math.round(rect.left + rect.width * 0.6), y, price: chart.coordinateToPrice(y - rect.top, pane)! };
  }, { price, pane });
}

async function source(page: Page, id: string): Promise<AlertSource> {
  return page.evaluate(id => window.__alertDrag.alerts.list().find(alert => alert.id === id)!.source, id);
}

async function updateCount(page: Page, id: string): Promise<number> {
  return page.evaluate(id => window.__alertDrag.events.filter(event => event.type === 'alert:updated' && event.id === id).length, id);
}

async function startDrag(page: Page, from: number, to: number, pane = 0): Promise<number> {
  const press = await point(page, from, pane);
  const target = await point(page, to, pane);
  await page.mouse.move(press.x, press.y);
  await page.mouse.down();
  await page.mouse.move(target.x, target.y, { steps: 8 });
  await paint(page);
  return target.price;
}

async function lineInk(page: Page, price: number, pane = 0): Promise<number> {
  return page.evaluate(({ price, pane }) => {
    const { chart } = window.__alertDrag;
    const canvas = chart.takeScreenshot();
    const width = document.getElementById('chart')!.getBoundingClientRect().width;
    const ratio = canvas.width / width;
    const y = chart.priceToCoordinate(price, pane)! * ratio;
    const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    let count = 0;
    for (let py = Math.floor(y - 3 * ratio); py <= y + 3 * ratio; py++) {
      for (let px = Math.floor(canvas.width * 0.55); px < canvas.width * 0.7; px++) {
        const offset = (py * canvas.width + px) * 4;
        if (pixels[offset] < 130 && pixels[offset + 1] > 90 && pixels[offset + 1] < 190 && pixels[offset + 2] > 220) count++;
      }
    }
    return count;
  }, { price, pane });
}

test('a real mouse drag previews the price line and commits once on release', async ({ page }, info) => {
  const before = await source(page, 'price');
  const stored = await page.evaluate(() => window.__alertDrag.chart.getState().alerts);
  const click = await point(page, 105);
  await page.mouse.click(click.x, click.y);
  expect(await source(page, 'price')).toEqual(before);
  expect(await updateCount(page, 'price')).toBe(0);
  expect(await lineInk(page, 105)).toBeGreaterThan(20);
  expect(await lineInk(page, 112)).toBe(0);
  const expected = await startDrag(page, 105, 112);
  expect(await lineInk(page, 112)).toBeGreaterThan(20);
  expect(await source(page, 'price')).toEqual(before);
  expect(await page.evaluate(() => window.__alertDrag.chart.getState().alerts)).toEqual(stored);
  expect(await updateCount(page, 'price')).toBe(0);
  await page.screenshot({ path: info.outputPath('price-preview.png') });
  await page.mouse.up();
  await expect.poll(() => source(page, 'price')).toMatchObject({ kind: 'price', price: expect.closeTo(expected, 6) });
  expect(await updateCount(page, 'price')).toBe(1);
  expect(await page.evaluate(() => window.__alertDrag.events.filter(event => event.type === 'alerts:changed' && event.id === 'price'))).toHaveLength(1);
  await paint(page);
  await page.screenshot({ path: info.outputPath('price-committed.png') });
});

test('range lines change the grabbed bound and clamp a crossing without swapping bounds', async ({ page }, info) => {
  const upper = await startDrag(page, 120, 127);
  await page.mouse.up();
  await expect.poll(() => source(page, 'range')).toMatchObject({ price: 90, upperPrice: expect.closeTo(upper, 6) });
  const lower = await startDrag(page, 90, 94);
  await page.mouse.up();
  await expect.poll(() => source(page, 'range')).toMatchObject({ price: expect.closeTo(lower, 6), upperPrice: expect.closeTo(upper, 6) });
  expect(await updateCount(page, 'range')).toBe(2);
  expect(await source(page, 'price')).toEqual({ kind: 'price', price: 105 });
  await page.screenshot({ path: info.outputPath('range-bounds.png') });
  await startDrag(page, 94, 132);
  await page.mouse.up();
  await expect.poll(() => source(page, 'range')).toMatchObject({ price: expect.closeTo(upper, 6), upperPrice: expect.closeTo(upper, 6) });
  expect(await updateCount(page, 'range')).toBe(3);
});

test('a study line uses its pane units while the pointer crosses into another pane', async ({ page }, info) => {
  const pane = await page.evaluate(() => window.__alertDrag.study.paneIndex);
  const target = await point(page, 70, pane);
  const press = await point(page, 30, pane);
  await page.mouse.move(press.x, press.y);
  await page.mouse.down();
  await page.mouse.move(target.x, target.y, { steps: 8 });
  await paint(page);
  expect(await lineInk(page, 70, pane)).toBeGreaterThan(20);
  await page.mouse.up();
  await expect.poll(() => source(page, 'study')).toMatchObject({ kind: 'indicator', value: expect.closeTo(target.price, 6) });
  expect(await source(page, 'price')).toEqual({ kind: 'price', price: 105 });
  expect(await updateCount(page, 'study')).toBe(1);
  await page.screenshot({ path: info.outputPath('study-units.png') });
  const acrossPane = await startDrag(page, 70, 110, pane);
  await page.mouse.up();
  await expect.poll(() => source(page, 'study')).toMatchObject({ value: expect.closeTo(acrossPane, 6) });
  expect(await updateCount(page, 'study')).toBe(2);
});

test('an independent study preserves candle autoscale from its first frame and drags in its own units', async ({ page }, info) => {
  await page.evaluate(() => window.__alertDrag.setupIndependentStudy());
  await paint(page);
  const first = await page.evaluate(() => {
    const { series, study, alerts } = window.__alertDrag;
    const scale = series.priceScale();
    const before = scale.priceRange();
    alerts.add({ id: 'independent', title: 'Independent threshold', source: {
      kind: 'indicator', instanceId: study.id, plotKey: 'value', value: 1000000,
    } });
    // The scheduled chart frame runs before this callback, without an intervening export.
    return new Promise<{ before: typeof before; after: typeof before; automatic: boolean; fixed: unknown }>(resolve => {
      requestAnimationFrame(() => resolve({ before, after: scale.priceRange(), automatic: scale.autoScale,
        fixed: scale.fixedRange }));
    });
  });
  expect(first.automatic).toBe(true);
  expect(first.fixed).toBeNull();
  expect(first.before.min).toBeGreaterThan(90);
  expect(first.before.max).toBeLessThan(110);
  expect(first.after).toEqual(first.before);
  await page.screenshot({ path: info.outputPath('independent-initial.png') });
  const geometry = await page.evaluate(() => {
    const { series, study } = window.__alertDrag;
    const scale = study.series('value')!.priceScale();
    scale.setOptions({ minMove: 10000 });
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    const from = Math.round(rect.top + scale.priceToY(1000000));
    const to = Math.round(rect.top + scale.priceToY(1200000));
    return { x: Math.round(rect.left + rect.width * 0.6), from, to, value: scale.snapToTick(scale.yToPrice(to - rect.top)),
      candleValue: series.priceScale().yToPrice(to - rect.top), independent: scale !== series.priceScale() };
  });
  expect(geometry.independent).toBe(true);
  expect(geometry.value).toBeGreaterThan(1100000);
  expect(geometry.candleValue).toBeLessThan(110);
  const ink = (value: number) => page.evaluate(value => {
    const { chart, study } = window.__alertDrag;
    const canvas = chart.takeScreenshot();
    const width = document.getElementById('chart')!.getBoundingClientRect().width;
    const ratio = canvas.width / width;
    const y = study.series('value')!.priceScale().priceToY(value) * ratio;
    const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    let plot = 0, axis = 0;
    for (let py = 0; py < canvas.height; py++) {
      for (let px = Math.floor(canvas.width * 0.55); px < canvas.width; px++) {
        const offset = (py * canvas.width + px) * 4;
        if (pixels[offset] >= 130 || pixels[offset + 1] <= 90 || pixels[offset + 1] >= 190 || pixels[offset + 2] <= 220) continue;
        if (px > (width - 72 + 2) * ratio) axis++;
        if (px < canvas.width * 0.7 && Math.abs(py - y) <= 3 * ratio) plot++;
      }
    }
    return { plot, axis };
  }, value);
  expect((await ink(1000000)).plot).toBeGreaterThan(20);
  expect(await ink(1200000)).toEqual({ plot: 0, axis: 0 });
  await page.mouse.move(geometry.x, geometry.from);
  await page.mouse.down();
  await page.mouse.move(geometry.x, geometry.to, { steps: 8 });
  await paint(page);
  expect(await source(page, 'independent')).toMatchObject({ value: 1000000 });
  expect(await updateCount(page, 'independent')).toBe(0);
  const preview = await ink(geometry.value);
  expect(preview.plot).toBeGreaterThan(20);
  expect(preview.axis).toBe(0);
  expect((await ink(1000000)).plot).toBe(0);
  expect(await page.evaluate(() => window.__alertDrag.series.priceScale().priceRange())).toEqual(first.before);
  await page.screenshot({ path: info.outputPath('independent-preview.png') });
  await page.mouse.up();
  await expect.poll(() => source(page, 'independent')).toMatchObject({ value: expect.closeTo(geometry.value, 6) });
  expect(await updateCount(page, 'independent')).toBe(1);
  await paint(page);
  expect(await page.evaluate(() => window.__alertDrag.series.priceScale().priceRange())).toEqual(first.before);
  const committed = await ink(geometry.value);
  expect(committed.plot).toBeGreaterThan(20);
  expect(committed.axis).toBe(0);
  await page.screenshot({ path: info.outputPath('independent-committed.png') });
});

for (const cancellation of ['pointercancel', 'Escape'] as const) {
  test(`${cancellation} restores the original visual and leaves storage untouched`, async ({ page }) => {
    const stored = await page.evaluate(() => window.__alertDrag.chart.getState().alerts);
    await startDrag(page, 105, 112);
    expect(await lineInk(page, 112)).toBeGreaterThan(20);
    if (cancellation === 'Escape') await page.keyboard.press('Escape');
    else {
      const pointerId = await page.evaluate(() => window.__alertDrag.pointerId);
      await page.locator('#chart').dispatchEvent('pointercancel', { pointerId, pointerType: 'mouse', button: 0, buttons: 0 });
    }
    await page.mouse.up();
    await paint(page);
    expect(await source(page, 'price')).toEqual({ kind: 'price', price: 105 });
    expect(await page.evaluate(() => window.__alertDrag.chart.getState().alerts)).toEqual(stored);
    expect(await updateCount(page, 'price')).toBe(0);
    expect(await lineInk(page, 105)).toBeGreaterThan(20);
    expect(await lineInk(page, 112)).toBe(0);
  });
}

for (const guard of ['pause', 'replay'] as const) {
  test(`${guard} prevents edits before and during a drag and releasing it restores dragging`, async ({ page }) => {
    const setGuard = (on: boolean) => page.evaluate(({ guard, on }) => {
      const api = window.__alertDrag;
      if (guard === 'pause') api.alerts.setPaused(on);
      else if (on) api.startReplay();
      else api.stopReplay();
    }, { guard, on });
    await setGuard(true);
    await startDrag(page, 105, 112);
    await page.mouse.up();
    expect(await source(page, 'price')).toEqual({ kind: 'price', price: 105 });
    expect(await updateCount(page, 'price')).toBe(0);
    await setGuard(false);
    await startDrag(page, 105, 112);
    expect(await lineInk(page, 112)).toBeGreaterThan(20);
    await setGuard(true);
    await page.mouse.up();
    expect(await source(page, 'price')).toEqual({ kind: 'price', price: 105 });
    expect(await updateCount(page, 'price')).toBe(0);
    await setGuard(false);
    const expected = await startDrag(page, 105, 112);
    await page.mouse.up();
    await expect.poll(() => source(page, 'price')).toMatchObject({ price: expect.closeTo(expected, 6) });
    expect(await updateCount(page, 'price')).toBe(1);
  });
}

test('a left price axis preserves the rendered line drag geometry', async ({ page }, info) => {
  expect(await page.evaluate(() => window.__alertDrag.chart.movePriceAxis(0, 'right', 'left'))).toBe(true);
  await paint(page);
  const expected = await startDrag(page, 105, 112);
  expect(await lineInk(page, 112)).toBeGreaterThan(20);
  await page.mouse.up();
  await expect.poll(() => source(page, 'price')).toMatchObject({ price: expect.closeTo(expected, 6) });
  expect(await updateCount(page, 'price')).toBe(1);
  await page.screenshot({ path: info.outputPath('left-axis-drag.png') });
});

for (const axis of ['right', 'left'] as const) {
  test(`dragging on the ${axis} price axis previews and stores a whole tick`, async ({ page }, info) => {
    await page.evaluate(axis => {
      const { chart, series } = window.__alertDrag;
      if (axis === 'left') chart.movePriceAxis(0, 'right', 'left');
      chart.panes()[0].priceScale.setOptions({ minMove: 0.01 });
      series.priceScale().setOptions({ minMove: 5 });
      chart.exportSVG();
    }, axis);
    await paint(page);
    await startDrag(page, 105, 112);
    expect(await source(page, 'price')).toMatchObject({ price: 105 });
    expect(await lineInk(page, 110)).toBeGreaterThan(20);
    expect(await lineInk(page, 112)).toBe(0);
    await page.screenshot({ path: info.outputPath(`${axis}-tick-preview.png`) });
    await page.mouse.up();
    await expect.poll(() => source(page, 'price')).toMatchObject({ price: 110 });
    expect(await updateCount(page, 'price')).toBe(1);
  });
}

test.describe('touch alert lines', () => {
  test.use({ hasTouch: true });
  test('touch drag commits the selected threshold on a narrow chart', async ({ page, browserName }, info) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await paint(page);
    const from = await point(page, 105);
    const to = await point(page, 112);
    const positions = [{ x: from.x, y: from.y }, { x: from.x, y: (from.y + to.y) / 2 }, { x: to.x, y: to.y }];
    if (browserName === 'chromium') {
      const touch = await page.context().newCDPSession(page);
      for (let index = 0; index < positions.length; index++) {
        await touch.send('Input.dispatchTouchEvent', {
          type: index === 0 ? 'touchStart' : 'touchMove', touchPoints: [{ ...positions[index], id: 31 }],
        });
      }
      await touch.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
      await touch.detach();
    } else {
      // Playwright exposes native touch drags through Chromium only.
      info.annotations.push({ type: 'coverage', description: 'Synthetic DOM touch pointers exercise this engine drag path.' });
      await page.evaluate(positions => {
        const target = document.elementFromPoint(positions[0].x, positions[0].y)!;
        positions.forEach((position, index) => target.dispatchEvent(new PointerEvent(index === 0 ? 'pointerdown' : 'pointermove', {
          bubbles: true, pointerId: 31, pointerType: 'touch', isPrimary: true, button: 0, buttons: 1,
          clientX: position.x, clientY: position.y,
        })));
        const last = positions[positions.length - 1];
        target.dispatchEvent(new PointerEvent('pointerup', {
          bubbles: true, pointerId: 31, pointerType: 'touch', isPrimary: true, button: 0, buttons: 0,
          clientX: last.x, clientY: last.y,
        }));
      }, positions);
    }
    await expect.poll(() => source(page, 'price')).toMatchObject({ price: expect.closeTo(to.price, 6) });
    expect(await updateCount(page, 'price')).toBe(1);
    await paint(page);
    await page.screenshot({ path: info.outputPath('touch-alert-drag.png') });
  });
});
