import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import type * as Charts from '../../src/index';
import {
  BENCH_BAR_COUNTS,
  BENCH_METRICS,
  BENCH_METRIC_LABELS,
  BENCH_RENDERERS,
  RENDER_BENCH_BUDGETS,
  renderBenchBudgetMs,
} from '../../scripts/render-bench-budgets.mjs';

/**
 * Render bench: what a frame costs at 10k, 50k and 200k bars, on the 2D and
 * the WebGL2 backend, against budgets that fail the run.
 *
 * Three scenarios, each timed step by step:
 *
 *   pan       a mouse drag across a price chart with a volume pane, about 200
 *             bars in view, one bar further per step
 *   zoomOut   the same chart with every loaded bar in view (the spacing floor
 *             is lowered so the fit does not stop at one bar per pixel), one
 *             pixel of drag per step
 *   tick      a forming-bar update on a chart carrying ten studies, the frame
 *             that recomputes and repaints them
 *
 * A step's cost is its input, the one chart frame that input asked for, and
 * the raster work that frame left behind: every chart canvas is drawn into a
 * one-pixel probe and the probe read back, which cannot finish before the
 * canvases are painted. The chart gets a frame scheduler that queues instead
 * of waiting for the display, so a step is timed from the input to painted
 * pixels, not to the next vsync. Waiting for the display would round every
 * cost up to a multiple of 16.7 ms and hide any change smaller than a frame.
 * The probe is read instead of the chart canvases because a canvas that is
 * read back repeatedly can be moved off the GPU by the browser, which would
 * change what is being measured.
 *
 * A fast number proves nothing unless the frame did its work, so each scenario
 * also has to show that every step ran a chart frame and moved the view (or,
 * for a tick, recomputed each of the ten studies once), that the price pane is
 * painted afterwards, that the WebGL rows drew on the GPU and never fell back
 * (and the 2D rows never touched it), and that the zoomed-out view really holds
 * every bar.
 *
 * The budgets live in scripts/render-bench-budgets.mjs; docs/performance-notes.md
 * records where they came from. The bench runs alone (`npm run bench:render`,
 * or the `render-bench` project with OAC_RENDER_BENCH=1): timing frames beside
 * the rest of the suite would measure the suite.
 */

type Renderer = (typeof BENCH_RENDERERS)[number];
type Metric = (typeof BENCH_METRICS)[number];

const W = 1280;
const H = 800;

/** Ten studies across the overlay and the separate-pane kinds. */
const STUDIES = ['ema', 'bollinger', 'rsi', 'macd', 'volume', 'supertrend', 'adx', 'stochastic', 'vwap', 'atr'];

/** CSS px per bar for the pan and tick views: about 200 bars across the plot. */
const BAR_SPACING = 6;

/**
 * Browser flags per renderer. Headless Chromium has no GPU, so it runs WebGL
 * and the accelerated 2D canvas on its software GL device, a CPU emulation of
 * one; the device is pinned so a desktop and a CI runner emulate the same one.
 * Left accelerated, a 2D canvas is rasterized by that emulation at roughly
 * ten to twenty times the cost of the browser's own software rasterizer (ten thousand
 * thin rects took 50 to 95 ms against 5 to 6 ms on the reference machine), and
 * the 2D rows would time the emulator rather than the chart. They rasterize in
 * software instead, a real configuration: a device without GPU raster. The
 * WebGL rows keep the accelerated 2D canvas their GPU surface is composited
 * into, as on a device with a GPU.
 */
const BROWSER_ARGS: Record<Renderer, string[]> = {
  canvas2d: ['--use-angle=swiftshader', '--disable-accelerated-2d-canvas'],
  webgl2: ['--use-angle=swiftshader'],
};

/**
 * Steps per scenario and bar count. Warmup steps run the same code and are not
 * recorded. More samples make a p95 steadier, not cheaper: with fewer than
 * twenty it is the slowest step, so one collection decides it.
 *
 * Since plots are written in place and the common studies take their tail, a
 * tick with ten studies costs tens of milliseconds at 50k bars and a few
 * hundred at 200k, where 2.5.7 took one to two seconds and five to seven. The
 * 50k tick therefore records as many steps as the 10k one. The 200k rows stay
 * at twenty (the p95 is then the second slowest) for the sake of a regression:
 * a tick back at 2.5.7's cost, on a runner four times slower than the
 * reference, still finishes twenty-odd steps inside the test timeout, so it
 * fails on its budget and the report says which path went wrong.
 */
