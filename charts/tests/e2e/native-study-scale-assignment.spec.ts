import { test, expect, type Page } from '@playwright/test';
import type { Chart, IPrimitive, SeriesApi, PriceScale, ChartState } from '../../src/index';
import type { IndicatorInstance } from '../../src/model/indicator-instance';
import type * as Charts from '../../src/index';

type Pill = { x: number; y: number; width: number; height: number };
declare global {
  interface Window {
    __studyExample: { chart: Chart; study: IndicatorInstance; upper: SeriesApi };
    __studyScale: {
      chart: Chart; study: IndicatorInstance; source: SeriesApi; series: SeriesApi[];
      primitives: IPrimitive[]; bound: IPrimitive[]; values: ReturnType<IndicatorInstance['values']>;
      overlayScale: PriceScale; data: string; counts: { calc: number; attach: number }; baseline: { calc: number; attach: number };
      objects: number; saved?: ChartState; pills: Pill[]; texts: string[];
    };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function inspect(page: Page) {
  return page.evaluate(() => {
    const state = window.__studyScale, { chart, study } = state;
    const pane = chart.panes()[study.paneIndex], scale = study.series('upper')!.priceScale();
    const resources = study.renderResources(), canvas = pane.base.element, context = canvas.getContext('2d')!;
    const ratio = canvas.width / 900, left = chart.panes().some(item => item.hasLeftScale()) ? 56 : 0;
    const point = (index: number, price: number) => ({ x: left + chart.timeScale.indexToX(index), y: scale.priceToY(price) });
    const pixel = (index: number, price: number) => {
      const at = point(index, price);
      return Array.from(context.getImageData(Math.round(at.x * ratio), Math.round(at.y * ratio), 1, 1).data);
    };
    const markerAt = point(12, 75), markerPixels = context.getImageData(Math.round((markerAt.x - 10) * ratio),
      Math.round((markerAt.y - 10) * ratio), Math.round(20 * ratio), Math.round(20 * ratio)).data;
    let markerInk = 0;
    for (let i = 0; i < markerPixels.length; i += 4) if (markerPixels[i] === 255 && markerPixels[i + 1] === 51 && markerPixels[i + 2] === 204) markerInk++;
    const overlay = study.series('price')!, pricePane = chart.panes()[0], overlayY = overlay.priceScale().priceToY(150);
    const overlayPixels = pricePane.base.ctx.getImageData(Math.round((left + chart.timeScale.indexToX(15) - 2) * ratio),
      Math.round((overlayY - 2) * ratio), Math.round(5 * ratio), Math.round(5 * ratio)).data;
    let overlayInk = 0;
    for (let i = 0; i < overlayPixels.length; i += 4) if (overlayPixels[i] === 204 && overlayPixels[i + 1] === 136 && overlayPixels[i + 2] === 68) overlayInk++;
    return {
      id: study.priceScaleId(), width: chart.timeScale.width, range: scale.priceRange(), auto: scale.autoScale,
      sameSeries: state.series.every((api, index) => resources.series[index]?.api === api),
      samePrimitives: resources.primitives.length === state.primitives.length && state.primitives.every(item => resources.primitives.some(entry => entry.primitive === item)),
      sameValues: study.values() === state.values,
      sameData: JSON.stringify(resources.series.map(item => item.api.getData())) === state.data,
      sameSource: chart.primarySeries() === state.source,
      sameOverlayScale: overlay.priceScale() === state.overlayScale,
      localScales: [study.series('upper'), study.series('lower')].every(api => api?.priceScale() === scale),
      boundIds: state.bound.map(primitive => pane.primitiveScaleId(primitive)),
      gradient: pixel(16.3, 50), box: pixel(7, 5), markerInk, overlayInk,
      pills: state.pills, texts: state.texts, counts: state.counts, baseline: state.baseline, objects: state.objects,
      leftRange: pane.scaleFor('left').priceRange(), hiddenRange: pane.scaleFor('overlay:study').priceRange(),
    };
  });
}

function expectVisuals(result: Awaited<ReturnType<typeof inspect>>, id: string | null) {
  expect(result.id).toBe(id);
  expect(result).toMatchObject({ sameSeries: true, samePrimitives: true, sameValues: true, sameData: true,
    sameSource: true, sameOverlayScale: true, localScales: true });
  expect(result.counts).toEqual(result.baseline);
  expect(result.boundIds.length).toBeGreaterThanOrEqual(3);
  expect(result.boundIds.every(binding => binding === (id ?? 'right'))).toBe(true);
  expect(result.markerInk).toBeGreaterThan(50);
  expect(result.overlayInk).toBeGreaterThan(5);
  expect(result.box).toEqual([0, 255, 255, 255]);
  expect(Math.abs(result.gradient[0] - 128)).toBeLessThan(8);
  expect(result.gradient[1]).toBe(0);
  expect(Math.abs(result.gradient[2] - 128)).toBeLessThan(8);
  expect(result.gradient[3]).toBe(255);
  expect(result.texts).toContain('Study label');
  expect(result.texts).toContain('Middle');
  expect(result.texts).toContain('75.0');
  if (id?.startsWith('overlay:')) expect(result.pills).toEqual([]);
  else {
    expect(result.pills).toHaveLength(1);
    const pill = result.pills[0];
    expect(pill.x).toBeGreaterThanOrEqual(id === 'left' ? 0 : 844);
    expect(pill.x + pill.width).toBeLessThanOrEqual(id === 'left' ? 56 : 900);
  }
}

test('a whole study keeps its geometry and ownership while changing scales and restoring state', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 620 });
  await page.route('**/study-scale.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#chart{width:900px;height:620px}</style></head><body><div id="chart"></div></body></html>' }));
  await page.goto('/study-scale.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs', lib = await import(bundle) as typeof Charts;
    const counts = { calc: 0, attach: 0 };
    lib.registerIndicator({ id: 'browser-moving-study', name: 'Movable study', placement: 'pane', inputs: [],
      plots: [
        { key: 'upper', type: 'line', title: 'Upper', style: { color: '#11cc88', lineWidth: 2, precision: 1 } },
        { key: 'lower', type: 'line', title: 'Lower', style: { color: '#ddee33', lineWidth: 2 } },
        { key: 'price', type: 'line', title: 'Price overlay', overlay: true, style: { color: '#cc8844', lineWidth: 3 } },
      ],
      calc: bars => { counts.calc++; return { upper: bars.map(() => 75), lower: bars.map(() => 25), price: bars.map(() => 150) }; },
      attach: () => { counts.attach++; },
      fills: [{ between: ['upper', 'lower'], opacity: 1,
        gradient: { topValue: 75, bottomValue: 25, topColor: '#ff0000', bottomColor: '#0000ff' } }],
      levels: () => [{ price: 55, title: 'Middle', color: '#ffaa00', dashed: false }],
      range: () => ({ min: 0, max: 100 }),
      draws: ({ bars }) => [
        { kind: 'box', from: { time: bars[5].time, price: 10 }, to: { time: bars[10].time, price: 0 }, color: '#00ffff', fillColor: '#00ffff', opacity: 1 },
        { kind: 'label', at: { time: bars[22].time, price: 90 }, text: 'Study label', color: '#993366' },
      ],
      markers: ({ bars }) => [{ id: 'plot-marker', time: bars[12].time, position: 'inBar', shape: 'square', color: '#ff33cc', size: 'big' }],
    });
    const chart = lib.createChart(document.getElementById('chart')!, { branding: false, theme: lib.darkTheme,
      animZoom: false, animAutoscale: false, timeNavigator: false });
    const source = chart.addSeries('line', { style: { color: '#888888' } });
    source.setData(Array.from({ length: 36 }, (_, index) => ({ time: 1700000000 + index * 60, open: 120, high: 120, low: 120, close: 120 })));
    const study = chart.addIndicator('browser-moving-study') as IndicatorInstance;
    chart.setPaneWeight(study.paneIndex, 0.8);
    const pane = chart.panes()[study.paneIndex];
    for (const [scale, min, max] of [[source.priceScale(), 100, 200], [pane.scaleFor('left'), -50, 150], [pane.scaleFor('overlay:study'), -100, 100]] as const) {
      scale.setAutoScale(false); scale.setPriceRange({ min, max });
    }
    const resources = study.renderResources(), pills: Pill[] = [], texts: string[] = [];
    const ctx = pane.base.ctx, clear = ctx.clearRect.bind(ctx), fill = ctx.fillRect.bind(ctx), text = ctx.fillText.bind(ctx);
    ctx.clearRect = (x, y, w, h) => { pills.length = 0; texts.length = 0; clear(x, y, w, h); };
    ctx.fillRect = (x, y, width, height) => {
      if (ctx.fillStyle === '#ffaa00') {
        const dpr = ctx.canvas.width / 900, matrix = ctx.getTransform(), point = new DOMPoint(x, y).matrixTransform(matrix);
        pills.push({ x: point.x / dpr, y: point.y / dpr, width: width * matrix.a / dpr, height: height * matrix.d / dpr });
      }
      fill(x, y, width, height);
    };
    ctx.fillText = (label, x, y, maxWidth) => { texts.push(label); if (maxWidth === undefined) text(label, x, y); else text(label, x, y, maxWidth); };
    const topText = pane.top.ctx.fillText.bind(pane.top.ctx);
    pane.top.ctx.fillText = (label, x, y, maxWidth) => {
      texts.push(label); if (maxWidth === undefined) topText(label, x, y); else topText(label, x, y, maxWidth);
    };
    window.__studyScale = { chart, study, source, series: resources.series.map(item => item.api),
      primitives: resources.primitives.map(item => item.primitive), bound: resources.primitives.map(item => item.primitive).filter(item => pane.primitiveScaleId(item) !== null),
      values: study.values(), overlayScale: study.series('price')!.priceScale(), data: JSON.stringify(resources.series.map(item => item.api.getData())),
      counts, baseline: { ...counts }, objects: 0, pills, texts };
    chart.on('objects:change', () => window.__studyScale.objects++);
    chart.setVisibleLogicalRange({ from: -2, to: 38 });
  });
  await paint(page);
  expectVisuals(await inspect(page), null);
  await page.locator('#chart').screenshot({ path: info.outputPath('study-right-default.png') });
  for (const id of ['left', 'overlay:study', 'right'] as const) {
    expect(await page.evaluate(scaleId => {
      const state = window.__studyScale; state.objects = 0;
      return state.study.setPriceScale(scaleId);
    }, id)).toBe(true);
    await paint(page);
    const result = await inspect(page); expectVisuals(result, id);
    expect(result.objects).toBe(1);
    expect(result.width).toBe(id === 'left' ? 788 : 844);
    expect(result.leftRange).toEqual({ min: -50, max: 150 });
    expect(result.hiddenRange).toEqual({ min: -100, max: 100 });
    expect(result.range).toEqual(id === 'left' ? result.leftRange : id === 'overlay:study' ? result.hiddenRange : { min: 0, max: 100 });
    await page.locator('#chart').screenshot({ path: info.outputPath(`study-${id.replace(':', '-')}.png`) });
  }
  await page.evaluate(() => {
    const state = window.__studyScale;
    state.study.setPriceScale('left'); state.saved = JSON.parse(JSON.stringify(state.chart.getState())) as ChartState;
  });
  await paint(page);
  const svg = await page.evaluate(() => window.__studyScale.chart.exportSVG());
  expect(svg).toContain('<linearGradient');
  const svgPills = await page.evaluate(source => {
    const root = new DOMParser().parseFromString(source, 'image/svg+xml').documentElement as unknown as SVGSVGElement;
    root.style.cssText = 'position:absolute;visibility:hidden;pointer-events:none'; document.body.appendChild(root);
    try {
      return Array.from(root.querySelectorAll<SVGRectElement>('rect[fill="#ffaa00"]')).map(rect => {
        const box = rect.getBBox(), matrix = rect.getCTM()!, point = new DOMPoint(box.x, box.y).matrixTransform(matrix);
        return { x: point.x, y: point.y, right: point.x + box.width, bottom: point.y + box.height };
      });
    } finally { root.remove(); }
  }, svg);
  expect(svgPills).toHaveLength(1);
  expect(svgPills[0].x).toBeGreaterThanOrEqual(0); expect(svgPills[0].right).toBeLessThanOrEqual(56);
  expect(svgPills[0].bottom).toBeLessThanOrEqual(620);
  await info.attach('study-left.svg', { body: svg, contentType: 'image/svg+xml' });
  const restored = await page.evaluate(() => {
    const state = window.__studyScale, { chart, saved } = state;
    state.study.setPriceScale('overlay:study');
    const result = chart.restoreState(saved!);
    const study = chart.indicators()[0], pane = chart.panes()[study.paneIndex];
    state.study = study as IndicatorInstance;
    return { applied: result.applied, id: study.priceScaleId(), sameSource: chart.primarySeries() === state.source,
      range: study.series('upper')!.priceScale().priceRange(),
      onLeft: study.series('upper')!.priceScale() === pane.scaleFor('left'),
      overlayOnPrice: study.series('price')!.priceScale() === chart.panes()[0].priceScale,
      savedId: saved!.indicators![0].priceScaleId };
  });
  expect(restored).toMatchObject({ applied: true, id: 'left', savedId: 'left', sameSource: true,
    range: { min: -50, max: 150 }, onLeft: true, overlayOnPrice: true });
  await paint(page);
  const restoredPixels = await inspect(page);
  expect(restoredPixels.markerInk).toBeGreaterThan(50);
  expect(restoredPixels.overlayInk).toBeGreaterThan(5);
  expect(restoredPixels.box).toEqual([0, 255, 255, 255]);
  expect(Math.abs(restoredPixels.gradient[0] - 128)).toBeLessThan(8);
  expect(Math.abs(restoredPixels.gradient[2] - 128)).toBeLessThan(8);
  await page.locator('#chart').screenshot({ path: info.outputPath('study-left-restored.png') });
  expect(errors).toEqual([]);
});

