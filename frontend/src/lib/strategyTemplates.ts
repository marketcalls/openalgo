/**
 * Strategy templates used by the Strategy Builder's template grid.
 *
 * Each template produces a list of legs with strikes expressed relative to ATM
 * (in "strike steps" — the strike interval in the option chain, e.g. 50 for
 * NIFTY, 100 for BANKNIFTY). The Strategy Builder resolves these offsets
 * against the nearest available strikes in the live option chain when the user
 * picks a template.
 */

import type { OptionType, Side } from './strategyMath'

export type Direction = 'BULLISH' | 'BEARISH' | 'NON_DIRECTIONAL'

export interface TemplateLeg {
  side: Side
  optionType: OptionType
  /** Offset in strike-steps from ATM. 0 = ATM, -1 = one strike ITM for calls, etc. */
  strikeOffset: number
  lots: number
  /**
   * Offset in expiries from the "near" expiry selected in the header.
   * 0 (default) = near expiry. 1 = next expiry in the list (farther out).
   * Used for calendar / diagonal spreads.
   */
  expiryOffset?: number
}

export interface StrategyTemplate {
  id: string
  name: string
  direction: Direction
  description: string
  legs: TemplateLeg[]
  /** Normalised viewBox-(0,0)-(100,40) SVG path for the mini payoff icon. */
  payoffPath: string
}

/**
 * Icons are drawn so that:
 *   x = 0 .. 100 represents the underlying range,
 *   y = 0 (top, max profit) .. 40 (bottom, max loss),
 *   the zero line sits at y = 20.
 */