function planFor(bars: number): Record<Metric, { warmup: number; samples: number }> {
  const steps = bars >= 200_000 ? { warmup: 3, samples: 20 } : { warmup: 5, samples: 40 };
  return { pan: { warmup: 10, samples: 60 }, zoomOut: steps, tick: steps };
}

interface SceneReport {
  /** Milliseconds per recorded step. */
  samples: number[];
  /**
   * The same steps up to the end of the chart's frame, before the raster wait:
   * the script's share. Reported, not budgeted, so a regression can be placed.
   */
  scriptSamples: number[];
  /** Recorded steps that ran no chart frame, so timed only the input. */
  emptySteps: number;
  /** Steps, warmup included, after which the visible range had moved. */
  viewMoves: number;
  /** `drawElements` calls during the recorded steps. */
  gpuDraws: number;
  kindBefore: string;
  kindAfter: string;
  fellBack: boolean;
  /** Distinct colours and non-background pixels on the price pane afterwards. */
  distinct: number;
  ink: number;
  /** Loaded bars inside the visible range while the scenario ran. */
  visibleBars: number;
  /** Tick scenario: study recomputes during every step, warmup included. */
  studyPasses: number;
  /** Steps run, warmup included. */
  steps: number;
}

interface PageReport {
  env: { userAgent: string; gl: string; dpr: number; cores: number; version: string };
  pan: SceneReport;
  zoomOut: SceneReport;
  tick: SceneReport;
}

/**
 * Hold a throwaway WebGL2 context across a few frames until one survives.
 * Headless Chromium can lose its first context while the GPU process is still
 * starting, and a chart built then falls back to 2D for its whole life, which
 * would time the 2D path under a WebGL label. The report checks the backend
 * afterwards as well; this only makes the fallback unlikely.
 */
