import type { CandlestickData, LineData, Time, UTCTimestamp } from 'lightweight-charts'

function normalizeEpochSeconds(value: number): number {
  if (!Number.isFinite(value)) return 0
  return value > 10_000_000_000 ? Math.floor(value / 1000) : Math.floor(value)
}

export function toChartTime(value: number | string | Date): UTCTimestamp {
  if (typeof value === 'number') {
    return normalizeEpochSeconds(value) as UTCTimestamp
  }

  if (value instanceof Date) {
    return Math.floor(value.getTime() / 1000) as UTCTimestamp
  }

  const numeric = Number(value)
  if (Number.isFinite(numeric)) {
    return normalizeEpochSeconds(numeric) as UTCTimestamp
  }

  return Math.floor(new Date(value).getTime() / 1000) as UTCTimestamp
}

export function toCandlestickData<
  T extends { time: number | string | Date; open: number; high: number; low: number; close: number },
>(candles: T[]): CandlestickData<Time>[] {
  return candles.map((candle) => ({
    time: toChartTime(candle.time),
    open: candle.open,
    high: candle.high,
    low: candle.low,
    close: candle.close,
  }))
}

export function toLineData<T extends { time: number | string | Date; value: number }>(
  points: T[],
): LineData<Time>[] {
  return points.map((point) => ({
    time: toChartTime(point.time),
    value: point.value,
  }))
}
