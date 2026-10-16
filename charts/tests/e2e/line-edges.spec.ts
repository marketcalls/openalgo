import { test, expect, type Page } from '@playwright/test';

// A line-family series draws the segment that crosses an edge of the view to
// the series' nearest bar beyond it (src/render/draw-items.ts, `edges`), cut
// at the view before it is stroked (src/render/line.ts, `trimToView`). Unit
// tests check the path the renderers ask for; this checks what the browsers
// actually paint, on both backends:
//
//  - The sparse case the edges exist for: a level held across the view with
//    none, or one, of its bars in it reaches both edges of the plot.
//  - The dash phase: a dashed or dotted line paints the same pixels from its
//    first bar in view on as the same line with nothing beyond the view, so
//    drawing the edge segment moved no dash of the visible line.
//  - A gap at the edge: when the bar on either side of an edge has no value,
//    a line, area, baseline or band paints exactly what it paints with
//    nothing beyond the view; no fill reaches out from the plot edge.
//  - The cost of a neighbour millions of pixels away: the GPU backend walked
//    a dashed segment's pattern over its whole length in script, frame after
//    frame, and uploaded a quad for every dash.
//
// The chart paints nothing in an OFF-SCREEN container, so every chart here is
// built visibly at the origin, one at a time, and destroyed before the next.

const W = 900;
const H = 520;
/** The level's colour: no candle, grid or axis paints it. */
const LEVEL = '#ffcc00';

/** Whether a WebGL2 context comes up and stays up in this browser. */
async function webgl2(page: Page): Promise<boolean> {
  return page.evaluate(async () => {
    const frame = (): Promise<void> => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
    for (let attempt = 0; attempt < 20; attempt++) {
      const gl = document.createElement('canvas').getContext('webgl2');
      if (gl === null) return false;
      await frame();
      if (!gl.isContextLost()) return true;
    }
    return false;
  });
}

/**
 * Installed in the page: five-second bars as a seeded random walk whose
 * volatility comes in clusters, in sessions with an overnight gap between them,
 * and a chart factory that builds visibly at the origin.
 */
async function install(page: Page): Promise<void> {
  await page.evaluate(async () => {
    const w = window as unknown as Record<string, unknown>;
    w.oacBase = await import('/dist/openalgo-charts.mjs');
    w.oacGl = await import('/dist/openalgo-charts.webgl.mjs');
    w.oacBars = (count: number, seed: number): unknown[] => {
      let s = seed >>> 0;
      const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
      const out: unknown[] = [];
      const session = 4_500; // 09:15 to 15:30 in five-second bars
      let t = 1_758_000_000, p = 24_800, vol = 2;
      for (let i = 0; i < count; i++) {
        if (i > 0 && i % session === 0) {
          t += 17.75 * 3600; // overnight
          p += (rnd() - 0.5) * 60; // and the gap it opens with
        }
        // Volatility clusters: it drifts and now and then jumps.
        vol = Math.min(9, Math.max(0.8, vol * (0.97 + rnd() * 0.06) + (rnd() < 0.002 ? 5 : 0)));
        const o = p;
        p += (rnd() - 0.5) * vol;
        out.push({ time: t, open: o, high: Math.max(o, p) + rnd() * vol * 0.6, low: Math.min(o, p) - rnd() * vol * 0.6, close: p });
        t += 5;
      }
      return out;
    };
  });
}

