import { LONG_NAMES } from './status.js';

// /api/history returns bars only. Keep metadata explicit rather than inferring
// a venue or asset class from a ticker suffix.
const METADATA = {
  'RELIANCE.NS': { exchange: 'NSE', assetClass: 'Equity' },
  'BTC-USD': { assetClass: 'Crypto' },
};

const CATALOG = Object.entries(LONG_NAMES).map(([symbol, name]) => ({
  symbol, name, ...(METADATA[symbol] || {}),
}));

export function referenceSymbolSearch(query) {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return [];
  return CATALOG.filter(({ symbol, name }) =>
    symbol.toLowerCase().includes(needle) || name.toLowerCase().includes(needle));
}
