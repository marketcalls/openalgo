/**
 * The WebGL2 render backend (src/render/webgl/backend.ts). Node has no GPU,
 * so the context is a recorder: what the backend uploads is decoded back into
 * rects, segments and fills and held against the shapes the 2D renderers
 * paint for the same items, op for op. The frame lifecycle, the 2D fallback,
 * context loss, the shared device and the chart wiring are checked on the
 * same fake. The pixel proof is the e2e parity spec.
 */
import { describe, it, expect, afterEach } from 'vitest';
import { Chart, type ChartOptions } from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import { makeCtx, type Op, type RecordingContext } from './helpers/fake-ctx';
import { createRenderBackend, unregisterRenderBackend, registeredRenderBackends } from '../src/render/backend';
import { getChartType, type DrawItem, type RendererEntry, type SeriesRenderContext } from '../src/model/chart-type-registry';
import { drawCandles, candleGeometry, DEFAULT_CANDLE_STYLE, type CandleStyle } from '../src/render/candles';
import { drawBars, drawColumns } from '../src/render/bars';
import { drawHistogram } from '../src/render/histogram';
import { drawLine } from '../src/render/line';
import type { SeriesStyle } from '../src/render/series-style';
import { darkTheme } from '../src/theme';
import type { Bar } from '../src/model/bar';
import {
  WebGL2Backend, GlDevice, createWebGL2Backend, registerWebGL2Backend, isWebGL2Supported, type GlSurface,
} from '../src/render/webgl/backend';
import { FLOATS_PER_VERTEX, VERTICES_PER_QUAD, SOLID } from '../src/render/webgl/batch';
import { parsePremultiplied, TRANSPARENT, type PremultipliedRgba } from '../src/render/webgl/color';

// ── the fake GPU ────────────────────────────────────────────────────────────

/** Enough of WebGL2 to run the backend and record what it did. */
class FakeGl {
  public calls: { name: string; args: unknown[] }[] = [];
  /** Vertex uploads, one per flush, copied at upload time. */
  public uploads: Float32Array[] = [];
  public indexUploads = 0;
  public draws: number[] = [];
  public programs = 0;
  public lost = false;
  public failCompile = false;

  public readonly VERTEX_SHADER = 0x8b31;
  public readonly FRAGMENT_SHADER = 0x8b30;
  public readonly COMPILE_STATUS = 0x8b81;
  public readonly LINK_STATUS = 0x8b82;
  public readonly ARRAY_BUFFER = 0x8892;
  public readonly ELEMENT_ARRAY_BUFFER = 0x8893;
  public readonly STREAM_DRAW = 0x88e0;
  public readonly STATIC_DRAW = 0x88e4;
  public readonly FLOAT = 0x1406;
  public readonly BLEND = 0x0be2;
  public readonly ONE = 1;
  public readonly ONE_MINUS_SRC_ALPHA = 0x0303;
  public readonly SCISSOR_TEST = 0x0c11;
  public readonly COLOR_BUFFER_BIT = 0x4000;
  public readonly TRIANGLES = 4;
  public readonly UNSIGNED_INT = 0x1405;
  public readonly DEPTH_TEST = 0x0b71;
  public readonly CULL_FACE = 0x0b44;

  private _log(name: string, ...args: unknown[]): void { this.calls.push({ name, args }); }
  public isContextLost(): boolean { return this.lost; }
  public createShader(type: number): object { this._log('createShader', type); return { type }; }
  public shaderSource(): void {}
  public compileShader(): void {}
  public getShaderParameter(): boolean { return !this.failCompile; }
  public getShaderInfoLog(): string { return 'fake compile failure'; }
  public deleteShader(): void {}
  public createProgram(): object { this.programs++; return { program: this.programs }; }
  public attachShader(): void {}
  public linkProgram(): void {}
  public getProgramParameter(): boolean { return true; }
  public getProgramInfoLog(): string { return ''; }
  public deleteProgram(): void {}
  public getAttribLocation(_p: object, name: string): number { return ['a_pos', 'a_color', 'a_local', 'a_shape'].indexOf(name); }
  public getUniformLocation(_p: object, name: string): object { return { name }; }
  public useProgram(p: object): void { this._log('useProgram', p); }
  public createBuffer(): object { return {}; }
  public bindBuffer(target: number): void { this._log('bindBuffer', target); }
  public bufferData(target: number, data: ArrayBufferView, usage: number, offset = 0, length?: number): void {
    this._log('bufferData', target, usage, offset, length);
    if (target === this.ARRAY_BUFFER) this.uploads.push((data as Float32Array).slice(offset, offset + (length ?? (data as Float32Array).length)));
    else this.indexUploads++;
  }
  public createVertexArray(): object { return {}; }
  public bindVertexArray(v: object | null): void { this._log('bindVertexArray', v); }
  public enableVertexAttribArray(i: number): void { this._log('enableVertexAttribArray', i); }
  public vertexAttribPointer(...args: unknown[]): void { this._log('vertexAttribPointer', ...args); }
  public enable(cap: number): void { this._log('enable', cap); }
  public disable(cap: number): void { this._log('disable', cap); }
  public blendFunc(s: number, d: number): void { this._log('blendFunc', s, d); }
  public viewport(...args: number[]): void { this._log('viewport', ...args); }
  public scissor(...args: number[]): void { this._log('scissor', ...args); }
  public clearColor(...args: number[]): void { this._log('clearColor', ...args); }
  public clear(mask: number): void { this._log('clear', mask); }
  public uniform2f(_u: object, x: number, y: number): void { this._log('uniform2f', x, y); }
  public drawElements(mode: number, count: number, type: number, offset: number): void {
    this._log('drawElements', mode, count, type, offset);
    this.draws.push(count);
  }

  public named(name: string): unknown[][] {
    return this.calls.filter((c) => c.name === name).map((c) => c.args);
  }
}

/** A surface that hands out one fake context and records listeners. */
class FakeSurface implements GlSurface {
  public width = 1;
  public height = 1;
  public readonly gl = new FakeGl();
  public listeners = new Map<string, ((e: Event) => void)[]>();
  public contexts = 0;
  public constructor(private readonly _available = true) {}
  public getContext(): WebGL2RenderingContext | null {
    this.contexts++;
    return this._available ? (this.gl as unknown as WebGL2RenderingContext) : null;
  }
  public addEventListener(type: string, fn: (e: Event) => void): void {
    const list = this.listeners.get(type) ?? [];
    list.push(fn);
    this.listeners.set(type, list);
  }
  public removeEventListener(type: string, fn: (e: Event) => void): void {
    this.listeners.set(type, (this.listeners.get(type) ?? []).filter((f) => f !== fn));
  }
  public fire(type: string): void {
    for (const fn of this.listeners.get(type) ?? []) fn({ preventDefault() {} } as unknown as Event);
  }
}

