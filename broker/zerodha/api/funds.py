# api/funds.py

import os

from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from Zerodha's API using the provided auth token."""
    api_key = os.getenv("BROKER_API_KEY")

    # Get the shared httpx client with connection pooling
    client = get_httpx_client()

    headers = {"X-Kite-Version": "3", "Authorization": f"token {auth_token}"}

    try:
        # Make the GET request using the shared client
        response = client.get("https://api.kite.trade/user/margins", headers=headers)
        response.raise_for_status()  # Raises an exception for 4XX/5XX responses

        # Parse the response
        margin_data = response.json()
    except Exception as e:
        error_message = str(e)
        try:
            if hasattr(e, "response") and e.response is not None:
                error_detail = e.response.json()
                error_message = error_detail.get("message", str(e))
        except:
            pass

        logger.error(f"Error fetching margin data: {error_message}")
        return {}

    if margin_data.get("status") == "error":
        logger.error(f"Error fetching margin data: {margin_data.get('errors')}")
        return {}

    try:
        # Calculate the sum of net values for available margin
        total_available_margin = sum(
            [margin_data["data"]["commodity"]["net"], margin_data["data"]["equity"]["net"]]
        )
        # Calculate the sum of debits for used margin
        total_used_margin = sum(
            [
                margin_data["data"]["commodity"]["utilised"]["debits"],
                margin_data["data"]["equity"]["utilised"]["debits"],
            ]
        )

        # Calculate the sum of collateral values
        total_collateral = sum(
            [
                margin_data["data"]["commodity"]["available"]["collateral"],
                margin_data["data"]["equity"]["available"]["collateral"],
            ]
        )

        # Fetch PnL from position book
        total_realised = 0
        total_unrealised = 0
        try:
            pos_response = client.get(
                "https://api.kite.trade/portfolio/positions", headers=headers
            )
            pos_response.raise_for_status()
            position_book = pos_response.json()

            if position_book.get("status") == "success" and position_book.get("data"):
                net_positions = position_book["data"].get("net", [])

                # Collect open positions to fetch live LTP
                open_positions = []
                for p in net_positions:
                    qty = p.get("quantity", 0)
                    if qty == 0:
                        # Fully closed position - PnL is realized
                        total_realised += p.get("sell_value", 0) - p.get("buy_value", 0)
                    else:
                        open_positions.append(p)

                # Fetch live LTP for open positions via quotes API
                if open_positions:
                    instruments = [
                        f"{p['exchange']}:{p['tradingsymbol']}" for p in open_positions
                    ]
                    query = "&".join(f"i={inst}" for inst in instruments)
                    quote_response = client.get(
                        f"https://api.kite.trade/quote/ltp?{query}", headers=headers
                    )
                    quote_response.raise_for_status()
                    quote_data = quote_response.json()
                    ltp_map = {}
                    if quote_data.get("status") == "success" and quote_data.get("data"):
                        for key, val in quote_data["data"].items():
                            ltp_map[key] = val.get("last_price", 0)

                    for p in open_positions:
                        qty = p.get("quantity", 0)
                        avg_price = p.get("average_price", 0)
                        inst_key = f"{p['exchange']}:{p['tradingsymbol']}"
                        live_ltp = ltp_map.get(inst_key, p.get("last_price", 0))
                        total_unrealised += (live_ltp - avg_price) * qty
        except Exception as e:
            logger.error(f"Error fetching positions for PnL: {e}")

        # Construct and return the processed margin data
        processed_margin_data = {
            "availablecash": f"{total_available_margin:.2f}",
            "collateral": f"{total_collateral:.2f}",
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": f"{total_used_margin:.2f}",
        }
        return processed_margin_data
    except KeyError:
        # Return an empty dictionary in case of unexpected data structure
        return {}
