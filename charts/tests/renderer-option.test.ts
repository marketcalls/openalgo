/**
 * The `renderer` option end to end with the real WebGL2 backend behind it:
 * how 'auto' and an explicit 'webgl2' resolve against a device that has a
 * context, has none, or loses it; the one console warning an explicit ask
 * gets when the device declines; the session fallback to canvas2d with its
 * 'renderer:fallback' event; and the tier boundary, which is a static
 * property of the import graph rather than of a build.
 *
 * Node has no GPU, so the context is a stand-in that accepts every call.
 * What the GPU path draws is proven in tests/webgl-backend.test.ts and the
 * e2e parity spec; here the question is only which path a chart is on.
 */
import { describe, it, expect, afterEach, vi } from 'vitest';
import { Chart, type ChartOptions, type RendererFallbackEvent } from '../src/core/chart';
import { Pane } from '../src/core/pane';
import { InvalidationLevel } from '../src/core/invalidate-mask';
import { fakeDocument } from './helpers/fake-dom';
import type { RecordingContext, Op } from './helpers/fake-ctx';
import {
  createRenderBackend, registeredRenderBackends, unregisterRenderBackend,
  backendDegradation, type IRenderBackend, type RenderBackendKind,
} from '../src/index';
import { Canvas2dBackend } from '../src/render/canvas2d-backend';
import {
  GlDevice, WebGL2Backend, createWebGL2Backend, registerWebGL2Backend, type GlSurface,
} from '../src/render/webgl';
import type { DrawItem, RendererEntry, SeriesRenderContext } from '../src/model/chart-type-registry';
import type { SeriesStyle } from '../src/render/series-style';
import type { Bar } from '../src/model/bar';

const T0 = 1_700_000_000;

// ── the stand-in GPU ────────────────────────────────────────────────────────

/**
 * A WebGL2 context that accepts every call: constants are distinct numbers,
 * every function returns a fresh handle, shaders compile while `compiles`
 * holds, and `lost` is what `isContextLost` reports.
 */
function fakeGl(state: { lost: boolean; compiles: boolean }): WebGL2RenderingContext {
  let next = 0;
  const constants = new Map<string, number>();
  const attribs = ['a_pos', 'a_color', 'a_local', 'a_shape'];
  return new Proxy({}, {
    get(_target, key) {
      if (typeof key !== 'string') return undefined;
      if (key === 'isContextLost') return () => state.lost;
      if (key === 'getShaderParameter') return () => state.compiles;
      if (key === 'getProgramParameter') return () => true;
      if (key === 'getShaderInfoLog' || key === 'getProgramInfoLog') return () => 'stand-in';
      if (key === 'getAttribLocation') return (_p: unknown, name: string) => attribs.indexOf(name);
      if (/^[A-Z][A-Z0-9_]*$/.test(key)) {
        if (!constants.has(key)) constants.set(key, ++next);
        return constants.get(key);
      }
      return () => ({});
    },
  }) as unknown as WebGL2RenderingContext;
}

/** A surface with one stand-in context (or none), whose loss the test can stage. */
class FakeSurface implements GlSurface {
  public width = 1;
  public height = 1;
  public readonly state = { lost: false, compiles: true };
  private readonly _listeners = new Map<string, ((e: Event) => void)[]>();

  public constructor(private readonly _hasContext = true) {}

  public getContext(): WebGL2RenderingContext | null {
    return this._hasContext ? fakeGl(this.state) : null;
  }
  public addEventListener(type: string, fn: (e: Event) => void): void {
    const list = this._listeners.get(type) ?? [];
    list.push(fn);
    this._listeners.set(type, list);
  }
  public removeEventListener(type: string, fn: (e: Event) => void): void {
    this._listeners.set(type, (this._listeners.get(type) ?? []).filter((f) => f !== fn));
  }
  /** What the browser does: flag the context, then tell the listeners. */
  public lose(): void {
    this.state.lost = true;
    for (const fn of this._listeners.get('webglcontextlost') ?? []) fn({ preventDefault() {} } as unknown as Event);
  }
  public restore(): void {
    this.state.lost = false;
    for (const fn of this._listeners.get('webglcontextrestored') ?? []) fn({} as Event);
  }
}

