import { expect, test, type Page } from '@playwright/test';
import type { AlertController, Chart, SeriesApi, Bar, AlertTriggeredPayload } from '../../src/index';
import type { DrawingController } from '../../src/draw/index';

declare global {
  interface Window {
    __alertsDemo: {
      chart: Chart; series: SeriesApi; draw: DrawingController; alerts: AlertController;
      bars: Bar[]; ids: Record<string, string>; drawingId: string; fired: AlertTriggeredPayload[];
    };
  }
}

async function ink(page: Page, rgb: readonly number[]) {
  return page.locator('#chart canvas').evaluateAll((elements, rgb) => {
    let count = 0;
    for (const element of elements) {
      const canvas = element as HTMLCanvasElement;
      const pixels = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] === rgb[0] && pixels[i + 1] === rgb[1] && pixels[i + 2] === rgb[2] && pixels[i + 3] > 200) count++;
      }
    }
    return count;
  }, [...rgb]);
}

test('price alerts remain visible across timeframes while their original evaluation stays paused', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto('/tests/e2e/alerts-fixture.html');
  await page.waitForFunction(() => !!window.__alertsDemo);
  await page.evaluate(() => {
    const { chart, series, alerts, bars } = window.__alertsDemo;
    const document = alerts.toJSON();
    series.setData([]);
    chart.setDataContext({ symbol: 'ALERT FIXTURE', exchange: 'SIM', interval: '5m' });
    series.setData(bars.filter((_, index) => index % 5 === 0));
    alerts.fromJSON(document);
    chart.fitContent();
  });
  await expect.poll(() => page.evaluate(() => window.__alertsDemo.chart.exportSVG().includes('Confirmed threshold (1m)'))).toBe(true);
  const paused = await page.evaluate(() => {
    const { chart, alerts, ids, fired } = window.__alertsDemo;
    return { svg: chart.exportSVG(), availability: alerts.availability(ids.close), fired: fired.length, count: alerts.list().length };
  });
  expect(paused.availability).toMatchObject({ available: false, reason: expect.stringContaining('1m') });
  expect(paused.count).toBe(5);
  expect(paused.fired).toBe(0);
  expect(paused.svg).toContain('Paused');
  expect(paused.svg).toContain('Disabled');
  expect(paused.svg).toContain('Expired');
  expect(paused.svg).not.toContain('Drawing threshold');
  await expect.poll(() => ink(page, [59, 130, 246])).toBeGreaterThan(100);
  const point = await page.evaluate(() => {
    const { chart } = window.__alertsDemo;
    const box = document.getElementById('chart')!.getBoundingClientRect();
    return { x: box.left + 400, y: box.top + chart.priceToCoordinate(110)! };
  });
  await page.mouse.move(point.x, point.y);
  expect(await page.locator('#chart').evaluate(node => node.style.cursor)).not.toBe('ns-resize');
  await page.mouse.move(5, 5);
  await page.screenshot({ path: info.outputPath('alerts-other-timeframe.png'), animations: 'disabled' });
  await page.evaluate(() => {
    const { chart, series, bars } = window.__alertsDemo;
    series.setData([]);
    chart.setDataContext({ symbol: 'ALERT FIXTURE', exchange: 'SIM', interval: '1m' });
    series.setData(bars);
    chart.fitContent();
  });
  expect(await page.evaluate(() => window.__alertsDemo.fired)).toEqual([]);
  expect(await page.evaluate(() => window.__alertsDemo.alerts.availability(window.__alertsDemo.ids.close).available)).toBe(true);
  expect(await page.evaluate(() => window.__alertsDemo.chart.exportSVG())).toContain('Drawing threshold');
  await page.evaluate(() => {
    const { series, bars } = window.__alertsDemo;
    const tail = bars[bars.length - 1];
    series.update({ ...tail, close: 112, high: 113 });
    series.update({ ...tail, time: tail.time + 60, open: 112, close: 112, high: 113 });
  });
  expect(await page.evaluate(() => {
    const { fired, ids } = window.__alertsDemo;
    return fired.filter(event => event.alertId === ids.close).length;
  })).toBe(1);
  expect(errors).toEqual([]);
});

