# API Playground Documentation

## Overview

The API Playground is a web-based interface for testing OpenAlgo REST API endpoints. It provides an intuitive UI to explore, test, and debug all available API endpoints without needing external tools like Postman or Bruno.

## Features

- **Three-Panel Layout**: Sidebar, request editor, and response viewer side-by-side
- **Comprehensive Endpoint Library**: Pre-configured with all OpenAlgo API endpoints loaded from Bruno collection
- **Organized Categories**: Endpoints grouped by functionality (Account, Orders, Data, Utilities)
- **Live Testing**: Send requests and view responses in real-time
- **Auto-Populated API Key**: Your API key is automatically injected into request bodies
- **Line Numbers**: Both request body and response display line numbers for easy reference
- **Prettify JSON**: Format and beautify JSON request bodies with one click
- **Response Metrics**: View status code, response time, and response size
- **Copy Options**: Copy response or generate cURL command
- **Search Functionality**: Quickly find endpoints by name

## Access

Navigate to: `http://your-host:port/playground`

**Note**: You must be logged in to access the Playground.

## Usage

### 1. API Key (Automatic)

Your API key is automatically managed:
- The API key is fetched when you open the Playground
- It's automatically injected into all request bodies containing an `apikey` field
- No manual copy/paste required

### 2. Select an Endpoint

Browse the left sidebar to find the endpoint you want to test:

- **Account**: Funds, orderbook, tradebook, positionbook, holdings
- **Orders**: Place, modify, cancel orders, basket orders, split orders
- **Data**: Quotes, depth, history, search, symbols, expiry dates
- **Utilities**: Ping, instruments, margin calculator

Click on any endpoint to load its configuration in the request panel.

### 3. Customize the Request

The middle panel contains two tabs:

#### Body Tab
- Edit the JSON request body with line numbers
- API key is automatically populated
- Click **Prettify** to format JSON
- Modify parameters as needed

#### Headers Tab
- Shows request headers
- Content-Type: application/json (default)

### 4. Send the Request

1. Review the URL and method in the URL bar
2. Click the **Send** button (or use the arrow icon)
3. View the response in the right panel

### 5. Analyze the Response

The right panel shows:
- **Status Code**: Color-coded (green for 2xx, red for errors)
- **Response Time**: Request duration in milliseconds
- **Response Size**: Size of the response in bytes/KB
- **Response Body**: Formatted JSON with line numbers
- **Copy Response**: Copy the JSON response
- **Copy cURL**: Generate and copy cURL command

## Endpoint Categories

### Account Endpoints

- **Analyzer Status**: Check if analyzer mode is enabled
- **Analyzer Toggle**: Enable/disable analyzer mode
- **Funds**: Get account balance and margin details
- **Orderbook**: View all orders
- **Tradebook**: View executed trades
- **Positionbook**: View open positions
- **Holdings**: View long-term holdings

### Order Endpoints

- **Place Order**: Place a single order
- **Place Smart Order**: Place order with position sizing
- **Basket Order**: Place multiple orders at once
- **Split Order**: Split large orders into smaller chunks
- **Modify Order**: Modify existing order parameters
- **Cancel Order**: Cancel a specific order
- **Cancel All Orders**: Cancel all pending orders
- **Close Position**: Close all positions for a strategy
- **Order Status**: Get status of a specific order
- **Open Position**: Check open position for a symbol

### Data Endpoints

- **Quotes**: Get real-time quotes for a symbol
- **Depth**: Get market depth (order book)
- **History**: Get historical OHLCV data
- **Intervals**: Get supported time intervals
- **Symbol**: Get symbol details
- **Search**: Search for symbols
- **Expiry**: Get expiry dates for derivatives
- **Option Symbol**: Get option chain symbols
- **Option Greeks**: Calculate option Greeks
- **Ticker**: Get ticker data (GET request)

### Utility Endpoints

- **Ping**: Test API connectivity
- **Instruments**: Download instrument master files
- **Margin Calculator**: Calculate margin requirements

## Tips

1. **Automatic API Key**: Your API key is automatically injected into requests - no manual entry needed
2. **Search Feature**: Use the search box to quickly find endpoints by name
3. **Prettify JSON**: Click the Prettify button to format messy JSON in the request body
4. **Line Numbers**: Use line numbers to reference specific parts of requests/responses
5. **Copy cURL**: Generate cURL commands to replicate requests in terminal
6. **Status Codes**:
   - 200-299: Success (green)
   - 400-499: Client errors (red)
   - 500-599: Server errors (red)

## Integration with Collections

The API Playground is built using the same endpoint definitions as:
- Postman Collection (`collections/postman/openalgo.postman_collection.json`)
- Bruno Collection (`collections/openalgo/*.bru`)

This ensures consistency across all testing tools.

## Troubleshooting

### "Authentication required" error
- Make sure you're logged into OpenAlgo
- Navigate to `/playground` while logged in

### API key not being injected
- Navigate to `/apikey` to generate your API key
- Refresh the Playground page after generating a key
- Ensure the request body contains an `apikey` field

### Invalid API key errors
- Navigate to `/apikey` to verify or regenerate your API key
- Ensure your API key is active and not expired

### Network errors
- Check if the OpenAlgo server is running
- Verify the URL in the request field is correct
- Check browser console for detailed error messages

## Security Notes

- API keys are automatically fetched from your secure session
- API keys are stored encrypted in the database
- Never share your API key with others
- The API Playground requires authentication (login) to access
- API keys are displayed in read-only mode for security

## Future Enhancements

Planned features:
- Request history and saved responses
- Favorite/starred endpoints
- Environment variables support
- WebSocket endpoint testing
- Response diff comparison
