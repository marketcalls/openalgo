/**
 * Richer pointer payloads (2.0). Every gesture event tells a host which
 * modifier keys were held, what device produced it and how hard it pressed,
 * and a drag carries the positions the browser coalesced between two move
 * events. None of it may change a default: the pre-2.0 fields are pinned by
 * exact key sets below, and the leave payload stays byte for byte what it was.
 *
 * The fake DOM does not synthesise PointerEvent, so the handlers are driven
 * directly, the way zoom-glide.test.ts drives `_onWheel`.
 */
import { describe, it, expect } from 'vitest';
import {
  Chart,
  type ChartClickEvent, type ChartDragEvent, type ChartDragEndEvent, type CrosshairMoveEvent, type PointerSample,
} from '../src/core/chart';
import { fakeDocument } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import type { IPrimitive, PrimitiveHit } from '../src/primitives/primitive';

const bars = (n = 60): Bar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: 1735689600 + i * 300,
    open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 10,
  }));

/** The private handlers and layout the tests reach into. */
interface Handlers {
  _onPointerDown(e: unknown): void;
  _onPointerMove(e: unknown): void;
  _onPointerUp(e: unknown): void;
  _onPointerLeave(): void;
  _onPointerCancel(e: unknown): void;
  _onKeyDown(e: unknown): void;
  _paneLayout(): { top: number; height: number }[];
}

/**
 * A MEASURED chart (applySize plus a synchronous raf, per CLAUDE.md): without
 * it every price scale sits on its 0..1 placeholder and the prices asserted
 * below would compare placeholder to placeholder.
 */