test('drawing alerts follow a real drag and render armed, triggered, disabled and expired levels', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1360, height: 900 });
  await page.goto('/tests/e2e/alerts-fixture.html');
  await page.waitForFunction(() => !!window.__alertsDemo);
  for (const rgb of [[59, 130, 246], [100, 116, 139], [217, 119, 6]]) {
    await expect.poll(() => ink(page, rgb)).toBeGreaterThan(100);
  }
  expect(await page.evaluate(() => window.__alertsDemo.chart.exportSVG())).toContain('Confirmed threshold');
  await page.screenshot({ path: info.outputPath('alerts-armed.png'), animations: 'disabled' });
  const point = await page.evaluate(() => {
    const { chart, bars } = window.__alertsDemo;
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    return { x: rect.left + chart.timeToCoordinate(bars[27].time), y: rect.top + chart.priceToCoordinate(108)!,
      targetY: rect.top + chart.priceToCoordinate(112)! };
  });
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x, point.targetY, { steps: 12 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => {
    const { draw, drawingId } = window.__alertsDemo;
    return draw.get(drawingId)!.points[0].price;
  })).toBeCloseTo(112, 1);
  await page.evaluate(() => {
    const { series, bars } = window.__alertsDemo;
    series.update({ ...bars[bars.length - 1], high: 114 });
  });
  await expect.poll(() => page.evaluate(() => window.__alertsDemo.fired.length)).toBe(2);
  expect(await page.evaluate(() => window.__alertsDemo.alerts.list().filter(alert => alert.state === 'triggered').map(alert => alert.id).sort()))
    .toEqual(await page.evaluate(() => [window.__alertsDemo.ids.touch, window.__alertsDemo.ids.drawing].sort()));
  await expect.poll(() => ink(page, [34, 197, 94])).toBeGreaterThan(100);
  await page.evaluate(() => {
    const { series, bars } = window.__alertsDemo;
    const last = bars[bars.length - 1];
    series.update(last);
    series.update({ ...last, time: last.time + 60 });
  });
  expect(await page.evaluate(() => window.__alertsDemo.alerts.list().find(alert => alert.id === window.__alertsDemo.ids.close)!.state)).toBe('armed');
  const svg = await page.evaluate(() => window.__alertsDemo.chart.exportSVG());
  for (const label of ['Triggered', 'Alert', 'Disabled', 'Expired']) expect(svg).toContain(label);
  const overdraw = await page.evaluate(() => {
    const { chart, draw, drawingId } = window.__alertsDemo;
    const price = draw.get(drawingId)!.points[0].price;
    const overlay = document.querySelectorAll<HTMLCanvasElement>('#chart canvas')[1];
    const dpr = overlay.width / overlay.getBoundingClientRect().width;
    const y = chart.priceToCoordinate(price)!;
    const pixels = overlay.getContext('2d')!.getImageData(8 * dpr, Math.round(y * dpr), 140 * dpr, 1).data;
    let magenta = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] > 200 && pixels[i + 1] > 70 && pixels[i + 1] < 160 && pixels[i + 2] > 200) magenta++;
    }
    return magenta;
  });
  expect(overdraw, 'Drawing strokes must not strike through alert state and title').toBe(0);
  await page.mouse.move(5, 5);
  await page.screenshot({ path: info.outputPath('alerts-triggered.png'), animations: 'disabled' });
  await page.evaluate(() => window.__alertsDemo.draw.remove(window.__alertsDemo.drawingId));
  expect(await page.evaluate(() => window.__alertsDemo.chart.exportSVG())).not.toContain('Drawing threshold');
  expect(errors).toEqual([]);
});

