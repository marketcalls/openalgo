import { test, expect, type Page } from '@playwright/test';

async function mount(page: Page) {
  await page.setViewportSize({ width: 1200, height: 760 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const base = '/dist/openalgo-charts.mjs';
    const tier = '/dist/openalgo-charts.draw.mjs';
    const { createChart } = await import(base);
    const { DrawingController } = await import(tier);
    const chart = createChart(document.getElementById('c'), { priceAxisWidth: 64, timeAxisHeight: 28, timeNavigator: false });
    const bars = Array.from({ length: 100 }, (_, i) => {
      const close = 23800 + Math.sin(i / 8) * 160;
      return { time: 1750000000 + i * 86400, open: close - 20, high: close + 35, low: close - 40, close };
    });
    const series = chart.addSeries('candlestick');
    series.setData(bars);
    chart.setVisibleLogicalRange({ from: 0, to: 140 });
    const draw = new DrawingController(chart, { defaultStyle: { color: '#ff00ff', lineWidth: 3 } });
    let crosshair: unknown;
    chart.subscribeCrosshairMove((event: unknown) => { crosshair = event; });
    (window as any).__future = { chart, draw, series, bars, DrawingController, crosshair: () => crosshair };
  });
}

async function futureInk(page: Page) {
  return page.locator('#c canvas').nth(1).evaluate(canvas => {
    const c = canvas as HTMLCanvasElement;
    const dpr = c.width / c.getBoundingClientRect().width;
    const x = Math.round(850 * dpr);
    const pixels = c.getContext('2d')!.getImageData(x, 100 * dpr, 260 * dpr, 500 * dpr).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] > 180 && pixels[i + 1] < 90 && pixels[i + 2] > 180 && pixels[i + 3] > 80) ink++;
    }
    return ink;
  });
}

for (const tool of ['trend-line', 'rectangle']) {
  test(`${tool} previews, commits and remains editable beyond the latest candle`, async ({ page }, info) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await mount(page);
    await page.evaluate(id => (window as any).__future.draw.setTool(id), tool);
    await page.mouse.click(620, 220);
    await page.mouse.move(1040, 430, { steps: 12 });
    await page.screenshot({ path: info.outputPath('future-preview.png') });
    const hovered = await page.evaluate(() => (window as any).__future.crosshair());
    expect(hovered.time).toBeNull();
    expect(hovered.bar).toBeNull();
    await expect.poll(() => futureInk(page)).toBeGreaterThan(100);
    await page.mouse.click(1040, 430);
    expect(await page.evaluate(() => (window as any).__future.draw.drawings().length)).toBe(1);
    await page.mouse.move(1040, 430);
    await page.mouse.down();
    await page.mouse.move(1080, 450, { steps: 10 });
    await page.mouse.up();
    const endpoint = await page.evaluate(() => {
      const { chart, draw } = (window as any).__future;
      const point = draw.drawings()[0].points[1];
      return { x: chart.timeToCoordinate(point.time), y: chart.priceToCoordinate(point.price) };
    });
    expect(endpoint.x).toBeCloseTo(1080, 4);
    expect(endpoint.y).toBeCloseTo(450, 4);
    await page.evaluate(() => {
      const api = (window as any).__future;
      const saved = JSON.parse(JSON.stringify(api.draw.toJSON()));
      api.draw.destroy();
      api.draw = new api.DrawingController(api.chart);
      api.draw.fromJSON(saved);
      api.series.update({ ...api.bars.at(-1), time: api.bars.at(-1).time + 86400 });
    });
    await page.mouse.move(10, 10);
    await expect.poll(() => futureInk(page)).toBeGreaterThan(100);
    await page.screenshot({ path: info.outputPath('future-restored.png') });
    expect(errors).toEqual([]);
  });
}

test('freehand strokes can start and continue in future space', async ({ page }, info) => {
  await mount(page);
  await page.evaluate(() => (window as any).__future.draw.setTool('brush'));
  await page.mouse.move(880, 280);
  await page.mouse.down();
  await page.mouse.move(960, 220, { steps: 8 });
  await page.mouse.move(1060, 350, { steps: 8 });
  await page.mouse.up();
  await page.mouse.move(10, 10);
  await page.screenshot({ path: info.outputPath('future-freehand.png') });
  expect(await page.evaluate(() => (window as any).__future.draw.drawings().length)).toBe(1);
  await expect.poll(() => futureInk(page)).toBeGreaterThan(100);
});


