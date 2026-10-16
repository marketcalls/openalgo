/**
 * The render backend port (src/render/backend.ts). The load-bearing claim is
 * that routing the series pass through a backend changes nothing about what
 * the chart paints: the 2D backend must produce the op stream the pane
 * produced when it called the renderer itself, op for op. The rest checks
 * that the option is actually threaded (declared, resolved, consumed) and
 * that the pane hands a backend exactly the series pass and nothing else.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import { Pane } from '../src/core/pane';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx, type RecordingContext, type Op } from './helpers/fake-ctx';
import {
  createRenderBackend, registerRenderBackend, unregisterRenderBackend, registeredRenderBackends,
  resolveRenderBackend, type IRenderBackend, type RenderBackendKind,
} from '../src/render/backend';
import { Canvas2dBackend } from '../src/render/canvas2d-backend';
import { getChartType, type DrawItem, type RendererEntry, type SeriesRenderContext } from '../src/model/chart-type-registry';
import { candleGeometry, drawCandles, optimalBarWidth, DEFAULT_CANDLE_STYLE, type CandleDrawItem } from '../src/render/candles';
import type { SeriesStyle } from '../src/render/series-style';
import type { Bar } from '../src/model/bar';

const T0 = 1_700_000_000;

/** Deterministic OHLCV, the shape the parity spec uses. */
function bars(count: number): Bar[] {
  const out: Bar[] = [];
  let p = 100;
  for (let i = 0; i < count; i++) {
    const o = p;
    p += Math.sin(i / 9) * 1.5 + ((i % 7) - 3) * 0.3;
    out.push({ time: T0 + i * 300, open: o, high: Math.max(o, p) + 1, low: Math.min(o, p) - 1, close: p, volume: 100 + i });
  }
  return out;
}

/**
 * A chart that paints synchronously (CLAUDE.md: without `applySize` and a
 * synchronous raf every scale sits on its 0..1 placeholder and the frame
 * proves nothing).
 */
function makeChart(options: ChartOptions = {}): Chart {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(),
    pixelRatio: () => 1,
    shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...options,
  });
  chart.applySize(800, 600);
  return chart;
}

/** The recording context behind a pane's base canvas. */
function baseOps(chart: Chart, pane = 0): Op[] {
  return (chart.panes()[pane].base.ctx as unknown as RecordingContext).ops;
}

/** A candlestick pane and a histogram pane, drawn once. */
function loaded(options: ChartOptions = {}): Chart {
  const chart = makeChart(options);
  const data = bars(120);
  chart.addSeries('candlestick').setData(data);
  chart.addSeries('histogram', { paneIndex: 1 }).setData(
    data.map((b) => ({ time: b.time, open: 0, high: b.volume ?? 0, low: 0, close: b.volume ?? 0 })),
  );
  chart.fitContent();
  return chart;
}

interface SeriesCall {
  entry: RendererEntry;
  items: readonly DrawItem[];
  priceToY: (p: number) => number;
  barSpacing: number;
  dpr: number;
  style: SeriesStyle;
  rc: SeriesRenderContext;
}

/** A backend that records what the pane asks of it and paints nothing. */
class SpyBackend implements IRenderBackend {
  public readonly kind: RenderBackendKind;
  public mounted: { canvas: HTMLCanvasElement; ctx2d: CanvasRenderingContext2D | null } | null = null;
  public resizes: [number, number, number][] = [];
  public frames: boolean[] = [];
  public ends = 0;
  public destroyed = 0;
  public calls: SeriesCall[] = [];
  /** The log of lifecycle calls in order, to assert begin/series/end framing. */
  public log: string[] = [];

  public constructor(kind: RenderBackendKind = 'webgl2') {
    this.kind = kind;
  }

