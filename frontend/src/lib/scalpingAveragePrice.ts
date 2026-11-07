/**
 * The open position a scalping chart marks with its average-price line.
 *
 * A symbol can be held under more than one product (MIS and NRML), so the
 * product the terminal is trading wins; any other open product is the
 * fallback. Quantities and prices may arrive as strings.
 */
export interface AveragePricePosition {
  symbol: string
  exchange: string
  product?: string
  quantity: number | string
  average_price: number | string
}

export interface OpenAverage {
  price: number
  quantity: number
}

export function openAveragePrice(
  positions: readonly AveragePricePosition[],
  symbol: string,
  exchange: string,
  product?: string
): OpenAverage | null {
  const open = positions
    .filter((p) => p.symbol === symbol && p.exchange === exchange)
    .map((p) => ({
      product: (p.product || '').toUpperCase(),
      quantity: Number(p.quantity) || 0,
      price: Number(p.average_price) || 0,
    }))
    .filter((p) => p.quantity !== 0 && p.price > 0)
  const chosen = open.find((p) => p.product === (product || '').toUpperCase()) ?? open[0]
  return chosen ? { price: chosen.price, quantity: chosen.quantity } : null
}