test('saved drawings remain visible in future space and stay outside the price axis', async ({ page }, info) => {
  await mount(page);
  await page.evaluate(() => {
    const { draw, bars } = (window as any).__future;
    draw.add({ tool: 'trend-line', points: [
      { time: bars[80].time, price: 23700 },
      { time: bars[99].time + 65 * 86400, price: 23900 },
    ], style: { color: '#ff00ff', lineWidth: 4 }, paneIndex: 0 });
    draw.add({ tool: 'rectangle', points: [
      { time: bars[90].time, price: 23780 },
      { time: bars[99].time + 50 * 86400, price: 23830 },
    ], style: { color: '#ff00ff', lineWidth: 4 }, paneIndex: 0 });
    const saved = JSON.parse(JSON.stringify(draw.toJSON()));
    draw.fromJSON(saved);
  });
  await page.mouse.move(10, 10);
  await expect.poll(() => futureInk(page)).toBeGreaterThan(100);
  const axisInk = await page.locator('#c canvas').nth(1).evaluate(canvas => {
    const c = canvas as HTMLCanvasElement;
    const chart = (window as any).__future.chart;
    const dpr = c.width / c.getBoundingClientRect().width;
    const x = Math.ceil(chart.timeScale.width * dpr);
    const pixels = c.getContext('2d')!.getImageData(x, 0, c.width - x, c.height).data;
    let ink = 0;
    for (let i = 0; i < pixels.length; i += 4) {
      if (pixels[i] > 180 && pixels[i + 1] < 90 && pixels[i + 2] > 180 && pixels[i + 3] > 80) ink++;
    }
    return ink;
  });
  await page.screenshot({ path: info.outputPath('saved-future-axis.png') });
  expect(axisInk).toBe(0);
});

for (const placement of ['left', 'pane', 'left-only'] as const) {
  test(`selected drawings clip to the ${placement} plot and time-axis boundary`, async ({ page }, info) => {
    await mount(page);
    await page.evaluate(where => {
      const { chart, draw, bars } = (window as any).__future;
      const paneIndex = where === 'pane' ? 1 : 0;
      if (paneIndex) chart.addSeries('line', { paneIndex }).setData(bars);
      else if (where === 'left-only') chart.movePriceAxis(0, 'right', 'left');
      else chart.addSeries('line', { priceScaleId: 'left' }).setData(bars);
      const drawing = draw.add({ tool: 'trend-line', paneIndex, points: [
        { time: bars[0].time - 20 * 86400, price: 24000 },
        { time: bars[99].time + 65 * 86400, price: 23500 },
      ], style: { color: '#ff00ff', lineWidth: 4 } });
      draw.select(drawing.id);
    }, placement);
    await page.mouse.move(10, 10);
    const canvas = page.locator('#c canvas').nth(placement === 'pane' ? 3 : 1);
    const pixels = async () => canvas.evaluate((element, where) => {
      const c = element as HTMLCanvasElement;
      const chart = (window as any).__future.chart;
      const dpr = c.width / c.getBoundingClientRect().width;
      const left = where === 'pane' ? 0 : 64 * dpr;
      const right = left + chart.timeScale.width * dpr;
      const bottom = c.height - 28 * dpr;
      const pixels = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
      let plot = 0, outside = 0;
      for (let i = 0; i < pixels.length; i += 4) {
        if (pixels[i] > 180 && pixels[i + 1] < 90 && pixels[i + 2] > 180 && pixels[i + 3] > 80) {
          const x = (i / 4) % c.width, y = Math.floor((i / 4) / c.width);
          if (x < left || x >= right || y >= bottom) outside++; else plot++;
        }
      }
      return { plot, outside };
    }, placement);
    await expect.poll(async () => (await pixels()).plot).toBeGreaterThan(100);
    await page.screenshot({ path: info.outputPath(`selected-${placement}-axis.png`) });
    expect((await pixels()).outside).toBe(0);
  });
}


test('a future endpoint remains draggable after moving the primary scale left', async ({ page }) => {
  await mount(page);
  const start = await page.evaluate(() => {
    const { chart, draw, bars } = (window as any).__future;
    const drawing = draw.add({ tool: 'trend-line', paneIndex: 0, points: [
      { time: bars[40].time, price: 23880 },
      { time: bars[99].time + 21 * 86400, price: 23750 },
    ], style: { color: '#ff00ff', lineWidth: 4 } });
    chart.movePriceAxis(0, 'right', 'left');
    draw.select(drawing.id);
    const endpoint = drawing.points[1];
    return { x: chart.timeToCoordinate(endpoint.time), y: chart.priceToCoordinate(endpoint.price) };
  });
  await expect.poll(() => futureInk(page)).toBeGreaterThan(100);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + 40, start.y - 30, { steps: 8 });
  await page.mouse.up();
  const moved = await page.evaluate(() => {
    const { chart, draw } = (window as any).__future;
    const endpoint = draw.drawings()[0].points[1];
    return { x: chart.timeToCoordinate(endpoint.time), y: chart.priceToCoordinate(endpoint.price) };
  });
  // Browser pointer events may quantize coordinates to whole CSS pixels.
  expect(Math.abs(moved.x - (start.x + 40))).toBeLessThanOrEqual(1);
  expect(Math.abs(moved.y - (start.y - 30))).toBeLessThanOrEqual(1);
});

