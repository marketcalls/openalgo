import { test, expect, type Page } from '@playwright/test';

// Backend parity: the WebGL2 tier against the 2D backend.
//
// CLAUDE.md: "Green unit tests do not prove a renderer works." The GPU backend
// has a unit suite that checks what each series emits into its vertex batch,
// but nothing in Node runs a shader. This spec renders the SAME data through
// `renderer: 'canvas2d'` and `renderer: 'webgl2'` in one real browser, for the
// series types the backend draws natively (kagi, point and figure and a host's
// own types go through the 2D renderer on both paths and are not the question
// here), at every bar spacing the candle LOD tiers turn on, and compares the
// canvases.
//
// Not pixel for pixel: the two backends anti-alias differently, and the GPU
// surface reaches the base canvas through an 8-bit premultiplied blit, so an
// edge pixel legitimately lands a few levels off. The comparison is two-fold.
// No more than a small share of the non-background pixels may differ by more
// than a channel tolerance, and the colours that cover a real share of the ink
// (the up and down colours, the line colour, a flat fill) must be the same set
// on both sides, up to that tolerance. A backend that dropped the down colour,
// painted every candle solid, or lost the bodies at one LOD tier fails the
// second check even where the first passes by a whisker.
//
// Three traps this file exists to remember, two of them inherited from
// render-parity.spec.ts:
//
//  - The chart paints nothing in an OFF-SCREEN container. Each chart is built
//    visibly, at the origin, one at a time.
//  - "Did it paint?" cannot be alpha != 0: the background is opaque. Ink is
//    measured against the most common colour, which IS the background.
//  - `chart.rendererKind === 'webgl2'` is not proof that the GPU drew a single
//    pixel. The backend hands any entry it does not recognise to that entry's
//    own 2D renderer, so a backend that recognised nothing (a registry lookup
//    answering from a private copy of the registry, inlined into the tier
//    bundle) reports 'webgl2', paints everything through 2D, and passes a
//    pixel comparison perfectly. The spec therefore counts `drawElements`
//    calls on the real context: the GL chart must issue them, the 2D chart
//    must not.

const W = 900;
const H = 520;

/**
 * Bar spacings that straddle the candle LOD tier boundary. 1 is the floor:
 * `TimeScale` clamps to `minBarSpacing`, so nothing below it renders
 * differently.
 */
const SPACINGS = [1, 1.5, 2, 3, 6, 12, 24];

/** Distinct colours a real chart paints; a blank one is far below this. */
const MIN_DISTINCT_COLORS = 10;

/** Per-channel difference an edge pixel may show before it counts as differing. */
const CHANNEL_TOLERANCE = 32;

/** Share of ink pixels allowed to differ beyond the tolerance. */
const MAX_DIFFERING_SHARE = 0.02;

/**
 * A colour covering this share of the ink is dominant, and the other side
 * must then cover at least this fraction of the same pixel count with it.
 */
const DOMINANT_SHARE = 0.02;
const DOMINANT_MIN_RATIO = 0.5;

/** Pixels a series colour must cover, on both sides, to count as present. */
const MIN_COLOR_PIXELS = 100;

const UP = '#26a69a';
const DOWN = '#ef5350';
const LINE = '#4f8cff';
const HIST = '#6b7fd7';

/**
 * The last-price line and its axis tag are 2D chrome on both backends, in
 * the up or down colour of the last bar. Off, so the series pass is the only
 * thing painting those colours and a backend that dropped one cannot hide
 * behind the tag.
 */
const CHROME_OFF = { priceLineVisible: false, lastValueVisible: false };

/**
 * One chart per type, each colour spelt out so the dominant-colour check
 * knows what it is looking for. The wick and border colours are pinned to
 * the body colours so the wick-only LOD tier at small spacings still has to
 * show both.
 */
