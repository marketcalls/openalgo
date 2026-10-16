import { test, expect } from '@playwright/test';

// Render parity against the previous release.
//
// CLAUDE.md: "Green unit tests do not prove a renderer works. Two shipped
// defects passed a fully green suite and were only caught by looking at pixels."
// This is the harness for that. It renders the SAME data through the built
// bundle and through a baseline bundle (`dist-baseline/`, built from the ref
// this branch started from) in one real browser, then compares the canvases
// pixel for pixel.
//
// Run `node scripts/build-baseline.mjs` to refresh the baseline; the spec skips
// itself when it is absent, so a fresh clone does not fail on a missing artifact.
//
// A change that is MEANT to alter pixels updates the baseline ref and says so in
// the commit. A change that is not, like the candle LOD tier, has to come
// through here at zero differing pixels.
//
// Two traps this file exists to remember:
//
//  - The chart paints nothing in an OFF-SCREEN container. An earlier version of
//    this spec parked both hosts at `left:-10000px`, so both charts rendered a
//    flat fill, compared equal, and passed against a deliberately broken
//    renderer. Each chart is therefore built visibly, at the origin, one at a
//    time.
//  - "Did it paint?" cannot be alpha != 0: the background is opaque, so every
//    pixel passes that test on a blank chart. It has to be measured against the
//    most common colour, which IS the background.

const W = 900;
const H = 520;

/**
 * Bar spacings that straddle the candle LOD tier boundary.
 *
 * 1 is the floor: `TimeScale` clamps to `minBarSpacing`, which defaults to 1,
 * so a chart never draws more than one bar per pixel column and anything below
 * this lands on the same render. Sub-pixel spacings are therefore not worth
 * enumerating here.
 */
const SPACINGS = [1, 1.5, 2, 3, 6, 12, 24];

/** Distinct colours a real chart paints; a blank one is far below this. */
const MIN_DISTINCT_COLORS = 10;