// Intraday bars in an IST cash session, 09:15 to 15:25 on 2026-02-02 (a
// Monday) through 2026-02-06 (Friday), so the space right of the last candle
// begins across a weekend.
const ist = (wall: string): number => Date.parse(`${wall}+05:30`) / 1000;

async function mountIntraday(page: Page, { calendar, mondayOpen }: { calendar: boolean; mondayOpen: boolean }) {
  await page.setViewportSize({ width: 1200, height: 760 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async ({ calendar, mondayOpen }) => {
    (window as any).__api.chart.destroy();
    const base = '/dist/openalgo-charts.mjs';
    const tier = '/dist/openalgo-charts.draw.mjs';
    const { createChart, SessionCalendar } = await import(base);
    const { DrawingController } = await import(tier);
    const chart = createChart(document.getElementById('c'), { priceAxisWidth: 64, timeAxisHeight: 28, timeNavigator: false });
    const times: number[] = [];
    for (const day of ['2026-02-02', '2026-02-03', '2026-02-04', '2026-02-05', '2026-02-06']) {
      const open = Date.parse(`${day}T09:15:00+05:30`) / 1000;
      for (let t = open; t <= open + 370 * 60; t += 300) times.push(t);
    }
    // Monday's opening bar last: the last gap is the whole weekend.
    if (mondayOpen) times.push(Date.parse('2026-02-09T09:15:00+05:30') / 1000);
    const bars = times.map((time, i) => {
      const close = 23800 + Math.sin(i / 12) * 60;
      return { time, open: close - 8, high: close + 14, low: close - 16, close };
    });
    const series = chart.addSeries('candlestick');
    series.setData(bars);
    if (calendar) chart.dataLayer.setSessionCalendar(new SessionCalendar({ timezone: 'Asia/Kolkata', sessions: ['0915-1530:23456'] }));
    const last = bars.length - 1;
    chart.setVisibleLogicalRange({ from: last - 60, to: last + 40 });
    const draw = new DrawingController(chart, { defaultStyle: { color: '#ff00ff', lineWidth: 3 } });
    (window as any).__future = { chart, draw, series, bars, last };
  }, { calendar, mondayOpen });
}

/** Magenta pixels right of the last candle inside the plot, and on the price axis, on the drawing layer. */
async function futureRegions(page: Page) {
  return page.locator('#c canvas').nth(1).evaluate(canvas => {
    const c = canvas as HTMLCanvasElement;
    const { chart, last } = (window as any).__future;
    const dpr = c.width / c.getBoundingClientRect().width;
    const future = Math.ceil((chart.timeScale.indexToX(last) + 6) * dpr);
    const right = Math.floor(chart.timeScale.width * dpr);
    const data = c.getContext('2d')!.getImageData(0, 0, c.width, c.height).data;
    let plot = 0, axis = 0;
    for (let i = 0; i < data.length; i += 4) {
      if (data[i] > 180 && data[i + 1] < 90 && data[i + 2] > 180 && data[i + 3] > 80) {
        const x = (i / 4) % c.width;
        if (x >= right) axis++;
        else if (x >= future) plot++;
      }
    }
    return { plot, axis };
  });
}

/** Page coordinates of a logical index and a price on the price pane. */
async function at(page: Page, index: number, price: number) {
  return page.evaluate(({ index, price }) => {
    const { chart } = (window as any).__future;
    const rect = document.getElementById('c')!.getBoundingClientRect();
    return { x: rect.left + chart.timeScale.indexToX(index), y: rect.top + chart.priceToCoordinate(price) };
  }, { index, price });
}

test('an intraday trend line drawn past Friday\'s close ends on Monday\'s session', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mountIntraday(page, { calendar: true, mondayOpen: false });
  const last = await page.evaluate(() => (window as any).__future.last as number);
  const from = await at(page, last - 20, 23820);
  // Twelve bars past Friday 15:25: Monday 09:15 is the first, so 10:10 the twelfth.
  const to = await at(page, last + 12, 23770);
  await page.evaluate(() => (window as any).__future.draw.setTool('trend-line'));
  await page.mouse.click(from.x, from.y);
  await page.mouse.move(to.x, to.y, { steps: 12 });
  await page.mouse.click(to.x, to.y);
  await page.mouse.move(5, 5);
  const points = await page.evaluate(() => (window as any).__future.draw.drawings()[0].points as { time: number; price: number }[]);
  // A click sits within half a CSS pixel of the bar's x: a small fraction of one five-minute bar.
  expect(Math.abs(points[1].time - ist('2026-02-09T10:10:00'))).toBeLessThan(60);
  expect(Math.abs(points[0].time - ist('2026-02-06T13:45:00'))).toBeLessThan(60);
  // Painted where it was placed, and inside the plot only.
  const drawnX = await page.evaluate(t => {
    const { chart } = (window as any).__future;
    return chart.timeToCoordinate(t) + document.getElementById('c')!.getBoundingClientRect().left;
  }, points[1].time);
  expect(Math.abs(drawnX - to.x)).toBeLessThanOrEqual(1);
  await expect.poll(async () => (await futureRegions(page)).plot).toBeGreaterThan(100);
  expect((await futureRegions(page)).axis).toBe(0);
  await page.screenshot({ path: info.outputPath('intraday-future-calendar.png') });
  expect(errors).toEqual([]);
});

