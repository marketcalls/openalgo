# Chartink Integration

OpenAlgo supports integration with Chartink for automated trading based on scanner alerts. This integration allows you to:
- Create and manage trading strategies
- Configure symbols with quantities and product types
- Handle intraday and positional strategies
- Automate order placement based on Chartink alerts
- Auto square-off positions for intraday strategies

## Setting Up a Strategy

1. Go to the Chartink section in OpenAlgo
2. Click "New Strategy" button
3. Fill in the strategy details:
   - Name: A unique name for your strategy
   - Type: Choose between Intraday or Positional
   - For Intraday strategies:
     - Start Time: Trading start time (default: 09:15)
     - End Time: Trading end time (default: 15:15)
     - Square Off Time: Auto square-off time (default: 15:15)

## Configuring Symbols

After creating a strategy, you need to configure the symbols to trade:

1. Click "Configure Symbols" on your strategy
2. Add symbols individually:
   - Select Exchange (NSE/BSE)
   - Search and select Symbol
   - Enter Quantity
   - Select Product Type (MIS for Intraday, CNC for Positional)
3. Or bulk add symbols using CSV format:
   ```
   RELIANCE,NSE,10,MIS
   HDFCBANK,NSE,5,CNC
   TATASTEEL,BSE,15,MIS
   ```

## Setting Up Chartink Alert

1. Create your scanner in Chartink
2. Set up an alert for your scanner
3. In the webhook URL field, paste your strategy's webhook URL:
   ```
   https://your-openalgo-domain/chartink/webhook/<webhook-id>
   ```

## How It Works

1. When your scanner conditions are met, Chartink sends an alert to your webhook URL
2. OpenAlgo receives the alert and:
   - Validates the webhook ID
   - Checks if strategy is active
   - For intraday strategies, checks if within trading hours
   - Matches symbols from alert with your configured symbols
   - Places orders according to your configuration

### Intraday Trading

For intraday strategies:
- Orders are only placed between Start Time and End Time
- At Square Off Time, all open positions are automatically closed
- Uses MIS product type for better leverage

### Positional Trading

For positional strategies:
- Orders can be placed any time during market hours
- No automatic square-off
- Uses CNC product type for delivery trades

## Order Placement

When a Chartink alert is received:
- For new positions:
  ```json
  {
    "apikey": "your-api-key",
    "strategy": "Strategy Name",
    "symbol": "SYMBOL",
    "exchange": "NSE/BSE",
    "action": "BUY",
    "product": "MIS/CNC",
    "pricetype": "MARKET",
    "quantity": "configured-quantity"
  }
  ```

- For square-off (intraday):
  ```json
  {
    "apikey": "your-api-key",
    "strategy": "Strategy Name",
    "symbol": "SYMBOL",
    "exchange": "NSE/BSE",
    "action": "SELL",
    "product": "MIS",
    "pricetype": "MARKET",
    "quantity": "0",
    "position_size": "0"
  }
  ```

## Strategy Management

### Activation/Deactivation

- Active strategies process incoming alerts
- Inactive strategies ignore alerts
- Toggle status from strategy view or list

### Symbol Management

- Add/remove symbols any time
- Update quantities as needed
- View all configured symbols
- Bulk import for multiple symbols

### Time Controls

For intraday strategies:
- Start Time: When to start accepting alerts
- End Time: When to stop accepting alerts
- Square Off Time: When to close all positions

## Best Practices

1. Test your strategy with small quantities first
2. Use proper stop-losses in your Chartink scanner
3. Monitor the strategy's performance
4. Keep track of order logs
5. Regularly verify symbol configurations

## Error Handling

OpenAlgo handles various error scenarios:
- Invalid webhook IDs
- Inactive strategies
- Outside trading hours
- Symbol mismatches
- Order placement failures

All errors are logged and can be viewed in the API analyzer.

## Limitations

1. Only supports NSE and BSE exchanges
2. Intraday square-off is all-or-nothing
3. No partial position closures
4. No modification of existing orders
5. Market orders only

## Security

- Each strategy has a unique webhook ID
- API keys are required for order placement
- Session validation for web interface
- Secure storage of credentials
- Rate limiting on endpoints

## Troubleshooting

1. Check strategy status (active/inactive)
2. Verify trading hours for intraday
3. Confirm symbol configurations
4. Check API analyzer for errors
5. Verify webhook URL in Chartink

## Support

For issues or questions:
1. Check the logs in API analyzer
2. Review error messages
3. Contact support with:
   - Strategy ID
   - Error details
   - Time of occurrence
   - Relevant logs