const CASES = [
  {
    type: 'candlestick',
    data: 'bars',
    style: { ...CHROME_OFF, upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN },
    colors: [UP, DOWN],
  },
  {
    type: 'hollow-candle',
    data: 'bars',
    style: { ...CHROME_OFF, upColor: UP, downColor: DOWN, borderUpColor: UP, borderDownColor: DOWN, wickUpColor: UP, wickDownColor: DOWN },
    colors: [UP, DOWN],
  },
  { type: 'bar', data: 'bars', style: { ...CHROME_OFF, upColor: UP, downColor: DOWN }, colors: [UP, DOWN] },
  { type: 'line', data: 'bars', style: { ...CHROME_OFF, color: LINE }, colors: [LINE] },
  { type: 'area', data: 'bars', style: { ...CHROME_OFF, color: LINE }, colors: [LINE] },
  { type: 'histogram', data: 'volume', style: { ...CHROME_OFF, color: HIST }, colors: [HIST] },
  // The base sits on the midline of the synthetic series (its sine term
  // integrates to 100 + 13.5 * (1 - cos(i / 9))), so the visible window
  // crosses it at every spacing and both the top and the bottom line get drawn.
  { type: 'baseline', data: 'bars', style: { ...CHROME_OFF, topColor: UP, bottomColor: DOWN, baseValue: 113.5 }, colors: [UP, DOWN] },
];

interface CaseReport {
  type: string;
  spacing: number;
  kind2d: string;
  kindGl: string;
  draws2d: number;
  drawsGl: number;
  planes: number;
  distinct: number;
  ink: number;
  differing: number;
  /** Colours dominant in the 2D render with no match in the GL render, and the reverse. */
  dominantOnlyIn2d: string[];
  dominantOnlyInGl: string[];
  /** Series colours the case asked for that one side or the other did not paint. */
  missing: string[];
}

interface Report {
  supported: boolean;
  registered: string[];
  cases: CaseReport[];
}

/**
 * Hold a throwaway WebGL2 context across a few frames until one survives.
 *
 * Headless Chromium hands out its first WebGL context while its GPU process
 * is still coming up and loses it a few milliseconds later, before the
 * program has compiled. The chart handles that the way it should (it falls
 * back to canvas2d for the session), which is exactly what would make these
 * tests vacuous: a parity run comparing 2D against 2D, and a loss test whose
 * loss already happened. So the GPU is brought up first, on a page that is
 * then discarded, and both tests assert on `rendererKind` afterwards rather
 * than trusting this.
 *
 * Resolves false when no context survives, or none is given at all.
 */
async function warmGpu(page: Page): Promise<boolean> {
  return page.evaluate(async () => {
    const frame = (): Promise<void> =>
      new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
    for (let attempt = 0; attempt < 20; attempt++) {
      const gl = document.createElement('canvas').getContext('webgl2');
      if (gl === null) return false;
      await frame();
      await frame();
      if (!gl.isContextLost()) return true;
    }
    return false;
  });
}