test('a sparse level reaches both edges of the plot with none or one of its bars in view', async ({ page }) => {
  test.setTimeout(120_000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('/');
  await page.setViewportSize({ width: W + 40, height: H + 40 });
  const gl = await webgl2(page);
  await install(page);

  const report = await page.evaluate(async ({ w, h, level, renderers }) => {
    type Chart = {
      addSeries: (t: string, o?: unknown) => { setData: (b: unknown[]) => void };
      applySize: (w: number, h: number) => void; destroy: () => void; readonly rendererKind: string;
      timeScale: { setBarSpacing: (n: number) => void; setRightOffset: (n: number) => void; readonly width: number; indexToX: (i: number) => number };
    };
    const g = window as unknown as { oacBase: { createChart: (el: HTMLElement, o?: unknown) => Chart }; oacBars: (n: number, s: number) => { time: number; close: number }[] };
    const bars = g.oacBars(20_000, 41);
    const frame = (): Promise<void> => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
    /** A price `at` of the way up the closes of bars `from` to `to`, so the level is on screen. */
    const within = (from: number, to: number, at: number): number => {
      let lo = Infinity, hi = -Infinity;
      for (let i = from; i <= to; i++) { lo = Math.min(lo, bars[i].close); hi = Math.max(hi, bars[i].close); }
      return lo + (hi - lo) * at;
    };
    const out: { label: string; kind: string; covered: number; plot: number; dashes: number; firstCol: number; lastCol: number }[] = [];
    for (const renderer of renderers) {
      for (const [label, rightIndex, lineStyle] of [
        ['no bar in view', 6_000, 'solid'], ['one bar in view', 9_060, 'solid'], ['no bar in view, dashed', 6_000, 'dashed'],
      ] as const) {
        const host = document.createElement('div');
        host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
        document.body.appendChild(host);
        const chart = g.oacBase.createChart(host, { priceAxisWidth: 64, renderer });
        chart.applySize(w, h);
        chart.addSeries('candlestick').setData(bars);
        // A position's average price: set at bar 2,000, moved at 9,000 and
        // again at 16,000, at prices the candles in view reach.
        const view = [rightIndex - 130, rightIndex] as const;
        const steps = [[2_000, within(...view, 0.3)], [9_000, within(...view, 0.7)], [16_000, within(...view, 0.5)]];
        chart.addSeries('step', { style: { color: level, lineWidth: 2, lineStyle } }).setData(
          steps.map(([i, p]) => ({ time: bars[i].time, open: p, high: p, low: p, close: p })),
        );
        chart.timeScale.setBarSpacing(6);
        chart.timeScale.setRightOffset(rightIndex - (bars.length - 1));
        await frame();
        const canvas = host.querySelector('canvas') as HTMLCanvasElement;
        const ratio = canvas.width / w;
        const plot = Math.floor(chart.timeScale.width * ratio);
        const d = (canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D).getImageData(0, 0, canvas.width, canvas.height).data;
        const isLevel = (i: number): boolean => d[i] > 200 && d[i + 1] > 160 && d[i + 2] < 90;
        // Columns of the plot with the level's colour anywhere in them, and
        // the most on/off changes along any one row (a dashed level's).
        let covered = 0, firstCol = -1, lastCol = -1;
        for (let x = 0; x < plot; x++) {
          for (let y = 0; y < canvas.height; y++) {
            if (isLevel((y * canvas.width + x) * 4)) {
              covered++;
              if (firstCol < 0) firstCol = x;
              lastCol = x;
              break;
            }
          }
        }
        let dashes = 0;
        for (let y = 0; y < canvas.height; y++) {
          let runs = 0, on = false;
          for (let x = 0; x < plot; x++) {
            const hit = isLevel((y * canvas.width + x) * 4);
            if (hit && !on) runs++;
            on = hit;
          }
          dashes = Math.max(dashes, runs);
        }
        out.push({ label: `${renderer} ${label}`, kind: chart.rendererKind, covered, plot, dashes, firstCol, lastCol });
        chart.destroy();
        host.remove();
      }
    }
    return out;
  }, { w: W, h: H, level: LEVEL, renderers: gl ? ['canvas2d', 'webgl2'] : ['canvas2d'] });

  for (const r of report) {
    expect(r.kind, r.label).toBe(r.label.split(' ')[0]);
    // From the plot's left edge to its right one, within a dash period.
    expect(r.firstCol, `${r.label}: no level in the plot`).toBeGreaterThanOrEqual(0);
    expect(r.firstCol, `${r.label}: the level starts at column ${r.firstCol}`).toBeLessThan(11);
    expect(r.lastCol, `${r.label}: the level ends at column ${r.lastCol} of ${r.plot}`).toBeGreaterThan(r.plot - 12);
    if (r.label.endsWith('dashed')) {
      expect(r.dashes, `${r.label}: ${r.dashes} dashes across the plot`).toBeGreaterThan(60);
    } else {
      // Every column but the odd one under the edge's anti-aliasing.
      expect(r.covered, `${r.label}: the level shows in ${r.covered} of ${r.plot} plot columns`).toBeGreaterThan(r.plot - 3);
    }
  }
  expect(errors).toEqual([]);
});

for (const dpr of [1, 2]) {
  test(`dashes and dots stay where they were before the edge segment was drawn, at a pixel ratio of ${dpr}`, async ({ browser }) => {
    test.setTimeout(180_000);
    const context = await browser.newContext({ deviceScaleFactor: dpr, viewport: { width: W + 40, height: H + 40 } });
    const page = await context.newPage();
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto('/');
    const gl = await webgl2(page);
    await install(page);

    const report = await page.evaluate(async ({ w, h, renderers }) => {
      type Chart = {
        addSeries: (t: string, o?: unknown) => { setData: (b: unknown[]) => void };
        applySize: (w: number, h: number) => void; destroy: () => void; readonly rendererKind: string;
        timeScale: {
          setBarSpacing: (n: number) => void; setRightOffset: (n: number) => void; readonly width: number;
          indexToX: (i: number) => number; visibleRange: () => { from: number; to: number };
        };
        panes: () => { priceScale: { setAutoScale: (on: boolean) => void; setPriceRange: (r: { min: number; max: number }) => void } }[];
      };
      const g = window as unknown as { oacBase: { createChart: (el: HTMLElement, o?: unknown) => Chart }; oacBars: (n: number, s: number) => { time: number; close: number }[] };
      const bars = g.oacBars(3_000, 7);
      // A one-minute study's dashed line on five-second bars: a point every
      // twelfth bar, so the segment into the view shows between the plot's
      // left edge and its first point in view.
      const EVERY = 12;
      let ema = bars[0].close;
      const plot = bars.map((b) => { ema += (b.close - ema) * 0.3; return { time: b.time, open: ema, high: ema + 3, low: ema - 3, close: ema }; });
      const frame = (): Promise<void> => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
      let lo = Infinity, hi = -Infinity;
      for (let i = 1_500; i < 2_000; i++) { lo = Math.min(lo, plot[i].close); hi = Math.max(hi, plot[i].close); }
      const shoot = async (renderer: string, type: string, style: Record<string, unknown>, spacing: number, keep: (i: number) => boolean) => {
        const host = document.createElement('div');
        host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
        document.body.appendChild(host);
        const chart = g.oacBase.createChart(host, { priceAxisWidth: 64, renderer });
        chart.applySize(w, h);
        // The full history holds the axis, hidden, so both charts share it.
        chart.addSeries('line', { style: { visible: false } }).setData(bars);
        chart.addSeries(type, { style }).setData(plot.filter((_, i) => i % EVERY === 0 && keep(i)));
        chart.timeScale.setBarSpacing(spacing);
        chart.timeScale.setRightOffset(1_905 - (bars.length - 1));
        // One price range for both charts: autoscale reads a bar past the
        // view that only one of them holds.
        const scale = chart.panes()[0].priceScale;
        scale.setAutoScale(false);
        scale.setPriceRange({ min: lo - 20, max: hi + 20 });
        await frame();
        const range = chart.timeScale.visibleRange();
        // The study's first and last point in view.
        const first = Math.ceil(Math.floor(range.from) / EVERY) * EVERY;
        const last = Math.floor(Math.ceil(range.to) / EVERY) * EVERY;
        const canvas = host.querySelector('canvas') as HTMLCanvasElement;
        const shot = {
          kind: chart.rendererKind, first, last,
          xFirst: chart.timeScale.indexToX(first), xLast: chart.timeScale.indexToX(last),
          width: canvas.width, height: canvas.height,
          data: (canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D).getImageData(0, 0, canvas.width, canvas.height).data,
        };
        chart.destroy();
        host.remove();
        return shot;
      };
      const out: { label: string; kind: string; beyond: number; worst: number; ink: number; edgeInk: number }[] = [];
      for (const renderer of renderers) {
        for (const type of ['line', 'step', 'area', 'line-markers']) {
          for (const lineStyle of ['dashed', 'dotted']) {
            for (const spacing of [3, 11]) {
              // No last-value line or tag: the two series end on different bars.
              // An area's fill goes transparent: it is one polygon either way
              // (split, a translucent fill would show the seam), and a browser
              // may round one of its edge pixels a level differently when the
              // polygon reaches further; the dashes are in its outline.
              const style = {
                lineStyle, lineWidth: 2, color: '#40a0ff', priceLineVisible: false, lastValueVisible: false,
                ...(type === 'area' ? { areaTopColor: 'rgba(0,0,0,0)', areaBottomColor: 'rgba(0,0,0,0)' } : {}),
              };
              const full = await shoot(renderer, type, style, spacing, () => true);
              // The same line with nothing beyond the view: the path 2.5.8 drew.
              const inView = await shoot(renderer, type, style, spacing, (i) => i >= full.first && i <= full.last);
              const ratio = full.width / w;
              // From past the first bar's cap to short of the last bar's.
              const x0 = Math.ceil((full.xFirst + 6) * ratio);
              const x1 = Math.floor((full.xLast - 6) * ratio);
              let beyond = 0, worst = 0, ink = 0, edgeInk = 0;
              const a = full.data, b = inView.data;
              for (let y = 0; y < full.height; y++) {
                for (let x = 0; x < full.width; x++) {
                  const i = (y * full.width + x) * 4;
                  const delta = Math.max(Math.abs(a[i] - b[i]), Math.abs(a[i + 1] - b[i + 1]), Math.abs(a[i + 2] - b[i + 2]));
                  if (x >= x0 && x <= x1) {
                    // The bars' own path is stroked on its own, so its dashes
                    // stay where they were, anti-aliasing included, up to one
                    // rasteriser rounding (see the assertion below).
                    if (delta > 0) beyond++;
                    if (delta > worst) worst = delta;
                    if (a[i + 2] > 200 && a[i] < 120) ink++;
                  } else if (x < x0 && delta > 0) {
                    edgeInk++;
                  }
                }
              }
              out.push({ label: `${renderer} ${type} ${lineStyle} at ${spacing}`, kind: full.kind, beyond, worst, ink, edgeInk });
            }
          }
        }
      }
      return out;
    }, { w: W, h: H, renderers: gl ? ['canvas2d', 'webgl2'] : ['canvas2d'] });

    for (const r of report) {
      expect(r.kind, r.label).toBe(r.label.split(' ')[0]);
      // The line was drawn, and the edge segment was too: the comparison is
      // between two real lines, one of which carries more than the other.
      expect(r.ink, `${r.label}: no line in view`).toBeGreaterThan(200);
      expect(r.edgeInk, `${r.label}: the edge segment added nothing`).toBeGreaterThan(0);
      // A moved dash phase moves every dash in view: hundreds of pixels. What
      // is allowed is WebKit's rasteriser on Linux rounding one dash end at its
      // fixed-point precision, which changes a single pixel by a few dozen
      // levels 113 px into an otherwise identical stroke.
      expect(r.beyond, `${r.label}: ${r.beyond} pixels in view moved (worst by ${r.worst})`).toBeLessThanOrEqual(2);
      expect(r.worst, `${r.label}: a pixel in view moved by ${r.worst}`).toBeLessThanOrEqual(64);
    }
    expect(errors).toEqual([]);
    await context.close();
  });
}

test('a gap at the edge of the view is never bridged, by a line or by a fill', async ({ page }) => {
  test.setTimeout(180_000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));
  await page.goto('/');
  await page.setViewportSize({ width: W + 40, height: H + 40 });
  const gl = await webgl2(page);
  await install(page);

  const report = await page.evaluate(async ({ w, h, renderers }) => {
    type Chart = {
      addSeries: (t: string, o?: unknown) => { setData: (b: unknown[]) => void };
      applySize: (w: number, h: number) => void; destroy: () => void; readonly rendererKind: string;
      timeScale: { setBarSpacing: (n: number) => void; setRightOffset: (n: number) => void; visibleRange: () => { from: number; to: number } };
      panes: () => { priceScale: { setAutoScale: (on: boolean) => void; setPriceRange: (r: { min: number; max: number }) => void } }[];
    };
    const g = window as unknown as { oacBase: { createChart: (el: HTMLElement, o?: unknown) => Chart }; oacBars: (n: number, s: number) => { time: number; close: number; high: number; low: number }[] };
    const bars = g.oacBars(3_000, 19);
    // A one-minute study on five-second bars, a point every twelfth bar, so
    // the first and last points in view sit well inside the plot and a
    // bridge from the plot edge would cross open ground.
    const EVERY = 12;
    const RIGHT = 1_905;
    const frame = (): Promise<void> => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
    let lo = Infinity, hi = -Infinity;
    for (let i = 1_500; i < 2_000; i++) { lo = Math.min(lo, bars[i].low); hi = Math.max(hi, bars[i].high); }
    const shoot = async (renderer: string, type: string, points: unknown[]) => {
      const host = document.createElement('div');
      host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
      document.body.appendChild(host);
      const chart = g.oacBase.createChart(host, { priceAxisWidth: 64, renderer });
      chart.applySize(w, h);
      chart.addSeries('line', { style: { visible: false } }).setData(bars);
      chart.addSeries(type, {
        style: { lineWidth: 2, color: '#40a0ff', baseValue: (lo + hi) / 2, priceLineVisible: false, lastValueVisible: false },
      }).setData(points);
      chart.timeScale.setBarSpacing(7);
      chart.timeScale.setRightOffset(RIGHT - (bars.length - 1));
      const scale = chart.panes()[0].priceScale;
      scale.setAutoScale(false);
      scale.setPriceRange({ min: lo - 20, max: hi + 20 });
      await frame();
      const range = chart.timeScale.visibleRange();
      const canvas = host.querySelector('canvas') as HTMLCanvasElement;
      const shot = {
        kind: chart.rendererKind, range, width: canvas.width, height: canvas.height,
        data: (canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D).getImageData(0, 0, canvas.width, canvas.height).data,
      };
      chart.destroy();
      host.remove();
      return shot;
    };
    // Where the study's first and last points in view fall at this zoom.
    const probe = await shoot('canvas2d', 'line', []);
    const first = Math.ceil(Math.floor(probe.range.from) / EVERY) * EVERY;
    const last = Math.floor(Math.ceil(probe.range.to) / EVERY) * EVERY;
    // A point with no value is written the way a study writes one: whitespace, a NaN bar.
    const point = (i: number, gap: boolean): unknown => (gap ? { time: bars[i].time }
      : { time: bars[i].time, open: bars[i].close, high: bars[i].high, low: bars[i].low, close: bars[i].close });
    const out: { label: string; kind: string; moved: number; ink: number }[] = [];
    for (const renderer of renderers) {
      // The chart with nothing on it, to tell what the study painted.
      const empty = (await shoot(renderer, 'line', [])).data;
      for (const type of ['line', 'area', 'baseline', 'hlc-area']) {
        for (const [where, gapAt] of [
          // The neighbours beyond both edges have no value.
          ['beyond', (i: number) => i === first - EVERY || i === last + EVERY],
          // The first and last points in view have none; the neighbours do.
          ['within', (i: number) => i === first || i === last],
        ] as const) {
          const points = bars.map((_, i) => i).filter((i) => i % EVERY === 0);
          const full = await shoot(renderer, type, points.map((i) => point(i, gapAt(i))));
          // The same study with nothing beyond the view: what 2.5.8 drew.
          const alone = await shoot(renderer, type, points.filter((i) => i >= first && i <= last).map((i) => point(i, gapAt(i))));
          let moved = 0, ink = 0;
          const a = full.data, b = alone.data;
          for (let i = 0; i < a.length; i += 4) {
            if (a[i] !== b[i] || a[i + 1] !== b[i + 1] || a[i + 2] !== b[i + 2]) moved++;
            if (a[i] !== empty[i] || a[i + 1] !== empty[i + 1] || a[i + 2] !== empty[i + 2]) ink++;
          }
          out.push({ label: `${renderer} ${type}, gap ${where} the view`, kind: full.kind, moved, ink });
        }
      }
    }
    return out;
  }, { w: W, h: H, renderers: gl ? ['canvas2d', 'webgl2'] : ['canvas2d'] });

  for (const r of report) {
    expect(r.kind, r.label).toBe(r.label.split(' ')[0]);
    expect(r.ink, `${r.label}: nothing painted`).toBeGreaterThan(200);
    expect(r.moved, `${r.label}: ${r.moved} pixels differ from the study with nothing beyond the view`).toBe(0);
  }
  expect(errors).toEqual([]);
});

