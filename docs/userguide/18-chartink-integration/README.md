# 18 - Chartink Integration

## Create a Chartink Strategy

Open **Platforms > Chartink** or `/chartink`. The built-in module receives Chartink scan payloads, maps configured equities, and queues orders through OpenAlgo.

1. Create a strategy and choose **Intraday** or **Positional**.
2. For Intraday, set start, entry-end and square-off times in **IST**, with `start < end < square-off`.
3. Open the strategy detail and **Configure Symbols**.
4. Add each Chartink symbol with its exchange (`NSE` or `BSE`), quantity and product (`MIS` or `CNC`). Search the master contract to verify the instrument.
5. Alternatively use Bulk Import with one `ChartinkSymbol,Exchange,Quantity,Product` row per line and no header. Review added/failed counts and saved mappings.
6. Copy the strategy's generated Webhook URL from its detail page. It has the form `/chartink/webhook/<webhook_id>`.

The native Chartink module is for NSE/BSE equities with MIS/CNC mappings; it is not a generic futures/options strategy builder.

## Configure the Alert

Your Chartink account/alert must support outbound webhooks to a reachable OpenAlgo address. Configure the public host URL for the installation; a remote provider cannot call your `localhost`. Copy the URL shown by OpenAlgo rather than constructing an API placement URL for Chartink's native scan payload.

Use exactly one action keyword in the scan/alert name:

| Keyword in `scan_name` | OpenAlgo behavior |
|---|---|
| `BUY` | Long entry using the mapped quantity |
| `SHORT` | Short entry using the mapped quantity |
| `SELL` | Smart-order exit with zero quantity and zero target |
| `COVER` | Smart-order cover with zero quantity and zero target |

The parser checks BUY, SELL, SHORT and COVER in that order. A name containing several keywords can select an unintended action, so keep the name unambiguous.

The webhook reads comma-separated `stocks` and the action from `scan_name`. Its own saved strategy/API key and symbol mappings supply the order settings. Trigger prices in the scan payload do not turn these into limit orders; this path sends MARKET requests.

Illustrative receiver payload:

```json
{
  "scan_name": "Momentum BUY",
  "stocks": "SBIN,INFY",
  "trigger_prices": "625,1800"
}
```

Keep the generated webhook URL private: its identifier selects the strategy. Unlike a direct `/api/v1/placeorder` request, the native receiver does not ask the sender to include the OpenAlgo API key in this payload.

## Activation and Trading Window

Activate the strategy after its mappings and alert are configured. An inactive strategy acknowledges that it is inactive and queues no orders. Unmapped symbols are skipped.

For Intraday:

- Before start, orders are refused.
- From entry-end onward, BUY/SHORT entries are refused while SELL/COVER exits remain eligible until square-off.
- At or after square-off, webhook orders are refused. The module schedules its separate square-off workflow.

Positional strategies do not apply those intraday time checks. Deactivation does not itself close existing positions. Confirm the scheduled square-off's actual orders and positions rather than treating a schedule as a fill guarantee.

## Rehearse and Monitor

1. Verify **Analyze** mode before enabling a real alert.
2. Send a test scan containing one mapped symbol and one intended action.
3. Read the webhook response and live/sandbox logs, then inspect orders, trades and positions.
4. Test entries, exits, entry-end and square-off behavior before Live.

`Orders queued for symbols` means the native queue accepted work; it is not a broker acceptance or fill. A repeated scan can create repeated entry decisions. Avoid retrying unclear requests until you have reconciled the resulting books. Semi-Auto routing can additionally queue eligible live placements in [Action Center](../22-action-center/README.md).

See [Chartink design](../../design/13-chartink/README.md) for queue and scheduling details, [Smart Orders](../12-smart-orders/README.md) for position semantics and [Troubleshooting](../29-troubleshooting/README.md) for connection failures.

---

**Previous**: [17 - Amibroker Integration](../17-amibroker-integration/README.md)

**Next**: [19 - GoCharting Integration](../19-gocharting-integration/README.md)
