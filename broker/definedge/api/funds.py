import http.client
import json
from utils.logging import get_logger

logger = get_logger(__name__)

def get_margin_data(auth_token):
    """Get margin data from DefinedGe Securities"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        conn.request("GET", "/dart/v1/limits", '', headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        response_data = json.loads(data)

        # Transform to OpenAlgo format
        # DefinedGe returns data directly in the response, not nested under 'data'
        if response_data.get('status') == '200' or 'cash' in response_data:
            # Map DefinedGe margin fields to OpenAlgo format
            formatted_data = {
                'availablecash': response_data.get('cash', '0'),
                'collateral': response_data.get('collateral', '0'),
                'm2munrealized': response_data.get('m2munrealized', '0'),
                'm2mrealized': response_data.get('m2mrealized', '0'),
                'openingbalance': response_data.get('cash', '0'),
                'payin': response_data.get('payin', '0'),
                'payout': response_data.get('payout', '0'),
                'utiliseddebits': response_data.get('marginUsed', '0'),
                'utilisedpayout': response_data.get('payout', '0')
            }

            return formatted_data
        else:
            logger.error(f"Failed to get margin data: {response_data}")
            return {}

    except Exception as e:
        logger.error(f"Error getting margin data: {e}")
        return {}

def get_limits_data(auth_token):
    """Get limits data from DefinedGe Securities"""
    try:
        api_session_key, susertoken, api_token = auth_token.split(":::")

        conn = http.client.HTTPSConnection("integrate.definedgesecurities.com")

        headers = {
            'Authorization': api_session_key,
            'Content-Type': 'application/json'
        }

        conn.request("GET", "/dart/v1/limits", '', headers)
        res = conn.getresponse()
        data = res.read().decode("utf-8")

        response_data = json.loads(data)

        # Transform to OpenAlgo format
        if response_data.get('status') == 'SUCCESS':
            limits_data = response_data.get('data', {})

            formatted_data = {
                'equity': {
                    'available': limits_data.get('equity_available', '0'),
                    'used': limits_data.get('equity_used', '0')
                },
                'commodity': {
                    'available': limits_data.get('commodity_available', '0'),
                    'used': limits_data.get('commodity_used', '0')
                }
            }

            return formatted_data
        else:
            logger.error(f"Failed to get limits data: {response_data}")
            return {}

    except Exception as e:
        logger.error(f"Error getting limits data: {e}")
        return {}
