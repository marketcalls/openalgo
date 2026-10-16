import { expect, test, type Page } from '@playwright/test';
import type { Chart } from '../../src/index';
import type { Widget } from '../../src/widget/index';

/**
 * The Vue 3 example (examples/vue) in a real browser, with Vue's own runtime.
 *
 * The component under test is the one the Vue 3 section of the website's
 * framework guide (/docs/frameworks#vue-3) documents: a composable that holds
 * the chart in a shallowRef, props that feed the same series, the chart's own
 * ResizeObserver for size, KeepAlive for switching
 * views and v-if for unmounting. What the engine could get wrong under a
 * framework is lifecycle, so the checks are about identity and teardown:
 * one chart per mount, the same chart through every prop change and every
 * deactivation, and after unmount nothing left listening, observing or
 * ticking on the page. tests/vue-reactivity.test.ts covers why the chart must
 * stay out of `ref()`.
 */

interface Instance { kind: 'chart' | 'widget'; chart: Chart; widget: Widget | null }
interface ExampleState {
  symbol: string; interval: string; theme: 'dark' | 'light'; view: 'chart' | 'widget';
  mounted: boolean; created: number; destroyed: number; status: string;
}
interface Tracked { listeners: string[]; containerListeners: number; observations: number; intervals: number }

declare global {
  interface Window {
    openalgoVueExample: { state: ExampleState; feed: { getBars(request: { symbol: string }): Promise<unknown[]> }; instances: Instance[] };
    __vueHeld?: { symbol: string; release(): void }[];
    __vueLeaks: { snapshot(containers: readonly Element[]): Tracked; framesSince(mark: number): number; mark(): number };
    __vueFirst?: Chart;
  }
}

const PAGE = '/examples/vue/index.html';

/**
 * Installed before any page script: a ledger of every event listener, every
 * observed element and every interval timer, so a teardown can be compared
 * with the page before the chart existed. Listeners on a node that has left
 * the document go with the node; everything else (window, document, media
 * queries, elements still on the page) must be released.
 */