  public mount(canvas: HTMLCanvasElement, ctx2d: CanvasRenderingContext2D | null): void {
    this.mounted = { canvas, ctx2d };
  }
  public resize(w: number, h: number, dpr: number): void { this.resizes.push([w, h, dpr]); }
  public beginFrame(clear: boolean): void { this.frames.push(clear); this.log.push('begin'); }
  public drawSeries(
    entry: RendererEntry, items: readonly DrawItem[], priceToY: (p: number) => number,
    barSpacing: number, dpr: number, style: SeriesStyle, rc: SeriesRenderContext,
  ): void {
    this.calls.push({ entry, items, priceToY, barSpacing, dpr, style, rc });
    this.log.push('series');
  }
  public endFrame(): void { this.ends++; this.log.push('end'); }
  public overlay2d(): CanvasRenderingContext2D | null { return this.mounted?.ctx2d ?? null; }
  public destroy(): void { this.destroyed++; }
}

afterEach(() => {
  unregisterRenderBackend('webgl2');
});

describe('candleGeometry', () => {
  const DPR = 1;

  it('is the snapping and parity rule drawCandles used inline', () => {
    for (const dpr of [1, 1.5, 2, 3]) {
      for (const spacing of [1, 1.5, 2, 3, 6, 12, 24]) {
        for (const x of [0, 4.2, 17.5, 200.49, 200.5]) {
          const g = candleGeometry(x, spacing, dpr);
          const bodyW = optimalBarWidth(spacing, dpr);
          const wickW = Math.max(1, Math.floor(dpr));
          const cx = Math.round(x * dpr);
          expect(g).toEqual({ cx, bodyX: cx - Math.floor(bodyW / 2), bodyW, wickX: cx - Math.floor(wickW / 2), wickW });
        }
      }
    }
  });

  it('scales the body per bar, clamped to 0.05..1 and never below one pixel', () => {
    const full = candleGeometry(50, 24, DPR);
    expect(full.bodyW).toBe(optimalBarWidth(24, DPR));
    expect(candleGeometry(50, 24, DPR, 1).bodyW).toBe(full.bodyW);
    expect(candleGeometry(50, 24, DPR, 0.5).bodyW).toBe(Math.max(1, Math.round(full.bodyW * 0.5)));
    // Below the floor and above the ceiling both clamp rather than vanish or grow.
    expect(candleGeometry(50, 24, DPR, 0)).toEqual(candleGeometry(50, 24, DPR, 0.05));
    expect(candleGeometry(50, 24, DPR, 4)).toEqual(full);
    expect(candleGeometry(50, 2, DPR, 0.05).bodyW).toBe(1);
    // The body stays centred on the wick whatever the scale did to its width.
    const half = candleGeometry(50, 24, DPR, 0.5);
    expect(half.bodyX).toBe(half.cx - Math.floor(half.bodyW / 2));
  });

  it('is what drawCandles paints: the body and wick rects come from it', () => {
    const items: CandleDrawItem[] = [
      { x: 4.4, bar: { time: 0, open: 10, high: 14, low: 9, close: 12 } },
      { x: 30.6, bar: { time: 1, open: 12, high: 13, low: 6, close: 7, volume: 50 } },
    ];
    const priceToY = (p: number): number => 40 - p * 2;
    const style = { ...DEFAULT_CANDLE_STYLE, borderVisible: false, widthScale: (b: Bar) => (b.volume === undefined ? 1 : 0.5) };
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, items, priceToY, 12, 2, style);
    const fills = rec.ops.filter((o) => o.type === 'fillRect');
    expect(fills).toHaveLength(4);
    for (let i = 0; i < items.length; i++) {
      const geo = candleGeometry(items[i].x, 12, 2, style.widthScale(items[i].bar));
      const [wick, body] = [fills[i * 2], fills[i * 2 + 1]];
      expect([wick.args[0], wick.args[2]]).toEqual([geo.wickX, geo.wickW]);
      expect([body.args[0], body.args[2]]).toEqual([geo.bodyX, geo.bodyW]);
    }
  });
});