// ── decoding what was uploaded ──────────────────────────────────────────────

type Shape =
  | { kind: 'rect'; x: number; y: number; w: number; h: number; color: number[] }
  | { kind: 'segment'; x0: number; y0: number; x1: number; y1: number; hw: number; round: boolean; color: number[] }
  | { kind: 'fill'; pts: [number, number][]; colors: number[][] };

const r6 = (v: number): number => Math.round(v * 1e6) / 1e6;

/** Quads back to the shapes the emitters meant, through the documented layout. */
function decode(floats: Float32Array): Shape[] {
  const out: Shape[] = [];
  const stride = FLOATS_PER_VERTEX;
  for (let o = 0; o + stride * VERTICES_PER_QUAD <= floats.length; o += stride * VERTICES_PER_QUAD) {
    const v = (i: number, k: number): number => floats[o + i * stride + k];
    const hx = v(0, 8);
    const hy = v(0, 9);
    const rad = v(0, 10);
    const color = (i: number): number[] => [r6(v(i, 2)), r6(v(i, 3)), r6(v(i, 4)), r6(v(i, 5))];
    if (hx === SOLID) {
      out.push({ kind: 'fill', pts: [0, 1, 2, 3].map((i) => [r6(v(i, 0)), r6(v(i, 1))]), colors: [0, 1, 2, 3].map(color) });
      continue;
    }
    // Corner 0 sits at local (-ex, -ey) and corner 3 at (+ex, +ey): their
    // midpoint is the shape centre whatever the frame's rotation.
    const cx = (v(0, 0) + v(3, 0)) / 2;
    const cy = (v(0, 1) + v(3, 1)) / 2;
    if (rad === 0 && hy > 0) {
      const ex = -v(0, 6);
      // A rect's frame is the page's; a butt segment's may be rotated.
      const dx = (v(1, 0) - v(0, 0)) / (2 * ex);
      const dy = (v(1, 1) - v(0, 1)) / (2 * ex);
      if (Math.abs(dy) < 1e-9 && Math.abs(dx - 1) < 1e-9) {
        out.push({ kind: 'rect', x: r6(cx - hx), y: r6(cy - hy), w: r6(2 * hx), h: r6(2 * hy), color: color(0) });
      } else {
        out.push({ kind: 'segment', x0: r6(cx - dx * hx), y0: r6(cy - dy * hx), x1: r6(cx + dx * hx), y1: r6(cy + dy * hx), hw: r6(hy), round: false, color: color(0) });
      }
      continue;
    }
    const ex = -v(0, 6);
    const dx = (v(1, 0) - v(0, 0)) / (2 * ex);
    const dy = (v(1, 1) - v(0, 1)) / (2 * ex);
    out.push({ kind: 'segment', x0: r6(cx - dx * hx), y0: r6(cy - dy * hx), x1: r6(cx + dx * hx), y1: r6(cy + dy * hx), hw: r6(rad), round: true, color: color(0) });
  }
  return out;
}

/** A colour as the batch stores it: parsed, then rounded through float32 like the upload. */
const rgba = (css: string): number[] => (parsePremultiplied(css) ?? TRANSPARENT).map((c) => r6(Math.fround(c)));

const sameColor = (a: number[], b: number[]): boolean => a.length === b.length && a.every((v, i) => Math.abs(v - b[i]) <= 1e-6);

/**
 * Shape lists compared with a float32 tolerance on every number: the upload
 * is a Float32Array, and a rotated segment's endpoints are recovered from its
 * corners, so a device coordinate comes back within a few 1e-5 of what went in.
 */
function expectShapes(got: Shape[], want: Shape[]): void {
  expect(got.length).toBe(want.length);
  const flat = (v: unknown): number[] => (Array.isArray(v) ? v.flatMap(flat) : [v as number]);
  for (let i = 0; i < got.length; i++) {
    const g = got[i] as unknown as Record<string, unknown>;
    const w = want[i] as unknown as Record<string, unknown>;
    expect(g.kind, `shape ${i}`).toBe(w.kind);
    for (const key of Object.keys(w)) {
      if (key === 'kind') continue;
      const a = flat(g[key]);
      const b = flat(w[key]);
      expect(a.length, `shape ${i} ${key}`).toBe(b.length);
      for (let k = 0; k < b.length; k++) {
        if (typeof b[k] === 'boolean') expect(a[k], `shape ${i} ${key}`).toBe(b[k]);
        else expect(Math.abs(a[k] - b[k]), `shape ${i} ${key}: ${JSON.stringify(g[key])} vs ${JSON.stringify(w[key])}`).toBeLessThanOrEqual(1e-3);
      }
    }
  }
}

/** The rects a 2D `strokeRect(x, y, w, h)` at line width L covers, as the backend's ring rule states it. */
function ring(x: number, y: number, w: number, h: number, L: number, color: number[]): Shape[] {
  const ox = x - L / 2, oy = y - L / 2, ow = w + L, oh = h + L;
  const rect = (rx: number, ry: number, rw: number, rh: number): Shape => ({ kind: 'rect', x: r6(rx), y: r6(ry), w: r6(rw), h: r6(rh), color });
  if (w - L <= 0 || h - L <= 0) return [rect(ox, oy, ow, oh)];
  return [rect(ox, oy, ow, L), rect(ox, oy + oh - L, ow, L), rect(ox, oy + L, L, oh - 2 * L), rect(ox + ow - L, oy + L, L, oh - 2 * L)];
}

/** The 2D op stream reduced to shapes: fillRect, strokeRect (ring at `L`), stroked paths and arcs. */
function shapesOf2d(ops: Op[], L: number): Shape[] {
  const out: Shape[] = [];
  let path: [number, number][][] = [];
  let arcs: { x: number; y: number; r: number }[] = [];
  for (const op of ops) {
    if (op.type === 'fillRect') out.push({ kind: 'rect', x: op.args[0], y: op.args[1], w: op.args[2], h: op.args[3], color: rgba(op.fillStyle as string) });
    else if (op.type === 'strokeRect') out.push(...ring(op.args[0], op.args[1], op.args[2], op.args[3], L, rgba(op.strokeStyle as string)));
    else if (op.type === 'beginPath') { path = []; arcs = []; }
    else if (op.type === 'moveTo') path.push([[op.args[0], op.args[1]]]);
    else if (op.type === 'lineTo') {
      if (path.length === 0) path.push([]);
      path[path.length - 1].push([op.args[0], op.args[1]]);
    } else if (op.type === 'arc') arcs.push({ x: op.args[0], y: op.args[1], r: op.args[2] });
    else if (op.type === 'stroke') {
      const color = rgba(op.strokeStyle as string);
      const hw = (op.lineWidth as number) / 2;
      for (const sub of path) {
        for (let i = 1; i < sub.length; i++) {
          if (sub[i][0] === sub[i - 1][0] && sub[i][1] === sub[i - 1][1]) continue;
          out.push({ kind: 'segment', x0: sub[i - 1][0], y0: sub[i - 1][1], x1: sub[i][0], y1: sub[i][1], hw, round: true, color });
        }
      }
    } else if (op.type === 'fill') {
      for (const a of arcs) out.push({ kind: 'segment', x0: a.x, y0: a.y, x1: a.x, y1: a.y, hw: a.r, round: true, color: rgba(op.fillStyle as string) });
      arcs = [];
    }
  }
  return out;
}

