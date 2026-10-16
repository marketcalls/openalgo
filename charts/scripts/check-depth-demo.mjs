/** Exercise the published API through the website's simulated depth demo. */
import { strict as assert } from 'node:assert';
import { mkdir } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { chromium, expect } from '@playwright/test';

const base = (process.argv[2] ?? 'http://127.0.0.1:4174/openalgo-charts').replace(/\/$/, '');
await mkdir('artifacts', { recursive: true });
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.addInitScript(() => {
    // Observe real browser timers and canvas output without replacing their work.
    window.__depthTimers = new Set();
    window.__depthCanvasText = new WeakMap();
    const setInterval = window.setInterval.bind(window);
    const clearInterval = window.clearInterval.bind(window);
    window.setInterval = (callback, delay, ...args) => {
      const id = setInterval(callback, delay, ...args);
      if (delay === 750) window.__depthTimers.add(id);
      return id;
    };
    window.clearInterval = id => {
      window.__depthTimers.delete(id);
      return clearInterval(id);
    };
    const fillText = CanvasRenderingContext2D.prototype.fillText;
    CanvasRenderingContext2D.prototype.fillText = function (...args) {
      const values = window.__depthCanvasText.get(this.canvas) ?? new Set();
      values.add(String(args[0]));
      window.__depthCanvasText.set(this.canvas, values);
      return fillText.apply(this, args);
    };
  });
  const response = await page.goto(`${base}/docs/depth-of-market/`);
  assert.equal(response.status(), 200, 'The depth-of-market documentation route must exist');
  const demo = page.getByRole('region', { name: 'Simulated depth of market' });
  await expect(demo.getByRole('button', { name: 'Pause updates' })).toBeEnabled();
  await expect(demo.locator('canvas').first()).toBeVisible();

  const snapshot = demo.getByLabel('Snapshot number');
  const first = await snapshot.textContent();
  const initialRows = await demo.locator('tbody').textContent();
  await expect(snapshot).not.toHaveText(first);
  await expect(demo.locator('tbody')).not.toHaveText(initialRows);
  await demo.getByRole('button', { name: 'Pause updates' }).click();
  const paused = await snapshot.textContent();
  const frozenRows = await demo.locator('tbody').textContent();
  await page.waitForTimeout(1100);
  assert.equal(await snapshot.textContent(), paused, 'Pause must stop simulated updates');
  assert.equal(await demo.locator('tbody').textContent(), frozenRows);
  assert.equal(await page.evaluate(() => window.__depthTimers.size), 0);

  const readBook = () => demo.locator('tbody tr').evaluateAll(rows => rows.map(row => ({
    price: Number(row.children[1].textContent),
    bid: Number(row.children[0].textContent.replaceAll(',', '')),
    ask: Number(row.children[2].textContent.replaceAll(',', '')),
  })));
  const totals = rows => rows.reduce((sum, row) => [sum[0] + row.bid, sum[1] + row.ask], [0, 0]);
  const raw = await readBook();
  assert.equal(raw.length, 40, '20 source levels per side should display 40 raw rows');
  const bookBounds = await demo.getByLabel('Scrollable depth rows').boundingBox();
  const headerBounds = await demo.getByRole('columnheader', { name: 'Bid qty' }).boundingBox();
  assert.ok(headerBounds.y >= bookBounds.y && headerBounds.y < bookBounds.y + 32, 'Column headings must stay visible when the book is scrolled to its centre');
  await page.mouse.move(0, 0);
  await page.waitForTimeout(150);
  const chartPixels = async () => createHash('sha256').update(await demo.locator('.depth-chart canvas').first().evaluate(canvas => canvas.toDataURL())).digest('hex');
  const originalChart = await chartPixels();
  for (const step of ['0.25', '0.50', '1.00']) {
    await demo.getByLabel('Display row size').selectOption(step);
    const grouped = await readBook();
    assert.ok(grouped.length < raw.length, 'Larger display rows must aggregate the supplied book');
    assert.deepEqual(totals(grouped), totals(raw), 'Grouping must preserve both side totals');
    assert.ok(grouped.every(row => Math.abs(row.price / Number(step) - Math.round(row.price / Number(step))) < 1e-7));
    assert.equal(await snapshot.textContent(), paused, 'Changing grouping must preserve the paused snapshot');
    await page.waitForTimeout(150);
    assert.equal(await chartPixels(), originalChart, 'Ladder grouping must not change the candle chart or its price scale');
  }

  await demo.getByLabel('Display row size').selectOption('0.05');
  assert.deepEqual(await readBook(), raw, 'Returning to the source tick must restore the original rows');
  const chartBounds = await demo.locator('.depth-chart').boundingBox();
  await page.mouse.move(chartBounds.x + chartBounds.width - 20, chartBounds.y + 140);
  await page.mouse.down();
  await page.mouse.move(chartBounds.x + chartBounds.width - 20, chartBounds.y + 210, { steps: 6 });
  await page.mouse.up();
  await page.mouse.move(0, 0);
  await page.waitForTimeout(150);
  const manuallyScaled = await chartPixels();
  assert.notEqual(manuallyScaled, originalChart, 'The regression check must start with a manually adjusted price scale');
  await demo.getByLabel('Display row size').selectOption('0.50');
  await page.waitForTimeout(150);
  assert.equal(await chartPixels(), manuallyScaled, 'Grouping must preserve a manually adjusted price scale');
  await demo.getByLabel('Display row size').selectOption('0.05');
  await demo.locator('canvas').evaluateAll(canvases => canvases.forEach(canvas => window.__depthCanvasText.delete(canvas)));
  await demo.getByLabel('Chart and ladder').selectOption('spot-option');
  await expect(demo.getByText('NIFTY spot · candlesticks', { exact: true })).toBeVisible();
  await expect.poll(chartPixels).not.toBe(originalChart);
  await expect.poll(() => demo.locator('.depth-chart canvas').evaluateAll(canvases =>
    canvases.flatMap(canvas => Array.from(window.__depthCanvasText.get(canvas) ?? []))
      .some(text => /^24,?0\d\d(?:\.\d+)?$/.test(text))
  )).toBe(true);
  assert.deepEqual(await readBook(), raw, 'Changing the chart instrument must preserve the independent option book');
  await page.waitForTimeout(150);
  const spotChart = await chartPixels();
  await demo.getByLabel('Display row size').selectOption('1.00');
  await page.waitForTimeout(150);
  assert.equal(await chartPixels(), spotChart, 'Option grouping must not rescale a spot chart');
  await demo.getByLabel('Display row size').selectOption('0.05');
  for (const levels of ['5', '200']) {
    await demo.getByLabel('Depth levels per side').selectOption(levels);
    assert.equal((await readBook()).length, Number(levels) * 2);
    assert.equal(await snapshot.textContent(), paused, 'Depth selection must not restart a paused simulation');
    await page.waitForTimeout(150);
    assert.equal(await chartPixels(), spotChart, 'Depth selection must not alter the chart');
  }
  await demo.getByLabel('Chart and ladder').selectOption('option-option');
  await expect(demo.getByText('NIFTY ATM CE · candlesticks', { exact: true })).toBeVisible();
  await demo.getByLabel('Display row size').selectOption('0.50');
  const pick = demo.getByRole('button', { name: /^Inspect bid at / }).first();
  await pick.click();
  await expect(demo.getByRole('status')).toContainText('Bid at');
  await expect(demo.getByRole('status')).toContainText('simulation only');
  const sharedRow = pick.locator('..').locator('..');
  await sharedRow.getByRole('button', { name: /^Inspect ask at / }).click();
  await expect(demo.getByRole('status')).toContainText('Ask at');
  await demo.getByRole('button', { name: 'Resume updates' }).click();
  await expect(snapshot).not.toHaveText(paused);
  assert.equal(await page.evaluate(() => window.__depthTimers.size), 1, 'Resume must create exactly one update timer');
  await demo.getByRole('button', { name: 'Pause updates' }).click();

  await page.evaluate(() => {
    localStorage.setItem('oac-theme', 'light');
  });
  await page.reload();
  await expect(page.locator('html')).toHaveClass(/light/);
  await expect(demo.getByRole('button', { name: 'Pause updates' })).toBeEnabled();
  await demo.getByRole('button', { name: 'Pause updates' }).click();
  await demo.screenshot({ path: 'artifacts/website-depth-light.png' });
  await page.evaluate(() => localStorage.setItem('oac-theme', 'dark'));
  await page.reload();
  await expect(page.locator('html')).toHaveClass(/dark/);
  await expect(demo.getByRole('button', { name: 'Pause updates' })).toBeEnabled();
  await demo.getByRole('button', { name: 'Pause updates' }).click();
  await demo.screenshot({ path: 'artifacts/website-depth-dark.png' });
  await page.setViewportSize({ width: 390, height: 844 });
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), 'Mobile page must not overflow horizontally');
  await demo.screenshot({ path: 'artifacts/website-depth-mobile.png' });
  await demo.getByRole('button', { name: 'Resume updates' }).click();
  const origin = await page.evaluate(() => performance.timeOrigin);
  await page.getByRole('link', { name: 'Data feeds', exact: true }).last().click();
  await expect(demo).toHaveCount(0);
  assert.equal(await page.evaluate(() => performance.timeOrigin), origin, 'Lifecycle check must navigate within the same document');
  assert.equal(await page.evaluate(() => window.__depthTimers.size), 0, 'Unmount must clear the simulation timer');
  assert.deepEqual(errors, []);
  console.log('Depth demo checks passed: independent candle/ladder scales, option and spot scenarios, changing quantities, pause/resume, quantity-preserving grouping, 5/20/200 levels, row inspection, themes, mobile layout and timer cleanup.');
} finally {
  await browser.close();
}
