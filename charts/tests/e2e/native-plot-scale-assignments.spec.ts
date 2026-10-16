import { test, expect, type Page } from '@playwright/test';
import type { Chart, IndicatorApi, ChartState } from '../../src/index';
import type * as Charts from '../../src/index';

declare global {
  interface Window {
    __plotScales: { chart: Chart; study: IndicatorApi; saved?: ChartState; calculations: number; changes: number };
    __plotExample: Chart;
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function pixels(page: Page) {
  return page.evaluate(() => {
    const { chart, study } = window.__plotScales;
    const left = Math.max(...chart.panes().map((_, index) => chart.priceAxisLayout(index)
      .filter(slot => slot.side === 'left').reduce((sum, slot) => sum + slot.width, 0)));
    const x = left + chart.timeScale.indexToX(15);
    const local = chart.panes()[study.paneIndex];
    const fillY = study.series('upper')!.priceScale().priceToY(40);
    const overlayY = study.series('price')!.priceScale().priceToY(300);
    const overlayPixels = chart.panes()[0].base.ctx.getImageData(Math.round(x) - 3, Math.round(overlayY) - 3, 7, 7).data;
    let overlayInk = 0;
    for (let i = 0; i < overlayPixels.length; i += 4) {
      if (overlayPixels[i] === 255 && overlayPixels[i + 1] === 153 && overlayPixels[i + 2] === 0) overlayInk++;
    }
    return { fill: Array.from(local.base.ctx.getImageData(Math.round(x), Math.round(fillY), 1, 1).data),
      overlayInk, bindings: study.plotPriceScaleIds(), effective: ['upper', 'lower', 'units', 'price'].map(key => study.plotPriceScaleId(key)),
      panes: chart.panes().length, calculations: window.__plotScales.calculations, changes: window.__plotScales.changes };
  });
}

for (const width of [900, 390]) test(`per-plot transactions retain fill and overlay pixels at ${width}px`, async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width, height: 640 });
  await page.route('**/plot-scales.html', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><head><style>html,body{margin:0;background:#101010}#chart{width:${width}px;height:630px}</style></head><body><div id="chart"></div></body></html>` }));
  await page.goto('/plot-scales.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    let calculations = 0;
    lib.registerIndicator({ id: 'browser-plot-scales', name: 'Separate plot units', placement: 'pane', inputs: [],
      plots: [{ key: 'upper', title: 'Upper', type: 'line', style: { color: '#22dddd' } },
        { key: 'lower', title: 'Lower', type: 'line', style: { color: '#22dddd' } },
        { key: 'units', title: 'Units', type: 'line', priceScaleId: 'left', style: { color: '#66ff44' } },
        { key: 'price', title: 'Price', type: 'line', overlay: true, style: { color: '#ff9900', lineWidth: 4 } }],
      fills: [{ between: ['upper', 'lower'], colorUp: '#552288', colorDown: '#552288', opacity: 1 }],
      calc: bars => { calculations++; if (window.__plotScales) window.__plotScales.calculations = calculations;
        return { upper: bars.map(() => 75), lower: bars.map(() => 25), units: bars.map(() => 2000), price: bars.map(() => 300) }; },
    });
    const chart = lib.createChart(document.getElementById('chart')!, { branding: false, theme: lib.darkTheme,
      animZoom: false, animAutoscale: false, pixelRatio: () => 1, timeNavigator: false });
    chart.addSeries('candlestick').setData(Array.from({ length: 32 }, (_, index) => ({
      time: 1700000000 + index * 60, open: 100, high: 112, low: 95, close: 107,
    })));
    const study = chart.addIndicator('browser-plot-scales');
    window.__plotScales = { chart, study, calculations, changes: 0 };
    chart.on('objects:change', () => { window.__plotScales.changes++; });
    for (const [paneIndex, scaleId, min, max] of [[0, 'right', 0, 400], [1, 'right', 0, 100], [1, 'left', 0, 4000]] as const) {
      const scale = chart.panes()[paneIndex].scaleFor(scaleId);
      scale.setFixedRange({ min, max }); scale.setOptions({ marginTop: 0, marginBottom: 0 });
    }
    chart.setVisibleLogicalRange({ from: 0, to: 31 });
    chart.resetScale();
    chart.panes()[0].scaleFor('right').setFixedRange({ min: 0, max: 400 });
    chart.panes()[1].scaleFor('right').setFixedRange({ min: 0, max: 100 });
    chart.panes()[1].scaleFor('left').setFixedRange({ min: 0, max: 4000 });
    chart.setVisibleLogicalRange({ from: 0, to: 31 });
  });
  await paint(page);
  const before = await pixels(page);
  expect(before.fill).toEqual([85, 34, 136, 255]);
  expect(before.overlayInk).toBeGreaterThan(8);
  expect(before.effective).toEqual(['right', 'right', 'left', 'right']);
  expect(await page.evaluate(() => window.__plotScales.study.setPlotPriceScales({ upper: 'left' }))).toBe(false);
  expect((await pixels(page)).changes).toBe(before.changes);
  const assignmentChanges = await page.evaluate(() => {
    const { chart, study } = window.__plotScales;
    const beforeChanges = window.__plotScales.changes;
    if (!study.setPlotPriceScales({ upper: 'overlay:band', lower: 'overlay:band', units: 'right', price: 'left' })) throw new Error('Plot move rejected');
    const assignmentChanges = window.__plotScales.changes - beforeChanges;
    chart.setPriceAxisPlacement(1, 'overlay:band', 'left');
    for (const [paneIndex, scaleId, min, max] of [[0, 'left', 0, 400], [1, 'overlay:band', 0, 100], [1, 'right', 0, 4000]] as const) {
      const scale = chart.panes()[paneIndex].scaleFor(scaleId);
      scale.setFixedRange({ min, max }); scale.setOptions({ marginTop: 0, marginBottom: 0 });
    }
    chart.setVisibleLogicalRange({ from: 0, to: 31 });
    study.updateLegendValues();
    return assignmentChanges;
  });
  expect(assignmentChanges).toBe(1);
  await paint(page);
  const moved = await pixels(page);
  expect(moved).toMatchObject({ fill: before.fill, calculations: before.calculations,
    changes: before.changes + 2, effective: ['overlay:band', 'overlay:band', 'right', 'left'] });
  expect(moved.overlayInk).toBeGreaterThan(8);
  const screenshot = await page.locator('#chart').screenshot({ path: info.outputPath('plots-independent.png') });
  await page.evaluate(() => {
    const state = window.__plotScales;
    state.saved = state.chart.getState();
    state.study.setPriceScale('left');
    if (!state.chart.restoreState(JSON.parse(JSON.stringify(state.saved))).applied) throw new Error('Restore rejected');
    state.study = state.chart.indicators()[0];
  });
  await paint(page);
  const restored = await pixels(page);
  expect(restored.bindings).toEqual(moved.bindings);
  expect(restored.effective).toEqual(moved.effective);
  expect(restored.fill).toEqual(before.fill);
  expect(restored.overlayInk).toBeGreaterThan(8);
  const restoredScreenshot = await page.locator('#chart').screenshot({ path: info.outputPath('plots-restored.png') });
  expect(restoredScreenshot.equals(screenshot), 'restoration preserves rendered pixels').toBe(true);
  expect(errors).toEqual([]);
});

