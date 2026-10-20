"""Map OpenAlgo margin requests to SMIFS /v1/funds/margin/multi and back."""
from database.token_db import get_token

from broker.smifs.mapping.transform_data import map_exchange_type, map_product_type

# SMIFS accepts between 1 and 20 legs in one multi-margin call.
MAX_LEGS = 20


def transform_margin_positions(positions, ltp_lookup):
    """OpenAlgo positions -> (SMIFS scrips, list of skipped-leg messages).

    SMIFS needs a price above zero for every leg. A MARKET or SL-M leg sent by
    OpenAlgo usually has price 0, so the last traded price from
    `ltp_lookup(segment, security_id)` is used for those legs instead.
    """
    scrips, skipped = [], []
    for pos in positions:
        symbol, exchange = pos.get("symbol"), pos.get("exchange")
        if exchange in ("NSE_INDEX", "BSE_INDEX"):
            skipped.append(f"{symbol}: an index has no margin")
            continue
        token = get_token(symbol, exchange)
        if token is None:
            skipped.append(f"{symbol}: not in the SMIFS master contract for {exchange}")
            continue
        segment = map_exchange_type(exchange)
        price = float(pos.get("price", 0) or 0)
        if price <= 0:
            price = float(ltp_lookup(segment, str(token)) or 0)
        if price <= 0:
            skipped.append(f"{symbol}: no price was given and no last traded price is available")
            continue
        leg = {
            "exchangeSegment": segment,
            "transactionType": str(pos.get("action", "BUY")).upper(),
            "quantity": int(pos.get("quantity", 0) or 0),
            "productType": map_product_type(pos.get("product", "MIS")),
            "securityId": str(token),
            "price": price,
        }
        trigger = float(pos.get("trigger_price", 0) or 0)
        if trigger > 0:
            leg["triggerPrice"] = trigger
        scrips.append(leg)
    return scrips, skipped


def parse_margin_response(body):
    """SMIFS multi-margin response -> OpenAlgo's standard margin dict."""
    legs = body.get("legs") or []
    return {
        "status": "success",
        "data": {
            "total_margin_required": float(body.get("totalMargin", 0) or 0),
            "span_margin": sum(float(leg.get("spanMargin", 0) or 0) for leg in legs),
            "exposure_margin": sum(float(leg.get("exposureMargin", 0) or 0) for leg in legs),
            "margin_benefit": float(body.get("benefitAmount", 0) or 0),
            "available_balance": float(body.get("availableBalance", 0) or 0),
            "insufficient_balance": float(body.get("insufficientBalance", 0) or 0),
        },
    }
