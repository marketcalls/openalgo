import type {
  ChargeBreakdown,
  ChargeSegment,
  ChargeSettings,
  CostReport,
  Estimate,
  EstimateRequest,
} from '@/api/sandbox-charges'

/**
 * One segment as the server sends it.
 *
 * `rates` is written main exchange first, the way the rate card is. The
 * server sends that order as the `exchanges` list, and sends the rates
 * themselves as an object whose keys it sorts, so BSE comes before NSE there.
 * This builds both the same way. A fixture that kept the rates in the order
 * they were typed let every calculator test pass while the real page opened
 * each card on BSE.
 */
function segment(
  key: string,
  label: string,
  group: string,
  flat: string,
  percent: string,
  rates: Record<string, string>,
  statutory: Partial<ChargeSegment['statutory']> = {}
): ChargeSegment {
  const exchanges = Object.keys(rates)
  const sorted = Object.fromEntries(Object.entries(rates).sort(([a], [b]) => a.localeCompare(b)))
  return {
    key,
    label,
    group,
    applies_to: `${label} orders`,
    flat,
    percent,
    default_flat: flat,
    default_percent: percent,
    exchanges: exchanges.length > 0 ? exchanges : ['CRYPTO'],
    statutory: {
      stt_label: 'STT',
      stt_buy: '0',
      stt_sell: '0',
      stamp_buy: '0.003',
      sebi: '0.0001',
      gst: '18',
      exchange_txn: sorted,
      ...statutory,
    },
  }
}

const NO_LEVIES = { stt_label: '', stamp_buy: '0', sebi: '0', gst: '0' }

/**
 * The plan as the server sends it to a browser on an Indian broker, on a fresh
 * install: the eight Indian segments and no crypto.
 */
export function chargeSettings(overrides: Partial<ChargeSettings> = {}): ChargeSettings {
  return {
    enabled: true,
    market: 'indian',
    limits: { flat_max: '1000', percent_max: '5' },
    statutory_as_of: '2026-11-23',
    segments: [
      segment(
        'equity_delivery',
        'Equity Delivery',
        'Equity',
        '20',
        '2.5',
        { NSE: '0.00307', BSE: '0.00375' },
        { stt_buy: '0.1', stt_sell: '0.1', stamp_buy: '0.015' }
      ),
      segment(
        'equity_intraday',
        'Equity Intraday',
        'Equity',
        '20',
        '0.1',
        { NSE: '0.00307', BSE: '0.00375' },
        { stt_sell: '0.025' }
      ),
      segment(
        'fno_futures',
        'F&O Futures',
        'Equity F&O',
        '20',
        '0.03',
        { NFO: '0.00183', BFO: '0' },
        { stt_sell: '0.05', stamp_buy: '0.002' }
      ),
      segment(
        'fno_options',
        'F&O Options',
        'Equity F&O',
        '20',
        '0',
        { NFO: '0.03553', BFO: '0.0325' },
        { stt_sell: '0.15' }
      ),
      segment('currency_futures', 'Currency Futures', 'Currency', '20', '0.03', {
        CDS: '0.0004',
        BCD: '0.00045',
      }),
      segment('currency_options', 'Currency Options', 'Currency', '20', '0', {
        CDS: '0.0331',
        BCD: '0.001',
      }),
      segment(
        'commodity_futures',
        'Commodity Futures',
        'Commodity',
        '20',
        '0.03',
        { MCX: '0.0021', NCDEX: '0.0021', NCO: '0.0001' },
        { stt_label: 'CTT', stt_sell: '0.01' }
      ),
      segment(
        'commodity_options',
        'Commodity Options',
        'Commodity',
        '20',
        '0',
        { MCX: '0.0418', NCDEX: '0.0418', NCO: '0.001' },
        { stt_label: 'CTT', stt_sell: '0.05' }
      ),
    ],
    ...overrides,
  }
}

/**
 * The plan as the server sends it to a browser on a crypto venue: the two
 * crypto segments and nothing of the Indian rate card.
 */
export function cryptoSettings(overrides: Partial<ChargeSettings> = {}): ChargeSettings {
  return {
    enabled: true,
    market: 'crypto',
    limits: { flat_max: '1000', percent_max: '5' },
    statutory_as_of: '2026-11-23',
    segments: [
      segment('crypto_futures', 'Crypto Futures and Spot', 'Crypto', '0', '0', {}, NO_LEVIES),
      segment('crypto_options', 'Crypto Options', 'Crypto', '0', '0', {}, NO_LEVIES),
    ],
    ...overrides,
  }
}

export function breakdown(overrides: Partial<ChargeBreakdown> = {}): ChargeBreakdown {
  return {
    brokerage: 0,
    stt: 0,
    exchange_charges: 0,
    sebi_charges: 0,
    stamp_duty: 0,
    gst: 0,
    total_charges: 0,
    ...overrides,
  }
}

/** A priced round trip. The total is 200.62 unless a test says otherwise. */
export function estimateFor(request: EstimateRequest, total = 200.62): Estimate {
  const quantity = Number(request.quantity)
  const turnover = (Number(request.buy_price) + Number(request.sell_price)) * quantity
  const gross = (Number(request.sell_price) - Number(request.buy_price)) * quantity
  return {
    segment: request.segment,
    exchange: request.exchange,
    brokerage_plan: '',
    stt_label: request.segment.startsWith('commodity') ? 'CTT' : 'STT',
    turnover,
    total: breakdown({
      brokerage: 40,
      stt: 110,
      exchange_charges: 25.79,
      sebi_charges: 0.84,
      stamp_duty: 12,
      gst: 11.99,
      total_charges: total,
    }),
    gross_pnl: gross,
    net_pnl: gross - total,
    points_to_breakeven: 0.5,
  }
}

export function costReport(overrides: Partial<CostReport> = {}): CostReport {
  const buy = breakdown({
    brokerage: 20,
    stt: 125,
    exchange_charges: 3.84,
    sebi_charges: 0.13,
    stamp_duty: 19,
    gst: 4.31,
    total_charges: 172.28,
  })
  const sell = breakdown({
    brokerage: 20,
    stt: 130,
    exchange_charges: 3.99,
    sebi_charges: 0.13,
    gst: 4.34,
    total_charges: 158.46,
  })
  const totals = {
    trades: 2,
    turnover: 255000,
    brokerage: 40,
    stt: 255,
    exchange_charges: 7.83,
    sebi_charges: 0.26,
    stamp_duty: 19,
    gst: 8.65,
    total_charges: 330.74,
  }
  const trade = {
    orderid: '1',
    symbol: 'RELIANCE',
    exchange: 'NSE',
    product: 'CNC',
    quantity: 50,
    segment: 'equity_delivery',
    segment_label: 'Equity Delivery',
    strategy: '',
  }
  return {
    from: '2026-10-25',
    to: '2026-11-23',
    totals,
    by_segment: [{ ...totals, segment: 'equity_delivery', label: 'Equity Delivery' }],
    by_day: [{ ...totals, date: '2026-11-23' }],
    trades: [
      {
        ...trade,
        ...sell,
        tradeid: 'TRADE-2',
        timestamp: '2026-11-23 10:05:00',
        action: 'SELL',
        price: 2600,
        turnover: 130000,
      },
      {
        ...trade,
        ...buy,
        tradeid: 'TRADE-1',
        timestamp: '2026-11-23 09:30:00',
        action: 'BUY',
        price: 2500,
        turnover: 125000,
      },
    ],
    trades_listed: 2,
    trades_total: 2,
    ...overrides,
  }
}