/** A device of its own, so nothing here touches the page-wide shared one. */
function device(hasContext = true): { device: GlDevice; surface: FakeSurface } {
  const surface = new FakeSurface(hasContext);
  return { device: new GlDevice(() => surface), surface };
}

// ── the chart under test ────────────────────────────────────────────────────

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

/** Measured and synchronous (CLAUDE.md): a chart without both proves nothing. */
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

/** A candlestick pane over a histogram pane, painted. */
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

function baseOps(chart: Chart, pane = 0): Op[] {
  return (chart.panes()[pane].base.ctx as unknown as RecordingContext).ops;
}

function count(ops: readonly Op[], type: string): number {
  return ops.filter((o) => o.type === type).length;
}

function repaint(chart: Chart): void {
  chart.invalidate((m) => m.invalidateGlobal(InvalidationLevel.Full));
}

/** A backend that records its lifecycle and paints nothing. */
class SpyBackend implements IRenderBackend {
  public readonly kind: RenderBackendKind = 'webgl2';
  public mounted: { canvas: HTMLCanvasElement; ctx2d: CanvasRenderingContext2D | null } | null = null;
  public resizes: [number, number, number][] = [];
  public destroyed = 0;
  public mount(canvas: HTMLCanvasElement, ctx2d: CanvasRenderingContext2D | null): void { this.mounted = { canvas, ctx2d }; }
  public resize(w: number, h: number, dpr: number): void { this.resizes.push([w, h, dpr]); }
  public beginFrame(): void {}
  public drawSeries(
    _e: RendererEntry, _i: readonly DrawItem[], _y: (p: number) => number, _b: number, _d: number, _s: SeriesStyle, _r: SeriesRenderContext,
  ): void {}
  public endFrame(): void {}
  public overlay2d(): CanvasRenderingContext2D | null { return this.mounted?.ctx2d ?? null; }
  public destroy(): void { this.destroyed++; }
}

afterEach(() => {
  unregisterRenderBackend('webgl2');
  vi.restoreAllMocks();
});

describe('the webgl2 registration', () => {
  it('registerWebGL2Backend puts webgl2 in the registry and auto resolves to it on a device with a context', () => {
    expect(registeredRenderBackends()).not.toContain('webgl2');
    registerWebGL2Backend(device().device);
    expect(registeredRenderBackends()).toContain('webgl2');
    expect(createRenderBackend('auto')).toBeInstanceOf(WebGL2Backend);
    expect(createRenderBackend('webgl2')).toBeInstanceOf(WebGL2Backend);
    expect(createRenderBackend('canvas2d')).toBeInstanceOf(Canvas2dBackend);
  });

  it('declines on a device with no context, and the registry falls through to canvas2d', () => {
    const { device: d } = device(false);
    expect(createWebGL2Backend(d)).toBeNull();
    registerWebGL2Backend(d);
    expect(createRenderBackend('auto')).toBeInstanceOf(Canvas2dBackend);
    expect(createRenderBackend('webgl2')).toBeInstanceOf(Canvas2dBackend);
  });

  it('is not a side effect of importing the module', () => {
    expect(registeredRenderBackends()).toEqual(['canvas2d']);
  });
});

