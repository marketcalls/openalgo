# 01 - What is OpenAlgo?

## Introduction

**OpenAlgo** is a free, open-source platform that lets you automate your stock market trading. Think of it as a bridge between your trading ideas and your broker - it takes signals from various sources (like TradingView charts, Amibroker strategies, or even AI assistants) and automatically places orders with your broker.

## The Problem OpenAlgo Solves

### Before OpenAlgo

```
You see a buy signal on TradingView
        ↓
You manually open your broker app
        ↓
You search for the stock
        ↓
You enter quantity and price
        ↓
You click buy
        ↓
Signal is 2 minutes old by now!
```

### With OpenAlgo

```
TradingView sends a signal
        ↓
OpenAlgo receives it instantly
        ↓
Order placed with your broker
        ↓
All in under 1 second!
```

## Who is OpenAlgo For?

### Retail Traders
- Tired of manually placing orders
- Want to trade multiple stocks simultaneously
- Need faster execution than manual trading

### Technical Traders
- Use TradingView for charting and alerts
- Use Amibroker for backtesting strategies
- Want to automate their proven strategies

### Algo Enthusiasts
- Want to learn algorithmic trading
- Need a platform to test strategies safely
- Looking for a free alternative to expensive platforms

### Investment Advisors
- Need order approval workflow
- Require audit trails for compliance
- Want semi-automated trading

## Key Benefits

### 1. One Platform, 24+ Brokers
Connect to any of the 24+ supported Indian brokers:
- Zerodha, Angel One, Dhan, Fyers
- 5paisa, Upstox, Kotak Neo
- And many more...

**Benefit**: Switch brokers without changing your strategy code!

### 2. Connect Any Signal Source
- **TradingView**: Pine Script alerts → automatic orders
- **Amibroker**: AFL strategies → automatic orders
- **ChartInk**: Scanner alerts → automatic orders
- **Python**: Your own scripts → automatic orders
- **AI Assistants**: Natural language → automatic orders

### 3. Test Before You Trade
**Analyzer Mode** gives you ₹1 Crore sandbox capital to:
- Test your strategies with real market data
- Learn without risking real money
- Validate before going live

### 4. Your Data Stays Yours
- Runs on YOUR computer/server
- No data sent to external servers
- Complete privacy and control

### 5. Completely Free
- No subscription fees
- No hidden charges
- Open source (you can verify the code)

## How OpenAlgo Works

```
┌─────────────────────────────────────────────────────────────────┐
│                    Your Trading Ecosystem                        │
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ TradingView  │  │  Amibroker   │  │   Python     │          │
│  │   Charts     │  │  Strategies  │  │   Scripts    │          │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘          │
│         │                 │                 │                    │
│         │    Webhooks     │    API Calls    │                    │
│         └────────────────┬┴─────────────────┘                    │
│                          │                                       │
│                          ▼                                       │
│         ┌────────────────────────────────────┐                  │
│         │           OpenAlgo                  │                  │
│         │                                     │                  │
│         │  • Receives signals                │                  │
│         │  • Validates orders                │                  │
│         │  • Routes to broker                │                  │
│         │  • Tracks positions                │                  │
│         │  • Sends notifications             │                  │
│         └────────────────┬───────────────────┘                  │
│                          │                                       │
│                          ▼                                       │
│         ┌────────────────────────────────────┐                  │
│         │        Your Broker Account          │                  │
│         │        (Zerodha, Angel, etc.)       │                  │
│         └────────────────────────────────────┘                  │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Real-World Example

**Scenario**: You have a moving average crossover strategy on TradingView.

**Traditional Way**:
1. You watch charts all day
2. When MA crosses, you get an alert
3. You open your broker app
4. You place the order manually
5. You repeat for every signal

**With OpenAlgo**:
1. Set up your TradingView alert once
2. Go about your day
3. OpenAlgo places orders automatically
4. You get Telegram notifications
5. Check your P&L at end of day

## What OpenAlgo is NOT

Let's be clear about what OpenAlgo doesn't do:

❌ **Not a get-rich-quick scheme** - It's a tool, not a magic money maker

❌ **Not a strategy provider** - You need your own trading ideas

❌ **Not financial advice** - You're responsible for your trading decisions

❌ **Not a black box** - It's open source; you can see exactly what it does

## Getting Started

Ready to begin? Here's your path:

1. **Next**: Learn [Key Concepts](../02-key-concepts/README.md)
2. Check [System Requirements](../03-system-requirements/README.md)
3. Follow [Installation Guide](../04-installation/README.md)
4. Complete [First-Time Setup](../05-first-time-setup/README.md)
5. Place your [First Order](../10-placing-first-order/README.md)!

## Summary

| Aspect | OpenAlgo |
|--------|----------|
| Cost | Free (Open Source) |
| Brokers | 24+ Indian brokers |
| Signal Sources | TradingView, Amibroker, Python, AI, etc. |
| Sandbox Testing | Yes (₹1 Crore sandbox capital) |
| Data Privacy | 100% - runs on your machine |
| Skill Required | Basic trading knowledge |

---

**Next**: [02 - Key Concepts](../02-key-concepts/README.md) - Understand the terminology before diving in.