function makeChart(): { chart: Chart; h: Handlers } {
  const chart = new Chart(fakeDocument().createElement('div'), {
    document: fakeDocument(), pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars());
  return { chart, h: chart as unknown as Handlers };
}

/** A pointer-event-shaped object with no pressure key, like a synthetic event. */
const hover = (x: number, y: number, extra: Record<string, unknown> = {}): Record<string, unknown> => ({
  clientX: x, clientY: y, pointerId: 1, pointerType: 'mouse', button: 0, buttons: 0,
  preventDefault() {}, ...extra,
});
const press = (x: number, y: number, extra: Record<string, unknown> = {}): Record<string, unknown> =>
  hover(x, y, { buttons: 1, ...extra });
const release = hover;

/** Anything under the pointer is a two-axis draggable handle, so a press arms a drag. */
const grip: IPrimitive = {
  zOrder: () => 'top',
  draw: () => {},
  hitTest: (): PrimitiveHit => ({ externalId: 'grip', zOrder: 'top', distance: 0, draggable: true }),
};

function last<T>(list: T[]): T {
  return list[list.length - 1];
}

describe('crosshair:move pointer payload', () => {
  it('reports modifiers, device and pressure alongside every field it always carried', () => {
    const { chart, h } = makeChart();
    const seen: CrosshairMoveEvent[] = [];
    chart.on('crosshair:move', (p) => seen.push(p as CrosshairMoveEvent));
    h._onPointerMove(hover(400, 300, { shiftKey: true, altKey: true, pointerType: 'pen', pressure: 0.7 }));

    const e = last(seen);
    expect(e.modifiers).toEqual({ shift: true, alt: true, ctrl: false, meta: false });
    expect(e.pointerType).toBe('pen');
    expect(e.pressure).toBeCloseTo(0.7, 12);
    // The 1.x fields, untouched.
    expect(typeof e.time).toBe('number');
    expect(typeof e.index).toBe('number');
    expect(Number.isFinite(e.price)).toBe(true);
    expect(e.bar).not.toBeNull();
    expect(e.point).toEqual({ x: 400, y: 300 });
    expect(e.paneIndex).toBe(0);
    expect(e.pressed).toBe(false);
    expect(Object.keys(e).sort()).toEqual([
      'bar', 'index', 'modifiers', 'paneIndex', 'point', 'pointerType', 'pressed', 'pressure', 'price', 'time',
    ]);
  });

  it('hands the same payload to subscribeCrosshairMove', () => {
    const { chart, h } = makeChart();
    let seen: CrosshairMoveEvent | null = null;
    chart.subscribeCrosshairMove((p) => { seen = p; });
    h._onPointerMove(hover(400, 300, { ctrlKey: true, pointerType: 'touch' }));
    expect(seen).not.toBeNull();
    expect((seen as unknown as CrosshairMoveEvent).modifiers).toEqual({ shift: false, alt: false, ctrl: true, meta: false });
    expect((seen as unknown as CrosshairMoveEvent).pointerType).toBe('touch');
  });

  it('falls back to the spec stand-in when the event carries no pressure', () => {
    const { chart, h } = makeChart();
    const seen: CrosshairMoveEvent[] = [];
    chart.on('crosshair:move', (p) => seen.push(p as CrosshairMoveEvent));

    // A hover: no button, nothing measured, so 0.
    h._onPointerMove(hover(400, 300));
    expect(last(seen).pressure).toBe(0);
    expect(last(seen).modifiers).toEqual({ shift: false, alt: false, ctrl: false, meta: false });

    // A held mouse button while a host is placing a shape: 0.5, and pressed.
    chart.setPlacementMode(true);
    h._onPointerDown(press(400, 300));
    h._onPointerMove(press(410, 305));
    expect(last(seen).pressed).toBe(true);
    expect(last(seen).pressure).toBe(0.5);
  });

  it('carries the coalesced samples of a pressed move, and none on a hover', () => {
    // Placement mode never arms a drag, so a freehand stroke has only this
    // payload to read its trail from; a hover has no trail worth carrying.
    const { chart, h } = makeChart();
    const seen: CrosshairMoveEvent[] = [];
    chart.on('crosshair:move', (p) => seen.push(p as CrosshairMoveEvent));
    h._onPointerMove(hover(400, 300));
    expect('samples' in last(seen)).toBe(false);

    chart.setPlacementMode(true);
    h._onPointerDown(press(400, 300));
    h._onPointerMove(press(430, 320, {
      pointerType: 'pen', pressure: 0.6,
      getCoalescedEvents: () => [
        press(410, 305, { pressure: 0.2 }),
        press(420, 312, { pressure: 0.4 }),
        press(430, 320, { pressure: 0.6 }),
      ],
    }));
    const e = last(seen);
    expect(e.pressed).toBe(true);
    // The drag payload's space: container x, pane-local y (the top pane here,
    // so it coincides with the container y), last sample under the pointer.
    expect(e.samples).toEqual([
      { x: 410, y: 305, pressure: 0.2 },
      { x: 420, y: 312, pressure: 0.4 },
      { x: 430, y: 320, pressure: 0.6 },
    ]);
    expect(e.point).toEqual({ x: 430, y: 320 });
    expect(last(e.samples as PointerSample[]).pressure).toBe(e.pressure);
  });

  it('clamps a pressure outside 0..1 and reports an unnamed device as a mouse', () => {
    const { chart, h } = makeChart();
    const seen: CrosshairMoveEvent[] = [];
    chart.on('crosshair:move', (p) => seen.push(p as CrosshairMoveEvent));

    h._onPointerMove(hover(400, 300, { pressure: 1.5 }));
    expect(last(seen).pressure).toBe(1);
    h._onPointerMove(hover(401, 300, { pressure: -0.25 }));
    expect(last(seen).pressure).toBe(0);
    h._onPointerMove(hover(402, 300, { pointerType: '' }));
    expect(last(seen).pointerType).toBe('mouse');
    h._onPointerMove(hover(403, 300, { pointerType: undefined }));
    expect(last(seen).pointerType).toBe('mouse');
    h._onPointerMove(hover(404, 300, { pointerType: 'touch' }));
    expect(last(seen).pointerType).toBe('touch');
  });

  it('leaves the pointer-leave payload exactly as it was', () => {
    const { chart, h } = makeChart();
    const seen: unknown[] = [];
    chart.on('crosshair:move', (p) => seen.push(p));
    h._onPointerMove(hover(400, 300, { shiftKey: true }));
    h._onPointerLeave();
    expect(last(seen)).toEqual({ time: null, index: null, price: null, bar: null, point: null, paneIndex: null });
  });
});

describe('click pointer payload', () => {
  it('carries modifiers, device and press pressure while keeping the flat flags', () => {
    const { chart, h } = makeChart();
    const clicks: ChartClickEvent[] = [];
    chart.on('click', (p) => clicks.push(p as ChartClickEvent));
    h._onPointerDown(press(400, 300, { ctrlKey: true, pointerType: 'pen', pressure: 0.9 }));
    // A release always reads 0 pressure; the click must report the press.
    h._onPointerUp(release(400, 300, { ctrlKey: true, pointerType: 'pen', pressure: 0 }));

    expect(clicks).toHaveLength(1);
    const c = clicks[0];
    expect(c.id).toBeNull();
    expect(Number.isFinite(c.price)).toBe(true);
    expect(typeof c.time).toBe('number');
    expect(c.paneIndex).toBe(0);
    expect(c.point).toEqual({ x: 400, y: 300 });
    expect(c.shiftKey).toBe(false);
    expect(c.ctrlKey).toBe(true);
    expect(c.metaKey).toBe(false);
    expect(c.modifiers).toEqual({ shift: false, alt: false, ctrl: true, meta: false });
    expect(c.pointerType).toBe('pen');
    expect(c.pressure).toBeCloseTo(0.9, 12);
    expect(Object.keys(c).sort()).toEqual([
      'ctrlKey', 'id', 'metaKey', 'modifiers', 'paneIndex', 'point', 'pointerType', 'pressure', 'price', 'shiftKey', 'time',
    ]);
  });

  it('reports the spec 0.5 for a mouse press that measured nothing', () => {
    const { chart, h } = makeChart();
    const clicks: ChartClickEvent[] = [];
    chart.on('click', (p) => clicks.push(p as ChartClickEvent));
    h._onPointerDown(press(400, 300));
    h._onPointerUp(release(400, 300));
    expect(clicks[0].pressure).toBe(0.5);
    expect(clicks[0].pointerType).toBe('mouse');
  });

  it('gives both halves of a placement drag the same pointer facts', () => {
    const { chart, h } = makeChart();
    const clicks: ChartClickEvent[] = [];
    chart.on('click', (p) => clicks.push(p as ChartClickEvent));
    chart.setPlacementMode(true);
    h._onPointerDown(press(300, 300, { shiftKey: true }));
    h._onPointerMove(press(340, 320, { shiftKey: true }));
    h._onPointerUp(release(340, 320, { shiftKey: true }));

    expect(clicks).toHaveLength(2);
    expect(clicks[0].point).toEqual({ x: 300, y: 300 });
    expect(clicks[0].viaDrag).toBeUndefined();
    expect(clicks[1].point).toEqual({ x: 340, y: 320 });
    expect(clicks[1].viaDrag).toBe(true);
    for (const c of clicks) {
      expect(c.modifiers.shift).toBe(true);
      expect(c.shiftKey).toBe(true);
      expect(c.pointerType).toBe('mouse');
      expect(c.pressure).toBe(0.5);
    }
  });

  it('carries them on a click on a draggable primitive that never moved', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const clicks: ChartClickEvent[] = [];
    chart.on('click', (p) => clicks.push(p as ChartClickEvent));
    h._onPointerDown(press(400, 300, { metaKey: true, pressure: 0.3 }));
    h._onPointerUp(release(400, 300, { metaKey: true }));

    expect(clicks).toHaveLength(1);
    expect(clicks[0].id).toBe('grip');
    expect(clicks[0].metaKey).toBe(true);
    expect(clicks[0].modifiers).toEqual({ shift: false, alt: false, ctrl: false, meta: true });
    expect(clicks[0].pressure).toBeCloseTo(0.3, 12);
  });
});

