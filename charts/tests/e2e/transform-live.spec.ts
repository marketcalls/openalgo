import { test, expect, type Page } from '@playwright/test';

/**
 * In-chart transforms in real browser pixels. Unit tests prove the elements a
 * run forms after every tick; this proves the chart paints them live: a tick
 * on the forming bar draws the bricks it completes, a tick back takes them
 * off the canvas again, and a closed bar keeps its bricks. Each transformed
 * chart type is also captured once per browser for a person to look at.
 */

interface Element { time: number; open: number; close: number }

async function ready(page: Page, query: string): Promise<void> {
  await page.setViewportSize({ width: 1100, height: 620 });
  await page.goto(`/tests/e2e/transform-live-fixture.html?${query}`);
  await page.waitForFunction(() => (window as any).__ready);
}

/** The chart's elements after the next painted frame. */
async function elements(page: Page): Promise<Element[]> {
  return page.evaluate(async () => { await (window as any).__frame(); return (window as any).__probe.elements(); });
}

/**
 * The colour painted at an element's body centre, read off the chart's own
 * capture, as `[r, g, b]` in device pixels.
 */
async function bodyColour(page: Page, element: Element): Promise<number[]> {
  return page.evaluate(async (el) => {
    const { chart } = (window as any).__probe;
    await (window as any).__frame();
    const shot = chart.takeScreenshot() as HTMLCanvasElement;
    const dpr = devicePixelRatio;
    const x = Math.round(chart.timeToCoordinate(el.time) * dpr);
    const y = Math.round(chart.priceToCoordinate((el.open + el.close) / 2) * dpr);
    return [...shot.getContext('2d')!.getImageData(x, y, 1, 1).data.slice(0, 3)];
  }, element);
}

const hex = (colour: string): number[] => [1, 3, 5].map(i => parseInt(colour.slice(i, i + 2), 16));
const near = (a: number[], b: number[]): boolean => a.every((v, i) => Math.abs(v - b[i]) <= 24);

