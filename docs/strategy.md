# Strategy Module Documentation

The Strategy Module is a core component of the OpenAlgo platform that enables users to create, manage, and execute automated trading strategies through webhooks. This document provides a comprehensive overview of the strategy module's features, architecture, and usage.

## Overview

The Strategy Module allows traders to:
- Create and manage trading strategies
- Configure multiple symbols per strategy
- Set up intraday and positional trading modes
- Control trading hours and auto square-off times
- Integrate with trading platforms via webhooks
- Execute trades based on external signals

## Core Components

### 1. Strategy Blueprint (`strategy.py`)

The strategy blueprint handles all HTTP routes and business logic for strategy management:

- **Route Management**: Handles all `/strategy/*` endpoints
- **Order Processing**: Manages order queues with rate limiting
- **Time Management**: Handles trading hours and square-off scheduling
- **Webhook Processing**: Processes incoming trading signals

### 2. Database Models (`strategy_db.py`)

Two main database models manage strategy data:

#### Strategy Model
- `id`: Unique identifier
- `name`: Strategy name
- `webhook_id`: Unique UUID for webhook identification
- `user_id`: Associated user
- `platform`: Trading platform (e.g., tradingview)
- `is_active`: Strategy activation status
- `is_intraday`: Intraday/Positional mode
- `trading_mode`: LONG/SHORT/BOTH
- `start_time`: Trading start time
- `end_time`: Trading end time
- `squareoff_time`: Auto square-off time

#### StrategySymbolMapping Model
- Links symbols to strategies
- Configures trading parameters per symbol
- Manages exchange and product type settings

## Features

### 1. Strategy Management
- Create new strategies
- Toggle strategy activation
- Delete strategies
- View strategy details
- Configure trading times

### 2. Symbol Configuration
- Add/remove symbols to strategies
- Configure quantity per symbol
- Set product type (MIS/CNC/NRML)
- Choose exchange

### 3. Trading Controls
- Intraday/Positional mode selection
- Trading direction control (LONG/SHORT/BOTH)
- Trading hours configuration
- Automatic square-off scheduling

### 4. Webhook Integration

The module processes webhook signals from trading platforms with the following format:
```
[BASE_URL]/strategy/webhook/[WEBHOOK_ID]
```

Signal Keywords:
- `BUY`: Long entry
- `SELL`: Long exit
- `SHORT`: Short entry
- `COVER`: Short cover

## Rate Limiting

The module implements sophisticated rate limiting:
- Regular orders: Max 10 orders per second
- Smart orders: 1 order per second
- Separate queues for different order types

## Security Features

- Session validation for all routes
- Unique webhook IDs per strategy
- User-specific strategy isolation
- API key management for trading platforms

## Best Practices

1. **Strategy Naming**:
   - Use descriptive names
   - Include relevant indicators/timeframes
   - Follow naming conventions

2. **Symbol Configuration**:
   - Verify exchange and product type compatibility
   - Set appropriate position sizes
   - Test with small quantities first

3. **Trading Hours**:
   - Set conservative trading hours
   - Allow buffer for square-off
   - Consider market timing restrictions

4. **Webhook Setup**:
   - Use secure webhook URLs
   - Include proper signal keywords
   - Test signals before live trading

## Error Handling

The module implements comprehensive error handling:
- Database transaction management
- Order placement retries
- Invalid signal filtering
- Rate limit compliance

## Integration Points

1. **Trading Platforms**:
   - TradingView
   - ChartInk
   - Custom platforms (via webhook API)

2. **Broker Integration**:
   - Supports multiple Indian brokers
   - Product type validation per exchange
   - Order type compatibility checks

## Performance Considerations

- Efficient order queue processing
- Rate limit compliance
- Database connection pooling
- Background task scheduling

## TradingView Webhook Configuration

### Setting Up TradingView Alerts

1. **Create Alert in TradingView**:
   - Go to TradingView Chart
   - Click "Alerts" icon
   - Select "Create Alert"