describe('drag pointer payload', () => {
  it('adds the point and the coalesced samples in the same space, keeping the grab origin', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const drags: ChartDragEvent[] = [];
    chart.on('drag', (p) => drags.push(p as ChartDragEvent));
    h._onPointerDown(press(400, 300));
    h._onPointerMove(press(430, 320, {
      altKey: true, pointerType: 'pen', pressure: 0.6,
      getCoalescedEvents: () => [
        press(410, 305, { pressure: 0.2 }),
        press(420, 312, { pressure: 0.4 }),
        press(430, 320, { pressure: 0.6 }),
      ],
    }));

    expect(drags).toHaveLength(1);
    const d = drags[0];
    expect(d.id).toBe('grip');
    expect(d.paneIndex).toBe(0);
    expect(d.price).toBeCloseTo(chart.coordinateToPrice(320) as number, 9);
    expect(d.fromPrice).toBeCloseTo(chart.coordinateToPrice(300) as number, 9);
    expect(typeof d.time).toBe('number');
    expect(typeof d.fromTime).toBe('number');
    expect(d.point).toEqual({ x: 430, y: 320 });
    expect(d.samples).toEqual([
      { x: 410, y: 305, pressure: 0.2 },
      { x: 420, y: 312, pressure: 0.4 },
      { x: 430, y: 320, pressure: 0.6 },
    ]);
    expect(last(d.samples)).toEqual({ ...d.point, pressure: d.pressure });
    expect(d.modifiers).toEqual({ shift: false, alt: true, ctrl: false, meta: false });
    expect(d.pointerType).toBe('pen');
    expect(d.pressure).toBeCloseTo(0.6, 12);
    expect(Object.keys(d).sort()).toEqual([
      'fromPrice', 'fromTime', 'id', 'modifiers', 'paneIndex', 'point', 'pointerType', 'pressure', 'price', 'samples', 'time',
    ]);
  });

  it('falls back to the event itself when coalesced events are absent or empty', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const drags: ChartDragEvent[] = [];
    chart.on('drag', (p) => drags.push(p as ChartDragEvent));
    h._onPointerDown(press(400, 300));
    h._onPointerMove(press(430, 320));
    h._onPointerMove(press(440, 330, { getCoalescedEvents: () => [] }));

    expect(drags).toHaveLength(2);
    expect(drags[0].samples).toEqual([{ x: 430, y: 320, pressure: 0.5 }]);
    expect(drags[1].samples).toEqual([{ x: 440, y: 330, pressure: 0.5 }]);
  });

  it('keeps samples pane-local on a lower pane, like the point', () => {
    const { chart, h } = makeChart();
    chart.addSeries('histogram', { paneIndex: 1 }).setData([{ time: 1735689600, open: 0, high: 5, low: 0, close: 5 }]);
    chart.addPrimitive(grip, 1);
    const drags: ChartDragEvent[] = [];
    chart.on('drag', (p) => drags.push(p as ChartDragEvent));
    const top = h._paneLayout()[1].top;
    expect(top).toBeGreaterThan(0);
    // Well clear of the divider, which would win the press over the primitive.
    const y0 = top + 40;
    h._onPointerDown(press(400, y0));
    h._onPointerMove(press(420, y0 + 10, {
      getCoalescedEvents: () => [press(410, y0 + 5), press(420, y0 + 10)],
    }));

    const d = drags[0];
    expect(d.paneIndex).toBe(1);
    expect(d.point).toEqual({ x: 420, y: 50 });
    expect(d.samples.map((s) => s.y)).toEqual([45, 50]);
  });

  it('drag:end carries the release point and pointer facts', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const ends: ChartDragEndEvent[] = [];
    chart.on('drag:end', (p) => ends.push(p as ChartDragEndEvent));
    h._onPointerDown(press(400, 300));
    h._onPointerMove(press(430, 320));
    h._onPointerUp(release(440, 330, { metaKey: true }));

    expect(ends).toHaveLength(1);
    const e = ends[0];
    expect(e.id).toBe('grip');
    expect(e.paneIndex).toBe(0);
    expect(e.price).toBeCloseTo(chart.coordinateToPrice(330) as number, 9);
    expect(typeof e.time).toBe('number');
    expect(e.point).toEqual({ x: 440, y: 330 });
    expect(e.modifiers).toEqual({ shift: false, alt: false, ctrl: false, meta: true });
    expect(e.pointerType).toBe('mouse');
    expect(e.pressure).toBe(0);
    expect(Object.keys(e).sort()).toEqual([
      'id', 'modifiers', 'paneIndex', 'point', 'pointerType', 'pressure', 'price', 'time',
    ]);
  });

  it('leaves the subscribeDrag callbacks as they were', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const moves: unknown[][] = [];
    const ends: unknown[][] = [];
    chart.subscribeDrag((...args) => moves.push(args), (...args) => ends.push(args));
    h._onPointerDown(press(400, 300));
    h._onPointerMove(press(430, 320, { getCoalescedEvents: () => [press(415, 310), press(430, 320)] }));
    h._onPointerUp(release(430, 320));

    expect(moves).toHaveLength(1);
    expect(moves[0]).toHaveLength(3);
    expect(moves[0][0]).toBe('grip');
    expect(ends).toHaveLength(1);
    expect(ends[0]).toHaveLength(3);
  });
});


