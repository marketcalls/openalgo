import { barCloseSec, utcSecondsToZonedParts, zonedWallClockToUtcSeconds } from '/dist/openalgo-charts.mjs';
import './intervals.js';

/** Calendar dates use the captured chart zone, including short and long days. */
export function replayBarEndTime(interval, timezone) {
  return bar => {
    if (interval === '1d' || interval === '1wk') {
      const p = utcSecondsToZonedParts(bar.time, timezone);
      const next = new Date(Date.UTC(p.year, p.month - 1, p.day + (interval === '1wk' ? 7 : 1)));
      return zonedWallClockToUtcSeconds(next.getUTCFullYear(), next.getUTCMonth() + 1, next.getUTCDate(),
        p.hour, p.minute, p.second, timezone);
    }
    const end = barCloseSec(interval, bar.time, timezone);
    if (!Number.isFinite(end)) throw new Error('The chart interval has no replay close time');
    return end;
  };
}
