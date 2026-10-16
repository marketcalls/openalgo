/**
 * Regression tests for the two cross-wiring defects the 1.3.0 release audit
 * found. Both are the same shape: a thing added on one side of a seam with
 * nothing on the other side reading it, which a per-module suite cannot see
 * because each module's own tests import past the seam.
 *
 * 1. `src/draw/clipboard.ts` was never re-exported from the draw tier entry, so
 *    `DrawingControllerOptions.clipboard` and `DrawingController.clipboard()`
 *    referred to types no consumer of the package could name. Its own test file
 *    imports `../src/draw/clipboard` directly, which is exactly why the gap
 *    survived a green suite.
 * 2. `Chart.isDestroyed` and the `'destroy'` event were added for a link group
 *    to use, and the link group used neither: it inferred death from an empty
 *    pane list and only ever checked on the next channel event.
 */
import { describe, it, expect, beforeEach, vi, afterEach } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import { createLinkGroup, withBarCache } from '../src/index';
import type { LinkChart } from '../src/index';
// Deliberately the tier entry, not the module: that is the seam under test.
import {
  DrawingController,
  DrawingClipboard,
  clearMemoryClipboard,
  systemClipboard,
  encodeClipboardPayload,
  decodeClipboardPayload,
  sanitizeDrawing,
  DRAWING_CLIPBOARD_KEY,
  DRAWING_CLIPBOARD_VERSION,
  type ClipboardPort,
  type DrawingClipboardOptions,
} from '../src/draw/index';
import type { Drawing } from '../src/draw/types';

const DAY = 86400;
const T0 = 1700438400;
const bar = (i: number): Bar => ({
  time: T0 + i * DAY, open: 100 + i, high: 101 + i, low: 99 + i, close: 100 + i,
});
const bars: Bar[] = Array.from({ length: 20 }, (_, i) => bar(i));

function makeChart(): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars);
  chart.fitContent();
  return chart;
}

beforeEach(() => {
  vi.stubGlobal('window', {});
  clearMemoryClipboard();
});
afterEach(() => { vi.unstubAllGlobals(); });

describe('the draw tier entry exposes the clipboard its own options are typed on', () => {
  it('exports the port type the controller option is declared as, usably', () => {
    // Compile-time half: `clipboard` is `ClipboardPort | null`, so a host that
    // cannot name `ClipboardPort` cannot write this at all.
    const port: ClipboardPort = {
      writeText: async () => {},
      readText: async () => '',
    };
    const chart = makeChart();
    const controller = new DrawingController(chart as never, { clipboard: port });
    // Runtime half: `clipboard()` hands back the exported class, not an opaque.
    expect(controller.clipboard()).toBeInstanceOf(DrawingClipboard);
    controller.destroy();
    chart.destroy();
  });

  it('exports a standalone clipboard a host can construct and round-trip through', async () => {
    const options: DrawingClipboardOptions = { port: null, fallbackToMemory: true };
    const clip = new DrawingClipboard(options);
    const drawing: Drawing = {
      id: 'd1',
      tool: 'trend-line',
      points: [{ time: T0, price: 100 }, { time: T0 + 3 * DAY, price: 110 }],
      style: { color: '#ff0000', lineWidth: 2 },
      paneIndex: 0,
      zIndex: 0,
    };
    expect(await clip.write([drawing])).toBe(true);
    // The copy reached memory but not the OS clipboard, and the host can find
    // that out: it is the difference between "works in this tab" and "works".
    expect(clip.lastError()).toContain('no system clipboard');
    const back = await clip.read();
    expect(back).not.toBeNull();
    expect(back).toHaveLength(1);
    expect((back as Omit<Drawing, 'id'>[])[0].points).toEqual(drawing.points);
  });

  it('exports the encode / decode / sanitize trio and the payload key', () => {
    expect(DRAWING_CLIPBOARD_KEY).toBe('openalgo-charts/drawings');
    // Tracks DRAWING_STATE_VERSION: the 2.0 model changed the on-wire shape,
    // and version 3 added the interval range a drawing is shown on.
    expect(DRAWING_CLIPBOARD_VERSION).toBe(3);
    const text = encodeClipboardPayload([{
      id: 'x', tool: 'rectangle',
      points: [{ time: T0, price: 1 }, { time: T0 + DAY, price: 2 }],
      style: {}, paneIndex: 0, zIndex: 0,
    }]);
    expect(JSON.parse(text)).toHaveProperty(DRAWING_CLIPBOARD_KEY);
    expect(decodeClipboardPayload(text)).toHaveLength(1);
    expect(decodeClipboardPayload('a spreadsheet cell')).toBeNull();
    expect(sanitizeDrawing({ tool: 'not-a-tool', points: [] })).toBeNull();
  });

  it('exports the system-clipboard probe, so a host need not feature-detect by hand', () => {
    expect(systemClipboard()).toBeNull();          // no navigator.clipboard here
    vi.stubGlobal('navigator', { clipboard: { writeText: async () => {}, readText: async () => '' } });
    expect(systemClipboard()).not.toBeNull();
  });
});