describe('resolving the renderer option on a chart', () => {
  it('auto takes the GPU backend when it is registered and available, and blits into the base canvas', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    registerWebGL2Backend(device().device);
    const chart = loaded({ renderer: 'auto' });
    expect(chart.rendererKind).toBe('webgl2');
    expect(chart.renderer).toBe(chart.rendererKind);
    for (const pane of chart.panes()) expect(pane.backend).toBeInstanceOf(WebGL2Backend);
    // The series reached the base canvas as one composite, not as rects: the
    // rects left are the chrome (background, tag boxes).
    const ops = baseOps(chart);
    expect(count(ops, 'drawImage')).toBeGreaterThan(0);
    expect(count(ops, 'fillRect')).toBeLessThan(40);
    expect(count(baseOps(chart, 1), 'drawImage')).toBeGreaterThan(0);
    expect(warn).not.toHaveBeenCalled();
    chart.destroy();
  });

  it('auto is canvas2d, silently, when the registered backend declines', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    registerWebGL2Backend(device(false).device);
    const chart = loaded({ renderer: 'auto' });
    expect(chart.rendererKind).toBe('canvas2d');
    for (const pane of chart.panes()) expect(pane.backend).toBeInstanceOf(Canvas2dBackend);
    // The candles were painted by the 2D renderer: a wick and a body per bar.
    expect(count(baseOps(chart), 'fillRect')).toBeGreaterThan(100);
    expect(count(baseOps(chart), 'drawImage')).toBe(0);
    expect(warn).not.toHaveBeenCalled();
    chart.destroy();
  });

  it('auto is canvas2d when no tier has registered webgl2', () => {
    const chart = loaded({ renderer: 'auto' });
    expect(chart.rendererKind).toBe('canvas2d');
    chart.destroy();
  });

  it('an explicit webgl2 falls back with exactly one warning when the device declines', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    registerWebGL2Backend(device(false).device);
    // Two panes, so two factory calls: the warning is still one per chart.
    const chart = loaded({ renderer: 'webgl2' });
    expect(chart.rendererKind).toBe('canvas2d');
    expect(count(baseOps(chart), 'fillRect')).toBeGreaterThan(100);
    expect(warn).toHaveBeenCalledTimes(1);
    expect(String(warn.mock.calls[0][0])).toMatch(/webgl2.*unavailable.*canvas2d/);
    chart.destroy();
  });

  it('an explicit webgl2 that the device honours does not warn', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    registerWebGL2Backend(device().device);
    const chart = loaded({ renderer: 'webgl2' });
    expect(chart.rendererKind).toBe('webgl2');
    expect(warn).not.toHaveBeenCalled();
    chart.destroy();
  });

  it('an explicit webgl2 still throws when the tier was never imported', () => {
    expect(() => makeChart({ renderer: 'webgl2' })).toThrow(/webgl2.*not registered/);
  });

  it('canvas2d never warns, and an injected factory bypasses the option and its warning', () => {
    const warn = vi.spyOn(console, 'warn').mockImplementation(() => {});
    registerWebGL2Backend(device(false).device);
    const plain = loaded({ renderer: 'canvas2d' });
    expect(plain.rendererKind).toBe('canvas2d');
    plain.destroy();
    const injected = loaded({ renderer: 'webgl2', renderBackend: () => null });
    expect(injected.rendererKind).toBe('canvas2d');
    injected.destroy();
    expect(warn).not.toHaveBeenCalled();
  });
});

