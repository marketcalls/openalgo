import { expect, test, type Page, type TestInfo } from '@playwright/test';
import type { Chart } from '../../src/index';

type DemoWindow = Window & { __oac: { app: { chart: Chart; loading: boolean } } };

const SAMPLE_ID = 'routed-signal-sample';
// Wide swings, so the momentum histogram crosses zero several times and the
// sample has Buy and Sell plates to route.
const BARS = Array.from({ length: 80 }, (_, index) => {
  const close = 100 + 20 * Math.sin(index / 4);
  return { time: 1_789_776_000 + index * 86400, open: close - 1, high: close + 3, low: close - 3, close, volume: 2000 };
});
const TOP = Math.max(...BARS.slice(BARS.length - 31).map(bar => bar.high));

test.use({ viewport: { width: 1440, height: 1000 } });
test.beforeEach(async ({ page, request }) => {
  const up = await request.get('/api/history?symbol=AAPL&interval=1d&period=1mo').then(response => response.ok(), () => false);
  test.skip(!up, 'the yfinance fixture server is not available');
  await page.route('**/api/history?**', route => route.fulfill({ json: BARS }));
  await page.goto('/examples/yfinance/index.html?test=1');
  await page.waitForFunction(() => Boolean((window as unknown as DemoWindow).__oac?.app.chart)
    && !(window as unknown as DemoWindow).__oac.app.loading);
  await expect(page.locator(`#indpick option[value="${SAMPLE_ID}"]`)).toHaveCount(1);
});

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function shot(page: Page, info: TestInfo, name: string): Promise<void> {
  const path = info.outputPath(`${name}.png`);
  await page.screenshot({ path });
  await info.attach(name, { path, contentType: 'image/png' });
}

test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) await shot(page, info, 'failure');
});

/**
 * What each pane holds of the sample: its Buy and Sell plates where they were
 * last drawn, where the range box was drawn, whether the Now label is there,
 * and how many pixels carry the box's exact label colour.
 */
async function routed(page: Page) {
  return page.evaluate(() => {
    const { chart } = (window as unknown as DemoWindow).__oac.app;
    type Layer = { _lastPositions?: { id: string; y: number }[]; _items?: { id?: string; text?: string }[]; _hits?: { id: string; y: number }[] };
    return chart.panes().map(pane => {
      const layers = pane.primitives() as unknown as Layer[];
      let ink = 0;
      for (const canvas of pane.element.querySelectorAll('canvas')) {
        const ctx = canvas.getContext('2d');
        if (!ctx || canvas.width === 0 || canvas.height === 0) continue;
        const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
        for (let i = 0; i < pixels.length; i += 4) {
          if (pixels[i + 3] === 255 && pixels[i] === 79 && pixels[i + 1] === 140 && pixels[i + 2] === 255) ink++;
        }
      }
      return {
        plates: layers.flatMap(layer => layer._lastPositions ?? []).filter(mark => mark.id.startsWith('signal:')).length,
        rangeTop: layers.flatMap(layer => layer._hits ?? []).find(hit => hit.id === 'routed-range')?.y ?? null,
        now: layers.some(layer => layer._items?.some(item => item.text === 'Now') === true),
        ink,
      };
    });
  });
}

test('the routed signal sample draws on the candles and follows them to the other axis', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const before = await routed(page);
  await page.locator('#chart').focus();
  await page.getByRole('button', { name: /^Add an indicator, / }).click();
  await expect(page.locator('.oac-pick')).toHaveCount(1);
  await page.locator(`.oac-pick__row[data-id="${SAMPLE_ID}"]`).click();
  await paint(page);
  const study = await page.evaluate(id => {
    const { chart } = (window as unknown as DemoWindow).__oac.app;
    const found = chart.indicators().filter(item => item.indicatorId === id);
    return { id: found[found.length - 1].id, pane: found[found.length - 1].paneIndex };
  }, SAMPLE_ID);
  expect(study.pane).toBeGreaterThan(0);
  const first = await routed(page);
  await shot(page, info, 'routed-on-candles');
  // Plates and the box on the candles; the Now label with the histogram.
  expect(first[0].plates).toBeGreaterThan(1);
  expect(first[study.pane].plates).toBe(0);
  expect(first[study.pane].now).toBe(true);
  expect(first[0].ink - before[0].ink).toBeGreaterThan(50);
  // The box top is the highest high of the last 31 bars, measured where the candles are.
  const top = () => page.evaluate(price => (window as unknown as DemoWindow).__oac.app.chart.panes()[0].readoutScale().priceToY(price), TOP);
  expect(first[0].rangeTop).not.toBeNull();
  expect(Math.abs(first[0].rangeTop! - await top())).toBeLessThan(2);

  // Moving the candles' axis to the left is allowed, and the box goes with them.
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart.movePriceAxis(0, 'right', 'left'))).toBe(true);
  await paint(page);
  const moved = await routed(page);
  await shot(page, info, 'routed-axis-left');
  expect(moved[0].plates).toBeGreaterThan(1);
  expect(Math.abs(moved[0].rangeTop! - await top())).toBeLessThan(2);
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart.movePriceAxis(0, 'left', 'right'))).toBe(true);

  // Signals on price off sends the plates to the histogram pane; the box stays.
  await page.evaluate(id => {
    (window as unknown as DemoWindow).__oac.app.chart.indicators().find(item => item.id === id)!.setSettings({ onPrice: false });
  }, study.id);
  await paint(page);
  const local = await routed(page);
  expect(local[0].plates).toBe(0);
  expect(local[study.pane].plates).toBeGreaterThan(1);
  expect(local[0].rangeTop).not.toBeNull();

  // Removing the study takes every routed layer with it.
  await page.evaluate(id => { (window as unknown as DemoWindow).__oac.app.chart.removeIndicator(id); }, study.id);
  await paint(page);
  const removed = await routed(page);
  expect(removed[0]).toMatchObject({ plates: 0, rangeTop: null, now: false });
  expect(removed[0].ink).toBeLessThanOrEqual(before[0].ink + 10);
  expect(errors).toEqual([]);
});


