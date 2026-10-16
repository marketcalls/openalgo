/**
 * The floating toolbar over the selected drawings: where it appears, what it
 * offers, what it says when the selection disagrees, and that every change it
 * makes is one step back.
 */
import { afterEach, beforeAll, describe, expect, it } from 'vitest';
import type { Bar } from '../src/index';
import { createWidget, type Widget, type WidgetOptions } from '../src/widget/index';
import { valueAcross } from '../src/widget/drawing-toolbar';
import { chromeIconSvg, LINE_WIDTH_FIELD } from '../src/draw/index';
import {
  ensureWindowGlobal, fakeContainer, fakeWidgetDocument, fire, fireKey,
  type FakeDocument, type FakeElement,
} from './helpers/fake-dom-widget';

beforeAll(ensureWindowGlobal);

const T0 = 1700000100;
// A small random walk, so anchors sit on bars a trader would draw on.
const bars: Bar[] = (() => {
  let seed = 7;
  const next = (): number => { seed = (seed * 16807) % 2147483647; return seed / 2147483647 - 0.5; };
  let close = 1500;
  return Array.from({ length: 80 }, (_, i) => {
    const open = close;
    close = Math.round((open + next() * 12) * 20) / 20;
    return { time: T0 + i * 300, open, high: Math.max(open, close) + 3, low: Math.min(open, close) - 3, close, volume: 1000 + i };
  });
})();

interface Made { w: Widget; doc: FakeDocument; root: FakeElement }
const live: Widget[] = [];
afterEach(() => { for (const w of live.splice(0)) if (!w.isDestroyed) w.destroy(); });

function make(opts: WidgetOptions = {}): Made {
  const doc = fakeWidgetDocument();
  const container = fakeContainer(doc, 1000, 640);
  const w = createWidget(container as unknown as HTMLElement, {
    document: doc as unknown as Document, mobile: 'never', pixelRatio: () => 1,
    raf: { schedule: (cb: () => void) => { cb(); return 1; }, cancel: () => {} },
    ...opts,
  });
  w.chart.applySize(900, 560);
  w.series.setData(bars);
  live.push(w);
  return { w, doc, root: w.root as unknown as FakeElement };
}

const line = (w: Widget, style: Record<string, unknown> = {}, from = 20, to = 50) => w.draw.add({
  tool: 'trend-line', paneIndex: 0, style,
  points: [{ time: bars[from].time, price: bars[from].low }, { time: bars[to].time, price: bars[to].low }],
});
const bar = (root: FakeElement): FakeElement => root.querySelector('.oac-drawbar') as FakeElement;
const control = (root: FakeElement, name: string): FakeElement => root.querySelector(`[data-drawbar="${name}"]`) as FakeElement;
/** Hidden itself or through the wrapper it sits in (the colour swatch's). */
const hidden = (root: FakeElement, name: string): boolean => control(root, name).hidden || control(root, name).parentElement!.hidden;
const menuRow = (root: FakeElement, label: string): FakeElement => {
  const row = root.querySelectorAll('.oac-menu__row').find((r) => r.textContent.startsWith(label));
  if (row === undefined) throw new Error(`no menu row ${label}`);
  return row;
};

