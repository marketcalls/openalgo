/**
 * The coordinates tab: every anchor as a date, a time on the chart's clock
 * and a price, edited exactly, validated, and written as one step.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import { utcSecondsToZonedParts, zonedWallClockToUtcSeconds, type Bar } from '../src/index';
import { createWidget, mountDrawingProperties, type Widget, type WidgetOptions } from '../src/widget/index';
import { formatAnchorPrice, parseTypedPrice } from '../src/widget/dialogs/drawing-coordinates';
import { formatWallClock as anchorWallClock, parseWallClock as parseAnchorTime } from '../src/widget/wall-clock';
import { ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey, type FakeElement } from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

// 09:15 IST on a Monday, five-minute bars.
const T0 = zonedWallClockToUtcSeconds(2026, 9, 14, 9, 15, 0, 'Asia/Kolkata');
const bars: Bar[] = (() => {
  let seed = 3;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  let close = 2468.35;
  return Array.from({ length: 70 }, (_, i) => {
    const open = close;
    close = Math.round((open + next() * 9) * 20) / 20;
    return { time: T0 + i * 300, open, high: Math.max(open, close) + 2.5, low: Math.min(open, close) - 2.5, close, volume: 900 + i };
  });
})();

const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

function make(opts: WidgetOptions = {}) {
  const doc = fakeWidgetDocument();
  const w = createWidget(fakeContainer(doc, 1000, 640) as unknown as HTMLElement, {
    document: doc as unknown as Document, mobile: 'never', pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...opts,
  });
  w.chart.applySize(900, 560);
  w.series.setData(bars);
  live.push(w);
  return { w, doc, root: w.root as unknown as FakeElement };
}

const trend = (w: Widget, extra: Record<string, unknown> = {}) => w.draw.add({
  tool: 'trend-line', paneIndex: 0, style: {},
  points: [{ time: bars[12].time, price: bars[12].low }, { time: bars[48].time, price: 2471.123456 }], ...extra,
});

/** Take the focus out of the dialog, as a click on the chart does. */
const leave = (w: Widget): void => { (w.root.querySelector('.oac-chart') as unknown as FakeElement).focus(); };

function open(w: Widget, ids: string[]) {
  const dialog = mountDrawingProperties(w.context, undefined, { ids, tab: 'coordinates' });
  const el = dialog.el as unknown as FakeElement;
  const row = (id: string, index: number) => {
    const line = el.querySelector(`[data-anchor="${id}:${index}"]`) as FakeElement;
    return {
      line,
      date: line.querySelector('.oac-coords__date') as FakeElement,
      time: line.querySelector('.oac-coords__time') as FakeElement,
      price: line.querySelector('.oac-coords__price') as FakeElement,
      error: line.querySelector('.oac-input-error') as FakeElement,
    };
  };
  return { dialog, el, row };
}

describe('typed anchor values', () => {
  it('reads prices with separators and refuses anything else', () => {
    expect(parseTypedPrice(' 2,468.35 ')).toBe(2468.35);
    expect(parseTypedPrice('-12.5')).toBe(-12.5);
    expect(parseTypedPrice('.5')).toBe(0.5);
    expect(parseTypedPrice('1e3')).toBe(1000);
    for (const bad of ['', 'abc', '12.3.4', '--1', '1e', 'Infinity', '0x10']) expect(parseTypedPrice(bad), bad).toBeNull();
  });

  it('shows a price at the pane precision when that is exact, and in full when it is not', () => {
    expect(formatAnchorPrice(2468.35, 2)).toBe('2468.35');
    expect(formatAnchorPrice(2468.3, 2)).toBe('2468.30');
    expect(formatAnchorPrice(2471.123456, 2)).toBe('2471.123456');
    expect(formatAnchorPrice(1e-7, 2)).toBe('1e-7');
  });

  it('reads a date and a time on a zone\'s clock, across a daylight saving change', () => {
    expect(parseAnchorTime('2026-09-14', '09:15', 'Asia/Kolkata')).toBe(T0);
    // New York is four hours behind UTC in July and five in December.
    expect(parseAnchorTime('2026-07-01', '09:30', 'America/New_York')).toBe(Date.UTC(2026, 6, 1, 13, 30) / 1000);
    expect(parseAnchorTime('2026-12-01', '09:30:15', 'America/New_York')).toBe(Date.UTC(2026, 11, 1, 14, 30, 15) / 1000);
    for (const [date, time] of [['2026-02-30', '09:15'], ['2026-13-01', '09:15'], ['14/09/2026', '09:15'], ['2026-09-14', '25:00'], ['2026-09-14', '9:5']]) {
      expect(parseAnchorTime(date, time, 'UTC'), `${date} ${time}`).toBeNull();
    }
    expect(anchorWallClock(T0, 'Asia/Kolkata')).toEqual({ date: '2026-09-14', time: '09:15', seconds: false });
    expect(anchorWallClock(T0 + 7, 'Asia/Kolkata')).toEqual({ date: '2026-09-14', time: '09:15:07', seconds: true });
  });
});

