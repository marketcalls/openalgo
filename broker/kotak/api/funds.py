# api/funds.py
import json

import httpx

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def safe_float(value, default=0.0):
    """
    Convert value to float, handling None, empty strings, and invalid values.

    Args:
        value: Value to convert to float
        default: Default value to return if conversion fails

    Returns:
        float: Converted value or default
    """
    if value is None or value == '':
        return default
    try:
        return float(value)
    except (ValueError, TypeError):
        logger.debug(f"Could not convert value to float: {value}, using default: {default}")
        return default


def safe_int(value, default=0):
    """
    Convert value to int, handling None, empty strings, and invalid values.

    Args:
        value: Value to convert to int
        default: Default value to return if conversion fails

    Returns:
        int: Converted value or default
    """
    if value is None or value == '':
        return default
    try:
        return int(value)
    except (ValueError, TypeError):
        logger.debug(f"Could not convert value to int: {value}, using default: {default}")
        return default


def get_margin_data(auth_token):
    """
    Fetch margin data from the broker's API using the provided auth token.

    Auth token format: trading_token:::trading_sid:::base_url:::access_token
    """
    try:
        # Parse auth token components
        access_token_parts = auth_token.split(":::")
        if len(access_token_parts) != 4:
            logger.error(
                f"Invalid auth token format. Expected 4 parts, got {len(access_token_parts)}"
            )
            return {}

        trading_token = access_token_parts[0]
        trading_sid = access_token_parts[1]
        base_url = access_token_parts[2]
        access_token = access_token_parts[3]

        if not base_url:
            logger.error("Base URL not found in auth token")
            return {}

        logger.debug(f"Fetching margin data from {base_url}")

        # Get the shared httpx client with connection pooling
        client = get_httpx_client()

        # Prepare payload as per Kotak API docs: jData with seg, exch, prod
        payload = (
            "jData=%7B%22seg%22%3A%22ALL%22%2C%22exch%22%3A%22ALL%22%2C%22prod%22%3A%22ALL%22%7D"
        )

        headers = {
            "accept": "application/json",
            "Sid": trading_sid,
            "Auth": trading_token,
            "neo-fin-key": "neotradeapi",
            "Content-Type": "application/x-www-form-urlencoded",
        }

        # Construct full URL
        url = f"{base_url}/quick/user/limits"

        logger.debug(f"Making POST request to {url}")

        response = client.post(url, headers=headers, content=payload)

        logger.debug(f"Kotak Limits API Response Status: {response.status_code}")
        logger.debug(f"Kotak Limits API Response: {response.text}")

        margin_data = json.loads(response.text)

        # Check for API errors
        if margin_data.get("stat") != "Ok":
            error_msg = margin_data.get("emsg", "Unknown error")
            logger.error(f"Kotak Limits API error: {error_msg}")
            return {}

        # Log API response structure for debugging
        logger.debug(f"Kotak API response keys: {list(margin_data.keys())}")

        # Validate critical fields exist
        required_fields = ['CollateralValue', 'RmsPayInAmt', 'RmsPayOutAmt', 'Collateral', 'MarginUsed']
        missing_fields = [field for field in required_fields if field not in margin_data]
        if missing_fields:
            logger.warning(f"Kotak API response missing fields: {missing_fields}")

        # Process margin data with null-safe parsing
        # Available Balance = CollateralValue + RmsPayInAmt - RmsPayOutAmt + Collateral
        collateral_value = safe_float(margin_data.get("CollateralValue"))
        pay_in = safe_float(margin_data.get("RmsPayInAmt"))
        pay_out = safe_float(margin_data.get("RmsPayOutAmt"))
        collateral = safe_float(margin_data.get("Collateral"))

        # Calculate PnL from positions for accuracy
        total_realised = 0.0
        total_unrealised = 0.0

        try:
            # Import here to avoid circular dependency
            from broker.kotak.api.order_api import get_positions

            logger.info("Fetching positions for PnL calculation")
            positions_response = get_positions(auth_token)
            logger.info(f"Positions API Response: {positions_response}")

            data = positions_response.get("data")
            if positions_response.get("stat", "").lower() == "ok" and data is not None:
                positions = data
                logger.info(f"Processing {len(positions)} positions for PnL")
                logger.info(f"Sample position data: {positions[0] if positions else 'No positions'}")

                for position in positions:
                    # Calculate net quantity
                    fl_buy_qty = safe_int(position.get("flBuyQty"))
                    fl_sell_qty = safe_int(position.get("flSellQty"))
                    cf_buy_qty = safe_int(position.get("cfBuyQty"))
                    cf_sell_qty = safe_int(position.get("cfSellQty"))

                    net_qty = (fl_buy_qty - fl_sell_qty) + (cf_buy_qty - cf_sell_qty)

                    # Handle realized P&L differently for closed vs open positions
                    if net_qty == 0:
                        # Closed position - use buyAmt/sellAmt for accurate realized P&L
                        # The rpnl field is often inaccurate for closed positions
                        buy_amt = safe_float(position.get("buyAmt"))
                        sell_amt = safe_float(position.get("sellAmt"))

                        if buy_amt > 0 or sell_amt > 0:
                            realized_pnl = sell_amt - buy_amt
                            total_realised += realized_pnl
                            logger.info(
                                f"Closed Position {position.get('trdSym')}: "
                                f"buyAmt={buy_amt}, sellAmt={sell_amt}, realized={realized_pnl:.2f}"
                            )
                    else:
                        # Open position - calculate both realized and unrealized P&L
                        # For partially closed positions, we need to calculate realized P&L
                        # from the closed portion
                        buy_amt = safe_float(position.get("buyAmt"))
                        sell_amt = safe_float(position.get("sellAmt"))

                        # Calculate realized P&L for the closed portion
                        if fl_sell_qty > 0 and fl_buy_qty > 0:
                            # Average buy price
                            avg_buy_price = buy_amt / fl_buy_qty if fl_buy_qty > 0 else 0
                            # Realized P&L = sellAmt - (avg_buy_price × sell_qty)
                            realized_pnl = sell_amt - (avg_buy_price * fl_sell_qty)
                            total_realised += realized_pnl
                            logger.info(
                                f"Partial Realized P&L for {position.get('trdSym')}: "
                                f"sold {fl_sell_qty} @ avg {avg_buy_price:.2f}, "
                                f"realized={realized_pnl:.2f}"
                            )

                        # Calculate unrealized PnL for open positions
                        # Kotak API doesn't provide flBuyAvg/flSellAvg, so calculate from amounts
                        avg_price = 0.0
                        if net_qty > 0:
                            # Long position - calculate buy average from buyAmt / flBuyQty
                            if fl_buy_qty > 0:
                                avg_price = buy_amt / fl_buy_qty
                        else:
                            # Short position - calculate sell average from sellAmt / flSellQty
                            if fl_sell_qty > 0:
                                avg_price = sell_amt / fl_sell_qty

                        # Get current LTP - Kotak positions API doesn't provide ltp
                        # We need to fetch it from quotes API
                        ltp = 0.0
                        try:
                            from broker.kotak.api.data import BrokerData
                            from broker.kotak.mapping.transform_data import map_exchange

                            # Get OpenAlgo exchange format
                            oa_exchange = map_exchange(position.get("exSeg"))

                            # Get OpenAlgo symbol from database
                            from database.token_db import get_symbol
                            token = position.get("tok")
                            oa_symbol = get_symbol(token, oa_exchange)

                            if oa_symbol and oa_exchange:
                                broker_data = BrokerData(auth_token)
                                quotes_response = broker_data.get_quotes(oa_symbol, oa_exchange)
                                if quotes_response:
                                    ltp = safe_float(quotes_response.get("ltp"))
                                    logger.debug(f"Fetched LTP for {position.get('trdSym')}: {ltp}")
                        except Exception as e:
                            logger.debug(f"Could not fetch LTP for {position.get('trdSym')}: {e}")

                        # Calculate unrealized PnL
                        if ltp > 0 and avg_price > 0:
                            unrealized = (ltp - avg_price) * net_qty
                            total_unrealised += unrealized
                            logger.info(
                                f"Open Position {position.get('trdSym')}: qty={net_qty}, "
                                f"avg={avg_price:.2f}, ltp={ltp:.2f}, unrealized={unrealized:.2f}"
                            )
                        else:
                            logger.warning(
                                f"Could not calculate unrealized PnL for {position.get('trdSym')}: "
                                f"avg_price={avg_price:.2f}, ltp={ltp:.2f}"
                            )

                logger.info(
                    f"Calculated PnL from positions - Realized: {total_realised:.2f}, "
                    f"Unrealized: {total_unrealised:.2f}"
                )

            else:
                logger.warning("Could not fetch positions, using API-provided PnL values")
                # Fallback to API-provided values if positions fetch fails
                total_realised = safe_float(margin_data.get('RealizedMtomPrsnt'))
                total_unrealised = safe_float(margin_data.get('UnrealizedMtomPrsnt'))

        except Exception as e:
            import traceback
            logger.error(f"Error calculating PnL from positions: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Fallback to API-provided values
            total_realised = safe_float(margin_data.get('RealizedMtomPrsnt'))
            total_unrealised = safe_float(margin_data.get('UnrealizedMtomPrsnt'))
            logger.info(
                f"Using API-provided PnL - Realized: {total_realised:.2f}, "
                f"Unrealized: {total_unrealised:.2f}"
            )

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": f"{collateral_value + pay_in - pay_out + collateral:.2f}",
            "collateral": f"{collateral:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{safe_float(margin_data.get('MarginUsed')):.2f}",
        }

        logger.info(f"Successfully fetched margin data: {processed_margin_data}")
        return processed_margin_data

    except KeyError as e:
        logger.error(f"Missing expected field in margin data: {e}")
        return {}
    except httpx.HTTPError as e:
        logger.error(f"HTTP request failed while fetching margin data: {e}")
        return {}
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse margin data JSON: {e}")
        return {}
    except Exception as e:
        logger.error(f"Error fetching margin data: {e}")
        return {}
