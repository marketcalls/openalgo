/**
 * A click on a primitive must fire once.
 *
 * `_onPointerMove` carries a missed-release recovery: if the primary button is
 * no longer held while a drag is live, it calls `_onPointerUp` to end the
 * gesture, because a release over a context menu or outside the window never
 * reaches us. The recovery reads `_dragging`, and the branch that ends a
 * primitive drag returned without clearing it. So the release fired the click,
 * left `_dragging` true, and the next pointer move with no button held ran
 * `_onPointerUp` a second time -- now with `_dragId` already null, so it fell
 * through to the plain click path and emitted a second click at the stale
 * `_downX` / `_downLocalY`.
 *
 * Every host control addressed by `subscribeClick` is hit by that: an indicator
 * legend's hide, move-pane and maximize, a comparison row's remove, an order
 * pill's cancel. Each fires twice, and a toggle that fires twice is a control
 * that looks dead.
 */
import { describe, it, expect, beforeAll } from 'vitest';
import { Chart } from '../src/core/chart';
import { fakeDocument, pointer, type FakeElement } from './helpers/fake-dom';
import type { Bar } from '../src/model/bar';
import { PriceLine } from '../src/primitives/price-line';

// The chart only wires its pointer handlers when it can see a window.
beforeAll(() => {
  const g = globalThis as unknown as { window?: unknown };
  g.window ??= {};
});

const bars = (n = 60): Bar[] =>
  Array.from({ length: n }, (_, i) => ({
    time: 1735689600 + i * 300,
    open: 100 + i, high: 101 + i, low: 99 + i, close: 100.5 + i, volume: 10,
  }));

function makeChart(): { chart: Chart; el: FakeElement } {
  const el = fakeDocument().createElement('div') as unknown as FakeElement;
  const chart = new Chart(el, {
    document: fakeDocument(), pixelRatio: () => 1, shortcuts: false,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
  });
  chart.applySize(800, 600);
  chart.addSeries('candlestick').setData(bars());
  return { chart, el };
}

/**
 * A draggable price line, which is what arms `_dragId` on the press. That is the
 * branch the recovery re-enters: a plain press on the plot takes the other path
 * and was never affected.
 *
 * `ns-resize` plus a registered `subscribeDrag` is the documented way a price
 * line arms, so both are set here.
 */
function clickableLine(chart: Chart): void {
  chart.subscribeDrag(() => {}, () => {});
  chart.addPrimitive(new PriceLine({
    price: 130, id: 'legend::hide', cursor: 'ns-resize',
    color: '#4f8cff',
  }), 0);
}

describe('a press on a primitive fires one click, not two', () => {
  it('does not fire again on a stray move after the release', () => {
    const { chart, el } = makeChart();
    clickableLine(chart);
    const clicks: string[] = [];
    chart.subscribeClick((id) => clicks.push(id));

    const y = chart.priceToCoordinate(130) as number;
    el.dispatch('pointerdown', pointer('down', 400, y));
    // The stray move arrives BETWEEN press and release. A real mouse reports
    // buttons: 1 throughout a press, so this is the shape a release swallowed by
    // a context menu takes, and the shape a synthetic click takes. The recovery
    // sees `_dragId` still set, ends the gesture and fires the click.
    el.dispatch('pointermove', pointer('move', 400, y, { buttons: 0 }));
    // Then the real release lands, finds no drag armed, and used to fall
    // through to the plain click path and fire the same click a second time.
    el.dispatch('pointerup', pointer('up', 400, y));
    expect(clicks).toEqual(['legend::hide']);
  });

  it('leaves no drag state behind for the recovery to find', () => {
    const { chart, el } = makeChart();
    clickableLine(chart);
    const clicks: string[] = [];
    chart.subscribeClick((id) => clicks.push(id));

    const y = chart.priceToCoordinate(130) as number;
    el.dispatch('pointerdown', pointer('down', 400, y));
    // Several strays, in case only the first is swallowed.
    for (let i = 0; i < 3; i++) {
      el.dispatch('pointermove', pointer('move', 400, y, { buttons: 0 }));
    }
    el.dispatch('pointerup', pointer('up', 400, y));
    expect(clicks).toHaveLength(1);
  });

  it('still recovers a drag whose release was genuinely missed', () => {
    // The recovery has to keep working: this is the case it exists for, a
    // release swallowed by a context menu, and it must still end the drag.
    const { chart, el } = makeChart();
    const ends: string[] = [];
    chart.subscribeDrag(() => {}, (id) => ends.push(id));
    chart.addPrimitive(new PriceLine({
      price: 130, id: 'legend::hide', cursor: 'ns-resize',
      color: '#4f8cff',
    }), 0);

    const y = chart.priceToCoordinate(130) as number;
    el.dispatch('pointerdown', pointer('down', 400, y));
    el.dispatch('pointermove', pointer('move', 400, y + 40));
    // No pointerup at all. The next move with no button held ends it.
    el.dispatch('pointermove', pointer('move', 400, y + 40, { buttons: 0 }));
    expect(ends).toEqual(['legend::hide']);
  });

  it('fires one click for a plain press on the plot, too', () => {
    const { chart, el } = makeChart();
    let n = 0;
    chart.on('click', () => { n++; });
    el.dispatch('pointerdown', pointer('down', 300, 200));
    el.dispatch('pointerup', pointer('up', 300, 200));
    el.dispatch('pointermove', pointer('move', 302, 201, { buttons: 0 }));
    expect(n).toBe(1);
  });
});