// ── fixtures ────────────────────────────────────────────────────────────────

const T0 = 1_700_000_000;

function bars(count: number, colorEvery = 0): Bar[] {
  const out: Bar[] = [];
  let p = 100;
  for (let i = 0; i < count; i++) {
    // Opens away from the prior close, so close-versus-open and
    // close-versus-previous-close disagree on some bars.
    const o = p + ((i % 3) - 1) * 1.1;
    p += Math.sin(i / 3) * 3 + ((i % 5) - 2) * 0.7;
    const bar: Bar = { time: T0 + i * 60, open: o, high: Math.max(o, p) + 1.3, low: Math.min(o, p) - 0.9, close: p, volume: 50 + (i * 37) % 100 };
    if (colorEvery > 0 && i % colorEvery === 0) bar.color = 'rgba(255,200,0,0.5)';
    out.push(bar);
  }
  return out;
}

const items = (data: readonly Bar[], spacing: number, prevClose?: number): DrawItem[] => data.map((bar, i) => {
  const it: DrawItem = { x: 10 + i * spacing, bar };
  if (i === 0 && prevClose !== undefined) it.prevClose = prevClose;
  return it;
});

const priceToY = (p: number): number => 300 - (p - 80) * 5;
const rc = (plotHeight = 300, maxVolume = 0): SeriesRenderContext => ({ plotHeight, maxVolume, theme: darkTheme });

interface Rig {
  backend: WebGL2Backend;
  device: GlDevice;
  surface: FakeSurface;
  ctx: CanvasRenderingContext2D;
  rec: RecordingContext;
  canvas: { width: number; height: number };
}

/** A mounted backend on a fake device and a recording base context. */
function rig(available = true, widthPx = 800, heightPx = 400): Rig {
  const surface = new FakeSurface(available);
  const device = new GlDevice(() => surface);
  const backend = new WebGL2Backend(device);
  const { ctx, rec } = makeCtx();
  const canvas = { width: widthPx, height: heightPx };
  backend.mount(canvas as unknown as HTMLCanvasElement, ctx);
  return { backend, device, surface, ctx, rec, canvas };
}

/** One series in one frame; returns the shapes uploaded for it. */
function frame(r: Rig, type: string, data: readonly Bar[], style: SeriesStyle = {}, spacing = 8, dpr = 1, context = rc(), prevClose?: number): Shape[] {
  r.backend.beginFrame(true);
  r.backend.drawSeries(getChartType(type), items(data, spacing, prevClose), priceToY, spacing, dpr, style, context);
  r.backend.endFrame();
  const up = r.surface.gl.uploads;
  return up.length === 0 ? [] : decode(up[up.length - 1]);
}

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

afterEach(() => {
  unregisterRenderBackend('webgl2');
});

// ── the factory and the device ──────────────────────────────────────────────

describe('createWebGL2Backend', () => {
  it('declines where there is no WebGL2 (this process) and builds a backend on a device that has it', () => {
    expect(isWebGL2Supported()).toBe(false);
    expect(createWebGL2Backend()).toBeNull();
    const device = new GlDevice(() => new FakeSurface());
    const backend = createWebGL2Backend(device);
    expect(backend).toBeInstanceOf(WebGL2Backend);
    expect(backend?.kind).toBe('webgl2');
    expect(createWebGL2Backend(new GlDevice(() => new FakeSurface(false)))).toBeNull();
    expect(createWebGL2Backend(new GlDevice(() => null))).toBeNull();
  });

  it('registers under webgl2 without importing being enough on its own', () => {
    expect(registeredRenderBackends()).not.toContain('webgl2');
    registerWebGL2Backend(new GlDevice(() => new FakeSurface()));
    expect(createRenderBackend('auto').kind).toBe('webgl2');
    expect(createRenderBackend('webgl2').kind).toBe('webgl2');
    registerWebGL2Backend(new GlDevice(() => new FakeSurface(false)));
    expect(createRenderBackend('auto').kind).toBe('canvas2d');
    expect(createRenderBackend('webgl2').kind).toBe('canvas2d');
  });

  it('uploads the index pattern once for the largest batch seen, whichever pane brought it', () => {
    const surface = new FakeSurface();
    const device = new GlDevice(() => surface);
    const small = new WebGL2Backend(device);
    const big = new WebGL2Backend(device);
    const ctx = makeCtx().ctx;
    small.mount({ width: 800, height: 400 } as unknown as HTMLCanvasElement, ctx);
    big.mount({ width: 800, height: 400 } as unknown as HTMLCanvasElement, ctx);
    const paint = (b: WebGL2Backend, count: number): void => {
      b.beginFrame(true);
      b.drawSeries(getChartType('histogram'), items(bars(count), 2), priceToY, 2, 1, {}, rc());
      b.endFrame();
    };
    paint(small, 10);
    expect(surface.gl.indexUploads).toBe(1);
    // A batch that outgrows its default capacity brings a bigger pattern.
    paint(big, 600);
    expect(surface.gl.indexUploads).toBe(2);
    // Neither pane needs another upload afterwards, whatever order they paint in.
    paint(small, 10);
    paint(big, 600);
    paint(small, 10);
    expect(surface.gl.indexUploads).toBe(2);
    expect(surface.gl.draws).toEqual([60, 3600, 60, 3600, 60]);
  });

  it('creates the context once and lets every backend share it', () => {
    const surface = new FakeSurface();
    const device = new GlDevice(() => surface);
    const a = new WebGL2Backend(device);
    const b = new WebGL2Backend(device);
    a.mount({ width: 300, height: 200 } as unknown as HTMLCanvasElement, makeCtx().ctx);
    b.mount({ width: 500, height: 100 } as unknown as HTMLCanvasElement, makeCtx().ctx);
    expect(surface.contexts).toBe(1);
    expect(device.refs).toBe(2);
    // The surface holds the largest pane in each dimension.
    expect([surface.width, surface.height]).toEqual([500, 200]);
    b.resize(400, 300, 2);
    expect([surface.width, surface.height]).toEqual([800, 600]);
    a.destroy();
    expect(device.refs).toBe(1);
    expect([surface.width, surface.height]).toEqual([800, 600]);
    b.destroy();
    b.destroy();
    expect(device.refs).toBe(0);
    // The drawing buffer is handed back with the last pane; the context stays.
    expect([surface.width, surface.height]).toEqual([1, 1]);
    expect(device.available).toBe(true);
  });
});