test('saved anchors on Monday\'s session sit one bar past Friday\'s close and clip at the price axis', async ({ page }, info) => {
  await mountIntraday(page, { calendar: true, mondayOpen: false });
  const placed = await page.evaluate(() => {
    const { chart, draw, bars, last } = (window as any).__future;
    const monday = (wall: string) => Date.parse(`2026-02-09T${wall}:00+05:30`) / 1000;
    draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#ff00ff', lineWidth: 3 },
      points: [{ time: monday('09:15'), price: 23830 }, { time: monday('09:40'), price: 23790 }] });
    // 13:00 is 46 bars past the last one, beyond the 40 on screen: the line runs off the plot.
    draw.add({ tool: 'trend-line', paneIndex: 0, style: { color: '#ff00ff', lineWidth: 4 },
      points: [{ time: bars[last - 30].time, price: 23740 }, { time: monday('13:00'), price: 23860 }] });
    return {
      open: chart.dataLayer.timeToIndexFloat(monday('09:15')) - last,
      oneBar: chart.timeToCoordinate(monday('09:15')) - chart.timeScale.indexToX(last + 1),
      afternoon: chart.dataLayer.timeToIndexFloat(monday('13:00')) - last,
    };
  });
  expect(placed.open).toBe(1);
  expect(Math.abs(placed.oneBar)).toBeLessThan(0.5);
  expect(placed.afternoon).toBe(46);
  await page.mouse.move(5, 5);
  await expect.poll(async () => (await futureRegions(page)).plot).toBeGreaterThan(100);
  expect((await futureRegions(page)).axis).toBe(0);
  await page.screenshot({ path: info.outputPath('intraday-future-saved.png') });
});

test('without a calendar, a weekend in the last gap does not stretch the future', async ({ page }, info) => {
  await mountIntraday(page, { calendar: false, mondayOpen: true });
  const last = await page.evaluate(() => (window as any).__future.last as number);
  const from = await at(page, last - 10, 23800);
  const to = await at(page, last + 3, 23760);
  await page.evaluate(() => (window as any).__future.draw.setTool('trend-line'));
  await page.mouse.click(from.x, from.y);
  await page.mouse.move(to.x, to.y, { steps: 8 });
  await page.mouse.click(to.x, to.y);
  await page.mouse.move(5, 5);
  const end = await page.evaluate(() => (window as any).__future.draw.drawings()[0].points[1].time as number);
  // Three median bars after Monday 09:15, not three weekends.
  expect(Math.abs(end - ist('2026-02-09T09:30:00'))).toBeLessThan(60);
  await expect.poll(async () => (await futureRegions(page)).plot).toBeGreaterThan(50);
  expect((await futureRegions(page)).axis).toBe(0);
  await page.screenshot({ path: info.outputPath('intraday-future-median.png') });
});

// Hourly bars stamped on the clock at a venue with a lunch break, 09:00 to
// 11:30 and 12:30 to 15:00 UTC, 2026-02-02 (a Monday) through 2026-02-06: the
// afternoon's first bar is 12:00, half a bar before its opening, while the
// morning's is 09:00, on its opening.
const utc = (wall: string): number => Date.parse(`${wall}:00Z`) / 1000;