function installLedger(): void {
  const listeners = new Map<EventTarget, Map<string, Set<unknown>>>();
  const add = EventTarget.prototype.addEventListener;
  const remove = EventTarget.prototype.removeEventListener;
  const captureOf = (options: unknown): boolean =>
    typeof options === 'boolean' ? options : !!(options as { capture?: boolean } | undefined)?.capture;
  const forget = (target: EventTarget, type: string, listener: unknown, capture: boolean): void => {
    const key = `${type}|${capture}`;
    const set = listeners.get(target)?.get(key);
    set?.delete(listener);
    if (set?.size === 0) listeners.get(target)!.delete(key);
  };
  EventTarget.prototype.addEventListener = function (this: EventTarget, type: string, listener: unknown, options?: unknown) {
    if (listener !== null && listener !== undefined) {
      const capture = captureOf(options);
      const key = `${type}|${capture}`;
      let byKey = listeners.get(this);
      if (!byKey) { byKey = new Map(); listeners.set(this, byKey); }
      let set = byKey.get(key);
      if (!set) { set = new Set(); byKey.set(key, set); }
      set.add(listener);
      const opts = typeof options === 'object' && options !== null ? options as { once?: boolean; signal?: AbortSignal } : {};
      // Listeners the platform removes by itself are removed here too.
      if (opts.once) add.call(this, type, () => forget(this, type, listener, capture), { once: true, capture });
      if (opts.signal) add.call(opts.signal, 'abort', () => forget(this, type, listener, capture), { once: true });
    }
    return add.call(this, type, listener as EventListener, options as AddEventListenerOptions);
  };
  EventTarget.prototype.removeEventListener = function (this: EventTarget, type: string, listener: unknown, options?: unknown) {
    forget(this, type, listener, captureOf(options));
    return remove.call(this, type, listener as EventListener, options as EventListenerOptions);
  };
  const mql = window.MediaQueryList?.prototype as (MediaQueryList & { addListener?: (l: unknown) => void; removeListener?: (l: unknown) => void }) | undefined;
  // The legacy media query calls do not go through addEventListener, so they
  // are routed there, which is what they are equivalent to.
  if (mql?.addListener) {
    mql.addListener = function (this: MediaQueryList, l: unknown) { this.addEventListener('change', l as EventListener); };
    mql.removeListener = function (this: MediaQueryList, l: unknown) { this.removeEventListener('change', l as EventListener); };
  }

  const observations = new Map<object, Set<unknown>>();
  for (const name of ['ResizeObserver', 'MutationObserver', 'IntersectionObserver'] as const) {
    const Base = (window as unknown as Record<string, new (...args: unknown[]) => { observe(t: unknown, o?: unknown): void; disconnect(): void; unobserve?(t: unknown): void }>)[name];
    if (typeof Base !== 'function') continue;
    const Observed = class extends Base {
      constructor(...args: unknown[]) { super(...args); observations.set(this, new Set()); }
      observe(target: unknown, options?: unknown): void { observations.get(this)!.add(target); super.observe(target, options); }
      unobserve(target: unknown): void { observations.get(this)!.delete(target); super.unobserve?.(target); }
      disconnect(): void { observations.get(this)!.clear(); super.disconnect(); }
    };
    Object.defineProperty(window, name, { value: Observed, configurable: true, writable: true });
  }

  const intervals = new Set<unknown>();
  const setI = window.setInterval.bind(window), clearI = window.clearInterval.bind(window);
  window.setInterval = ((handler: TimerHandler, ms?: number, ...args: unknown[]) => {
    const id = setI(handler, ms, ...args);
    intervals.add(id);
    return id;
  }) as typeof window.setInterval;
  window.clearInterval = ((id?: number) => { intervals.delete(id); clearI(id); }) as typeof window.clearInterval;

  let frames = 0;
  const raf = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = (cb: FrameRequestCallback) => { frames++; return raf(cb); };

  const describe = (target: EventTarget): string => {
    if (target === window) return 'window';
    if (target === document) return 'document';
    if (target instanceof Element) return `${target.tagName.toLowerCase()}${target.id ? '#' + target.id : ''}${target.getAttribute('data-control') ? '[' + target.getAttribute('data-control') + ']' : ''}`;
    if (typeof MediaQueryList !== 'undefined' && target instanceof MediaQueryList) return `media ${target.media}`;
    return target.constructor?.name ?? 'target';
  };
  window.__vueLeaks = {
    snapshot(containers) {
      const live: string[] = [];
      let containerListeners = 0;
      for (const [target, byKey] of listeners) {
        const inContainer = target instanceof Node && containers.some(c => c === target || c.contains(target));
        for (const [key, set] of byKey) {
          if (set.size === 0) continue;
          if (inContainer) containerListeners += set.size;
          if (!(target instanceof Node) || target.isConnected) live.push(`${describe(target)} ${key} x${set.size}`);
        }
      }
      let observed = 0;
      for (const targets of observations.values()) observed += targets.size;
      return { listeners: live.sort(), containerListeners, observations: observed, intervals: intervals.size };
    },
    mark: () => frames,
    framesSince: (mark) => frames - mark,
  };
}

async function open(page: Page, query = ''): Promise<string[]> {
  const problems: string[] = [];
  page.on('pageerror', error => problems.push(`pageerror: ${error.message}`));
  page.on('console', message => {
    if (message.type() === 'error' || /\[Vue warn\]/.test(message.text())) problems.push(`${message.type()}: ${message.text()}`);
  });
  await page.addInitScript(installLedger);
  await page.setViewportSize({ width: 1100, height: 700 });
  await page.goto(`${PAGE}${query}`);
  await page.waitForFunction(() => window.openalgoVueExample !== undefined);
  return problems;
}