describe('Canvas2dBackend', () => {
  it('draws on the context it is handed, through the entry renderer, with every argument intact', () => {
    const backend = new Canvas2dBackend();
    const { ctx, rec } = makeCtx();
    const canvas = { width: 100, height: 50, getContext: () => makeCtx().ctx } as unknown as HTMLCanvasElement;
    backend.mount(canvas, ctx);
    expect(backend.kind).toBe('canvas2d');
    expect(backend.overlay2d()).toBe(ctx);

    const seen: unknown[] = [];
    const entry: RendererEntry = {
      defaultStyle: {}, isPriceSeries: true,
      draw: (g, items, toY, bs, dpr, s, rc) => { seen.push(g, items, toY, bs, dpr, s, rc); g.fillRect(1, 2, 3, 4); },
      extents: (b) => ({ min: b.low, max: b.high }),
    };
    const items: DrawItem[] = [{ x: 1, bar: { time: 0, open: 1, high: 2, low: 0, close: 1 } }];
    const toY = (p: number): number => p;
    const style: SeriesStyle = { color: '#123' };
    const rc: SeriesRenderContext = { plotHeight: 10, maxVolume: 0, theme: {} as SeriesRenderContext['theme'] };
    backend.beginFrame(true);
    backend.drawSeries(entry, items, toY, 6, 2, style, rc);
    backend.endFrame();
    expect(seen).toEqual([ctx, items, toY, 6, 2, style, rc]);
    // The clear is the one CanvasLayer.clearBitmap does: reset transform, then
    // clear the whole bitmap.
    expect(rec.ops.map((o) => o.type)).toEqual(['setTransform', 'clearRect', 'fillRect']);
    expect(rec.ops[1].args).toEqual([0, 0, 100, 50]);
  });

  it('asks the canvas for a context only when the pane has none to share', () => {
    const backend = new Canvas2dBackend();
    const own = makeCtx().ctx;
    const canvas = { width: 1, height: 1, getContext: () => own } as unknown as HTMLCanvasElement;
    backend.mount(canvas, null);
    expect(backend.overlay2d()).toBe(own);
    backend.destroy();
    expect(backend.overlay2d()).toBeNull();
  });

  it('does nothing before a frame is begun with clear, or after destroy', () => {
    const backend = new Canvas2dBackend();
    const { ctx, rec } = makeCtx();
    backend.mount({ width: 1, height: 1 } as unknown as HTMLCanvasElement, ctx);
    backend.beginFrame(false);
    backend.endFrame();
    expect(rec.ops).toEqual([]);
    backend.destroy();
    backend.drawSeries(getChartType('line'), [], (p) => p, 6, 1, {}, { plotHeight: 1, maxVolume: 0, theme: {} as SeriesRenderContext['theme'] });
    expect(rec.ops).toEqual([]);
  });
});

describe('render backend registry', () => {
  it('ships canvas2d registered and resolves auto to it while nothing else is', () => {
    expect(registeredRenderBackends()).toContain('canvas2d');
    expect(registeredRenderBackends()).not.toContain('webgl2');
    expect(createRenderBackend().kind).toBe('canvas2d');
    expect(createRenderBackend('auto').kind).toBe('canvas2d');
    expect(createRenderBackend('canvas2d')).toBeInstanceOf(Canvas2dBackend);
  });

  it('refuses an explicit kind nothing registered, naming the missing tier', () => {
    expect(() => resolveRenderBackend('webgl2')).toThrow(/webgl2.*not registered/);
    expect(() => makeChart({ renderer: 'webgl2' })).toThrow(/webgl2/);
  });

  it('lets a later tier register webgl2 and auto picks it up', () => {
    registerRenderBackend('webgl2', () => new SpyBackend('webgl2'));
    expect(createRenderBackend('auto').kind).toBe('webgl2');
    expect(createRenderBackend('webgl2').kind).toBe('webgl2');
    expect(createRenderBackend('canvas2d').kind).toBe('canvas2d');
    expect(unregisterRenderBackend('webgl2')).toBe(true);
    expect(createRenderBackend('auto').kind).toBe('canvas2d');
  });

  it('falls back to canvas2d when a registered factory declines at run time', () => {
    registerRenderBackend('webgl2', () => null);
    expect(createRenderBackend('auto').kind).toBe('canvas2d');
    expect(createRenderBackend('webgl2').kind).toBe('canvas2d');
  });

  it('will not unregister the fallback', () => {
    expect(unregisterRenderBackend('canvas2d')).toBe(false);
    expect(registeredRenderBackends()).toContain('canvas2d');
  });
});