async function warmGpu(page: Page): Promise<boolean> {
  return page.evaluate(async () => {
    const frame = (): Promise<void> => new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));
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

/** Nearest-rank percentile of an unsorted sample. */
function percentile(samples: readonly number[], p: number): number {
  const sorted = [...samples].sort((a, b) => a - b);
  return sorted[Math.max(0, Math.ceil((p / 100) * sorted.length) - 1)];
}

const round = (ms: number): number => Math.round(ms * 100) / 100;

/**
 * The build the page loads, a folder at the package root: `dist` normally, and
 * `dist-baseline` (scripts/build-baseline.mjs) when `npm run bench:release`
 * measures the previous release on the same machine for the release's
 * benchmark entry. Held to a bare folder name, since it becomes a URL path.
 */
const BENCH_DIST = process.env.OAC_RENDER_BENCH_DIST ?? 'dist';
if (!/^[A-Za-z0-9_-]+$/.test(BENCH_DIST)) throw new Error(`OAC_RENDER_BENCH_DIST must be a folder name, got ${BENCH_DIST}`);

/** Build the charts in the page, run the three scenarios, and hand back what was measured. */
async function measureRow(page: Page, renderer: Renderer, bars: number): Promise<PageReport> {
  await page.goto('/tests/e2e/render-bench-fixture.html');
  if (renderer === 'webgl2') expect(await warmGpu(page), 'no WebGL2 context survives in this browser').toBe(true);

  return page.evaluate(
    async ({ renderer, bars, w, h, plan, studies, spacing, dist }) => {
      type Mod = typeof Charts;
      type ChartApi = ReturnType<Mod['createChart']>;
      type Descriptor = ReturnType<Mod['registeredIndicators']>[number];
      const base = (await import(`/${dist}/openalgo-charts.mjs`)) as unknown as Mod;
      await import(`/${dist}/openalgo-charts.indicators.mjs`);
      if (renderer === 'webgl2') await import(`/${dist}/openalgo-charts.webgl.mjs`);

      // Every GPU draw on the page goes through the prototype, so counting
      // there sees the backend's shared context whatever it is called.
      let gpuDraws = 0;
      const proto = WebGL2RenderingContext.prototype;
      const drawElements = proto.drawElements;
      proto.drawElements = function (this: WebGL2RenderingContext, mode: number, count: number, type: number, offset: number): void {
        gpuDraws++;
        drawElements.call(this, mode, count, type, offset);
      };

      const env = (() => {
        const probeGl = document.createElement('canvas').getContext('webgl2');
        const info = probeGl?.getExtension('WEBGL_debug_renderer_info');
        const gl = probeGl === null ? 'none' : String(info ? probeGl.getParameter(info.UNMASKED_RENDERER_WEBGL) : probeGl.getParameter(probeGl.RENDERER));
        probeGl?.getExtension('WEBGL_lose_context')?.loseContext();
        return { userAgent: navigator.userAgent, gl, dpr: devicePixelRatio, cores: navigator.hardwareConcurrency, version: base.VERSION };
      })();

      // Deterministic OHLCV, the generator scripts/bench-indicators.mjs uses,
      // so a number is comparable between runs and between machines.
      let seed = 20260831 >>> 0;
      const rnd = (): number => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0), seed / 4294967296);
      const data: { time: number; open: number; high: number; low: number; close: number; volume: number }[] = [];
      let price = 1000;
      for (let i = 0; i < bars; i++) {
        const open = price;
        const close = 1000 + Math.sin(i / 47) * 18 + (rnd() - 0.5) * 6;
        data.push({
          time: 1735689600 + i * 900,
          open,
          high: Math.max(open, close) + rnd() * 3,
          low: Math.min(open, close) - rnd() * 3,
          close,
          volume: Math.floor(1000 + rnd() * 9000),
        });
        price = close;
      }
      const volume = data.map((b) => ({ time: b.time, open: 0, high: b.volume, low: 0, close: b.volume }));

      // The probe that makes a step wait for painted pixels (see the header).
      const probe = document.createElement('canvas');
      probe.width = 1;
      probe.height = 1;
      const probeCtx = probe.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
      const rasterize = (host: HTMLElement): void => {
        for (const c of Array.from(host.querySelectorAll('canvas'))) {
          if (c.width > 0 && c.height > 0) probeCtx.drawImage(c, 0, 0, 1, 1, 0, 0, 1, 1);
        }
        probeCtx.getImageData(0, 0, 1, 1);
      };

      interface Mounted {
        host: HTMLElement;
        chart: ChartApi;
        /** Run every callback the chart has queued: one display frame's worth. */
        frame: () => number;
        /** Run frames until none is queued, or give up after a bound. */
        settle: () => void;
        fellBack: () => boolean;
      }

      // Visible and at the origin: the chart paints nothing off-screen.
      const mount = (options: Record<string, unknown>): Mounted => {
        const host = document.createElement('div');
        host.style.cssText = `position:fixed;left:0;top:0;width:${w}px;height:${h}px`;
        document.body.appendChild(host);
        const queued = new Map<number, () => void>();
        let next = 1;
        const chart = base.createChart(host, {
          ...options,
          renderer,
          raf: {
            schedule: (cb: () => void) => { const id = next++; queued.set(id, cb); return id; },
            cancel: (id: number) => { queued.delete(id); },
          },
        });
        let fell = false;
        chart.on('renderer:fallback', () => { fell = true; });
        const frame = (): number => {
          const batch = [...queued.values()];
          queued.clear();
          for (const cb of batch) cb();
          return batch.length;
        };
        const settle = (): void => { for (let i = 0; i < 240 && frame() > 0; i++); };
        return { host, chart, frame, settle, fellBack: () => fell };
      };

      const pointer = (host: HTMLElement, type: string, x: number, y: number, buttons: number): void => {
        host.dispatchEvent(new PointerEvent(type, {
          bubbles: true, cancelable: true, composed: true, pointerId: 1, pointerType: 'mouse', isPrimary: true,
          button: 0, buttons, clientX: x, clientY: y,
        }));
      };

      // A macrotask between steps, outside the timed window, so the browser
      // gets to composite and collect the way it would between frames.
      const yieldTask = (): Promise<void> => new Promise((r) => setTimeout(r, 0));

      const measure = async (
        m: Mounted, counts: { warmup: number; samples: number }, step: (i: number) => void,
      ): Promise<{ samples: number[]; scriptSamples: number[]; emptySteps: number; viewMoves: number; gpuDraws: number }> => {
        const samples: number[] = [];
        const scriptSamples: number[] = [];
        let emptySteps = 0;
        let viewMoves = 0;
        let draws = 0;
        let offset = m.chart.timeScale.rightOffset;
        for (let i = 0; i < counts.warmup + counts.samples; i++) {
          const before = gpuDraws;
          const t0 = performance.now();
          step(i);
          const ran = m.frame();
          const script = performance.now() - t0;
          rasterize(m.host);
          const ms = performance.now() - t0;
          if (i >= counts.warmup) {
            samples.push(ms);
            scriptSamples.push(script);
            if (ran === 0) emptySteps++;
            draws += gpuDraws - before;
          }
          if (m.chart.timeScale.rightOffset !== offset) viewMoves++;
          offset = m.chart.timeScale.rightOffset;
          await yieldTask();
        }
        return { samples, scriptSamples, emptySteps, viewMoves, gpuDraws: draws };
      };

      const scratch = document.createElement('canvas');
      /** Distinct colours and pixels that are not the most common one (the background). */
      const inkOf = (chart: ChartApi): { distinct: number; ink: number } => {
        const src = chart.panes()[0].base.element;
        scratch.width = src.width;
        scratch.height = src.height;
        const ctx = scratch.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
        ctx.drawImage(src, 0, 0);
        const d = ctx.getImageData(0, 0, scratch.width, scratch.height).data;
        const counts = new Map<number, number>();
        for (let i = 0; i < d.length; i += 4) {
          const key = ((d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]) >>> 0;
          counts.set(key, (counts.get(key) ?? 0) + 1);
        }
        let most = 0;
        let total = 0;
        for (const n of counts.values()) { total += n; if (n > most) most = n; }
        return { distinct: counts.size, ink: total - most };
      };

      const inView = (chart: ChartApi): number => {
        const r = chart.timeScale.visibleRange();
        return Math.max(0, Math.min(bars - 1, Math.floor(r.to)) - Math.max(0, Math.ceil(r.from)) + 1);
      };

      // ── pan and full zoom-out: one price chart with a volume pane ─────────────
      // The spacing floor is lowered so a fit can hold every loaded bar; at the
      // pan spacing it changes nothing.
      const priceChart = mount({ timeScale: { minBarSpacing: 1e-4 } });
      const pc = priceChart.chart;
      pc.addSeries('candlestick').setData(data);
      pc.addSeries('histogram', { paneIndex: 1 }).setData(volume);
      priceChart.settle();
      pc.timeScale.setBarSpacing(spacing);
      priceChart.settle();

      const x0 = Math.round(w * 0.3);
      const y0 = Math.round(h * 0.3);
      const panKindBefore = pc.rendererKind;
      const panView = inView(pc);
      pointer(priceChart.host, 'pointerdown', x0, y0, 1);
      // One bar further per step, dragging right into older history.
      const panRun = await measure(priceChart, plan.pan, (i) => pointer(priceChart.host, 'pointermove', x0 + (i + 1) * spacing, y0, 1));
      pointer(priceChart.host, 'pointerup', x0 + (plan.pan.warmup + plan.pan.samples) * spacing, y0, 0);
      const pan = {
        ...panRun, kindBefore: panKindBefore, kindAfter: pc.rendererKind, fellBack: priceChart.fellBack(),
        ...inkOf(pc), visibleBars: panView, studyPasses: 0, steps: plan.pan.warmup + plan.pan.samples,
      };

      // A fit also stops the fling the drag's release started.
      pc.fitContent();
      priceChart.settle();
      const zoomKindBefore = pc.rendererKind;
      const zoomView = inView(pc);
      pointer(priceChart.host, 'pointerdown', x0, y0, 1);
      // One pixel right and back: the whole history stays in view and every
      // step is a real change of range, so every step paints.
      const zoomRun = await measure(priceChart, plan.zoomOut, (i) => pointer(priceChart.host, 'pointermove', x0 + ((i + 1) % 2), y0, 1));
      pointer(priceChart.host, 'pointerup', x0, y0, 0);
      const zoomOut = {
        ...zoomRun, kindBefore: zoomKindBefore, kindAfter: pc.rendererKind, fellBack: priceChart.fellBack(),
        ...inkOf(pc), visibleBars: zoomView, studyPasses: 0, steps: plan.zoomOut.warmup + plan.zoomOut.samples,
      };
      pc.destroy();
      priceChart.host.remove();

      // ── tick: ten studies on the forming bar ──────────────────────────────────
      // Counted through wrappers rather than by instrumenting the engine. A
      // `calcTail` that answers is one pass; one that declines falls through to
      // `calc`, which is then the pass.
      let studyPasses = 0;
      const registry = new Map<string, Descriptor>(base.registeredIndicators().map((d) => [d.id, d]));
      const tickChart = mount({});
      const tc = tickChart.chart;
      const series = tc.addSeries('candlestick');
      series.setData(data);
      for (const id of studies) {
        const d = registry.get(id);
        if (d === undefined) throw new Error(`no study registered as ${id}`);
        const counted: Descriptor = { ...d, calc: (...a: Parameters<Descriptor['calc']>) => { studyPasses++; return d.calc(...a); } };
        const tail = d.calcTail;
        if (tail !== undefined) {
          counted.calcTail = (...a: Parameters<NonNullable<Descriptor['calcTail']>>) => {
            const out = tail.apply(d, a);
            if (out !== null) studyPasses++;
            return out;
          };
        }
        base.registerIndicator(counted);
        tc.addIndicator(id);
      }
      tickChart.settle();
      tc.timeScale.setBarSpacing(spacing);
      tickChart.settle();

      const last = data[data.length - 1];
      const tickKindBefore = tc.rendererKind;
      const tickView = inView(tc);
      studyPasses = 0;
      const tickRun = await measure(tickChart, plan.tick, (i) => {
        const close = last.close + Math.sin(i * 0.7) * 2;
        series.update({ ...last, close, high: Math.max(last.high, close), low: Math.min(last.low, close) });
      });
      const tick = {
        ...tickRun, kindBefore: tickKindBefore, kindAfter: tc.rendererKind, fellBack: tickChart.fellBack(),
        ...inkOf(tc), visibleBars: tickView, studyPasses, steps: plan.tick.warmup + plan.tick.samples,
      };
      tc.destroy();
      tickChart.host.remove();
      for (const d of registry.values()) base.registerIndicator(d);

      return { env, pan, zoomOut, tick };
    },
    { renderer, bars, w: W, h: H, plan: planFor(bars), studies: STUDIES, spacing: BAR_SPACING, dist: BENCH_DIST },
  );
}