test('webgl2 paints what canvas2d paints for every native series type at every zoom', async ({ page }) => {
  // Seven types at seven spacings, twice each, plus the pixel analysis: well
  // over the default budget on a software GL device.
  test.setTimeout(180_000);

  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto('/');
  await page.setViewportSize({ width: W + 40, height: H + 40 });
  expect(await warmGpu(page), 'no WebGL2 context survives in this browser').toBe(true);

  const report: Report = await page.evaluate(
    async ({ w, h, spacings, cases, tol, dominantShare, minRatio, minColorPixels }) => {
      interface ChartLike {
        addSeries: (t: string, o?: unknown) => { setData: (b: unknown[]) => void };
        applySize: (w: number, h: number) => void;
        fitContent: () => void;
        destroy: () => void;
        readonly rendererKind: string;
        timeScale: { setBarSpacing: (n: number) => void };
      }
      interface BaseMod {
        createChart: (el: HTMLElement, o?: unknown) => ChartLike;
        registeredRenderBackends: () => string[];
      }
      interface TierMod {
        isWebGL2Supported: () => boolean;
      }

      // The tier registers the backend as a side effect of being imported,
      // the way a host's `import 'openalgo-charts/webgl'` would.
      const base = (await import('/dist/openalgo-charts.mjs')) as unknown as BaseMod;
      const tier = (await import('/dist/openalgo-charts.webgl.mjs')) as unknown as TierMod;
      const supported = tier.isWebGL2Supported();
      const registered = base.registeredRenderBackends();

      // Every GPU draw on the page goes through here; the shared device is
      // one real context, so counting on the prototype sees it.
      let gpuDraws = 0;
      const proto = WebGL2RenderingContext.prototype;
      const drawElements = proto.drawElements;
      proto.drawElements = function (this: WebGL2RenderingContext, mode: number, count: number, type: number, offset: number): void {
        gpuDraws++;
        drawElements.call(this, mode, count, type, offset);
      };

      // Deterministic OHLCV, shared by every chart.
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
      const volume = bars.map((b) => ({ time: b.time, open: 0, high: b.volume, low: 0, close: b.volume }));

      const frame = (): Promise<void> =>
        new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));

      interface Shot {
        planes: Uint8ClampedArray[];
        kind: string;
        draws: number;
      }

      /**
       * Render one case on one backend at one spacing and hand back the raw
       * canvas bytes. Visible and at the origin: the renderer paints nothing
       * off-screen. The spacing rides on the frame `setData` scheduled; the
       * time scale's setters schedule nothing themselves.
       */
      const shoot = async (renderer: string, c: (typeof cases)[number], spacing: number): Promise<Shot> => {
        const host = document.createElement('div');
        host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px;z-index:9999`;
        document.body.appendChild(host);
        const before = gpuDraws;
        const chart = base.createChart(host, { priceAxisWidth: 64, renderer });
        chart.applySize(w, h);
        chart.addSeries(c.type, { style: c.style }).setData(c.data === 'volume' ? volume : bars);
        chart.fitContent();
        chart.timeScale.setBarSpacing(spacing);
        await frame();
        const planes = Array.from(host.querySelectorAll('canvas')).map((cv) => {
          const el = cv as HTMLCanvasElement;
          const ctx = el.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
          return ctx.getImageData(0, 0, el.width, el.height).data;
        });
        const shot = { planes, kind: chart.rendererKind, draws: gpuDraws - before };
        chart.destroy();
        host.remove();
        return shot;
      };

      const key = (d: Uint8ClampedArray, i: number): number => ((d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]) >>> 0;
      const hex = (k: number): string => '#' + (k >>> 8).toString(16).padStart(6, '0');
      const parse = (css: string): number => (parseInt(css.slice(1), 16) * 256 + 255) >>> 0;
      const channelsApart = (a: number, b: number): number =>
        Math.max(
          Math.abs((a >>> 24) - (b >>> 24)),
          Math.abs(((a >>> 16) & 255) - ((b >>> 16) & 255)),
          Math.abs(((a >>> 8) & 255) - ((b >>> 8) & 255)),
        );

      /** Opaque colour histogram over every plane; transparent overlay pixels are skipped. */
      const histogram = (planes: readonly Uint8ClampedArray[]): Map<number, number> => {
        const counts = new Map<number, number>();
        for (const d of planes) {
          for (let i = 0; i < d.length; i += 4) {
            if (d[i + 3] === 0) continue;
            const k = key(d, i);
            counts.set(k, (counts.get(k) ?? 0) + 1);
          }
        }
        return counts;
      };

      /** Pixels within the channel tolerance of `colour`, across the whole histogram. */
      const near = (hist: Map<number, number>, colour: number): number => {
        let n = 0;
        for (const [k, c] of hist) if (channelsApart(k, colour) <= tol) n += c;
        return n;
      };

      const out: CaseReport[] = [];
      for (const c of cases) {
        for (const spacing of spacings) {
          const a = await shoot('canvas2d', c, spacing);
          const b = await shoot('webgl2', c, spacing);

          const histA = histogram(a.planes);
          const histB = histogram(b.planes);
          // The background is the most common colour of the 2D render; the
          // two charts share a theme, so it is the GL render's too.
          let bg = 0;
          let most = 0;
          for (const [k, n] of histA) if (n > most) { most = n; bg = k; }

          let ink = 0;
          let differing = 0;
          const planes = Math.min(a.planes.length, b.planes.length);
          for (let pl = 0; pl < planes; pl++) {
            const x = a.planes[pl];
            const y = b.planes[pl];
            if (x.length !== y.length) {
              const n = Math.abs(x.length - y.length) / 4;
              ink += n;
              differing += n;
              continue;
            }
            for (let i = 0; i < x.length; i += 4) {
              if (x[i + 3] === 0 && y[i + 3] === 0) continue;
              const kx = key(x, i);
              const ky = key(y, i);
              if (kx === bg && ky === bg) continue;
              ink++;
              if (
                Math.abs(x[i] - y[i]) > tol || Math.abs(x[i + 1] - y[i + 1]) > tol ||
                Math.abs(x[i + 2] - y[i + 2]) > tol || Math.abs(x[i + 3] - y[i + 3]) > tol
              ) differing++;
            }
          }

          const inkOf = (hist: Map<number, number>): number => {
            let n = 0;
            for (const [k, v] of hist) if (k !== bg) n += v;
            return n;
          };
          const inkA = inkOf(histA);
          const inkB = inkOf(histB);
          // Counted within the tolerance on both sides, so anti-aliasing that
          // spreads a flat colour over a few neighbours is not a difference,
          // while a colour that covers half the pixels it should is.
          const dominantOnly = (mine: Map<number, number>, myInk: number, theirs: Map<number, number>): string[] => {
            const missing: string[] = [];
            for (const [k, n] of mine) {
              if (k === bg || n < dominantShare * myInk) continue;
              if (near(theirs, k) < minRatio * near(mine, k)) missing.push(hex(k));
            }
            return missing;
          };
          const missing: string[] = [];
          for (const css of c.colors) {
            const k = parse(css);
            if (near(histA, k) < minColorPixels) missing.push(`${css} in canvas2d`);
            if (near(histB, k) < minColorPixels) missing.push(`${css} in webgl2`);
          }

          out.push({
            type: c.type,
            spacing,
            kind2d: a.kind,
            kindGl: b.kind,
            draws2d: a.draws,
            drawsGl: b.draws,
            planes,
            distinct: histA.size,
            ink,
            differing,
            dominantOnlyIn2d: dominantOnly(histA, inkA, histB),
            dominantOnlyInGl: dominantOnly(histB, inkB, histA),
            missing,
          });
        }
      }
      proto.drawElements = drawElements;
      return { supported, registered, cases: out };
    },
    {
      w: W, h: H, spacings: SPACINGS, cases: CASES, tol: CHANNEL_TOLERANCE,
      dominantShare: DOMINANT_SHARE, minRatio: DOMINANT_MIN_RATIO, minColorPixels: MIN_COLOR_PIXELS,
    },
  );

  // The numbers behind a pass, for whoever tunes the tolerances next.
  await test.info().attach('webgl-parity-report', { body: JSON.stringify(report, null, 1), contentType: 'application/json' });

  // No skip: a browser without WebGL2 would make every GL chart a 2D chart
  // and the comparison vacuous, so it has to fail, not pass quietly.
  expect(report.registered, 'importing the tier registers the webgl2 backend').toContain('webgl2');
  expect(report.supported, 'this browser has no WebGL2, so the spec cannot prove anything here').toBe(true);
  expect(report.cases).toHaveLength(CASES.length * SPACINGS.length);

  for (const r of report.cases) {
    const at = `${r.type} at spacing ${r.spacing}`;
    // Soft, so one run reports every case that is off rather than the first.
    expect.soft(r.kind2d, `${at}: the 2D chart reports its backend`).toBe('canvas2d');
    expect.soft(r.kindGl, `${at}: renderer 'webgl2' did not take effect`).toBe('webgl2');
    expect.soft(r.draws2d, `${at}: the 2D chart issued GPU draw calls`).toBe(0);
    expect.soft(r.drawsGl, `${at}: the webgl2 chart issued no GPU draw call, so its series went through the 2D renderer`).toBeGreaterThan(0);
    // A blank pair would compare equal and prove nothing.
    expect.soft(r.planes, `${at}: rendered no canvases`).toBeGreaterThan(0);
    expect.soft(r.distinct, `${at}: painted only ${r.distinct} colours, the chart is blank`).toBeGreaterThan(MIN_DISTINCT_COLORS);
    expect.soft(r.ink, `${at}: painted only background`).toBeGreaterThan(2000);
    expect.soft(r.missing, `${at}: series colours absent from one side`).toEqual([]);
    expect.soft(r.dominantOnlyIn2d, `${at}: colours dominant in canvas2d that webgl2 did not paint`).toEqual([]);
    expect.soft(r.dominantOnlyInGl, `${at}: colours dominant in webgl2 that canvas2d did not paint`).toEqual([]);
    const share = r.ink > 0 ? r.differing / r.ink : 0;
    expect.soft(
      share,
      `${at}: ${r.differing} of ${r.ink} ink pixels differ by more than ${CHANNEL_TOLERANCE} in a channel`,
    ).toBeLessThanOrEqual(MAX_DIFFERING_SHARE);
  }
  expect(errors).toEqual([]);
});

test('a lost GPU context moves the chart to canvas2d for the session, and it keeps painting', async ({ page }) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(String(e)));

  await page.goto('/');
  expect(await warmGpu(page), 'no WebGL2 context survives in this browser').toBe(true);

  // The fixture passes `?renderer=` straight through to `createChart`, after
  // importing the tier, so this is the same page every other e2e spec drives.
  await page.goto('/?renderer=webgl2');
  await page.waitForFunction(() => (window as unknown as { __ready?: boolean }).__ready === true);

  const result = await page.evaluate(async () => {
    interface ChartLike {
      readonly rendererKind: string;
      on: (event: string, cb: (payload: unknown) => void) => () => void;
    }
    interface TierMod {
      sharedGlDevice: () => { gl: WebGL2RenderingContext | null; available: boolean; lost: boolean };
    }
    const { chart, price, bars } = (window as unknown as {
      __api: { chart: ChartLike; price: { setData: (b: unknown[]) => void }; bars: unknown[] };
    }).__api;
    // The same module instance the fixture imported, so the same shared device.
    const tier = (await import('/dist/openalgo-charts.webgl.mjs')) as unknown as TierMod;

    const frame = (): Promise<void> =>
      new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
    const shoot = (): Uint8ClampedArray[] =>
      Array.from(document.querySelectorAll('#c canvas')).map((cv) => {
        const el = cv as HTMLCanvasElement;
        const ctx = el.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
        return ctx.getImageData(0, 0, el.width, el.height).data;
      });
    /** Distinct colours, and how many pixels are NOT the most common one. */
    const ink = (planes: readonly Uint8ClampedArray[]): { distinct: number; nonBackground: number } => {
      const counts = new Map<number, number>();
      for (const d of planes) {
        for (let i = 0; i < d.length; i += 4) {
          if (d[i + 3] === 0) continue;
          const k = (d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3];
          counts.set(k, (counts.get(k) ?? 0) + 1);
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

    await frame();
    const device = tier.sharedGlDevice();
    const kindBefore = chart.rendererKind;
    const deviceBefore = { available: device.available, lost: device.lost };
    const before = shoot();

    const events: unknown[] = [];
    chart.on('renderer:fallback', (e) => events.push(e));

    const gl = device.gl;
    const ext = gl?.getExtension('WEBGL_lose_context') ?? null;
    if (gl === null || ext === null) {
      throw new Error(`cannot simulate a context loss: chart on ${kindBefore}, device ${JSON.stringify(deviceBefore)}`);
    }
    ext.loseContext();

    // Nothing may reach the GPU once the chart has left it.
    let gpuDraws = 0;
    const proto = WebGL2RenderingContext.prototype;
    const drawElements = proto.drawElements;
    proto.drawElements = function (this: WebGL2RenderingContext, mode: number, count: number, type: number, offset: number): void {
      gpuDraws++;
      drawElements.call(this, mode, count, type, offset);
    };

    // New data, so a fresh paint can be told from a stale one, and a frame to
    // carry it (the time scale's setters alone schedule nothing). The chart
    // notices the loss after that frame, swaps every pane and repaints.
    price.setData(bars.slice(0, bars.length - 60));
    await frame();
    await frame();
    const after = shoot();
    proto.drawElements = drawElements;

    let changed = 0;
    for (let pl = 0; pl < Math.min(before.length, after.length); pl++) {
      const x = before[pl];
      const y = after[pl];
      if (x.length !== y.length) { changed += Math.abs(x.length - y.length) / 4; continue; }
      for (let i = 0; i < x.length; i += 4) {
        if (x[i] !== y[i] || x[i + 1] !== y[i + 1] || x[i + 2] !== y[i + 2] || x[i + 3] !== y[i + 3]) changed++;
      }
    }

    return {
      kindBefore,
      deviceBefore,
      kindAfter: chart.rendererKind,
      events,
      gpuDraws,
      contextLost: gl.isContextLost(),
      changed,
      ...ink(after),
    };
  });

  expect(
    result.kindBefore,
    `the fixture's ?renderer=webgl2 did not take effect (device ${JSON.stringify(result.deviceBefore)})`,
  ).toBe('webgl2');
  expect(result.contextLost).toBe(true);
  expect(result.events).toEqual([{ from: 'webgl2', to: 'canvas2d', reason: 'context-lost' }]);
  expect(result.kindAfter).toBe('canvas2d');
  expect(result.gpuDraws, 'the chart kept drawing on a lost context').toBe(0);
  expect(result.changed, 'the chart did not repaint after the fallback').toBeGreaterThan(0);
  expect(result.distinct, `painted only ${result.distinct} colours after the fallback: the chart is blank`).toBeGreaterThan(MIN_DISTINCT_COLORS);
  expect(result.nonBackground, 'painted only background after the fallback').toBeGreaterThan(2000);
  expect(errors).toEqual([]);
});
