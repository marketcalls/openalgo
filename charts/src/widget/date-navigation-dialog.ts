/**
 * The go-to panel: a date, or a range of two, typed on the chart's own clock
 * and handed to a `DateNavigator` (through `navigate`) as UTC seconds.
 *
 * The fields read the chart's timezone rather than the browser's, for the
 * reason the alert expiry does: the axis the user reads is labelled in that
 * zone, so a date typed in any other would land hours away from the candle
 * they meant. A result that is not a clean placement keeps the panel open
 * with the reason, since the next thing the user does is change the date.
 * Bars a day or longer are named by their date alone, so their panel has no
 * time fields: a time could not change which bar a date names. Both choices
 * hold for one interval and one zone, so a change to either closes the panel.
 */
import type { WidgetContext } from './context';
import { timeBuckets, type DateNavigationResult, type DateNavigationTarget } from './date-navigator';
import { button, dialogFrame, el, openPanel, type PanelHandle } from './form';
import { widgetText, type WidgetTranslationOptions } from './localization';
import { token as v } from './tokens';
import { formatWallClock, parseWallClock } from './wall-clock';

export interface DateNavigationDialogOptions {
  /** Run one request. The panel reports the result and closes once it is placed. */
  navigate(target: DateNavigationTarget): Promise<DateNavigationResult>;
  /**
   * Abandon the panel's request. Called when the panel closes while that
   * request is still loading (dismissed, or closed by an interval or timezone
   * change), so the view cannot jump after the user has moved on; not called
   * when the panel closed because its chart was destroyed.
   */
  cancel?(): void;
  /**
   * A request already under way that this panel shows and reports as its own,
   * for a host whose history load rebuilds the chart and so closes the panel
   * that started it. A closed panel reports nothing.
   */
  pending?: { target: DateNavigationTarget; result: Promise<DateNavigationResult> };
  onClose?(): void;
}

let sequence = 0;

/**
 * The words for what a request came to when it fell short: history that
 * stops, a range wider than the chart, an interval with no dates, a failed
 * load. The go-to panel and the bottom bar's ranges both say these, so they
 * say them the same way; each keeps its own words for a clean placement and
 * for no data. Null for any other status.
 */
export function describeNavigation(ctx: WidgetTranslationOptions, result: DateNavigationResult, span: { from: string; to: string }): string | null {
  switch (result.status) {
    case 'partial':
      if (result.clipped) return widgetText(ctx, 'The range is wider than the chart. Showing {from} to {to}', span);
      if (result.history === 'exhausted') return widgetText(ctx, 'History starts at {date}', { date: span.from });
      if (result.history === 'limited') return widgetText(ctx, 'The history limit stops at {date}', { date: span.from });
      if (result.history === 'empty') return widgetText(ctx, 'No older bars were found before {date}', { date: span.from });
      return widgetText(ctx, 'Older history cannot load now. Showing from {date}', { date: span.from });
    case 'unsupported': return widgetText(ctx, 'Go to needs a time-based interval');
    case 'error': return widgetText(ctx, 'Could not load history: {error}', { error: result.error?.message ?? '' });
    default: return null;
  }
}

