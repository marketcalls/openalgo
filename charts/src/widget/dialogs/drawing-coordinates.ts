/**
 * The coordinates tab of the drawing properties: every anchor of the
 * selected drawings as a date, a time and a price, typed exactly rather than
 * dragged close.
 *
 * Times are read and written on the chart's own clock (`chart.timezone()`),
 * the one its time axis is labelled in, so a time typed here lands on the
 * candle the user reads it from. A price shows at the pane's precision when
 * it sits on that grid, and in full when it does not, so opening the tab and
 * leaving it never moves an anchor by rounding it.
 *
 * An anchor is committed on Enter, or when the focus leaves its row, after
 * the whole row validates: one row is one `update`, so one undo step, and
 * the tool's own constraint still applies (a horizontal line keeps its other
 * anchor level). Not on `change`: a date or time field reports one for every
 * segment typed, so typing a year would write 0002, 0020 and 0202 on the way
 * to 2026, each its own step. A field that does not validate says why and
 * writes nothing. A drawing pinned to the screen has no time or price, and a
 * freehand stroke has a point per sample, so neither lists its anchors.
 */
import type { Drawing, DrawingPoint } from 'openalgo-charts/draw';
import { drawingToolOf, editableIds, type WidgetContext } from '../context';
import { el } from '../form';
import { widgetText } from '../localization';
import { formatWallClock, parseWallClock } from '../wall-clock';
import { MIN_PRICE_DIGITS } from '../statusline';

export interface DrawingCoordinatesHandle {
  readonly el: HTMLElement;
  /** Read the drawings again; a row being edited keeps what is typed in it. */
  refresh(): void;
  destroy(): void;
}

/** A typed price: digits with an optional sign and decimal point; thousands separators and spaces are ignored. */
export function parseTypedPrice(text: string): number | null {
  const clean = text.trim().replace(/[\s,]/g, '');
  if (!/^[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[-+]?\d+)?$/i.test(clean)) return null;
  const value = Number(clean);
  return Number.isFinite(value) ? value : null;
}

/** A price as the field shows it: at `digits` when that is exact, else in full, never in exponent form. */
export function formatAnchorPrice(price: number, digits: number): string {
  const fixed = price.toFixed(Math.max(0, Math.min(10, digits)));
  if (Number(fixed) === price) return fixed;
  return String(Number(price.toFixed(10)));
}

interface Row {
  el: HTMLElement;
  date: HTMLInputElement;
  time: HTMLInputElement;
  price: HTMLInputElement;
  error: HTMLElement;
  /** What the fields were filled with, so an untouched field keeps its exact value. */
  shown: { date: string; time: string; price: string };
}

let sequence = 0;

/**
 * Render the anchors of `ids()` into `host`. `why` is the reason the
 * selection cannot be edited, or null; with one, every field is read-only.
 */