describe('the coordinates tab', () => {
  it('lists each anchor on the chart clock, IST unless the chart says otherwise', () => {
    const { w } = make();
    const d = trend(w);
    const { el, row } = open(w, [d.id]);
    expect(el.querySelector('[role="tab"][aria-selected="true"]')!.dataset.tab).toBe('coordinates');
    const first = row(d.id, 0);
    const wall = utcSecondsToZonedParts(bars[12].time, 'Asia/Kolkata');
    expect(first.date.value).toBe(`2026-09-${String(wall.day).padStart(2, '0')}`);
    expect(first.time.value).toBe(`${String(wall.hour).padStart(2, '0')}:${String(wall.minute).padStart(2, '0')}`);
    expect(first.price.value).toBe(formatAnchorPrice(bars[12].low, 2));
    expect(row(d.id, 1).price.value).toBe('2471.123456');
    expect(el.querySelector('.oac-coords__zone')!.textContent).toContain('Asia/Kolkata');
    const ny = make({ timezone: 'America/New_York' });
    const other = trend(ny.w);
    const shown = open(ny.w, [other.id]).row(other.id, 0);
    const there = utcSecondsToZonedParts(bars[12].time, 'America/New_York');
    expect(shown.time.value).toBe(`${String(there.hour).padStart(2, '0')}:${String(there.minute).padStart(2, '0')}`);
  });

  it('writes a typed price as one step and leaves an untouched field exactly as it was', () => {
    const { w } = make();
    const d = trend(w);
    const { row } = open(w, [d.id]);
    const second = row(d.id, 1);
    second.price.value = '2,480.5';
    fireKey(second.price, 'Enter');
    expect(w.draw.get(d.id)!.points[1].price).toBe(2480.5);
    // The time was not touched, so it did not move by a rounding.
    expect(w.draw.get(d.id)!.points[1].time).toBe(bars[48].time);
    const first = row(d.id, 0);
    first.time.focus();
    first.time.value = '10:45';
    leave(w);
    const expected = zonedWallClockToUtcSeconds(...(first.date.value.split('-').map(Number) as [number, number, number]), 10, 45, 0, 'Asia/Kolkata');
    expect(w.draw.get(d.id)!.points[0].time).toBe(expected);
    // The unedited price stays exactly as placed, not rounded to the field.
    expect(w.draw.get(d.id)!.points[1].price).toBe(2480.5);
    w.history.undo();
    expect(w.draw.get(d.id)!.points[0].time).toBe(bars[12].time);
    expect(w.draw.get(d.id)!.points[1].price).toBe(2480.5);
    w.history.undo();
    expect(w.draw.get(d.id)!.points[1].price).toBe(2471.123456);
  });

  it('refuses what does not read, says why, and writes nothing', () => {
    const { w } = make();
    const d = trend(w);
    const before = JSON.stringify(w.draw.get(d.id)!.points);
    const steps = w.draw.historySteps().undo.length;
    const { row } = open(w, [d.id]);
    const first = row(d.id, 0);
    first.price.value = 'twenty';
    fireKey(first.price, 'Enter');
    expect(first.price.getAttribute('aria-invalid')).toBe('true');
    expect(first.error.hidden).toBe(false);
    expect(first.error.textContent).toBe('Enter a price as a number');
    first.price.value = formatAnchorPrice(bars[12].low, 2);
    first.date.focus();
    first.date.value = '2026-02-30';
    leave(w);
    expect(first.date.getAttribute('aria-invalid')).toBe('true');
    expect(first.time.getAttribute('aria-invalid')).toBeNull();
    first.date.value = '2026-09-14';
    first.time.focus();
    first.time.value = '9 am';
    leave(w);
    expect(first.time.getAttribute('aria-invalid')).toBe('true');
    expect(first.error.textContent).toBe('Enter a date and a time on the chart clock');
    expect(JSON.stringify(w.draw.get(d.id)!.points)).toBe(before);
    expect(w.draw.historySteps().undo).toHaveLength(steps);
  });

  it('writes a row once, when the focus leaves it, however many changes its fields report on the way', () => {
    const { w } = make();
    const d = trend(w);
    const steps = w.draw.historySteps().undo.length;
    const { row } = open(w, [d.id]);
    const first = row(d.id, 0);
    const day = first.date.value.slice(0, 8);
    first.date.focus();
    // A date field typed segment by segment reports every value it passes
    // through, the years 0002, 0020 and 0202 among them.
    for (const typed of ['0002', '0020', '0202', '2026']) {
      first.date.value = `${typed}${first.date.value.slice(4)}`;
      fire(first.date, 'input');
      fire(first.date, 'change');
    }
    first.date.value = `${day}15`;
    fire(first.date, 'change');
    // Across the row is still the same edit.
    first.time.focus();
    first.time.value = '11:05';
    fire(first.time, 'change');
    first.price.focus();
    first.price.value = '2,455.5';
    fire(first.price, 'change');
    expect(w.draw.get(d.id)!.points[0]).toEqual({ time: bars[12].time, price: bars[12].low });
    leave(w);
    const [y, m] = day.split('-').map(Number);
    expect(w.draw.get(d.id)!.points[0]).toEqual({ time: zonedWallClockToUtcSeconds(y, m, 15, 11, 5, 0, 'Asia/Kolkata'), price: 2455.5 });
    expect(w.draw.historySteps().undo).toHaveLength(steps + 1);
    // Enter writes too, and the field then shows where the anchor landed.
    first.price.focus();
    first.price.value = '2,460.2';
    fireKey(first.price, 'Enter');
    expect(w.draw.get(d.id)!.points[0].price).toBe(2460.2);
    expect(first.price.value).toBe('2460.20');
    expect(w.draw.historySteps().undo).toHaveLength(steps + 2);
    // Leaving a row with nothing changed writes nothing.
    leave(w);
    expect(w.draw.historySteps().undo).toHaveLength(steps + 2);
  });

  it('refuses a price at or below zero on a logarithmic scale', () => {
    const { w } = make();
    w.chart.panes()[0].priceScale.setOptions({ mode: 'logarithmic' });
    const d = trend(w);
    const { row } = open(w, [d.id]);
    row(d.id, 0).price.value = '0';
    fireKey(row(d.id, 0).price, 'Enter');
    expect(row(d.id, 0).error.textContent).toBe('A logarithmic scale needs a price above zero');
    expect(w.draw.get(d.id)!.points[0].price).toBe(bars[12].low);
  });

  it('greys the fields of a read-only drawing, and says why a pinned or freehand one has none', () => {
    const { w, root } = make();
    const fixed = trend(w, { policy: { editable: false } });
    const { row, dialog } = open(w, [fixed.id]);
    for (const input of ['date', 'time', 'price'] as const) {
      expect((row(fixed.id, 0)[input] as unknown as { disabled: boolean }).disabled).toBe(true);
    }
    dialog.close();
    const pinned = w.draw.add({ tool: 'text', paneIndex: 0, style: {}, text: { value: 'Session high' }, space: 'viewport', points: [], viewportPoints: [{ x: 0.2, y: 0.2 }] });
    const stroke = w.draw.add({ tool: 'brush', paneIndex: 0, style: {}, points: bars.slice(5, 15).map((b) => ({ time: b.time, price: b.close })) });
    open(w, [pinned.id, stroke.id]);
    const notes = root.querySelectorAll('.oac-coords__note').map((n) => n.textContent);
    expect(notes).toEqual(['Pinned to the screen: its anchors are not a time and a price.', 'A freehand stroke has 10 points. Move it on the chart.']);
  });

  it('follows a drag while open, but keeps what is being typed', () => {
    const { w, doc } = make();
    const d = trend(w);
    const { row } = open(w, [d.id]);
    const first = row(d.id, 0);
    first.price.focus();
    first.price.value = '2400';
    // The drawing moves under the dialog: another row follows, the typed one stays.
    w.draw.update(d.id, { points: [{ time: bars[13].time, price: bars[13].low }, { time: bars[50].time, price: 2475 }] });
    expect(row(d.id, 1).price.value).toBe('2475.00');
    expect(first.price.value).toBe('2400');
    expect(doc.activeElement).toBe(first.price);
  });

  it('starts on the style tab and switches with the tab list', () => {
    const { w } = make();
    const d = trend(w);
    const dialog = mountDrawingProperties(w.context, undefined, { ids: [d.id] });
    const el = dialog.el as unknown as FakeElement;
    const tabs = el.querySelectorAll('[role="tab"]');
    expect(tabs.map((t) => t.dataset.tab)).toEqual(['style', 'coordinates']);
    expect((el.querySelector('.oac-props__anchors') as FakeElement).hidden).toBe(true);
    expect(el.querySelector('.oac-coords')).toBeNull();
    tabs[1].click();
    expect((el.querySelector('.oac-props__anchors') as FakeElement).hidden).toBe(false);
    expect(el.querySelector('.oac-coords')).not.toBeNull();
    fireKey(tabs[1], 'ArrowLeft');
    expect((el.querySelector('.oac-props__anchors') as FakeElement).hidden).toBe(true);
  });
});
