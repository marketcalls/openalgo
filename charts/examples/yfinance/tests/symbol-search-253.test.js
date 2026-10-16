import { describe, expect, it } from 'vitest';
import { referenceSymbolSearch } from '../src/symbol-search.js';

describe('reference symbol catalog', () => {
  it('returns a named instrument with its explicit venue and asset class', () => {
    expect(referenceSymbolSearch('reliance')).toEqual([{
      symbol: 'RELIANCE.NS', name: 'Reliance Industries Limited', exchange: 'NSE', assetClass: 'Equity',
    }]);
  });

  it('leaves unavailable exchange metadata absent and filters by description', () => {
    expect(referenceSymbolSearch('bitcoin')).toEqual([{
      symbol: 'BTC-USD', name: 'Bitcoin / US Dollar', assetClass: 'Crypto',
    }]);
    expect(referenceSymbolSearch('not-listed')).toEqual([]);
  });
});