export const STRATEGY_TEMPLATES: StrategyTemplate[] = [
  // ──────────────────────────────────────────────────────────────────────
  // BULLISH (9)
  // ──────────────────────────────────────────────────────────────────────
  {
    id: 'long_call',
    name: 'Long Call',
    direction: 'BULLISH',
    description: 'Unlimited upside, limited downside. Best for strong bullish view.',
    legs: [{ side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 }],
    payoffPath: 'M0,30 L55,30 L100,2',
  },
  {
    id: 'short_put',
    name: 'Short Put',
    direction: 'BULLISH',
    description: 'Collect premium; profit if price stays above strike.',
    legs: [{ side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 }],
    payoffPath: 'M0,38 L50,10 L100,10',
  },
  {
    id: 'bull_call_spread',
    name: 'Bull Call Spread',
    direction: 'BULLISH',
    description: 'Buy ATM call, sell OTM call. Capped profit & loss.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,28 L50,28 L75,6 L100,6',
  },
  {
    id: 'bull_put_spread',
    name: 'Bull Put Spread',
    direction: 'BULLISH',
    description: 'Sell ATM put, buy OTM put. Net credit trade.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
    ],
    payoffPath: 'M0,34 L25,34 L50,10 L100,10',
  },
  {
    id: 'call_ratio_back_spread',
    name: 'Call Ratio Back Spread',
    direction: 'BULLISH',
    description:
      'Sell 1 ATM call, buy 2 OTM calls. Small credit; unlimited upside if market rallies hard.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 2 },
    ],
    payoffPath: 'M0,18 L40,18 L60,28 L75,22 L100,2',
  },
  {
    id: 'long_synthetic',
    name: 'Long Synthetic',
    direction: 'BULLISH',
    description:
      'Buy ATM call + sell ATM put (same strike). Synthetic long futures — unlimited upside, unlimited downside.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
    payoffPath: 'M0,38 L100,2',
  },
  {
    id: 'range_forward',
    name: 'Range Forward',
    direction: 'BULLISH',
    description:
      'Sell OTM put + buy OTM call. Bullish collar-style structure — limited downside via short put, unlimited upside via long call.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,38 L30,22 L65,22 L100,2',
  },
  {
    id: 'bullish_butterfly',
    name: 'Bullish Butterfly',
    direction: 'BULLISH',
    description:
      'Call butterfly centred above spot — buy 1 ATM CE, sell 2 OTM CE, buy 1 further OTM CE. Max profit if spot rallies to the body strike.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 2 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
    payoffPath: 'M0,26 L55,26 L70,4 L85,26 L100,26',
  },
  {
    id: 'bullish_condor',
    name: 'Bullish Condor',
    direction: 'BULLISH',
    description:
      'Call condor above spot — profit zone sits over a range of higher strikes. Defined risk on both ends.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 1, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 3, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
    payoffPath: 'M0,26 L45,26 L60,6 L80,6 L92,26 L100,26',
  },

  // ──────────────────────────────────────────────────────────────────────
  // BEARISH (9)
  // ──────────────────────────────────────────────────────────────────────
  {
    id: 'short_call',
    name: 'Short Call',
    direction: 'BEARISH',
    description: 'Collect premium; profit if price stays below strike.',
    legs: [{ side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 }],
    payoffPath: 'M0,10 L50,10 L100,38',
  },
  {
    id: 'long_put',
    name: 'Long Put',
    direction: 'BEARISH',
    description: 'Unlimited downside profit, limited loss. Best for strong bearish view.',
    legs: [{ side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 }],
    payoffPath: 'M0,2 L45,30 L100,30',
  },
  {
    id: 'bear_call_spread',
    name: 'Bear Call Spread',
    direction: 'BEARISH',
    description: 'Sell ATM call, buy OTM call. Net credit trade.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,10 L50,10 L75,34 L100,34',
  },
  {
    id: 'bear_put_spread',
    name: 'Bear Put Spread',
    direction: 'BEARISH',
    description: 'Buy ATM put, sell OTM put. Capped profit & loss.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
    ],
    payoffPath: 'M0,6 L25,6 L50,28 L100,28',
  },
  {
    id: 'put_ratio_back_spread',
    name: 'Put Ratio Back Spread',
    direction: 'BEARISH',
    description:
      'Sell 1 ATM put, buy 2 OTM puts. Small credit; unlimited downside if market falls hard.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 2 },
    ],
    payoffPath: 'M0,2 L25,22 L40,28 L60,18 L100,18',
  },
  {
    id: 'short_synthetic',
    name: 'Short Synthetic',
    direction: 'BEARISH',
    description:
      'Sell ATM call + buy ATM put (same strike). Synthetic short futures — unlimited downside profit, unlimited upside loss.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
    payoffPath: 'M0,2 L100,38',
  },
  {
    id: 'risk_reversal',
    name: 'Risk Reversal',
    direction: 'BEARISH',
    description:
      'Buy OTM put + sell OTM call. Bearish collar — profits on downside, unlimited upside loss.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,2 L35,22 L70,22 L100,38',
  },
  {
    id: 'bearish_butterfly',
    name: 'Bearish Butterfly',
    direction: 'BEARISH',
    description:
      'Put butterfly centred below spot — buy 1 ATM PE, sell 2 OTM PE, buy 1 further OTM PE. Max profit if spot falls to the body strike.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 2 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
    ],
    payoffPath: 'M0,26 L15,26 L30,4 L45,26 L100,26',
  },
  {
    id: 'bearish_condor',
    name: 'Bearish Condor',
    direction: 'BEARISH',
    description:
      'Put condor below spot — profit zone sits over a range of lower strikes. Defined risk on both ends.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -1, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -3, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
    ],
    payoffPath: 'M0,26 L8,26 L20,6 L40,6 L55,26 L100,26',
  },

  // ──────────────────────────────────────────────────────────────────────
  // NON-DIRECTIONAL (20)
  // ──────────────────────────────────────────────────────────────────────
  {
    id: 'long_straddle',
    name: 'Long Straddle',
    direction: 'NON_DIRECTIONAL',
    description: 'Buy ATM call + put. Profits from a large move either way.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
    payoffPath: 'M0,4 L50,30 L100,4',
  },
  {
    id: 'short_straddle',
    name: 'Short Straddle',
    direction: 'NON_DIRECTIONAL',
    description: 'Sell ATM call + put. Profits if price stays pinned near strike.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
    ],
    payoffPath: 'M0,36 L50,10 L100,36',
  },
  {
    id: 'long_strangle',
    name: 'Long Strangle',
    direction: 'NON_DIRECTIONAL',
    description: 'Buy OTM call + OTM put. Cheaper than straddle; needs bigger move.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,6 L30,26 L70,26 L100,6',
  },
  {
    id: 'short_strangle',
    name: 'Short Strangle',
    direction: 'NON_DIRECTIONAL',
    description: 'Sell OTM call + OTM put. Wider profit zone than short straddle.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,34 L30,14 L70,14 L100,34',
  },
  {
    id: 'jade_lizard',
    name: 'Jade Lizard',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell OTM put + short OTM call spread. No risk on upside if credit exceeds call-spread width.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
    payoffPath: 'M0,34 L20,34 L35,14 L75,14 L90,20 L100,20',
  },
  {
    id: 'reverse_jade_lizard',
    name: 'Reverse Jade Lizard',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell OTM call + short OTM put spread. No risk on downside if credit exceeds put-spread width.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
    ],
    payoffPath: 'M0,20 L10,20 L25,14 L65,14 L80,34 L100,34',
  },
  {
    id: 'call_ratio_spread',
    name: 'Call Ratio Spread',
    direction: 'NON_DIRECTIONAL',
    description:
      'Buy 1 ATM call, sell 2 OTM calls. Peak profit at short strike; unlimited upside loss above.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 2 },
    ],
    payoffPath: 'M0,28 L50,28 L75,4 L100,38',
  },
  {
    id: 'put_ratio_spread',
    name: 'Put Ratio Spread',
    direction: 'NON_DIRECTIONAL',
    description:
      'Buy 1 ATM put, sell 2 OTM puts. Peak profit at short strike; unlimited downside loss below.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 2 },
    ],
    payoffPath: 'M0,38 L25,4 L50,28 L100,28',
  },
  {
    id: 'batman_strategy',
    name: 'Batman Strategy',
    direction: 'NON_DIRECTIONAL',
    description:
      'Call ratio spread (1×2) above + Put ratio spread (1×2) below. Two-eared "Batman" profile — small profit peaks at the short strikes, with unlimited loss on both wings due to the extra short legs.',
    legs: [
      // ── CE side: call ratio spread — long 1, short 2 ──
      { side: 'BUY', optionType: 'CE', strikeOffset: 10, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 15, lots: 2 },
      // ── PE side: put ratio spread — long 1, short 2 ──
      { side: 'BUY', optionType: 'PE', strikeOffset: -10, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -15, lots: 2 },
    ],
    payoffPath: 'M0,38 L15,30 L30,12 L45,22 L55,22 L70,12 L85,30 L100,38',
  },
  {
    id: 'long_iron_fly',
    name: 'Long Iron Fly',
    direction: 'NON_DIRECTIONAL',
    description: 'Short ATM straddle + long OTM wings. Max profit pinned at ATM.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,30 L25,30 L50,6 L75,30 L100,30',
  },
  {
    id: 'short_iron_fly',
    name: 'Short Iron Fly',
    direction: 'NON_DIRECTIONAL',
    description:
      'Long ATM straddle + short OTM wings. Max profit on a big move either way; max loss pinned at ATM.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,10 L25,10 L50,34 L75,10 L100,10',
  },
  {
    id: 'double_fly',
    name: 'Double Fly',
    direction: 'NON_DIRECTIONAL',
    description:
      'Two iron butterflies — one centred below spot, one above. Eight legs total: short straddle at each body strike, long CE wing above and long PE wing below. Two profit peaks at the body strikes, defined risk on both ends.',
    legs: [
      // ── CE legs (grouped first) ──
      // Lower iron fly body @ ATM − 8, CE wing @ ATM − 4 (4 strikes above body)
      { side: 'SELL', optionType: 'CE', strikeOffset: -8, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: -4, lots: 1 },
      // Upper iron fly body @ ATM + 8, CE wing @ ATM + 12 (4 strikes above body)
      { side: 'SELL', optionType: 'CE', strikeOffset: 8, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 12, lots: 1 },
      // ── PE legs ──
      // Lower iron fly PE wing @ ATM − 12 (4 strikes below body), body @ ATM − 8
      { side: 'BUY', optionType: 'PE', strikeOffset: -12, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -8, lots: 1 },
      // Upper iron fly PE wing @ ATM + 4 (4 strikes below body), body @ ATM + 8
      { side: 'BUY', optionType: 'PE', strikeOffset: 4, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 8, lots: 1 },
    ],
    payoffPath: 'M0,30 L10,30 L20,8 L35,30 L65,30 L80,8 L90,30 L100,30',
  },
  {
    id: 'long_iron_condor',
    name: 'Long Iron Condor',
    direction: 'NON_DIRECTIONAL',
    description: 'Bull put spread + bear call spread. Defined-risk range play.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -4, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
    payoffPath: 'M0,30 L20,30 L35,14 L65,14 L80,30 L100,30',
  },
  {
    id: 'short_iron_condor',
    name: 'Short Iron Condor',
    direction: 'NON_DIRECTIONAL',
    description:
      'Reverse of long iron condor — long wings pay off on a big move either way, short body caps upside if spot pins in the middle.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: -4, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 4, lots: 1 },
    ],
    payoffPath: 'M0,10 L20,10 L35,26 L65,26 L80,10 L100,10',
  },
  {
    id: 'double_condor',
    name: 'Double Condor',
    direction: 'NON_DIRECTIONAL',
    description:
      'Call condor + put condor at different strikes. Two wide profit plateaus on either side of spot.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: -5, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -4, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: -2, lots: 1 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -1, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 1, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 4, lots: 1 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 5, lots: 1 },
    ],
    payoffPath: 'M0,30 L15,30 L25,12 L40,12 L50,30 L60,30 L70,12 L85,12 L95,30 L100,30',
  },
  {
    id: 'call_calendar',
    name: 'Call Calendar',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell near-expiry ATM CE, buy far-expiry ATM CE (same strike). Profits from near-leg theta while the long keeps time value.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1, expiryOffset: 0 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 0, lots: 1, expiryOffset: 1 },
    ],
    // Asymmetric — steep left-side rise to a sharp peak, gentle fall off
    // to the right (calls lose value as spot drops; the far leg retains
    // value as spot rises so right-side decay is slower).
    payoffPath: 'M0,32 L25,28 L42,6 L65,18 L100,28',
  },
  {
    id: 'put_calendar',
    name: 'Put Calendar',
    direction: 'NON_DIRECTIONAL',
    description:
      'Sell near-expiry ATM PE, buy far-expiry ATM PE (same strike). Put-side equivalent of the call calendar.',
    legs: [
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 1, expiryOffset: 0 },
      { side: 'BUY', optionType: 'PE', strikeOffset: 0, lots: 1, expiryOffset: 1 },
    ],
    // Mirror of the call calendar — gentle left-side rise, steep fall on
    // the right (puts lose value as spot rises; the far leg retains value
    // as spot falls).
    payoffPath: 'M0,28 L35,18 L58,6 L75,28 L100,32',
  },
  {
    id: 'diagonal_calendar',
    name: 'Diagonal Calendar',
    direction: 'NON_DIRECTIONAL',
    description:
      'Calendar with different strikes — sell near ATM CE, buy far OTM CE. Adds a mild directional tilt to a calendar.',
    legs: [
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 1, expiryOffset: 0 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1, expiryOffset: 1 },
    ],
    // Diagonals show a widened peak — two small humps and a plateau
    // between the near-leg strike and the far-leg strike.
    payoffPath: 'M0,32 L20,28 L38,14 L50,10 L62,14 L78,22 L100,28',
  },
  {
    id: 'call_butterfly',
    name: 'Call Butterfly',
    direction: 'NON_DIRECTIONAL',
    description:
      'Long call butterfly centred at ATM. Max profit if spot pins at the body strike.',
    legs: [
      { side: 'BUY', optionType: 'CE', strikeOffset: -2, lots: 1 },
      { side: 'SELL', optionType: 'CE', strikeOffset: 0, lots: 2 },
      { side: 'BUY', optionType: 'CE', strikeOffset: 2, lots: 1 },
    ],
    payoffPath: 'M0,30 L35,30 L50,6 L65,30 L100,30',
  },
  {
    id: 'put_butterfly',
    name: 'Put Butterfly',
    direction: 'NON_DIRECTIONAL',
    description:
      'Long put butterfly centred at ATM. Put-side mirror of the call butterfly.',
    legs: [
      { side: 'BUY', optionType: 'PE', strikeOffset: 2, lots: 1 },
      { side: 'SELL', optionType: 'PE', strikeOffset: 0, lots: 2 },
      { side: 'BUY', optionType: 'PE', strikeOffset: -2, lots: 1 },
    ],
    payoffPath: 'M0,30 L35,30 L50,6 L65,30 L100,30',
  },
]

export function templatesByDirection(direction: Direction | 'ALL'): StrategyTemplate[] {
  if (direction === 'ALL') return STRATEGY_TEMPLATES
  return STRATEGY_TEMPLATES.filter((t) => t.direction === direction)
}