describe('losing the context', () => {
  it('moves every pane to canvas2d for the session and emits renderer:fallback once', () => {
    const { device: d, surface } = device();
    registerWebGL2Backend(d);
    const chart = loaded({ renderer: 'auto' });
    const events: RendererFallbackEvent[] = [];
    chart.on('renderer:fallback', (e) => events.push(e as RendererFallbackEvent));
    const blitsBefore = count(baseOps(chart), 'drawImage');

    surface.lose();
    // Nothing happens until a frame notices: the canvas keeps its last pixels.
    expect(events).toHaveLength(0);
    expect(chart.rendererKind).toBe('webgl2');

    const mark = baseOps(chart).length;
    repaint(chart);
    expect(events).toEqual([{ from: 'webgl2', to: 'canvas2d', reason: 'context-lost' }]);
    expect(chart.rendererKind).toBe('canvas2d');
    expect(chart.renderer).toBe('canvas2d');
    for (const pane of chart.panes()) expect(pane.backend).toBeInstanceOf(Canvas2dBackend);
    // The repaint the fallback queued went through the 2D renderer: candle
    // rects, and no blit since the loss.
    const since = baseOps(chart).slice(mark);
    expect(count(since, 'fillRect')).toBeGreaterThan(100);
    expect(count(baseOps(chart), 'drawImage')).toBe(blitsBefore);

    // A restored context does not bring the GPU back for this chart, and
    // the event does not repeat.
    surface.restore();
    expect(d.lost).toBe(false);
    repaint(chart);
    expect(chart.rendererKind).toBe('canvas2d');
    expect(events).toHaveLength(1);
    expect(count(baseOps(chart), 'drawImage')).toBe(blitsBefore);

    // A pane added after the fallback matches the ones on screen.
    chart.addSeries('line', { paneIndex: 2 }).setData(bars(20));
    expect(chart.panes()).toHaveLength(3);
    expect(chart.panes()[2].backend).toBeInstanceOf(Canvas2dBackend);
    chart.destroy();
  });

  it('a new chart after a restore is on the GPU again: the fallback is per chart, not per device', () => {
    const { device: d, surface } = device();
    registerWebGL2Backend(d);
    const first = loaded({ renderer: 'auto' });
    surface.lose();
    repaint(first);
    expect(first.rendererKind).toBe('canvas2d');
    first.destroy();
    surface.restore();
    const second = loaded({ renderer: 'auto' });
    expect(second.rendererKind).toBe('webgl2');
    expect(count(baseOps(second), 'drawImage')).toBeGreaterThan(0);
    second.destroy();
  });

  it('reports a program that will not compile as unavailable', () => {
    const { device: d, surface } = device();
    surface.state.compiles = false;
    registerWebGL2Backend(d);
    // The first frame with a series is the first compile attempt, so the
    // listener can be in place before it.
    const chart = makeChart({ renderer: 'auto' });
    expect(chart.rendererKind).toBe('webgl2');
    const events: RendererFallbackEvent[] = [];
    chart.on('renderer:fallback', (e) => events.push(e as RendererFallbackEvent));
    chart.addSeries('candlestick').setData(bars(60));
    expect(events).toEqual([{ from: 'webgl2', to: 'canvas2d', reason: 'unavailable' }]);
    expect(chart.rendererKind).toBe('canvas2d');
    expect(count(baseOps(chart), 'fillRect')).toBeGreaterThan(100);
    expect(count(baseOps(chart), 'drawImage')).toBe(0);
    chart.destroy();
  });

  it('a chart already on canvas2d never polls for degradation', () => {
    const { device: d, surface } = device();
    registerWebGL2Backend(d);
    const chart = loaded({ renderer: 'canvas2d' });
    const events: unknown[] = [];
    chart.on('renderer:fallback', (e) => events.push(e));
    surface.lose();
    repaint(chart);
    expect(events).toHaveLength(0);
    expect(chart.rendererKind).toBe('canvas2d');
    chart.destroy();
  });
});

describe('backendDegradation', () => {
  const backend = (kind: RenderBackendKind, dev?: { available: boolean; lost: boolean }): IRenderBackend => {
    const b = new SpyBackend() as SpyBackend & { kind: RenderBackendKind; device?: { available: boolean; lost: boolean } };
    b.kind = kind;
    if (dev !== undefined) b.device = dev;
    return b;
  };

  it('is null for canvas2d and for a backend without a device, whatever the device says', () => {
    expect(backendDegradation(backend('canvas2d'))).toBeNull();
    expect(backendDegradation(backend('canvas2d', { available: false, lost: true }))).toBeNull();
    expect(backendDegradation(backend('webgl2'))).toBeNull();
    expect(backendDegradation(backend('webgl2', { available: true, lost: false }))).toBeNull();
  });

  it('names the loss before the unavailability', () => {
    expect(backendDegradation(backend('webgl2', { available: true, lost: true }))).toBe('context-lost');
    expect(backendDegradation(backend('webgl2', { available: false, lost: false }))).toBe('unavailable');
    expect(backendDegradation(backend('webgl2', { available: false, lost: true }))).toBe('context-lost');
  });

  it('reads the real device through the port: the GL backend exposes it as is', () => {
    const { device: d, surface } = device();
    const gl = createWebGL2Backend(d) as WebGL2Backend;
    expect(gl.device).toBe(d);
    expect(backendDegradation(gl)).toBeNull();
    surface.lose();
    expect(backendDegradation(gl)).toBe('context-lost');
    surface.restore();
    expect(backendDegradation(gl)).toBeNull();
  });
});

