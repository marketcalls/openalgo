import { test, expect } from '@playwright/test';

test('one group clock preserves scope, time and restoration in built charts', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', value => errors.push(String(value)));
  await page.setViewportSize({ width: 1000, height: 640 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const source = '/dist/openalgo-charts.mjs';
    const lib = await import(source);
    document.body.innerHTML = '<div id="controls"><button id="all">All charts</button>'
      + '<button id="focus">Focus second chart</button><button id="play">Play</button>'
      + '<button id="faster">Speed 2</button><button id="tick">Advance clock</button>'
      + '<button id="close">Close second chart</button></div>'
      + '<div id="fast" style="position:absolute;inset:32px 50% 0 0"></div>'
      + '<div id="slow" style="position:absolute;inset:32px 0 0 50%"></div>';
    const origin = 1700000000;
    const bars = (step: number, count: number) => Array.from({ length: count }, (_, index) => ({
      time: origin + step * index, open: 100 + index, high: 105 + index,
      low: 98 + index, close: 102 + index, volume: 100 + index,
    }));
    const charts = [lib.createChart(document.getElementById('fast')), lib.createChart(document.getElementById('slow'))];
    charts[0].addSeries('candlestick').setData(bars(60, 20));
    charts[1].addSeries('candlestick').setData(bars(300, 4));
    charts[0].timeScale.setBarSpacing(9); charts[0].timeScale.setRightOffset(3);
    let now = 0;
    const timers = new Set<() => void>();
    const group = new lib.ReplayGroup(charts.map((chart: any, index: number) => ({
      id: index ? 'slow' : 'fast', chart,
      options: { timing: { barEndTime: (bar: any) => bar.time + (index ? 300 : 60) } },
    })), { startTime: origin + 120, now: () => now,
      scheduler: (callback: () => void) => { timers.add(callback); return () => timers.delete(callback); } });
    document.getElementById('all')!.onclick = () => group.setScope('all');
    document.getElementById('focus')!.onclick = () => group.setScope('focused', 'slow');
    document.getElementById('play')!.onclick = () => group.play();
    document.getElementById('faster')!.onclick = () => group.play({ speed: 2 });
    document.getElementById('tick')!.onclick = () => {
      now += 1000 / group.state().speed;
      for (const callback of [...timers]) callback();
    };
    document.getElementById('close')!.onclick = () => charts[1].destroy();
    (window as any).__groupHarness = { group, charts, timers, origin };
  });
  const inspect = () => page.evaluate(() => {
    const { group, charts, timers, origin } = (window as any).__groupHarness;
    const state = group.state();
    return { counts: charts.map((chart: any) => chart.primaryBars().length), timers: timers.size,
      time: state.time - origin, scope: state.scope, active: state.active, destroyed: state.destroyed };
  });
  expect(await inspect()).toMatchObject({ counts: [2, 4], scope: 'focused', time: 120 });
  await page.locator('#all').click();
  expect(await inspect()).toMatchObject({ counts: [2, 0], scope: 'all', time: 120 });
  await page.locator('#play').click();
  for (let i = 0; i < 3; i++) await page.locator('#tick').click();
  expect(await inspect()).toMatchObject({ counts: [5, 1], timers: 1, time: 300 });
  await page.locator('#faster').click(); await page.locator('#tick').click();
  expect(await inspect()).toMatchObject({ counts: [6, 1], timers: 1, time: 360 });
  await page.locator('#focus').click(); await page.locator('#tick').click();
  expect(await inspect()).toMatchObject({ counts: [20, 2], timers: 1, time: 600, scope: 'focused' });
  await page.locator('#all').click();
  expect(await inspect()).toMatchObject({ counts: [10, 2], timers: 1, time: 600, scope: 'all' });
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await page.screenshot({ path: info.outputPath('replay-group-common-clock.png') });
  await page.locator('#close').click();
  const restored = await page.evaluate(() => {
    const { group, charts, timers } = (window as any).__groupHarness;
    return { active: group.state().active, destroyed: group.state().destroyed, timers: timers.size,
      bars: charts[0].primaryBars().length, spacing: charts[0].timeScale.barSpacing,
      offset: charts[0].timeScale.rightOffset, deadPanes: charts[1].panes().length };
  });
  expect(restored).toEqual({ active: false, destroyed: true, timers: 0, bars: 20, spacing: 9, offset: 3, deadPanes: 0 });
  expect(errors).toEqual([]);
});

test('different chart intervals expose only candles available at the replay clock', async ({ page }, info) => {
  await page.setViewportSize({ width: 1000, height: 600 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  const initial = await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const source = '/dist/openalgo-charts.mjs';
    const lib = await import(source);
    document.body.innerHTML = '<div id="fast" style="position:absolute;inset:0 50% 0 0"></div>'
      + '<div id="slow" style="position:absolute;inset:0 0 0 50%"></div>';
    const origin = 1700000000;
    const bars = (step: number, count: number) => Array.from({ length: count }, (_, index) => ({
      time: origin + step * index, open: 100 + index, high: 105 + index,
      low: 98 + index, close: 102 + index, volume: 100 + index,
    }));
    const charts = [lib.createChart(document.getElementById('fast')), lib.createChart(document.getElementById('slow'))];
    charts[0].addSeries('candlestick').setData(bars(60, 10));
    charts[1].addSeries('candlestick').setData(bars(300, 2));
    const controllers = charts.map((chart: any, index: number) => new lib.ReplayController(chart, {
      timing: { barEndTime: (bar: any) => bar.time + (index ? 300 : 60) }, startTime: origin + 120,
    }));
    (window as any).__timed = { charts, controllers, origin };
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return charts.map((chart: any) => chart.primaryBars().map((bar: any) => bar.time - origin));
  });
  expect(initial).toEqual([[0, 60], []]);
  await page.screenshot({ path: info.outputPath('replay-time-before-coarse-close.png') });
  const complete = await page.evaluate(async () => {
    const { charts, controllers, origin } = (window as any).__timed;
    controllers.forEach((controller: any) => controller.seekTime(origin + 300));
    await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    return charts.map((chart: any) => chart.primaryBars().map((bar: any) => bar.time - origin));
  });
  expect(complete).toEqual([[0, 60, 120, 180, 240], [0]]);
  await page.screenshot({ path: info.outputPath('replay-time-at-coarse-close.png') });
  expect(await page.evaluate(() => {
    const { charts, controllers } = (window as any).__timed;
    controllers.forEach((controller: any) => controller.stop());
    return charts.map((chart: any) => chart.primaryBars().length);
  })).toEqual([10, 2]);
});