test('paints the same pixels as the baseline build at every zoom', async ({ page, request }) => {
  const probe = await request.get('/dist-baseline/openalgo-charts.mjs');
  test.skip(!probe.ok(), 'no dist-baseline/; run node scripts/build-baseline.mjs');

  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto('/');
  await page.setViewportSize({ width: W + 40, height: H + 40 });

  const report = await page.evaluate(
    async ({ w, h, spacings }) => {
      interface ChartLike {
        addSeries: (t: string, o?: unknown) => { setData: (b: unknown[]) => void };
        applySize: (w: number, h: number) => void;
        fitContent: () => void;
        destroy: () => void;
        timeScale: { setBarSpacing: (n: number) => void };
      }
      type Mod = { createChart: (el: HTMLElement, o?: unknown) => ChartLike };

      const [next, base] = (await Promise.all([
        import('/dist/openalgo-charts.mjs'),
        import('/dist-baseline/openalgo-charts.mjs'),
      ])) as unknown as [Mod, Mod];

      // Deterministic OHLCV, shared by both charts.
      const bars: Array<{ time: number; open: number; high: number; low: number; close: number; volume: number }> = [];
      let p = 100;
      for (let i = 0; i < 600; i++) {
        const o = p;
        p += Math.sin(i / 9) * 1.5 + ((i % 7) - 3) * 0.3;
        bars.push({
          time: 1_700_000_000 + i * 300,
          open: o,
          high: Math.max(o, p) + 1,
          low: Math.min(o, p) - 1,
          close: p,
          volume: 100 + i,
        });
      }

      const frame = (): Promise<void> =>
        new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));

      /**
       * Render one bundle at one spacing and hand back the raw canvas bytes.
       * Visible and at the origin: the renderer paints nothing off-screen.
       */
      const shoot = async (mod: Mod, spacing: number): Promise<Uint8ClampedArray[]> => {
        const host = document.createElement('div');
        host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
        document.body.appendChild(host);
        const chart = mod.createChart(host, { priceAxisWidth: 64 });
        chart.applySize(w, h);
        chart.addSeries('candlestick').setData(bars);
        chart.addSeries('histogram', { paneIndex: 1 }).setData(
          bars.map((b) => ({ time: b.time, open: 0, high: b.volume, low: 0, close: b.volume })),
        );
        chart.fitContent();
        chart.timeScale.setBarSpacing(spacing);
        await frame();
        const shot = Array.from(host.querySelectorAll('canvas')).map((cv) => {
          const c = cv as HTMLCanvasElement;
          const ctx = c.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
          return ctx.getImageData(0, 0, c.width, c.height).data;
        });
        chart.destroy();
        host.remove();
        return shot;
      };

      /** Distinct colours, and how many pixels are NOT the most common one. */
      const ink = (planes: readonly Uint8ClampedArray[]): { distinct: number; nonBackground: number } => {
        const counts = new Map<number, number>();
        for (const d of planes) {
          for (let i = 0; i < d.length; i += 4) {
            if (d[i + 3] === 0) continue; // fully transparent overlay plane
            const key = (d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3];
            counts.set(key, (counts.get(key) ?? 0) + 1);
          }
        }
        let total = 0;
        let most = 0;
        for (const n of counts.values()) {
          total += n;
          if (n > most) most = n;
        }
        return { distinct: counts.size, nonBackground: total - most };
      };

      const out: Array<{ spacing: number; planes: number; differing: number; distinct: number; nonBackground: number }> = [];
      for (const spacing of spacings) {
        const a = await shoot(next, spacing);
        const b = await shoot(base, spacing);
        let differing = 0;
        const planes = Math.min(a.length, b.length);
        for (let c = 0; c < planes; c++) {
          const x = a[c];
          const y = b[c];
          if (x.length !== y.length) {
            differing += Math.abs(x.length - y.length) / 4;
            continue;
          }
          for (let i = 0; i < x.length; i += 4) {
            if (x[i] !== y[i] || x[i + 1] !== y[i + 1] || x[i + 2] !== y[i + 2] || x[i + 3] !== y[i + 3]) differing++;
          }
        }
        out.push({ spacing, planes, ...ink(a), differing });
      }
      return out;
    },
    { w: W, h: H, spacings: SPACINGS },
  );

  for (const r of report) {
    // A blank pair would compare equal and prove nothing, so the chart has to
    // be shown to have actually drawn before the comparison means anything.
    expect(r.planes, `spacing ${r.spacing} rendered no canvases`).toBeGreaterThan(0);
    expect(r.distinct, `spacing ${r.spacing} painted only ${r.distinct} colours: the chart is blank`).toBeGreaterThan(
      MIN_DISTINCT_COLORS,
    );
    expect(r.nonBackground, `spacing ${r.spacing} painted only background`).toBeGreaterThan(2000);
    expect(r.differing, `spacing ${r.spacing} differs from baseline in ${r.differing} pixels`).toBe(0);
  }
  expect(errors).toEqual([]);
});

/**
 * Every built-in series type, not only the candles and volume above: the
 * series pass writes its draw items in place and the renderers work their
 * geometry out without an object per bar (candles, OHLC and high-low bars,
 * columns, and the line family's reused point buffers), and none of that may
 * move a pixel. Per-bar colours, a whitespace gap and previous-close colouring
 * take the renderers down their less common paths, and a pixel ratio of two
 * checks the device-pixel snapping as well as the one-to-one case.
 */
const TYPES = [
  'candlestick', 'hollow-candle', 'volume-candle', 'bar', 'high-low',
  'line', 'line-markers', 'step', 'area', 'hlc-area', 'baseline', 'column', 'histogram',
];

