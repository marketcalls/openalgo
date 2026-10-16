import { expect, test, type Page, type TestInfo } from '@playwright/test';
import type { Bar, Chart, IndicatorApi } from '../../src/index';
import type * as Charts from '../../src/index';

interface SourceEvent { instanceId: string; indicatorId: string; paneIndex: number }
interface Point { x: number; y: number }
interface Bounds { left: number; right: number; top: number; bottom: number }

declare global {
  interface Window {
    __indicatorRegression: {
      chart: Chart;
      bars: Bar[];
      studies: IndicatorApi[];
      source: SourceEvent[];
      settings: SourceEvent[];
    };
  }
}

async function paint(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }));
}

async function fixture(page: Page, mode: 'legend' | 'source' | 'markers'): Promise<void> {
  await page.setViewportSize({ width: 1000, height: 600 });
  await page.route('**/indicator-source-markers-fixture.html', route => route.fulfill({
    contentType: 'text/html',
    body: '<!doctype html><html><head><style>html,body{margin:0;width:100%;height:100%;background:#101010}#chart{width:100%;height:100%}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/indicator-source-markers-fixture.html');
  await page.evaluate(async mode => {
    const bundle = '/dist/openalgo-charts.mjs';
    const { createChart, darkTheme, registerIndicator } = await import(bundle) as typeof Charts;
    const chart = createChart(document.querySelector<HTMLElement>('#chart')!, {
      branding: false,
      theme: { ...darkTheme, background: '#101010', axisText: '#eeeeee', crosshair: 'transparent', crosshairLabelVisible: false },
    });
    const bars = Array.from({ length: 24 }, (_, index) => ({
      time: 1_789_776_000 + index * 60,
      open: index % 2 === 0 ? 96 : 104,
      high: 130,
      low: 70,
      close: index % 2 === 0 ? 104 : 96,
    }));
    chart.addSeries('candlestick').setData(bars);
    chart.setPriceScaleOptions({ marginTop: 0.3, marginBottom: 0.15, minMove: 0.01 });
    chart.setVisibleLogicalRange({ from: -1, to: 25 });
    const studies: IndicatorApi[] = [];
    const source: SourceEvent[] = [];
    const settings: SourceEvent[] = [];
    chart.on('indicatorSource', event => source.push(event as SourceEvent));
    chart.on('indicatorSettings', event => settings.push(event as SourceEvent));
    window.__indicatorRegression = { chart, bars, studies, source, settings };

    if (mode === 'legend') {
      for (const [index, color] of ['transparent', 'rgba(0,0,0,0)', '#0000', '#00000000', undefined].entries()) {
        const id = `invisible-reading-${index}`;
        registerIndicator({
          id, name: 'Readout', placement: 'onchart', inputs: [],
          plots: [
            ...(color === undefined ? [] : [{ key: 'mid', type: 'line' as const, title: 'Mid', style: { color } }]),
            { key: 'visible', type: 'line', title: 'Visible', style: { color: '#00ff80' } },
          ],
          calc: bars => ({ mid: bars.map(() => 100), visible: bars.map(() => 110) }),
        });
        studies.push(chart.addIndicator(id));
      }
    } else if (mode === 'source') {
      for (const hasSource of [true, false]) {
        registerIndicator({
          id: hasSource ? 'source-study' : 'plain-study', name: 'Readout', placement: 'onchart', inputs: [], hasSource,
          plots: [{ key: 'value', type: 'line', title: 'Value', style: { color: '#00ff80' } }],
          calc: bars => ({ value: bars.map(() => 110) }),
        });
      }
      studies.push(chart.addIndicator('source-study'), chart.addIndicator('source-study'), chart.addIndicator('plain-study'));
    } else {
      registerIndicator({
        id: 'price-markers', name: 'Price signals', placement: 'onchart', inputs: [], markerAnchor: 'price',
        plots: [
          { key: 'mid', type: 'line', title: 'Mid', style: { color: 'rgba(0,0,0,0)' } },
          { key: 'trend', type: 'line', title: 'Trend', style: { color: '#5378b0' } },
        ],
        calc: bars => ({
          mid: bars.map((bar, index) => index === 9 ? null : (bar.open + bar.close) / 2),
          trend: bars.map((bar, index) => index % 2 === 0 ? bar.close : null),
        }),
        markers: ({ bars }) => [4, 9].flatMap(index => [
          { time: bars[index].time, position: 'belowBar', shape: 'labelUp', size: 'medium', color: '#ff00ff', text: 'BUY' },
          { time: bars[index].time, position: 'aboveBar', shape: 'labelDown', size: 'medium', color: '#00ffff', text: 'SELL' },
        ]),
      });
      registerIndicator({
        id: 'gap-markers', name: 'Gap signals', placement: 'onchart', inputs: [],
        plots: [{ key: 'trend', type: 'line', title: 'Trend', style: { color: '#5378b0' } }],
        calc: bars => ({ trend: bars.map((bar, index) => index < 12 ? bar.close : null) }),
        markers: ({ bars }) => [
          { time: bars[14].time, position: 'belowBar', shape: 'labelUp', size: 'medium', color: '#ff8000', text: 'GAP BUY' },
          { time: bars[18].time, position: 'aboveBar', shape: 'labelDown', size: 'medium', color: '#ffff00', text: 'GAP SELL' },
        ],
      });
      studies.push(chart.addIndicator('price-markers'), chart.addIndicator('gap-markers'));
    }
  }, mode);
  await paint(page);
}

async function ink(page: Page, box: Bounds, color: 'gray' | 'green' | 'magenta' | 'cyan' | 'orange' | 'yellow'): Promise<Point[]> {
  return page.evaluate(({ box, color }) => {
    const canvas = window.__indicatorRegression.chart.takeScreenshot();
    const ratio = canvas.width / document.querySelector('#chart')!.getBoundingClientRect().width;
    const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    const points: Point[] = [];
    for (let y = Math.ceil(box.top * ratio); y < box.bottom * ratio; y++) {
      for (let x = Math.ceil(box.left * ratio); x < box.right * ratio; x++) {
        const offset = (y * canvas.width + x) * 4;
        const r = data[offset], g = data[offset + 1], b = data[offset + 2];
        const match = color === 'gray' ? r > 100 && Math.abs(r - g) < 3 && Math.abs(r - b) < 3
          : color === 'green' ? r < 60 && g > 90 && g > b && b > 40 && b < 180
          : color === 'magenta' ? r > 180 && g < 40 && b > 180
          : color === 'cyan' ? r < 40 && g > 180 && b > 180
          : color === 'orange' ? r > 180 && g > 70 && g < 170 && b < 40
          : r > 180 && g > 180 && b < 40;
        if (match) points.push({ x: x / ratio, y: y / ratio });
      }
    }
    return points;
  }, { box, color });
}

function bounds(points: Point[]): Bounds {
  expect(points.length, 'Expected visible canvas pixels').toBeGreaterThan(0);
  return {
    left: Math.min(...points.map(point => point.x)), right: Math.max(...points.map(point => point.x)),
    top: Math.min(...points.map(point => point.y)), bottom: Math.max(...points.map(point => point.y)),
  };
}

function groups(points: Point[]): Bounds[] {
  const columns = [...new Set(points.map(point => Math.floor(point.x)))].sort((a, b) => a - b);
  const ranges: { left: number; right: number }[] = [];
  for (const x of columns) {
    const last = ranges[ranges.length - 1];
    if (!last || x > last.right + 1) ranges.push({ left: x, right: x });
    else last.right = x;
  }
  return ranges.map(range => bounds(points.filter(point => point.x >= range.left && point.x < range.right + 1)));
}

async function screenshot(page: Page, info: TestInfo, name: string): Promise<void> {
  const path = info.outputPath(`${name}.png`);
  await page.screenshot({ path, animations: 'disabled' });
  await info.attach(name, { path, contentType: 'image/png' });
}

test.afterEach(async ({ page }, info) => {
  if (info.status !== info.expectedStatus) await screenshot(page, info, 'failure');
});

test('transparent plots leave no blank value in the legend', async ({ page }, info) => {
  await fixture(page, 'legend');
  const rows: Bounds[] = [];
  for (let row = 0; row < 5; row++) {
    // Row 0 is the persistent Indicators N control, so study rows start one row down.
    rows.push(bounds(await ink(page, { left: 60, right: 200, top: 6 + (row + 1) * 18, bottom: 24 + (row + 1) * 18 }, 'green')));
  }
  for (const row of rows.slice(0, 4)) expect(row.left).toBe(rows[4].left);
  await screenshot(page, info, 'transparent-legend');
});

test('source braces, enlarged hitboxes and stacked rows identify the clicked instance', async ({ page }, info) => {
  await fixture(page, 'source');
  const ids = await page.evaluate(() => window.__indicatorRegression.studies.map(study => study.id));
  const extents: number[] = [];
  for (const size of [16, 24]) {
    await page.evaluate(size => window.__indicatorRegression.chart.setLegendIconSize(size), size);
    const pitch = size === 16 ? 18 : 26;
    for (let row = 0; row < 2; row++) {
      // The persistent Indicators N control holds the first row at every icon size.
      const cy = 6 + (row + 1) * pitch + pitch / 2;
      await page.mouse.move(30, cy);
      await paint(page);
      const value = bounds(await ink(page, { left: 60, right: 150, top: cy - 7, bottom: cy + 7 }, 'green'));
      const pixels = await ink(page, { left: value.right + 3, right: 300, top: cy - size / 2, bottom: cy + size / 2 + 1 }, 'gray');
      const glyphs = groups(pixels);
      expect(glyphs, 'Eye, gear, two braces, and remove must all paint').toHaveLength(5);
      const source = bounds(pixels.filter(point => point.x >= glyphs[2].left && point.x <= glyphs[3].right));
      const cx = (source.left + source.right) / 2;
      const middle = pixels.filter(point => Math.abs(point.y - cy) <= 1.5 && point.x >= source.left && point.x <= source.right);
      const hooks = pixels.filter(point => Math.abs(point.y - cy) >= size * 0.27 && point.x >= source.left && point.x <= source.right);
      expect(bounds(middle).left, 'Opening brace waist points outward').toBeLessThan(bounds(hooks).left);
      expect(bounds(middle).right, 'Closing brace waist points outward').toBeGreaterThan(bounds(hooks).right);
      if (row === 0) extents.push(source.bottom - source.top);
      const before = await page.evaluate(() => window.__indicatorRegression.source.length);
      // A larger target must be clickable beyond the default button's edge.
      await page.mouse.move(cx + size / 2 - 1, cy + size / 2 - 1);
      await page.mouse.down();
      // A held press must remain clickable after hover controls repaint.
      await paint(page);
      await page.mouse.up();
      await expect.poll(() => page.evaluate(() => window.__indicatorRegression.source.length)).toBe(before + 1);
      expect(await page.evaluate(() => window.__indicatorRegression.source.at(-1))).toEqual({
        instanceId: ids[row], indicatorId: 'source-study', paneIndex: 0,
      });
      if (size === 24 && row === 1) await screenshot(page, info, 'source-enlarged-second-row');
    }
    const plainY = 6 + 3 * pitch + pitch / 2;
    await page.mouse.move(30, plainY);
    await paint(page);
    const value = bounds(await ink(page, { left: 60, right: 150, top: plainY - 7, bottom: plainY + 7 }, 'green'));
    const plain = groups(await ink(page, { left: value.right + 3, right: 300, top: plainY - size / 2, bottom: plainY + size / 2 + 1 }, 'gray'));
    expect(plain, 'A descriptor without source has only eye, gear, and remove').toHaveLength(3);
  }
  expect(extents[0]).toBeGreaterThan(9.24);
  expect(extents[1]).toBeGreaterThan(extents[0] * 1.3);
  expect(await page.evaluate(() => window.__indicatorRegression.settings)).toEqual([]);
  expect(await page.evaluate(() => window.__indicatorRegression.chart.indicators().length)).toBe(3);
});

test('price markers clear candle extremes with an invisible mid-body plot and gaps', async ({ page }, info) => {
  await fixture(page, 'markers');
  const positions = await page.evaluate(() => {
    const { chart, bars } = window.__indicatorRegression;
    return [4, 9].map(index => ({
      x: chart.timeToCoordinate(bars[index].time),
      high: chart.priceToCoordinate(bars[index].high)!, low: chart.priceToCoordinate(bars[index].low)!,
    }));
  });
  for (const point of positions) {
    const box = { left: point.x - 30, right: point.x + 30, top: 130, bottom: 570 };
    expect(bounds(await ink(page, box, 'magenta')).top).toBeGreaterThan(point.low);
    expect(bounds(await ink(page, box, 'cyan')).bottom).toBeLessThan(point.high);
  }
  await screenshot(page, info, 'price-markers');
});

test('a default plot anchor falls back to candles at null plot gaps', async ({ page }, info) => {
  await fixture(page, 'markers');
  const [buy, sell] = await page.evaluate(() => {
    const { chart, bars } = window.__indicatorRegression;
    return [14, 18].map(index => ({
      x: chart.timeToCoordinate(bars[index].time),
      high: chart.priceToCoordinate(bars[index].high)!, low: chart.priceToCoordinate(bars[index].low)!,
    }));
  });
  expect(bounds(await ink(page, { left: buy.x - 40, right: buy.x + 40, top: 130, bottom: 570 }, 'orange')).top).toBeGreaterThan(buy.low);
  expect(bounds(await ink(page, { left: sell.x - 40, right: sell.x + 40, top: 130, bottom: 570 }, 'yellow')).bottom).toBeLessThan(sell.high);
  await screenshot(page, info, 'gap-markers');
});