export function mountDrawingCoordinates(
  ctx: WidgetContext, host: HTMLElement, ids: () => readonly string[], why: () => string | null,
): DrawingCoordinatesHandle {
  const { chart, draw } = ctx;
  const doc = ctx.document;
  const root = el(doc, 'div', 'oac-coords');
  host.appendChild(root);
  const rows = new Map<string, Row>();
  let zone = chart.timezone();
  let destroyed = false;

  // The axis may print whole numbers on a wide range; a price typed here is a
  // price, so it gets the status line's two decimals at least.
  const digitsOf = (d: Drawing): number => {
    const p = chart.panes()[d.paneIndex]?.priceScale.precision();
    return Math.max(MIN_PRICE_DIGITS, p !== undefined && Number.isFinite(p) ? Math.round(p) : 0);
  };
  const logarithmic = (d: Drawing): boolean => chart.panes()[d.paneIndex]?.priceScale.options.mode === 'logarithmic';

  function fill(row: Row, d: Drawing, point: DrawingPoint): void {
    const wall = formatWallClock(point.time, zone);
    const price = formatAnchorPrice(point.price, digitsOf(d));
    row.date.value = wall.date;
    row.time.step = wall.seconds ? '1' : '60';
    row.time.value = wall.time;
    row.price.value = price;
    row.shown = { date: wall.date, time: wall.time, price };
    row.error.hidden = true;
    row.error.textContent = '';
    for (const input of [row.date, row.time, row.price]) input.removeAttribute('aria-invalid');
  }

  function fail(row: Row, input: HTMLInputElement, message: string): void {
    row.error.textContent = message;
    row.error.hidden = false;
    input.setAttribute('aria-invalid', 'true');
  }

  /** Validate a row and write it as one step. Nothing is written for a field left as it was shown. */
  function commit(id: string, index: number, row: Row): void {
    const d = draw.get(id);
    const point = d?.points[index];
    if (destroyed || d === undefined || point === undefined || why() !== null) return;
    for (const input of [row.date, row.time, row.price]) input.removeAttribute('aria-invalid');
    row.error.hidden = true;
    let time = point.time;
    if (row.date.value !== row.shown.date || row.time.value !== row.shown.time) {
      const typed = parseWallClock(row.date.value, row.time.value, zone);
      if (typed === null) {
        // The field to fix: the date when it names no day, else the time.
        const dateReads = parseWallClock(row.date.value, '00:00', zone) !== null;
        fail(row, dateReads ? row.time : row.date, widgetText(ctx, 'Enter a date and a time on the chart clock'));
        return;
      }
      time = typed;
    }
    let price = point.price;
    if (row.price.value !== row.shown.price) {
      const typed = parseTypedPrice(row.price.value);
      if (typed === null) { fail(row, row.price, widgetText(ctx, 'Enter a price as a number')); return; }
      if (typed <= 0 && logarithmic(d)) { fail(row, row.price, widgetText(ctx, 'A logarithmic scale needs a price above zero')); return; }
      price = typed;
    }
    if (time === point.time && price === point.price) return;
    const points = d.points.map((p, i) => (i === index ? { ...p, time, price } : { ...p }));
    draw.update(id, { points });
    // A refresh passes over the row being typed in; this one is done, so it
    // shows where the anchor landed, in the field's own format.
    const now = draw.get(id);
    const landed = now?.points[index];
    if (now !== undefined && landed !== undefined) fill(row, now, landed);
  }

  function makeRow(id: string, index: number): Row {
    const line = el(doc, 'div', 'oac-coords__row');
    line.dataset.anchor = `${id}:${index}`;
    const key = `oac-coords-${++sequence}`;
    const label = el(doc, 'label', 'oac-coords__label', widgetText(ctx, 'Point {number}', { number: index + 1 }));
    label.htmlFor = `${key}-date`;
    const date = el(doc, 'input', 'oac-coords__date');
    date.type = 'date';
    date.id = `${key}-date`;
    const time = el(doc, 'input', 'oac-coords__time');
    time.type = 'time';
    const price = el(doc, 'input', 'oac-coords__price');
    price.type = 'text';
    price.setAttribute('inputmode', 'decimal');
    price.setAttribute('spellcheck', 'false');
    price.autocomplete = 'off';
    const error = el(doc, 'p', 'oac-input-error');
    error.setAttribute('role', 'alert');
    error.hidden = true;
    const row: Row = { el: line, date, time, price, error, shown: { date: '', time: '', price: '' } };
    const name = (field: string): string => widgetText(ctx, '{field} of point {number}', { field, number: index + 1 });
    date.setAttribute('aria-label', name(widgetText(ctx, 'Date')));
    time.setAttribute('aria-label', name(widgetText(ctx, 'Time')));
    price.setAttribute('aria-label', name(widgetText(ctx, 'Price')));
    for (const input of [date, time, price]) {
      input.addEventListener('keydown', (event) => {
        if ((event as KeyboardEvent).key !== 'Enter') return;
        event.preventDefault();
        commit(id, index, row);
      });
    }
    // Moving between the fields of one row is still typing it.
    line.addEventListener('focusout', (event) => {
      const next = (event as FocusEvent).relatedTarget as Node | null;
      if (next !== null && line.contains(next)) return;
      commit(id, index, row);
    });
    const fields = el(doc, 'div', 'oac-coords__fields');
    fields.append(date, time, price);
    line.append(label, fields, error);
    return row;
  }

  function note(text: string): void {
    root.appendChild(el(doc, 'p', 'oac-coords__note', text));
  }

  /** What the tab lists: the drawings, their anchor counts and spaces. A change rebuilds it; anything else fills it in place. */
  let layout = '';

  function render(): void {
    if (destroyed) return;
    const focused = doc.activeElement as HTMLElement | null;
    const inside = focused !== null && root.contains(focused);
    const editing = inside ? (focused.closest('[data-anchor]') as HTMLElement | null)?.dataset.anchor : undefined;
    zone = chart.timezone();
    const locked = why();
    const drawings = ids().map((id) => draw.get(id)).filter((d): d is Drawing => d !== undefined);
    const shape = JSON.stringify([zone, drawings.map((d) => [d.id, d.tool, d.space ?? 'data', d.points.length])]);
    const rebuild = shape !== layout;
    layout = shape;
    const wanted = new Set<string>();
    if (rebuild) {
      root.replaceChildren();
      const head = el(doc, 'div', 'oac-coords__head');
      head.append(
        el(doc, 'span', '', widgetText(ctx, 'Date')),
        el(doc, 'span', '', widgetText(ctx, 'Time')),
        el(doc, 'span', '', widgetText(ctx, 'Price')),
      );
      root.append(head, el(doc, 'p', 'oac-coords__zone', widgetText(ctx, 'Times are on the chart clock, {zone}.', { zone })));
    }
    for (const d of drawings) {
      // An unregistered tool still has its anchors.
      const tool = drawingToolOf(d.tool);
      if (rebuild && drawings.length > 1) root.appendChild(el(doc, 'div', 'oac-head', widgetText(ctx, `schema.drawing.${d.tool}.name`, {}, tool?.name ?? d.tool)));
      if (d.space === 'viewport') { if (rebuild) note(widgetText(ctx, 'Pinned to the screen: its anchors are not a time and a price.')); continue; }
      if (tool?.freehand === true) { if (rebuild) note(widgetText(ctx, 'A freehand stroke has {count} points. Move it on the chart.', { count: d.points.length })); continue; }
      const readOnly = locked !== null || editableIds(draw, [d.id]).length === 0;
      d.points.forEach((point, index) => {
        const key = `${d.id}:${index}`;
        wanted.add(key);
        let row = rows.get(key);
        if (row === undefined) { row = makeRow(d.id, index); rows.set(key, row); }
        // The row being typed in keeps its text; every other one follows the model.
        if (key !== editing) fill(row, d, point);
        for (const input of [row.date, row.time, row.price]) {
          input.disabled = readOnly;
          input.title = readOnly ? (locked ?? widgetText(ctx, 'read-only')) : '';
        }
        if (rebuild) root.appendChild(row.el);
      });
    }
    for (const key of [...rows.keys()]) if (!wanted.has(key)) rows.delete(key);
    // A rebuild detached the field being typed in; put the caret back in the same one.
    if (inside && !root.contains(focused) && editing !== undefined) {
      const row = rows.get(editing);
      const same = row === undefined ? undefined : [row.date, row.time, row.price].find((input) => input.className === focused.className);
      same?.focus();
    }
  }

  const offs = [chart.on('timezone:changed', render)];
  render();
  return {
    el: root,
    refresh: render,
    destroy: () => {
      if (destroyed) return;
      destroyed = true;
      for (const off of offs) off();
      rows.clear();
      root.remove();
    },
  };
}

