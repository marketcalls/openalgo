/**
 * The market status and the clock as words: what the bottom bar, the status
 * line and the phone layout's sheet print from a session calendar.
 *
 * The status is read from the chart's own calendar
 * (`chart.dataLayer.sessionCalendar`), never from a clock rule of the
 * widget's: the calendar knows the venue's zone, its weekly hours, its closed
 * dates and its pre and post hours, and a guess from the wall clock knows none
 * of them. A calendar that cannot answer, such as one whose window a clock
 * change removes, reads as no status at all rather than stopping the chrome.
 */
import {
  formatZonedTime, formatZonedTimeSeconds, marketStatusAt, utcSecondsToZonedParts, zoneOffsetSeconds,
  type Chart, type MarketStatus, type SessionCalendarSource, type SessionPhase,
} from 'openalgo-charts';
import { widgetText, type WidgetTranslationOptions } from './localization';

/** The status as the chrome prints it. */
export interface MarketStatusReading {
  readonly phase: SessionPhase;
  /** The state: "Market open", "Pre-open", "Holiday". */
  readonly label: string;
  /** What comes next, on the chart's clock: "closes 15:30", "opens Mon 09:15". Empty when nothing is due within 14 days. */
  readonly detail: string;
}

/** The words a reading is built from, and the glyph each phase shows. */
const PHASE_LABELS: Readonly<Record<SessionPhase, string>> = {
  regular: 'Market open',
  pre: 'Pre-open',
  post: 'Post-close',
  extended: 'Extended hours',
  closed: 'Market closed',
  holiday: 'Holiday',
};

/** The chrome glyph for a phase, from the draw tier's icon set. */
export const PHASE_GLYPHS: Readonly<Record<SessionPhase, string>> = {
  regular: 'market-open',
  pre: 'market-pre',
  post: 'market-post',
  extended: 'market-post',
  closed: 'market-closed',
  holiday: 'market-holiday',
};

/** `UTC+5:30`, `UTC-4`, `UTC`: the offset a zone is at, at an instant, in the form a clock labels it. */
export function utcOffsetLabel(utcSeconds: number, zone: string): string {
  const offset = Math.round(zoneOffsetSeconds(utcSeconds, zone) / 60);
  if (offset === 0) return 'UTC';
  const minutes = Math.abs(offset);
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  return `UTC${offset < 0 ? '-' : '+'}${hours}${rest === 0 ? '' : ':' + String(rest).padStart(2, '0')}`;
}

/** The clock as the bar shows it: `14:32:05` on the chart's zone. */
export function clockText(utcSeconds: number, zone: string, seconds = true): string {
  return seconds ? formatZonedTimeSeconds(Math.floor(utcSeconds), zone) : formatZonedTime(Math.floor(utcSeconds), zone);
}

const weekdayFormats = new Map<string, Intl.DateTimeFormat>();

/** An instant as `15:30` on the same day as `nowSec`, else `Mon 09:15`, both on `zone`'s clock. */
function when(t: number, nowSec: number, zone: string, locale: string | undefined): string {
  const time = formatZonedTime(t, zone);
  const a = utcSecondsToZonedParts(t, zone);
  const b = utcSecondsToZonedParts(nowSec, zone);
  if (a.year === b.year && a.month === b.month && a.day === b.day) return time;
  const key = `${locale ?? ''}\u0000${zone}`;
  let format = weekdayFormats.get(key);
  if (format === undefined) {
    try { format = new Intl.DateTimeFormat(locale, { timeZone: zone, weekday: 'short' }); }
    catch { format = new Intl.DateTimeFormat(undefined, { timeZone: zone, weekday: 'short' }); }
    weekdayFormats.set(key, format);
  }
  return `${format.format(new Date(t * 1000))} ${time}`;
}

/** The status as words, the next change on the chart's clock. */
export function marketStatusReading(
  ctx: WidgetTranslationOptions & { readonly locale?: string | undefined },
  status: MarketStatus, nowSec: number, zone: string,
): MarketStatusReading {
  const phase = status.phase;
  const label = widgetText(ctx, `schema.ui.market.${phase}`, {}, PHASE_LABELS[phase]);
  const at = (t: number | null): string => (t === null ? '' : when(t, nowSec, zone, ctx.locale));
  let detail = '';
  if (phase === 'regular' && status.closesAt !== null) {
    detail = widgetText(ctx, 'schema.ui.market.closes', { time: at(status.closesAt) }, 'closes {time}');
  } else if ((phase === 'post' || phase === 'extended') && status.changesAt !== null) {
    detail = widgetText(ctx, 'schema.ui.market.until', { time: at(status.changesAt) }, 'until {time}');
  } else if (phase !== 'regular' && status.opensAt !== null) {
    detail = widgetText(ctx, 'schema.ui.market.opens', { time: at(status.opensAt) }, 'opens {time}');
  }
  return { phase, label, detail };
}

/**
 * A market status held until it can change. Laying a calendar's dates out
 * costs a good deal more than reading a clock, and a readout asks every
 * second, so the status is worked out again only when the calendar is
 * replaced, when its next change comes, or once a day for one that holds.
 */
export class MarketStatusHold {
  private _calendar: SessionCalendarSource | null | undefined = undefined;
  private _status: MarketStatus | null = null;
  private _from = Infinity;
  private _until = -Infinity;

  /** The status at `nowSec` from `calendar`, or null without one that lays out phases, or one that fails to. */
  public read(calendar: SessionCalendarSource | null, nowSec: number): MarketStatus | null {
    if (calendar !== this._calendar || nowSec < this._from || nowSec >= this._until) {
      this._calendar = calendar;
      this._from = nowSec;
      try { this._status = marketStatusAt(calendar, nowSec); } catch { this._status = null; }
      this._until = this._status?.changesAt ?? nowSec + 86400;
    }
    return this._status;
  }

  /** When the held status next needs reading again, in UTC seconds. */
  public until(): number { return this._until; }
}

/** Whether the chart's switches let a readout show the session state (the settings dialog's "Session state"). */
export function sessionStateShown(chart: Chart): boolean {
  return chart.statusLineOptions().marketStatus !== false;
}
