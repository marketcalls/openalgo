import { test, expect, type Page } from '@playwright/test';

// What a live tick repaints, and how the glides use the animation frame, in a
// real browser (ARCHITECTURE.md §3.2).
//
// A tick that replaces the forming bar repaints the price pane and the panes
// of the studies computed from it, and leaves every other pane's canvases as
// they are. The unit tests count those paints. What only a browser can show is
// that the pixels the chart leaves alone are still right: after every tick,
// each canvas must match what a chart-wide repaint then paints over it, at a
// whole and at a fractional device scale, and with the axis chrome that reads
// the wall clock switched on.
//
// The glides step inside the render loop's frame. Every animation-frame
// request is counted per frame here, keyed by the timestamp all callbacks of
// one frame share, so a glide that asked for a second callback per frame
// would show up as a count of two.

/** Every canvas of every pane, as pixels, in pane order. */
async function canvases(page: Page): Promise<string[]> {
  return page.evaluate(() => {
    const chart = (window as any).__api.chart;
    return chart.panes().flatMap((pane: { element: HTMLElement }) =>
      [...pane.element.querySelectorAll('canvas')].map(canvas => (canvas as HTMLCanvasElement).toDataURL()));
  });
}

/** Wait until the chart has had two animation frames to paint what is pending. */
async function frames(page: Page): Promise<void> {
  await page.evaluate(() => new Promise<void>(done => requestAnimationFrame(() => requestAnimationFrame(() => done()))));
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize({ width: 1100, height: 760 });
  await page.goto('/');
  await page.waitForFunction(() => (window as any).__ready === true);
});

// At a whole and a fractional device scale: a pane painted alone has to land on
// the same device pixels as one painted with every other pane.
for (const scale of [1, 1.25]) {
  test.describe(`at a device scale of ${scale}`, () => {
    test.use({ deviceScaleFactor: scale });

    test('a live tick leaves every pane it does not repaint exactly as a full repaint paints it', async ({ page }, info) => {
      expect(await page.evaluate(() => window.devicePixelRatio)).toBe(scale);
      await page.evaluate(async () => {
        const { registerIndicator } = await import('/dist/openalgo-charts.mjs' as string);
        const api = (window as any).__api;
        registerIndicator({
          id: 'e2e-repaint-scope', name: 'Range', placement: 'pane', inputs: [],
          plots: [{ key: 'v', type: 'line', title: 'Range' }],
          calc: (input: { high: number; low: number }[]) => ({ v: input.map(bar => bar.high - bar.low) }),
        });
        api.chart.addIndicator('e2e-repaint-scope');
        // Paint counts per pane, by instance, so the bundle's own class is untouched.
        api.paints = api.chart.panes().map(() => 0);
        api.chart.panes().forEach((pane: any, i: number) => {
          const paint = pane.paintBase;
          pane.paintBase = function (...args: unknown[]) { api.paints[i]++; return paint.apply(this, args); };
        });
      });
      await frames(page);
      expect(await page.evaluate(() => (window as any).__api.chart.panes().length)).toBe(4);
      // Compared against repaints only: a line's very first paint can differ from
      // every later one by a pixel, in the published build as much as this one.
      await page.evaluate(() => (window as any).__api.chart.invalidate((m: any) => m.invalidateGlobal(3)));
      await frames(page);

      const tick = (kind: 'replace' | 'append', step: number) => page.evaluate(({ kind, step }) => {
        const api = (window as any).__api;
        const data = api.price.getData();
        const last = data[data.length - 1];
        api.paints.fill(0);
        // A new high past the range, then prices back inside it, so the price
        // scale has to re-measure both ways.
        const close = last.close + (step % 2 === 0 ? 9 : -4);
        const bar = kind === 'append'
          ? { time: last.time + 300, open: last.close, high: Math.max(last.close, close) + 1, low: Math.min(last.close, close) - 1, close }
          : { ...last, high: Math.max(last.high, close + 1), low: Math.min(last.low, close - 1), close };
        api.price.update(bar);
      }, { kind, step });

      const steps: ('replace' | 'append')[] = ['replace', 'replace', 'replace', 'append', 'replace', 'replace'];
      for (const [step, kind] of steps.entries()) {
        await tick(kind, step);
        await frames(page);
        const paints = await page.evaluate(() => [...(window as any).__api.paints]);
        if (kind === 'replace') {
          // The price pane and the study computed from it; the host's histogram
          // and line panes have nothing new to show.
          expect(paints, `paints after ${kind} ${step}`).toEqual([1, 0, 0, 1]);
        } else {
          expect(paints.every((n: number) => n >= 1), `paints after ${kind} ${step}`).toBe(true);
        }
        const local = await canvases(page);
        await page.evaluate(() => (window as any).__api.chart.invalidate((m: any) => m.invalidateGlobal(3)));
        await frames(page);
        const full = await canvases(page);
        expect(local.length).toBe(8);
        for (let i = 0; i < full.length; i++) expect(local[i] === full[i], `canvas ${i} after ${kind} ${step}`).toBe(true);
      }
      await info.attach(`after the ticks at ${scale}`, { body: await page.screenshot(), contentType: 'image/png' });
    });
  });
}

