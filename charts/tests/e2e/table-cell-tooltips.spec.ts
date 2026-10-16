import { expect, test, type Page } from '@playwright/test';
import type { Chart, ChartTable, IndicatorApi, PrimitiveHit } from '../../src/index';

declare global {
  interface Window {
    __tableTooltips: {
      chart: Chart; study: IndicatorApi; table: ChartTable; clicks: (string | null)[]; hovers: (string | null)[];
      point(pane: number, row?: number, column?: number): { x: number; y: number };
      setTooltips(enabled: boolean): void;
      hit(pane: number, row?: number, column?: number): PrimitiveHit | null;
      measure(pane: number): { ink: number; axisHash: number; dpr: number };
      resize(): void;
    };
  }
}
const painted = (page: Page) => page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
async function hover(page: Page, pane: number, row = 1, column = 0) {
  const point = await page.evaluate(({ pane, row, column }) => window.__tableTooltips.point(pane, row, column), { pane, row, column });
  await page.mouse.move(2, 2); await page.mouse.move(point.x, point.y); await painted(page);
  return point;
}

for (const width of [1100, 390]) for (const dpr of [1, 1.5, 2]) {
  test.describe(`table details width ${width} DPR ${dpr}`, () => {
    test.use({ viewport: { width, height: 790 }, deviceScaleFactor: dpr });
    test('keeps cell hover, click identity, geometry and owner lifecycle consistent', async ({ page }, info) => {
      const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
      await page.goto('/tests/e2e/table-cell-tooltips-fixture.html');
      await page.waitForFunction(() => window.__tableTooltips !== undefined); await painted(page);
      const before = await page.evaluate(() => ({ bars: window.__tableTooltips.chart.primaryBars(), values: window.__tableTooltips.study.values() }));
      await page.evaluate(() => window.__tableTooltips.setTooltips(false)); await painted(page);
      await hover(page, 0);
      const plain = await page.evaluate(() => window.__tableTooltips.measure(0));
      await page.evaluate(() => window.__tableTooltips.setTooltips(true)); await painted(page);
      const leftPoint = await hover(page, 0);
      const left = await page.evaluate(() => ({ pixels: window.__tableTooltips.measure(0), hit: window.__tableTooltips.hit(0) }));
      expect(left.hit?.externalId).toBe('shared-table'); expect(left.hit?.hoverKey).toBeTruthy();
      expect(left.pixels.ink - plain.ink).toBeGreaterThan(200 * dpr * dpr);
      expect(left.pixels.axisHash).toBe(plain.axisHash);
      await page.mouse.click(leftPoint.x, leftPoint.y); await painted(page);
      expect(await page.evaluate(() => {
        const clicks = window.__tableTooltips.clicks;
        return clicks[clicks.length - 1];
      })).toBe('shared-table');

      await hover(page, 0, 1, 1);
      const right = await page.evaluate(() => window.__tableTooltips.hit(0, 1, 1));
      expect(right?.externalId).toBe('shared-table'); expect(right?.hoverKey).not.toBe(left.hit?.hoverKey);
      const merged = await page.evaluate(() => [window.__tableTooltips.hit(0, 0, 0), window.__tableTooltips.hit(0, 0, 1)]);
      expect(merged[0]?.hoverKey).toBeTruthy(); expect(merged[1]?.hoverKey).toBe(merged[0]?.hoverKey);
      await hover(page, 0, 0, 1);
      await page.screenshot({ path: info.outputPath('merged-tooltip.png') });
      const svg = await page.evaluate(() => window.__tableTooltips.chart.exportSVG({ width: 900, height: 640 }));
      expect(svg).toContain('Merged heading'); expect(svg).not.toContain('Merged detail'); expect(svg).not.toContain('Covered detail');
      await painted(page);
      await hover(page, 0, 2, 0);
      expect(await page.evaluate(() => window.__tableTooltips.hit(0, 2, 0)?.hoverKey)).toBeUndefined();

      await hover(page, 1);
      const second = await page.evaluate(() => ({ hit: window.__tableTooltips.hit(1), firstInk: window.__tableTooltips.measure(0).ink,
        secondInk: window.__tableTooltips.measure(1).ink }));
      expect(second.hit?.externalId).toBe('shared-table'); expect(second.hit?.hoverKey).not.toBe(left.hit?.hoverKey);
      expect(second.firstInk).toBeLessThan(left.pixels.ink - 100 * dpr * dpr);
      await page.evaluate(() => window.__tableTooltips.study.setSettings({ alternate: true })); await painted(page);
      const changed = await page.evaluate(() => ({ hit: window.__tableTooltips.hit(1), ink: window.__tableTooltips.measure(1).ink }));
      expect(changed.hit?.hoverKey).not.toBe(second.hit?.hoverKey);
      expect(changed.ink).toBeLessThan(second.secondInk - 100 * dpr * dpr);
      await hover(page, 1); await page.screenshot({ path: info.outputPath('updated-owner-tooltip.png') });
      await page.evaluate(() => window.__tableTooltips.study.setVisible(false)); await painted(page);
      expect(await page.evaluate(() => window.__tableTooltips.hit(1))).toBeNull();
      await page.evaluate(() => window.__tableTooltips.study.setVisible(true)); await painted(page); await hover(page, 1);
      expect(await page.evaluate(() => window.__tableTooltips.hit(1)?.hoverKey)).toBeTruthy();

      await page.evaluate(() => window.__tableTooltips.resize()); await painted(page); await hover(page, 0, 0, 0);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: info.outputPath('resized-tooltip.png') });
      await page.evaluate(() => window.__tableTooltips.chart.removePrimitive(window.__tableTooltips.table)); await painted(page);
      expect(await page.evaluate(() => window.__tableTooltips.table.hitTest(80, 82))).toBeNull();
      await page.evaluate(() => window.__tableTooltips.chart.addPrimitive(window.__tableTooltips.table)); await painted(page); await hover(page, 0);
      expect(await page.evaluate(() => window.__tableTooltips.hit(0)?.hoverKey)).toBeTruthy();
      const after = await page.evaluate(() => ({ bars: window.__tableTooltips.chart.primaryBars(), values: window.__tableTooltips.study.values() }));
      expect(after).toEqual(before);
      await page.evaluate(() => window.__tableTooltips.study.remove()); await painted(page);
      expect(await page.evaluate(() => window.__tableTooltips.chart.indicators().length)).toBe(0);
      expect(errors).toEqual([]);
    });
  });
}