describe('the pane and the backend', () => {
  it('mounts the base canvas with its existing context, and forwards resize and destroy', () => {
    const spy = new SpyBackend();
    const pane = new Pane(fakeDocument(), spy);
    expect(pane.backend).toBe(spy);
    expect(spy.mounted?.canvas).toBe(pane.base.element);
    expect(spy.mounted?.ctx2d).toBe(pane.base.ctx);
    pane.resize(640, 480, 2);
    expect(spy.resizes).toEqual([[640, 480, 2]]);
    pane.destroy();
    expect(spy.destroyed).toBe(1);
  });

  it('defaults a bare pane to the 2D backend', () => {
    const pane = new Pane(fakeDocument());
    expect(pane.backend.kind).toBe('canvas2d');
    expect(pane.backend.overlay2d()).toBe(pane.base.ctx);
  });

  it('hands the backend exactly the series pass, framed by begin and end, per pane', () => {
    const spies: SpyBackend[] = [];
    const chart = loaded({ renderBackend: () => { const s = new SpyBackend(); spies.push(s); return s; } });
    expect(chart.renderer).toBe('webgl2');
    expect(spies).toHaveLength(2);
    for (const spy of spies) {
      // Every on-screen frame clears; the log shows one series between the
      // framing calls on each paint.
      expect(spy.frames.length).toBeGreaterThan(0);
      expect(spy.frames.every((c) => c)).toBe(true);
      expect(spy.ends).toBe(spy.frames.length);
      const last = spy.log.lastIndexOf('begin');
      expect(spy.log.slice(last)).toEqual(['begin', 'series', 'end']);
    }
    const [price, volume] = spies;
    const candle = price.calls[price.calls.length - 1];
    expect(candle.entry).toBe(getChartType('candlestick'));
    expect(candle.items.length).toBeGreaterThan(0);
    expect(candle.items.length).toBeLessThanOrEqual(120);
    expect(candle.dpr).toBe(1);
    expect(candle.barSpacing).toBe(chart.timeScale.barSpacing);
    // The projection is the pane's readout scale, measured: a placeholder
    // scale would map every price to the same y.
    const y1 = candle.priceToY(candle.items[0].bar.high);
    const y2 = candle.priceToY(candle.items[0].bar.low);
    expect(y1).toBeLessThan(y2);
    expect(candle.rc.plotHeight).toBeGreaterThan(0);
    // The bars carry volume, so the volume-candle scale reference is measured.
    expect(candle.rc.maxVolume).toBeGreaterThan(0);
    const hist = volume.calls[volume.calls.length - 1];
    expect(hist.entry).toBe(getChartType('histogram'));
    expect(hist.rc.plotHeight).toBeGreaterThan(0);
    chart.destroy();
    expect(price.destroyed).toBe(1);
    expect(volume.destroyed).toBe(1);
  });

  it('keeps the chrome on the overlay context: nothing from a series reaches it', () => {
    const chart = loaded({ renderBackend: () => new SpyBackend() });
    const ops = baseOps(chart);
    // The background fill, the grid, the axis text: the pane still draws these.
    expect(ops.some((o) => o.type === 'fillText')).toBe(true);
    expect(ops.some((o) => o.type === 'fillRect')).toBe(true);
    // The candle renderer paints one fillRect per wick; a hundred-odd rects of
    // candle width would be them. The chrome's rects are the background and
    // the tag boxes, far fewer.
    const rects = ops.filter((o) => o.type === 'fillRect');
    expect(rects.length).toBeLessThan(40);
    chart.destroy();
  });

  it('lets the factory decline and takes the 2D backend for that pane', () => {
    const chart = loaded({ renderBackend: () => null });
    expect(chart.renderer).toBe('canvas2d');
    for (const pane of chart.panes()) expect(pane.backend).toBeInstanceOf(Canvas2dBackend);
    chart.destroy();
  });

  it('reports what it actually got: auto with nothing registered is canvas2d', () => {
    const chart = loaded({ renderer: 'auto' });
    expect(chart.renderer).toBe('canvas2d');
    chart.destroy();
    registerRenderBackend('webgl2', () => new SpyBackend('webgl2'));
    const gl = loaded({ renderer: 'auto' });
    expect(gl.renderer).toBe('webgl2');
    gl.destroy();
  });
});

