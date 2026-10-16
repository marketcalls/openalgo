import { test, expect, type Page } from '@playwright/test';
import type { Chart, PriceScale, SeriesApi, SeriesMarkers } from '../../src/index';
import type * as Charts from '../../src/index';

type AxisText = { text: string; x: number; y: number; width: number; size: number };
type AxisBox = { color: string; x: number; y: number; width: number; height: number };

declare global {
  interface Window {
    __seriesScaleAssignment: {
      chart: Chart; series: SeriesApi; markers: SeriesMarkers;
      scales: { right: PriceScale; left: PriceScale; overlay: PriceScale };
      data: string; labels: string[]; objects: number; updates: number;
    };
    __axisValueTags: { chart: Chart; primary: SeriesApi; left: SeriesApi; right: SeriesApi; texts: AxisText[]; boxes: AxisBox[] };
  }
}

async function paint(page: Page) {
  await page.evaluate(() => new Promise<void>(resolve => requestAnimationFrame(() => requestAnimationFrame(() => resolve()))));
}

async function pixelDifference(page: Page, first: string, second: string) {
  return page.evaluate(async ([a, b]) => {
    const decode = async (encoded: string) => {
      const bitmap = await createImageBitmap(await (await fetch(`data:image/png;base64,${encoded}`)).blob());
      const canvas = document.createElement('canvas');
      canvas.width = bitmap.width; canvas.height = bitmap.height;
      const context = canvas.getContext('2d')!;
      context.drawImage(bitmap, 0, 0);
      bitmap.close();
      return context.getImageData(0, 0, canvas.width, canvas.height).data;
    };
    const [left, right] = await Promise.all([decode(a), decode(b)]);
    let changedPixels = 0, maxChannelDelta = 0;
    for (let i = 0; i < left.length; i += 4) {
      const delta = Math.max(...[0, 1, 2, 3].map(channel => Math.abs(left[i + channel] - right[i + channel])));
      if (delta > 0) changedPixels++;
      maxChannelDelta = Math.max(maxChannelDelta, delta);
    }
    return { changedPixels, maxChannelDelta };
  }, [first, second]);
}

async function inspect(page: Page) {
  return page.evaluate(() => {
    const state = window.__seriesScaleAssignment;
    const { chart, series, markers, scales } = state;
    const id = chart.getState().series![0].priceScaleId;
    const target = id === 'right' ? scales.right : id === 'left' ? scales.left : scales.overlay;
    const bar = series.getData()[24];
    const x = chart.timeScale.indexToX(24), y = target.priceToY((bar.open + bar.close) / 2);
    const left = id === 'left' ? 56 : 0;
    let markerInk = 0;
    for (const canvas of document.querySelectorAll<HTMLCanvasElement>('#chart canvas')) {
      const context = canvas.getContext('2d');
      if (!context) continue;
      const dpr = canvas.width / 900;
      const pixels = context.getImageData(Math.round((left + x - 10) * dpr), Math.round((y - 10) * dpr), Math.round(20 * dpr), Math.round(20 * dpr)).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === 238 && pixels[i + 1] === 34 && pixels[i + 2] === 170 && pixels[i + 3] === 255) markerInk++;
      }
    }
    return {
      width: chart.timeScale.width, id,
      sameHandle: chart.primarySeries() === series, sameScale: series.priceScale() === target,
      sameData: JSON.stringify(series.getData()) === state.data,
      marker: markers.hitTest(x, y)?.externalId, markerInk,
      labels: state.labels.filter(label => /^[RLH]:/.test(label)),
      right: { range: scales.right.priceRange(), options: { ...scales.right.options }, auto: scales.right.autoScale },
      left: { range: scales.left.priceRange(), options: { ...scales.left.options }, auto: scales.left.autoScale },
      overlay: { range: scales.overlay.priceRange(), options: { ...scales.overlay.options }, auto: scales.overlay.autoScale },
      objects: state.objects, updates: state.updates,
    };
  });
}

