// Shared symbol-search response type, used by the symbol search endpoint
// and by features that surface broker-symbol metadata (e.g. chartink
// configuration). Lives here independently of strategy/v2 because the
// type itself is not strategy-specific — it's the OpenAlgo unified
// representation of a broker instrument lookup result.

export interface SymbolSearchResult {
  symbol: string
  brsymbol: string
  name: string
  exchange: string
  token: string
  lotsize: number
}
