import { useMemo } from 'react'
import { useBrokerStore } from '@/stores/brokerStore'

/** Exchange option for dropdowns */
export interface ExchangeOption {
  value: string
  label: string
}

/** Default underlyings per F&O exchange */
const UNDERLYINGS: Record<string, string[]> = {
  NFO: ['NIFTY', 'BANKNIFTY', 'FINNIFTY', 'MIDCPNIFTY'],
  BFO: ['SENSEX', 'BANKEX'],
  MCX: ['GOLDM', 'CRUDEOIL', 'SILVERM', 'NATURALGAS', 'COPPER'],
  CDS: ['USDINR', 'EURINR', 'GBPINR', 'JPYINR'],
  CRYPTO: ['BTC', 'ETH', 'SOL', 'BNB', 'XRP'],
}

/** Index exchanges excluded from trading/FNO lists */
const INDEX_EXCHANGES = new Set([
  'NSE_INDEX',
  'BSE_INDEX',
  'MCX_INDEX',
  'CDS_INDEX',
  'GLOBAL_INDEX',
])

/** F&O exchange codes (intersected with each broker's reported capabilities below). */
const FNO_CODES = new Set(['NFO', 'BFO', 'MCX', 'CDS', 'BCD', 'NCO', 'NCDEX', 'CRYPTO'])

/** Fallback exchanges when capabilities haven't loaded yet (backward compatible) */
const FALLBACK_EXCHANGES = ['NSE', 'BSE', 'NFO', 'BFO', 'CDS', 'MCX', 'CRYPTO']

/**
 * Central hook for broker-aware exchange filtering.
 *
 * All pages should use this instead of hardcoding exchange arrays.
 * Reads from brokerStore (populated at login via /api/broker/capabilities).
 *
 * Returns categorized exchange lists so each page picks what it needs:
 * - Tools pages → fnoExchanges, defaultFnoExchange, defaultUnderlyings
 * - TradingView/GoCharting → tradingExchanges, defaultExchange
 * - Historify → allExchanges
 * - Search → tradingExchanges
 */
export function useSupportedExchanges() {
  const capabilities = useBrokerStore((s) => s.capabilities)

  return useMemo(() => {
    // Use fallback exchanges when capabilities haven't loaded yet (backward compatible)
    const supported = capabilities?.supported_exchanges ?? FALLBACK_EXCHANGES
    const isCrypto = capabilities?.broker_type === 'crypto'

    // All exchanges from plugin.json
    const allExchanges: ExchangeOption[] = supported.map((e) => ({ value: e, label: e }))

    // Trading exchanges: exclude _INDEX suffixed exchanges
    const tradingExchanges: ExchangeOption[] = supported
      .filter((e) => !INDEX_EXCHANGES.has(e))
      .map((e) => ({ value: e, label: e }))

    // F&O exchanges (only those the broker reports as supported).
    const fnoExchanges: ExchangeOption[] = supported
      .filter((e) => FNO_CODES.has(e))
      .map((e) => ({ value: e, label: e }))

    // Exchanges shown by general /tools pages (Option Chain, OI Tracker,
    // Straddle Chart, Custom Straddle etc.). Strategy Builder uses its own
    // broader derivative list below.
    //
    // MCX is now included: commodity options have no tradable spot, and the
    // backend resolves the near-month future as the pricing reference instead,
    // so chains, quotes and expiries all work. CDS, BCD and NCDEX remain out of
    // the general tools until those routes implement their venue-specific flows.
    const toolsFnoExchanges: ExchangeOption[] = fnoExchanges.filter(
      (e) => !['CDS', 'BCD', 'NCDEX'].includes(e.value)
    )
    const strategyBuilderExchanges: ExchangeOption[] = fnoExchanges.filter(
      (e) => e.value !== 'CDS'
    )

    // Defaults
    const defaultExchange = tradingExchanges[0]?.value ?? (isCrypto ? 'CRYPTO' : 'NSE')
    const defaultFnoExchange = fnoExchanges[0]?.value ?? (isCrypto ? 'CRYPTO' : 'NFO')
    const defaultToolsFnoExchange = toolsFnoExchanges[0]?.value ?? (isCrypto ? 'CRYPTO' : 'NFO')
    const defaultStrategyBuilderExchange =
      strategyBuilderExchanges[0]?.value ?? (isCrypto ? 'CRYPTO' : 'NFO')

    // Underlyings filtered to only supported FNO exchanges
    const defaultUnderlyings: Record<string, string[]> = {}
    for (const ex of fnoExchanges) {
      if (UNDERLYINGS[ex.value]) {
        defaultUnderlyings[ex.value] = UNDERLYINGS[ex.value]
      }
    }

    return {
      /** All exchanges from plugin.json (including _INDEX) */
      allExchanges,
      /** Trading exchanges (no _INDEX) — for TradingView, GoCharting, Search */
      tradingExchanges,
      /** Broker-reported F&O exchanges, including commodity/currency derivatives. */
      fnoExchanges,
      /**
       * F&O exchanges shown in general /tools pages. Strategy Builder uses
       * `strategyBuilderExchanges` because it supports BCD and NCDEX too.
       */
      toolsFnoExchanges,
      /** Broker-reported derivative venues supported specifically by Strategy Builder. */
      strategyBuilderExchanges,
      /** First trading exchange */
      defaultExchange,
      /** First F&O exchange */
      defaultFnoExchange,
      /** First tools-supported F&O exchange */
      defaultToolsFnoExchange,
      /** First Strategy Builder-supported derivative exchange. */
      defaultStrategyBuilderExchange,
      /** Underlyings map filtered to supported F&O exchanges */
      defaultUnderlyings,
      /** Quick check: is this a crypto broker? */
      isCrypto,
    }
  }, [capabilities])
}
