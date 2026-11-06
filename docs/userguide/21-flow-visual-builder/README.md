# 21 - Flow Visual Builder

## Open the Editor

Open **Flow Editor** from the profile menu, or visit `/flow`. Create a workflow from the list, then open its canvas at `/flow/editor/<id>`. Nodes can be dragged from the palette or added with its buttons, configured in the properties panel and connected by their handles.

The [Flow import reference](../../prompt/flow-import-format.md) is the canonical contract for node fields, variables and branching. Use its worked examples when importing a workflow or asking an AI assistant to generate one; do not invent node types.

## Build a Workflow

1. Choose a trigger: **Schedule**, **Price Alert**, **Webhook** or **Order Update**.
2. Add data nodes for the market/account information needed by the decision, such as Get Quote, History, Indicator, Position Book or Order Book.
3. Add conditions and connect their matching outputs. A true/false handle determines which path runs; a condition is not an implicit loop.
4. Configure the order action and explicitly set symbol, exchange, product, side and quantity.
5. Add Log or Telegram/WhatsApp alerts where useful, then **Save**.
6. Verify **Analyze** mode before using **Run Now**, inspect the execution result and sandbox books, then activate only the intended trigger.

Run Now and Activate use the server's saved workflow. The editor saves dirty changes before these actions; if it cannot obtain a stable saved graph, it refuses the action. A successful save alone does not activate a workflow or place a trade.

## Variables and Indicators

Variables use `{{name.field}}` interpolation. A Webhook trigger exposes payload fields as `{{webhook.symbol}}`, `{{webhook.action}}` and similar paths. Data and action nodes write to their configured output variable. Use the actual node output shape from the [import reference](../../prompt/flow-import-format.md), rather than assuming every node returns the same fields.

Variables are local to an execution. They do not persist a flag or counter into the next scheduled run. Ask the broker/sandbox for positions and order history when checking whether you have already traded.

The Indicator node uses the Python `openalgo.ta` library and historical data; it does not run JavaScript chart indicators or OpenScript. See the [Flow indicator reference](<../../prompt/indicators/flow indicator reference.md>).

## Webhooks

Open a workflow's **Webhook** settings from the list. Enable it, choose payload or URL authentication, and copy the generated URL and secret. The route has the form `POST /flow/webhook/<token>`; there is no manually chosen `/flow/tradingview` route.

For payload authentication, send the secret in the JSON body with the signal fields. URL authentication is available for senders that cannot supply that body field; copy the exact URL shown in the dialog. Keep the URL/token and secret private. Regenerating them invalidates the old values and requires updating every sender.

A webhook trigger needs an active, webhook-enabled workflow. Test its real response and execution log. Repeated webhook requests can cause repeated trading decisions; do not assume placement requests are automatically deduplicated.

## Activation, Edits and Imports

**Activate** registers the workflow's trigger. **Deactivate** unregisters it; deactivating does not cancel broker orders or close positions already created. Inspect any in-flight execution and manage its actual positions separately.

Use Export/Import for a new copy. Import creates a new workflow and new webhook identity. To retain the existing workflow ID and webhook, use **Replace from JSON** in its editor menu. Check any validation and `needs_reactivate` message: when a trigger changes, deactivate and reactivate as instructed. If registering a saved trigger fails, the editor reports that the workflow was deactivated.

Open **Keyboard Shortcuts** in Flow (`/flow/shortcuts`) for canvas controls.

## Execution Limits and Order Safety

Flow has no general loop, persistent variable store, symbol-list iterator or backtesting engine. Use a recurring Schedule with a Time Window for repeated checks, or separate entry, exit and square-off workflows. Delay and Wait Until are timing controls, not persistent monitoring of a target or stop.

Do not build a blind order retry path. A timeout or failed HTTP response can occur after the broker accepted an order; reconcile order book, trades and positions before sending any replacement. Baskets can have partial outcomes. Use [Action Center](../22-action-center/README.md) when intentionally requiring manual approval, and check each API operation's Semi-Auto behavior before relying on automated exits.

Live/Analyze applies across the instance. Run Now is an actual execution in the current mode, not a simulation button. Verify the mode and quantities before using it. Historical strategy testing belongs in a backtester, not a Flow execution.

For full node and import behavior, use the [Flow import reference](../../prompt/flow-import-format.md). For implementation details, see [Flow execution](../../prd/flow-execution.md).

---

**Previous**: [20 - Python Strategies](../20-python-strategies/README.md)

**Next**: [22 - Action Center](../22-action-center/README.md)
