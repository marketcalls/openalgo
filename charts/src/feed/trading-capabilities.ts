import type { OrderType } from './types';

export type TradingOperation = 'place' | 'modify' | 'cancel';

/** Optional restrictions on existing write paths; omissions preserve legacy support. */
export interface TradingCapabilities {
  readonly place?: boolean | 'unknown';
  readonly modify?: boolean | 'unknown';
  readonly cancel?: boolean | 'unknown';
  /** Accepted types for new orders. An empty list disables placement. */
  readonly orderTypes?: readonly OrderType[];
  /** Accepted modes for new orders; does not change the broker's actual mode. */
  readonly modes?: readonly ('live' | 'analyzer')[];
}

export interface TradingCapabilityRequest {
  readonly operation: TradingOperation;
  readonly symbol?: string;
  readonly exchange?: string | undefined;
  readonly orderId?: string | undefined;
  readonly type?: OrderType | undefined;
  readonly mode?: 'live' | 'analyzer' | undefined;
}

/** A configured provider returning undefined declares that support is unavailable. */
export type TradingCapabilitySource = TradingCapabilities
  | ((request: Readonly<TradingCapabilityRequest>) => TradingCapabilities | undefined);

export type TradingCapabilityResult = { supported: true } | { supported: false; reason: string };

// A reason reaches the chart's menus and a host's toasts, so it names the
// operation, the order type and the mode in words, not by their ids.
const OPERATION_WORDS: Record<TradingOperation, string> = { place: 'placing orders', modify: 'modifying orders', cancel: 'cancelling orders' };
const TYPE_WORDS: Record<OrderType, string> = { MARKET: 'Market orders', LIMIT: 'Limit orders', SL: 'Stop-loss orders', 'SL-M': 'Stop-loss market orders' };
const MODE_WORDS = { live: 'Live trading', analyzer: 'Analyzer mode' } as const;
const capital = (words: string): string => words[0]!.toUpperCase() + words.slice(1); // only ever handed a word

/** Shared by host controls and the write boundary. Never grants broker authority. */
export function checkTradingCapability(
  source: TradingCapabilitySource | undefined,
  request: TradingCapabilityRequest,
): TradingCapabilityResult {
  if (source === undefined) return { supported: true };
  try {
    const capabilities = typeof source === 'function' ? source(Object.freeze({ ...request })) : source;
    if (!capabilities || typeof capabilities !== 'object' || Array.isArray(capabilities) || 'then' in capabilities) {
      return { supported: false, reason: 'Trading capabilities are unavailable' };
    }
    const support = capabilities[request.operation];
    if (support === false) return { supported: false, reason: `${capital(OPERATION_WORDS[request.operation] ?? request.operation)} is not supported` };
    if (support !== undefined && support !== true) {
      return { supported: false, reason: `Support for ${OPERATION_WORDS[request.operation] ?? request.operation} is unknown` };
    }
    // Placement restrictions cannot strand an existing order that remains cancellable.
    if (request.operation === 'place') {
      if (capabilities.orderTypes !== undefined) {
        if (!Array.isArray(capabilities.orderTypes) || request.type === undefined) {
          return { supported: false, reason: 'Supported order types are unavailable for this request' };
        }
        if (!capabilities.orderTypes.includes(request.type)) {
          return { supported: false, reason: `${TYPE_WORDS[request.type] ?? `${request.type} orders`} are not supported` };
        }
      }
      if (capabilities.modes !== undefined) {
        if (!Array.isArray(capabilities.modes) || request.mode === undefined) {
          return { supported: false, reason: 'Supported trading modes are unavailable for this request' };
        }
        if (!capabilities.modes.includes(request.mode)) {
          return { supported: false, reason: `${MODE_WORDS[request.mode] ?? `${request.mode} mode`} is not supported` };
        }
      }
    }
    return { supported: true };
  } catch {
    return { supported: false, reason: 'Trading capabilities are unavailable' };
  }
}

/** Raised only before delivery, so an unsupported write does not become ambiguous. */
export class TradingCapabilityError extends Error {
  public readonly preflight = true as const;
  public readonly operation: TradingOperation;

  public constructor(operation: TradingOperation, reason: string) {
    super(reason);
    this.name = 'TradingCapabilityError';
    this.operation = operation;
  }
}

export function assertTradingCapability(source: TradingCapabilitySource | undefined, request: TradingCapabilityRequest): void {
  const result = checkTradingCapability(source, request);
  if (!result.supported) throw new TradingCapabilityError(request.operation, result.reason);
}
