"""
GEX (Gamma Exposure) Service
Computes Gamma Exposure across strikes using live option chain data + Black-76 model.

GEX = gamma * open_interest * lot_size
Net GEX = Call GEX - Put GEX
"""

from typing import Any

from services.oi_tracker_service import _get_nearest_futures_price
from services.option_chain_service import get_option_chain
from services.option_greeks_service import calculate_greeks
from utils.logging import get_logger

logger = get_logger(__name__)


def get_gex_data(
    underlying: str, exchange: str, expiry_date: str, api_key: str
) -> tuple[bool, dict[str, Any], int]:
    """
    Get Gamma Exposure data for all strikes.

    Fetches option chain, computes gamma for each CE/PE using Black-76,
    then calculates GEX = gamma * OI * lotsize.

    Returns OI walls (raw CE/PE OI) and Net GEX per strike.

    Args:
        underlying: Underlying symbol (e.g., NIFTY, BANKNIFTY)
        exchange: Exchange (NFO, BFO)
        expiry_date: Expiry in DDMMMYY format
        api_key: OpenAlgo API key

    Returns:
        Tuple of (success, response_data, status_code)
    """
    try:
        # Fetch option chain (45 strikes around ATM)
        success, chain_response, status_code = get_option_chain(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            strike_count=45,
            api_key=api_key,
        )

        if not success:
            return False, chain_response, status_code

        full_chain = chain_response.get("chain", [])
        atm_strike = chain_response.get("atm_strike")
        spot_price = chain_response.get("underlying_ltp")

        if not spot_price or spot_price <= 0:
            return False, {"status": "error", "message": "Could not determine spot price"}, 500

        # Determine options exchange for symbol parsing
        options_exchange = exchange.upper()
        if options_exchange in ("NSE_INDEX", "NSE"):
            options_exchange = "NFO"
        elif options_exchange in ("BSE_INDEX", "BSE"):
            options_exchange = "BFO"

        lot_size = None
        gex_chain = []

        for item in full_chain:
            strike = item["strike"]
            ce = item.get("ce")
            pe = item.get("pe")

            ce_oi = 0
            pe_oi = 0
            ce_gex = 0
            pe_gex = 0
            ce_gamma = 0
            pe_gamma = 0
            current_lotsize = 1

            # Process CE
            if ce and ce.get("symbol"):
                ce_oi = ce.get("oi", 0) or 0
                ce_ltp = ce.get("ltp", 0) or 0
                current_lotsize = ce.get("lotsize", 1) or 1
                if lot_size is None:
                    lot_size = current_lotsize

                if ce_ltp > 0 and ce_oi > 0:
                    try:
                        ok, greeks_resp, _ = calculate_greeks(
                            option_symbol=ce["symbol"],
                            exchange=options_exchange,
                            spot_price=spot_price,
                            option_price=ce_ltp,
                        )
                        if ok and greeks_resp.get("status") == "success":
                            greeks = greeks_resp.get("greeks", {})
                            ce_gamma = greeks.get("gamma", 0) or 0
                            ce_gex = ce_gamma * ce_oi * current_lotsize
                    except Exception:
                        pass

            # Process PE
            if pe and pe.get("symbol"):
                pe_oi = pe.get("oi", 0) or 0
                pe_ltp = pe.get("ltp", 0) or 0
                current_lotsize = pe.get("lotsize", 1) or 1
                if lot_size is None:
                    lot_size = current_lotsize

                if pe_ltp > 0 and pe_oi > 0:
                    try:
                        ok, greeks_resp, _ = calculate_greeks(
                            option_symbol=pe["symbol"],
                            exchange=options_exchange,
                            spot_price=spot_price,
                            option_price=pe_ltp,
                        )
                        if ok and greeks_resp.get("status") == "success":
                            greeks = greeks_resp.get("greeks", {})
                            pe_gamma = greeks.get("gamma", 0) or 0
                            pe_gex = pe_gamma * pe_oi * current_lotsize
                    except Exception:
                        pass

            net_gex = ce_gex - pe_gex

            gex_chain.append(
                {
                    "strike": strike,
                    "ce_oi": ce_oi,
                    "pe_oi": pe_oi,
                    "ce_gamma": round(ce_gamma, 6),
                    "pe_gamma": round(pe_gamma, 6),
                    "ce_gex": round(ce_gex, 2),
                    "pe_gex": round(pe_gex, 2),
                    "net_gex": round(net_gex, 2),
                }
            )

        # Get futures price
        futures_price = _get_nearest_futures_price(
            underlying=underlying,
            exchange=exchange,
            expiry_date=expiry_date,
            api_key=api_key,
        )

        # Compute totals
        total_ce_oi = sum(item["ce_oi"] for item in gex_chain)
        total_pe_oi = sum(item["pe_oi"] for item in gex_chain)
        total_ce_gex = sum(item["ce_gex"] for item in gex_chain)
        total_pe_gex = sum(item["pe_gex"] for item in gex_chain)
        total_net_gex = sum(item["net_gex"] for item in gex_chain)
        pcr_oi = round(total_pe_oi / total_ce_oi, 2) if total_ce_oi > 0 else 0

        return (
            True,
            {
                "status": "success",
                "underlying": chain_response.get("underlying", underlying),
                "spot_price": spot_price,
                "futures_price": futures_price,
                "lot_size": lot_size or 1,
                "atm_strike": atm_strike,
                "expiry_date": expiry_date,
                "pcr_oi": pcr_oi,
                "total_ce_oi": total_ce_oi,
                "total_pe_oi": total_pe_oi,
                "total_ce_gex": round(total_ce_gex, 2),
                "total_pe_gex": round(total_pe_gex, 2),
                "total_net_gex": round(total_net_gex, 2),
                "chain": gex_chain,
            },
            200,
        )

    except Exception as e:
        logger.exception(f"Error in get_gex_data: {e}")
        return (
            False,
            {"status": "error", "message": "Error fetching GEX data"},
            500,
        )
