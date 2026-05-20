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

            logger.debug("Fetching positions for PnL calculation")
            positions_response = get_positions(auth_token)
            logger.debug(f"Positions API Response: {positions_response}")

            data = positions_response.get("data")
            if positions_response.get("stat", "").lower() == "ok" and data is not None:
                positions = data
                logger.info(f"Processing {len(positions)} positions for PnL")

                # Collect all symbols for batch LTP fetch
                symbols_to_fetch = []
                position_map = {}  # Map symbol to position data

                for position in positions:
                    # Calculate net quantity
                    fl_buy_qty = safe_int(position.get("flBuyQty"))
                    fl_sell_qty = safe_int(position.get("flSellQty"))
                    cf_buy_qty = safe_int(position.get("cfBuyQty"))
                    cf_sell_qty = safe_int(position.get("cfSellQty"))

                    net_qty = (fl_buy_qty - fl_sell_qty) + (cf_buy_qty - cf_sell_qty)

                    # Only fetch LTP for open positions
                    if net_qty != 0:
                        try:
                            from broker.kotak.mapping.transform_data import map_exchange
                            from database.token_db import get_symbol

                            oa_exchange = map_exchange(position.get("exSeg"))
                            token = position.get("tok")
                            oa_symbol = get_symbol(token, oa_exchange)

                            if oa_symbol and oa_exchange:
                                symbols_to_fetch.append({
                                    "symbol": oa_symbol,
                                    "exchange": oa_exchange
                                })
                                position_map[f"{oa_symbol}_{oa_exchange}"] = position
                        except Exception as e:
                            logger.debug(f"Could not prepare symbol for LTP fetch: {e}")

                # Batch fetch LTP for all open positions
                ltp_map = {}
                use_api_fallback = False
                if symbols_to_fetch:
                    try:
                        from broker.kotak.api.data import BrokerData
                        broker_data = BrokerData(auth_token)
                        multiquotes_response = broker_data.get_multiquotes(symbols_to_fetch)

                        for quote_item in multiquotes_response:
                            if "data" in quote_item and quote_item["data"]:
                                symbol = quote_item["symbol"]
                                exchange = quote_item["exchange"]
                                ltp = safe_float(quote_item["data"].get("ltp"))
                                if ltp > 0:  # Only add valid LTP values
                                    ltp_map[f"{symbol}_{exchange}"] = ltp
                                    logger.debug(f"Fetched LTP for {symbol}: {ltp}")

                        # Check if we got any usable LTP data
                        if not ltp_map and symbols_to_fetch:
                            logger.warning("Batch LTP fetch returned no usable data")
                            use_api_fallback = True
                    except Exception as e:
                        logger.warning(f"Could not batch fetch LTP: {e}")
                        use_api_fallback = True
                else:
                    # No open positions to fetch LTP for, but we might still have unrealized P&L from API
                    # This handles the case where all positions are closed but API reports unrealized P&L
                    pass

                # Fallback: use API-provided unrealized P&L if batch fetch failed or returned no data
                if use_api_fallback:
                    logger.info("Using API-provided unrealized P&L as fallback")
                    total_unrealised = safe_float(margin_data.get('UnrealizedMtomPrsnt'))
                    # Still calculate realized P&L from positions
                    # (continue with position loop but skip unrealized calculation)

                # Track positions with missing LTP data
                positions_with_missing_ltp = 0
                positions_needing_ltp = 0

                # Now calculate P&L for each position
                for position in positions:
                    # Calculate net quantity
                    fl_buy_qty = safe_int(position.get("flBuyQty"))
                    fl_sell_qty = safe_int(position.get("flSellQty"))
                    cf_buy_qty = safe_int(position.get("cfBuyQty"))
                    cf_sell_qty = safe_int(position.get("cfSellQty"))

                    net_qty = (fl_buy_qty - fl_sell_qty) + (cf_buy_qty - cf_sell_qty)

                    # Get amounts including carry-forward
                    fl_buy_amt = safe_float(position.get("buyAmt"))
                    fl_sell_amt = safe_float(position.get("sellAmt"))
                    cf_buy_amt = safe_float(position.get("cfBuyAmt"))
                    cf_sell_amt = safe_float(position.get("cfSellAmt"))

                    total_buy_amt = fl_buy_amt + cf_buy_amt
                    total_sell_amt = fl_sell_amt + cf_sell_amt
                    total_buy_qty = fl_buy_qty + cf_buy_qty
                    total_sell_qty = fl_sell_qty + cf_sell_qty

                    # Handle realized P&L differently for closed vs open positions
                    if net_qty == 0:
                        # Closed position - use total buyAmt/sellAmt for accurate realized P&L
                        if total_buy_amt > 0 or total_sell_amt > 0:
                            realized_pnl = total_sell_amt - total_buy_amt
                            total_realised += realized_pnl
                            logger.debug(
                                f"Closed Position {position.get('trdSym')}: "
                                f"buyAmt={total_buy_amt}, sellAmt={total_sell_amt}, realized={realized_pnl:.2f}"
                            )
                    else:
                        # Open position - calculate both realized and unrealized P&L
                        # Calculate realized P&L for the closed portion
                        if total_sell_qty > 0 and total_buy_qty > 0:
                            if net_qty > 0:
                                # Net long position - some bought shares were sold
                                # Realized P&L = sellAmt - (avg_buy_price × sell_qty)
                                avg_buy_price = total_buy_amt / total_buy_qty if total_buy_qty > 0 else 0
                                realized_pnl = total_sell_amt - (avg_buy_price * total_sell_qty)
                            elif net_qty < 0:
                                # Net short position - some sold shares were bought back
                                # Realized P&L = (avg_sell_price × buy_qty) - buyAmt
                                avg_sell_price = total_sell_amt / total_sell_qty if total_sell_qty > 0 else 0
                                realized_pnl = (avg_sell_price * total_buy_qty) - total_buy_amt
                            else:
                                # Should not reach here (net_qty == 0 handled above)
                                realized_pnl = 0.0

                            total_realised += realized_pnl
                            logger.debug(
                                f"Partial Realized P&L for {position.get('trdSym')}: "
                                f"net_qty={net_qty}, realized={realized_pnl:.2f}"
                            )

                        # Calculate unrealized PnL for open positions
                        # Include carry-forward in average price calculation
                        avg_price = 0.0
                        if net_qty > 0:
                            # Long position - calculate buy average including carry-forward
                            if total_buy_qty > 0:
                                avg_price = total_buy_amt / total_buy_qty
                        else:
                            # Short position - calculate sell average including carry-forward
                            if total_sell_qty > 0:
                                avg_price = total_sell_amt / total_sell_qty

                        # Get LTP from batch fetch
                        try:
                            from broker.kotak.mapping.transform_data import map_exchange
                            from database.token_db import get_symbol

                            oa_exchange = map_exchange(position.get("exSeg"))
                            token = position.get("tok")
                            oa_symbol = get_symbol(token, oa_exchange)

                            ltp = ltp_map.get(f"{oa_symbol}_{oa_exchange}", 0.0)

                            # Track if we're missing LTP for positions that need it
                            if ltp == 0.0:
                                positions_with_missing_ltp += 1
                            positions_needing_ltp += 1
                        except Exception as e:
                            logger.debug(f"Could not get LTP for {position.get('trdSym')}: {e}")
                            ltp = 0.0
                            positions_with_missing_ltp += 1
                            positions_needing_ltp += 1

                        # Calculate unrealized PnL only if we have LTP data
                        # If batch fetch failed or returned no data, unrealized P&L was set from API fallback
                        if not use_api_fallback:  # Only calculate if we have LTP data
                            if ltp > 0 and avg_price > 0:
                                unrealized = (ltp - avg_price) * net_qty
                                total_unrealised += unrealized
                                logger.debug(
                                    f"Open Position {position.get('trdSym')}: qty={net_qty}, "
                                    f"avg={avg_price:.2f}, ltp={ltp:.2f}, unrealized={unrealized:.2f}"
                                )
                            else:
                                logger.debug(
                                    f"Could not calculate unrealized PnL for {position.get('trdSym')}: "
                                    f"avg_price={avg_price:.2f}, ltp={ltp:.2f}"
                                )

                logger.info(
                    f"Calculated PnL from positions - Realized: {total_realised:.2f}, "
                    f"Unrealized: {total_unrealised:.2f}"
                )

                # If we have open positions but couldn't get LTP for any of them, fall back to API unrealized P&L
                if not use_api_fallback and positions_needing_ltp > 0 and positions_with_missing_ltp == positions_needing_ltp:
                    logger.warning(
                        f"Could not get LTP for any of {positions_needing_ltp} open positions, "
                        "falling back to API-provided unrealized P&L"
                    )
                    total_unrealised = safe_float(margin_data.get('UnrealizedMtomPrsnt'))

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
