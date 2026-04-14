# 21 - Flow Visual Strategy Builder

## Introduction

The Flow Visual Strategy Builder is OpenAlgo's node-based visual programming interface. It allows you to create trading strategies without writing code by connecting nodes in a flowchart-like canvas.

## What is the Flow Builder?

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Flow Visual Strategy Builder                         │
│                                                                              │
│  ┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐          │
│  │  Trigger │────▶│ Condition│────▶│  Action  │────▶│  Output  │          │
│  │   Node   │     │   Node   │     │   Node   │     │   Node   │          │
│  └──────────┘     └──────────┘     └──────────┘     └──────────┘          │
│                                                                              │
│  Example: Webhook → Check Price → Place Order → Send Notification           │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Benefits

| Feature | Description |
|---------|-------------|
| No Coding Required | Build strategies visually |
| Drag and Drop | Intuitive interface |
| Real-time Testing | Test flows instantly |
| Reusable Components | Save and reuse node groups |
| Version Control | Track changes to flows |

## Accessing the Flow Builder

1. Login to OpenAlgo
2. Navigate to **Flow** in the sidebar
3. Click **New Flow** or select existing

## Interface Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Flow Builder                                           [Save] [Run] [Stop] │
├───────────────────┬─────────────────────────────────────────────────────────┤
│                   │                                                          │
│  Node Palette     │                  Canvas                                 │
│  ───────────────  │                                                          │
│                   │    ┌────────┐                                           │
│  ▶ Triggers       │    │Webhook │                                           │
│    • Webhook      │    │ Input  │───────┐                                   │
│    • Timer        │    └────────┘       │                                   │
│    • Schedule     │                     ▼                                   │
│                   │              ┌────────────┐                             │
│  ▶ Conditions     │              │ Price Check│                             │
│    • If/Else      │              └────────────┘                             │
│    • Compare      │                     │                                   │
│    • Logic Gate   │                     ▼                                   │
│                   │              ┌────────────┐                             │
│  ▶ Actions        │              │Place Order │                             │
│    • Place Order  │              └────────────┘                             │
│    • Smart Order  │                                                          │
│    • Close All    │                                                          │
│                   │                                                          │
│  ▶ Utilities      │                                                          │
│    • Log          │                                                          │
│    • Telegram     │                                                          │
│    • Delay        │                                                          │
│                   │                                                          │
└───────────────────┴─────────────────────────────────────────────────────────┘
```

## Node Types

### Trigger Nodes

Trigger nodes start flow execution.

| Node | Description | Use Case |
|------|-------------|----------|
| Webhook | Receives external HTTP requests | TradingView, ChartInk alerts |
| Timer | Executes at intervals | Periodic checks |
| Schedule | Executes at specific times | Market open/close actions |
| Manual | Manual trigger button | Testing |

### Condition Nodes

Condition nodes control flow logic.

| Node | Description | Use Case |
|------|-------------|----------|
| If/Else | Branch based on condition | Price above/below threshold |
| Compare | Compare two values | Value comparisons |
| Logic Gate | AND, OR, NOT operations | Multiple conditions |
| Switch | Multiple branches | Route by symbol/action |

### Action Nodes

Action nodes execute trading operations.

| Node | Description | Use Case |
|------|-------------|----------|
| Place Order | Send order to broker | Standard orders |
| Smart Order | Position-aware order | Reversal strategies |
| Basket Order | Multiple orders | Multi-symbol strategies |
| Close Position | Close specific position | Exit trades |
| Close All | Close all positions | End-of-day square off |

### Utility Nodes

Utility nodes for supporting operations.

| Node | Description | Use Case |
|------|-------------|----------|
| Log | Write to log | Debugging |
| Telegram | Send Telegram message | Notifications |
| Delay | Wait for specified time | Throttling |
| Variable | Store/retrieve values | State management |
| HTTP Request | Call external APIs | Data fetching |

## Building Your First Flow

### Example: TradingView Alert to Order

**Step 1: Add Webhook Trigger**

1. Drag **Webhook** node to canvas
2. Configure:
   - Name: "TradingView Alert"
   - Path: `/flow/tradingview`

**Step 2: Add Place Order Action**

1. Drag **Place Order** node to canvas
2. Connect Webhook output to Order input
3. Configure order parameters:
   - Symbol: `{{webhook.symbol}}`
   - Exchange: `NSE`
   - Action: `{{webhook.action}}`
   - Quantity: `100`
   - Price Type: `MARKET`
   - Product: `MIS`

**Step 3: Add Notification**

1. Drag **Telegram** node to canvas
2. Connect Order output to Telegram input
3. Configure message:
   ```
   Order placed: {{webhook.action}} {{webhook.symbol}}
   Order ID: {{order.orderid}}
   ```

**Step 4: Save and Activate**

1. Click **Save**
2. Click **Activate** to enable the flow
3. Copy the webhook URL for TradingView

## Using Variables

### Dynamic Values from Webhook

```
Webhook Input:
{
  "symbol": "SBIN",
  "action": "BUY",
  "quantity": "100"
}

Access as:
Symbol: {{webhook.symbol}}      → SBIN
Action: {{webhook.action}}      → BUY
Quantity: {{webhook.quantity}}  → 100
```

### Node Output Variables

```
Order Node Output:
{
  "status": "success",
  "orderid": "230125000012345"
}

