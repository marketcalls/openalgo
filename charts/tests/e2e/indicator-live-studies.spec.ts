import { test, expect, chromium, firefox, webkit } from '@playwright/test';

// The seven built-ins added after 2.5.10 (ZigZag, 52 Week High/Low, ZLEMA,
// VIDYA, Elder-Ray, Schaff Trend Cycle, Volatility Squeeze) in real engines.
//
// Each one is drawn alone on a seeded random walk, with the candles in greys so
// the study's own colours can be counted in the plot area, and a screenshot is
// kept per study. Then all seven take live ticks and appended bars on one
// chart, and after every event each must hold what a fresh full calculation of
// the same bars returns, bit for bit, mostly through its tail. The baseline
// comparison in indicator-tail-parity.spec.ts cannot cover them: the release
// it builds has none of the seven.
//
// Each engine is launched from here, so the one spec runs in all three
// wherever the engine suite runs.

const STUDIES: Record<string, string[]> = {
  zigzag: ['#2962ff'],
  'high-low-52-week': ['#26a69a', '#ef5350'],
  zlema: ['#00bcd4'],
  vidya: ['#ff9800'],
  'elder-ray': ['#26a69a', '#ef5350'],
  'schaff-trend-cycle': ['#2962ff'],
  'volatility-squeeze': ['#26a69a', '#a7d8d2', '#ef5350', '#f5b0ae', '#ff9800'],
};

const PAGE = '<!doctype html><html><head><style>html,body{margin:0;height:100%;background:#101216}#chart{height:100%}</style></head><body><div id="chart"></div></body></html>';

