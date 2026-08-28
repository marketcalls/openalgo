# Flow node reference

Generated from `services/flow_workflow_validator.py` and
`services/flow_executor_service.py` by `generate_reference.py`. Do not hand-edit:
regenerate it instead, so the table cannot drift from the contract.

**61 node types.** `Required` is what strict validation
demands at import and activation. `Also read` is every other `data` key the
executor looks at, so it is the complete set of what a node responds to.

## Every node

| Type | Kind | Required | Also read |
|---|---|---|---|
| `andGate` | gate | none | - |
| `barOffset` | action | `symbol`, `exchange` | `interval`, `offsetBars`, `source` |
| `basketOrder` | order | `orders` | `basketName` |
| `calendar` | action | none | `date` |
| `cancelAllOrders` | order | none | - |
| `cancelOrder` | order | `orderId` | - |
| `closePositions` | order | none | - |
| `delay` | action | none | `delayMs`, `delayUnit`, `delayValue` |
| `expiry` | action | `symbol`, `exchange` | `instrumenttype` |
| `fundCheck` | condition | none | `minAvailable`, `operator`, `threshold` |
| `funds` | action | none | - |
| `getDepth` | action | `symbol`, `exchange` | - |
| `getOrderStatus` | action | `orderId` | - |
| `getQuote` | action | `symbol`, `exchange` | - |
| `group` | action | none | - |
| `history` | action | `symbol`, `exchange`, `interval` | `days`, `endDate`, `startDate` |
| `holdings` | action | none | - |
| `holidays` | action | none | `year` |
| `httpRequest` | action | `url` | `body`, `headers`, `method`, `timeout` |
| `indicator` | action | `indicatorName` | `exchange`, `interval`, `lookbackBars`, `offsetBars`, `params`, `source`, `sourceField`, `sourceSeries`, `symbol`, `tailBars` |
| `intervals` | action | none | - |
| `log` | action | none | `level`, `message` |
| `margin` | action | none | `action`, `exchange`, `price`, `priceType`, `product`, `quantity`, `symbol` |
| `mathExpression` | action | `expression` | `outputVariable` |
| `modifyOrder` | order | `orderId` | - |
| `multiQuotes` | action | `symbols` | `exchange` |
| `notGate` | action | none | - |
| `openPosition` | action | `symbol`, `exchange` | `product` |
| `optionChain` | action | `underlying` | `exchange`, `expiryDate`, `strikeCount` |
| `optionSymbol` | action | `underlying`, `optionType` | `exchange`, `expiryDate`, `offset` |
| `optionsMultiOrder` | order | `underlying`, `quantity` | `action`, `exchange`, `expiryDate`, `expiryType`, `offset`, `optionType`, `price`, `priceType`, `product`, `splitSize`, `strangleWidth`, `strategy`, `strike`, `strikeMode`, `triggerPrice` |
| `optionsOrder` | order | `underlying`, `action`, `quantity` | `exchange`, `expiryDate`, `expiryType`, `offset`, `optionType`, `price`, `priceType`, `product`, `splitSize`, `triggerPrice` |
| `orGate` | gate | none | - |
| `orderBook` | action | none | - |
| `orderUpdateTrigger` | trigger | none | - |
| `placeOrder` | order | `symbol`, `exchange`, `action`, `quantity` | - |
| `positionBook` | action | none | - |
| `positionCheck` | condition | `symbol`, `exchange`, `condition` | `product`, `threshold` |
| `priceAlert` | trigger | `symbol`, `exchange`, `condition` | `price`, `priceLower`, `priceUpper` |
| `priceCondition` | condition | `symbol`, `exchange`, `operator` | `field`, `threshold`, `value` |
| `priorPeriodOhlc` | action | `symbol`, `exchange` | `period`, `source` |
| `smartOrder` | order | `symbol`, `exchange`, `action`, `quantity` | `positionSize` |
| `splitOrder` | order | `symbol`, `exchange`, `action`, `quantity`, `splitSize` | - |
| `start` | trigger | none | - |
| `strategyPnl` | action | none | `strategy` |
| `subscribeDepth` | action | `symbol`, `exchange` | `outputVariable` |
| `subscribeLtp` | action | `symbol`, `exchange` | `outputVariable` |
| `subscribeQuote` | action | `symbol`, `exchange` | `outputVariable` |
| `symbol` | action | `symbol`, `exchange` | - |
| `syntheticFuture` | action | `underlying` | `exchange`, `expiryDate` |
| `telegramAlert` | action | `message` | - |
| `timeCondition` | condition | none | `conditionType`, `operator`, `targetTime` |
| `timeWindow` | condition | none | `endTime`, `invertCondition`, `startTime` |
| `timings` | action | none | `date` |
| `tradeBook` | action | none | - |
| `unsubscribe` | action | none | `exchange`, `streamType`, `symbol` |
| `varCondition` | condition | `leftValue`, `operator` | - |
| `variable` | action | `variableName` | `jsonPath`, `name`, `operation`, `sourceVariable`, `value` |
| `waitUntil` | action | `targetTime` | - |
| `webhookTrigger` | trigger | none | - |
| `whatsappAlert` | action | `message` | `to` |

## Enumerated values

Matching is case-insensitive: a payload sending `buy` is accepted for `BUY`.

| Field | Accepted |
|---|---|
| `action` | `BUY`, `SELL` |
| `exchange` | `BCD`, `BFO`, `BSE`, `BSE_INDEX`, `CDS`, `CRYPTO`, `GLOBAL_INDEX`, `MCX`, `MCX_INDEX`, `NCDEX`, `NCO`, `NFO`, `NSE`, `NSE_INDEX` |
| `product` | `CNC`, `MIS`, `NRML` |
| `priceType` | `LIMIT`, `MARKET`, `SL`, `SL-M` |
| `optionType` | `CE`, `PE` |
| `expiryType` | `current_month`, `current_week`, `next_month`, `next_week`, or a `DDMMMYY` date |
| leg `strikeMode` | `OFFSET`, `STRIKE` |
| `offset` | `ATM`, `ITM1`-`ITM50`, `OTM1`-`OTM50` |

## Kinds

- **trigger** (`orderUpdateTrigger`, `priceAlert`, `start`, `webhookTrigger`) - a workflow needs
  exactly one, and it is the single execution root.
- **condition** - fans out into TRUE and FALSE branches; edges leaving one must
  set `sourceHandle`.
- **gate** - waits for every wired input before firing once.
- **order** - reaches a broker. Every field is guarded, so an unresolved
  `{{reference}}` fails the node instead of becoming a default.
- **action** - everything else: data, utility, streaming.

## Nodes with no executor branch

`group`, `notGate`

These are handled inline or by the graph walk rather than by a node method.
