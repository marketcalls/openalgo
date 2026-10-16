/** Source shown in runnable examples and evaluated alongside the chart library. */
export const STOCK_BARS_SOURCE = `function stockBars(startTime, count, intervalSec, startPrice, seed, volatility = 0.004, baseVolume = 2000) {
  let state = seed >>> 0 || 1;
  const random = () => {
    state ^= state << 13; state >>>= 0;
    state ^= state >>> 17;
    state ^= state << 5; state >>>= 0;
    return state / 4294967296;
  };
  const round = value => Math.round(value * 100) / 100;
  const bars = [];
  const trends = [0.5, -0.35, 0.2, 0.85, -0.7, 0.15, -0.4];
  let close = round(startPrice);
  let regimeEnd = 0;
  let trend = 0;
  for (let i = 0; i < count; i++) {
    if (i >= regimeEnd) {
      trend = trends[Math.floor(random() * trends.length)] * volatility;
      regimeEnd = i + 14 + Math.floor(random() * 18);
    }
    const gap = i > 0 && i % 37 === 0 ? (random() - 0.5) * volatility * 6 : 0;
    const open = round(Math.max(0.01, close * (1 + gap)));
    const noise = (random() + random() + random() - 1.5) * volatility * 2;
    const move = trend + noise;
    close = round(Math.max(0.01, open * (1 + move)));
    const upperWick = Math.max(0.01, round(open * volatility * (0.12 + random() * 0.7)));
    const lowerWick = Math.max(0.01, round(open * volatility * (0.12 + random() * 0.7)));
    const volume = Math.round(baseVolume * (0.65 + random() * 0.8
      + Math.abs(move) / volatility * 0.18 + (i % 31 === 0 ? 1.5 : 0)));
    bars.push({ time: startTime + i * intervalSec, open,
      high: round(Math.max(open, close) + upperWick),
      low: round(Math.max(0.01, Math.min(open, close) - lowerWick)),
      close, volume });
  }
  return bars;
}`;

export interface StockBar { time: number; open: number; high: number; low: number; close: number; volume: number }

/**
 * The same generator for a component that builds its chart directly. It is
 * made from the source string above, so a runnable example's data and a
 * component's data come from one definition and cannot drift apart.
 */
export const stockBars = new Function(`${STOCK_BARS_SOURCE}\nreturn stockBars;`)() as (
  startTime: number, count: number, intervalSec: number, startPrice: number, seed: number,
  volatility?: number, baseVolume?: number,
) => StockBar[];