/** Candle-coloured pixels on the price pane of the given instance, in the theme it is using now. */
async function candlePixels(page: Page, index: number): Promise<number> {
  return page.evaluate((i) => {
    const { chart } = window.openalgoVueExample.instances[i];
    const theme = chart.theme();
    const canvas = chart.panes()[0].base.element;
    const data = canvas.getContext('2d')!.getImageData(0, 0, canvas.width, canvas.height).data;
    const rgb = (hex: string) => [1, 3, 5].map(k => parseInt(hex.slice(k, k + 2), 16));
    const colours = [rgb(theme.upColor), rgb(theme.downColor)];
    let n = 0;
    for (let p = 0; p < data.length; p += 4) {
      if (data[p + 3] > 0 && colours.some(c => Math.abs(data[p] - c[0]) < 24 && Math.abs(data[p + 1] - c[1]) < 24 && Math.abs(data[p + 2] - c[2]) < 24)) n++;
    }
    return n;
  }, index);
}

async function waitForStatus(page: Page, text: RegExp): Promise<void> {
  await expect(page.locator('[data-status] span').first()).toHaveText(text);
}

test('mounts one chart, paints candles, and follows prop changes without a new chart', async ({ page }) => {
  const problems = await open(page);
  await waitForStatus(page, /^NIFTY 5m, \d+ bars$/);
  await expect.poll(() => candlePixels(page, 0)).toBeGreaterThan(400);
  const first = await page.evaluate(() => {
    const { instances } = window.openalgoVueExample;
    window.__vueFirst = instances[0].chart;
    const bars = instances[0].chart.primaryBars();
    return { count: instances.length, kind: instances[0].kind, close: bars[bars.length - 1].close, context: instances[0].chart.getDataContext() };
  });
  expect(first.count).toBe(1);
  expect(first.kind).toBe('chart');
  expect(first.close).toBeGreaterThan(20_000);
  expect(first.context).toMatchObject({ symbol: 'NIFTY', exchange: 'NSE', interval: '5m' });

  await page.locator('[data-control="symbol"]').selectOption('RELIANCE');
  await waitForStatus(page, /^RELIANCE 5m, \d+ bars$/);
  await page.locator('[data-control="interval"]').selectOption('15m');
  await waitForStatus(page, /^RELIANCE 15m, \d+ bars$/);
  const after = await page.evaluate(() => {
    const { instances } = window.openalgoVueExample;
    const chart = instances[0].chart;
    const bars = chart.primaryBars();
    return {
      count: instances.length, same: chart === window.__vueFirst, destroyed: chart.isDestroyed,
      series: chart.panes()[0].series().length, close: bars[bars.length - 1].close,
      step: bars[1].time - bars[0].time, context: chart.getDataContext(),
    };
  });
  // setData on the same series of the same chart: no second chart, no second series.
  expect(after).toMatchObject({ count: 1, same: true, destroyed: false, series: 1, step: 900 });
  expect(after.close).toBeGreaterThan(2_000);
  expect(after.close).toBeLessThan(4_000);
  expect(after.context).toMatchObject({ symbol: 'RELIANCE', interval: '15m' });
  await expect.poll(() => candlePixels(page, 0)).toBeGreaterThan(400);
  expect(problems).toEqual([]);
});