/** Open the go-to panel below `anchor`, prefilled with the visible window or the pending request. */
export function openDateNavigation(ctx: WidgetContext, anchor: HTMLElement | undefined, options: DateNavigationDialogOptions): PanelHandle {
  const doc = ctx.document;
  const chart = ctx.chart;
  const zone = chart.timezone();
  const interval = ctx.interval();
  const buckets = timeBuckets(interval);
  const intraday = buckets?.mode === 'interval' && buckets.seconds < 86400;
  const format = new Intl.DateTimeFormat(ctx.locale, { timeZone: zone, dateStyle: 'medium', ...(intraday ? { timeStyle: 'short' } : {}) });
  const when = (time: number): string => format.format(new Date(time * 1000));
  let range = false;
  let closed = false;
  let busy = false;
  let request = 0;
  let panel: PanelHandle | null = null;
  const id = `oac-goto-${++sequence}`;

  const frame = dialogFrame(doc, { translate: ctx.translate, title: widgetText(ctx, 'Go to'), className: 'oac-goto', onClose: close });
  const modes = el(doc, 'div', 'oac-goto__modes');
  modes.setAttribute('role', 'group');
  modes.setAttribute('aria-label', widgetText(ctx, 'Go to'));
  const mode = (name: 'date' | 'range', label: string): HTMLButtonElement => {
    const b = button(doc, { label, onClick: () => setRange(name === 'range') });
    b.dataset.mode = name;
    modes.appendChild(b);
    return b;
  };
  const dateMode = mode('date', widgetText(ctx, 'Date'));
  const rangeMode = mode('range', widgetText(ctx, 'Range'));

  const row = (key: string): { row: HTMLElement; label: HTMLLabelElement; date: HTMLInputElement; time: HTMLInputElement } => {
    const line = el(doc, 'div', 'oac-goto__row');
    const label = el(doc, 'label', 'oac-goto__label');
    label.htmlFor = `${id}-${key}`;
    const date = el(doc, 'input');
    date.type = 'date';
    date.id = `${id}-${key}`;
    const time = el(doc, 'input');
    time.type = 'time';
    time.hidden = !intraday;
    line.append(label, date, time);
    return { row: line, label, date, time };
  };
  const start = row('from');
  const end = row('to');
  if (!intraday) frame.el.classList.add('oac-goto--days');
  const hint = el(doc, 'p', 'oac-goto__hint', intraday
    ? widgetText(ctx, 'Times are in {zone}. A blank time is the start of the day, or its end for To.', { zone })
    : widgetText(ctx, 'Dates are in {zone}.', { zone }));
  const message = el(doc, 'p', 'oac-goto__message');
  message.setAttribute('role', 'status');
  message.setAttribute('aria-live', 'polite');
  frame.body.append(modes, start.row, end.row, hint, message);
  const go = button(doc, { label: widgetText(ctx, 'Go'), variant: 'primary', onClick: () => { void commit(); } });
  go.dataset.action = 'go-to';
  frame.actions.appendChild(go);
  for (const input of [start.date, start.time, end.date, end.time]) {
    input.addEventListener('keydown', event => {
      if ((event as KeyboardEvent).key !== 'Enter') return;
      event.preventDefault();
      void commit();
    });
    input.addEventListener('input', () => { message.textContent = ''; });
  }

  // Prefill with the window in view, so a small correction is a small edit.
  const view = chart.getVisibleLogicalRange();
  const shown = [chart.dataLayer.indexToTime(Math.max(0, Math.ceil(view.from))),
    chart.dataLayer.indexToTime(Math.min(chart.dataLayer.length - 1, Math.floor(view.to)))];
  const fill = (fields: { date: HTMLInputElement; time: HTMLInputElement }, time: number | undefined): void => {
    if (time === undefined) return;
    const wall = formatWallClock(time, zone, false);
    fields.date.value = wall.date;
    fields.time.value = intraday ? wall.time : '';
  };
  const pending = options.pending;
  fill(start, pending?.target.from ?? shown[0]);
  fill(end, pending === undefined ? shown[1] : pending.target.to ?? pending.target.from);

  function setRange(on: boolean): void {
    range = on;
    end.row.hidden = !on;
    start.label.textContent = on ? widgetText(ctx, 'From') : widgetText(ctx, 'Date');
    end.label.textContent = widgetText(ctx, 'To');
    start.time.setAttribute('aria-label', on ? widgetText(ctx, 'From time') : widgetText(ctx, 'Time'));
    end.time.setAttribute('aria-label', widgetText(ctx, 'To time'));
    dateMode.setAttribute('aria-pressed', String(!on));
    rangeMode.setAttribute('aria-pressed', String(on));
    message.textContent = '';
  }
  setRange(pending?.target.to !== undefined);

  /** UTC seconds for a typed date and time, or null. A blank end time means the last second of that day. */
  function read(fields: { date: HTMLInputElement; time: HTMLInputElement }, closing: boolean): number | null {
    return parseWallClock(fields.date.value, fields.time.value, zone, closing ? { blank: 'end', end: true } : { blank: 'start' });
  }

  function describe(result: DateNavigationResult, target: DateNavigationTarget): string {
    const span = { from: when(result.from ?? target.from), to: when(result.to ?? target.to ?? target.from) };
    switch (result.status) {
      case 'placed': return range ? widgetText(ctx, 'Showing {from} to {to}', span) : widgetText(ctx, 'Showing {date}', { date: span.from });
      case 'no-data': return target.to === undefined
        ? widgetText(ctx, 'No bars at or after {date}', { date: when(target.from) })
        : widgetText(ctx, 'No bars between {from} and {to}', { from: when(target.from), to: when(target.to) });
      case 'invalid': return widgetText(ctx, 'Enter a valid date');
      default: return describeNavigation(ctx, result, span) ?? '';
    }
  }

  async function commit(): Promise<void> {
    if (closed) return;
    const from = read(start, false);
    const to = range ? read(end, true) : undefined;
    if (from === null || to === null) { message.textContent = widgetText(ctx, 'Enter a valid date'); return; }
    if (to !== undefined && to < from) { message.textContent = widgetText(ctx, 'The end must not be before the start'); return; }
    const target: DateNavigationTarget = to === undefined ? { from } : { from, to };
    await follow(target, options.navigate(target));
  }

  async function follow(target: DateNavigationTarget, work: Promise<DateNavigationResult>): Promise<void> {
    const mine = ++request;
    message.textContent = widgetText(ctx, 'Loading history');
    go.disabled = busy = true;
    let result: DateNavigationResult;
    try { result = await work; } finally { if (mine === request) go.disabled = busy = false; }
    if (closed || mine !== request) return;
    // Taken over by a context change or a move of the view: no longer loading.
    if (result.status === 'cancelled') { message.textContent = ''; return; }
    const text = describe(result, target);
    const failed = result.status === 'error' || result.status === 'unsupported';
    ctx.status(text, failed ? 'error' : 'info');
    if (result.status === 'placed') close();
    else message.textContent = text;
  }

  function close(): void {
    if (closed) return;
    closed = true;
    for (const off of offs) off();
    panel?.close();
    options.onClose?.();
    // Decided once the closing task has run: a host rebuilding its chart
    // closes the panel just before destroying that chart, and the request is
    // then the host's to finish rather than one the user walked away from.
    if (busy) void Promise.resolve().then(() => { if (!chart.isDestroyed) options.cancel?.(); });
  }
  const offs = [chart.on('destroy', close), chart.on('timezone:changed', close),
    chart.on('data:context', () => { if (ctx.interval() !== interval) close(); })];
  panel = openPanel(ctx, frame.el, { anchor, placement: 'below', initialFocus: start.date }, close);
  if (closed) panel.close();
  else if (pending !== undefined) void follow(pending.target, pending.result);
  return { el: frame.el, close, isOpen: () => !closed && panel!.isOpen() };
}