// ── the frame ───────────────────────────────────────────────────────────────

describe('frame lifecycle', () => {
  it('mounts on the pane context, clears the way the 2D backend does, and blits once per frame', () => {
    const r = rig();
    expect(r.backend.overlay2d()).toBe(r.ctx);
    const shapes = frame(r, 'candlestick', bars(20));
    expect(shapes.length).toBeGreaterThan(20);
    const types = r.rec.ops.map((o) => o.type);
    expect(types).toEqual(['setTransform', 'clearRect', 'drawImage']);
    expect(r.rec.ops[1].args).toEqual([0, 0, 800, 400]);
    const gl = r.surface.gl;
    // Fixed state once, then per flush: viewport and scissor to the pane in
    // the top-left of the surface, clear, upload, one draw of every index.
    expect(gl.named('blendFunc')).toEqual([[gl.ONE, gl.ONE_MINUS_SRC_ALPHA]]);
    expect(gl.named('viewport')).toEqual([[0, 0, 800, 400]]);
    expect(gl.named('scissor')).toEqual([[0, 0, 800, 400]]);
    expect(gl.named('clear')).toHaveLength(1);
    expect(gl.named('uniform2f')).toEqual([[800, 400]]);
    expect(gl.draws).toEqual([shapes.length * 6]);
    expect(gl.indexUploads).toBe(1);
    // A second frame within capacity re-uploads vertices, not indices.
    frame(r, 'candlestick', bars(20));
    expect(gl.uploads).toHaveLength(2);
    expect(gl.indexUploads).toBe(1);
    expect(r.rec.count('drawImage')).toBe(2);
  });

  it('raises the viewport to the top of a taller shared surface so the blit reads rows from zero', () => {
    const surface = new FakeSurface();
    const device = new GlDevice(() => surface);
    const tall = new WebGL2Backend(device);
    tall.mount({ width: 800, height: 900 } as unknown as HTMLCanvasElement, makeCtx().ctx);
    const r: Rig = { ...rig(), device, surface };
    r.backend = new WebGL2Backend(device);
    r.backend.mount(r.canvas as unknown as HTMLCanvasElement, r.ctx);
    frame(r, 'histogram', bars(5));
    expect(surface.gl.named('viewport')).toEqual([[0, 500, 800, 400]]);
    expect(surface.gl.named('scissor')).toEqual([[0, 500, 800, 400]]);
  });

  it('does no GPU work and no blit for a frame with nothing batched', () => {
    const r = rig();
    r.backend.beginFrame(true);
    r.backend.endFrame();
    r.backend.beginFrame(false);
    r.backend.drawSeries(getChartType('line'), [], priceToY, 8, 1, {}, rc());
    r.backend.endFrame();
    expect(r.surface.gl.uploads).toHaveLength(0);
    expect(r.rec.ops.map((o) => o.type)).toEqual(['setTransform', 'clearRect']);
  });

  it('follows the pane size and pixel ratio through resize', () => {
    const r = rig();
    r.backend.resize(640, 480, 2);
    expect([r.surface.width, r.surface.height]).toEqual([1280, 960]);
    frame(r, 'histogram', bars(3));
    expect(r.surface.gl.named('viewport')).toEqual([[0, 0, 1280, 960]]);
    expect(r.surface.gl.named('uniform2f')).toEqual([[1280, 960]]);
  });

  it('paints nothing after destroy', () => {
    const r = rig();
    r.backend.destroy();
    expect(r.backend.overlay2d()).toBeNull();
    r.backend.beginFrame(true);
    r.backend.drawSeries(getChartType('candlestick'), items(bars(3), 8), priceToY, 8, 1, {}, rc());
    r.backend.endFrame();
    expect(r.rec.ops).toEqual([]);
    expect(r.surface.gl.uploads).toHaveLength(0);
  });
});

// ── parity with the 2D renderers ────────────────────────────────────────────

describe('candles', () => {
  const candle2d = (data: readonly Bar[], style: CandleStyle, spacing: number, dpr: number, L: number, prevClose?: number): Shape[] => {
    const { ctx, rec } = makeCtx();
    drawCandles(ctx, items(data, spacing, prevClose), priceToY, spacing, dpr, style);
    return shapesOf2d(rec.ops, L);
  };
  const themed = (s: SeriesStyle, extra: Partial<CandleStyle> = {}): CandleStyle => ({
    ...DEFAULT_CANDLE_STYLE,
    upColor: s.upColor ?? darkTheme.upColor, downColor: s.downColor ?? darkTheme.downColor,
    borderUpColor: s.borderUpColor ?? darkTheme.upColor, borderDownColor: s.borderDownColor ?? darkTheme.downColor,
    wickUpColor: s.wickUpColor ?? darkTheme.wickUpColor, wickDownColor: s.wickDownColor ?? darkTheme.wickDownColor,
    borderVisible: s.borderVisible ?? true, bodyVisible: s.bodyVisible ?? true, wickVisible: s.wickVisible ?? true,
    colorByPreviousClose: s.colorByPreviousClose, ...extra,
  });

  it('emits the wick and body rects drawCandles fills, in order, with the same colours', () => {
    const data = bars(30, 7);
    for (const spacing of [12, 6, 3, 1.5]) {
      const got = frame(rig(), 'candlestick', data, {}, spacing);
      expectShapes(got, candle2d(data, themed({}), spacing, 1, 1));
      expect(got.length).toBeGreaterThan(0);
    }
  });

  it('mirrors every style switch: borders, body, wick, previous-close colouring, custom colours', () => {
    const data = bars(24, 5);
    const styles: SeriesStyle[] = [
      { borderVisible: false },
      { bodyVisible: false },
      { bodyVisible: false, borderVisible: false },
      { wickVisible: false },
      { colorByPreviousClose: true },
      { upColor: '#112233', downColor: '#445566', borderUpColor: '#778899', borderDownColor: '#aabbcc', wickUpColor: '#ddeeff', wickDownColor: '#001122' },
      { upColor: '#112233', wickUpColor: '#112233', downColor: '#445566', wickDownColor: '#445566', borderVisible: false },
    ];
    for (const style of styles) {
      for (const spacing of [12, 2]) {
        const got = frame(rig(), 'candlestick', data, style, spacing, 1, rc(), 97);
        const want = candle2d(data, themed(style), spacing, 1, 1, 97);
        expect(got).toEqual(want);
      }
    }
  });

  it('draws hollow candles as outlines and honours the border switch on them', () => {
    const data = bars(24, 6);
    for (const style of [{}, { borderVisible: false }, { bodyVisible: false }] as SeriesStyle[]) {
      const got = frame(rig(), 'hollow-candle', data, style, 12);
      expectShapes(got, candle2d(data, themed(style, { hollow: true }), 12, 1, 1));
      // Not vacuous: an outline is four rects per up candle.
      expect(got.some((s) => s.kind === 'rect' && s.h === 1 && s.w > 3)).toBe(true);
    }
  });

  it('strokes a hollow outline at the wick width on a HiDPI screen, straddling half pixels like the 2D path', () => {
    const data: Bar[] = [{ time: T0, open: 100, high: 106, low: 98, close: 104 }];
    const got = frame(rig(), 'hollow-candle', data, {}, 12, 2);
    const geo = candleGeometry(10, 12, 2);
    const top = Math.round(priceToY(104) * 2);
    const bodyH = Math.round(priceToY(100) * 2) - top;
    expectShapes([got[0]], [{ kind: 'rect', x: geo.wickX, y: Math.round(priceToY(106) * 2), w: 2, h: Math.round(priceToY(98) * 2) - Math.round(priceToY(106) * 2), color: rgba(darkTheme.wickUpColor) }]);
    expectShapes(got.slice(1), ring(geo.bodyX + 0.5, top + 0.5, geo.bodyW - 1, bodyH - 1, 2, rgba(darkTheme.upColor)));
  });

  it('scales volume-candle bodies by relative volume through rc.maxVolume', () => {
    const data = bars(10);
    const max = Math.max(...data.map((b) => b.volume ?? 0));
    const got = frame(rig(), 'volume-candle', data, { borderVisible: false }, 12, 1, rc(300, max));
    const bodies = got.filter((s, i) => s.kind === 'rect' && i % 2 === 1);
    expect(bodies).toHaveLength(10);
    for (let i = 0; i < 10; i++) {
      const geo = candleGeometry(10 + i * 12, 12, 1, (data[i].volume ?? 0) / max);
      const body = bodies[i] as Extract<Shape, { kind: 'rect' }>;
      expect([body.x, body.w]).toEqual([geo.bodyX, geo.bodyW]);
    }
    expect(new Set(bodies.map((b) => (b as Extract<Shape, { kind: 'rect' }>).w)).size).toBeGreaterThan(1);
    // With no volume reference every body is full width, as the 2D path does.
    const flat = frame(rig(), 'volume-candle', data, { borderVisible: false }, 12, 1, rc(300, 0));
    expectShapes(flat, candle2d(data, themed({ borderVisible: false }), 12, 1, 1));
  });

  it('skips the body at the wick tier, exactly when drawCandles does', () => {
    const data = bars(40);
    const got = frame(rig(), 'candlestick', data, {}, 1.5);
    expect(got).toHaveLength(40);
    expectShapes(got, candle2d(data, themed({}), 1.5, 1, 1));
  });
});

