export function riskError(
  action: 'BUY' | 'SELL',
  entry: number | null,
  stoploss?: number,
  target?: number,
  trailing?: number
): string | null {
  if (
    [stoploss, target, trailing].some((v) => v !== undefined && (!Number.isFinite(v) || v <= 0))
  ) {
    return 'Risk prices and trailing distance must be positive numbers.'
  }
  if (stoploss === undefined && target === undefined) return null
  if (!entry || !Number.isFinite(entry) || entry <= 0)
    return 'A current entry price is required to validate risk levels.'
  if (stoploss !== undefined && (action === 'BUY' ? stoploss >= entry : stoploss <= entry)) {
    return `Stop loss must be ${action === 'BUY' ? 'below' : 'above'} the entry price.`
  }
  if (target !== undefined && (action === 'BUY' ? target <= entry : target >= entry)) {
    return `Target must be ${action === 'BUY' ? 'above' : 'below'} the entry price.`
  }
  return null
}