describe('drawing toolbar', () => {
  it('shows for a selection, after the chart in the tab order, and stands aside while placing or dragging', () => {
    const { w, root } = make();
    const chartEl = root.querySelector('.oac-chart') as FakeElement;
    const stage = chartEl.parentElement!;
    // Right after the chart, so Tab from the focused chart reaches it.
    expect(stage.children[stage.children.indexOf(chartEl) + 1]).toBe(bar(root));
    expect(bar(root).getAttribute('role')).toBe('toolbar');
    expect(bar(root).hidden).toBe(true);
    const d = line(w);
    w.draw.select(d.id);
    expect(bar(root).hidden).toBe(false);
    w.draw.setTool('rectangle');
    expect(bar(root).hidden).toBe(true);
    w.draw.setTool(null);
    expect(bar(root).hidden).toBe(false);
    w.chart.emit('draw:preview', { drawings: [] });
    expect(bar(root).hidden).toBe(true);
    w.chart.emit('draw:preview-clear', { ids: [d.id] });
    expect(bar(root).hidden).toBe(false);
    w.draw.select(null);
    expect(bar(root).hidden).toBe(true);
  });

  it('offers only what every selected tool declares', () => {
    const { w, root } = make();
    const d = line(w);
    w.draw.select(d.id);
    for (const name of ['color', 'width', 'style', 'lock', 'delete', 'more']) expect(hidden(root, name), name).toBe(false);
    // A note has a width and no line style; a callout has neither.
    const note = w.draw.add({ tool: 'note', paneIndex: 0, style: {}, text: { value: 'Breakout' }, points: [{ time: bars[30].time, price: bars[30].high }] });
    w.draw.select([d.id, note.id]);
    expect(hidden(root, 'style')).toBe(true);
    expect(hidden(root, 'width')).toBe(false);
    const callout = w.draw.add({ tool: 'callout', paneIndex: 0, style: {}, text: { value: 'Gap fill' },
      points: [{ time: bars[31].time, price: bars[31].high }, { time: bars[36].time, price: bars[36].high + 5 }] });
    w.draw.select([d.id, callout.id]);
    expect(hidden(root, 'style')).toBe(true);
    expect(hidden(root, 'width')).toBe(true);
    expect(hidden(root, 'color')).toBe(false);
    expect(hidden(root, 'lock')).toBe(false);
    // The text tool colours its words, not a stroke: no swatch.
    const text = w.draw.add({ tool: 'text', paneIndex: 0, style: {}, text: { value: 'Open' }, points: [{ time: bars[33].time, price: bars[33].high }] });
    w.draw.select([d.id, text.id]);
    expect(hidden(root, 'color')).toBe(true);
    expect(hidden(root, 'delete')).toBe(false);
  });

  it('says mixed when the selection disagrees, and one value when it agrees', () => {
    const { w, root } = make();
    const a = line(w, { color: '#f0a020', lineWidth: 2 });
    const b = line(w, { color: '#2a9df4', lineWidth: 3 }, 30, 60);
    w.draw.update(b.id, { locked: true });
    w.draw.select([a.id, b.id]);
    expect(control(root, 'color').getAttribute('aria-label')).toBe('Color: mixed');
    expect(control(root, 'color').parentElement!.classList.contains('is-mixed')).toBe(true);
    // The swatch shows both colours in use rather than the first one's.
    expect(control(root, 'color').style.backgroundImage).toContain('#f0a020');
    expect(control(root, 'color').style.backgroundImage).toContain('#2a9df4');
    expect(control(root, 'width').textContent).toBe('Mixed');
    expect(control(root, 'width').getAttribute('aria-label')).toBe('Line width: mixed');
    expect(control(root, 'lock').getAttribute('aria-pressed')).toBe('mixed');
    w.draw.select(a.id);
    expect(control(root, 'color').getAttribute('aria-label')).toBe('Color: #f0a020');
    expect(control(root, 'width').textContent).toBe('2 px');
    expect(control(root, 'lock').getAttribute('aria-pressed')).toBe('false');
    expect(valueAcross([w.draw.get(a.id)!, w.draw.get(b.id)!], LINE_WIDTH_FIELD, '#fff')).not.toBe(2);
  });

  it('pictures the line style with the registry glyph, mixed included, and beside each style in its menu', () => {
    const { w, root } = make();
    const glyph = (el: FakeElement | undefined): string | undefined => el?.querySelector('.oac-glyph')?.innerHTML;
    const a = line(w, { lineStyle: 'dashed' });
    const b = line(w, { lineStyle: 'solid' }, 30, 60);
    w.draw.select(a.id);
    expect(glyph(control(root, 'style'))).toBe(chromeIconSvg('line-dashed'));
    w.draw.select([a.id, b.id]);
    expect(glyph(control(root, 'style'))).toBe(chromeIconSvg('line-mixed'));
    control(root, 'style').click();
    expect(['Solid', 'Dashed', 'Dotted'].map((label) => glyph(menuRow(root, label))))
      .toEqual(['minus', 'line-dashed', 'line-dotted'].map((id) => chromeIconSvg(id)));
  });

  it('writes a width, a style, a colour and a lock to the whole selection as one step each', () => {
    const { w, root } = make();
    const a = line(w, { color: '#f0a020', lineWidth: 2 });
    const b = line(w, { color: '#2a9df4', lineWidth: 1 }, 30, 60);
    w.draw.select([a.id, b.id]);
    control(root, 'width').click();
    menuRow(root, '3 px').click();
    expect([w.draw.get(a.id)!.style.lineWidth, w.draw.get(b.id)!.style.lineWidth]).toEqual([3, 3]);
    control(root, 'style').click();
    menuRow(root, 'Dotted').click();
    expect([w.draw.get(a.id)!.style.lineStyle, w.draw.get(b.id)!.style.lineStyle]).toEqual(['dotted', 'dotted']);
    control(root, 'color').click();
    (root.querySelectorAll('.oac-color__choice').find((c) => c.getAttribute('aria-label') === '#ab79df') as FakeElement).click();
    expect([w.draw.get(a.id)!.style.color, w.draw.get(b.id)!.style.color]).toEqual(['#ab79df', '#ab79df']);
    control(root, 'lock').click();
    expect([w.draw.get(a.id)!.locked, w.draw.get(b.id)!.locked]).toEqual([true, true]);
    // Four clicks, four presses back, each restoring both drawings together.
    w.history.undo();
    expect([w.draw.get(a.id)!.locked, w.draw.get(b.id)!.locked]).toEqual([undefined, undefined]);
    w.history.undo();
    expect([w.draw.get(a.id)!.style.color, w.draw.get(b.id)!.style.color]).toEqual(['#f0a020', '#2a9df4']);
    w.history.undo();
    expect([w.draw.get(a.id)!.style.lineStyle, w.draw.get(b.id)!.style.lineStyle]).toEqual([undefined, undefined]);
    w.history.undo();
    expect([w.draw.get(a.id)!.style.lineWidth, w.draw.get(b.id)!.style.lineWidth]).toEqual([2, 1]);
  });

  it('deletes as one step and brings a stack order change back in one press', () => {
    const { w, root } = make();
    const a = line(w);
    const b = line(w, {}, 30, 60);
    const c = line(w, {}, 40, 70);
    w.draw.select([a.id, b.id]);
    control(root, 'more').click();
    menuRow(root, 'Bring to front').click();
    expect(w.draw.drawings().map((d) => d.id)).toEqual([c.id, a.id, b.id]);
    w.history.undo();
    expect(w.draw.drawings().map((d) => d.id)).toEqual([a.id, b.id, c.id]);
    w.draw.select([a.id, b.id]);
    control(root, 'delete').click();
    expect(w.draw.drawings().map((d) => d.id)).toEqual([c.id]);
    w.history.undo();
    expect(w.draw.drawings()).toHaveLength(3);
  });

  it('greys every edit on a read-only selection, with the reason', () => {
    const { w, root } = make();
    const d = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: { lineWidth: 2 }, policy: { editable: false },
      points: [{ time: bars[10].time, price: bars[10].low }, { time: bars[40].time, price: bars[40].low }] });
    w.draw.select(d.id);
    expect(bar(root).hidden).toBe(false);
    for (const name of ['color', 'width', 'style', 'lock', 'delete']) {
      expect((control(root, name) as unknown as { disabled: boolean }).disabled, name).toBe(true);
      expect(control(root, name).title, name).toContain('read-only');
    }
    // The more menu still opens: properties can be read, if not changed.
    expect((control(root, 'more') as unknown as { disabled: boolean }).disabled).toBe(false);
    control(root, 'delete').click();
    expect(w.draw.get(d.id)).toBeDefined();
  });

  it('walks its controls with the arrows instead of nudging the drawing, and Escape goes back to the chart', () => {
    const { w, doc, root } = make();
    const d = line(w);
    w.draw.select(d.id);
    const before = JSON.stringify(w.draw.get(d.id)!.points);
    control(root, 'color').focus();
    fireKey(control(root, 'color'), 'ArrowRight');
    expect(doc.activeElement).toBe(control(root, 'width'));
    fireKey(doc.activeElement, 'ArrowRight');
    expect(doc.activeElement).toBe(control(root, 'style'));
    fireKey(doc.activeElement, 'End');
    expect(doc.activeElement).toBe(control(root, 'more'));
    fireKey(doc.activeElement, 'ArrowRight');
    expect(doc.activeElement).toBe(control(root, 'color'));
    fireKey(doc.activeElement, 'ArrowLeft');
    expect(doc.activeElement).toBe(control(root, 'more'));
    // One tab stop: the control last used.
    expect(root.querySelectorAll('[data-drawbar]').filter((c) => c.tabIndex === 0)).toEqual([control(root, 'more')]);
    // Every arrow the chart reads as a nudge walks the bar instead, Shift or not.
    fireKey(doc.activeElement, 'ArrowDown');
    expect(doc.activeElement).toBe(control(root, 'color'));
    fireKey(doc.activeElement, 'ArrowUp');
    expect(doc.activeElement).toBe(control(root, 'more'));
    fireKey(doc.activeElement, 'ArrowRight', { shiftKey: true });
    fireKey(doc.activeElement, 'ArrowDown', { shiftKey: true });
    expect(doc.activeElement).toBe(control(root, 'width'));
    fireKey(doc.activeElement, 'ArrowUp', { shiftKey: true });
    fireKey(doc.activeElement, 'ArrowLeft', { shiftKey: true });
    fireKey(doc.activeElement, 'ArrowLeft');
    expect(doc.activeElement).toBe(control(root, 'delete'));
    expect(JSON.stringify(w.draw.get(d.id)!.points)).toBe(before);
    fireKey(doc.activeElement, 'Escape');
    expect(doc.activeElement).toBe(root.querySelector('.oac-chart'));
    expect(w.draw.selection()).toEqual([d.id]);
  });

  it('gives focus back to the chart when the selection goes while focus is in it', () => {
    const { w, doc, root } = make();
    const d = line(w);
    w.draw.select(d.id);
    control(root, 'delete').focus();
    control(root, 'delete').click();
    expect(bar(root).hidden).toBe(true);
    expect(doc.activeElement).toBe(root.querySelector('.oac-chart'));
  });

  it('sits above the selection, below it when the top has no room, and inside the chart', () => {
    const { w, root } = make();
    const chartEl = root.querySelector('.oac-chart') as FakeElement;
    const stage = chartEl.parentElement!;
    stage.rect = { left: 0, top: 40, width: 1000, height: 576 };
    chartEl.rect = { left: 42, top: 40, width: 900, height: 560 };
    bar(root).offsetWidth = 220;
    bar(root).offsetHeight = 36;
    const d = line(w);
    w.draw.select(d.id);
    const pts = w.draw.screenPoints(d.id)!;
    const top = Math.min(...pts.map((p) => p.y));
    const mid = (pts[0].x + pts[1].x) / 2;
    expect(parseFloat(bar(root).style.left as string)).toBeCloseTo(42 + mid - 110, 0);
    expect(parseFloat(bar(root).style.top as string)).toBeCloseTo(top - 10 - 36, 0);
    // A drawing at the top edge: the bar goes under it.
    const high = w.draw.add({ tool: 'horizontal-line', paneIndex: 0, style: {}, points: [{ time: bars[40].time, price: w.chart.coordinateToPrice(4)! }] });
    w.draw.select(high.id);
    const y = w.draw.screenPoints(high.id)![0].y;
    expect(parseFloat(bar(root).style.top as string)).toBeCloseTo(y + 10, 0);
    // Anchors far off to the right: clamped inside the chart.
    const far = line(w, {}, 70, 79);
    w.chart.setVisibleLogicalRange({ from: 0, to: 30 });
    w.draw.select(far.id);
    const left = parseFloat(bar(root).style.left as string);
    expect(left).toBeLessThanOrEqual(42 + 900 - 6 - 220);
    expect(left).toBeGreaterThanOrEqual(42 + 6);
  });

  it('follows a price scale that moves with no pan: an axis drag, and a tick that moves the autoscale', () => {
    const { w, root } = make();
    const chartEl = root.querySelector('.oac-chart') as FakeElement;
    const stage = chartEl.parentElement!;
    stage.rect = { left: 0, top: 40, width: 1000, height: 576 };
    chartEl.rect = { left: 42, top: 40, width: 900, height: 560 };
    bar(root).offsetWidth = 220;
    bar(root).offsetHeight = 36;
    const d = line(w);
    w.draw.select(d.id);
    const barTop = (): number => parseFloat(bar(root).style.top as string);
    const anchorTop = (): number => Math.min(...w.draw.screenPoints(d.id)!.map((p) => p.y));
    const scale = w.chart.panes()[0].priceScale;
    const range = scale.priceRange();
    expect(barTop()).toBeCloseTo(anchorTop() - 10 - 36, 0);
    // A press dragging the price axis sets the range directly; the chart says nothing.
    scale.setAutoScale(false);
    scale.setPriceRange({ min: range.min - 40, max: range.max + 40 });
    const moved = anchorTop();
    fire(chartEl, 'pointermove', { buttons: 1 });
    expect(barTop()).toBeCloseTo(moved - 10 - 36, 0);
    // A pointer only passing over the chart is not a rescale, and costs no layout.
    scale.setPriceRange({ min: range.min + 5, max: range.max + 5 });
    const stale = barTop();
    fire(chartEl, 'pointermove', { buttons: 0 });
    expect(barTop()).toBe(stale);
    // A tick: a new high widens the autoscale, and the drawing moves under the bar.
    scale.setAutoScale(true);
    const last = bars[bars.length - 1];
    const before = anchorTop();
    w.series.update({ ...last, high: last.high + 240, close: last.close + 180 });
    expect(Math.abs(anchorTop() - before)).toBeGreaterThan(20);
    expect(barTop()).toBeCloseTo(anchorTop() - 10 - 36, 0);
  });

  it('translates its words and can be turned off', () => {
    const { w, root } = make({ translate: (key, fallback) => (key === 'Drawing toolbar' ? 'Barre de dessin' : key === 'More drawing actions' ? 'Plus' : fallback) });
    line(w);
    expect(bar(root).getAttribute('aria-label')).toBe('Barre de dessin');
    expect(control(root, 'more').getAttribute('aria-label')).toBe('Plus');
    const off = make({ drawingToolbar: false });
    expect(off.root.querySelector('.oac-drawbar')).toBeNull();
    const railless = make({ rail: false });
    expect(railless.root.querySelector('.oac-drawbar')).toBeNull();
    const asked = make({ rail: false, drawingToolbar: true });
    expect(asked.root.querySelector('.oac-drawbar')).not.toBeNull();
  });

  it('names Delete by the chord in force, moved or unbound', () => {
    const { w, root } = make();
    const d = line(w);
    w.draw.select(d.id);
    expect(control(root, 'delete').title).toBe('Delete (Del)');
    w.context.keymap.rebind('delete', 'Shift+Delete');
    w.draw.select(null);
    w.draw.select(d.id);
    expect(control(root, 'delete').title).toBe('Delete (Shift+Del)');
    w.context.keymap.rebind('delete', null);
    w.draw.select(null);
    w.draw.select(d.id);
    expect(control(root, 'delete').title).toBe('Delete');
  });

  it('keeps one name on the lock and lets the pressed state say it is locked', () => {
    const { w, root } = make();
    const d = line(w);
    w.draw.update(d.id, { locked: true });
    w.draw.select(d.id);
    expect(control(root, 'lock').getAttribute('aria-label')).toBe('Lock');
    expect(control(root, 'lock').getAttribute('aria-pressed')).toBe('true');
    expect(control(root, 'lock').title).toBe('Lock');
    const fixed = w.draw.add({ tool: 'trend-line', paneIndex: 0, style: {}, locked: true, policy: { editable: false },
      points: [{ time: bars[10].time, price: bars[10].low }, { time: bars[40].time, price: bars[40].low }] });
    w.draw.select(fixed.id);
    expect(control(root, 'lock').getAttribute('aria-label')).toBe('Lock');
    expect(control(root, 'lock').title).toBe('Lock (read-only)');
  });

  it('marks action rows as plain menu items and only choices as radio items', () => {
    const { w, root } = make();
    w.draw.select(line(w).id);
    control(root, 'more').click();
    const rows = root.querySelectorAll('.oac-menu__row');
    expect(rows.length).toBeGreaterThan(3);
    for (const row of rows) {
      expect(row.getAttribute('role'), row.textContent).toBe('menuitem');
      expect(row.getAttribute('aria-checked'), row.textContent).toBeNull();
    }
    // The chord beside Duplicate is shown, not read into its name; the row says it as its shortcut.
    const duplicate = menuRow(root, 'Duplicate');
    expect(duplicate.querySelector('.oac-menu__key')!.getAttribute('aria-hidden')).toBe('true');
    expect(duplicate.getAttribute('aria-keyshortcuts')).toMatch(/^(Control|Meta)\+D$/);
    w.context.overlays.closeAll();
    control(root, 'width').click();
    const widths = root.querySelectorAll('.oac-menu__row');
    expect(widths.every((row) => row.getAttribute('role') === 'menuitemradio')).toBe(true);
    expect(widths.filter((row) => row.getAttribute('aria-checked') === 'true')).toHaveLength(1);
  });

  it('is gone with the widget', () => {
    const { w, root } = make();
    w.draw.select(line(w).id);
    w.destroy();
    expect(root.querySelector('.oac-drawbar')).toBeNull();
    fire(root, 'pointerdown');
  });
});
