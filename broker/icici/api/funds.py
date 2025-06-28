# api/funds.py

from breeze_connect import BreezeConnect
from broker.icici.api.auth_api import login_breeze
import logging
import os

logger = logging.getLogger(__name__)

def get_margin_data(api_key: str, api_secret: str, totp: str = None) -> dict:
    """
    Fetch margin (funds) data from ICICI Breeze.
    
    Parameters:
        api_key (str): ICICI Breeze App Key
        api_secret (str): API Secret
        totp (str): Optional TOTP if required
    
    Returns:
        dict: Funds summary in unified format
    """
    try:
        breeze = BreezeConnect(api_key=api_key)
        breeze.generate_session(api_secret=api_secret)
        if totp:
            breeze.set_totp(totp)

        # Breeze does not have a direct `funds` endpoint like some brokers.
        # But we can mimic the funds display using balance + P&L summary
        positions = breeze.get_positions()
        logger.info("Fetched positions for margin summary")

        total_realised = 0
        total_unrealised = 0
        if isinstance(positions, list):
            for p in positions:
                total_realised += float(p.get("realized_profit", 0))
                total_unrealised += float(p.get("unrealized_profit", 0))

        # Breeze does not directly return available cash; using placeholder or custom logic
        # You may replace below with your own call if Breeze adds a fund summary endpoint
        processed_margin_data = {
            "availablecash": "0.00",  # Not provided
            "collateral": "0.00",     # Not provided
            "m2munrealized": f"{total_unrealised:.2f}",
            "m2mrealized": f"{total_realised:.2f}",
            "utiliseddebits": "0.00"  # Not provided
        }
        return processed_margin_data

    except Exception as e:
        logger.error(f"Error fetching margin data from ICICI Breeze: {str(e)}")
        return {}