test.describe('in-chart transforms', () => {
  test('ticks a Renko chart live, brick by brick', async ({ page }, testInfo) => {
    await ready(page, 'type=renko&study=chart');
    const theme = await page.evaluate(() => { const { lib } = (window as any).__probe; return { up: lib.darkTheme.upColor, down: lib.darkTheme.downColor }; });
    const box = 2;
    const history = await elements(page);
    expect(history.length).toBeGreaterThan(40);
    const edge = history[history.length - 1].close;

    // A new bar opens and ticks up through three boxes: three bricks form on it.
    await page.evaluate(() => (window as any).__probe.open());
    await page.evaluate((price) => (window as any).__probe.tick(price), edge + box * 3.4);
    const up = await elements(page);
    expect(up.slice(0, history.length)).toEqual(history);
    expect(up.length).toBe(history.length + 3);
    const newest = up[up.length - 1];
    expect(newest.close - newest.open).toBeCloseTo(box, 6);
    expect(near(await bodyColour(page, newest), hex(theme.up))).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('renko-forming.png') });

    // The same bar falls back inside the box it opened in: those bricks were
    // only ever provisional, and leave the chart with the price.
    await page.evaluate((price) => (window as any).__probe.tick(price), edge + box * 0.5);
    const back = await elements(page);
    expect(back).toEqual(history);
    expect(near(await bodyColour(page, newest), hex(theme.up))).toBe(false);

    // It closes two boxes down, and the next bar opens: the down bricks stay.
    await page.evaluate((price) => (window as any).__probe.tick(price), edge - box * 2.2);
    await page.evaluate(() => (window as any).__probe.open());
    const closed = await elements(page);
    expect(closed.length).toBe(history.length + 2);
    const down = closed[closed.length - 1];
    expect(down.open - down.close).toBeCloseTo(box, 6);
    expect(near(await bodyColour(page, down), hex(theme.down))).toBe(true);
    await page.evaluate((price) => (window as any).__probe.tick(price), edge - box * 1.9);
    expect(await elements(page)).toEqual(closed);
    // The host's own bars are what the series still holds.
    expect(await page.evaluate(() => (window as any).__probe.lastSource().close)).toBeCloseTo(edge - box * 1.9, 6);
  });

  test('fires a crossing alert once per brick on a replayed Renko chart', async ({ page }, testInfo) => {
    await ready(page, 'type=renko&study=none');
    const run = await page.evaluate(async () => {
      const { chart, series, lib } = (window as any).__probe;
      // A five-brick average of the brick closes, and two alerts: one on every
      // new brick, one on a brick that closes across the average.
      const average = (c: number[]) => c.map((_, i) => i < 4 ? null : c.slice(i - 4, i + 1).reduce((sum, x) => sum + x, 0) / 5);
      const side = (bars: any[], avg: (number | null)[], i: number) => avg[i] == null ? 0 : Math.sign(bars[i].close - avg[i]!);
      const crossed = (bars: any[], avg: (number | null)[], i: number) =>
        i > 0 && side(bars, avg, i - 1) * side(bars, avg, i) === -1;
      lib.registerIndicator({
        id: 'e2e-brick-cross', name: 'Brick cross', placement: 'onchart', inputs: [],
        plots: [{ key: 'avg', type: 'line', title: 'Average', style: { color: '#f5a623', lineWidth: 2 } }],
        calc: (bars: any[]) => ({ avg: average(bars.map(b => b.close)) }),
        alerts: [
          { id: 'brick', title: 'New brick', when: () => true },
          { id: 'cross', title: 'Crossed the average', when: ({ bars, values, index }: any) => crossed(bars, values.avg, index) },
        ],
      });
      chart.addIndicator('e2e-brick-cross');
      const events: { id: string; time: number; index: number }[] = [];
      chart.on('indicator:alert', (e: any) => events.push({ id: e.alertId, time: e.time, index: e.index }));
      const start = chart.primaryBars().length;
      // Seven more hours replayed bar by bar, as a feed delivers them: a seeded
      // continuation of the session's random walk. Each bar is one update, and
      // a bar that moves more than a box completes several bricks at once.
      let seed = 20261001;
      const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
      const gauss = () => Math.sqrt(-2 * Math.log(random() || 1e-9)) * Math.cos(2 * Math.PI * random());
      let last = series.getData().at(-1);
      const steps: number[] = [];
      for (let i = 0; i < 84; i++) {
        const open = last.close;
        const close = Math.round(open * (1 + gauss() * 0.0019) * 20) / 20;
        const bar = { time: last.time + 300, open, close, high: Math.max(open, close), low: Math.min(open, close), volume: 50000 };
        const before = chart.primaryBars().length;
        series.update(bar);
        await (window as any).__frame();
        steps.push(chart.primaryBars().length - before);
        last = bar;
      }
      const bricks = chart.primaryBars();
      const avg = chart.indicators()[0].values().avg;
      // Each brick formed once and never changed, so the final bricks say what
      // each alert should have judged.
      const expected = bricks.map((_: unknown, i: number) => i).filter((i: number) => i >= start && crossed(bricks, avg, i));
      const cross = events.filter(e => e.id === 'cross');
      series.createMarkers().setMarkers(cross.map(e => {
        const up = bricks[e.index].close > avg[e.index]!;
        return { time: e.time, position: up ? 'belowBar' : 'aboveBar', shape: up ? 'arrowUp' : 'arrowDown', size: 'small',
          color: up ? '#26a69a' : '#ef5350', text: up ? 'Up' : 'Down' };
      }));
      // The brick each replayed bar completed last, so a brick before it formed in the same step.
      const lastOfStep = new Set<number>();
      steps.reduce((at, k) => { if (k > 0) lastOfStep.add(at + k - 1); return at + k; }, start);
      // The replayed bricks and a few before them, wide enough to read.
      chart.setVisibleLogicalRange({ from: start - 8, to: bricks.length + 2 });
      await (window as any).__frame();
      return {
        start, count: bricks.length, steps, expected,
        brick: events.filter(e => e.id === 'brick').map(e => e.index),
        cross: cross.map(e => e.index),
        timesMatch: events.every(e => bricks[e.index].time === e.time),
        crossInsideStep: cross.filter(e => !lastOfStep.has(e.index)).length,
      };
    });
    expect(run.steps.filter(k => k >= 2).length).toBeGreaterThan(3);
    // Every brick the replay formed is judged once, in order, including those
    // that formed two or more to a bar.
    expect(run.brick).toEqual(Array.from({ length: run.count - run.start }, (_, i) => run.start + i));
    expect(run.cross).toEqual(run.expected);
    expect(run.cross.length).toBeGreaterThan(4);
    expect(run.crossInsideStep).toBeGreaterThan(0);
    expect(run.timesMatch).toBe(true);
    await page.screenshot({ path: testInfo.outputPath('renko-replay-alerts.png') });
  });

  test('fires a crossing alert once per vertex on a replayed Kagi chart', async ({ page }, testInfo) => {
    await ready(page, 'type=kagi&study=none');
    const run = await page.evaluate(async () => {
      const { chart, series, lib } = (window as any).__probe;
      // A five-vertex average of the vertex prices, an alert on every new
      // vertex, and one when a new vertex confirms a turning point that sits
      // across the average from the one before it. The turning point is final
      // once the line has left it, so each mark can be checked by eye.
      const average = (c: number[]) => c.map((_, i) => i < 4 ? null : c.slice(i - 4, i + 1).reduce((sum, x) => sum + x, 0) / 5);
      const side = (bars: any[], avg: (number | null)[], i: number) => avg[i] == null ? 0 : Math.sign(bars[i].close - avg[i]!);
      const crossed = (bars: any[], avg: (number | null)[], i: number) =>
        i > 0 && side(bars, avg, i - 1) * side(bars, avg, i) === -1;
      lib.registerIndicator({
        id: 'e2e-vertex-cross', name: 'Vertex cross', placement: 'onchart', inputs: [],
        plots: [{ key: 'avg', type: 'line', title: 'Average', style: { color: '#f5a623', lineWidth: 2 } }],
        calc: (bars: any[]) => ({ avg: average(bars.map(b => b.close)) }),
        alerts: [
          { id: 'vertex', title: 'New vertex', when: () => true },
          { id: 'cross', title: 'Turned across the average', when: ({ bars, values, index }: any) => crossed(bars, values.avg, index - 1) },
        ],
      });
      chart.addIndicator('e2e-vertex-cross');
      const events: { id: string; time: number; index: number }[] = [];
      chart.on('indicator:alert', (e: any) => events.push({ id: e.alertId, time: e.time, index: e.index }));
      const start = chart.primaryBars().length;
      // Seven more hours replayed bar by bar, a seeded continuation of the
      // session's random walk. Each bar dates the vertex still forming again,
      // and a bar that turns the line adds a vertex after it.
      let seed = 20261001;
      const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
      const gauss = () => Math.sqrt(-2 * Math.log(random() || 1e-9)) * Math.cos(2 * Math.PI * random());
      let last = series.getData().at(-1);
      // What separate appends would judge: each vertex a bar added, once, at
      // the time it had then, on the vertices and the average as they stood.
      const expected = { vertex: [] as { index: number; time: number }[], cross: [] as { index: number; time: number }[] };
      let redated = 0;
      for (let i = 0; i < 84; i++) {
        const open = last.close;
        const close = Math.round(open * (1 + gauss() * 0.0019) * 20) / 20;
        const bar = { time: last.time + 300, open, close, high: Math.max(open, close), low: Math.min(open, close), volume: 50000 };
        const before = chart.primaryBars().map((v: any) => v.time);
        series.update(bar);
        await (window as any).__frame();
        const now = chart.primaryBars();
        if (now[before.length - 1].time > before[before.length - 1]) redated++;
        const avg = average(now.map((v: any) => v.close));
        for (let k = before.length; k < now.length; k++) {
          expected.vertex.push({ index: k, time: now[k].time });
          if (crossed(now, avg, k - 1)) expected.cross.push({ index: k, time: now[k].time });
        }
        last = bar;
      }
      const vertices = chart.primaryBars();
      const avg = chart.indicators()[0].values().avg;
      // The same turning points read off the final vertices: the ones the marks show.
      const turns = vertices.map((_: unknown, j: number) => j).filter((j: number) => j >= start - 1 && j < vertices.length - 1 && crossed(vertices, avg, j));
      const pick = (id: string) => events.filter(e => e.id === id).map(e => ({ index: e.index, time: e.time }));
      series.createMarkers().setMarkers(events.filter(e => e.id === 'cross').map(e => {
        const turn = vertices[e.index - 1], up = turn.close > avg[e.index - 1]!;
        return { time: turn.time, position: up ? 'aboveBar' : 'belowBar', shape: up ? 'arrowUp' : 'arrowDown', size: 'small',
          color: up ? '#26a69a' : '#ef5350', text: up ? 'Up' : 'Down' };
      }));
      chart.setVisibleLogicalRange({ from: start - 6, to: vertices.length + 1 });
      await (window as any).__frame();
      return { start, count: vertices.length, redated, expected, turns, vertex: pick('vertex'), cross: pick('cross') };
    });
    // Nearly every bar dates the forming vertex again, and the line turned many times.
    expect(run.redated).toBeGreaterThan(70);
    expect(run.count - run.start).toBeGreaterThan(8);
    // Every vertex the replay formed is judged once, in order, at the time it had then.
    expect(run.vertex.map(e => e.index)).toEqual(Array.from({ length: run.count - run.start }, (_, i) => run.start + i));
    expect(run.vertex).toEqual(run.expected.vertex);
    expect(run.cross).toEqual(run.expected.cross);
    expect(run.cross.map(e => e.index - 1)).toEqual(run.turns);
    expect(run.cross.length).toBeGreaterThan(2);
    await page.screenshot({ path: testInfo.outputPath('kagi-replay-alerts.png') });
  });

  // Each transform that is not one element per bar. Kagi, range bars and point
  // and figure keep an element forming that reads the newest bar; Renko and
  // line break do not.
  for (const type of ['renko', 'line-break', 'range-bars', 'point-figure', 'kagi']) {
    test(`delivers a study alert once per bar under a replayed ${type} chart`, async ({ page }, testInfo) => {
      await ready(page, `type=${type}&study=none`);
      const run = await page.evaluate(async (forming) => {
        const { chart, series, lib } = (window as any).__probe;
        // A study on the five-minute bars under the elements: a five-bar average
        // of their closes to draw, and an alert on a bar that closes above its
        // open at each frequency, naming the bar it read. Each element reads the
        // bar it was completed on, so the elements of one bar all read that bar.
        const average = (c: number[]) => c.map((_, i) => i < 4 ? null : c.slice(i - 4, i + 1).reduce((sum, x) => sum + x, 0) / 5);
        const rising = { when: ({ values, index }: any) => values.up[index] === 1, message: ({ values, index }: any) => String(values.at[index]) };
        lib.registerIndicator({
          id: 'e2e-underlying-rise', name: 'Underlying rise', placement: 'onchart', inputs: [],
          plots: [{ key: 'avg', type: 'line', title: 'Average', style: { color: '#f5a623', lineWidth: 2 } }],
          calc: (bars: any[]) => ({ avg: average(bars.map(b => b.close)), up: bars.map(b => b.close > b.open ? 1 : 0), at: bars.map(b => b.time) }),
          alerts: [
            { id: 'omitted', title: 'Rising bar', ...rising },
            { id: 'oncePerBar', title: 'Rising bar, once per bar', frequency: 'oncePerBar', ...rising },
            { id: 'everyUpdate', title: 'Rising bar, every update', frequency: 'everyUpdate', ...rising },
          ],
        });
        chart.addIndicator('e2e-underlying-rise', {}, { barSource: 'underlying' });
        const events: { id: string; time: number; index: number; message: string }[] = [];
        chart.on('indicator:alert', (e: any) => events.push({ id: e.alertId, time: e.time, index: e.index, message: e.message }));
        const start = chart.primaryBars().length;
        // Seven more hours replayed bar by bar, a seeded continuation of the
        // session's random walk, each bar one update as a feed delivers it.
        let seed = 20261001;
        const random = () => { seed = (seed * 16807) % 2147483647; return seed / 2147483647; };
        const gauss = () => Math.sqrt(-2 * Math.log(random() || 1e-9)) * Math.cos(2 * Math.PI * random());
        let last = series.getData().at(-1);
        // A rising bar that added an element is delivered once, at the first
        // element it added. An alert with a frequency also judges a bar that
        // only moved the element still forming, which reads it, and none that
        // no element reads.
        const expected: { index: number; time: number; message: string }[] = [];
        const explicit: typeof expected = [];
        let risingSteps = 0;
        for (let i = 0; i < 84; i++) {
          const open = last.close;
          const close = Math.round(open * (1 + gauss() * 0.0019) * 20) / 20;
          const bar = { time: last.time + 300, open, close, high: Math.max(open, close), low: Math.min(open, close), volume: 50000 };
          const before = chart.primaryBars().length;
          series.update(bar);
          await (window as any).__frame();
          const bricks = chart.primaryBars(), at = bricks.length > before ? before : forming ? before - 1 : -1;
          if (close > open && bricks.length > before) expected.push({ index: before, time: bricks[before].time, message: String(bar.time) });
          if (close > open && at >= 0) explicit.push({ index: at, time: bricks[at].time, message: String(bar.time) });
          if (close > open && bricks.length > before + 1) risingSteps++;
          last = bar;
        }
        const pick = (id: string) => events.filter(e => e.id === id).map(({ index, time, message }) => ({ index, time, message }));
        // At the element's time now: a newer bar dates a forming Kagi vertex or range bar again.
        const final = chart.primaryBars();
        series.createMarkers().setMarkers(pick('omitted').map(e => ({
          time: final[e.index].time, position: 'belowBar', shape: 'arrowUp', size: 'small', color: '#26a69a', text: 'Up',
        })));
        chart.setVisibleLogicalRange({ from: start - 8, to: chart.primaryBars().length + 2 });
        await (window as any).__frame();
        return { expected, explicit, risingSteps, omitted: pick('omitted'), oncePerBar: pick('oncePerBar'), everyUpdate: pick('everyUpdate') };
      }, ['kagi', 'range-bars', 'point-figure'].includes(type));
      // On Renko, rising bars that completed two bricks or more: each once, not once per brick.
      if (type === 'renko') expect(run.risingSteps).toBeGreaterThan(3);
      expect(run.expected.length).toBeGreaterThan(2);
      expect(run.omitted).toEqual(run.expected);
      expect(run.oncePerBar).toEqual(run.explicit);
      expect(run.everyUpdate).toEqual(run.explicit);
      await page.screenshot({ path: testInfo.outputPath(`${type}-underlying-alerts.png`) });
    });
  }

  for (const type of ['heikin-ashi', 'renko', 'range-bars', 'line-break', 'point-figure', 'kagi']) {
    test(`draws a ${type} chart`, async ({ page }, testInfo) => {
      await ready(page, `type=${type}`);
      const drawn = await elements(page);
      expect(drawn.length).toBeGreaterThan(type === 'kagi' || type === 'point-figure' ? 8 : 40);
      // Something other than the background is painted inside the plot.
      const painted = await page.evaluate(() => {
        const { chart, lib } = (window as any).__probe;
        const shot = chart.takeScreenshot() as HTMLCanvasElement, plot = chart.plotRect(0), dpr = devicePixelRatio;
        const data = shot.getContext('2d')!.getImageData(plot.left * dpr, plot.top * dpr, plot.width * dpr, plot.height * dpr).data;
        const bg = [1, 3, 5].map(i => parseInt(lib.darkTheme.background.slice(i, i + 2), 16));
        let count = 0;
        for (let i = 0; i < data.length; i += 4) if (Math.abs(data[i] - bg[0]) + Math.abs(data[i + 1] - bg[1]) + Math.abs(data[i + 2] - bg[2]) > 60) count++;
        return count / (data.length / 4);
      });
      expect(painted).toBeGreaterThan(0.01);
      await page.screenshot({ path: testInfo.outputPath(`${type}.png`) });
    });
  }

  test('picks Renko from the widget chart type menu and ticks it live', async ({ page }, testInfo) => {
    await page.setViewportSize({ width: 1200, height: 700 });
    await page.goto('/tests/e2e/widget-transform-fixture.html');
    await page.waitForFunction(() => (window as any).fixture?.widget.chart.primaryBars().length === 300);
    await page.click('.oac-topbar__type');
    const menu = page.locator('.oac-menu[role="menu"]');
    for (const name of ['Heikin Ashi', 'Renko', 'Range bars', 'Line break', 'Point and figure', 'Kagi']) {
      await expect(menu.getByRole('menuitemradio', { name, exact: true })).toBeVisible();
    }
    await page.screenshot({ path: testInfo.outputPath('widget-type-menu.png') });
    await menu.getByRole('menuitemradio', { name: 'Kagi', exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath('widget-type-menu-end.png') });
    await menu.getByRole('menuitemradio', { name: 'Renko', exact: true }).click();
    const state = () => page.evaluate(async () => {
      const { widget } = (window as any).fixture;
      await (window as any).__frame();
      const bricks = widget.chart.primaryBars();
      return { type: widget.chartType(), transform: widget.chart.seriesTransform(widget.series), count: bricks.length,
        last: bricks[bricks.length - 1], box: Math.abs(bricks[0].close - bricks[0].open), label: document.querySelector('.oac-topbar__type')?.textContent };
    });
    const renko = await state();
    expect(renko).toMatchObject({ type: 'renko', transform: { type: 'renko' } });
    expect(renko.label).toContain('Renko');
    expect(renko.count).toBeGreaterThan(20);
    // A live bar through three and a half boxes: three bricks form on it.
    await page.evaluate(({ price }) => (window as any).fixture.live(price, true), { price: renko.last.close + renko.box * 3.5 });
    const ticked = await state();
    expect(ticked.count).toBe(renko.count + 3);
    await page.screenshot({ path: testInfo.outputPath('widget-renko.png') });
    // Back inside the box it opened in: the provisional bricks go.
    await page.evaluate(({ price }) => (window as any).fixture.live(price), { price: renko.last.close + renko.box * 0.2 });
    expect((await state()).count).toBe(renko.count);
  });
});
