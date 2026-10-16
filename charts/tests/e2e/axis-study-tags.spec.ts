import { expect, test, type Page } from '@playwright/test';
import type { Chart } from '../../src/index';
import type * as Charts from '../../src/index';

/**
 * The price axis of a study pane, and of the price pane beside it.
 *
 * Reported on a live chart: the study pane's value tag carried the bar
 * countdown, a clock for a bar that pane does not draw, which doubled the tag
 * into the study's own level tags, and the 70 level tag painted over it; and
 * tick labels at the panes' edges were printed cut in half. Here the study
 * ends between its 50 and 30 levels, near enough to both that a two-row tag
 * reaches their tags, and an order rests just under the last price, so each
 * readout tag meets a level tag.
 */

declare global {
  interface Window { __axis: { chart: Chart; texts: { pane: number; text: string; x: number; y: number; top: number; bottom: number; fill: string }[] } }
}

async function mount(page: Page): Promise<void> {
  await page.setViewportSize({ width: 960, height: 640 });
  await page.route('**/axis-study-tags.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#c{width:960px;height:640px}</style></head><body><div id="c"></div></body></html>',
  }));
  await page.goto('/axis-study-tags.html');
  await page.evaluate(async () => {
    const { createChart, darkTheme } = await import('/dist/openalgo-charts.mjs') as typeof Charts;
    await import('/dist/openalgo-charts.indicators.mjs');
    // A seeded walk with clustered volatility and an overnight gap each
    // session.
    let seed = 4242, price = 1840, vol = 1.2, time = 1_758_000_000;
    const rnd = (): number => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0), seed / 4294967296);
    const bars = Array.from({ length: 220 }, (_, i) => {
      vol = Math.max(0.4, Math.min(6, vol * (0.9 + rnd() * 0.22)));
      const open = price, close = open + (rnd() - 0.5) * 2 * vol + (i > 190 ? 0.42 : 0);
      price = close;
      time += (i + 1) % 75 === 0 ? 17 * 3600 : 300;
      return { time, open, high: Math.max(open, close) + rnd() * vol, low: Math.min(open, close) - rnd() * vol, close };
    });
    const last = bars[bars.length - 1];
    const chart = createChart(document.getElementById('c')!, {
      theme: darkTheme, branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
      axisChrome: { barCountdown: true, clock: () => last.time + 130 },
    });
    chart.addSeries('candlestick').setData(bars);
    chart.addIndicator('rsi');
    chart.addPriceLine({ id: 'order', price: last.close - 0.4, color: '#7e57c2', label: 'BUY 25' });
    // Every text each pane's base canvas prints, with its ink box in device px.
    const texts: Window['__axis']['texts'] = [];
    chart.panes().forEach((pane, index) => {
      const ctx = pane.base.ctx;
      const fillText = ctx.fillText.bind(ctx);
      ctx.fillText = (text: string, x: number, y: number, maxWidth?: number) => {
        const m = ctx.measureText(text), t = ctx.getTransform();
        texts.push({ pane: index, text, x: x + t.e, y: y + t.f, top: y + t.f - m.actualBoundingBoxAscent,
          bottom: y + t.f + m.actualBoundingBoxDescent, fill: String(ctx.fillStyle) });
        if (maxWidth === undefined) fillText(text, x, y); else fillText(text, x, y, maxWidth);
      };
    });
    window.__axis = { chart, texts };
  });
}

/** One full frame, recording its texts afresh. */
async function repaint(page: Page): Promise<void> {
  await page.evaluate(() => { window.__axis.texts.length = 0; window.__axis.chart.invalidate((m) => m.invalidateGlobal(3)); });
  await page.evaluate(() => new Promise<void>(r => requestAnimationFrame(() => requestAnimationFrame(() => r()))));
}

test('the study pane carries no countdown, its value reads over its levels, and no tick label is cut', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  await repaint(page);
  const facts = await page.evaluate(() => {
    const { chart, texts } = window.__axis;
    const dpr = window.devicePixelRatio;
    const clock = /^\d\d:\d\d:\d\d$/;
    // The study's own level tags, which the value tag meets.
    const LEVELS = ['70.00', '50.00', '30.00'];
    const panes = chart.panes().map((pane, index) => ({
      plotBottom: pane.priceScale.height * dpr,
      clocks: texts.filter(t => t.pane === index && clock.test(t.text)).length,
    }));
    // Tick labels: printed in the axis text colour, right of the plot.
    const axisText = String(chart.theme().axisText);
    const plotRight = chart.timeScale.width * dpr;
    const ticks = texts.filter(t => t.x > plotRight && t.fill.toLowerCase() === axisText.toLowerCase());
    const cut = ticks.filter(t => t.top < -0.5 || t.bottom > panes[t.pane].plotBottom + 0.5).map(t => `${t.pane}:${t.text}`);
    // Where each readout tag's text sits, and the colour painted there last.
    const readout = (index: number, pattern: RegExp): { text: string; covered: boolean } | null => {
      const t = texts.filter(x => x.pane === index && x.x > plotRight && pattern.test(x.text) && !LEVELS.includes(x.text)).pop();
      if (t === undefined) return null;
      const canvas = chart.panes()[index].base.element;
      const px = canvas.getContext('2d')!.getImageData(Math.round(t.x - 3 * dpr), Math.round(t.y), 1, 1).data;
      const [r, g, b] = [1, 3, 5].map(i => parseInt(chart.theme().lastPriceUp.slice(i, i + 2), 16));
      const [r2, g2, b2] = [1, 3, 5].map(i => parseInt(chart.theme().lastPriceDown.slice(i, i + 2), 16));
      const near = (a: number, c: number): boolean => Math.abs(a - c) < 3;
      const tagged = (near(px[0], r) && near(px[1], g) && near(px[2], b)) || (near(px[0], r2) && near(px[1], g2) && near(px[2], b2));
      return { text: t.text, covered: !tagged };
    };
    return { panes, ticks: ticks.length, cut, study: readout(1, /^\d+\.\d\d$/), price: readout(0, /^18\d\d\.\d$/) };
  });
  await page.screenshot({ path: info.outputPath('axis-study-tags.png') });
  expect(facts.panes).toHaveLength(2);
  expect(facts.panes[0].clocks, 'the price pane counts its bar down').toBe(1);
  expect(facts.panes[1].clocks, 'the study pane carries no countdown').toBe(0);
  expect(facts.ticks, "tick labels to check").toBeGreaterThan(5);
  expect(facts.cut, 'tick labels cut by a pane edge').toEqual([]);
  expect(facts.study?.covered, `the study value ${facts.study?.text} is not covered by its level tag`).toBe(false);
  expect(facts.price?.covered, `the last price ${facts.price?.text} is not covered by the order tag`).toBe(false);
  expect(errors).toEqual([]);
});
