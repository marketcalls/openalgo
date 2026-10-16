/**
 * The render backend port (ARCHITECTURE.md section 3). A pane paints its series
 * through one of these and draws everything else (background, grid, primitives,
 * axes) on a 2D context itself, so a backend that rasterises series on the GPU
 * plugs in without the pane, the registry or any renderer learning about it.
 *
 * The port is deliberately narrow. It covers the one hot path a GPU can take
 * over, the per-frame series pass, and nothing the 2D context already does
 * well. Text, dashed lines, gradients and the drawing tools stay on canvas 2D.
 *
 * Which backend a chart gets is decided once, at construction, by the
 * `renderer` chart option or an injected factory. This module keeps the
 * registry that resolves the option; the shipped 2D backend registers itself
 * from its own module, and a later tier registers `webgl2` the same way, so
 * this file never has to import either.
 */
import type { DrawItem, RendererEntry, SeriesRenderContext } from '../model/chart-type-registry';
import type { SeriesStyle } from './series-style';

/** The backends the port can name. Only `canvas2d` ships in the base tier. */
export type RenderBackendKind = 'canvas2d' | 'webgl2';

/**
 * The `renderer` chart option. `'auto'` picks `webgl2` when a backend of that
 * kind is registered and available on this device, and `canvas2d` otherwise,
 * which is every chart until that tier is imported.
 */
export type RendererChoice = RenderBackendKind | 'auto';

/**
 * Paints one pane's series. One instance per pane: a backend holds a context
 * on that pane's base canvas, and contexts do not travel between canvases.
 */
export interface IRenderBackend {
  readonly kind: RenderBackendKind;
  /**
   * Take the pane's base data canvas. `ctx2d` is the 2D context the pane
   * already holds on it, when it holds one: the canvas-2D backend draws on
   * exactly that object, so a frame is one context's op stream and not two
   * contexts' interleaved. A backend that owns the canvas outright ignores it.
   */
  mount(canvas: HTMLCanvasElement, ctx2d: CanvasRenderingContext2D | null): void;
  /** The pane's media size and pixel ratio changed. Sizes in CSS px. */
  resize(widthPx: number, heightPx: number, dpr: number): void;
  /** Start a frame on the base canvas, clearing it first when asked. */
  beginFrame(clear: boolean): void;
  /**
   * Paint one series. Same contract as `RendererEntry.draw` minus the context:
   * `priceToY` and `items[].x` are media px, and the renderer snaps to device
   * pixels with `dpr` itself.
   *
   * `items` and the objects in it belong to the pane, which rewrites them in
   * place the next time it draws this series, so a backend that keeps any of
   * it past that (a batch held across frames, say) copies what it keeps.
   */
  drawSeries(
    entry: RendererEntry,
    items: readonly DrawItem[],
    priceToY: (price: number) => number,
    barSpacing: number,
    dpr: number,
    style: SeriesStyle,
    rc: SeriesRenderContext,
  ): void;
  /** Finish the frame: flush whatever the backend batched. */
  endFrame(): void;
  /**
   * A 2D context for what the backend does not draw natively (grid, axes,
   * primitives), or null when the backend paints those itself.
   */
  overlay2d(): CanvasRenderingContext2D | null;
  /** Release the context and any GPU resources. The pane removes the canvas. */
  destroy(): void;
  /**
   * The GPU device behind the backend, when it has one. The chart reads it
   * after a frame (`backendDegradation`) to learn that the context has been
   * lost or never came up, and moves every pane to `canvas2d` for the rest of
   * the session, announced by the 'renderer:fallback' chart event. A backend
   * without a device is never degraded, so the 2D backend leaves it unset.
   */
  readonly device?: RenderDevice;
}

/**
 * What the chart needs to know about a GPU device. `available` is whether it
 * ever got a usable context (a driver that cannot run the program counts as
 * never having one), and `lost` is the window between a context loss and its
 * restoration.
 */
export interface RenderDevice {
  readonly available: boolean;
  readonly lost: boolean;
}

/**
 * Why a chart left its GPU backend: the context went away mid-session, or
 * the device turned out to be unusable after the backend was built (the
 * program failed to compile on a live context).
 */
export type RendererFallbackReason = 'context-lost' | 'unavailable';

/**
 * Whether a backend is painting through its own 2D fallback rather than the
 * path it was chosen for, and why. Null for a healthy backend and always for
 * `canvas2d`, which has nothing to fall back from.
 */
export function backendDegradation(backend: IRenderBackend): RendererFallbackReason | null {
  if (backend.kind === 'canvas2d' || backend.device === undefined) return null;
  if (backend.device.lost) return 'context-lost';
  if (!backend.device.available) return 'unavailable';
  return null;
}

/**
 * Builds a backend for one pane, or returns null to decline: a `webgl2`
 * factory on a device without WebGL2 says so here, and the chart falls back
 * to `canvas2d` rather than painting nothing.
 */
export type RenderBackendFactory = () => IRenderBackend | null;

const factories = new Map<RenderBackendKind, RenderBackendFactory>();

/** Register (or replace) the factory for a backend kind. */
export function registerRenderBackend(kind: RenderBackendKind, factory: RenderBackendFactory): void {
  factories.set(kind, factory);
}

/**
 * Drop a registered backend. The 2D backend is refused: it is the fallback
 * every other choice lands on, and a chart with no backend paints nothing.
 */
export function unregisterRenderBackend(kind: RenderBackendKind): boolean {
  if (kind === 'canvas2d') return false;
  return factories.delete(kind);
}

export function registeredRenderBackends(): RenderBackendKind[] {
  return Array.from(factories.keys());
}

/**
 * Turn the `renderer` option into a factory the chart calls once per pane.
 *
 * An explicit kind that nothing has registered throws, the way an unloaded
 * chart type does: the caller asked for a tier they did not import, and a
 * silent 2D fallback would hide that. A registered factory that declines at
 * run time (no WebGL2 on this device) falls back to `canvas2d` instead,
 * because that is a property of the machine, not a mistake in the code.
 */
export function resolveRenderBackend(choice: RendererChoice = 'canvas2d'): RenderBackendFactory {
  const fallback = factories.get('canvas2d');
  if (fallback === undefined) throw new Error('openalgo-charts: no canvas2d render backend is registered');
  if (choice === 'auto') {
    const gl = factories.get('webgl2');
    if (gl === undefined) return fallback;
    return () => gl() ?? fallback();
  }
  const factory = factories.get(choice);
  if (factory === undefined) {
    throw new Error(`openalgo-charts: render backend "${choice}" is not registered; import the tier that provides it first`);
  }
  if (choice === 'canvas2d') return factory;
  return () => factory() ?? fallback();
}

/** One backend instance for the given choice; see `resolveRenderBackend`. */
export function createRenderBackend(choice: RendererChoice = 'canvas2d'): IRenderBackend {
  const backend = resolveRenderBackend(choice)();
  // The canvas2d fallback never declines, so the only way here is a custom
  // canvas2d factory that did. Nobody asked for that, so say so.
  if (backend === null) throw new Error('openalgo-charts: the canvas2d render backend factory returned null');
  return backend;
}