test('clear plot space preserves pane panning and alert teardown removes every overlay', async ({ page }) => {
  await page.goto('/tests/e2e/alerts-fixture.html');
  await page.waitForFunction(() => !!window.__alertsDemo);
  const point = await page.evaluate(() => {
    const { chart } = window.__alertsDemo;
    const rect = document.getElementById('chart')!.getBoundingClientRect();
    return { x: rect.left + 500, y: rect.top + chart.priceToCoordinate(101)!, from: chart.getVisibleLogicalRange()!.from };
  });
  await page.mouse.move(point.x, point.y);
  await page.mouse.down();
  await page.mouse.move(point.x + 120, point.y, { steps: 10 });
  await page.mouse.up();
  await expect.poll(() => page.evaluate(() => window.__alertsDemo.chart.getVisibleLogicalRange()!.from)).not.toBe(point.from);
  await page.evaluate(() => window.__alertsDemo.alerts.destroy());
  const svg = await page.evaluate(() => window.__alertsDemo.chart.exportSVG());
  for (const label of ['Intrabar threshold', 'Confirmed threshold', 'Drawing threshold', 'Disabled level', 'Expired level']) expect(svg).not.toContain(label);
});

for (const spentLines of ['show', 'hide']) {
  test(`a page reload restores drawing anchors without new delivery with spent lines ${spentLines}`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.setViewportSize({ width: 1360, height: 900 });
    await page.goto(`/tests/e2e/alerts-fixture.html?spentLines=${spentLines}`);
    await page.waitForFunction(() => !!window.__alertsDemo);
    await page.evaluate(() => {
      const { series, bars, chart } = window.__alertsDemo;
      series.update({ ...bars[bars.length - 1], high: 114 });
      sessionStorage.setItem('saved-alert-chart', JSON.stringify(chart.getState()));
    });
    expect(await page.evaluate(() => window.__alertsDemo.fired.length)).toBe(2);
    await page.reload();
    await page.waitForFunction(() => !!window.__alertsDemo);
    expect(await page.evaluate(() => window.__alertsDemo.chart.restoreState(JSON.parse(sessionStorage.getItem('saved-alert-chart')!)).applied)).toBe(true);
    expect(await page.evaluate(() => window.__alertsDemo.alerts.list().map(alert => [alert.title, alert.state]))).toEqual([
      ['Intrabar threshold', 'triggered'], ['Confirmed threshold', 'armed'], ['Drawing threshold', 'triggered'],
      ['Disabled level', 'disabled'], ['Expired level', 'expired'],
    ]);
    expect(await page.evaluate(() => {
      const { alerts, draw } = window.__alertsDemo;
      const source = alerts.list().find(alert => alert.title === 'Drawing threshold')!.source;
      return source.kind === 'drawing' && draw.get(source.drawingId)?.points[0].price;
    })).toBe(108);
    await page.evaluate(() => {
      const { series, bars } = window.__alertsDemo;
      const last = bars[bars.length - 1];
      series.update({ ...last, high: 115 });
      series.update({ ...last, time: last.time + 60 });
    });
    expect(await page.evaluate(() => window.__alertsDemo.fired)).toEqual([]);
    if (spentLines === 'show') await expect.poll(() => ink(page, [34, 197, 94])).toBeGreaterThan(100);
    else {
      await expect.poll(() => ink(page, [34, 197, 94])).toBe(0);
      await expect.poll(() => ink(page, [217, 119, 6])).toBe(0);
      await expect.poll(() => ink(page, [232, 121, 249])).toBeGreaterThan(100);
    }
    const svg = await page.evaluate(() => window.__alertsDemo.chart.exportSVG());
    for (const title of ['Intrabar threshold', 'Confirmed threshold', 'Drawing threshold', 'Disabled level', 'Expired level']) {
      const hidden = spentLines === 'hide' && ['Intrabar threshold', 'Drawing threshold', 'Expired level'].includes(title);
      expect(svg.split(title).length - 1).toBe(hidden ? 0 : 1);
    }
    await page.screenshot({ path: info.outputPath('alerts-restored.png'), animations: 'disabled' });
    await page.evaluate(() => {
      const { alerts, ids } = window.__alertsDemo;
      alerts.enable(ids.touch);
      alerts.update(ids.expired, { expiresAt: 2000, state: 'armed' });
    });
    const rearmed = await page.evaluate(() => window.__alertsDemo.chart.exportSVG());
    expect(rearmed).toContain('Intrabar threshold');
    expect(rearmed).toContain('Expired level');
    expect(await page.evaluate(() => window.__alertsDemo.fired)).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('hidden spent ranges remove both bounds while repeating alerts keep their lines', async ({ page }, info) => {
  await page.goto('/tests/e2e/alerts-fixture.html?spentLines=hide');
  await page.waitForFunction(() => !!window.__alertsDemo);
  const states = await page.evaluate(() => {
    const { alerts, series, bars } = window.__alertsDemo;
    const range = alerts.add({ title: 'Finished band', source: { kind: 'price', price: 102, upperPrice: 107 },
      condition: 'enteringRange', policy: 'onTouch' });
    const repeat = alerts.add({ title: 'Repeating threshold', source: { kind: 'price', price: 103 },
      condition: 'crossingUp', policy: 'onTouch', repeat: 'everyTime' });
    series.update({ ...bars[bars.length - 1], close: 104, high: 104 });
    return { range: alerts.list().find(item => item.id === range.id)?.state,
      repeat: alerts.list().find(item => item.id === repeat.id)?.state };
  });
  expect(states).toEqual({ range: 'triggered', repeat: 'armed' });
  const svg = await page.evaluate(() => window.__alertsDemo.chart.exportSVG());
  expect(svg).not.toContain('Finished band');
  expect(svg).toContain('Repeating threshold');
  await expect.poll(() => ink(page, [59, 130, 246])).toBeGreaterThan(100);
  await page.screenshot({ path: info.outputPath('spent-range-hidden-repeat-visible.png'), animations: 'disabled' });
});

for (const finish of ['trigger', 'expire']) {
  test(`hiding an alert during a drag cancels its draft on ${finish}`, async ({ page }) => {
    await page.goto('/tests/e2e/alerts-fixture.html?spentLines=hide');
    await page.waitForFunction(() => !!window.__alertsDemo);
    const point = await page.evaluate(() => {
      const { chart } = window.__alertsDemo;
      const box = document.getElementById('chart')!.getBoundingClientRect();
      return { x: box.left + 500, y: box.top + chart.priceToCoordinate(105)! };
    });
    await page.mouse.move(point.x, point.y);
    await expect.poll(() => page.evaluate(() => window.__alertsDemo.alerts.hovered()))
      .toBe(await page.evaluate(() => window.__alertsDemo.ids.touch));
    await page.mouse.down();
    await page.mouse.move(point.x, point.y + 12, { steps: 4 });
    await page.evaluate(finish => {
      const { alerts, ids, series, bars } = window.__alertsDemo;
      if (finish === 'expire') alerts.update(ids.touch, { expiresAt: 999 });
      else series.update({ ...bars[bars.length - 1], high: 106 });
    }, finish);
    await page.mouse.up();
    const result = await page.evaluate(() => {
      const { alerts, ids, chart } = window.__alertsDemo;
      return { alert: alerts.list().find(item => item.id === ids.touch), hovered: alerts.hovered(),
        visible: chart.exportSVG().includes('Intrabar threshold') };
    });
    expect(result.alert).toMatchObject({ state: finish === 'expire' ? 'expired' : 'triggered',
      source: { kind: 'price', price: 105 } });
    expect(result.hovered).toBeUndefined();
    expect(result.visible).toBe(false);
  });
}

test('a price alert fires once, at the brick a replayed Renko step crossed inside it', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.setViewportSize({ width: 1100, height: 620 });
  await page.goto('/tests/e2e/transform-live-fixture.html?type=renko&study=none');
  await page.waitForFunction(() => (window as any).__ready);
  const run = await page.evaluate(async () => {
    const { chart, series, lib } = (window as any).__probe;
    const bricksOf = (bars: any[]) => {
      const transform = lib.getSeriesTransform('renko').create({ boxSize: 2 });
      transform.setData(bars);
      return transform.elements() as any[];
    };
    // Seven more hours replayed bar by bar, as a feed delivers them: a seeded
    // continuation of the session's random walk. A bar that moves more than a
    // box completes several bricks in one update.
    const history = series.getData();
    let seed = 20261001;
    const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
    const gauss = () => Math.sqrt(-2 * Math.log(random() || 1e-9)) * Math.cos(2 * Math.PI * random());
    const replay: any[] = [];
    for (let i = 0, last = history.at(-1); i < 84; i++) {
      const open = last.close;
      const close = Math.round(open * (1 + gauss() * 0.0019) * 20) / 20;
      last = { time: last.time + 300, open, close, high: Math.max(open, close), low: Math.min(open, close), volume: 50000 };
      replay.push(last);
    }
    // Where each replayed bar's bricks end, worked out ahead, so the level can
    // sit inside a step of two or more bricks with no crossing before it.
    const start = chart.primaryBars().length;
    const ends = replay.map((_, i) => bricksOf([...history, ...replay.slice(0, i + 1)]).length);
    const bricks = bricksOf([...history, ...replay]);
    const crosses = (level: number, j: number) => (bricks[j - 1].close - level) * (bricks[j].close - level) < 0;
    let target = -1, level = NaN;
    for (let b = start; b < bricks.length - 1 && target < 0; b++) {
      const step = ends.findIndex(end => end > b);
      if (b === ends[step] - 1) continue; // the last brick of its step
      const candidate = (bricks[b - 1].close + bricks[b].close) / 2;
      let clear = true;
      for (let j = start - 1; j < b; j++) if (crosses(candidate, j)) clear = false;
      if (clear) { target = b; level = candidate; }
    }
    const alerts = new lib.AlertController(chart);
    const close = alerts.add({ title: 'Brick close', source: { kind: 'price', price: level }, condition: 'crossing' });
    const touch = alerts.add({ title: 'Brick touch', source: { kind: 'price', price: level }, condition: 'crossing', policy: 'onTouch' });
    const every = alerts.add({ title: 'Every brick close', source: { kind: 'price', price: level }, condition: 'crossing', repeat: 'everyTime' });
    const fired: { id: string; time: number; index: number; price: number }[] = [];
    chart.on('alert:triggered', (e: any) => fired.push({ id: e.alertId, time: e.time, index: e.index, price: e.price }));
    for (const bar of replay) {
      series.update(bar);
      await (window as any).__frame();
    }
    const drawn = chart.primaryBars();
    const at = (id: string) => fired.filter(e => e.id === id).map(({ time, index, price }) => ({ time, index, price }));
    series.createMarkers().setMarkers([...at(close.id), ...at(touch.id)].slice(0, 1).map(e => ({
      time: e.time, position: drawn[e.index].close > level ? 'belowBar' : 'aboveBar',
      shape: drawn[e.index].close > level ? 'arrowUp' : 'arrowDown', size: 'medium', color: '#f5a623', text: 'Alert',
    })));
    chart.setVisibleLogicalRange({ from: target - 30, to: target + 20 });
    await (window as any).__frame();
    return {
      start, target, level, count: drawn.length,
      same: JSON.stringify(drawn.map((b: any) => [b.time, b.close])) === JSON.stringify(bricks.map(b => [b.time, b.close])),
      stepOfTarget: ends.findIndex(end => end > target),
      stepSize: (() => { const s = ends.findIndex(end => end > target); return ends[s] - (s === 0 ? start : ends[s - 1]); })(),
      brick: { time: bricks[target]?.time, close: bricks[target]?.close },
      close: at(close.id), touch: at(touch.id), every: at(every.id).map(e => e.index),
      expectedEvery: bricks.map((_, j) => j).filter(j => j >= start - 1 && j < bricks.length - 1 && crosses(level, j)),
      states: alerts.list().map((alert: any) => alert.state),
    };
  });
  expect(run.same).toBe(true);
  expect(run.target).toBeGreaterThanOrEqual(run.start);
  // The crossing brick formed with at least one more brick in the same update.
  expect(run.stepSize).toBeGreaterThanOrEqual(2);
  expect(run.close).toEqual([{ time: run.brick.time, index: run.target, price: run.brick.close }]);
  expect(run.touch).toEqual([{ time: run.brick.time, index: run.target, price: run.level }]);
  expect(run.states).toEqual(['triggered', 'triggered', 'armed']);
  // Every closed brick across the level is confirmed, the first at the target.
  expect(run.every).toEqual(run.expectedEvery);
  expect(run.every[0]).toBe(run.target);
  await page.screenshot({ path: info.outputPath('renko-replay-price-alert.png'), animations: 'disabled' });
  expect(errors).toEqual([]);
});
