"""
OpenAlgo Expiry Date Extraction Example
----------------------------------------
Demonstrates how to extract expiry dates using the OpenAlgo Python SDK.

Weekly: current_week, next_week, current_month, next_month
Monthly: current_month, next_month, far_month

Reference: AlgoMirror Strategy Executor implementation
"""

from datetime import datetime

from openalgo import api

# Initialize client with explicit parameters
client = api(
    api_key="7371cc58b9d30204e5fee1d143dc8cd926bcad90c24218201ad81735384d2752",  # Replace with your API key
    host="http://127.0.0.1:5000",  # Replace with your API host
)

# Expiry request parameters
symbol = "NIFTY"  # Index symbol (NIFTY, BANKNIFTY, SENSEX, etc.)
exchange = "NFO"  # Exchange (NFO for NIFTY/BANKNIFTY, BFO for SENSEX)
instrumenttype = "options"  # Instrument type ("options" or "futures")
expirytype = "weekly"  # Expiry type ("weekly" or "monthly")


def get_expiry_dates(symbol: str, exchange: str, instrumenttype: str, expirytype: str):
    """
    Fetch and categorize expiry dates from OpenAlgo API.

    Args:
        symbol: Index symbol (NIFTY, BANKNIFTY, SENSEX, etc.)
        exchange: Exchange (NFO for NIFTY/BANKNIFTY, BFO for SENSEX)
        instrumenttype: Instrument type ("options" or "futures")
        expirytype: Expiry type ("weekly" or "monthly")

    Returns:
        For weekly: dict with current_week, next_week, current_month, next_month
        For monthly: dict with current_month, next_month, far_month
    """
    # Fetch expiry dates from OpenAlgo
    response = client.expiry(symbol=symbol, exchange=exchange, instrumenttype=instrumenttype)

    if response.get("status") != "success":
        raise Exception(f"Failed to fetch expiries: {response.get('message')}")

    expiries = response.get("data", [])
    if not expiries:
        raise Exception(f"No expiries available for {symbol}")

    # Parse and sort expiries chronologically
    def parse_expiry(exp_str):
        """Parse expiry string to datetime"""
        formats = ["%d-%b-%y", "%d%b%y", "%d-%B-%y", "%d%B%y"]
        exp_upper = exp_str.upper().strip()
        for fmt in formats:
            try:
                return datetime.strptime(exp_upper, fmt)
            except ValueError:
                continue
        return datetime.max

    sorted_expiries = sorted(expiries, key=parse_expiry)

    # Extract expiry dates by category
    now = datetime.now()
    current_month = now.month
    current_year = now.year
    next_month = (current_month % 12) + 1
    next_year = current_year + 1 if next_month == 1 else current_year
    far_month = (next_month % 12) + 1
    far_year = next_year + 1 if far_month == 1 else next_year

    if expirytype == "weekly":
        result = {
            "current_week": None,
            "next_week": None,
            "current_month": None,
            "next_month": None,
        }

        # Current week = nearest expiry (index 0)
        if sorted_expiries:
            result["current_week"] = sorted_expiries[0]

        # Next week = second expiry (index 1)
        if len(sorted_expiries) > 1:
            result["next_week"] = sorted_expiries[1]

        # Current month = last expiry of current calendar month
        for exp_str in sorted_expiries:
            exp_date = parse_expiry(exp_str)
            if exp_date.month == current_month and exp_date.year == current_year:
                result["current_month"] = exp_str  # Keep updating to get the last one

        # Next month = last expiry of next calendar month
        for exp_str in sorted_expiries:
            exp_date = parse_expiry(exp_str)
            if exp_date.month == next_month and exp_date.year == next_year:
                result["next_month"] = exp_str  # Keep updating to get the last one

    else:  # monthly
        result = {"current_month": None, "next_month": None, "far_month": None}

        # Current month = last expiry of current calendar month
        for exp_str in sorted_expiries:
            exp_date = parse_expiry(exp_str)
            if exp_date.month == current_month and exp_date.year == current_year:
                result["current_month"] = exp_str  # Keep updating to get the last one

        # Next month = last expiry of next calendar month
        for exp_str in sorted_expiries:
            exp_date = parse_expiry(exp_str)
            if exp_date.month == next_month and exp_date.year == next_year:
                result["next_month"] = exp_str  # Keep updating to get the last one

        # Far month = last expiry of far calendar month
        for exp_str in sorted_expiries:
            exp_date = parse_expiry(exp_str)
            if exp_date.month == far_month and exp_date.year == far_year:
                result["far_month"] = exp_str  # Keep updating to get the last one

    return result


# Example usage
if __name__ == "__main__":
    # Get expiries
    expiries = get_expiry_dates(
        symbol=symbol, exchange=exchange, instrumenttype=instrumenttype, expirytype=expirytype
    )

    print(f"{symbol} Expiry Dates ({expirytype}):")
    if expirytype == "weekly":
        print(f"  Current Week : {expiries['current_week']}")
        print(f"  Next Week    : {expiries['next_week']}")
        print(f"  Current Month: {expiries['current_month']}")
        print(f"  Next Month   : {expiries['next_month']}")
    else:  # monthly
        print(f"  Current Month: {expiries['current_month']}")
        print(f"  Next Month   : {expiries['next_month']}")
        print(f"  Far Month    : {expiries['far_month']}")