test('a live series changes scales with its data, markers and target settings intact', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 550 });
  await page.route('**/series-scale-assignment.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#chart{width:900px;height:550px}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/series-scale-assignment.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const { createChart, darkTheme } = await import(bundle) as typeof Charts;
    const chart = createChart(document.getElementById('chart')!, {
      branding: false, theme: darkTheme, animZoom: false, animAutoscale: false, timeNavigator: false,
    });
    const series = chart.addSeries('line', { style: { color: '#22aadd', lineWidth: 3 } });
    const bars = Array.from({ length: 48 }, (_, i) => {
      const close = 100 + i / 2 + Math.sin(i / 3) * 7;
      return { time: 1700000000 + i * 60, open: close - 1, high: close + 2, low: close - 2, close };
    });
    series.setData(bars);
    const markers = series.createMarkers();
    markers.setMarkers([{ id: 'entry', time: bars[24].time, position: 'inBar', shape: 'square', size: 'big', color: '#ee22aa' }]);
    const pane = chart.panes()[0];
    const scales = { right: series.priceScale(), left: pane.scaleFor('left'), overlay: pane.scaleFor('overlay:manual') };
    for (const [scale, prefix, min, max, inverted] of [
      [scales.right, 'R:', 80, 160, false],
      [scales.left, 'L:', 60, 180, true],
      [scales.overlay, 'H:', 40, 200, false],
    ] as const) {
      scale.setAutoScale(false);
      scale.setPriceRange({ min, max });
      scale.setOptions({ inverted, marginTop: 0.15, marginBottom: 0.2 });
      scale.setPriceFormatter(value => `${prefix}${value.toFixed(0)}`);
    }
    const labels: string[] = [];
    for (const context of [pane.base.ctx, pane.top.ctx]) {
      const fillText = context.fillText.bind(context);
      context.fillText = (text, x, y, maxWidth) => {
        labels.push(text);
        if (maxWidth === undefined) fillText(text, x, y);
        else fillText(text, x, y, maxWidth);
      };
    }
    const state = { chart, series, markers, scales, data: JSON.stringify(series.getData()), labels, objects: 0, updates: 0 };
    chart.on('objects:change', () => state.objects++);
    chart.on('data:update', () => state.updates++);
    window.__seriesScaleAssignment = state;
    chart.setVisibleLogicalRange({ from: -2, to: 50 });
  });
  await paint(page);
  const original = await inspect(page);
  expect(original.width).toBe(844);
  expect(original.markerInk).toBeGreaterThan(60);
  expect(original.labels.some(label => label.startsWith('R:'))).toBe(true);
  const initialImage = await page.locator('#chart').screenshot({ path: info.outputPath('series-scale-initial.png') });

  for (const id of ['left', 'overlay:manual', 'right'] as const) {
    expect(await page.evaluate(scaleId => {
      const state = window.__seriesScaleAssignment;
      state.labels.length = 0; state.objects = 0; state.updates = 0;
      return state.chart.setSeriesPriceScale(state.series, scaleId);
    }, id)).toBe(true);
    await paint(page);
    const actual = await inspect(page);
    expect(actual).toMatchObject({ id, sameHandle: true, sameScale: true, sameData: true, marker: 'entry', objects: 1, updates: 0 });
    expect(actual.width).toBe(id === 'overlay:manual' ? 900 : 844);
    expect(actual.right).toEqual(original.right);
    expect(actual.left).toEqual(original.left);
    expect(actual.overlay).toEqual(original.overlay);
    expect(actual.markerInk).toBeGreaterThan(60);
    const prefix = id === 'left' ? 'L:' : 'R:';
    if (id === 'overlay:manual') expect(actual.labels).toEqual([]);
    else {
      expect(actual.labels.length).toBeGreaterThan(2);
      expect(actual.labels.every(label => label.startsWith(prefix))).toBe(true);
    }
    const first = await page.locator('#chart').screenshot({ path: info.outputPath(`series-scale-${id.replace(':', '-')}.png`) });
    await page.evaluate(() => window.__seriesScaleAssignment.series.applyOptions({ lineWidth: 3 }));
    await paint(page);
    const repeated = await page.locator('#chart').screenshot();
    expect(repeated.equals(first)).toBe(true);
    if (id === 'right') {
      // Canvas dash antialiasing can round a few channels differently after transforms.
      const difference = await pixelDifference(page, initialImage.toString('base64'), repeated.toString('base64'));
      expect(difference.changedPixels).toBeLessThanOrEqual(20);
      expect(difference.maxChannelDelta).toBeLessThanOrEqual(3);
    } else expect(repeated.equals(initialImage)).toBe(false);
    if (id === 'overlay:manual') {
      await page.evaluate(() => { window.__seriesScaleAssignment.labels.length = 0; });
      await page.mouse.move(450, 220);
      await paint(page);
      expect((await inspect(page)).labels).toEqual([]);
      await page.locator('#chart').screenshot({ path: info.outputPath('series-scale-hidden-crosshair.png') });
      await page.mouse.move(-10, -10);
      await paint(page);
    }
  }

  await page.evaluate(() => {
    const { series } = window.__seriesScaleAssignment;
    const bars = series.getData(), last = bars[bars.length - 1];
    series.update({ ...last, close: last.close + 4 });
  });
  await paint(page);
  expect((await inspect(page)).sameData).toBe(false);
  expect((await inspect(page)).updates).toBe(1);
  expect(errors).toEqual([]);
});