export const DRAWING_COORDINATES_CSS = `
.oac-widget .oac-coords { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.oac-widget .oac-coords__head, .oac-widget .oac-coords__fields { display: grid; grid-template-columns: minmax(0, 1.3fr) minmax(0, 1fr) minmax(0, 1fr); align-items: center; gap: 6px; }
.oac-widget .oac-coords__head { order: -1; color: var(--oac-faint); font-size: 10px; font-weight: 600; text-transform: uppercase; letter-spacing: .5px; padding: 2px 0 0; }
.oac-widget .oac-coords__zone { margin: 0 0 4px; color: var(--oac-faint); font-size: 11px; }
.oac-widget .oac-coords__row { display: flex; flex-direction: column; gap: 3px; }
.oac-widget .oac-coords__label { color: var(--oac-mut); font-size: 11px; }
.oac-widget .oac-coords input { min-width: 0; width: 100%; height: var(--oac-ctl-h); padding: 0 6px; border: 1px solid var(--oac-bd);
  border-radius: var(--oac-radius); background: var(--oac-elev); color: var(--oac-tx); color-scheme: inherit; font-variant-numeric: tabular-nums; }
.oac-widget .oac-coords input:disabled { opacity: .6; cursor: not-allowed; }
.oac-widget .oac-coords .oac-input-error { margin: 0; }
.oac-widget .oac-coords__note { margin: 4px 0; color: var(--oac-mut); font-size: 12px; overflow-wrap: anywhere; }
`;
