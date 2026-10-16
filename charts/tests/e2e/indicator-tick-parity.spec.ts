import { test, expect } from '@playwright/test';

// Studies through live ticks paint the same pixels as the previous release.
//
// A study writes its plots in place on a tick: only the points that moved,
// and the last one, rather than the whole history. The unit tests prove the
// plot data comes out the same; this proves the canvas does, in a real
// browser, since green unit tests do not prove a renderer works (CLAUDE.md).
// render-parity.spec.ts covers bare candles at every zoom; this covers ten
// built-in studies and a coloured custom one at the default zoom, after each
// kind of write a live feed makes.
//
// The two builds run side by side, one above the other and both on screen
// (the renderer paints nothing off-screen), and take the same writes in the
// same turn, so every step compares two charts in the same state. It skips
// when `dist-baseline/` is absent, like render-parity.spec.ts.

const W = 900;
const H = 520;
const STUDIES = ['ema', 'bollinger', 'rsi', 'macd', 'volume', 'supertrend', 'adx', 'stochastic', 'vwap', 'atr'];
/** Distinct colours a chart with studies paints; a blank one is far below this. */
const MIN_DISTINCT_COLORS = 20;

for (const scale of [1, 1.25]) {
  test.describe(`device scale ${scale}`, () => {
    test.use({ deviceScaleFactor: scale });

    test('studies paint the same pixels as the baseline build through live ticks', async ({ page, request }) => {
      const probe = await request.get('/dist-baseline/openalgo-charts.indicators.mjs');
      test.skip(!probe.ok(), 'no dist-baseline/, run: node scripts/build-baseline.mjs');

      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.setViewportSize({ width: W + 40, height: 2 * H + 60 });
      // A blank page: the default fixture runs a chart of its own underneath.
      await page.route('**/indicator-tick-parity.html', (route) => route.fulfill({
        contentType: 'text/html',
        body: '<!doctype html><style>html,body{margin:0;background:#0d0e12}</style>',
      }));
      await page.goto('/indicator-tick-parity.html');

      const report = await page.evaluate(
        async ({ w, h, studies }) => {
          interface Bar { time: number; open: number; high: number; low: number; close: number; volume: number }
          interface SeriesLike { setData(b: Bar[]): void; update(b: Bar): void; prependData(b: Bar[]): void }
          interface ChartLike {
            addSeries(t: string): SeriesLike;
            addIndicator(id: string): unknown;
            applySize(w: number, h: number): void;
            destroy(): void;
          }
          interface Mod {
            createChart(el: HTMLElement, o?: unknown): ChartLike;
            registerIndicator(d: unknown): void;
          }
          const load = async (dir: string): Promise<Mod> => {
            const mod = (await import(`/${dir}/openalgo-charts.mjs`)) as unknown as Mod;
            await import(`/${dir}/openalgo-charts.indicators.mjs`);
            return mod;
          };
          const [next, base] = await Promise.all([load('dist'), load('dist-baseline')]);

          // Deterministic bars, shared by both charts; the first 80 arrive
          // later as a page of history.
          const all: Bar[] = [];
          let s = 20260926 >>> 0;
          const rnd = (): number => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0), s / 4294967296);
          let price = 1000;
          for (let i = 0; i < 480; i++) {
            const open = price;
            const close = 1000 + Math.sin(i / 17) * 18 + (rnd() - 0.5) * 6;
            all.push({
              time: 1_735_689_600 + i * 300, open, close,
              high: Math.max(open, close) + rnd() * 3, low: Math.min(open, close) - rnd() * 3,
              volume: Math.floor(1000 + rnd() * 9000),
            });
            price = close;
          }

          // Per-bar colours, one read from the bar after it, so a tick
          // recolours the forming bar and the one before it.
          const coloured = {
            id: 'tick-parity-coloured', name: 'Tick parity', placement: 'pane', inputs: [],
            plots: [
              { key: 'diff', type: 'histogram', title: 'Diff', colorBy: ({ value }: { value: number }) => (value >= 0 ? '#26a69a' : '#ef5350') },
              {
                key: 'lead', type: 'line', title: 'Lead',
                colorBy: ({ index, values }: { index: number; values: Record<string, (number | null)[]> }) =>
                  ((values.diff[index + 1] ?? 0) >= 0 ? '#1e88e5' : '#fb8c00'),
              },
            ],
            calc: (bars: Bar[]) => ({ diff: bars.map((b) => b.close - b.open), lead: bars.map((b) => b.open) }),
          };

          const make = (mod: Mod, top: number) => {
            // A copy per build: each keeps its own registry.
            mod.registerIndicator({ ...coloured, plots: coloured.plots.map((plot) => ({ ...plot })) });
            const host = document.createElement('div');
            host.style.cssText = `position:fixed;left:0;top:${top}px;width:${w}px;height:${h}px;z-index:9999`;
            document.body.appendChild(host);
            const chart = mod.createChart(host, { priceAxisWidth: 64 });
            chart.applySize(w, h);
            const series = chart.addSeries('candlestick');
            series.setData(all.slice(80));
            for (const id of [...studies, coloured.id]) chart.addIndicator(id);
            return { host, chart, series };
          };
          const charts = [make(next, 0), make(base, h + 20)];

          const frame = (): Promise<void> =>
            new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(() => r())));

          let last = all[all.length - 1];
          const write = (bar: Bar): void => { for (const c of charts) c.series.update(bar); };
          const tick = (close: number): void => {
            last = { ...last, close, high: Math.max(last.high, close), low: Math.min(last.low, close) };
            write(last);
          };
          const open = (): void => {
            last = { time: last.time + 300, open: last.close, high: last.close + 1, low: last.close - 1, close: last.close, volume: 900 };
            write(last);
          };
          const steps: [string, () => void][] = [
            ['loaded', () => {}],
            ['forming bar up', () => tick(last.close + 6)],
            ['forming bar down', () => tick(last.close - 11)],
            ['forming bar back to its open', () => tick(last.open)],
            ['appended bar', () => open()],
            ['three writes before one frame', () => { tick(last.close + 3); open(); tick(last.close - 2); }],
            ['correction far back', () => write({ ...all[200], close: all[200].close + 40, high: all[200].high + 40 })],
            ['page of history', () => { for (const c of charts) c.series.prependData(all.slice(0, 80)); }],
            ['tick after history', () => tick(last.close + 2)],
          ];

          const planes = (host: HTMLElement): Uint8ClampedArray[] =>
            Array.from(host.querySelectorAll('canvas')).map((cv) => {
              const c = cv as HTMLCanvasElement;
              const ctx = c.getContext('2d', { willReadFrequently: true }) as CanvasRenderingContext2D;
              return ctx.getImageData(0, 0, c.width, c.height).data;
            });
          const distinct = (list: readonly Uint8ClampedArray[]): number => {
            const seen = new Set<number>();
            for (const d of list) {
              for (let i = 0; i < d.length; i += 4) {
                if (d[i + 3] !== 0) seen.add((d[i] << 24) | (d[i + 1] << 16) | (d[i + 2] << 8) | d[i + 3]);
              }
            }
            return seen.size;
          };

          const out: { step: string; planes: number; distinct: number; differing: number }[] = [];
          for (const [step, run] of steps) {
            run();
            await frame();
            const a = planes(charts[0].host), b = planes(charts[1].host);
            let differing = Math.abs(a.length - b.length);
            for (let c = 0; c < Math.min(a.length, b.length); c++) {
              const x = a[c], y = b[c];
              if (x.length !== y.length) { differing += Math.abs(x.length - y.length) / 4; continue; }
              for (let i = 0; i < x.length; i += 4) {
                if (x[i] !== y[i] || x[i + 1] !== y[i + 1] || x[i + 2] !== y[i + 2] || x[i + 3] !== y[i + 3]) differing++;
              }
            }
            out.push({ step, planes: a.length, distinct: distinct(a), differing });
          }
          for (const c of charts) { c.chart.destroy(); c.host.remove(); }
          return out;
        },
        { w: W, h: H, studies: STUDIES },
      );

      expect(report).toHaveLength(9);
      for (const r of report) {
        // A blank pair would compare equal and prove nothing.
        expect(r.planes, `${r.step}: no canvases`).toBeGreaterThan(0);
        expect(r.distinct, `${r.step}: only ${r.distinct} colours, the chart is blank`).toBeGreaterThan(MIN_DISTINCT_COLORS);
        expect(r.differing, `${r.step}: ${r.differing} pixels differ from the baseline build`).toBe(0);
      }
      expect(errors).toEqual([]);
    });
  });
}
