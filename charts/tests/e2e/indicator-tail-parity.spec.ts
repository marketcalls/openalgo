import { test, expect, chromium, firefox, webkit } from '@playwright/test';

// The built-ins' calcTail in real engines. One chart on this build and one on
// the baseline build (`dist-baseline/`, the release this branch started from,
// which has no built-in tails and recomputes in full on every tick) take the
// same ticks and appended bars. After every one, each study must hold the same
// values on both, bit for bit, while this build reaches them through its tail.
//
// The unit property test (tests/indicator-tail.test.ts) covers the edges:
// missing prices, overflow, every parameter shape. This covers the engines, and
// the runtime between a price update and the values a host reads back.
//
// Each engine is launched from here rather than through a project, so the one
// spec runs in all three wherever the engine suite runs.

const IDS = [
  'sma', 'ema', 'wma', 'rsi', 'atr', 'adx', 'macd', 'bollinger', 'vwap', 'supertrend',
  'stochastic', 'obv', 'cci', 'keltner-channel', 'donchian', 'parabolic-sar',
];

for (const [name, engine] of Object.entries({ chromium, firefox, webkit })) {
  test(`live studies hold the baseline's full calculation in ${name}`, async ({ request, baseURL }) => {
    const probe = await request.get('/dist-baseline/openalgo-charts.indicators.mjs');
    test.skip(!probe.ok(), 'no dist-baseline/: run node scripts/build-baseline.mjs');
    // The baseline recomputes sixteen studies in full on every event, and one
    // engine launch sits inside the test as well.
    test.setTimeout(120_000);
    const browser = await engine.launch();
    try {
      const page = await browser.newPage({ baseURL });
      const errors: string[] = [];
      page.on('pageerror', (e) => errors.push(String(e)));
      await page.goto('/');
      const report = await page.evaluate(async (ids) => {
        type Values = Record<string, readonly (number | null)[]>;
        interface Study { values(): Values }
        interface Lib {
          createChart(el: HTMLElement): {
            addSeries(t: string): { setData(b: unknown[]): void; update(b: unknown): void };
            addIndicator(id: string): Study;
            destroy(): void;
          };
          getIndicator(id: string): Record<string, unknown> & { calcTail?: (...a: unknown[]) => unknown };
          registerIndicator(d: unknown): void;
        }
        const load = async (dir: string): Promise<Lib> => {
          const lib = await import(`/${dir}/openalgo-charts.mjs`) as unknown as Lib;
          await import(`/${dir}/openalgo-charts.indicators.mjs`);
          return lib;
        };
        const next = await load('dist');
        const prev = await load('dist-baseline');

        // Deterministic 15-minute bars in 09:15 to 15:30 IST sessions, on a
        // 0.05 tick so ties are common, some with no volume.
        let seed = 20260926;
        const rnd = (): number => ((seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0), seed / 4294967296);
        const tick = (v: number): number => Math.round(v * 20) / 20;
        let time = Date.UTC(2025, 0, 6, 3, 45) / 1000;
        const step = (t: number): number => {
          const open = Math.floor(t / 86400) * 86400 + 3 * 3600 + 45 * 60;
          if (t + 900 < open + 25 * 900) return t + 900;
          let day = Math.floor(t / 86400) * 86400 + 86400;
          while ([0, 6].includes(new Date(day * 1000).getUTCDay())) day += 86400;
          return day + 3 * 3600 + 45 * 60;
        };
        const barAt = (t: number, from: number, forming?: { open: number; high: number; low: number }) => {
          const close = tick(Math.max(1, from + (rnd() - 0.5) * 2));
          const open = forming?.open ?? from;
          const bar: Record<string, number> = {
            time: t, open,
            high: tick(Math.max(open, close, forming?.high ?? -Infinity) + rnd() * 0.5),
            low: tick(Math.min(open, close, forming?.low ?? Infinity) - rnd() * 0.5),
            close,
          };
          if (rnd() > 0.1) bar.volume = Math.floor(rnd() * 5000);
          return bar;
        };
        const bars: Record<string, number>[] = [];
        let price = 1000;
        for (let i = 0; i < 1500; i++) {
          bars.push(barAt(time, price));
          price = bars[i].close;
          time = step(time);
        }

        const tails: Record<string, number> = Object.fromEntries(ids.map((id) => [id, 0]));
        for (const id of ids) {
          const d = next.getIndicator(id);
          next.registerIndicator({
            ...d, id: `tail-probe-${id}`,
            calcTail: (...args: unknown[]) => { const out = d.calcTail!(...args); if (out !== null) tails[id]++; return out; },
          });
        }
        const mount = (lib: Lib, prefix: string) => {
          const el = document.createElement('div');
          el.style.cssText = 'position:absolute;left:0;top:0;width:600px;height:400px';
          document.body.appendChild(el);
          const chart = lib.createChart(el);
          const series = chart.addSeries('candlestick');
          series.setData(bars.map((b) => ({ ...b })));
          return { chart, series, studies: ids.map((id) => chart.addIndicator(prefix + id)) };
        };
        const a = mount(next, 'tail-probe-');
        const b = mount(prev, '');

        let mismatch: string | null = null;
        const events = 60;
        for (let e = 0; e < events && mismatch === null; e++) {
          const last = bars[bars.length - 1];
          const bar = rnd() < 0.3 ? barAt(step(last.time), last.close) : barAt(last.time, last.close, last as never);
          if (bar.time === last.time) bars[bars.length - 1] = bar; else bars.push(bar);
          a.series.update({ ...bar });
          b.series.update({ ...bar });
          ids.forEach((id, k) => {
            if (mismatch !== null) return;
            const x = a.studies[k].values();
            const y = b.studies[k].values();
            for (const key of Object.keys(y)) {
              const p = x[key];
              const q = y[key];
              if (p === undefined || p.length !== q.length) { mismatch = `${id}.${key} missing or misaligned after event ${e}`; return; }
              for (let i = 0; i < q.length; i++) {
                if (!Object.is(p[i] ?? null, q[i] ?? null)) { mismatch = `${id}.${key}[${i}] ${p[i]} against ${q[i]} after event ${e}`; return; }
              }
            }
          });
        }
        a.chart.destroy();
        b.chart.destroy();
        return { mismatch, tails, events };
      }, IDS);

      expect(errors).toEqual([]);
      expect(report.mismatch).toBeNull();
      // Every study took its tail on (almost) every event; VWAP may decline the
      // odd appended bar that changes how its sessions are read.
      for (const id of IDS) expect(report.tails[id], id).toBeGreaterThan(report.events * 0.9);
    } finally {
      await browser.close();
    }
  });
}