for (const renderer of BENCH_RENDERERS) {
  for (const bars of BENCH_BAR_COUNTS) {
    test(`${renderer} at ${bars} bars stays within its frame budgets`, async ({ playwright }, testInfo) => {
      // Minutes, not seconds, at 200k bars on a CI runner; a regression that
      // slows the tick path several times over must fail on its budget rather
      // than on this timeout.
      test.setTimeout(900_000);
      // A browser per row, launched with its renderer's flags (BROWSER_ARGS);
      // a project can carry only one set.
      const browser = await playwright.chromium.launch({
        args: BROWSER_ARGS[renderer],
        headless: testInfo.project.use.headless !== false,
      });
      const errors: string[] = [];
      let report: PageReport;
      try {
        const context = await browser.newContext({
          viewport: { width: W, height: H }, deviceScaleFactor: 1, baseURL: String(testInfo.project.use.baseURL),
        });
        const page = await context.newPage();
        page.on('pageerror', (e) => errors.push(String(e)));
        page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
        report = await measureRow(page, renderer, bars);
      } finally {
        await browser.close();
      }

      const rows = BENCH_METRICS.map((metric: Metric) => {
        const s = report[metric].samples;
        return {
          metric,
          label: BENCH_METRIC_LABELS[metric],
          samples: s.length,
          p50: round(percentile(s, 50)),
          p95: round(percentile(s, 95)),
          max: round(Math.max(...s)),
          scriptP95: round(percentile(report[metric].scriptSamples, 95)),
          referenceP95: RENDER_BENCH_BUDGETS.measuredP95Ms[renderer][bars][metric],
          budget: renderBenchBudgetMs(renderer, bars, metric),
        };
      });

      const out = resolve(process.env.OAC_RENDER_BENCH_OUT ?? join(testInfo.project.testDir, '..', '..', 'artifacts', 'render-bench'));
      mkdirSync(out, { recursive: true });
      const record = {
        renderer, bars, measuredAt: new Date().toISOString(), env: report.env,
        margin: RENDER_BENCH_BUDGETS.margin, floorMs: RENDER_BENCH_BUDGETS.floorMs, reference: RENDER_BENCH_BUDGETS.reference,
        browserArgs: BROWSER_ARGS[renderer],
        rows,
        checks: Object.fromEntries(BENCH_METRICS.map((m) => {
          const { samples: _samples, scriptSamples: _script, ...rest } = report[m];
          return [m, rest];
        })),
        samples: Object.fromEntries(BENCH_METRICS.map((m) => [m, report[m].samples.map(round)])),
        scriptSamples: Object.fromEntries(BENCH_METRICS.map((m) => [m, report[m].scriptSamples.map(round)])),
      };
      writeFileSync(join(out, `${renderer}-${bars}.json`), JSON.stringify(record, null, 2) + '\n');
      await testInfo.attach(`render-bench-${renderer}-${bars}`, { body: JSON.stringify(record, null, 2), contentType: 'application/json' });
      console.log(`render bench, ${renderer}, ${bars} bars (${report.env.gl}, ${report.env.cores} logical CPUs)`);
      for (const r of rows) {
        const verdict = r.p95 <= r.budget ? 'ok' : 'OVER BUDGET';
        console.log(`  ${r.label.padEnd(26)} p50 ${String(r.p50).padStart(8)}  p95 ${String(r.p95).padStart(8)}  max ${String(r.max).padStart(8)}  script p95 ${String(r.scriptP95).padStart(8)}  budget ${String(r.budget).padStart(6)} ms  ${verdict}`);
      }

      // The run has to have measured what it claims before any number counts.
      for (const m of BENCH_METRICS) {
        const s = report[m];
        const where = `${renderer}, ${bars} bars, ${m}`;
        expect(s.samples.length, `${where}: recorded steps`).toBe(planFor(bars)[m].samples);
        expect(s.emptySteps, `${where}: steps that ran no chart frame`).toBe(0);
        expect(s.distinct, `${where}: the price pane painted ${s.distinct} colours, so it is blank`).toBeGreaterThan(10);
        expect(s.ink, `${where}: the price pane painted only background`).toBeGreaterThan(2000);
        if (renderer === 'webgl2') {
          expect([s.kindBefore, s.kindAfter, s.fellBack], `${where}: the chart left the GPU backend`).toEqual(['webgl2', 'webgl2', false]);
          expect(s.gpuDraws, `${where}: the WebGL backend issued no GPU draw`).toBeGreaterThan(0);
        } else {
          expect([s.kindBefore, s.kindAfter], `${where}: backend`).toEqual(['canvas2d', 'canvas2d']);
          expect(s.gpuDraws, `${where}: the 2D backend touched the GPU`).toBe(0);
        }
      }
      expect(report.pan.viewMoves, 'every pan step moved the view').toBe(report.pan.steps);
      expect(report.zoomOut.viewMoves, 'every zoomed-out step moved the view').toBe(report.zoomOut.steps);
      expect(report.pan.visibleBars, 'the pan view holds about 200 bars').toBeLessThan(400);
      expect(report.zoomOut.visibleBars, 'the zoomed-out view holds every loaded bar').toBe(bars);
      expect(report.tick.studyPasses, 'each tick recomputed each study exactly once').toBe(report.tick.steps * STUDIES.length);

      // Every budget is checked before the test fails, so one run lists them all.
      for (const r of rows) {
        expect.soft(r.p95, `${renderer}, ${bars} bars: ${r.label} ${r.p95} ms is over its ${r.budget} ms budget`).toBeLessThanOrEqual(r.budget);
      }
      expect(errors, 'browser errors during the bench').toEqual([]);
    });
  }
}
