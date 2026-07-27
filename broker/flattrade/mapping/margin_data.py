# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping Flattrade Span Calculator API

from database.token_db import get_br_symbol
from utils.logging import get_logger

logger = get_logger(__name__)


def transform_margin_positions(positions, account_id):
    """
    Transform OpenAlgo margin positions to Flattrade margin format.

    Args:
        positions: List of positions in OpenAlgo format
        account_id: Flattrade account ID (API key)

    Returns:
        Dict in Flattrade margin format with actid and pos array
    """
    transformed_positions = []

    for position in positions:
        try:
            # Use the original OpenAlgo symbol for parsing derivative details
            oa_symbol = position["symbol"]

            # Log the incoming position data
            logger.info(
                f"Processing position: symbol='{oa_symbol}', exchange='{position['exchange']}'"
            )

            # Get the broker symbol for validation only
            br_symbol = get_br_symbol(oa_symbol, position["exchange"])
            logger.info(f"Broker symbol for '{oa_symbol}': '{br_symbol}'")

            if not br_symbol:
                logger.warning(
                    f"Symbol not found for: {oa_symbol} on exchange: {position['exchange']}"
                )
                continue

            # Parse the OpenAlgo symbol (not broker symbol) to extract details
            # Determine instrument name based on symbol pattern
            # This is a simplified mapping - may need enhancement based on actual symbol patterns
            instname = determine_instrument_name(oa_symbol, position["exchange"])

            # Extract symbol name (without suffix for options/futures)
            symname = extract_symbol_name(oa_symbol)

            # Extract expiry date, option type, and strike price if applicable
            exd, optt, strprc = extract_derivative_details(oa_symbol, position["exchange"])

            # Log the parsed details for debugging
            logger.info(
                f"Parsed symbol '{oa_symbol}': instname={instname}, symname={symname}, exd={exd}, optt={optt}, strprc={strprc}"
            )

            # Map product type from OpenAlgo to Flattrade format
            # Official SDK: C = CNC, M = NRML/Margin, H = MIS (Intraday)
            product_map = {
                "CNC": "C",
                "MIS": "H",  # H = MIS (same as Shoonya)
                "NRML": "M",
            }
            product = position.get("product", "NRML")  # Default to NRML for F&O
            prd = product_map.get(product, "M")  # Default to 'M' if not found

            # Calculate quantities based on action
            quantity = int(position["quantity"])
            if position["action"].upper() == "BUY":
                buyqty = quantity
                sellqty = 0
                netqty = quantity
            else:
                buyqty = 0
                sellqty = quantity
                netqty = -quantity  # Negative for sell positions (same as Shoonya)

            # Transform the position - ALL VALUES MUST BE STRINGS (same as Shoonya)
            # Official SDK requires prd field: C=CNC, M=NRML, H=MIS
            transformed_position = {
                "prd": prd,  # Required: C=CNC, M=NRML/Margin, H=MIS
                "exch": position["exchange"],
                "instname": instname,
                "symname": symname,
                "exd": exd,  # DD-MMM-YYYY format
                "optt": optt,  # 'CE', 'PE', or 'XX' for futures
                "strprc": str(strprc) if strprc else "-1",  # String! '-1' for futures
                "buyqty": str(buyqty),  # String!
                "sellqty": str(sellqty),  # String!
                "netqty": str(netqty),  # String!
            }

            transformed_positions.append(transformed_position)

        except Exception as e:
            logger.error(f"Error transforming position: {position}, Error: {e}")
            continue

    return {"actid": account_id, "pos": transformed_positions}


