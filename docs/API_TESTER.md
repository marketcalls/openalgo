# API Tester Documentation

## Overview

The API Tester is a web-based interface for testing OpenAlgo REST API endpoints. It provides an intuitive UI to explore, test, and debug all available API endpoints without needing external tools like Postman or Bruno.

## Features

- **Comprehensive Endpoint Library**: Pre-configured with all OpenAlgo API endpoints
- **Organized Categories**: Endpoints grouped by functionality (Account, Orders, Data, Utilities)
- **Live Testing**: Send requests and view responses in real-time
- **API Key Management**: Save and reuse your API key across sessions
- **Request Customization**: Modify request body, parameters, and headers
- **Response Viewer**: Formatted JSON response with status codes and timing
- **Search Functionality**: Quickly find endpoints by name or path
- **Copy to Clipboard**: Easy copying of responses for further analysis

## Access

Navigate to: `http://your-host:port/api-tester`

**Note**: You must be logged in to access the API Tester.

## Usage

### 1. API Key (Automatic)

Your API key is automatically loaded from your user session:
- The API key is fetched when you open the API Tester
- It's displayed in a read-only field at the top
- Click "Copy" to copy it to clipboard
- Click "Manage" to generate or update your API key
- The API key is automatically populated in all request bodies

### 2. Select an Endpoint

Browse the left sidebar to find the endpoint you want to test:

- **Account**: Funds, orderbook, tradebook, positionbook, holdings, analyzer
- **Orders**: Place, modify, cancel orders, basket orders, split orders
- **Data**: Quotes, depth, history, search, symbols, expiry dates
- **Utilities**: Ping, instruments, margin calculator

Click on any endpoint to load its configuration.

### 3. Customize the Request

#### Body Tab (POST/PUT requests)
- Edit the JSON request body
- API key is pre-filled if saved
- Modify parameters as needed

#### Params Tab (GET requests)
- Add/remove query parameters
- Each parameter has a key-value pair
- Click "+" to add new parameters

#### Headers Tab
- View request headers
- Content-Type is set to application/json by default

### 4. Send the Request

1. Click the "Send Request" button
2. Wait for the response (loading indicator will show)
3. View the response in the Response panel below

### 5. Analyze the Response

The response panel shows:
- **Status Code**: Color-coded (green for success, red for errors)
- **Response Time**: Request duration in milliseconds
- **Response Body**: Formatted JSON with syntax highlighting
- **Copy Button**: Copy the entire response to clipboard

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

1. **Automatic API Key**: Your API key is automatically loaded from your session - no manual entry needed!
2. **Search Feature**: Use the search box to quickly find endpoints
3. **Copy Responses**: Use the Copy button to save responses for documentation
4. **Copy API Key**: Click the Copy button next to the API key to copy it to clipboard
5. **Clear Button**: Reset the request panel to start fresh
6. **Status Codes**: 
   - 200-299: Success (green)
   - 400-499: Client errors (red)
   - 500-599: Server errors (red)

## Integration with Collections

The API Tester is built using the same endpoint definitions as:
- Postman Collection (`collections/postman/openalgo.postman_collection.json`)
- Bruno Collection (`collections/openalgo/*.bru`)

This ensures consistency across all testing tools.

## Troubleshooting

### "Authentication required" error
- Make sure you're logged into OpenAlgo
- Navigate to `/api-tester` while logged in

### No API key shown
- Click "Manage" to generate a new API key
- Navigate to `/apikey` to create your first API key
- Refresh the page after generating a key

### Invalid API key errors
- Click "Manage" to verify or regenerate your API key
- Ensure your API key is active and not expired

### Network errors
- Check if the OpenAlgo server is running
- Verify the URL in the request field is correct
- Check browser console for detailed error messages

## Security Notes

- API keys are automatically fetched from your secure session
- API keys are stored encrypted in the database
- Never share your API key with others
- The API Tester requires authentication (login) to access
- API keys are displayed in read-only mode for security

## Future Enhancements

Planned features:
- Request history
- Save favorite endpoints
- Export/import test collections
- Environment variables support
- Bulk testing capabilities
