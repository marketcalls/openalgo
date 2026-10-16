# Trading capabilities

`TradingCapabilities` declares which existing trading operations a feed or host
supports. The same query is available from `openalgo-charts` and
`openalgo-charts/trade`, so controls and write boundaries can use one contract.
It does not place orders, change broker mode or create a second order authority.

```ts
interface TradingCapabilities {
  readonly place?: boolean | 'unknown';
  readonly modify?: boolean | 'unknown';
  readonly cancel?: boolean | 'unknown';
  readonly orderTypes?: readonly ('MARKET' | 'LIMIT' | 'SL' | 'SL-M')[];
  readonly modes?: readonly ('live' | 'analyzer')[];
}
```

An omitted declaration or omitted field preserves existing behavior. Explicit
`false` means unsupported; `'unknown'` means support has not been established.
Both block the corresponding operation. An empty `orderTypes` or `modes` list
blocks new orders. These lists apply to placement only, so withdrawing support
for a new order type does not prevent cancelling an existing order when
`cancel` remains supported.

Use `TradingCapabilitySource` for a static declaration or a synchronous
provider. The provider receives a readonly `TradingCapabilityRequest` with
`operation` and optional `symbol`, `exchange`, `orderId`, `type` and `mode`.
A configured provider returning `undefined`, throwing, or returning a non-object,
array or asynchronous result is treated as unavailable. This is distinct from
omitting the provider. Return explicit unknown support while account or instrument metadata
is unavailable; do not substitute an empty declaration for unknown support.

`checkTradingCapability(source, request)` returns `TradingCapabilityResult`:
either `{ supported: true }` or `{ supported: false, reason }`. Hosts can hide
unsupported controls or disable them with the returned reason. A declared
type or mode list requires that qualifier in the request; the helper does not
guess a missing type or mode. Providers receive a frozen copy of the request
and cannot change the operation being checked.

`assertTradingCapability(source, request)` throws `TradingCapabilityError` on
refusal. The error carries `operation` and `preflight: true`, because this
particular attempt was refused before delivery. That marker does not release
or resolve a previous ambiguous attempt with the same token.

## Existing trading paths

`OrderFeed.capabilities` is optional. `OrderEngineOptions.capabilities` adds
host restrictions to the feed's declaration; it cannot override a feed refusal.
The engine checks both before confirmation and again before delivery. It also
checks drag modifies when queued and when flushed, and checks manual and OCO
cancellations before delivery. Capability refusals for placement return
`PlaceResult` with `intent: 'BLOCKED'`. Modify/cancel refusals use the existing
`onValidationError` callback and leave the current order state intact.

The engine and direct feed snapshot placement values at entry. Changes to the
caller's request during confirmation or mode lookup cannot replace the admitted
order. Confirmation callbacks receive a separate copy; changing that copy does
not change the submitted values. Modify options and patches are also detached
before capability callbacks or adapter delivery can change them.

`OpenAlgoTradeConfig.capabilities` applies the same restrictions when a host
calls `OpenAlgoTradeFeed` directly. The feed exposes the source through its
readonly `capabilities` getter. It checks placement before the mode lookup and
again after that asynchronous boundary. Unsupported modify and cancel calls
fail before request delivery; an unsupported modify does not change cached
order context. The existing server-mode verification, quantity checks and
idempotency behavior remain in place.

No declaration enables a broker feature the broker does not have. A successful
capability check is an admission check, not an order acknowledgement, account
permission, margin approval, or proof that a specific order can be changed.
Keep the existing broker checks and reconciliation paths.

## Replay and changing host state

Use a provider when support can change during confirmation, account switches,
replay selection or queued order edits. Static declarations are appropriate
only when their lifetime matches the capability being described.

This example combines an active chart replay with a host-owned workspace lock:

```ts
import {
  isReplaying,
  type TradingCapabilities,
  type TradingCapabilitySource,
} from 'openalgo-charts';

function tradingSource(
  chart: object,
  brokerCapabilities: () => TradingCapabilities | undefined,
  workspaceLocked: () => boolean,
): TradingCapabilitySource {
  return () => {
    if (isReplaying(chart) || workspaceLocked()) {
      return { place: false, modify: false, cancel: false };
    }
    return brokerCapabilities();
  };
}
```

Supply the same provider to `OrderEngineOptions.capabilities` or the direct
feed's config and to the host's controls. `isReplaying(chart)` reads active
replay; the host still owns selection, loading transitions and locks covering
other charts. A standalone engine or feed has no chart reference and cannot
infer these states without that provider.

The widget and its context-menu hooks accept `tradingCapabilities`, optional
`tradingMode`, and `tradingLocked`. The widget checks capabilities when building
the menu and immediately before calling `onOrder`. It also checks current
chart replay and the host lock at callback time, so an open menu cannot retain
permission after replay starts. `tradingMode` qualifies the capability check;
it does not route the order or replace the feed's server-mode guard.

## Broker authority and uncertainty

Capability changes do not alter orders, positions or broker statuses. Unknown
order-book statuses remain unknown. A delivered request with an uncertain
outcome retains its `AMBIGUOUS` intent and idempotency claim. A duplicate
engine placement still reports that existing ambiguous intent after support
is withdrawn.

A refused modify or cancel leaves the previous client state and intent in
place, including partial fills and an unacknowledged `SUBMITTED` intent. A
broker event received while a preflight refusal is pending remains
authoritative. Transport success alone still does not write `brokerStatus`;
only the broker update path (`onBrokerUpdate`, or `onBrokerOrder` with the
client token the broker echoes) does that, plus a feed error marked
`rejected: true`, which is the broker's own explicit refusal and settles the
intent as rejected.

New broker updates, reconciliation and later modify/cancel attempts supersede
older write completions. A late transport success or failure cannot overwrite
the newer intent, restore an outdated modify offset, or turn a broker-confirmed
fill back into an ambiguous intent. Superseding an attempt does not cancel its
network request; subsequent broker events still establish the actual outcome.

Capabilities and replay locks are runtime inputs. They are not workspace
layout data and do not serialize broker orders, account state or armed flags.

## Newer operations are declared, not assumed

Accounts, execution and order history, preview, durations, leverage, close,
partial close, reverse and provider brackets are declared separately, with the
trade tier's `TradingFeatures` on `OrderFeed.features` and checked with
`checkTradingFeature`. The rule is the reverse of the flags above: an omitted
feature is unsupported, so a provider written before these operations existed
refuses them instead of dropping an account or a duration on the wire, or
standing in an opposite order for a close. The place flag and accepted modes
still govern the position commands, so a host replay lock stops them as well.
See the website guide, Accounts and advanced orders, and
`tests/order-engine-accounts.test.ts`, `tests/account-manager.test.ts`.

## Verification

The capability regressions use memory feeds and injected HTTP responses; no
broker connection or order delivery occurs. Run the focused regression set:

```sh
npx vitest run tests/trading-request-races.test.ts tests/trading-capabilities.test.ts tests/order-engine.test.ts tests/hardening-order-engine.test.ts tests/hardening-trade-feed.test.ts tests/feed-guards.test.ts tests/hardening-validation.test.ts tests/openalgo-adapters.test.ts
```

The new cases include capability changes during confirmation and mode lookup,
queued modify withdrawal, unknown metadata, preflight state preservation,
OCO cancellation guards, unknown book rows and ambiguous token retention. They
also cover caller/callback request mutation, newer broker fills followed by
late write successes or failures, and reconciliation across pending writes.
Widget callback and replay guards have separate widget tests. Connected broker
support remains a host integration check; these deterministic tests do not
establish support for any specific broker or account.