async function inspectAxisTags(page: Page) {
  return page.evaluate(() => {
    const { chart, texts, boxes } = window.__axisValueTags;
    const canvas = chart.panes()[0].base.element, context = canvas.getContext('2d')!;
    const dpr = canvas.width / 900;
    const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data;
    let primaryInk = 0, minX = canvas.width, maxX = -1, minY = canvas.height, maxY = -1;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] !== 238 || pixels[i + 1] !== 34 || pixels[i + 2] !== 170 || pixels[i + 3] !== 255) continue;
      const x = (i / 4) % canvas.width, y = Math.floor(i / 4 / canvas.width);
      primaryInk++; minX = Math.min(minX, x); maxX = Math.max(maxX, x); minY = Math.min(minY, y); maxY = Math.max(maxY, y);
    }
    const tags = boxes.filter(box => ['#ee22aa', '#eebb22', '#4488ff'].includes(box.color));
    return {
      width: chart.timeScale.width, texts,
      tags: tags.map(box => {
        const data = context.getImageData(Math.max(0, Math.floor(box.x * dpr)), Math.max(0, Math.floor(box.y * dpr)),
          Math.max(1, Math.ceil(box.width * dpr)), Math.max(1, Math.ceil(box.height * dpr))).data;
        const rgb = [1, 3, 5].map(start => parseInt(box.color.slice(start, start + 2), 16));
        let ink = 0;
        for (let i = 0; i < data.length; i += 4) if (data[i] === rgb[0] && data[i + 1] === rgb[1] && data[i + 2] === rgb[2] && data[i + 3] === 255) ink++;
        return { ...box, ink };
      }),
      primaryInk, primaryBounds: { minX: minX / dpr, maxX: maxX / dpr, minY: minY / dpr, maxY: maxY / dpr },
    };
  });
}