for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  test(`the seven newer studies draw and hold their full calculation live in ${name}`, async ({ baseURL }, info) => {
    test.setTimeout(120_000);
    const browser = await engine.launch();
    try {
      const page = await browser.newPage({ baseURL, viewport: { width: 1000, height: 640 } });
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.route('**/live-studies.html', (route) => route.fulfill({ contentType: 'text/html', body: PAGE }));
      await page.goto('/live-studies.html');
      await page.evaluate(async () => {
        type Values = Record<string, readonly (number | null)[]>;
        interface Study { values(): Values; remove(): void }
        interface Lib {
          createChart(el: HTMLElement, o?: unknown): {
            addSeries(t: string, o?: unknown): { setData(b: unknown[]): void; update(b: unknown): void };
            addIndicator(id: string): Study;
            setVisibleLogicalRange(r: { from: number; to: number }): void;
            destroy(): void;
          };
          getIndicator(id: string): Record<string, unknown> & {
            calc(...a: unknown[]): Values; calcTail?: (...a: unknown[]) => Values | null;
          };
          indicatorDefaults(d: unknown): Record<string, unknown>;
          registerIndicator(d: unknown): void;
        }
        const lib = await import('/dist/openalgo-charts.mjs') as unknown as Lib;
        await import('/dist/openalgo-charts.indicators.mjs');

        // A seeded random walk of daily bars, weekdays only, long enough for a
        // 52 week window to cover the last year and a half of it.
        let seed = 20260930;
        const rnd = (): number => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0), seed / 4294967296);
        const tick = (v: number): number => Math.round(v * 20) / 20;
        const next = (t: number): number => {
          let d = t + 86400;
          while ([0, 6].includes(new Date(d * 1000).getUTCDay())) d += 86400;
          return d;
        };
        const barAt = (t: number, from: number, forming?: { open: number; high: number; low: number }) => {
          const close = tick(Math.max(1, from * (1 + (rnd() - 0.5) * 0.04)));
          const open = forming?.open ?? from;
          return {
            time: t, open,
            high: tick(Math.max(open, close, forming?.high ?? -Infinity) * (1 + rnd() * 0.01)),
            low: tick(Math.min(open, close, forming?.low ?? Infinity) * (1 - rnd() * 0.01)),
            close, volume: Math.floor(1000 + rnd() * 9000),
          };
        };
        const bars: ReturnType<typeof barAt>[] = [];
        let time = Date.UTC(2023, 0, 2, 10) / 1000;
        let price = 1000;
        for (let i = 0; i < 640; i++) {
          bars.push(barAt(time, price));
          price = bars[i].close;
          time = next(time);
        }
        const grey = { upColor: '#8a8a8a', downColor: '#5c5c5c', borderUpColor: '#8a8a8a', borderDownColor: '#5c5c5c', wickUpColor: '#8a8a8a', wickDownColor: '#5c5c5c' };
        const host = document.querySelector<HTMLElement>('#chart')!;

        let shown: ReturnType<Lib['createChart']> | null = null;
        const show = (id: string): void => {
          shown?.destroy();
          shown = lib.createChart(host, { branding: false });
          shown.addSeries('candlestick', { style: grey }).setData(bars.map((b) => ({ ...b })));
          shown.addIndicator(id);
          shown.setVisibleLogicalRange({ from: bars.length - 260, to: bars.length + 4 });
        };

        // Pixels near one of `colours` in the plot area, left of the price axis.
        const ink = (colours: string[]): number => {
          const rgb = colours.map((c) => [1, 3, 5].map((k) => parseInt(c.slice(k, k + 2), 16)));
          let count = 0;
          for (const canvas of document.querySelectorAll('canvas')) {
            const ctx = canvas.getContext('2d');
            if (!ctx || canvas.width === 0 || canvas.height === 0) continue;
            const scale = canvas.width / canvas.getBoundingClientRect().width;
            const w = Math.max(0, Math.floor(canvas.width - 90 * scale));
            if (w === 0) continue;
            const px = ctx.getImageData(0, 0, w, canvas.height).data;
            for (let i = 0; i < px.length; i += 4) {
              if (px[i + 3] < 200) continue;
              if (rgb.some(([r, g, b]) => Math.abs(px[i] - r) + Math.abs(px[i + 1] - g) + Math.abs(px[i + 2] - b) < 40)) count++;
            }
          }
          return count;
        };

        const live = (events: number) => {
          shown?.destroy();
          shown = null;
          const ids = Object.keys((window as unknown as { __colours: Record<string, string[]> }).__colours);
          const tails: Record<string, number> = Object.fromEntries(ids.map((id) => [id, 0]));
          for (const id of ids) {
            const d = lib.getIndicator(id);
            lib.registerIndicator({
              ...d, id: `live-probe-${id}`,
              calcTail: (...args: unknown[]) => { const out = d.calcTail!(...args); if (out !== null) tails[id]++; return out; },
            });
          }
          const chart = lib.createChart(host, { branding: false });
          const series = chart.addSeries('candlestick', { style: grey });
          series.setData(bars.map((b) => ({ ...b })));
          const studies = ids.map((id) => chart.addIndicator(`live-probe-${id}`));
          let mismatch: string | null = null;
          for (let e = 0; e < events && mismatch === null; e++) {
            const last = bars[bars.length - 1];
            const bar = rnd() < 0.3 ? barAt(next(last.time), last.close) : barAt(last.time, last.close, last);
            if (bar.time === last.time) bars[bars.length - 1] = bar; else bars.push(bar);
            series.update({ ...bar });
            ids.forEach((id, k) => {
              if (mismatch !== null) return;
              const d = lib.getIndicator(id);
              const want = d.calc(bars.map((b) => ({ ...b })), lib.indicatorDefaults(d), {});
              const got = studies[k].values();
              for (const key of Object.keys(want)) {
                const p = got[key];
                const q = want[key];
                if (p === undefined || p.length !== q.length) { mismatch = `${id}.${key} misaligned after event ${e}`; return; }
                for (let i = 0; i < q.length; i++) {
                  if (!Object.is(p[i] ?? null, q[i] ?? null)) { mismatch = `${id}.${key}[${i}] ${p[i]} against ${q[i]} after event ${e}`; return; }
                }
              }
            });
          }
          chart.destroy();
          return { mismatch, tails, events };
        };

        Object.assign(window, { __show: show, __ink: ink, __live: live });
      });
      await page.evaluate((colours) => Object.assign(window, { __colours: colours }), STUDIES);

      const painted = () => page.evaluate(() => new Promise<void>((r) => requestAnimationFrame(() => requestAnimationFrame(() => r()))));
      for (const [id, colours] of Object.entries(STUDIES)) {
        await page.evaluate((i) => (window as unknown as { __show(id: string): void }).__show(i), id);
        await painted();
        const count = await page.evaluate((c) => (window as unknown as { __ink(c: string[]): number }).__ink(c), colours);
        expect(count, `${id} drew its colours`).toBeGreaterThan(300);
        await page.screenshot({ path: info.outputPath(`${name}-${id}.png`) });
      }

      const report = await page.evaluate(() => (window as unknown as {
        __live(n: number): { mismatch: string | null; tails: Record<string, number>; events: number };
      }).__live(60));
      expect(errors).toEqual([]);
      expect(report.mismatch).toBeNull();
      // Each study splices its tail on most events. ZigZag declines when a tick
      // moves the end of its last leg off a bar before the tail (the first tick
      // of a bar that extends the leg), which is the study revising its past.
      for (const id of Object.keys(STUDIES)) {
        expect(report.tails[id], id).toBeGreaterThan(report.events * (id === 'zigzag' ? 0.5 : 0.9));
      }
    } finally {
      await browser.close();
    }
  });
}