test.describe('table details with a touch pointer', () => {
  test.use({ viewport: { width: 390, height: 790 }, hasTouch: true, deviceScaleFactor: 1 });
  test('keeps the table click ID and clears the detail after release', async ({ page }) => {
    await page.goto('/tests/e2e/table-cell-tooltips-fixture.html');
    await page.waitForFunction(() => window.__tableTooltips !== undefined); await painted(page);
    await page.evaluate(() => {
      const events: string[] = [];
      Object.assign(window, { __tablePointerEvents: events });
      for (const type of ['pointerdown', 'pointerup']) document.addEventListener(type, event => {
        events.push(`${event.type}:${(event as PointerEvent).pointerType}`);
      });
    });
    const point = await page.evaluate(() => window.__tableTooltips.point(0));
    await page.touchscreen.tap(point.x, point.y); await painted(page);
    const released = await page.evaluate(() => ({
      clicks: window.__tableTooltips.clicks, hovers: window.__tableTooltips.hovers,
      pixels: window.__tableTooltips.measure(0),
      pointers: (window as unknown as { __tablePointerEvents: string[] }).__tablePointerEvents,
    }));
    expect(released.clicks).toEqual(['shared-table']);
    expect(released.hovers).toEqual(['shared-table', null]);
    expect(released.pointers).toEqual(['pointerdown:touch', 'pointerup:touch']);
    await page.evaluate(() => window.__tableTooltips.setTooltips(false)); await painted(page);
    expect(await page.evaluate(() => window.__tableTooltips.measure(0))).toEqual(released.pixels);
  });
});