describe('parity through the 2D backend', () => {
  /**
   * The pre-port pane called `entry.draw(g, ...)` on its own base context
   * between the grid and the axes. A backend that does literally that, on the
   * pane's context, is the reference; the shipped 2D backend must match it op
   * for op, and so must the default (no option at all).
   */
  class DirectBackend extends Canvas2dBackend {}

  const frameOps = (options: ChartOptions): Op[][] => {
    const chart = loaded(options);
    const out = chart.panes().map((_, i) => baseOps(chart, i).map((o) => ({ ...o })));
    chart.destroy();
    return out;
  };

  it('paints the op stream the pane painted before the port existed', () => {
    const reference = frameOps({
      renderBackend: () => {
        const b = new DirectBackend();
        // Bypass the class entirely for the series pass: the renderer called
        // straight on the overlay context, as the old pane did.
        b.drawSeries = (entry, items, toY, bs, dpr, s, rc) => entry.draw(b.overlay2d() as CanvasRenderingContext2D, items, toY, bs, dpr, s, rc);
        return b;
      },
    });
    const shipped = frameOps({ renderer: 'canvas2d' });
    const defaulted = frameOps({});
    expect(shipped).toEqual(reference);
    expect(defaulted).toEqual(reference);
    // Not vacuous: the stream holds the candles (a wick fill per visible bar).
    const rects = reference[0].filter((o) => o.type === 'fillRect');
    expect(rects.length).toBeGreaterThan(100);
    expect(reference[0].filter((o) => o.type === 'clearRect')).not.toHaveLength(0);
  });

  it('is the 2D path on every frame, not only the first: a Light repaint goes through the backend too', () => {
    const spy = new SpyBackend();
    const chart = makeChart({ renderBackend: () => spy });
    const series = chart.addSeries('candlestick');
    series.setData(bars(50));
    chart.fitContent();
    const before = spy.calls.length;
    series.update({ time: T0 + 49 * 300, open: 100, high: 101, low: 99, close: 100.5 });
    expect(spy.calls.length).toBeGreaterThan(before);
    chart.destroy();
  });

  it('keeps the vector export on the serialising target, with the backend idle', () => {
    const spy = new SpyBackend();
    const chart = loaded({ renderBackend: () => spy });
    const framesBefore = spy.frames.length;
    const callsBefore = spy.calls.length;
    const svg = chart.exportSVG();
    expect(svg).toContain('<svg');
    // The export ran a full paint into its own target: the backend saw none of
    // it, and the document still holds the candle rects.
    expect(spy.frames.length).toBe(framesBefore);
    expect(spy.calls.length).toBe(callsBefore);
    expect((svg.match(/<rect/g) ?? []).length).toBeGreaterThan(100);
    chart.destroy();
  });
});