describe('primitive drag lifecycle', () => {
  it('announces the press before the first move without requiring a drag callback', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const starts: ChartDragEndEvent[] = [];
    chart.on('drag:start', (p) => starts.push(p as ChartDragEndEvent));
    h._onPointerDown(press(400, 300, { pointerType: 'pen', pressure: 0.7 }));
    expect(starts).toHaveLength(1);
    expect(starts[0]).toMatchObject({ id: 'grip', paneIndex: 0, point: { x: 400, y: 300 }, pointerType: 'pen', pressure: 0.7 });
    expect(starts[0].price).toBeCloseTo(chart.coordinateToPrice(300) as number, 9);
  });

  it('cancels before the legacy release notification and suppresses a cancelled click', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const events: string[] = [];
    chart.on('drag:cancel', (p) => { expect(p).toEqual({ id: 'grip', paneIndex: 0, reason: 'pointercancel' }); events.push('cancel'); });
    chart.on('drag:end', () => events.push('end'));
    chart.on('click', () => events.push('click'));
    h._onPointerDown(press(400, 300));
    h._onPointerCancel(release(400, 300));
    expect(events).toEqual(['cancel', 'end']);
  });

  it('cancels a single-pointer drag when a second finger starts a pinch', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const cancelled: unknown[] = [];
    chart.on('drag:cancel', (p) => cancelled.push(p));
    h._onPointerDown(press(400, 300, { pointerType: 'touch', pointerId: 1 }));
    h._onPointerDown(press(500, 300, { pointerType: 'touch', pointerId: 2 }));
    expect(cancelled).toEqual([{ id: 'grip', paneIndex: 0, reason: 'pinch' }]);
  });

  it('Escape cancels an active drag even with shortcuts disabled and consumes its release', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive({ ...grip, hitTest: () => ({ ...grip.hitTest!(0, 0, {} as never)!, cancelOnEscape: true }) }, 0);
    const events: string[] = [];
    chart.on('drag:cancel', () => events.push('cancel'));
    chart.on('drag:end', () => events.push('end'));
    chart.on('click', () => events.push('click'));
    h._onPointerDown(press(400, 300));
    h._onKeyDown({ key: 'Escape', target: null, preventDefault() {} });
    h._onPointerUp(release(400, 300));
    expect(events).toEqual(['cancel']);
    h._onPointerDown(press(400, 300));
    h._onPointerUp(release(400, 300));
    expect(events).toEqual(['cancel', 'end', 'click']);
  });

  it('preserves release notifications for primitives that did not opt into Escape cancellation', () => {
    const { chart, h } = makeChart();
    chart.addPrimitive(grip, 0);
    const events: string[] = [];
    chart.on('drag:cancel', () => events.push('cancel'));
    chart.on('drag:end', () => events.push('end'));
    h._onPointerDown(press(400, 300));
    h._onPointerMove(press(400, 320));
    h._onKeyDown({ key: 'Escape', target: null, preventDefault() {} });
    h._onPointerUp(release(400, 320));
    expect(events).toEqual(['end']);
  });

  it('keeps points, coalesced samples and release in the grabbed pane across pane boundaries', () => {
    const { chart, h } = makeChart();
    chart.addSeries('histogram', { paneIndex: 1 }).setData([{ time: 1735689600, open: 0, high: 5, low: 0, close: 5 }]);
    chart.addPrimitive(grip, 1);
    const top = h._paneLayout()[1].top;
    const drags: ChartDragEvent[] = [];
    const ends: ChartDragEndEvent[] = [];
    chart.on('drag', (p) => drags.push(p as ChartDragEvent));
    chart.on('drag:end', (p) => ends.push(p as ChartDragEndEvent));
    h._onPointerDown(press(400, top + 40));
    h._onPointerMove(press(420, top - 20, { getCoalescedEvents: () => [press(410, top - 10), press(420, top - 20)] }));
    h._onPointerUp(release(420, top - 20));
    expect(drags[0].point.y).toBe(-20);
    expect(drags[0].samples.map((p) => p.y)).toEqual([-10, -20]);
    expect(ends[0].point.y).toBe(-20);
    expect(ends[0].price).toBeCloseTo(chart.coordinateToPrice(top - 20, 1) as number, 9);
  });
});
