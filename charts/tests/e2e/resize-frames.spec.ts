import { writeFileSync } from 'node:fs';
import { expect, test, type Page } from '@playwright/test';
import type { Chart } from '../../src/index';
import type * as Charts from '../../src/index';

/**
 * No blank frame while the chart is resized.
 *
 * Resizing a canvas clears it, and the chart hears of a new size from a
 * ResizeObserver, whose callbacks run after the frame's animation callbacks
 * and before the browser paints. A repaint left to the next animation frame
 * therefore puts one cleared frame on screen for every step of a drag.
 *
 * Each step here resizes the container inside an animation callback and, in
 * the same callback, asks for a callback in the next frame. That one is asked
 * for before the chart can ask for its own, so it runs first in the next
 * frame and sees the canvases exactly as the browser painted them in this
 * one. Every pane of every captured frame must be painted, the price pane
 * with its candles, at the size the step set.
 */

declare global {
  interface Window { __rf: { chart: Chart } }
}

const STEPS: readonly [number, number][] = [
  [640, 380], [700, 400], [580, 340], [720, 420], [500, 300],
  [760, 440], [610, 370], [540, 330], [680, 390], [600, 360],
];

async function mount(page: Page): Promise<void> {
  await page.setViewportSize({ width: 900, height: 600 });
  await page.route('**/resize-frames.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#c{position:absolute;left:10px;top:10px;width:600px;height:360px}</style></head><body><div id="c"></div></body></html>',
  }));
  await page.goto('/resize-frames.html');
  await page.evaluate(async () => {
    const { createChart, darkTheme } = await import('/dist/openalgo-charts.mjs') as typeof Charts;
    const chart = createChart(document.getElementById('c')!, {
      theme: darkTheme, branding: false, timeNavigator: false, animZoom: false, animAutoscale: false,
    });
    const bars = Array.from({ length: 150 }, (_, i) => {
      const close = 100 + Math.sin(i / 6) * 8;
      return { time: 1_700_000_000 + i * 300, open: close - 1, high: close + 2, low: close - 2, close, volume: 100 + i };
    });
    chart.addSeries('candlestick').setData(bars);
    chart.addSeries('line', { paneIndex: 1 }).setData(bars.map(b => ({ time: b.time, value: b.close })));
    window.__rf = { chart };
  });
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

test('keeps every frame painted while the container is resized', async ({ page }, testInfo) => {
  await mount(page);
  const result = await page.evaluate(async (steps) => {
    const { chart } = window.__rf;
    const el = document.getElementById('c')!;
    const theme = chart.theme();
    const hex = (h: string) => [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16));
    const [up, down] = [hex(theme.upColor), hex(theme.downColor)];
    const near = (d: Uint8ClampedArray, i: number, rgb: number[]) => Math.abs(d[i] - rgb[0]) < 24 && Math.abs(d[i + 1] - rgb[1]) < 24 && Math.abs(d[i + 2] - rgb[2]) < 24;
    const dpr = devicePixelRatio;
    // A filmstrip of every captured frame, for looking at as well as asserting on.
    const film = document.createElement('canvas');
    const thumb = { w: 190, h: 115 };
    film.width = thumb.w * 5;
    film.height = thumb.h * Math.ceil(steps.length / 5);
    const filmCtx = film.getContext('2d')!;
    filmCtx.fillStyle = '#ff00ff';
    filmCtx.fillRect(0, 0, film.width, film.height);
    const frames: { size: [number, number]; panes: { width: number; opaque: number; candles: number }[] }[] = [];
    let n = 0;
    for (const [w, h] of steps) {
      await new Promise<void>(resolve => {
        requestAnimationFrame(() => {
          requestAnimationFrame(() => {
            const panes = chart.panes().map((pane, i) => {
              const canvas = pane.base.element;
              const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
              let opaque = 0, candles = 0;
              for (let p = 0; p < data.length; p += 4) {
                if (data[p + 3] === 255) opaque++;
                if (i === 0 && data[p + 3] > 0 && (near(data, p, up) || near(data, p, down))) candles++;
              }
              return { width: canvas.width, opaque: opaque / (canvas.width * canvas.height), candles };
            });
            // Stack the panes' base canvases into one thumbnail, as the page shows them.
            let y = 0;
            const col = n % 5, row = Math.floor(n / 5);
            const scale = Math.min(thumb.w / (w * dpr), thumb.h / (h * dpr));
            for (const pane of chart.panes()) {
              const c = pane.base.element;
              filmCtx.drawImage(c, col * thumb.w, row * thumb.h + y * scale, c.width * scale, c.height * scale);
              y += c.height;
            }
            n++;
            frames.push({ size: [w, h], panes });
            resolve();
          });
          el.style.width = `${w}px`;
          el.style.height = `${h}px`;
        });
      });
    }
    return { frames, film: film.toDataURL('image/png'), dpr };
  }, STEPS);
  const filmstrip = testInfo.outputPath('resize-filmstrip.png');
  writeFileSync(filmstrip, Buffer.from(result.film.split(',')[1], 'base64'));
  await testInfo.attach('resize-filmstrip', { path: filmstrip, contentType: 'image/png' });
  expect(result.frames).toHaveLength(STEPS.length);
  for (const [i, frame] of result.frames.entries()) {
    const [w] = frame.size;
    for (const [p, pane] of frame.panes.entries()) {
      // The step's size reached the canvas in the frame it was set in, so the frame is a real test.
      expect(pane.width, `frame ${i} pane ${p} width`).toBe(Math.round(w * result.dpr));
      // And the frame shows it painted: a cleared canvas is fully transparent.
      expect(pane.opaque, `frame ${i} pane ${p} painted share`).toBeGreaterThan(0.9);
    }
    expect(frame.panes[0].candles, `frame ${i} candles`).toBeGreaterThan(50);
  }
});
