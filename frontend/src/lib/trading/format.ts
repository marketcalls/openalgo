/**
 * Tick-size + price formatting for the chart-trading terminal.
 *
 * All display uses toFixed (platform-independent) with decimals derived from the
 * instrument tick, plus manual Indian digit grouping — Intl 'en-IN' data and
 * minMove-based auto-precision both vary across OS/browser, which produced
 * different decimals on Windows vs macOS.
 */

/** The instrument tick, guarded against an implausibly coarse feed. */
export function tickSize(tick: number | undefined, refPrice: number): number {
  const t = Number(tick)
  if (!(t > 0)) return 0.05
  // A tick greater than ~1% of the price is impossible for a real instrument
  // (e.g. a ₹1 tick on a ₹23 stock, or a paise/rupee unit mismatch) and would
  // snap every order to a whole number — fall back to a valid 0.05.
  if (refPrice > 0 && t > refPrice * 0.01) return 0.05
  return t
}

/** Decimals implied by the tick (0.05→2, 0.01→2, 0.1→1, 1→0), computed numerically. */
export function tickDecimals(tick: number | undefined, refPrice: number): number {
  const t = tickSize(tick, refPrice)
  if (t >= 1) return 0
  let d = 0
  let v = t
  while (d < 8 && Math.abs(v - Math.round(v)) > 1e-9) {
    v *= 10
    d++
  }
  return d
}

/** Display decimals: tick-accurate, floored at 2 so every price shows ≥ 2 dp. */
export const priceDp = (tick: number | undefined, refPrice: number): number =>
  Math.max(2, tickDecimals(tick, refPrice))

/** Snap a price to the instrument tick. */
export function snapTick(price: number, tick: number | undefined, refPrice: number): number {
  const t = tickSize(tick, refPrice)
  return Number((Math.round(price / t) * t).toFixed(tickDecimals(tick, refPrice)))
}

/** Indian digit grouping (12,34,567) of an integer string. */
function groupIndian(intStr: string): string {
  if (intStr.length <= 3) return intStr
  return `${intStr.slice(0, -3).replace(/\B(?=(\d{2})+(?!\d))/g, ',')},${intStr.slice(-3)}`
}

/** Fixed-decimal price with Indian grouping — byte-identical on every platform. */
export function fmtPrice(n: number, tick: number | undefined, refPrice: number): string {
  const [ip, fp] = Number(n).toFixed(priceDp(tick, refPrice)).split('.')
  const neg = ip.startsWith('-')
  const grouped = groupIndian(neg ? ip.slice(1) : ip)
  return `${neg ? '-' : ''}${grouped}${fp ? `.${fp}` : ''}`
}

/** 2-decimal grouped rupee value (₹ P&L) — never rounds paise away to ₹0. */
export function money(n: number): string {
  const [ip, fp] = Math.abs(Number(n)).toFixed(2).split('.')
  return `${groupIndian(ip)}.${fp}`
}
