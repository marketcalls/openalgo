/**
 * A time as the chart's clock reads it, and back. Every field that asks for a
 * date and a time (the go-to panel, a drawing's anchors, an alert's expiry,
 * the chart data export's bounds) reads the chart's timezone rather than the
 * browser's: the axis the user compares the reading with is labelled in that
 * zone, so a time typed in any other would land hours away from the candle
 * meant. One reader, so every field refuses the same malformed input; each
 * keeps its own policy (a blank time, a skipped one) through the options.
 */
import { utcSecondsToZonedParts, zonedWallClockToUtcSeconds } from 'openalgo-charts';

/** A date and a time as the fields show them: `YYYY-MM-DD` and `HH:MM`, or `HH:MM:SS` when `seconds`. */
interface WallClock {
  date: string;
  time: string;
  seconds: boolean;
}

/** How a field reads what the user typed. */
interface WallClockReading {
  /**
   * A blank time reads as the start of the day, or as its last second, for a
   * field that allows one; without it a blank time does not read.
   */
  blank?: 'start' | 'end';
  /** A time written to the minute reads as that minute's last second, for an inclusive upper bound. */
  end?: boolean;
  /** Refuse a wall time a spring-forward skipped, rather than read the reading it maps to. */
  rejectSkipped?: boolean;
}

const DATE = /^(\d{4})-(\d{2})-(\d{2})$/;
const TIME = /^(\d{2}):(\d{2})(?::(\d{2}))?$/;
const pad = (n: number): string => String(n).padStart(2, '0');

/** `time` on `zone`'s clock as the fields show it; seconds when asked, or by default when it has any. */
export function formatWallClock(time: number, zone: string, seconds?: boolean): WallClock {
  const p = utcSecondsToZonedParts(time, zone);
  const withSeconds = seconds ?? p.second !== 0;
  return {
    date: `${p.year}-${pad(p.month)}-${pad(p.day)}`,
    time: `${pad(p.hour)}:${pad(p.minute)}${withSeconds ? `:${pad(p.second)}` : ''}`,
    seconds: withSeconds,
  };
}

/**
 * UTC seconds for a typed date and time on `zone`'s clock, or null when they
 * do not read: a malformed field, a field out of range, or a calendar date
 * that does not exist (the 31st of a 30-day month), which the calendar maths
 * would otherwise roll into the next month.
 */
export function parseWallClock(date: string, time: string, zone: string, opts: WallClockReading = {}): number | null {
  const d = DATE.exec(date.trim());
  const text = time.trim();
  const t = TIME.exec(text);
  if (d === null || (t === null && (text !== '' || opts.blank === undefined))) return null;
  const [year, month, day] = [Number(d[1]), Number(d[2]), Number(d[3])];
  const probe = new Date(Date.UTC(year, month - 1, day));
  if (probe.getUTCMonth() !== month - 1 || probe.getUTCDate() !== day) return null;
  if (t === null) {
    const out = opts.blank === 'end'
      ? zonedWallClockToUtcSeconds(year, month, day + 1, 0, 0, 0, zone) - 1
      : zonedWallClockToUtcSeconds(year, month, day, 0, 0, 0, zone);
    return Number.isFinite(out) ? out : null;
  }
  const [hour, minute] = [Number(t[1]), Number(t[2])];
  const second = t[3] !== undefined ? Number(t[3]) : opts.end === true ? 59 : 0;
  if (hour > 23 || minute > 59 || second > 59) return null;
  const out = zonedWallClockToUtcSeconds(year, month, day, hour, minute, second, zone);
  if (!Number.isFinite(out)) return null;
  if (opts.rejectSkipped === true) {
    // A skipped reading maps to another one; reading it back shows which.
    const back = formatWallClock(out, zone, true);
    if (back.date !== `${d[1]}-${d[2]}-${d[3]}` || back.time !== `${pad(hour)}:${pad(minute)}:${pad(second)}`) return null;
  }
  return out;
}