test('a slow answer for an older symbol never replaces a newer one', async ({ page }) => {
  const problems = await open(page);
  await waitForStatus(page, /^NIFTY 5m/);
  // Hold every request until the test lets it go, then answer the newer one
  // first: the older answer arriving last is the case the guard exists for.
  await page.evaluate(() => {
    const { feed } = window.openalgoVueExample;
    const real = feed.getBars.bind(feed);
    window.__vueHeld = [];
    feed.getBars = request => new Promise((resolve, reject) => {
      window.__vueHeld!.push({ symbol: request.symbol, release: () => real(request).then(resolve, reject) });
    });
  });
  await page.locator('[data-control="symbol"]').selectOption('BANKNIFTY');
  await expect.poll(() => page.evaluate(() => window.__vueHeld!.length)).toBe(1);
  await page.locator('[data-control="symbol"]').selectOption('RELIANCE');
  await expect.poll(() => page.evaluate(() => window.__vueHeld!.map(h => h.symbol))).toEqual(['BANKNIFTY', 'RELIANCE']);
  await page.evaluate(() => window.__vueHeld![1].release());
  await waitForStatus(page, /^RELIANCE 5m/);
  await page.evaluate(() => window.__vueHeld![0].release());
  await page.waitForTimeout(100);
  const shown = await page.evaluate(() => {
    const chart = window.openalgoVueExample.instances[0].chart;
    const bars = chart.primaryBars();
    return { symbol: chart.getDataContext()?.symbol, close: bars[bars.length - 1].close, status: window.openalgoVueExample.state.status };
  });
  expect(shown.symbol).toBe('RELIANCE');
  expect(shown.close).toBeLessThan(4_000);
  expect(shown.status).toMatch(/^RELIANCE 5m/);
  expect(problems).toEqual([]);
});

test('follows the container size and switches theme in place', async ({ page }) => {
  const problems = await open(page);
  await waitForStatus(page, /^NIFTY 5m/);
  const width = () => page.evaluate(() => {
    const { chart } = window.openalgoVueExample.instances[0];
    const el = document.querySelector<HTMLElement>('[data-view="chart"]')!;
    return { canvas: chart.panes()[0].base.element.width, css: el.clientWidth, dpr: devicePixelRatio };
  });
  const wide = await width();
  expect(wide.canvas).toBe(Math.round(wide.css * wide.dpr));
  await page.setViewportSize({ width: 720, height: 560 });
  await expect.poll(async () => { const w = await width(); return w.canvas === Math.round(w.css * w.dpr) && w.css < wide.css; }).toBe(true);
  await expect.poll(() => candlePixels(page, 0)).toBeGreaterThan(300);

  const background = () => page.evaluate(() => {
    const { chart } = window.openalgoVueExample.instances[0];
    const canvas = chart.panes()[0].base.element;
    const [r, g, b] = canvas.getContext('2d')!.getImageData(4, 4, 1, 1).data;
    return { pixel: [r, g, b], theme: chart.theme().background };
  });
  const dark = await background();
  expect(dark.theme).toBe('#0d0e12');
  expect(Math.max(...dark.pixel)).toBeLessThan(40);
  await page.locator('[data-control="theme"]').click();
  await expect.poll(async () => Math.min(...(await background()).pixel)).toBeGreaterThan(230);
  const light = await background();
  expect(light.theme).toBe('#ffffff');
  await expect.poll(() => candlePixels(page, 0)).toBeGreaterThan(300);
  expect(await page.evaluate(() => window.openalgoVueExample.instances.length)).toBe(1);
  expect(problems).toEqual([]);
});

