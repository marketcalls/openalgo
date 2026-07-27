/**
 * Per-exchange price precision for the scalping terminal.
 *
 * Currency derivatives (NSE CDS, BSE BCD) quote to 4 decimals — e.g. USDINR
 * 94.4625 with a 0.0025 tick — while equity/index/commodity F&O quote to 2.
 * The tickers, charts, position book, and SL dialog all derive their decimal
 * places from this so a CDS price is never truncated to 94.46.
 */
export function priceDecimals(exchange?: string | null): number {
  const e = (exchange || '').toUpperCase()
  return e === 'CDS' || e === 'BCD' ? 4 : 2
}