describe('a link group lets go of a destroyed chart the moment it dies', () => {
  it('drops the member on the destroy event, not at the next channel event', () => {
    const a = makeChart();
    const b = makeChart();
    const group = createLinkGroup({ crosshair: true, viewport: true });
    group.add(a);
    group.add(b);
    expect(group.has(b)).toBe(true);

    b.destroy();
    // `has` does not prune, so before the fix this stayed true until some other
    // call happened to sweep, and the group kept the dead chart and every
    // listener closure it captured.
    expect(group.has(b)).toBe(false);
    expect(group.members()).toEqual([a]);

    group.destroy();
    a.destroy();
  });

  it('believes the chart flag over the pane-count inference', () => {
    // A chart that says it is destroyed while still reporting panes: the flag
    // wins, because it is the only one of the two that cannot be a coincidence.
    const zombie = {
      isDestroyed: true,
      on: () => () => {},
      getVisibleLogicalRange: () => ({ from: 0, to: 10 }),
      setVisibleLogicalRange: () => {},
      dataLayer: {
        length: 0,
        indexToTime: () => undefined,
        timeToIndex: () => undefined,
        indexToTimeFloat: () => 0,
        timeToIndexFloat: () => 0,
      },
      panes: () => [{}, {}],
      addPrimitive: () => { throw new Error('must not touch a destroyed chart'); },
      removePrimitive: () => { throw new Error('must not touch a destroyed chart'); },
    } satisfies LinkChart;

    const group = createLinkGroup();
    group.add(zombie);
    expect(group.has(zombie)).toBe(false);
    expect(group.members()).toEqual([]);
    group.destroy();
  });

  it('a chart destroyed after the group was built stops receiving linked crosshairs', () => {
    const leader = makeChart();
    const follower = makeChart();
    const group = createLinkGroup({ crosshair: true, viewport: false });
    group.add(leader);
    group.add(follower);
    follower.destroy();
    // Any broadcast after this must not reach the corpse. `addPrimitive` on a
    // destroyed chart would recreate pane 0, which is the concrete damage.
    leader.setVisibleLogicalRange({ from: 2, to: 12 });
    expect(follower.panes()).toHaveLength(0);
    expect(group.members()).toEqual([leader]);
    group.destroy();
    leader.destroy();
  });
});

describe('the bar cache is a transparent wrapper, not a narrowing one', () => {
  it('forwards the arguments a DataFeed does not declare but a live feed reads', () => {
    // `OpenAlgoLiveDataFeed.subscribeBars` takes a third argument (seedFrom,
    // cumDayVolumeSoFar) that the `DataFeed` interface does not declare. A
    // wrapper that forwarded only the two declared ones would silently stop a
    // live bar continuing the last history bar's bucket, with nothing anywhere
    // reporting it: the types are satisfied either way.
    const seen: unknown[][] = [];
    const source = {
      getBars: async (): Promise<Bar[]> => bars,
      subscribeBars: (...args: unknown[]) => { seen.push(args); return () => {}; },
      subscribeDepth: (...args: unknown[]) => { seen.push(args); return () => {}; },
    };
    const cache = withBarCache(source as never);
    const req = { symbol: 'INFY', exchange: 'NSE', interval: '1m' };
    const onBar = (): void => {};
    const opts = { seedFrom: bars[bars.length - 1], cumDayVolumeSoFar: 1234 };
    (cache.subscribeBars as (...a: unknown[]) => unknown)(req, onBar, opts);
    (cache.subscribeDepth as (...a: unknown[]) => unknown)(req, onBar, 'extra');

    expect(seen).toHaveLength(2);
    expect(seen[0]).toEqual([req, onBar, opts]);
    expect(seen[1]).toEqual([req, onBar, 'extra']);
  });

  it('still hides an optional method the wrapped feed does not have', () => {
    // Feature detection on `subscribeBars` is how the codebase tells a
    // history-only feed from a live one, so the wrapper must not grow a stub.
    const historyOnly = { getBars: async (): Promise<Bar[]> => bars };
    const cache = withBarCache(historyOnly as never);
    expect(cache.subscribeBars).toBeUndefined();
    expect(cache.subscribeDepth).toBeUndefined();
  });
});