for (const width of [900, 390]) test(`the documented plot assignment controls preserve values at ${width}px`, async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.request.get('/website/pages/examples.mdx');
  expect(response.ok()).toBe(true);
  let source = (await response.text()).split('## Assign scales to individual study plots')[1].split('code={`')[1].split('`} />')[0];
  // The site's template splices the shared bar generator in; do the same here.
  const market = await (await page.request.get('/website/components/synthetic-market.ts')).text();
  source = source.replace('${STOCK_BARS_SOURCE}', market.split('STOCK_BARS_SOURCE = `')[1].split('`;')[0]);
  await page.setViewportSize({ width, height: 600 });
  await page.route('**/plot-example.html', route => route.fulfill({ contentType: 'text/html', body:
    `<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:${width}px;height:600px}</style></head><body><div id="example"></div></body></html>` }));
  await page.goto('/plot-example.html');
  await page.evaluate(async code => {
    const bundle = '/dist/openalgo-charts.mjs';
    const lib = await import(bundle) as typeof Charts;
    window.__plotExample = new Function('el', 'lib', code)(document.getElementById('example'), lib) as Chart;
  }, source);
  const snapshot = () => page.evaluate(() => {
    const chart = window.__plotExample, study = chart.indicators()[0];
    return { overrides: study.plotPriceScaleIds(), whole: study.priceScaleId(),
      effective: ['signal', 'upper', 'lower', 'price'].map(key => study.plotPriceScaleId(key)),
      formatted: [study.series('signal')!.priceScale().format(0.35), study.series('upper')!.priceScale().format(67),
        study.series('price')!.priceScale().format(115.75)],
      values: study.values(), bars: chart.primarySeries()!.getData() };
  });
  const before = await snapshot();
  expect(before.effective).toEqual(['right', 'overlay:band', 'overlay:band', 'right']);
  let saved = before;
  for (const [label, effective, whole] of [
    ['Signal left', ['left', 'overlay:band', 'overlay:band', 'right'], null],
    ['Move band pair', ['left', 'overlay:band-right', 'overlay:band-right', 'right'], null],
    ['Reject split band', ['left', 'overlay:band-right', 'overlay:band-right', 'right'], null],
    ['Price overlay left', ['left', 'overlay:band-right', 'overlay:band-right', 'left'], null],
    ['Save layout', ['left', 'overlay:band-right', 'overlay:band-right', 'left'], null],
    ['Clear signal override', ['right', 'overlay:band-right', 'overlay:band-right', 'left'], null],
    ['Whole study left', ['left', 'left', 'left', 'left'], 'left'],
    ['Descriptor defaults', ['right', 'overlay:band', 'overlay:band', 'left'], null],
    ['Restore layout', ['left', 'overlay:band-right', 'overlay:band-right', 'left'], null],
  ] as const) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await paint(page);
    const state = await snapshot();
    expect(state.effective).toEqual(effective);
    expect(state.whole).toBe(whole);
    expect(state.formatted).toEqual([whole === 'left' ? '0%' : '0.35', '67%', '115.75']);
    expect(state.values).toEqual(before.values);
    expect(state.bars).toEqual(before.bars);
    await expect(page.getByRole('status')).toContainText('Last: 0.45 / 62.27 / 42.27 / 99.70');
    if (label === 'Reject split band') await expect(page.getByRole('status')).toContainText('Reject split band: false');
    if (label === 'Save layout') saved = state;
    if (label === 'Restore layout') expect(state.overrides).toEqual(saved.overrides);
    if (label === 'Save layout' || label === 'Restore layout') {
      await page.locator('#example').screenshot({ path: info.outputPath(`example-${label.toLowerCase().replace(' ', '-')}.png`) });
    }
  }
  expect(errors).toEqual([]);
});
