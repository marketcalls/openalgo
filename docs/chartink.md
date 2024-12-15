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
   - Name: A unique name for your strategy (will be prefixed with 'chartink_')
   - Type: Choose between Intraday or Positional
   - For Intraday strategies:
     - Start Time: Trading start time (default: 09:15)
     - End Time: Trading end time (default: 15:00)
     - Square Off Time: Auto square-off time (default: 15:15)

## Alert Name Keywords

The alert name in Chartink MUST include one of these keywords (not case-sensitive):

1. **BUY** - For entering long positions
   - Examples: 
     - "BUY Alert"
     - "Alert for BUY 2024-12-13"
     - "Supertrend BUY Signal"

2. **SELL** - For exiting long positions or regular selling
   - Examples:
     - "SELL Alert"
     - "Alert for SELL 2024-12-13"
     - "Supertrend SELL Signal"

3. **SHORT** - For entering short positions (selling first)
   - Examples:
     - "SHORT Alert"
     - "Alert for SHORT 2024-12-13"
     - "Supertrend SHORT Signal"

4. **COVER** - For exiting short positions (buying to cover)
   - Examples:
     - "COVER Alert"
     - "Alert for COVER 2024-12-13"
     - "Supertrend COVER Signal"

### Keyword Rules
- Keywords can appear anywhere in the alert name
- Keywords are not case-sensitive (buy/BUY/Buy all work)
- Alert will fail if no valid keyword is found
- Only one action will be taken even if multiple keywords are present

## Configuring Symbols

After creating a strategy, you need to configure the symbols to trade:

1. Click "Configure Symbols" on your strategy
2. Add symbols individually:
   - Search and select Symbol (with exchange badge)
   - Select Exchange (NSE by default)
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
2. Click "Create Alert" button
3. Enter an alert name that includes one of the action keywords
4. Find the "Webhook url(optional)" field
5. Copy and paste your strategy's webhook URL:
   ```
   https://your-openalgo-domain/chartink/webhook/<webhook-id>
   ```
6. Configure other alert settings as needed
7. Click "Save alert" button

## How It Works

1. When your scanner conditions are met, Chartink sends an alert to your webhook URL
2. OpenAlgo receives the alert and:
   - Validates the webhook ID
   - Checks if strategy is active
   - Validates the alert name for action keyword
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
    "action": "BUY/SELL/SHORT/COVER",
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
- Toggle status from strategy view

### Symbol Management

- Add/remove symbols any time
- Update quantities as needed
- View all configured symbols with exchange badges
- Bulk import for multiple symbols
- Delete confirmation for symbol removal

### Time Controls

For intraday strategies:
- Start Time: When to start accepting alerts
- End Time: When to stop accepting alerts
- Square Off Time: When to close all positions

## Best Practices

1. Test your strategy with small quantities first
2. Use proper stop-losses in your Chartink scanner
3. Monitor the first few alerts
4. Keep your webhook URL private
5. Include action keyword in scan name
6. For intraday strategies:
   - Ensure orders are placed during trading hours
   - Monitor square-off at configured time

## Error Handling

OpenAlgo handles various error scenarios:
- Invalid webhook IDs
- Missing action keywords in alert names
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
6. Alert name must contain valid action keyword

## Security

- Each strategy has a unique webhook ID
- API keys are required for order placement
- Session validation for web interface
- Secure storage of credentials
- Rate limiting on endpoints
- Confirmation dialogs for deletions

## Troubleshooting

1. Check strategy status (active/inactive)
2. Verify trading hours for intraday
3. Confirm symbol configurations
4. Check alert name contains valid keyword
5. Check API analyzer for errors
6. Verify webhook URL in Chartink

## Support

For issues or questions:
1. Check the logs in API analyzer
2. Review error messages
3. Contact support with:
   - Strategy ID
   - Error details
   - Time of occurrence
   - Relevant logs
   - Alert name and webhook URL used