Access as:
Status: {{order.status}}    → success
Order ID: {{order.orderid}} → 230125000012345
```

## Advanced Flow Examples

### Example 1: Smart Order with Reversal

```
┌──────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ Webhook  │────▶│  Switch  │────▶│  Smart   │────▶│ Telegram │
│  Input   │     │ (action) │     │  Order   │     │  Notify  │
└──────────┘     └──────────┘     └──────────┘     └──────────┘
```

Configuration:
- Switch node routes by `{{webhook.action}}`
- Smart Order: position_size = `{{webhook.position_size}}`

### Example 2: Conditional Order Based on Price

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│ Webhook  │────▶│ Compare  │────▶│  Place   │
│  Input   │     │Price>100 │     │  Order   │
└──────────┘     └──────────┘     └──────────┘
                      │
                      ▼ (else)
                ┌──────────┐
                │   Log    │
                │ "Skipped"│
                └──────────┘
```

### Example 3: Multi-Symbol Basket Order

```
┌──────────┐     ┌──────────────────────────────────────────┐
│ Schedule │────▶│              For Each                    │
│  9:20 AM │     │  Symbols: SBIN, HDFCBANK, ICICIBANK     │
└──────────┘     └──────────────────────────────────────────┘
                                    │
                                    ▼
                           ┌──────────────┐
                           │ Place Order  │
                           │ for {{item}} │
                           └──────────────┘
```

## Webhook Configuration

### Making Flow Webhooks Accessible

Flow webhooks need to be accessible from the internet for external triggers (TradingView, ChartInk, etc.).

**Recommended**: Deploy OpenAlgo on an Ubuntu server with your domain using `install.sh`:
```
https://yourdomain.com/api/v1/flow/{flow-id}/webhook
```

**Alternative**: Use tunneling services **for webhooks only**:

| Service | Command |
|---------|---------|
| **ngrok** | `ngrok http 5000` |
| **devtunnel** (Microsoft) | `devtunnel host -p 5000` |
| **Cloudflare Tunnel** | `cloudflared tunnel --url http://localhost:5000` |

See [Installation Guide](../04-installation/README.md) for detailed setup.

### Webhook URL Format

```
https://your-openalgo-url/api/v1/flow/{flow-id}/webhook
```

### TradingView Alert Message

```json
{
  "symbol": "{{ticker}}",
  "action": "{{strategy.order.action}}",
  "quantity": "{{strategy.order.contracts}}",
  "position_size": "{{strategy.position_size}}"
}
```

### Testing Webhooks

1. Open flow in editor
2. Click **Test Webhook**
3. Enter sample payload
4. Click **Execute**
5. View results in right panel

## Flow Templates

OpenAlgo provides pre-built templates:

| Template | Description |
|----------|-------------|
| TradingView Basic | Simple webhook to order |
| Smart Reversal | Position-aware trading |
| Multi-Symbol Basket | Trade multiple symbols |
| Scheduled Square-off | EOD position close |
| Options Strategy | Multi-leg options |

### Using Templates

1. Click **Templates** in Flow Builder
2. Select desired template
3. Click **Use Template**
4. Customize parameters
5. Save with your name

## Debugging Flows

### View Execution History

1. Go to **Flow** → select your flow
2. Click **History** tab
3. View past executions

### Execution Details

```
┌─────────────────────────────────────────────────────────────────────────────┐
│  Execution #12345                                   2025-01-21 10:30:15     │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ✅ Webhook Input         Duration: 2ms                                     │
│     Input: {"symbol": "SBIN", "action": "BUY"}                             │
│                                                                              │
│  ✅ Place Order           Duration: 150ms                                   │
│     Output: {"status": "success", "orderid": "12345"}                       │
│                                                                              │
│  ✅ Telegram Notify       Duration: 300ms                                   │
│     Output: {"status": "sent"}                                              │
│                                                                              │
│  Total Duration: 452ms                                                      │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

### Common Issues

| Issue | Cause | Solution |
|-------|-------|----------|
| Flow not triggering | Not activated | Activate flow |
| Wrong symbol | Variable mismatch | Check variable names |
| Order failed | Invalid parameters | Verify node configuration |
| Timeout | Slow external API | Increase timeout |

## Best Practices

### 1. Test Before Activating

Always test with sample data before going live.

### 2. Use Descriptive Names

Name nodes clearly:
- "TradingView Buy Signal" not "Node 1"
- "SBIN Order" not "Place Order"

### 3. Add Error Handling

```
┌──────────┐     ┌──────────┐     ┌──────────┐
│  Order   │────▶│ If Error │────▶│  Retry   │
│  Node    │     │ Occurred │     │  Node    │
└──────────┘     └──────────┘     └──────────┘
                      │
                      ▼ (no error)
                ┌──────────┐
                │  Success │
                │  Handler │
                └──────────┘
```

### 4. Add Notifications

Always add notification nodes for important events.

### 5. Version Your Flows

- Save with version numbers
- Keep backup copies
- Document changes

## Flow Security

### Access Control

- Flows are tied to your API key
- Webhook URLs are unique per flow
- Authentication required for editing

### Webhook Security

- Use HTTPS only
- Validate incoming data
- Implement rate limiting

---

**Previous**: [20 - Python Strategies](../20-python-strategies/README.md)

**Next**: [22 - Action Center](../22-action-center/README.md)