test('the GPU backend uploads a bounded batch for a dashed line whose neighbours are millions of pixels away', async ({ page }) => {
  test.setTimeout(120_000);
  await page.goto('/');
  await page.setViewportSize({ width: W + 40, height: H + 40 });
  test.skip(!(await webgl2(page)), 'no WebGL2 context survives in this browser');
  await install(page);
  const r = await page.evaluate(async ({ w, h, level }) => {
    type Chart = {
      addSeries: (t: string, o?: unknown) => { setData: (b: unknown[]) => void };
      applySize: (w: number, h: number) => void; destroy: () => void; readonly rendererKind: string;
      timeScale: { setBarSpacing: (n: number) => void; setRightOffset: (n: number) => void; readonly rightOffset: number };
    };
    const g = window as unknown as { oacBase: { createChart: (el: HTMLElement, o?: unknown) => Chart }; oacBars: (n: number, s: number) => { time: number; close: number }[] };
    // Ninety thousand five-second bars, twenty sessions: at 160 px a bar the
    // level's first and last bars sit over seven million pixels either side.
    const bars = g.oacBars(90_000, 3);
    const mid = 45_000;
    let floats = 0;
    const proto = WebGL2RenderingContext.prototype;
    const bufferData = proto.bufferData as (...args: unknown[]) => void;
    (proto as unknown as { bufferData: (...args: unknown[]) => void }).bufferData = function (this: WebGL2RenderingContext, ...args: unknown[]): void {
      if (args[0] === this.ARRAY_BUFFER) floats = Math.max(floats, typeof args[4] === 'number' ? args[4] : (args[1] as Float32Array).length);
      bufferData.apply(this, args);
    };
    const frame = (): Promise<void> => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(() => res())));
    const host = document.createElement('div');
    host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
    document.body.appendChild(host);
    const chart = g.oacBase.createChart(host, { priceAxisWidth: 64, renderer: 'webgl2', timeScale: { maxBarSpacing: 200 } });
    chart.applySize(w, h);
    const price = bars[mid].close;
    chart.addSeries('line', { style: { color: level, lineWidth: 2, lineStyle: 'dashed' } }).setData(
      [0, mid - 2, bars.length - 1].map((i) => ({ time: bars[i].time, open: price, high: price, low: price, close: price })),
    );
    chart.addSeries('candlestick').setData(bars);
    chart.timeScale.setBarSpacing(160);
    chart.timeScale.setRightOffset(mid - (bars.length - 1));
    await frame();
    floats = 0;
    const t0 = performance.now();
    for (let k = 0; k < 4; k++) {
      chart.timeScale.setRightOffset(chart.timeScale.rightOffset - 0.25);
      await frame();
    }
    const ms = (performance.now() - t0) / 4;
    const kind = chart.rendererKind;
    // And the level is there, dashed, across the plot.
    const canvas = host.querySelector('canvas') as HTMLCanvasElement;
    const d = (canvas.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D).getImageData(0, 0, canvas.width, canvas.height).data;
    let dashes = 0;
    for (let y = 0; y < canvas.height; y++) {
      let runs = 0, on = false;
      for (let x = 0; x < canvas.width * 0.9; x++) {
        const i = (y * canvas.width + x) * 4;
        const hit = d[i] > 200 && d[i + 1] > 160 && d[i + 2] < 90;
        if (hit && !on) runs++;
        on = hit;
      }
      dashes = Math.max(dashes, runs);
    }
    chart.destroy();
    host.remove();
    (proto as unknown as { bufferData: unknown }).bufferData = bufferData;
    return { floats, ms, kind, dashes };
  }, { w: W, h: H, level: LEVEL });
  expect(r.kind).toBe('webgl2');
  // A frame of a few candles and one cut line is a few thousand floats; the
  // uncut line was well over ten million.
  expect(r.floats, `${r.floats} floats in one upload, ${Math.round(r.ms)} ms a frame`).toBeLessThan(200_000);
  expect(r.dashes, 'the dashed level across the plot').toBeGreaterThan(60);
});