test('KeepAlive keeps the chart through a view switch, and the widget binds back with v-model', async ({ page }) => {
  const problems = await open(page);
  await waitForStatus(page, /^NIFTY 5m/);
  await page.evaluate(() => { window.__vueFirst = window.openalgoVueExample.instances[0].chart; });

  await page.locator('[data-control="view-widget"]').click();
  await expect(page.locator('[data-view="widget"] .oac-widget')).toBeVisible();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances.length)).toBe(2);
  const parked = await page.evaluate(() => {
    const [chart, widget] = window.openalgoVueExample.instances;
    return {
      kinds: [chart.kind, widget.kind], chartDestroyed: chart.chart.isDestroyed,
      chartAttached: chart.chart.panes()[0].base.element.isConnected, widgetHasChart: widget.widget?.chart === widget.chart,
    };
  });
  expect(parked).toEqual({ kinds: ['chart', 'widget'], chartDestroyed: false, chartAttached: false, widgetHasChart: true });
  await expect.poll(() => candlePixels(page, 1)).toBeGreaterThan(400);

  // The widget's own controls report back through v-model: its interval pill
  // moves the page's select, and the page's theme reaches the widget.
  await page.locator('[data-view="widget"]').getByRole('radio', { name: 'Interval 15m', exact: true }).click();
  await expect(page.locator('[data-control="interval"]')).toHaveValue('15m');
  await page.locator('[data-control="theme"]').click();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances[1].widget!.theme())).toBe('light');
  await page.locator('[data-control="symbol"]').selectOption('BANKNIFTY');
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances[1].widget!.symbol())).toBe('BANKNIFTY');

  // Back to the chart: the same instance, reattached, carrying every change
  // made while it was parked, painted at its container's size.
  await page.locator('[data-control="view-chart"]').click();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances[0].chart.panes()[0].base.element.isConnected)).toBe(true);
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances[0].chart.getDataContext()?.symbol)).toBe('BANKNIFTY');
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances[0].chart.primaryBars().length)).toBeGreaterThan(100);
  const back = await page.evaluate(() => {
    const { instances } = window.openalgoVueExample;
    const chart = instances[0].chart;
    const bars = chart.primaryBars();
    const el = document.querySelector<HTMLElement>('[data-view="chart"]')!;
    return {
      count: instances.length, same: chart === window.__vueFirst, destroyed: chart.isDestroyed, widgetDestroyed: instances[1].chart.isDestroyed,
      context: chart.getDataContext(), close: bars[bars.length - 1].close, step: bars[1].time - bars[0].time,
      theme: chart.theme().background, canvas: chart.panes()[0].base.element.width, css: el.clientWidth, dpr: devicePixelRatio,
    };
  });
  expect(back).toMatchObject({ count: 2, same: true, destroyed: false, widgetDestroyed: false, step: 900, theme: '#ffffff' });
  expect(back.context).toMatchObject({ symbol: 'BANKNIFTY', interval: '15m' });
  expect(back.close).toBeGreaterThan(40_000);
  expect(back.canvas).toBe(Math.round(back.css * back.dpr));
  await expect.poll(() => candlePixels(page, 0)).toBeGreaterThan(400);
  expect(problems).toEqual([]);
});

test('a deactivated chart keeps its viewport', async ({ page }) => {
  const problems = await open(page);
  await waitForStatus(page, /^NIFTY 5m/);
  const range = () => page.evaluate(() => window.openalgoVueExample.instances[0].chart.getVisibleLogicalRange());
  // Somewhere other than the default view, so a reset would show.
  await page.evaluate(() => {
    const { chart } = window.openalgoVueExample.instances[0];
    const r = chart.getVisibleLogicalRange();
    chart.setVisibleLogicalRange({ from: r.from - 40, to: r.to - 60 });
  });
  const before = await range();
  await page.locator('[data-control="view-widget"]').click();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances.length)).toBe(2);
  await page.locator('[data-control="view-chart"]').click();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances[0].chart.panes()[0].base.element.isConnected)).toBe(true);
  await page.evaluate(() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r))));
  const after = await range();
  expect(after.from).toBeCloseTo(before.from, 3);
  expect(after.to).toBeCloseTo(before.to, 3);
  expect(problems).toEqual([]);
});

