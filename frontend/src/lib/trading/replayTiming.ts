import {
  isValidTimezone,
  nextBucketStart,
  type ReplayTiming,
  tryResolveInterval,
  utcSecondsToZonedParts,
  zonedWallClockToUtcSeconds,
} from 'openalgo-charts'

/** Declared interval availability, not an inferred exchange trading calendar. */
function closeTime(interval: string, timeZone: string): ReplayTiming['barEndTime'] {
  const code = interval.trim()
  const month = /^(\d*)M$/.exec(code) ?? /^(\d+)mo$/.exec(code)
  const week = /^(\d+)wk$/.exec(code)
  const resolved = tryResolveInterval(code) ?? (week ? tryResolveInterval(`${week[1]}w`) : null)
  const rule = resolved
    ? { ...resolved.bucketing }
    : month
      ? { mode: 'calendar' as const, unit: 'month' as const, count: Number(month[1] || 1) }
      : null
  if (!rule) throw new Error('The selected interval has no replay close time')
  if (rule.mode === 'ticks' || rule.mode === 'volume') {
    throw new Error('Replay needs time-based candles with known close times')
  }
  if (
    (rule.mode === 'interval' && (!Number.isFinite(rule.seconds) || rule.seconds <= 0)) ||
    (rule.mode === 'calendar' && (!Number.isSafeInteger(rule.count ?? 1) || (rule.count ?? 1) <= 0))
  ) {
    throw new Error('The selected interval has no valid replay close time')
  }
  const calendarToken = /^(\d*)\s*([dw])$/i.exec(week ? `${week[1]}w` : code)
  const days = calendarToken
    ? Number(calendarToken[1] || 1) * (calendarToken[2].toLowerCase() === 'w' ? 7 : 1)
    : 0

  return (bar) => {
    if (!Number.isFinite(bar.time)) throw new Error('A replay candle has an invalid time')
    let end: number | null
    if (rule.mode === 'calendar') {
      end = nextBucketStart(rule, bar.time, timeZone)
    } else if (days > 0 && rule.seconds === days * 86400) {
      // Daily and weekly bars keep their local opening time across DST changes.
      const parts = utcSecondsToZonedParts(bar.time, timeZone)
      const next = new Date(Date.UTC(parts.year, parts.month - 1, parts.day + days))
      end = zonedWallClockToUtcSeconds(
        next.getUTCFullYear(),
        next.getUTCMonth() + 1,
        next.getUTCDate(),
        parts.hour,
        parts.minute,
        parts.second,
        timeZone
      )
    } else {
      end = bar.time + rule.seconds
    }
    if (end === null || !Number.isFinite(end) || end <= bar.time) {
      throw new Error('A replay candle has no valid close time')
    }
    return end
  }
}

/** All returned times are UTC seconds; finer candles need their own availability. */
export function replayTiming(
  interval: string,
  timeZone: string,
  finerInterval?: string
): ReplayTiming {
  if (!isValidTimezone(timeZone)) throw new Error('The replay timezone is unavailable')
  return {
    barEndTime: closeTime(interval, timeZone),
    ...(finerInterval === undefined ? {} : { subBarEndTime: closeTime(finerInterval, timeZone) }),
  }
}
