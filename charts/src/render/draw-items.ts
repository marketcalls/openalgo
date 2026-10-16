/**
 * The draw items one series hands its renderer each frame, built without
 * allocating per bar.
 *
 * The series pass runs on every frame of a pan, a zoom or a live tick, and it
 * used to build two fresh objects for every visible bar each time: the
 * data layer's `{ index, bar }` pair and the renderer's `{ x, bar }` item, and
 * the autoscale walk built the pairs again. Nothing kept any of it past the
 * frame; it was garbage for the collector at the rate of the frame times the
 * bars in view (scripts/bench-pane.mjs measures it). Here the visible bars are
 * walked in place and written into items owned by the series, reused from one
 * frame to the next.
 *
 * Contract for a renderer or a render backend: `items`, and the objects in it,
 * are valid until the same series is drawn again. Anything kept longer has to
 * be copied. They are the bars in view, and for a renderer that joins
 * neighbouring bars (`RendererEntry.connectsBars`) the series' nearest bar
 * beyond each edge as well, marked with the edge it lies beyond
 * (`DrawItem.edgeX`).
 */
import type { Bar } from '../model/bar';
import type { DrawItem } from '../model/chart-type-registry';
import { visibleSpan, type DataLayer, type SeriesId, type VisibleSpan } from '../model/data-layer';
import type { TimeScale } from '../scale/time-scale';
import { createLodColumns, type LodKind } from '../model/conflation';

/** The level of detail a frame asks for: the reduction, and the ratio and factor its columns follow. */
export interface LodRequest {
  kind: LodKind;
  dpr: number;
  factor: number;
}

/** Placeholder bar for a pooled item not in this frame; never drawn. */
const NO_BAR: Bar = { time: 0, open: NaN, high: NaN, low: NaN, close: NaN };

/** Items a series keeps however far the view zooms back in: a wide plot's worth. */
const POOL_KEEP = 4096;

/** Scratch for the visible walk: `build` runs start to end without yielding, so one serves every series. */
const SPAN: VisibleSpan = { start: 0, lastTime: 0 };

/**
 * A pooled item. `prevClose` and `edgeX` hold undefined rather than being
 * absent, which a renderer reads the same, so the pool says so and hands the
 * item on as a `DrawItem`.
 */
type PooledItem = Omit<DrawItem, 'prevClose' | 'edgeX'> & { prevClose?: number | undefined; edgeX?: number | undefined };

/** What maps a price to media-px y: a price scale. */
interface PriceMapper {
  priceToY(price: number): number;
}

export interface SeriesDrawItems {
  /** This frame's items, in drawing order. The same array every frame. */
  readonly items: DrawItem[];
  /**
   * Maps with the scale the last `build` was given. One function for the life
   * of the series, so the renderer's call to it keeps a single target and the
   * compiler can fold it in, rather than a new closure every frame.
   */
  readonly priceToY: (price: number) => number;
  /** Logical index of the first bar in view in the last `build`, or -1 when none was. */
  firstIndex(): number;
  /**
   * Fill `items` with the bars of series `id` whose logical index, shifted by
   * `shift`, lands in [from + shift, to + shift], each at the x its shifted
   * index maps to. With `lod`, the bars go through the level of detail on the
   * way and `items` holds its columns instead. With `edges`, the series' bar
   * just before and just after that span are included too, off screen and
   * marked with `edgeX`, for a renderer that draws a segment between
   * neighbouring bars. They bypass the level of detail: a bar off screen
   * belongs to no column, and the columns in view stay what they are without it.
   */
  build(
    layer: DataLayer, id: SeriesId, from: number, to: number, shift: number, timeScale: TimeScale,
    scale: PriceMapper, lod: LodRequest | null, edges?: boolean,
  ): DrawItem[];
}

/**
 * One series' draw items. A closure rather than a class, for the same reason
 * as `createLodColumns`: its state costs the bundle a letter a name.
 */
export function createSeriesDrawItems(): SeriesDrawItems {
  const items: DrawItem[] = [];
  /** Item objects, reused: the first `count` of them are this frame's. */
  const pool: PooledItem[] = [];
  let count = 0, first = -1;
  let mapper: PriceMapper | null = null;
  const push = (x: number, bar: Bar): void => {
    const n = count++;
    let item = pool[n];
    if (item === undefined) {
      // `prevClose` and `edgeX` are present from the start, so setting one
      // later never reshapes the object.
      item = { x: 0, bar: NO_BAR, prevClose: undefined, edgeX: undefined };
      pool.push(item);
    }
    item.x = x;
    item.bar = bar;
    item.prevClose = undefined;
    item.edgeX = undefined;
    items[n] = item as DrawItem;
  };
  /**
   * The neighbour beyond an edge, marked with that edge's x. Made once with
   * the buffer rather than inside `build`, so a frame allocates nothing for it.
   */
  const pushEdge = (layer: DataLayer, bar: Bar, shift: number, timeScale: TimeScale, edgeX: number): void => {
    const index = layer.timeToIndex(bar.time);
    if (index === undefined) return;
    push(timeScale.indexToX(index + shift), bar);
    items[count - 1]!.edgeX = edgeX; // the item push just wrote
  };
  const lodColumns = createLodColumns(push);
  return {
    items,
    priceToY: (price: number): number => (mapper as PriceMapper).priceToY(price),
    firstIndex: (): number => first,
    build(layer, id, from, to, shift, timeScale, scale, lod, edges = false): DrawItem[] {
      mapper = scale;
      count = 0;
      first = -1;
      const bars = layer.seriesBars(id);
      if (visibleSpan(layer, bars, from, to, SPAN)) {
        // SPAN.start is at most bars.length, and each read of `bars` below is
        // under bars.length: past SPAN.start after the test on it, in the loop,
        // or after the test on `i`.
        const last = SPAN.lastTime;
        if (edges && SPAN.start > 0) pushEdge(layer, bars[SPAN.start - 1]!, shift, timeScale, 0);
        if (lod !== null) lodColumns.begin(lod.kind, lod.dpr, lod.factor);
        let i = SPAN.start;
        for (; i < bars.length; i++) {
          const bar = bars[i]!;
          if (bar.time > last) break;
          const index = layer.timeToIndex(bar.time);
          if (index === undefined) continue;
          if (first < 0) first = index;
          const x = timeScale.indexToX(index + shift);
          if (lod !== null) lodColumns.push(x, bar);
          else push(x, bar);
        }
        if (lod !== null) lodColumns.end();
        if (edges && i < bars.length) pushEdge(layer, bars[i]!, shift, timeScale, timeScale.width);
      }
      if (items.length !== count) {
        // Items this frame did not reach let go of their bars, so a pool sized
        // for yesterday's history does not keep that history alive. Every item
        // came from the pool, so the pool is at least as long as `items`.
        for (let i = count; i < items.length; i++) pool[i]!.bar = NO_BAR;
        items.length = count;
      }
      // A view zoomed back in from a very wide one gives the spare items back.
      if (pool.length > POOL_KEEP && count * 4 < pool.length) pool.length = Math.max(POOL_KEEP, count * 2);
      return items;
    },
  };
}