test('v-if unmount destroys every chart and leaves nothing listening, and a remount works', async ({ page }) => {
  const problems = await open(page, '?mounted=0');
  await expect(page.locator('.empty')).toBeVisible();
  // The baseline is not zero: the test driver keeps an observer of its own.
  const baseline = await page.evaluate(() => window.__vueLeaks.snapshot([]));

  // Mount, then open the widget as well, so KeepAlive holds two.
  await page.locator('[data-control="mounted"]').check();
  await waitForStatus(page, /^NIFTY 5m/);
  await expect.poll(() => candlePixels(page, 0)).toBeGreaterThan(400);
  await page.locator('[data-control="view-widget"]').click();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances.length)).toBe(2);
  await expect.poll(() => candlePixels(page, 1)).toBeGreaterThan(400);
  const holders = await page.evaluateHandle(() => [
    document.querySelector('[data-view="widget"]'),
    window.openalgoVueExample.instances[0].chart.panes()[0].base.element.closest('.oac-vue-chart'),
  ]);
  const busy = await page.evaluate(() => window.__vueLeaks.snapshot([]));
  expect(busy.observations).toBeGreaterThan(baseline.observations);
  expect(busy.listeners.length).toBeGreaterThan(baseline.listeners.length);

  await page.locator('[data-control="mounted"]').uncheck();
  await expect(page.locator('.empty')).toBeVisible();
  const gone = await page.evaluate((els) => {
    const { instances, state } = window.openalgoVueExample;
    return {
      destroyed: instances.map(i => i.chart.isDestroyed),
      counted: [state.created, state.destroyed],
      empty: (els as Element[]).map(el => el.childElementCount),
      attached: (els as Element[]).map(el => el.isConnected),
      ledger: window.__vueLeaks.snapshot(els as Element[]),
    };
  }, holders);
  expect(gone.destroyed).toEqual([true, true]);
  expect(gone.counted).toEqual([2, 2]);
  expect(gone.empty).toEqual([0, 0]);
  expect(gone.attached).toEqual([false, false]);
  expect(gone.ledger.listeners).toEqual(baseline.listeners);
  expect(gone.ledger.containerListeners).toBe(0);
  expect(gone.ledger.observations).toBe(baseline.observations);
  expect(gone.ledger.intervals).toBe(baseline.intervals);
  // Nothing asks for frames once both charts are gone.
  const mark = await page.evaluate(() => window.__vueLeaks.mark());
  await page.waitForTimeout(400);
  expect(await page.evaluate((m) => window.__vueLeaks.framesSince(m), mark)).toBe(0);

  // A remount builds a new chart into a new container and paints it.
  await page.locator('[data-control="mounted"]').check();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances.length)).toBe(3);
  const remounted = await page.evaluate(() => {
    const [a, b, c] = window.openalgoVueExample.instances;
    return { kind: c.kind, fresh: c.chart !== a.chart && c.chart !== b.chart, destroyed: c.chart.isDestroyed };
  });
  // The view was left on the widget, so the remount builds a widget.
  expect(remounted).toEqual({ kind: 'widget', fresh: true, destroyed: false });
  await expect.poll(() => candlePixels(page, 2)).toBeGreaterThan(400);
  // And the bare chart, which KeepAlive no longer holds, is built again too.
  await page.locator('[data-control="view-chart"]').click();
  await expect.poll(() => page.evaluate(() => window.openalgoVueExample.instances.length)).toBe(4);
  expect(await page.evaluate(() => {
    const { instances } = window.openalgoVueExample;
    return [instances[3].kind, instances[3].chart !== instances[0].chart, instances[3].chart.isDestroyed];
  })).toEqual(['chart', true, false]);
  await expect.poll(() => candlePixels(page, 3)).toBeGreaterThan(400);
  await page.locator('[data-control="mounted"]').uncheck();
  await expect(page.locator('.empty')).toBeVisible();
  expect(await page.evaluate(() => window.openalgoVueExample.instances.map(i => i.chart.isDestroyed))).toEqual([true, true, true, true]);
  const again = await page.evaluate(() => window.__vueLeaks.snapshot([]));
  expect(again.listeners).toEqual(baseline.listeners);
  expect(again.observations).toBe(baseline.observations);
  expect(again.intervals).toBe(baseline.intervals);
  expect(problems).toEqual([]);
});
