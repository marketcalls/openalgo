/**
 * Order state machine (ARCHITECTURE.md §9.5). Explicit client-side states with
 * a guarded transition table: no optimistic guesswork. Pure and fully testable.
 *
 *   pending_place -ack-> working -fill-> filled
 *                 -reject-> rejected
 *   working/partial -reject-> rejected     (the broker refusing one it accepted)
 *   working/partial -submitModify-> modify_pending -ack-> working / -reject-> working
 *   working/partial -submitCancel-> cancel_pending -cancelled-> cancelled / -reject-> working
 *   any non-terminal -reconnectAbsent-> stale
 */
export type ClientOrderState =
  | 'pending_place'
  | 'working'
  | 'partial'
  | 'filled'
  | 'modify_pending'
  | 'cancel_pending'
  | 'rejected'
  | 'cancelled'
  | 'stale';

export type OrderEvent =
  | 'ack'
  | 'partialFill'
  | 'fill'
  | 'reject'
  | 'submitModify'
  | 'submitCancel'
  | 'cancelled'
  | 'reconnectAbsent';

const TERMINAL: ReadonlySet<ClientOrderState> = new Set(['filled', 'cancelled', 'rejected', 'stale']);

export function isTerminal(state: ClientOrderState): boolean {
  return TERMINAL.has(state);
}

const TRANSITIONS: Record<ClientOrderState, Partial<Record<OrderEvent, ClientOrderState>>> = {
  pending_place: { ack: 'working', partialFill: 'partial', fill: 'filled', reject: 'rejected', reconnectAbsent: 'stale' },
  // `reject` from working/partial is the broker rejecting an order it had
  // already accepted (an AMO the exchange refuses at open, an RMS square-off).
  // Without the edge, an authoritative "rejected" left `state` reading working
  // while `brokerStatus` said otherwise, and the row never settled.
  working: { partialFill: 'partial', fill: 'filled', reject: 'rejected', submitModify: 'modify_pending', submitCancel: 'cancel_pending', cancelled: 'cancelled', reconnectAbsent: 'stale' },
  partial: { partialFill: 'partial', fill: 'filled', reject: 'rejected', submitModify: 'modify_pending', submitCancel: 'cancel_pending', cancelled: 'cancelled', reconnectAbsent: 'stale' },
  modify_pending: { ack: 'working', reject: 'working', fill: 'filled', partialFill: 'partial', cancelled: 'cancelled', reconnectAbsent: 'stale' },
  cancel_pending: { cancelled: 'cancelled', reject: 'working', fill: 'filled', reconnectAbsent: 'stale' },
  // terminal states accept nothing
  filled: {},
  cancelled: {},
  rejected: {},
  stale: {},
};

/** Whether `event` is allowed from `state`. */
export function canTransition(state: ClientOrderState, event: OrderEvent): boolean {
  return TRANSITIONS[state][event] !== undefined;
}

/** Apply `event`; returns the next state, or the same state if the event is invalid. */
export function transition(state: ClientOrderState, event: OrderEvent): ClientOrderState {
  return TRANSITIONS[state][event] ?? state;
}
