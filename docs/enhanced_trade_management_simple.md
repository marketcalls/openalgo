# Enhanced Trade Management - Simple Guide

## 🎯 What We're Building

A comprehensive trade management system that automatically monitors your trades and manages risk at two levels:
1. **Individual Trade Level** - Each position has its own stop-loss and target
2. **Portfolio Level** - Your entire strategy has overall risk limits

## 📊 Key Features

### **Individual Trade Management**
- **Stop Loss**: Automatically exit if price drops X% from entry
- **Target**: Automatically exit if price rises X% from entry  
- **Trailing Stop Loss**: Stop loss that moves up with profitable trades
- **Real-time Monitoring**: Live price tracking via WebSocket

### **Portfolio Management (Strategy Level)**
- **Portfolio Stop Loss**: Close ALL positions if total strategy loss hits limit
- **Portfolio Target**: Close ALL positions if total strategy profit hits target
- **Portfolio Trailing SL**: Protect profits across all positions in strategy
- **Fund Allocation**: Allocate specific capital to each strategy

### **Position Sizing**
- **Fixed Quantity**: Always trade X shares (e.g., 100 shares)
- **Fixed Value**: Always trade ₹X worth (e.g., ₹50,000 per trade)
- **Percentage**: Use X% of allocated funds per trade

## 🔧 How It Works

### Setup Example:
```
Strategy: "Nifty Momentum"
Allocated Funds: ₹5,00,000
Position Size: 10% per trade (₹50,000)

Individual Settings:
- Stop Loss: 1.5% below entry price
- Target: 3% above entry price
- Trailing SL: 0.5% from highest price

Portfolio Settings:
- Portfolio SL: -₹10,000 (close all if total loss hits this)
- Portfolio Target: +₹15,000 (close all if total profit hits this)
- Portfolio Trailing SL: ₹5,000 from peak P&L
```

### Live Example:
```
10:30 AM: Buy 20 RELIANCE @ ₹2,500 (₹50,000 trade)
- Individual SL: ₹2,462.50 (1.5% below ₹2,500)
- Individual Target: ₹2,575 (3% above ₹2,500)

10:45 AM: Buy 15 TCS @ ₹3,333 (₹50,000 trade)
- Individual SL: ₹3,283.50
- Individual Target: ₹3,433

Portfolio Status:
- Total Invested: ₹1,00,000
- Portfolio P&L: ₹0
- Portfolio SL: -₹10,000 (will close both positions)
- Portfolio Target: +₹15,000 (will close both positions)
```

### What Happens During Trading:
```
11:30 AM: Prices move favorably
RELIANCE: ₹2,580 (+₹1,600 profit)
TCS: ₹3,380 (+₹705 profit)
Portfolio P&L: +₹2,305

System Actions:
- RELIANCE Trailing SL moves to ₹2,567.50
- TCS Trailing SL moves to ₹3,363.50
- Portfolio Trailing SL activates at -₹2,695 (₹2,305 - ₹5,000)

12:00 PM: RELIANCE drops to ₹2,460
- Individual SL triggered for RELIANCE only
- TCS position continues
- Portfolio P&L: +₹705 (only TCS remaining)
```

## 📱 What You'll See in the UI

### Strategy Configuration Page:
```
Individual Trade Risk:
├── Stop Loss: [✓] 1.5% below entry
├── Target: [✓] 3.0% above entry
└── Trailing SL: [✓] 0.5% from peak

Portfolio Risk:
├── Portfolio SL: [✓] ₹10,000 loss
├── Portfolio Target: [✓] ₹15,000 profit
└── Portfolio Trailing: [✓] ₹5,000 from peak

Fund Allocation:
├── Allocated Funds: ₹5,00,000
├── Position Size: 10% per trade
├── Max Positions: 5
└── Daily Loss Limit: ₹20,000
```

### Trade Monitoring Dashboard:
```
Strategy: Nifty Momentum
Portfolio P&L: +₹2,305 (0.46%)
Active Trades: 2 | Allocated: ₹5,00,000
Portfolio SL: -₹10,000 | Target: +₹15,000

Individual Trades:
┌─────────┬─────┬───────┬─────┬──────┬─────────┬─────────┐
│ Symbol  │ Qty │ Entry │ LTP │ P&L  │ Stop SL │ Target  │
├─────────┼─────┼───────┼─────┼──────┼─────────┼─────────┤
│ TCS     │ 15  │ 3333  │3380 │ +705 │ 3363.50 │ 3433    │
│ INFY    │ 35  │ 1429  │1435 │ +210 │ 1429    │ 1472    │
└─────────┴─────┴───────┴─────┴──────┴─────────┴─────────┘
```

### Real-time Alerts:
```
✅ "TCS Individual Target Hit at ₹3433 - Profit: ₹1,500"
⚠️ "RELIANCE Individual SL Hit at ₹2462 - Loss: ₹750"
🎯 "Nifty Momentum Portfolio Target Hit - All positions closed - Total Profit: ₹15,250"
📈 "Portfolio Trailing SL updated to +₹8,000"
```

## 🛡️ Safety Features

### Strategy Deletion Protection:
```
⚠️ Warning: 3 Active Trades Found!
┌─────────┬─────┬─────────┬──────┐
│ Symbol  │ P&L │ SL Set  │Status│
├─────────┼─────┼─────────┼──────┤
│ RELIANCE│ +800│ ₹2,462  │ACTIVE│
│ TCS     │ -200│ ₹3,152  │ACTIVE│
│ INFY    │ +375│ ₹1,379  │ACTIVE│
└─────────┴─────┴─────────┴──────┘

Choose Action:
○ Close all positions immediately
○ Stop monitoring (keep positions open)
● Cancel deletion
```

### Application Restart Recovery:
- All trade states saved to database
- Automatic recovery on restart
- WebSocket reconnection
- Position validation against broker

## 🚀 Key Benefits

1. **Set and Forget**: No need to watch positions constantly
2. **Dual Protection**: Individual + Portfolio level risk management
3. **Capital Allocation**: Professional fund management per strategy
4. **Real-time Monitoring**: Live updates via WebSocket
5. **Complete Automation**: Automatic exits when conditions met
6. **Audit Trail**: Every action logged for analysis
7. **Crash Recovery**: System restarts don't lose monitoring state

## 💡 Use Cases

**Intraday Trader**: Set 1% SL, 2% target per trade, ₹5,000 portfolio SL
**Swing Trader**: Set 3% SL, 8% target per trade, 5% portfolio trailing SL  
**Options Trader**: Fixed ₹10,000 per trade, portfolio target ₹50,000
**Multi-Strategy**: Different funds and risk levels per strategy

This system transforms OpenAlgo into a professional-grade trading platform with institutional-level risk management capabilities, all while maintaining its user-friendly interface.