test('the documented whole-study example moves its plots with each scale button', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  const response = await page.request.get('/website/pages/examples.mdx');
  expect(response.ok()).toBe(true);
  const markdown = await response.text();
  const code = markdown.split('## Move a whole study between scales')[1].split('code={`')[1].split('`} />')[0];
  await page.setViewportSize({ width: 900, height: 440 });
  await page.route('**/study-example.html', route => route.fulfill({ contentType: 'text/html', body:
    '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#example{width:900px;height:440px}</style></head><body><div id="example"></div></body></html>' }));
  await page.goto('/study-example.html');
  await page.evaluate(async source => {
    const bundle = '/dist/openalgo-charts.mjs', lib = await import(bundle) as typeof Charts;
    const chart = new Function('el', 'lib', source)(document.getElementById('example'), lib) as Chart;
    const study = chart.indicators()[0] as IndicatorInstance;
    window.__studyExample = { chart, study, upper: study.series('upper')! };
  }, code);
  for (const [label, id] of [['Left', 'left'], ['Hidden', 'overlay:band'], ['Right', 'right'], ['Descriptor defaults', null]] as const) {
    await page.getByRole('button', { name: label, exact: true }).click();
    await paint(page);
    const result = await page.evaluate(() => {
      const { chart, study, upper } = window.__studyExample;
      return { id: study.priceScaleId(), sameHandle: study.series('upper') === upper,
        together: upper.priceScale() === study.series('lower')!.priceScale(),
        leftRange: chart.panes()[study.paneIndex].scaleFor('left').priceRange() };
    });
    expect(result).toEqual({ id, sameHandle: true, together: true, leftRange: { min: -25, max: 125 } });
    if (id === 'left' || id === 'overlay:band') await page.screenshot({ path: info.outputPath(`example-${label.toLowerCase()}.png`) });
  }
  expect(errors).toEqual([]);
});