test('left and right value pills retain their colors, countdown and bounded text', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 900, height: 550 });
  await page.route('**/axis-value-tags.html', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><html><head><style>html,body{margin:0;background:#101010}#chart{width:900px;height:550px}</style></head><body><div id="chart"></div></body></html>',
  }));
  await page.goto('/axis-value-tags.html');
  await page.evaluate(async () => {
    const bundle = '/dist/openalgo-charts.mjs';
    const { createChart, darkTheme } = await import(bundle) as typeof Charts;
    const chart = createChart(document.getElementById('chart')!, { branding: false, animZoom: false, animAutoscale: false,
      timeNavigator: false, theme: { ...darkTheme, lastPriceUp: '#ee22aa', lastPriceDown: '#ee22aa', lastPriceText: '#ffffff' },
      axisChrome: { barCountdown: true, clock: () => 1700000000 + 47 * 60 + 20 },
    });
    const bars = (value: number) => Array.from({ length: 48 }, (_, index) => ({
      time: 1700000000 + index * 60, open: value, high: value, low: value, close: value,
    }));
    const primary = chart.addSeries('line', { priceScaleId: 'left', style: { color: '#22aadd', lineWidth: 2, priceLineVisible: false } });
    primary.setData(bars(100.25));
    const left = chart.addSeries('line', { priceScaleId: 'left', style: { color: '#eebb22' } });
    left.setData(bars(150.25));
    const right = chart.addSeries('line', { style: { color: '#4488ff' } });
    right.setData(bars(150.25));
    for (const [series, prefix] of [[primary, 'L'], [right, 'R']] as const) {
      const scale = series.priceScale();
      scale.setAutoScale(false);
      scale.setPriceRange({ min: 0, max: 200 });
      scale.setPriceFormatter(value => `${prefix}${value.toFixed(1)}`);
    }
    const texts: AxisText[] = [], boxes: AxisBox[] = [];
    const context = chart.panes()[0].base.ctx;
    const clearRect = context.clearRect.bind(context), fillRect = context.fillRect.bind(context), fillText = context.fillText.bind(context);
    context.clearRect = (x, y, width, height) => { texts.length = 0; boxes.length = 0; clearRect(x, y, width, height); };
    context.fillRect = (x, y, width, height) => {
      const matrix = context.getTransform(), point = new DOMPoint(x, y).matrixTransform(matrix), dpr = context.canvas.width / 900;
      boxes.push({ color: String(context.fillStyle), x: point.x / dpr, y: point.y / dpr, width: width * matrix.a / dpr, height: height * matrix.d / dpr });
      fillRect(x, y, width, height);
    };
    context.fillText = (text, x, y, maxWidth) => {
      const matrix = context.getTransform(), point = new DOMPoint(x, y).matrixTransform(matrix), dpr = context.canvas.width / 900;
      texts.push({ text, x: point.x / dpr, y: point.y / dpr, width: context.measureText(text).width * matrix.a / dpr,
        size: Number(/([\d.]+)px/.exec(context.font)?.[1] ?? 0) / dpr });
      if (maxWidth === undefined) fillText(text, x, y);
      else fillText(text, x, y, maxWidth);
    };
    window.__axisValueTags = { chart, primary, left, right, texts, boxes };
    chart.setVisibleLogicalRange({ from: -2, to: 50 });
  });
  await paint(page);
  const initial = await inspectAxisTags(page);
  expect(initial.width).toBe(788);
  expect(initial.tags).toHaveLength(3);
  expect(initial.texts.filter(text => text.text === '00:00:40')).toHaveLength(1);
  for (const [label, color, side] of [['L100.3', '#ee22aa', 'left'], ['L150.3', '#eebb22', 'left'], ['R150.3', '#4488ff', 'right']] as const) {
    const box = initial.tags.find(tag => tag.color === color)!;
    const text = initial.texts.find(item => item.text === label)!;
    expect(box?.ink).toBeGreaterThan(100);
    expect(text).toBeDefined();
    expect(box.x).toBeGreaterThanOrEqual(side === 'left' ? 0 : 844);
    expect(box.x + box.width).toBeLessThanOrEqual(side === 'left' ? 56 : 900);
    expect(text.x).toBeGreaterThanOrEqual(box.x);
    expect(text.x + text.width).toBeLessThanOrEqual(box.x + box.width + 0.01);
  }
  const first = await page.locator('#chart').screenshot({ path: info.outputPath('both-axis-value-pills.png') });
  await page.evaluate(() => window.__axisValueTags.primary.applyOptions({ lineWidth: 2 }));
  await paint(page);
  expect((await page.locator('#chart').screenshot()).equals(first)).toBe(true);

  await page.evaluate(() => {
    const { chart, primary, left, right } = window.__axisValueTags;
    chart.setSeriesPriceScale(primary, 'overlay:primary');
    chart.setSeriesPriceScale(left, 'overlay:left');
    chart.setSeriesPriceScale(right, 'overlay:right');
  });
  await paint(page);
  const hidden = await inspectAxisTags(page);
  expect(hidden.width).toBe(900);
  expect(hidden.tags).toEqual([]);
  expect(hidden.primaryInk).toBe(0);
  expect(hidden.texts.some(text => text.text === '00:00:40')).toBe(false);
  await page.locator('#chart').screenshot({ path: info.outputPath('hidden-scale-no-value-pills.png') });

  await page.evaluate(() => {
    const { chart, primary, left, right } = window.__axisValueTags;
    chart.setSeriesPriceScale(primary, 'left'); left.remove(); right.remove();
    chart.applyOptions({ theme: { ...chart.theme(), axisFontSize: 48 } });
    primary.priceScale().setPriceFormatter(value => `Long price ${value.toFixed(6)}`);
  });
  for (const edge of ['top', 'bottom'] as const) {
    await page.evaluate(position => {
      const { primary } = window.__axisValueTags;
      primary.priceScale().setPriceRange(position === 'top' ? { min: 0, max: 100.25 } : { min: 100.25, max: 200.25 });
      primary.applyOptions({ lineWidth: 2 });
    }, edge);
    await paint(page);
    const state = await inspectAxisTags(page), box = state.tags.find(tag => tag.color === '#ee22aa')!;
    expect(box?.ink).toBeGreaterThan(100);
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(56);
    expect(box.y).toBeGreaterThanOrEqual(0);
    expect(box.y + box.height).toBeLessThanOrEqual(528);
    expect(edge === 'top' ? box.y : box.y + box.height).toBe(edge === 'top' ? 0 : 528);
    expect(state.primaryBounds.minX).toBeGreaterThanOrEqual(0);
    expect(state.primaryBounds.maxX).toBeLessThan(56);
    expect(state.primaryBounds.minY).toBeGreaterThanOrEqual(0);
    expect(state.primaryBounds.maxY).toBeLessThan(528);
    const rows = state.texts.filter(text => text.y >= box.y && text.y <= box.y + box.height && text.x >= box.x && text.x < box.x + box.width);
    expect(rows.map(row => row.text)).toEqual(['Long price 100.250000', '00:00:40']);
    for (const row of rows) {
      expect(row.size).toBeLessThanOrEqual(12.01);
      expect(row.x + row.width).toBeLessThanOrEqual(box.x + box.width + 0.01);
    }
    await page.locator('#chart').screenshot({ path: info.outputPath(`left-value-pill-${edge}-large-font.png`) });
  }
  expect(errors).toEqual([]);
});
