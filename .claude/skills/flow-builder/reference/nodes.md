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
| `barOffset` | action | `symbol`, `exchange` | `interval`, `offsetBars`, `outputVariable`, `source` |
| `basketOrder` | order | `orders` | `basketName`, `outputVariable` |
| `calendar` | action | none | `date`, `outputVariable` |
| `cancelAllOrders` | order | none | `outputVariable` |
| `cancelOrder` | order | `orderId` | - |
| `closePositions` | order | none | `exchange`, `outputVariable`, `product`, `strategyTag`, `symbol` |
| `delay` | action | none | `delayMs`, `delayUnit`, `delayValue` |
| `expiry` | action | `symbol`, `exchange` | `instrumenttype`, `outputVariable` |
| `fundCheck` | condition | none | `minAvailable`, `operator`, `threshold` |
| `funds` | action | none | `outputVariable` |
| `getDepth` | action | `symbol`, `exchange` | `outputVariable` |
| `getOrderStatus` | action | `orderId` | `outputVariable` |
| `getQuote` | action | `symbol`, `exchange` | `outputVariable` |
| `group` | action | none | - |
| `history` | action | `symbol`, `exchange`, `interval` | `days`, `endDate`, `outputVariable`, `startDate` |
| `holdings` | action | none | `outputVariable` |
| `holidays` | action | none | `outputVariable`, `year` |
| `httpRequest` | action | `url` | `body`, `headers`, `method`, `outputVariable`, `timeout` |
| `indicator` | action | `indicatorName` | `exchange`, `interval`, `lookbackBars`, `offsetBars`, `outputVariable`, `params`, `source`, `sourceField`, `sourceSeries`, `symbol`, `tailBars` |
| `intervals` | action | none | `outputVariable` |
| `log` | action | none | `level`, `message` |
| `margin` | action | none | `action`, `exchange`, `outputVariable`, `price`, `priceType`, `pricetype`, `product`, `quantity`, `symbol`, `trigger_price` |
| `mathExpression` | action | `expression` | `outputVariable` |
| `modifyOrder` | order | `orderId` | `action`, `exchange`, `newPrice`, `newQuantity`, `newTriggerPrice`, `outputVariable`, `priceType`, `product`, `symbol` |
| `multiQuotes` | action | `symbols` | `exchange`, `outputVariable` |
| `notGate` | action | none | - |
| `openPosition` | action | `symbol`, `exchange` | `outputVariable`, `product` |
| `optionChain` | action | `underlying` | `exchange`, `expiryDate`, `outputVariable`, `strikeCount` |
| `optionSymbol` | action | `underlying`, `optionType` | `exchange`, `expiryDate`, `offset`, `outputVariable` |
| `optionsMultiOrder` | order | `underlying`, `quantity` | `action`, `exchange`, `expiryType`, `offset`, `optionType`, `outputVariable`, `price`, `priceType`, `product`, `splitSize`, `strangleWidth`, `strategy`, `strategyTag`, `strike`, `strikeMode`, `triggerPrice` |
| `optionsOrder` | order | `underlying`, `action`, `quantity` | `exchange`, `expiryType`, `offset`, `optionType`, `outputVariable`, `price`, `priceType`, `product`, `splitSize`, `strategyTag`, `triggerPrice` |
| `orGate` | gate | none | - |
| `orderBook` | action | none | `outputVariable` |
| `orderUpdateTrigger` | trigger | none | - |
| `placeOrder` | order | `symbol`, `exchange`, `action`, `quantity` | `outputVariable`, `price`, `priceType`, `product`, `strategyTag`, `triggerPrice` |
| `positionBook` | action | none | `outputVariable` |
| `positionCheck` | condition | `symbol`, `exchange`, `condition` | `product`, `threshold` |
| `priceAlert` | trigger | `symbol`, `exchange`, `condition` | `outputVariable`, `price`, `priceLower`, `priceUpper` |
| `priceCondition` | condition | `symbol`, `exchange`, `operator` | `field`, `threshold`, `value` |
| `priorPeriodOhlc` | action | `symbol`, `exchange` | `outputVariable`, `period`, `source` |
| `smartOrder` | order | `symbol`, `exchange`, `action`, `quantity` | `outputVariable`, `positionSize`, `price`, `priceType`, `product`, `strategyTag`, `triggerPrice` |
| `splitOrder` | order | `symbol`, `exchange`, `action`, `quantity`, `splitSize` | `outputVariable`, `price`, `priceType`, `product`, `strategyTag`, `triggerPrice` |
| `start` | trigger | none | - |
| `strategyPnl` | action | none | `outputVariable`, `strategy` |
| `subscribeDepth` | action | `symbol`, `exchange` | `outputVariable` |
| `subscribeLtp` | action | `symbol`, `exchange` | `outputVariable` |
| `subscribeQuote` | action | `symbol`, `exchange` | `outputVariable` |
| `symbol` | action | `symbol`, `exchange` | `outputVariable` |
| `syntheticFuture` | action | `underlying` | `exchange`, `expiryDate`, `outputVariable` |
| `telegramAlert` | action | `message` | - |
| `timeCondition` | condition | none | `conditionType`, `operator`, `targetTime` |
| `timeWindow` | condition | none | `endTime`, `invertCondition`, `startTime` |
| `timings` | action | none | `date`, `outputVariable` |
| `tradeBook` | action | none | `outputVariable` |
| `unsubscribe` | action | none | `exchange`, `streamType`, `symbol` |
| `varCondition` | condition | `leftValue`, `operator` | `rightValue` |
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
