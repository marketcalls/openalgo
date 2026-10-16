import { expect, test, type Page } from '@playwright/test';
import type { Widget } from '../../src/widget/widget';
import type { Chart } from '../../src/core/chart';
import type { DrawingController } from '../../src/draw/controller';

declare global {
  interface Window {
    __stack: {
      widget: Widget; chart: Chart; flatId: string; boxId: string; coverId: string;
      glChart: Chart; glDraw: DrawingController; glFlatId: string; glBoxId: string; targets: string[];
      at(time: number, price: number): { x: number; y: number };
      t(index: number): number;
      body(index: number): number;
      pixel(which: 'main' | 'gl', time: number, price: number): number[];
    };
  }
}

async function mount(page: Page): Promise<string[]> {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1200, height: 1000 });
  await page.goto('/tests/e2e/stack-order-fixture.html');
  await page.waitForFunction(() => !!window.__stack);
  return errors;
}

/** Which of the two opaque colours one pixel of the main chart shows. */
async function colour(page: Page, which: 'main' | 'gl', bar: number, price: number): Promise<string> {
  const [r, g, b] = await page.evaluate(([w, i, p]) => window.__stack.pixel(w as 'main' | 'gl', window.__stack.t(i as number), p as number), [which, bar, price]);
  if (r > 200 && g < 60 && b < 60) return 'red';
  if (r < 60 && g < 60 && b > 200) return 'blue';
  if (r < 60 && g > 200 && b > 200) return 'cyan';
  return `other(${r},${g},${b})`;
}

/** Paint the next frame before reading pixels: placement repaints on the next animation frame. */
const settle = (page: Page) => page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));

test('a drawing paints where it is placed in the stack: in front, between studies, behind the series', async ({ page }, info) => {
  const errors = await mount(page);
  await settle(page);
  // Bar 80 at price 120 is on the flat study and inside the blue box.
  expect(await colour(page, 'main', 80, 120)).toBe('blue');
  await page.evaluate(() => { const s = window.__stack; s.widget.draw.placeInStack(s.boxId, { entry: 'source:primary' }, 'above'); });
  await settle(page);
  expect(await colour(page, 'main', 80, 120)).toBe('red');
  await page.screenshot({ path: info.outputPath('box-under-study.png') });
  await page.evaluate(() => { const s = window.__stack; s.widget.draw.placeInStack(s.boxId, { entry: 'indicator:' + s.flatId }, 'above'); });
  await settle(page);
  expect(await colour(page, 'main', 80, 120)).toBe('blue');
  await page.screenshot({ path: info.outputPath('box-over-study.png') });
  // The cyan box covers candles; behind the series a candle body shows through it.
  const body = await page.evaluate(() => window.__stack.body(125));
  expect(await colour(page, 'main', 125, body)).toBe('cyan');
  await page.evaluate(() => { const s = window.__stack; s.widget.draw.sendBehindSeries(s.coverId); });
  await settle(page);
  expect(await colour(page, 'main', 125, body)).not.toBe('cyan');
  // And moving the source over the flat study leaves the study where it paints.
  await page.evaluate(() => { const s = window.__stack; s.chart.moveInSeriesStack('source:primary', 'indicator:' + s.flatId, 'above'); });
  await settle(page);
  expect(await page.evaluate(() => window.__stack.chart.seriesStack(0))).toEqual(await page.evaluate(() => ['indicator:' + window.__stack.flatId, 'source:primary']));
  expect(await colour(page, 'main', 80, 120)).toBe('blue');
  await page.screenshot({ path: info.outputPath('stack-final.png') });
  expect(errors).toEqual([]);
});

test('the renderer the browser gives the second chart keeps the same order', async ({ page }, info) => {
  const errors = await mount(page);
  await settle(page);
  const kind = await page.evaluate(() => window.__stack.glChart.rendererKind);
  info.annotations.push({ type: 'renderer', description: String(kind) });
  expect(await colour(page, 'gl', 80, 120)).toBe('blue');
  await page.evaluate(() => { const s = window.__stack; s.glDraw.placeInStack(s.glBoxId, { entry: 'source:primary' }, 'above'); });
  await settle(page);
  expect(await colour(page, 'gl', 80, 120)).toBe('red');
  await page.evaluate(() => { const s = window.__stack; s.glDraw.placeInStack(s.glBoxId, { entry: 'indicator:' + s.glFlatId }, 'above'); });
  await settle(page);
  expect(await colour(page, 'gl', 80, 120)).toBe('blue');
  await page.locator('#gl').screenshot({ path: info.outputPath(`gl-${kind}.png`) });
  expect(errors).toEqual([]);
});