/** Styles for the go-to panel; part of the widget component sheet. */
export const DATE_NAVIGATION_CSS = `
.oac-widget .oac-goto { width: 340px; }
.oac-widget .oac-goto__modes { display: flex; gap: 4px; margin-bottom: 10px; }
.oac-widget .oac-goto__row { display: grid; grid-template-columns: 44px minmax(0, 1fr) 96px; align-items: center; gap: 6px; margin: 0 0 6px; }
.oac-widget .oac-goto--days .oac-goto__row { grid-template-columns: 44px minmax(0, 1fr); }
.oac-widget .oac-goto__label { color: ${v('mut')}; font-size: 12px; }
.oac-widget .oac-goto input[type=date], .oac-widget .oac-goto input[type=time] { min-width: 0; height: ${v('ctl-h')}; padding: 0 6px;
  border: 1px solid ${v('bd')}; border-radius: ${v('radius')}; background: ${v('elev')}; color: ${v('tx')}; color-scheme: inherit; }
.oac-widget .oac-goto__hint { margin: 4px 0 0; color: ${v('faint')}; font-size: 11px; line-height: 1.4; }
.oac-widget .oac-goto__message { min-height: 16px; margin: 6px 0 0; color: ${v('mut')}; font-size: 12px; overflow-wrap: anywhere; }
`;