describe('bars, columns and histogram', () => {
  it('emits the range and tick rects drawBars fills, with per-bar colour and previous-close colouring', () => {
    const data = bars(20, 4);
    for (const style of [{}, { colorByPreviousClose: true }, { upColor: '#123456', downColor: '#654321' }] as SeriesStyle[]) {
      for (const [type, hl] of [['bar', false], ['high-low', true]] as const) {
        const got = frame(rig(), type, data, style, 8, 1, rc(), 101);
        const { ctx, rec } = makeCtx();
        drawBars(ctx, items(data, 8, 101), priceToY, 8, 1, { ...style, upColor: style.upColor ?? darkTheme.upColor, downColor: style.downColor ?? darkTheme.downColor }, hl);
        expectShapes(got, shapesOf2d(rec.ops, 1));
        expect(got).toHaveLength(hl ? 20 : 60);
      }
    }
  });

  it('emits the column rects drawColumns fills: per-bar colour, then the flat colour, then up/down', () => {
    const data = bars(15, 3);
    for (const style of [{}, { color: '#abcdef' }, { base: 100 }, { upColor: '#111111', downColor: '#222222', base: 90 }] as SeriesStyle[]) {
      const got = frame(rig(), 'column', data, style, 8);
      const { ctx, rec } = makeCtx();
      drawColumns(ctx, items(data, 8), priceToY, 8, 1, { ...style, upColor: style.upColor ?? darkTheme.upColor, downColor: style.downColor ?? darkTheme.downColor });
      expectShapes(got, shapesOf2d(rec.ops, 1));
      expect(got).toHaveLength(15);
    }
  });

  it('emits the histogram rects with the bar colour over the style colour over the default', () => {
    const data = bars(15, 2);
    for (const style of [{}, { color: '#abcdef', base: 95 }] as SeriesStyle[]) {
      for (const dpr of [1, 2]) {
        const got = frame(rig(), 'histogram', data, style, 8, dpr);
        const { ctx, rec } = makeCtx();
        drawHistogram(ctx, items(data, 8), priceToY, 8, dpr, { color: style.color ?? '#3a4666', base: style.base ?? 0 });
        expectShapes(got, shapesOf2d(rec.ops, 1));
        expect(got).toHaveLength(15);
      }
    }
  });
});