for (const dpr of [1, 2]) {
  test(`paints every built-in series type as the baseline build does at a pixel ratio of ${dpr}`, async ({ browser }) => {
    const context = await browser.newContext({ deviceScaleFactor: dpr, viewport: { width: W + 40, height: H + 40 } });
    const page = await context.newPage();
    const probe = await page.request.get('/dist-baseline/openalgo-charts.mjs');
    test.skip(!probe.ok(), 'no dist-baseline/ (run: node scripts/build-baseline.mjs)');
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(String(e)));
    await page.goto('/');

    const report = await page.evaluate(
      async ({ w, h, types }) => {
        interface ChartLike {
          addSeries: (t: string, o?: unknown) => { setData: (b: unknown[]) => void };
          applySize: (w: number, h: number) => void;
          fitContent: () => void;
          destroy: () => void;
          timeScale: { setBarSpacing: (n: number) => void };
        }
        type Mod = { createChart: (el: HTMLElement, o?: unknown) => ChartLike };
        const [next, base] = (await Promise.all([
          import('/dist/openalgo-charts.mjs'),
          import('/dist-baseline/openalgo-charts.mjs'),
        ])) as unknown as [Mod, Mod];

        const bars: Array<Record<string, number | string>> = [];
        let p = 100;
        for (let i = 0; i < 400; i++) {
          const o = p;
          p += Math.sin(i / 7) * 1.2 + ((i % 5) - 2) * 0.4;
          const bar: Record<string, number | string> = {
            time: 1_700_000_000 + i * 300, open: o, high: Math.max(o, p) + 0.8, low: Math.min(o, p) - 0.8, close: p, volume: 100 + (i % 37) * 9,
          };
          // A study that colours some bars by its own rule, and one gap of whitespace.
          if (i % 11 === 3) bar.color = '#aa44ff';
          if (i >= 200 && i < 206) { bar.open = NaN; bar.high = NaN; bar.low = NaN; bar.close = NaN; }
          bars.push(bar);
        }
        const frame = (): Promise<void> =>
          new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
        const shoot = async (mod: Mod, type: string, spacing: number, variant: number): Promise<Uint8ClampedArray[]> => {
          const host = document.createElement('div');
          host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
          document.body.appendChild(host);
          const chart = mod.createChart(host, { priceAxisWidth: 64 });
          chart.applySize(w, h);
          const style = variant === 0 ? {}
            : { colorByPreviousClose: true, highColor: '#ff8800', lowColor: '#0088ff', baseValue: 101, lineStyle: 'dashed', markers: true };
          chart.addSeries(type, { style }).setData(bars);
          chart.fitContent();
          chart.timeScale.setBarSpacing(spacing);
          await frame();
          const shot = Array.from(host.querySelectorAll('canvas')).map((cv) => {
            const c = cv as HTMLCanvasElement;
            const ctx = c.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
            return ctx.getImageData(0, 0, c.width, c.height).data;
          });
          chart.destroy();
          host.remove();
          return shot;
        };
        const out: Array<{ label: string; differing: number; nonBackground: number }> = [];
        for (const type of types) {
          for (const [spacing, variant] of [[1.5, 0], [4, 1], [13, 0]] as const) {
            const a = await shoot(next, type, spacing, variant);
            const b = await shoot(base, type, spacing, variant);
            let differing = 0;
            const counts = new Map<number, number>();
            for (let c = 0; c < Math.min(a.length, b.length); c++) {
              const x = a[c], y = b[c];
              if (x.length !== y.length) { differing += Math.abs(x.length - y.length) / 4; continue; }
              for (let i = 0; i < x.length; i += 4) {
                if (x[i] !== y[i] || x[i + 1] !== y[i + 1] || x[i + 2] !== y[i + 2] || x[i + 3] !== y[i + 3]) differing++;
                if (x[i + 3] !== 0) {
                  const key = (x[i] << 24) | (x[i + 1] << 16) | (x[i + 2] << 8) | x[i + 3];
                  counts.set(key, (counts.get(key) ?? 0) + 1);
                }
              }
            }
            let total = 0, most = 0;
            for (const n of counts.values()) { total += n; if (n > most) most = n; }
            out.push({ label: `${type} at ${spacing} px, variant ${variant}`, differing, nonBackground: total - most });
          }
        }
        return out;
      },
      { w: W, h: H, types: TYPES },
    );

    for (const r of report) {
      expect(r.nonBackground, `${r.label} painted only background`).toBeGreaterThan(2000);
      expect(r.differing, `${r.label} differs from baseline in ${r.differing} pixels`).toBe(0);
    }
    expect(errors).toEqual([]);
    await context.close();
  });
}