/** Momentum of the sample at its default length, the sign that picks each bar's shade. */
const MOMENTUM = BARS.map((bar, i) => (i < 10 ? null : bar.close - BARS[i - 10].close));
// Bars with a reading, before the range box starts, whose candles sit well away from the
// price read beside them, so no candle, plate or box is under the point read.
const SAMPLED = BARS.map((_, i) => i).filter(i => i >= 12 && i < 45 && Math.abs(BARS[i].close - 100) > 8 && MOMENTUM[i] !== 0);

/**
 * The colour at each sampled bar on one pane. On the price pane it is read at the bar's own
 * x, at a price far from that bar (below the candles when they are high, above them when
 * they are low), so the shading column of that bar is under the point and nothing else is.
 * In the study pane it is read a quarter of the way down, between two bars.
 */
async function sample(page: Page, paneIndex: number) {
  return page.evaluate(({ bars, sampled, paneIndex: index }) => {
    const { chart } = (window as unknown as DemoWindow).__oac.app;
    const pane = chart.panes()[index];
    const canvas = pane.element.querySelector('canvas')!;
    const rect = canvas.getBoundingClientRect();
    const host = document.getElementById('chart')!.getBoundingClientRect();
    const box = pane.element.getBoundingClientRect();
    const scale = canvas.width / rect.width;
    const ctx = canvas.getContext('2d')!;
    return sampled.map(i => {
      const x = host.left + chart.timeToCoordinate(bars[i].time) + (index === 0 ? 0 : chart.timeScale.barSpacing / 2);
      const y = box.top + (index === 0 ? pane.readoutScale().priceToY(bars[i].close > 100 ? 87 : 113.5) : box.height * 0.25);
      return [...ctx.getImageData(Math.floor((x - rect.left) * scale), Math.floor((y - rect.top) * scale), 1, 1).data.slice(0, 3)];
    });
  }, { bars: BARS, sampled: SAMPLED, paneIndex });
}

const same = (a: number[][], b: number[][]): number => a.filter((colour, k) => colour.join() === b[k].join()).length;

/** The study's settings and its legend summary, which names every select input's value. */
async function shading(page: Page, id: string): Promise<{ shade: unknown; summary: string | undefined }> {
  return page.evaluate(studyId => {
    const study = (window as unknown as DemoWindow).__oac.app.chart.indicators().find(item => item.id === studyId)!;
    return { shade: study.settings().shade, summary: (study.legend() as unknown as { _opts: { params?: string } })._opts.params };
  }, id);
}

/**
 * Pick a Momentum shading option the way a user does: hover the study's legend row, press
 * its gear, choose the option by its label in the host's settings dialog, and apply.
 */