describe('lines', () => {
  const line2d = (data: readonly Bar[], style: SeriesStyle, dpr: number): Shape[] => {
    const { ctx, rec } = makeCtx();
    drawLine(ctx, items(data, 8), priceToY, dpr, { ...style, color: style.color ?? darkTheme.lineColor });
    return shapesOf2d(rec.ops, 1);
  };
  const gapped = (data: Bar[], at: number[]): Bar[] => data.map((b, i) => (at.includes(i) ? { time: b.time, open: NaN, high: NaN, low: NaN, close: NaN } : b));

  it('strokes one round segment per span at half the device line width, breaking at gaps', () => {
    const data = gapped(bars(20), [5, 6, 12]);
    for (const dpr of [1, 2]) {
      for (const style of [{}, { lineWidth: 3 }, { lineWidth: 0.2 }] as SeriesStyle[]) {
        const got = frame(rig(), 'line', data, style, 8, dpr);
        expectShapes(got, line2d(data, style, dpr));
        expect(got).toHaveLength(14);
        expect((got[0] as Extract<Shape, { kind: 'segment' }>).hw).toBe(Math.max(1, (style.lineWidth ?? 1.5) * dpr) / 2);
      }
    }
  });

  it('colours the segment arriving at a bar in that bar\'s colour, as the 2D run split does', () => {
    const data = bars(12, 3);
    data[7].color = '#00ff00';
    const got = frame(rig(), 'line', data, {});
    expectShapes(got, line2d(data, {}, 1));
    const colours = got.map((s) => JSON.stringify(s.kind === 'segment' ? s.color : null));
    expect(new Set(colours).size).toBe(3);
  });

  it('draws a step line through the same horizontal-then-vertical points', () => {
    const data = bars(10, 4);
    const got = frame(rig(), 'step', data, {});
    expectShapes(got, line2d(data, { step: true }, 1));
    const segs = got as Extract<Shape, { kind: 'segment' }>[];
    expect(segs.every((s) => s.x0 === s.x1 || s.y0 === s.y1)).toBe(true);
    // A zero-length vertical leg (flat close to close) is dropped, nothing else.
    expect(segs.length).toBeGreaterThanOrEqual(9);
  });

  it('puts a dot on every point for line-markers, in the bar colour, and only dots for markersOnly', () => {
    const data = gapped(bars(10, 3), [4]);
    const got = frame(rig(), 'line-markers', data, { markerRadius: 3 });
    expectShapes(got, line2d(data, { markers: true, markerRadius: 3 }, 1));
    const dots = got.filter((s) => s.kind === 'segment' && s.x0 === s.x1 && s.y0 === s.y1);
    expect(dots).toHaveLength(9);
    expect((dots[0] as Extract<Shape, { kind: 'segment' }>).hw).toBe(3);
    expect(sameColor((dots[0] as Extract<Shape, { kind: 'segment' }>).color, rgba('rgba(255,200,0,0.5)'))).toBe(true);
    const only = frame(rig(), 'line', data, { markersOnly: true });
    expectShapes(only, line2d(data, { markersOnly: true }, 1));
    expect(only).toHaveLength(9);
    expect(only.every((s) => s.kind === 'segment' && s.x0 === s.x1)).toBe(true);
  });

  it('walks the dash pattern along the path with a round cap on every dash, phase carried across joins', () => {
    const data: Bar[] = [100, 100, 100].map((v, i) => ({ time: T0 + i, open: v, high: v, low: v, close: v }));
    // Three flat points 8 px apart: a 16 px path. Dashed is 6 on 4 off.
    const got = frame(rig(), 'line', data, { lineStyle: 'dashed' }) as Extract<Shape, { kind: 'segment' }>[];
    const y = priceToY(100);
    expect(got.map((s) => [s.x0, s.x1])).toEqual([[10, 16], [20, 26]]);
    expect(got.every((s) => s.round && s.y0 === y && s.y1 === y)).toBe(true);
    // Dotted is 1 on 3 off: a dash spanning the join is one piece per segment.
    const dotted = frame(rig(), 'line', data, { lineStyle: 'dotted' }) as Extract<Shape, { kind: 'segment' }>[];
    expect(dotted.map((s) => [s.x0, s.x1])).toEqual([[10, 11], [14, 15], [18, 19], [22, 23]]);
    // Solid emits one piece per span.
    expect(frame(rig(), 'line', data, {})).toHaveLength(2);
  });
});

/**
 * The segment to a neighbour beyond the view (DrawItem.edgeX) is cut at the
 * view before it reaches the batch. Uncut, a dashed line whose neighbour sat
 * ten million pixels away emitted a quad for every dash of the way: half a
 * million per series per frame.
 */
describe('lines joining a neighbour beyond the view', () => {
  /** The items for `data`, with a neighbour `far` px beyond each end, marked with the view edges given. */
  const edged = (data: readonly Bar[], far: number, leftEdge: number, rightEdge: number): DrawItem[] => {
    const out = items(data, 8);
    const lastX = out[out.length - 1].x;
    return [
      { x: out[0].x - far, bar: { ...data[0], close: data[0].close - 7 }, edgeX: leftEdge },
      ...out,
      { x: lastX + far, bar: { ...data[0], close: data[0].close + 9 }, edgeX: rightEdge },
    ];
  };
  const shoot = (type: string, list: DrawItem[], style: SeriesStyle, dpr = 1): Shape[] => {
    const r = rig();
    r.backend.beginFrame(true);
    r.backend.drawSeries(getChartType(type), list, priceToY, 8, dpr, style, rc());
    r.backend.endFrame();
    const up = r.surface.gl.uploads;
    return up.length === 0 ? [] : decode(up[up.length - 1]);
  };

  it('emits a bounded batch for a dashed line whose neighbours are a million pixels away', () => {
    const data = bars(40);
    for (const type of ['line', 'step', 'area'] as const) {
      for (const lineStyle of ['dashed', 'dotted'] as const) {
        const got = shoot(type, edged(data, 1e6, 0, 800), { lineStyle });
        expect(got.length, `${type} ${lineStyle}`).toBeLessThan(1500);
        for (const s of got) {
          const xs = s.kind === 'segment' ? [s.x0, s.x1] : s.kind === 'fill' ? s.pts.map((p) => p[0]) : [s.x, s.x + s.w];
          for (const x of xs) {
            expect(x).toBeGreaterThan(-100);
            expect(x).toBeLessThan(900);
          }
        }
      }
    }
  });

  it('paints the dashes from the first bar in view exactly as it does without the neighbours', () => {
    const data = bars(40);
    const same = (a: Shape, b: Shape): boolean => a.kind === 'segment' && b.kind === 'segment'
      && [a.x0 - b.x0, a.y0 - b.y0, a.x1 - b.x1, a.y1 - b.y1].every((d) => Math.abs(d) < 1e-3);
    for (const dpr of [1, 2]) {
      for (const type of ['line', 'step'] as const) {
        for (const lineStyle of ['dashed', 'dotted'] as const) {
          // A far neighbour, one cut a few dashes out, and a near one inside the margin.
          for (const far of [1e6, 40.5, 12]) {
            const style: SeriesStyle = { lineStyle };
            const without = shoot(type, items(data, 8), style, dpr);
            const withEdges = shoot(type, edged(data, far, 0, 10 + 39 * 8 + 1), style, dpr);
            // What comes before the line's own first dash is the added edge
            // segment; from that dash on it is the line as it was, dash for dash.
            const lead = withEdges.findIndex((s) => same(s, without[0]));
            expect(lead, `${type} ${lineStyle} ${far} at ${dpr}`).toBeGreaterThan(0);
            expectShapes(withEdges.slice(lead, lead + without.length), without);
          }
        }
      }
    }
  });

  it('never bridges a gap at the edge of the view: a line or a fill is what the bars in view make alone', () => {
    // A study's plot stores a bar with no value as NaN, so the neighbour, or
    // the bar in view next to it, can be a gap. Uncut, a fill joined the
    // neighbour's value across the gap to the next value in view.
    const gap = (b: Bar): Bar => ({ time: b.time, open: NaN, high: NaN, low: NaN, close: NaN });
    const data = bars(40);
    /** The neighbours with values, and the first and last bar in view each a gap. */
    const within = edged(data, 1e6, 0, 800).map((it, i, all) => (i === 1 || i === all.length - 2 ? { ...it, bar: gap(it.bar) } : it));
    const cases: [string, DrawItem[], DrawItem[]][] = [
      ['beyond', edged(data, 1e6, 0, 800).map((it, i, all) => (i === 0 || i === all.length - 1 ? { ...it, bar: gap(it.bar) } : it)), items(data, 8)],
      ['within', within, within.slice(1, -1)],
    ];
    for (const [name, withEdges, without] of cases) {
      for (const type of ['line', 'area', 'baseline', 'hlc-area'] as const) {
        for (const style of [{}, { lineStyle: 'dashed' }, { highColor: '#ff0000', lowColor: '#0000ff', baseValue: 100 }] as SeriesStyle[]) {
          const label = `${type} ${JSON.stringify(style)}, gap ${name} the view`;
          const got = shoot(type, withEdges, style);
          expect(got.length, label).toBeGreaterThan(0);
          expectShapes(got, shoot(type, without, style));
        }
      }
    }
  });
});

