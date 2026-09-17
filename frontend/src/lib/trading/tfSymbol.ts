/**
 * TradeFinder's name for a stock, mapped to the one the broker's master uses.
 *
 * After a corporate action TradeFinder keeps trading under the old name while
 * the symbol master moves to the new one, so a ranked-list symbol can be one no
 * history or option-chain call will answer for. On 17-Sep-2026 that silently
 * emptied the strikes section for TATAMOTORS -- the day's number one -- because
 * the master lists it as TMPV under the same ISIN.
 *
 * The Python side keeps the same table in services/tf_symbol_alias.py. Two
 * copies, one per language, is the floor; a third would be a bug waiting.
 */
const ALIASES: Record<string, string> = {
  TATAMOTORS: 'TMPV',
}

/** The name to ask the broker for. Unknown symbols pass through unchanged. */
export function tradableSymbol(symbol: string): string {
  return ALIASES[symbol] ?? symbol
}
