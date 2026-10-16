import { expect, test, type Page } from '@playwright/test';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __curvedStudy: {
      chart: Charts.Chart;
      study: Charts.IndicatorApi;
      source: Charts.SeriesApi;
      points: Charts.DrawAnchor[];
      midpoint: () => [number, number];
      ink: (point?: [number, number]) => { plot: number; outside: number };
    };
  }
}

const painted = (page: Page) => page.evaluate(() => new Promise<void>(resolve =>
  requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));

for (const width of [900, 390]) {
  test(`curved study paths render, clip and follow their owner at ${width}px`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width, height: 520 });
    await page.route('**/curved-study.html', route => route.fulfill({ contentType: 'text/html',
      body: '<!doctype html><style>html,body{margin:0;height:100%;background:#101010}#chart{height:100%}</style><div id="chart"></div>',
    }));
    await page.goto('/curved-study.html');
    await page.evaluate(async pixelRatio => {
      const url = '/dist/openalgo-charts.mjs';
      const lib = await import(url) as typeof Charts;
      const chart = lib.createChart(document.getElementById('chart')!, {
        branding: false, timeNavigator: false, theme: lib.darkTheme,
        animAutoscale: false, animZoom: false, pixelRatio: () => pixelRatio,
      });
      const source = chart.addSeries('candlestick');
      const bars = Array.from({ length: 24 }, (_, i) => ({ time: 1700000000 + i * 60, open: 48, high: 90, low: 20, close: 52 }));
      source.setData(bars);
      const points = [2, 8, 14, 20].map((index, i) => ({ time: bars[index].time, price: [30, 80, 25, 70][i] }));
      lib.registerIndicator({
        id: 'curved-study-fixture', name: 'Curved study', placement: 'onchart',
        inputs: [
          { key: 'smooth', label: 'Smooth', type: 'boolean', default: true },
          { key: 'closed', label: 'Closed', type: 'boolean', default: false },
          { key: 'edges', label: 'Edges', type: 'boolean', default: false },
        ],
        plots: [{ key: 'carrier', type: 'line', title: 'Curve' }],
        calc: rows => ({ carrier: rows.map(() => null) }),
        draws: ({ settings }) => [{
          kind: 'polyline',
          points: settings.edges ? [-20, 8, 14, 60].map((index, i) => ({ time: bars[0].time + index * 60, price: [50, 130, -20, 50][i] })) : points,
          curve: settings.smooth ? 'smooth' : 'linear', color: '#ff00ff', lineWidth: 3,
          closed: !!settings.closed, fillColor: settings.closed ? '#ff00ff' : undefined, opacity: 0.15,
        }],
      });
      const study = chart.addIndicator('curved-study-fixture');
      chart.setVisibleLogicalRange({ from: 0, to: 24 });
      window.__curvedStudy = {
        chart, study, source, points,
        midpoint: () => {
          const xy = points.map(point => [chart.timeScale.indexToX(chart.dataLayer.timeToIndexFloat(point.time)), source.priceScale().priceToY(point.price)]);
          return [0, 1].map(axis => (8 * xy[0][axis] + 9 * xy[1][axis] - xy[2][axis]) / 16) as [number, number];
        },
        ink: point => {
          const canvas = chart.panes()[0].base.element;
          const ctx = chart.panes()[0].base.ctx;
          const data = ctx.getImageData(0, 0, canvas.width, canvas.height).data;
          const plotWidth = chart.timeScale.width, plotHeight = source.priceScale().height;
          let plot = 0, outside = 0;
          for (let y = 0; y < canvas.height; y++) for (let x = 0; x < canvas.width; x++) {
            if (point && (Math.abs(x / pixelRatio - point[0]) > 3 || Math.abs(y / pixelRatio - point[1]) > 3)) continue;
            const i = (y * canvas.width + x) * 4;
            if (data[i] > 220 && data[i + 1] < 25 && data[i + 2] > 220) {
              if (x / pixelRatio >= plotWidth || y / pixelRatio >= plotHeight) outside++;
              else plot++;
            }
          }
          return { plot, outside };
        },
      };
    }, width === 390 ? 2 : 1);
    await painted(page);
    const curved = await page.evaluate(() => window.__curvedStudy.ink(window.__curvedStudy.midpoint()));
    expect(curved.plot).toBeGreaterThan(0);
    await page.screenshot({ path: info.outputPath('smooth.png') });
    await page.evaluate(() => window.__curvedStudy.study.setSettings({ smooth: false }));
    await painted(page);
    expect((await page.evaluate(() => window.__curvedStudy.ink(window.__curvedStudy.midpoint()))).plot).toBe(0);
    await page.evaluate(() => {
      window.__curvedStudy.study.setSettings({ smooth: true, closed: true });
      window.__curvedStudy.chart.setPriceScaleOptions({ mode: 'logarithmic', inverted: true });
    });
    await painted(page);
    expect((await page.evaluate(() => window.__curvedStudy.ink())).plot).toBeGreaterThan(30);
    await page.screenshot({ path: info.outputPath('closed-log-inverted.png') });
    const exported = await page.evaluate(() => {
      const chart = window.__curvedStudy.chart;
      const xml = new DOMParser().parseFromString(chart.exportSVG(), 'image/svg+xml');
      const path = Array.from(xml.querySelectorAll('path')).find(element => element.getAttribute('stroke') === '#ff00ff');
      const clipGroup = path?.closest('[clip-path]');
      const clipId = clipGroup?.getAttribute('clip-path')?.slice(5, -1);
      const clipPath = clipId ? xml.getElementById(clipId)?.querySelector('path')?.getAttribute('d') : null;
      const w = Math.round(chart.timeScale.width * 100) / 100;
      const h = Math.round(window.__curvedStudy.source.priceScale().height * 100) / 100;
      return { path: path?.getAttribute('d'), clipPath, expectedClip: `M0 0h${w}v${h}h${-w}Z`, parseErrors: xml.querySelectorAll('parsererror').length };
    });
    expect(exported.path).toContain('C');
    expect(exported.path).toContain('Z');
    expect(exported.clipPath).toBe(exported.expectedClip);
    expect(exported.parseErrors).toBe(0);
    await page.evaluate(() => {
      window.__curvedStudy.chart.setPriceScaleOptions({ mode: 'linear', inverted: false });
      window.__curvedStudy.study.setSettings({ closed: false, edges: true });
    });
    await painted(page);
    const edges = await page.evaluate(() => window.__curvedStudy.ink());
    expect(edges.plot).toBeGreaterThan(30);
    expect(edges.outside).toBe(0);
    await page.screenshot({ path: info.outputPath('clipped-edges.png') });
    await page.evaluate(() => window.__curvedStudy.study.setVisible(false));
    await painted(page);
    expect((await page.evaluate(() => window.__curvedStudy.ink())).plot).toBe(0);
    await page.evaluate(() => window.__curvedStudy.study.setVisible(true));
    await painted(page);
    expect((await page.evaluate(() => window.__curvedStudy.ink())).plot).toBeGreaterThan(30);
    await page.evaluate(() => window.__curvedStudy.study.remove());
    await painted(page);
    expect((await page.evaluate(() => window.__curvedStudy.ink())).plot).toBe(0);
    expect(errors).toEqual([]);
  });
}