describe('area, baseline and HLC area', () => {
  const fills = (shapes: Shape[]): Extract<Shape, { kind: 'fill' }>[] => shapes.filter((s): s is Extract<Shape, { kind: 'fill' }> => s.kind === 'fill');
  const segments = (shapes: Shape[]): Extract<Shape, { kind: 'segment' }>[] => shapes.filter((s): s is Extract<Shape, { kind: 'segment' }> => s.kind === 'segment');

  it('fills one trapezoid per span down to the plot bottom, graded top to bottom, and strokes the line over it', () => {
    const data = bars(6);
    data[2] = { time: data[2].time, open: NaN, high: NaN, low: NaN, close: NaN };
    const got = frame(rig(), 'area', data, {}, 8, 1, rc(300));
    const f = fills(got);
    // Five finite points, four spans (the gap is skipped, not a break).
    expect(f).toHaveLength(4);
    const top = parsePremultiplied(darkTheme.areaTopColor) as PremultipliedRgba;
    for (const q of f) {
      expect(q.pts[2][1]).toBe(300);
      expect(q.pts[3][1]).toBe(300);
      // The gradient runs from the top colour at y 0 to the bottom one at the base.
      for (let i = 0; i < 2; i++) {
        const t = q.pts[i][1] / 300;
        expect(sameColor(q.colors[i], top.map((c) => c * (1 - t)))).toBe(true);
      }
      expect(q.colors[2]).toEqual([0, 0, 0, 0]);
    }
    // The line is batched after the fill so it lands on top.
    const lineIndex = got.findIndex((s) => s.kind === 'segment');
    expect(lineIndex).toBe(4);
    expect(segments(got)).toHaveLength(3);
    expect(sameColor(segments(got)[0].color, rgba(darkTheme.lineColor))).toBe(true);
  });

  it('gives the area line its dash while the fill stays solid', () => {
    const data = bars(4);
    const got = frame(rig(), 'area', data, { lineStyle: 'dotted', lineWidth: 2 });
    expect(fills(got)).toHaveLength(3);
    expect(segments(got).length).toBeGreaterThan(3);
    expect(segments(got).every((s) => s.hw === 1 && s.round)).toBe(true);
  });

  it('splits the baseline fill at the base into a faded upper part and a flat lower part, and the stroke by side', () => {
    // Closes 96, 104, 96, 104: every span crosses the base at 100.
    const data: Bar[] = [96, 104, 96, 104].map((v, i) => ({ time: T0 + i, open: v, high: v, low: v, close: v }));
    const got = frame(rig(), 'baseline', data, { baseValue: 100 });
    const baseY = priceToY(100);
    const f = fills(got);
    // Three spans, each two lobes: three above, three below.
    expect(f).toHaveLength(6);
    const topFill = parsePremultiplied(darkTheme.baselineTopFill) as PremultipliedRgba;
    const botFill = rgba(darkTheme.baselineBottomFill);
    const above = f.filter((q) => q.pts[0][1] < baseY);
    const below = f.filter((q) => q.pts[0][1] > baseY);
    expect(above).toHaveLength(3);
    expect(below).toHaveLength(3);
    for (const q of above) {
      // Triangle: apex at the point, two corners on the base at the crossing and under the point.
      expect(q.pts[1][1]).toBe(baseY);
      expect(q.pts[2][1]).toBe(baseY);
      const t = q.pts[0][1] / baseY;
      expect(sameColor(q.colors[0], topFill.map((c) => c * (1 - t)))).toBe(true);
      expect(q.colors[1]).toEqual([0, 0, 0, 0]);
    }
    for (const q of below) {
      expect(q.colors.every((c) => sameColor(c, botFill))).toBe(true);
    }
    // The crossing sits midway: symmetric closes either side of the base.
    expect(above[0].pts[1][0]).toBe(14);
    expect(below[0].pts[1][0]).toBe(14);
    // Strokes: butt, one per span, coloured by the midpoint side (all three straddle exactly: midpoint on the base counts as above).
    const s = segments(got);
    expect(s).toHaveLength(3);
    expect(s.every((seg) => !seg.round && seg.hw === 1)).toBe(true);
    expect(s.every((seg) => sameColor(seg.color, rgba(darkTheme.baselineTopLine)))).toBe(true);
    // A series entirely below takes the bottom line colour and only flat fills.
    const low = frame(rig(), 'baseline', data.map((b) => ({ ...b, close: b.close - 20 })), { baseValue: 100 });
    expect(segments(low).every((seg) => sameColor(seg.color, rgba(darkTheme.baselineBottomLine)))).toBe(true);
    expect(fills(low)).toHaveLength(3);
    expect(fills(low).every((q) => q.pts[0][1] > baseY)).toBe(true);
  });

  it('fills the HLC band between highs and lows, strokes only the edges named, then the close line', () => {
    const data = bars(5);
    const got = frame(rig(), 'hlc-area', data, {});
    const f = fills(got);
    expect(f).toHaveLength(4);
    for (let i = 0; i < 4; i++) {
      expectShapes([f[i]], [{ kind: 'fill', colors: f[i].colors, pts: [
        [10 + i * 8, priceToY(data[i].high)], [18 + i * 8, priceToY(data[i + 1].high)],
        [10 + i * 8, priceToY(data[i].low)], [18 + i * 8, priceToY(data[i + 1].low)],
      ] }]);
      expect(sameColor(f[i].colors[0], rgba('rgba(79,140,255,0.15)'))).toBe(true);
    }
    // Close line only: four round segments in the theme line colour.
    expect(segments(got)).toHaveLength(4);
    expect(sameColor(segments(got)[0].color, rgba(darkTheme.lineColor))).toBe(true);
    const edged = frame(rig(), 'hlc-area', data, { highColor: '#ff0000', lowColor: '#0000ff', lineWidth: 2 });
    const s = segments(edged);
    expect(s).toHaveLength(12);
    expect(s.slice(0, 4).every((seg) => sameColor(seg.color, rgba('#ff0000')))).toBe(true);
    expect(s.slice(4, 8).every((seg) => sameColor(seg.color, rgba('#0000ff')))).toBe(true);
    expect(s[0].y0).toBeCloseTo(priceToY(data[0].high), 3);
    expect(s[4].y0).toBeCloseTo(priceToY(data[0].low), 3);
  });
});

// ── the 2D fallback ─────────────────────────────────────────────────────────