// The corner clock and the bar countdown have no timer: each reads the
// injected wall clock as its pane paints, and must show the new reading on a
// pane the tick does not write to. The clock sits in the corner of the bottom
// pane, a host line, and a tick to the price series leaves that pane alone.
// The countdown sits in the price source's tag, on the price pane, so there
// the tick goes to the host line at the bottom instead. The clock moves on
// before each tick.
for (const reading of ['sessionClock', 'barCountdown'] as const) {
  test(`a live tick keeps the ${reading} reading the time on a pane the tick does not write to`, async ({ page }) => {
    await page.evaluate(reading => {
      const api = (window as any).__api;
      const data = api.price.getData();
      // Inside the forming bar, so the countdown has a close to count to.
      api.clockAt = data[data.length - 1].time + 10;
      api.chart.setAxisChromeOptions({ [reading]: true, clock: () => api.clockAt });
      // A second host line on the bottom pane, for the countdown's ticks to write to.
      api.bottom = api.chart.addSeries('line', { paneIndex: 2, style: { color: '#7e57c2' } });
      api.bottom.setData(data.map((b: { time: number; close: number }) => ({ time: b.time, value: b.close % 40 + 30 })));
      api.paints = api.chart.panes().map(() => 0);
      api.chart.panes().forEach((pane: any, i: number) => {
        const paint = pane.paintBase;
        pane.paintBase = function (...args: unknown[]) { api.paints[i]++; return paint.apply(this, args); };
      });
    }, reading);
    await frames(page);
    expect(await page.evaluate(() => (window as any).__api.chart.panes().length)).toBe(3);
    for (let step = 1; step <= 3; step++) {
      await page.evaluate(([step, reading]) => {
        const api = (window as any).__api;
        api.clockAt += 7;
        api.paints.fill(0);
        if (reading === 'sessionClock') {
          const data = api.price.getData();
          const last = data[data.length - 1];
          api.price.update({ ...last, close: last.close + (step as number) / 10 });
        } else {
          const data = api.bottom.getData();
          const last = data[data.length - 1];
          api.bottom.update({ ...last, value: last.value + (step as number) / 10 });
        }
      }, [step, reading] as const);
      await frames(page);
      // The tick's pane, the reading's pane, and not the histogram between them.
      expect(await page.evaluate(() => [...(window as any).__api.paints]), `paints after tick ${step}`).toEqual([1, 0, 1]);
      const local = await canvases(page);
      await page.evaluate(() => (window as any).__api.chart.invalidate((m: any) => m.invalidateGlobal(3)));
      await frames(page);
      const full = await canvases(page);
      for (let i = 0; i < full.length; i++) expect(local[i] === full[i], `canvas ${i} after tick ${step}`).toBe(true);
    }
  });
}

test('a fling and a wheel-zoom glide ask for one animation frame per frame', async ({ page }) => {
  await page.evaluate(() => {
    const w = window as any;
    const original = window.requestAnimationFrame.bind(window);
    w.__frames = new Map<number, number>();
    w.__current = null;
    window.requestAnimationFrame = (cb: FrameRequestCallback): number => {
      if (w.__current !== null) w.__frames.set(w.__current, (w.__frames.get(w.__current) ?? 0) + 1);
      return original((t: number) => {
        w.__current = t;
        try { cb(t); } finally { w.__current = null; }
      });
    };
  });
  const settle = async (read: () => Promise<number>): Promise<void> => {
    let last = await read();
    for (let i = 0; i < 40; i++) {
      await page.waitForTimeout(100);
      const now = await read();
      if (now === last) return;
      last = now;
    }
    throw new Error('the glide did not settle');
  };
  const counts = () => page.evaluate(() => [...(window as any).__frames.values()] as number[]);
  const offset = () => page.evaluate(() => (window as any).__api.chart.timeScale.rightOffset as number);
  const spacing = () => page.evaluate(() => (window as any).__api.chart.timeScale.barSpacing as number);

  // A touch flick released while still moving, one move per frame: the view
  // keeps coasting. Only a touch release coasts; a mouse release places the
  // view where it is.
  const released = await page.evaluate(async () => {
    const host = document.getElementById('c')!;
    const touch = (type: string, x: number): void => {
      host.dispatchEvent(new PointerEvent(type, {
        bubbles: true, pointerId: 41, pointerType: 'touch', isPrimary: true, button: 0,
        buttons: type === 'pointerup' ? 0 : 1, clientX: x, clientY: 250,
      }));
    };
    const frame = (): Promise<void> => new Promise(done => requestAnimationFrame(() => done()));
    touch('pointerdown', 700);
    for (let x = 670; x >= 460; x -= 30) { await frame(); touch('pointermove', x); }
    touch('pointerup', 460);
    return (window as any).__api.chart.timeScale.rightOffset as number;
  });
  await page.evaluate(() => (window as any).__frames.clear());
  await settle(offset);
  expect(await offset()).not.toBe(released);
  const fling = await counts();
  expect(fling.length).toBeGreaterThan(5);
  expect(Math.max(...fling)).toBe(1);

  await page.evaluate(() => (window as any).__frames.clear());
  const before = await spacing();
  await page.mouse.move(500, 250);
  await page.mouse.wheel(0, -100);
  await settle(spacing);
  expect(await spacing()).toBeGreaterThan(before);
  const zoom = await counts();
  expect(zoom.length).toBeGreaterThan(3);
  expect(Math.max(...zoom)).toBe(1);
});
