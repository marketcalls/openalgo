import { expect, test, type Page } from '@playwright/test';
import type { Chart } from '../../src/index';
import type * as Charts from '../../src/index';

/**
 * A chart parked out of the document while the pointer is over it.
 *
 * A framework that keeps a view alive moves its DOM out of the document when
 * the user switches away, and the switch is often a key. The browser sends no
 * pointerleave to a node it has removed, and the chart hears keys on the
 * document, so it went on answering hover-scoped keys typed at the view that
 * replaced it. Here a key swaps the chart's container for another view in the
 * same place, the pointer never moves, and the arrow that follows must leave
 * the parked chart where it was.
 */

declare global {
  interface Window { __park: { chart: Chart; range: () => string; swaps: number } }
}

async function mount(page: Page): Promise<void> {
  await page.setViewportSize({ width: 900, height: 560 });
  await page.route('**/detached-container.html', route => route.fulfill({
    contentType: 'text/html',
    body: `<!doctype html><html><head><style>
      html,body{margin:0;background:#101010;color:#c8ccd8;font:13px system-ui,sans-serif}
      #slot{position:absolute;left:20px;top:20px;width:820px;height:480px}
      #slot > div{width:100%;height:100%}
      #other{display:flex;align-items:center;justify-content:center;background:#16181f;border:1px solid #2a3046}
    </style></head><body><div id="slot"><div id="chart"></div></div></body></html>`,
  }));
  await page.goto('/detached-container.html');
  await page.evaluate(async () => {
    const { createChart, darkTheme } = await import('/dist/openalgo-charts.mjs') as typeof Charts;
    const host = document.getElementById('chart')!;
    const chart = createChart(host, { theme: darkTheme, branding: false, timeNavigator: false, animZoom: false, animAutoscale: false });
    // A seeded walk whose volatility clusters, with an overnight gap each session.
    let seed = 20260927, price = 2412, vol = 1.4, time = 1_758_000_000;
    const rnd = (): number => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0), seed / 4294967296);
    const bars = Array.from({ length: 300 }, (_, i) => {
      vol = Math.max(0.4, Math.min(7, vol * (0.88 + rnd() * 0.26)));
      const open = price, close = open + (rnd() - 0.5) * 2 * vol;
      price = close;
      time += (i + 1) % 75 === 0 ? 17 * 3600 : 300;
      return { time, open, high: Math.max(open, close) + rnd() * vol, low: Math.min(open, close) - rnd() * vol, close };
    });
    chart.addSeries('candlestick').setData(bars);
    // The view the framework swaps in, and the key it swaps on.
    const other = document.createElement('div');
    other.id = 'other';
    other.textContent = 'Order book';
    const slot = document.getElementById('slot')!;
    // The view by what a key moves: a parked container is measured at no size,
    // so its visible range collapses whatever the keys do.
    const state = { chart, range: () => JSON.stringify([chart.timeScale.rightOffset, chart.timeScale.barSpacing]), swaps: 0 };
    document.addEventListener('keydown', e => {
      if (e.code !== 'KeyS') return;
      state.swaps++;
      if (host.isConnected) slot.replaceChild(other, host); else slot.replaceChild(host, other);
    }, true);
    window.__park = state;
  });
  await frames(page);
}

const frames = (page: Page): Promise<void> =>
  page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));

test('a parked chart does not answer hover-scoped keys, and waits for the pointer once it is back', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mount(page);
  const range = (): Promise<string> => page.evaluate(() => window.__park.range());

  await page.mouse.move(400, 260);
  await page.mouse.move(420, 270);
  await frames(page);
  const start = await range();
  await page.keyboard.press('ArrowLeft');
  await frames(page);
  const hovered = await range();
  expect(hovered, 'an arrow over the chart pans it').not.toBe(start);
  await page.screenshot({ path: info.outputPath('1-hovered.png') });

  // Swap the chart out from under the still pointer.
  await page.keyboard.press('KeyS');
  await frames(page);
  expect(await page.evaluate(() => document.getElementById('chart') === null)).toBe(true);
  await page.keyboard.press('ArrowLeft');
  await page.keyboard.press('Equal');
  await frames(page);
  expect(await range(), 'keys typed at the other view leave the parked chart alone').toBe(hovered);
  await page.screenshot({ path: info.outputPath('2-parked.png') });

  // Back in place: the chart waits for the pointer to come in again.
  await page.keyboard.press('KeyS');
  await page.mouse.move(430, 280);
  await page.mouse.move(440, 285);
  await frames(page);
  await page.keyboard.press('ArrowLeft');
  await frames(page);
  expect(await range(), 'the chart answers again once the pointer is over it').not.toBe(hovered);
  await page.screenshot({ path: info.outputPath('3-back.png') });
  expect(errors).toEqual([]);
});