async function mountLunch(page: Page) {
  await page.setViewportSize({ width: 1200, height: 760 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready);
  await page.evaluate(async () => {
    (window as any).__api.chart.destroy();
    const base = '/dist/openalgo-charts.mjs';
    const tier = '/dist/openalgo-charts.draw.mjs';
    const { createChart, SessionCalendar } = await import(base);
    const { DrawingController } = await import(tier);
    const chart = createChart(document.getElementById('c'), { priceAxisWidth: 64, timeAxisHeight: 28, timeNavigator: false, timezone: 'UTC' });
    const times: number[] = [];
    for (const day of ['2026-02-02', '2026-02-03', '2026-02-04', '2026-02-05', '2026-02-06']) {
      for (const hour of ['09', '10', '11', '12', '13', '14']) times.push(Date.parse(`${day}T${hour}:00:00Z`) / 1000);
    }
    const bars = times.map((time, i) => {
      const close = 23800 + Math.sin(i / 3) * 60;
      return { time, open: close - 8, high: close + 14, low: close - 16, close };
    });
    const series = chart.addSeries('candlestick');
    series.setData(bars);
    const last = bars.length - 1;
    chart.setVisibleLogicalRange({ from: last - 20, to: last + 12 });
    const draw = new DrawingController(chart, { defaultStyle: { color: '#ff00ff', lineWidth: 3 } });
    const lunch = new SessionCalendar({ timezone: 'UTC', sessions: ['0900-1130:23456', '1230-1500:23456'] });
    (window as any).__future = { chart, draw, series, bars, last, lunch };
  });
}

/** Two animation frames, so anything a call asked to paint has painted. */
const frames = (page: Page) => page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));

test('past a lunch break each window keeps its own bar offset, and applying the hours repaints an idle chart', async ({ page }, info) => {
  const errors: string[] = [];
  page.on('pageerror', error => errors.push(error.message));
  await mountLunch(page);
  // A box on Monday morning, saved before the hours are known: without them
  // it sits about 70 median bars out, off screen.
  await page.evaluate(() => {
    const { draw } = (window as any).__future;
    const monday = (wall: string) => Date.parse(`2026-02-09T${wall}:00Z`) / 1000;
    draw.add({ tool: 'rectangle', paneIndex: 0, style: { color: '#ff00ff', lineWidth: 3 },
      points: [{ time: monday('09:00'), price: 23840 }, { time: monday('11:00'), price: 23780 }] });
  });
  await frames(page);
  expect((await futureRegions(page)).plot).toBe(0);
  // The hours arrive on an idle chart. Nothing else asks for a frame.
  await page.evaluate(() => { const { lunch, chart } = (window as any).__future; lunch.applyTo(chart); });
  await expect.poll(async () => (await futureRegions(page)).plot).toBeGreaterThan(100);
  expect((await futureRegions(page)).axis).toBe(0);
  const slots = await page.evaluate(() => {
    const { chart, last } = (window as any).__future;
    const at = (wall: string) => chart.dataLayer.timeToIndexFloat(Date.parse(`${wall}:00Z`) / 1000) - last;
    return [at('2026-02-09T09:00'), at('2026-02-09T10:00'), at('2026-02-09T11:00'), at('2026-02-09T12:00'),
      at('2026-02-09T14:00'), at('2026-02-10T09:00')];
  });
  expect(slots).toEqual([1, 2, 3, 4, 6, 7]);
  // A trend line clicked two bars past Friday's last candle ends on Monday 10:00.
  const from = await at(page, (await page.evaluate(() => (window as any).__future.last)) - 8, 23820);
  const to = await at(page, (await page.evaluate(() => (window as any).__future.last)) + 2, 23770);
  await page.evaluate(() => (window as any).__future.draw.setTool('trend-line'));
  await page.mouse.click(from.x, from.y);
  await page.mouse.move(to.x, to.y, { steps: 8 });
  await page.mouse.click(to.x, to.y);
  await page.mouse.move(5, 5);
  const end = await page.evaluate(() => (window as any).__future.draw.drawings()[1].points[1].time as number);
  // Half a CSS pixel of a click is a small fraction of one hourly bar.
  expect(Math.abs(end - utc('2026-02-09T10:00'))).toBeLessThan(120);
  await page.screenshot({ path: info.outputPath('lunch-future-calendar.png') });
  expect(errors).toEqual([]);
});