describe('Pane.setBackend', () => {
  it('destroys the old backend, mounts the new one on the base canvas and tells it the size', () => {
    const a = new SpyBackend();
    const b = new SpyBackend();
    const pane = new Pane(fakeDocument(), a);
    pane.resize(640, 480, 2);
    pane.setBackend(b);
    expect(pane.backend).toBe(b);
    expect(a.destroyed).toBe(1);
    expect(b.mounted?.canvas).toBe(pane.base.element);
    expect(b.mounted?.ctx2d).toBe(pane.base.ctx);
    expect(b.resizes).toEqual([[640, 480, 2]]);
    // Setting the same backend again is a no-op, not a destroy.
    pane.setBackend(b);
    expect(b.destroyed).toBe(0);
    pane.destroy();
    expect(b.destroyed).toBe(1);
  });

  it('does not size a backend on a pane that has not been measured', () => {
    const pane = new Pane(fakeDocument(), new SpyBackend());
    const b = new SpyBackend();
    pane.setBackend(b);
    expect(b.resizes).toEqual([]);
  });
});

describe('the tier boundary', () => {
  // Every source file as text, keyed by its path relative to this test. The
  // glob is resolved at transform time, the way the indicator suites read
  // their siblings, so the walk needs no filesystem access and no Node types.
  type Sources = Record<string, string>;
  const SOURCES = (import.meta as unknown as {
    glob(pattern: string, options: { query: string; import: string; eager: true }): Sources;
  }).glob('../src/**/*.ts', { query: '?raw', import: 'default', eager: true });

  /** POSIX join of a relative specifier onto the directory of `from`, with '.' and '..' collapsed. */
  function join(from: string, spec: string): string {
    const parts = from.split('/').slice(0, -1);
    for (const seg of spec.split('/')) {
      if (seg === '.' || seg === '') continue;
      if (seg === '..') parts.pop(); else parts.push(seg);
    }
    return parts.join('/');
  }

  /** Every module reachable from `entry` through static imports, as glob keys. */
  function reachable(entry: string): Set<string> {
    const seen = new Set<string>();
    const queue = [entry];
    const spec = /(?:^|\n)\s*(?:import|export)\b[^'"]*?from\s*['"]([^'"]+)['"]|(?:^|\n)\s*import\s*['"]([^'"]+)['"]/g;
    while (queue.length > 0) {
      const file = queue.pop() as string;
      if (seen.has(file)) continue;
      seen.add(file);
      const source = SOURCES[file];
      if (source === undefined) throw new Error(`not a source file: ${file}`);
      for (const m of source.matchAll(spec)) {
        const target = m[1] ?? m[2];
        if (!target.startsWith('.')) continue;
        const base = join(file, target);
        const hit = [base + '.ts', base + '/index.ts'].find((c) => c in SOURCES);
        if (hit !== undefined) queue.push(hit);
      }
    }
    return seen;
  }

  const under = (files: Set<string>, dir: string): string[] =>
    Array.from(files).filter((f) => f.includes(`/src/${dir}/`));

  it('the glob saw the tree', () => {
    expect(Object.keys(SOURCES).length).toBeGreaterThan(50);
    expect(SOURCES).toHaveProperty(['../src/index.ts']);
  });

  it('the base entry never reaches src/render/webgl, so the GPU backend stays out of the base bundle', () => {
    const files = reachable('../src/index.ts');
    // Not vacuous: the walk does see the port and the 2D backend.
    expect(under(files, 'render')).toEqual(expect.arrayContaining([
      '../src/render/backend.ts', '../src/render/canvas2d-backend.ts',
    ]));
    expect(under(files, 'render/webgl')).toEqual([]);
  });

  it('the walk is real: the webgl module does reach its own files and the port', () => {
    const files = reachable('../src/render/webgl/index.ts');
    expect(under(files, 'render/webgl').length).toBeGreaterThanOrEqual(4);
    expect(files.has('../src/render/backend.ts')).toBe(true);
  });
});
