# Mapping OpenAlgo API Request https://openalgo.in/docs
# Mapping 5paisa Margin API https://xstream.5paisa.com/dev-docs/funds-management-system/margin

from utils.logging import get_logger

logger = get_logger(__name__)

def parse_margin_response(response_data):
    """
    Parse 5paisa margin response to OpenAlgo standard format.

    Note: 5paisa Margin API returns account-level margin information,
    not position-specific margin calculations like other brokers.

    Args:
        response_data: Raw response from 5paisa API

    Returns:
        Standardized margin response
    """
    try:
        if not response_data or not isinstance(response_data, dict):
            return {
                'status': 'error',
                'message': 'Invalid response from broker'
            }

        # Check head status
        head = response_data.get('head', {})
        if head.get('status') != '0':
            error_message = head.get('statusDescription', 'Failed to retrieve margin')
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract body data
        body = response_data.get('body', {})

        # Check body status
        if body.get('Status') != 0:
            error_message = body.get('Message', 'Failed to retrieve margin')
            return {
                'status': 'error',
                'message': error_message
            }

        # Extract equity margin (first element of array)
        equity_margin = body.get('EquityMargin', [])
        if not equity_margin or len(equity_margin) == 0:
            return {
                'status': 'error',
                'message': 'No equity margin data available'
            }

        margin_data = equity_margin[0]

        # Extract MF margin (first element of array)
        mf_margin_data = {}
        mf_margin = body.get('MFMargin', [])
        if mf_margin and len(mf_margin) > 0:
            mf_margin_data = mf_margin[0]

        # Return standardized format
        # Note: This is account-level margin, not position-specific
        return {
            'status': 'success',
            'data': {
                'available_margin': margin_data.get('NetAvailableMargin', 0),
                'margin_utilized': margin_data.get('MarginUtilized', 0),
                'collateral_value': margin_data.get('CollateralValueAfterHairCut', 0),
                'ledger_balance': margin_data.get('Ledgerbalance', 0),
                'margin_blocked_orders': margin_data.get('MarginBlockedForPendingOrders', 0),
                'margin_blocked_positions_cash': margin_data.get('MarginBlockedforOpenPostion_Cash', 0),
                'margin_blocked_positions_collateral': margin_data.get('MarginBlockedforOpenPostion_Collateral', 0),
                'gross_holding_value': margin_data.get('GrossHoldingValue', 0),
                'options_premium': margin_data.get('OptionsPremium', 0),
                'unsettled_credits': margin_data.get('Unsettled_Credits', 0),
                'mf_collateral_value': mf_margin_data.get('MFCollateralValue', 0),
                'mf_free_stock_value': mf_margin_data.get('MFFreeStockValue', 0),
                'note': '5paisa returns account-level margin, not position-specific calculations',
                'raw_response': {
                    'equity_margin': margin_data,
                    'mf_margin': mf_margin_data
                }
            }
        }

    except Exception as e:
        logger.error(f"Error parsing margin response: {e}")
        return {
            'status': 'error',
            'message': f'Failed to parse margin response: {str(e)}'
        }