2. **Alert Settings**:
   - Name: Include signal keyword (BUY/SELL/SHORT/COVER)
   - Condition: Set your trading condition
   - Message: Configure webhook message (see format below)
   - Webhook URL: `[BASE_URL]/strategy/webhook/[YOUR_WEBHOOK_ID]`

### Webhook Message Formats

The webhook message format varies based on the trading mode of your strategy:

#### 1. Long Only Mode
```json
{
    "symbol": "RELIANCE",
    "action": "BUY"  // or "SELL"
}
```

#### 2. Short Only Mode
```json
{
    "symbol": "NIFTY",
    "action": "SELL"  // or "BUY"
}
```

#### 3. Both Modes (Long & Short)
```json
{
    "symbol": "TATASTEEL",
    "action": "BUY",  // BUY/SELL
    "position_size": "1"  // Required for both modes
}
```

### TradingView Alert Message Setup

1. **Alert Message Format for Long/Short Only Mode**:
```
{
    "symbol": "openalgo_symbol",
    "action": "{{strategy.order.action}}"
}
```

2. **Alert Message Format for Both Modes**:
```
{
    "symbol": "openalgo_symbol",
    "action": "{{strategy.order.action}}",
    "position_size": "{{strategy.position_size}}"
}
```

### Signal Actions by Trading Mode

1. **Long Only Mode**:
   - `BUY`: Opens a long position
   - `SELL`: Closes the long position

2. **Short Only Mode**:
   - `SELL`: Opens a short position
   - `BUY`: Closes the short position

3. **Both Modes**:
   - `BUY` with positive position_size: Opens/Increases long position
   - `SELL` with positive position_size: Opens/Increases short position
   - `BUY` with zero position_size: Closes short position
   - `SELL` with zero position_size: Closes long position

### Important Notes:

1. **Symbol Format**:
   - Use the exact symbol as configured in your strategy
   - Symbols are case-sensitive
   - Must match with the configured exchange

2. **Position Size**:
   - Required only for "BOTH" trading mode
   - Must be included in every webhook message for "BOTH" mode
   - Represents the desired position size

3. **Action Values**:
   - Must be uppercase: "BUY" or "SELL"
   - Action interpretation depends on trading mode

### Sample Python Code

Here are examples of how to send webhook requests using Python:

#### 1. Basic Long/Short Mode Example
```python
import requests

# Inputs: host URL and webhook ID
host_url = "http://127.0.0.1:5000"
webhook_id = "ee12219c-3ce1-4a2c-a9b0-0c67c5fa7e32"

# Construct the full URL
webhook_url = f"{host_url}/strategy/webhook/{webhook_id}"

# Message to be sent
post_message = {
    "symbol": "SYMBOL",
    "action": "BUY"
}

# Send POST request
try:
    response = requests.post(webhook_url, json=post_message)
    print(f"Response Status Code: {response.status_code}")
    print(f"Response Body: {response.text}")
except requests.exceptions.RequestException as e:
    print(f"An error occurred: {e}")
```

#### 2. Both Mode Example
```python
import requests

def send_strategy_signal(host_url, webhook_id, symbol, action, position_size=None):
    """
    Send a strategy signal via webhook
    
    Args:
        host_url (str): Base URL of the OpenAlgo server
        webhook_id (str): Strategy's webhook ID
        symbol (str): Trading symbol
        action (str): "BUY" or "SELL"
        position_size (int, optional): Required for BOTH mode
    """
    # Construct webhook URL
    webhook_url = f"{host_url}/strategy/webhook/{webhook_id}"
    
    # Prepare message
    post_message = {
        "symbol": symbol,
        "action": action.upper()
    }
    
    # Add position_size for BOTH mode
    if position_size is not None:
        post_message["position_size"] = str(position_size)
    
    try:
        response = requests.post(webhook_url, json=post_message)
        if response.status_code == 200:
            print(f"Signal sent successfully: {post_message}")
        else:
            print(f"Error sending signal. Status: {response.status_code}")
            print(f"Response: {response.text}")
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")

# Example usage
host = "http://127.0.0.1:5000"
webhook_id = "ee12219c-3ce1-4a2c-a9b0-0c67c5fa7e32"

# Long entry example (BOTH mode)
send_strategy_signal(host, webhook_id, "RELIANCE", "BUY", 1)

# Short entry example (BOTH mode)
send_strategy_signal(host, webhook_id, "NIFTY", "SELL", 1)

# Close positions example (BOTH mode)
send_strategy_signal(host, webhook_id, "RELIANCE", "SELL", 0)  # Close long
send_strategy_signal(host, webhook_id, "NIFTY", "BUY", 0)     # Close short
```