describe('fallback to the 2D context', () => {
  const custom = (log: string[]): RendererEntry => ({
    defaultStyle: {}, isPriceSeries: true,
    draw: (g, its) => { log.push('draw'); g.fillRect(1, 2, 3, its.length); },
    extents: (b) => ({ min: b.low, max: b.high }),
  });

  it('flushes what was batched, then lets the entry paint on the overlay, keeping z-order', () => {
    const r = rig();
    const log: string[] = [];
    r.backend.beginFrame(true);
    r.backend.drawSeries(getChartType('candlestick'), items(bars(5), 8), priceToY, 8, 1, { borderVisible: false }, rc());
    r.backend.drawSeries(custom(log), items(bars(2), 8), priceToY, 8, 1, {}, rc());
    r.backend.drawSeries(getChartType('histogram'), items(bars(3), 8), priceToY, 8, 1, {}, rc());
    r.backend.endFrame();
    expect(log).toEqual(['draw']);
    // Candles blitted, the custom fillRect, then the histogram blitted at end.
    expect(r.rec.ops.map((o) => o.type)).toEqual(['setTransform', 'clearRect', 'drawImage', 'fillRect', 'drawImage']);
    expect(r.rec.ops[3].args).toEqual([1, 2, 3, 2]);
    expect(r.surface.gl.uploads).toHaveLength(2);
    expect(decode(r.surface.gl.uploads[0])).toHaveLength(10);
    expect(decode(r.surface.gl.uploads[1])).toHaveLength(3);
  });

  it('takes the whole frame through 2D while the device has no context or a lost one', () => {
    const none = rig(false);
    none.backend.beginFrame(true);
    none.backend.drawSeries(getChartType('candlestick'), items(bars(4), 8), priceToY, 8, 1, {}, rc());
    none.backend.endFrame();
    expect(none.rec.count('fillRect')).toBe(8);
    expect(none.rec.count('drawImage')).toBe(0);

    const r = rig();
    frame(r, 'candlestick', bars(4));
    expect(r.rec.count('drawImage')).toBe(1);
    r.surface.fire('webglcontextlost');
    expect(r.device.lost).toBe(true);
    const programsBefore = r.surface.gl.programs;
    frame(r, 'candlestick', bars(4));
    expect(r.rec.count('fillRect')).toBe(8);
    expect(r.rec.count('drawImage')).toBe(1);
    expect(r.surface.gl.uploads).toHaveLength(1);
    r.surface.fire('webglcontextrestored');
    expect(r.device.lost).toBe(false);
    frame(r, 'candlestick', bars(4));
    // Back on the GPU, with the program rebuilt for the new context.
    expect(r.rec.count('drawImage')).toBe(2);
    expect(r.surface.gl.programs).toBe(programsBefore + 1);
    expect(r.surface.gl.uploads).toHaveLength(2);
  });

  it('drops the batch and finishes the frame in 2D when the context goes mid-frame', () => {
    const r = rig();
    r.backend.beginFrame(true);
    r.backend.drawSeries(getChartType('candlestick'), items(bars(4), 8), priceToY, 8, 1, {}, rc());
    r.surface.gl.lost = true;
    r.backend.drawSeries(getChartType('histogram'), items(bars(3), 8), priceToY, 8, 1, {}, rc());
    r.backend.endFrame();
    expect(r.rec.count('fillRect')).toBe(3);
    expect(r.rec.count('drawImage')).toBe(0);
    expect(r.surface.gl.uploads).toHaveLength(0);
  });

  it('gives up the GPU for good when the program will not compile', () => {
    const r = rig();
    r.surface.gl.failCompile = true;
    frame(r, 'candlestick', bars(4));
    expect(r.rec.count('drawImage')).toBe(0);
    expect(r.device.available).toBe(false);
    frame(r, 'candlestick', bars(4));
    expect(r.rec.count('fillRect')).toBe(8);
  });

  it('resolves colours the parser cannot read through the pane context, once', () => {
    const r = rig();
    let asked = 0;
    const ctx = r.ctx as unknown as { fillStyle: string };
    let current = '#000';
    Object.defineProperty(ctx, 'fillStyle', {
      get: () => current,
      set: (v: string) => { if (v === 'lime') { asked++; current = '#00ff00'; } else current = v; },
    });
    const data = bars(3).map((b) => ({ ...b, color: 'lime' }));
    const got = frame(r, 'histogram', data);
    expect(got.every((s) => s.kind === 'rect' && sameColor(s.color, rgba('#00ff00')))).toBe(true);
    expect(asked).toBe(2);
    frame(r, 'histogram', data);
    expect(asked).toBe(2);
  });
});

// ── through the chart ───────────────────────────────────────────────────────

describe('in a chart', () => {
  it('paints every pane through the shared device, blitting into each base canvas inside the plot clip', () => {
    const surface = new FakeSurface();
    const device = new GlDevice(() => surface);
    const chart = makeChart({ renderBackend: () => createWebGL2Backend(device) });
    expect(chart.renderer).toBe('webgl2');
    const data = bars(120);
    chart.addSeries('candlestick').setData(data);
    chart.addSeries('histogram', { paneIndex: 1 }).setData(
      data.map((b) => ({ time: b.time, open: 0, high: b.volume ?? 0, low: 0, close: b.volume ?? 0 })),
    );
    chart.fitContent();
    expect(device.refs).toBe(2);
    expect(surface.contexts).toBe(1);
    for (const pane of chart.panes()) {
      const ops = (pane.base.ctx as unknown as RecordingContext).ops;
      const types = ops.map((o) => o.type);
      // The blit sits between the plot clip and its restore, so the price
      // line and tags the pane draws afterwards land over the series.
      const blit = types.lastIndexOf('drawImage');
      const clip = types.lastIndexOf('clip', blit);
      const restore = types.indexOf('restore', clip);
      expect(clip).toBeGreaterThan(-1);
      expect(blit).toBeGreaterThan(clip);
      expect(blit).toBeLessThan(restore);
      // No candle rects on the 2D context: the chrome only.
      expect(ops.filter((o) => o.type === 'fillRect').length).toBeLessThan(40);
    }
    // The GPU drew the visible candles: a wick and a body each.
    const last = surface.gl.uploads[surface.gl.uploads.length - 2];
    expect(decode(last).length).toBeGreaterThan(100);
    chart.destroy();
    expect(device.refs).toBe(0);
  });

  it('is picked up by renderer auto once registered, and stands down to 2D when the device declines', () => {
    registerWebGL2Backend(new GlDevice(() => new FakeSurface()));
    const gl = makeChart({ renderer: 'auto' });
    expect(gl.renderer).toBe('webgl2');
    gl.destroy();
    registerWebGL2Backend(new GlDevice(() => new FakeSurface(false)));
    const fallback = makeChart({ renderer: 'webgl2' });
    expect(fallback.renderer).toBe('canvas2d');
    fallback.destroy();
  });
});