async function chooseShading(page: Page, id: string, label: string, info?: TestInfo): Promise<void> {
  const gear = () => page.evaluate(studyId => {
    const { chart } = (window as unknown as DemoWindow).__oac.app;
    const study = chart.indicators().find(item => item.id === studyId)!;
    const buttons = (study.legend() as unknown as { _buttons: { id: string; x: number; y: number }[] })._buttons;
    const button = buttons.find(item => item.id.endsWith('::settings'));
    const pane = chart.panes()[study.paneIndex].element.getBoundingClientRect();
    return { row: { x: pane.left + 40, y: pane.top + 15 }, at: button ? { x: pane.left + button.x + 8, y: pane.top + button.y + 8 } : null };
  }, id);
  await page.mouse.move((await gear()).row.x, (await gear()).row.y);
  await paint(page);
  let at = (await gear()).at;
  expect(at).not.toBeNull();
  // The controls reveal on hover and can shift as they do; follow them until they hold still.
  for (let tries = 0; tries < 4; tries++) {
    await page.mouse.move(at!.x, at!.y);
    await paint(page);
    const next = (await gear()).at;
    expect(next).not.toBeNull();
    const settled = Math.abs(next!.x - at!.x) < 0.5 && Math.abs(next!.y - at!.y) < 0.5;
    at = next;
    if (settled) break;
  }
  await page.mouse.click(at!.x, at!.y);
  const dialog = page.locator('#setmodal');
  await expect(dialog).toBeVisible();
  await expect(page.locator('#set-title')).toHaveText('Routed signal sample settings');
  const field = dialog.locator('#set-body [data-key="shade"]');
  await expect(field.locator('option')).toHaveText(['On price', 'In study pane', 'Off']);
  await field.selectOption({ label });
  if (info) await shot(page, info, 'routed-shading-dialog');
  await dialog.locator('#set-ok').click();
  await expect(dialog).toBeHidden();
  await page.mouse.move(5, 5);
  await paint(page);
}

test('the routed signal sample shades the candles by momentum and its settings dialog moves it', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  expect(SAMPLED.length).toBeGreaterThan(8);
  await page.locator('#chart').focus();
  await page.getByRole('button', { name: /^Add an indicator, / }).click();
  await expect(page.locator('.oac-pick')).toHaveCount(1);
  await page.locator(`.oac-pick__row[data-id="${SAMPLE_ID}"]`).click();
  await page.locator('.oac-pick').getByRole('button', { name: 'Done', exact: true }).click();
  await expect(page.locator('.oac-pick')).toHaveCount(0);
  await paint(page);
  const study = await page.evaluate(id => {
    const { chart } = (window as unknown as DemoWindow).__oac.app;
    const found = chart.indicators().filter(item => item.indicatorId === id);
    return { id: found[found.length - 1].id, pane: found[found.length - 1].paneIndex };
  }, SAMPLE_ID);
  expect(study.pane).toBeGreaterThan(0);
  // A select input's value is part of the legend summary, the way every select is summarised.
  expect(await shading(page, study.id)).toEqual({ shade: 'price', summary: '10 price' });
  const shaded = await sample(page, 0);
  await shot(page, info, 'routed-shading-on-candles');
  // The same layout with the shading off is what the candles look like without it.
  await chooseShading(page, study.id, 'Off');
  expect(await shading(page, study.id)).toEqual({ shade: 'off', summary: '10 off' });
  const plain = await sample(page, 0);
  const studyPlain = await sample(page, study.pane);
  await shot(page, info, 'routed-shading-off');
  // On the candles, each sampled bar is tinted green where momentum is up and red where it is
  // down. A price line crossing a sampled point would leave that one unchanged, never wrong.
  const verdicts = SAMPLED.map((bar, k) => {
    const [r0, g0] = plain[k];
    const [r, g] = shaded[k];
    if (shaded[k].join() === plain[k].join()) return 'unchanged';
    return (g - g0 > r - r0) === MOMENTUM[bar]! > 0 ? 'right' : `wrong at bar ${bar}`;
  });
  expect(verdicts.filter(verdict => verdict.startsWith('wrong'))).toEqual([]);
  expect(verdicts.filter(verdict => verdict === 'right').length).toBeGreaterThan(SAMPLED.length * 0.8);
  expect(same(await sample(page, study.pane), studyPlain)).toBe(SAMPLED.length);

  // In the study pane: the candles are as they were and the histogram pane is tinted.
  await chooseShading(page, study.id, 'In study pane', info);
  expect(await shading(page, study.id)).toEqual({ shade: 'study', summary: '10 study' });
  expect(await sample(page, 0)).toEqual(plain);
  expect(same(await sample(page, study.pane), studyPlain)).toBeLessThan(SAMPLED.length / 2);
  await shot(page, info, 'routed-shading-in-study-pane');
  // Back on the candles exactly as before; the study pane is clear again.
  await chooseShading(page, study.id, 'On price');
  expect(await shading(page, study.id)).toEqual({ shade: 'price', summary: '10 price' });
  expect(await sample(page, 0)).toEqual(shaded);
  expect(await sample(page, study.pane)).toEqual(studyPlain);
  // Removing the study takes the shading with it.
  await page.evaluate(id => { (window as unknown as DemoWindow).__oac.app.chart.removeIndicator(id); }, study.id);
  await paint(page);
  expect(await page.evaluate(() => (window as unknown as DemoWindow).__oac.app.chart.panes()
    .some(pane => pane.primitives().some(layer => Array.isArray((layer as unknown as { _colors?: unknown })._colors))))).toBe(false);
  expect(errors).toEqual([]);
});