def determine_instrument_name(symbol, exchange):
    """
    Determine instrument name based on symbol and exchange.

    Returns: FUTSTK, FUTIDX, OPTSTK, OPTIDX, FUTCUR, etc.
    """
    # For equity exchanges
    if exchange in ["NSE", "BSE"]:
        return "EQ"

    # For derivative exchanges
    if exchange == "NFO":
        if "FUT" in symbol or symbol.endswith("F"):
            if any(idx in symbol for idx in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]):
                return "FUTIDX"
            else:
                return "FUTSTK"
        elif "CE" in symbol or "PE" in symbol or symbol.endswith("C") or symbol.endswith("P"):
            # Check if it's an index option or stock option
            if any(idx in symbol for idx in ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"]):
                return "OPTIDX"
            else:
                return "OPTSTK"

    # For currency
    if exchange == "CDS":
        if "FUT" in symbol:
            return "FUTCUR"
        elif "CE" in symbol or "PE" in symbol:
            return "OPTCUR"

    # For commodity
    if exchange == "MCX":
        if "FUT" in symbol:
            return "FUTCOM"
        elif "CE" in symbol or "PE" in symbol:
            return "OPTCOM"

    # Default
    return "EQ"


def extract_symbol_name(symbol):
    """
    Extract base symbol name from trading symbol.
    E.g., NIFTY25NOV25FUT -> NIFTY
    E.g., NIFTY30DEC2524500CE -> NIFTY
    """
    import re

    # Start with the full symbol
    base = symbol

    # First remove option type suffixes (CE, PE, C, P)
    # Check for CE/PE first (longer pattern)
    if "CE" in base:
        base = base.split("CE")[0]
    elif "PE" in base:
        base = base.split("PE")[0]
    # Then check for single character suffix
    elif base.endswith("C") and not base.endswith("DEC"):
        base = base[:-1]  # Remove last character 'C'
    elif base.endswith("P"):
        base = base[:-1]  # Remove last character 'P'

    # Remove FUT suffix
    if "FUT" in base:
        base = base.split("FUT")[0]

    # Remove -EQ suffix
    if "-EQ" in base:
        base = base.split("-EQ")[0]

    # Remove date patterns (e.g., 30DEC25, 2025-11-28, etc.)
    base = re.sub(r"\d{2}[A-Z]{3}\d{2}", "", base)
    base = re.sub(r"\d{4}-\d{2}-\d{2}", "", base)

    # Remove strike prices (3 or more consecutive digits)
    base = re.sub(r"\d{3,}", "", base)

    return base.strip()


def extract_derivative_details(symbol, exchange):
    """
    Extract expiry date, option type, and strike price from symbol.

    Returns: (exd, optt, strprc)
    """
    exd = ""
    optt = ""
    strprc = ""

    # For equity exchanges, no derivatives
    if exchange in ["NSE", "BSE"]:
        return exd, optt, strprc

    import re

    # Extract expiry date (format: DDMMMYY to DD-MMM-YYYY for Flattrade)
    date_match = re.search(r"(\d{2})([A-Z]{3})(\d{2})", symbol)
    if date_match:
        day = date_match.group(1)
        month_str = date_match.group(2)
        year_2digit = date_match.group(3)
        year_4digit = "20" + year_2digit

        # Working test uses DD-MMM-YYYY format (e.g., 29-DEC-2022)
        exd = f"{day}-{month_str}-{year_4digit}"

    # Check if it's a future or option
    is_option = "CE" in symbol or "PE" in symbol or symbol.endswith("C") or symbol.endswith("P")
    is_future = "FUT" in symbol and not is_option

    if is_future:
        # For futures: optt='XX' and strprc='-1' as per working test
        optt = "XX"
        strprc = "-1"
    elif "CE" in symbol:
        optt = "CE"
        # Extract strike price: digits after date pattern and before CE
        # Pattern: date(DDMMMYY) followed by digits (strike) followed by CE
        strike_match = re.search(r"\d{2}[A-Z]{3}\d{2}(\d+\.?\d*)CE", symbol)
        if strike_match:
            strprc = strike_match.group(1)
    elif "PE" in symbol:
        optt = "PE"
        # Extract strike price: digits after date pattern and before PE
        strike_match = re.search(r"\d{2}[A-Z]{3}\d{2}(\d+\.?\d*)PE", symbol)
        if strike_match:
            strprc = strike_match.group(1)
    # Also handle single character suffix (C/P) in case that's the format
    elif symbol.endswith("C") and not symbol.endswith("DEC"):
        optt = "CE"
        strike_match = re.search(r"\d{2}[A-Z]{3}\d{2}(\d+\.?\d*)C$", symbol)
        if strike_match:
            strprc = strike_match.group(1)
    elif symbol.endswith("P") and not is_future:
        optt = "PE"
        strike_match = re.search(r"\d{2}[A-Z]{3}\d{2}(\d+\.?\d*)P$", symbol)
        if strike_match:
            strprc = strike_match.group(1)

    return exd, optt, strprc


def parse_margin_response(response_data):
    """
    Parse Flattrade margin response to OpenAlgo standard format.

    Args:
        response_data: Raw response from Flattrade API

    Returns:
        Standardized margin response matching OpenAlgo format
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {"status": "error", "message": "Invalid response from broker"}

        # Check if the response status is Ok
        if response_data.get("stat") != "Ok":
            error_message = response_data.get("emsg", "Failed to calculate margin")
            return {"status": "error", "message": error_message}

        # Extract margin data
        # Flattrade returns: span, expo, span_trade, expo_trade
        span = float(response_data.get("span", 0))
        expo = float(response_data.get("expo", 0))
        total_margin = span + expo

        # Return standardized format matching OpenAlgo API specification
        return {
            "status": "success",
            "data": {
                "total_margin_required": total_margin,
                "span_margin": span,
                "exposure_margin": expo,
            },
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {"status": "error", "message": f"Failed to parse margin response: {str(e)}"}
