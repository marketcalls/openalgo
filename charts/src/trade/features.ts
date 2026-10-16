/**
 * Declarations for the trading operations that came after place, modify and
 * cancel: account reads, order preview, durations, leverage, and the native
 * position commands.
 *
 * The rule here is the opposite of the original capability flags. Those treat
 * an omission as "the legacy route still works", because a provider written
 * before they existed must keep placing orders. Nothing written before this
 * file can carry an account, a duration or a close, so an omission here means
 * unsupported. A host that assumed otherwise would drop the field on the wire
 * and send the order somewhere the user did not choose, or dress an opposite
 * order up as a native close.
 */
import type { TradingCapabilityResult } from 'openalgo-charts';
import type { OrderType } from './types';

/** Time in force for a new order. `GTD` needs an expiry. */
export type OrderDuration = 'DAY' | 'IOC' | 'FOK' | 'GTC' | 'GTD';

/** Every duration the request schema understands, in display order. */
export const ORDER_DURATIONS: readonly OrderDuration[] = ['DAY', 'IOC', 'FOK', 'GTC', 'GTD'];

export type TradingFeature =
  | 'accounts'
  | 'executions'
  | 'orderHistory'
  | 'preview'
  | 'duration'
  | 'leverage'
  | 'close'
  | 'partialClose'
  | 'reverse'
  | 'brackets';

/** What a provider declares. Omitted, false and `'unknown'` all refuse. */
export interface TradingFeatures {
  /** Account list, snapshots, positions and selection. */
  readonly accounts?: boolean | 'unknown';
  readonly executions?: boolean | 'unknown';
  readonly orderHistory?: boolean | 'unknown';
  readonly preview?: boolean | 'unknown';
  /** Durations accepted on new orders. Omitted: no explicit duration may be sent. */
  readonly durations?: readonly OrderDuration[];
  readonly leverage?: boolean | 'unknown';
  readonly close?: boolean | 'unknown';
  readonly partialClose?: boolean | 'unknown';
  readonly reverse?: boolean | 'unknown';
  /** Brackets whose stop and target legs the provider itself links. */
  readonly brackets?: boolean | 'unknown';
}

export interface TradingFeatureRequest {
  readonly feature: TradingFeature;
  readonly symbol?: string | undefined;
  readonly exchange?: string | undefined;
  readonly account?: string | undefined;
  readonly mode?: 'live' | 'analyzer' | undefined;
  readonly type?: OrderType | undefined;
  readonly duration?: OrderDuration | undefined;
}

/** A configured provider returning undefined, throwing or answering late declares nothing. */
export type TradingFeatureSource = TradingFeatures
  | ((request: Readonly<TradingFeatureRequest>) => TradingFeatures | undefined);

const LABEL: Readonly<Record<TradingFeature, string>> = {
  accounts: 'Account data',
  executions: 'Execution history',
  orderHistory: 'Order history',
  preview: 'Order preview',
  duration: 'Order duration',
  leverage: 'Leverage',
  close: 'Closing a position',
  partialClose: 'Partial close',
  reverse: 'Reversing a position',
  brackets: 'Bracket placement',
};

/** The words a refusal uses for a feature, shared so every surface says the same thing. */
export function tradingFeatureLabel(feature: TradingFeature): string {
  return LABEL[feature];
}

/** Shared by host controls, the order engine, the account manager and the simulated broker. */
export function checkTradingFeature(
  source: TradingFeatureSource | undefined,
  request: TradingFeatureRequest,
): TradingCapabilityResult {
  const label = LABEL[request.feature];
  const undeclared = { supported: false, reason: `${label} is not declared by this provider` } as const;
  if (source === undefined) return undeclared;
  try {
    const features = typeof source === 'function' ? source(Object.freeze({ ...request })) : source;
    if (!features || typeof features !== 'object' || Array.isArray(features) || 'then' in features) {
      return { supported: false, reason: 'Trading features are unavailable' };
    }
    if (request.feature === 'duration') {
      const list = features.durations;
      if (!Array.isArray(list)) return undeclared;
      if (request.duration === undefined) return { supported: false, reason: 'Order duration needs a named duration' };
      return list.includes(request.duration)
        ? { supported: true }
        : { supported: false, reason: `Duration ${request.duration} is not supported` };
    }
    const support = features[request.feature];
    if (support === true) return { supported: true };
    if (support === false) return { supported: false, reason: `${label} is not supported` };
    if (support === undefined) return undeclared;
    return { supported: false, reason: `Support for ${label.toLowerCase()} is unknown` };
  } catch {
    return { supported: false, reason: 'Trading features are unavailable' };
  }
}