test('the pointer takes what is painted on top', async ({ page }) => {
  const errors = await mount(page);
  await settle(page);
  const at = await page.evaluate(() => window.__stack.at(window.__stack.t(80), 120));
  const lastTarget = async (): Promise<string> => {
    await page.mouse.click(at.x, at.y, { button: 'right' });
    await page.keyboard.press('Escape');
    return page.evaluate(() => window.__stack.targets.at(-1)!);
  };
  expect(await lastTarget()).toBe('drawing');
  await page.evaluate(() => { const s = window.__stack; s.widget.draw.placeInStack(s.boxId, { entry: 'source:primary' }, 'above'); });
  await settle(page);
  expect(await lastTarget()).toBe('indicator');
  await page.evaluate(() => { const s = window.__stack; s.widget.draw.placeInStack(s.boxId, { entry: 'indicator:' + s.flatId }, 'above'); });
  await settle(page);
  expect(await lastTarget()).toBe('drawing');
  // Where two boxes overlap a click selects the one painted on top.
  const second = await page.evaluate(() => {
    const s = window.__stack;
    return s.widget.draw.add({ tool: 'rectangle', paneIndex: 0, points: [{ time: s.t(70), price: 124 }, { time: s.t(90), price: 110 }],
      style: { color: '#00ff00', fill: true, fillOpacity: 1 } }).id;
  });
  await page.evaluate(() => window.__stack.widget.draw.select(null));
  const inner = await page.evaluate(() => window.__stack.at(window.__stack.t(85), 117));
  await page.mouse.click(inner.x, inner.y);
  expect(await page.evaluate(() => window.__stack.widget.draw.selection())).toEqual([second]);
  await page.evaluate((id) => { const s = window.__stack; s.widget.draw.placeInStack(id, { entry: 'source:primary' }, 'above'); s.widget.draw.select(null); }, second);
  await settle(page);
  await page.mouse.click(inner.x, inner.y);
  expect(await page.evaluate(() => window.__stack.widget.draw.selection())).toEqual(await page.evaluate(() => [window.__stack.boxId]));
  expect(errors).toEqual([]);
});

test('the Objects panel lists each pane in draw order and reorders it by drag', async ({ page }, info) => {
  const errors = await mount(page);
  const opener = page.getByRole('button', { name: 'Objects', exact: true });
  await opener.click();
  const panel = page.locator('.oac-objects');
  await expect(panel.getByRole('searchbox')).toBeVisible();
  const ids = () => panel.locator('[data-pane-index="0"] [data-object-id]').evaluateAll(nodes => nodes.map(node => (node as HTMLElement).dataset.objectId));
  const { flat, box, cover } = await page.evaluate(() => ({ flat: 'indicator:' + window.__stack.flatId,
    box: 'drawing:' + window.__stack.boxId, cover: 'drawing:' + window.__stack.coverId }));
  expect(await ids()).toEqual(['source:primary', flat, box, cover]);
  // Drop the blue box on the upper half of the flat study's row: it goes under the study.
  const target = panel.locator(`[data-object-id="${flat}"]`);
  const tbox = (await target.boundingBox())!;
  await panel.locator(`[data-object-id="${box}"]`).dragTo(target, { targetPosition: { x: tbox.width / 2, y: 4 } });
  await expect.poll(ids).toEqual(['source:primary', box, flat, cover]);
  await settle(page);
  expect(await colour(page, 'main', 80, 120)).toBe('red');
  await expect(panel.locator(`[data-object-id="${box}"]`)).toContainText('Above');
  await page.screenshot({ path: info.outputPath('objects-draw-order.png') });
  // Earlier and Later step it back through the same order.
  await panel.locator(`[data-object-id="${box}"] [data-action="later"]`).click();
  await expect.poll(ids).toEqual(['source:primary', flat, box, cover]);
  await settle(page);
  expect(await colour(page, 'main', 80, 120)).toBe('blue');
  expect(errors).toEqual([]);
});