#### 3. Error Handling Example
```python
import requests
import json
from typing import Dict, Optional
from datetime import datetime

class WebhookError(Exception):
    """Custom exception for webhook errors"""
    pass

class StrategyWebhook:
    def __init__(self, host_url: str, webhook_id: str):
        self.webhook_url = f"{host_url}/strategy/webhook/{webhook_id}"
    
    def send_signal(self, 
                   symbol: str, 
                   action: str, 
                   position_size: Optional[int] = None) -> Dict:
        """
        Send a trading signal with comprehensive error handling
        
        Args:
            symbol: Trading symbol
            action: "BUY" or "SELL"
            position_size: Required for BOTH mode
        
        Returns:
            Dict containing response data
        
        Raises:
            WebhookError: If the request fails or returns non-200 status
        """
        # Validate inputs
        if action.upper() not in ["BUY", "SELL"]:
            raise ValueError("Action must be either 'BUY' or 'SELL'")
        
        # Prepare message
        message = {
            "symbol": symbol,
            "action": action.upper(),
            "timestamp": datetime.now().isoformat()
        }
        
        if position_size is not None:
            message["position_size"] = str(position_size)
        
        try:
            response = requests.post(
                self.webhook_url, 
                json=message,
                timeout=5  # 5 seconds timeout
            )
            
            # Check response status
            if response.status_code != 200:
                raise WebhookError(
                    f"Request failed with status {response.status_code}: "
                    f"{response.text}"
                )
            
            return response.json()
            
        except requests.exceptions.Timeout:
            raise WebhookError("Request timed out")
        except requests.exceptions.ConnectionError:
            raise WebhookError("Connection failed")
        except json.JSONDecodeError:
            raise WebhookError("Invalid JSON response")
        except Exception as e:
            raise WebhookError(f"Unexpected error: {str(e)}")

# Usage example
try:
    webhook = StrategyWebhook(
        "http://127.0.0.1:5000",
        "ee12219c-3ce1-4a2c-a9b0-0c67c5fa7e32"
    )
    
    # Send a signal
    result = webhook.send_signal("RELIANCE", "BUY", 1)
    print(f"Signal sent successfully: {result}")
    
except WebhookError as e:
    print(f"Webhook error: {e}")
except ValueError as e:
    print(f"Invalid input: {e}")
except Exception as e:
    print(f"Unexpected error: {e}")
```

### How Webhook Processing Works

1. **Signal Reception**:
   - Webhook endpoint receives TradingView alert
   - Validates webhook ID and message format
   - Checks strategy status and trading hours

2. **Order Processing**:
   - Matches symbol with strategy configuration
   - Validates trading mode compatibility
   - Applies position sizing rules
   - Routes to appropriate order queue

3. **Rate Limiting**:
   - Regular orders: Max 10/second
   - Smart orders: 1/second
   - Queue management for order bursts

4. **Position Management**:
   - Tracks open positions per symbol
   - Handles partial fills
   - Manages stop-loss and target orders
   - Implements square-off rules

### Best Practices for Webhook Usage

1. **Alert Naming**:
   - Use clear, consistent naming patterns
   - Include strategy identifier
   - Add signal type in name

2. **Message Formatting**:
   - Use proper JSON syntax
   - Include all required fields
   - Add custom fields for strategy-specific data

3. **Error Handling**:
   - Set up retry mechanism in TradingView
   - Monitor webhook delivery status
   - Implement fallback signals

4. **Testing**:
   - Test with paper trading first
   - Verify webhook connectivity
   - Validate all signal types
   - Check position tracking

## Future Enhancements

Planned improvements include:
- Advanced order types
- Strategy templates
- Performance analytics
- Risk management features
- Multi-account support
