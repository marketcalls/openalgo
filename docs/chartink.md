# Chartink Integration Guide

This guide explains how to use OpenAlgo's Chartink integration to automate your trading strategies.

## Table of Contents
- [Overview](#overview)
- [Prerequisites](#prerequisites)
- [Creating a Strategy](#creating-a-strategy)
- [Configuring Symbols](#configuring-symbols)
- [Setting Up Chartink](#setting-up-chartink)
- [Trading Times](#trading-times)
- [Scanner Names](#scanner-names)
- [Webhook Format](#webhook-format)
- [Troubleshooting](#troubleshooting)

## Overview

The Chartink integration allows you to:
- Receive alerts from Chartink scanners
- Automatically place orders based on alerts
- Configure multiple strategies with different symbols
- Control trading times for intraday strategies
- Support both NSE and BSE symbols

## Prerequisites

1. OpenAlgo Account Setup:
   - Login to OpenAlgo
   - Create API Key (Required for orders)
   - Note: Keep your API key secure

2. Chartink Premium Account:
   - Required for webhook alerts
   - Access to real-time data

## Creating a Strategy

1. Navigate to Chartink section in OpenAlgo
2. Click "New Strategy"
3. Fill in the details:
   ```
   Strategy Name: My First Strategy
   Is Intraday: Yes/No
   Trading Times (IST):
   - Signal Start: 09:30:00
   - Trading End: 15:00:00
   - Square-off: 15:15:00
   ```
4. Click "Create Strategy"
5. Copy the generated webhook URL

## Configuring Symbols

### Single Symbol Add
1. Click "Configure Symbols" on your strategy
2. Select exchange (NSE/BSE)
3. Search and select symbol
4. Set quantity and product type:
   ```
   Symbol: RELIANCE
   Exchange: NSE
   Quantity: 10
   Product Type: MIS/CNC
   ```

### Bulk Symbol Add
1. Use the bulk add textarea
2. Format: SYMBOL,EXCHANGE,QUANTITY,PRODUCT
3. One symbol per line:
   ```
   RELIANCE,NSE,10,MIS
   HDFCBANK,NSE,5,CNC
   TATASTEEL,BSE,15,MIS
   ```

## Setting Up Chartink

### Creating Scanners

1. Long Entry Scanner:
   ```
   // Example: Moving Average Crossover
   close > sma(close,20) and close[1] <= sma(close,20)[1]
   Name: "MA Crossover BUY"  // Must end with BUY
   ```

2. Long Exit Scanner:
   ```
   // Example: Moving Average Crossover Exit
   close < sma(close,20) and close[1] >= sma(close,20)[1]
   Name: "MA Crossover SELL"  // Must end with SELL
   ```

3. Short Entry Scanner:
   ```
   // Example: RSI Overbought
   rsi(14) crosses above 70
   Name: "RSI Overbought SHORT"  // Must end with SHORT
   ```

4. Short Exit Scanner:
   ```
   // Example: RSI Oversold
   rsi(14) crosses below 30
   Name: "RSI Oversold COVER"  // Must end with COVER
   ```

### Setting Up Alerts

1. Click "Create Alert" on your scanner
2. Set Alert Options:
   - Frequency: 1 minute (recommended)
   - Add webhook URL from OpenAlgo
   - Enable during market hours

## Trading Times

For intraday strategies, the system enforces these time controls:

1. Signal Start Time (e.g., 09:30:00)
   - No orders before this time
   - Allows market to stabilize
   - Default: 09:30:00

2. Trading End Time (e.g., 15:00:00)
   - No new positions after this time
   - Existing positions remain open
   - Default: 15:00:00

3. Square-off Time (e.g., 15:15:00)
   - All positions automatically closed
   - Uses smart orders for closure
   - Default: 15:15:00

## Scanner Names

The system uses scanner name suffixes to determine the action:

| Suffix | Action | Description | Example Name |
|--------|--------|-------------|--------------|
| BUY | Long Entry | Places regular buy order | "SMA Crossover BUY" |
| SELL | Long Exit | Closes long positions | "RSI Exit SELL" |
| SHORT | Short Entry | Places regular sell order | "Breakdown SHORT" |
| COVER | Short Exit | Closes short positions | "Reversal COVER" |

## Webhook Format

When Chartink sends alerts, it uses this format:

```json
{
    "stocks": "RELIANCE,SBIN",
    "trigger_prices": "2500.00,550.75",
    "triggered_at": "14:30:00",
    "scan_name": "MA Crossover BUY",
    "scan_url": "ma-crossover",
    "alert_name": "Alert for MA Crossover",
    "webhook_url": "your-webhook-url"
}
```

Important Notes:
- The scan_name suffix determines the action
- Only configured symbols will be processed
- Orders respect trading time controls
- Uses your API key for authentication

## Troubleshooting

### Common Issues

1. "API key not found" Error
   - Ensure you've created an API key in OpenAlgo
   - Check if API key is active
   - Create a new API key if needed

2. Orders Not Executing
   - Check if within trading hours
   - Verify symbol is configured
   - Ensure scanner name has correct suffix
   - Check logs for specific errors

3. Symbol Not Found
   - Verify symbol exists in selected exchange
   - Check symbol spelling
   - Ensure exchange is correct (NSE/BSE)

4. Webhook Not Working
   - Verify webhook URL is correct
   - Check if strategy is active
   - Ensure Chartink premium subscription is active

### Best Practices

1. Testing New Strategies
   - Start with small quantities
   - Test during market hours
   - Monitor first few trades
   - Check logs for any issues

2. Symbol Configuration
   - Use correct exchange
   - Verify quantities
   - Double-check product types
   - Test with one symbol first

3. Time Settings
   - Allow buffer after market open
   - Set square-off before market close
   - Consider market liquidity
   - Test time-based controls

4. Scanner Setup
   - Use clear naming convention
   - Test conditions thoroughly
   - Monitor alert frequency
   - Verify webhook delivery

### Logs and Monitoring

1. Check OpenAlgo Logs for:
   - Webhook receipts
   - Order execution
   - Error messages
   - Time validations

2. Monitor Chartink for:
   - Alert triggers
   - Webhook delivery
   - Scanner conditions
   - Real-time updates

For additional support or questions, refer to the OpenAlgo documentation or contact support.
