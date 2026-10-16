import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, SeriesApi } from '../../src/index';

declare global {
  interface Window {
    __annotationStyle: {
      chart: Chart; study: IndicatorApi; price: SeriesApi;
      info(): { caption: number; text: number; glyph: number; outside: number; baseHash: number };
    };
  }
}
const painted = (page: Page) => page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
async function textStyle(page: Page, text: string) {
  return page.evaluate(text => {
    const document = new DOMParser().parseFromString(window.__annotationStyle.chart.exportSVG(), 'image/svg+xml');
    const item = [...document.querySelectorAll('text')].find(item => item.textContent === text);
    return item && { size: item.getAttribute('font-size'), family: item.getAttribute('font-family'),
      weight: item.getAttribute('font-weight'), slant: item.getAttribute('font-style'), fill: item.getAttribute('fill'),
      anchor: item.getAttribute('text-anchor') };
  }, text);
}
for (const width of [1100, 390]) for (const dpr of [1, 1.5, 2]) {
  test.describe(`annotation type width ${width} DPR ${dpr}`, () => {
    test.use({ viewport: { width, height: 740 }, deviceScaleFactor: dpr });
    test('renders independent text and preserves its owner through updates and restore', async ({ page }, info) => {
      const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
      await page.goto('/tests/e2e/indicator-text-style-fixture.html');
      await page.waitForFunction(() => Boolean(window.__annotationStyle)); await painted(page);
      const before = await page.evaluate(() => ({ values: window.__annotationStyle.study.values(), bars: window.__annotationStyle.chart.primaryBars() }));
      const initial = await page.evaluate(() => window.__annotationStyle.info());
      expect(initial.caption).toBeGreaterThan(35 * dpr * dpr); expect(initial.text).toBeGreaterThan(15 * dpr * dpr);
      // A narrow plot clamps the circle to 4 CSS pixels; its antialiased edge is excluded by the exact-color count.
      expect(initial.glyph).toBeGreaterThanOrEqual(4 * dpr * dpr); expect(initial.outside).toBe(0);
      expect(await textStyle(page, 'Styled')).toMatchObject({ size: '18', family: 'ui-monospace, monospace', weight: '600', slant: 'italic', fill: '#baf2ff' });
      expect(await textStyle(page, 'Mark')).toMatchObject({ fill: '#d3f34a', family: 'ui-monospace, monospace', weight: '600' });
      await page.screenshot({ path: info.outputPath('initial-typography.png') });

      await page.evaluate(() => window.__annotationStyle.study.setSettings({ size: 26, align: 'right' })); await painted(page);
      const larger = await page.evaluate(() => window.__annotationStyle.info());
      expect(larger.baseHash).not.toBe(initial.baseHash); expect(larger.text).toBeGreaterThan(initial.text);
      expect(larger.glyph).toBe(initial.glyph); expect(larger.outside).toBe(0);
      expect(await textStyle(page, 'Styled')).toMatchObject({ size: '26', anchor: 'end' });
      expect(await textStyle(page, 'Mark')).toMatchObject({ size: '26', anchor: 'end' });
      await page.screenshot({ path: info.outputPath('larger-right-aligned.png') });

      const saved = await page.evaluate(() => window.__annotationStyle.chart.getState());
      await page.evaluate(() => window.__annotationStyle.study.setVisible(false)); await painted(page);
      expect(await page.evaluate(() => window.__annotationStyle.info())).toMatchObject({ caption: 0, text: 0, glyph: 0 });
      await page.evaluate(state => {
        const h = window.__annotationStyle, report = h.chart.restoreState(state);
        if (!report.applied) throw new Error('Typography restore failed');
        h.study = h.chart.indicators()[0];
      }, saved); await painted(page);
      expect(await textStyle(page, 'Styled')).toMatchObject({ size: '26', anchor: 'end' });
      await page.evaluate(() => {
        const h = window.__annotationStyle, bars = h.chart.primaryBars(), last = bars[bars.length - 1];
        h.price.update({ ...last, close: last.close + 1 });
      }); await painted(page);
      expect(await textStyle(page, 'Mark')).toMatchObject({ size: '26', fill: '#d3f34a' });
      await page.evaluate(() => {
        const h = window.__annotationStyle, bars = h.chart.primaryBars(), last = bars[bars.length - 1];
        h.price.update({ ...last, close: last.close - 1 });
        h.study.setSettings({ plain: true });
      }); await painted(page);
      expect(await textStyle(page, 'Styled')).toMatchObject({ size: '11', weight: null, slant: null });
      const after = await page.evaluate(() => ({ values: window.__annotationStyle.study.values(), bars: window.__annotationStyle.chart.primaryBars() }));
      expect(after).toEqual(before);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(width);
      await page.screenshot({ path: info.outputPath('restored-default-caption.png') });
      await page.evaluate(() => window.__annotationStyle.study.remove()); await painted(page);
      expect(await page.evaluate(() => window.__annotationStyle.info())).toMatchObject({ caption: 0, text: 0, glyph: 0 });
      expect(errors).toEqual([]);
    });
  });
}
