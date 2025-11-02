# mstock Broker Integration

This document provides a guide to setting up and using the mstock broker integration with OpenAlgo.

## Configuration

To enable the mstock broker, you need to set the following environment variables:

- `MSTOCK_BROKER_API_KEY`: Your mstock API key.
- `MSTOCK_USERNAME`: Your mstock username.
- `MSTOCK_PASSWORD`: Your mstock password.
- `MSTOCK_TOTP_SECRET`: Your mstock TOTP secret for two-factor authentication.

These variables should be added to your `.env` file or set as environment variables in your deployment environment.

## Authentication

The mstock integration uses a TOTP-based authentication flow. The system will use the provided credentials to log in and generate a session token. The access token is refreshed automatically.

## Supported Features

- **Authentication**: TOTP-based login.
- **Order Management**: Place, modify, and cancel orders.
- **Account Information**: Fetch funds, holdings, and positions.
- **Market Data**: Fetch OHLC, LTP, and historical data.

## API Endpoints

The following API endpoints are available for the mstock integration:

- `GET /funds`: Get fund summary.
- `GET /holdings`: Get holdings.
- `GET /positions`: Get positions.
- `POST /orders`: Place an order.
- `PUT /orders/{order_id}`: Modify an order.
- `DELETE /orders/{order_id}`: Cancel an order.
- `GET /orders`: Get the order book.
- `GET /quotes`: Get market quotes.
- `GET /history`: Get historical data.

## Usage

To use the mstock broker, select "mstock" as the broker in your OpenAlgo client configuration. The SDK will automatically handle the authentication and API calls.
