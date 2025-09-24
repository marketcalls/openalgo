# api/funds.py

import os
import socket
import uuid
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

def get_client_ip():
    """Get the client's local IP address"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"

def get_mac_address():
    """Get the MAC address of the machine"""
    try:
        mac = ':'.join(['{:02x}'.format((uuid.getnode() >> ele) & 0xff) for ele in range(0,8*6,8)][::-1])
        return mac
    except:
        return "00:00:00:00:00:00"

def get_margin_data(auth_token):
    """Fetch margin data from Motilal Oswal API using the provided auth token."""
    api_key = os.getenv('BROKER_API_KEY')
    
    if not api_key:
        logger.error("BROKER_API_KEY environment variable not set")
        return {}
    
    try:
        # Get the shared httpx client with connection pooling
        client = get_httpx_client()
        
        # Get system information for headers
        client_local_ip = get_client_ip()
        mac_address = get_mac_address()
        
        # Set headers as per Motilal Oswal API documentation
        headers = {
            'Accept': 'application/json',
            'User-Agent': 'MOSL/V.1.1.0',
            'Authorization': auth_token,  # Use auth token in Authorization header
            'ApiKey': api_key,
            'ClientLocalIp': client_local_ip,
            'ClientPublicIp': client_local_ip,
            'MacAddress': mac_address,
            'SourceId': 'WEB',
            'vendorinfo': 'CLIENT',  # Generic vendor info for margin calls
            'osname': 'Windows 10',
            'osversion': '10.0.19041',
            'devicemodel': 'AHV',
            'manufacturer': 'DELL',
            'productname': 'OpenAlgo Trading Platform',
            'productversion': '1.0',
            'browsername': 'Chrome',
            'browserversion': '105.0',
            'Content-Type': 'application/json'
        }
        
        # Use production or UAT URL based on environment
        is_testing = os.getenv('MOTILAL_USE_UAT', 'false').lower() == 'true'
        if is_testing:
            margin_url = "https://openapi.motilaloswaluat.com/rest/report/v1/getreportmarginsummary"
        else:
            margin_url = "https://openapi.motilaloswal.com/rest/report/v1/getreportmarginsummary"
        
        logger.info(f"Fetching margin data from Motilal Oswal: {margin_url}")
        
        # For regular clients, send empty body. For dealers, would need clientcode
        response = client.post(margin_url, headers=headers, json={})
        
        logger.debug(f"Motilal margin response status: {response.status_code}")
        
        if response.status_code == 200:
            margin_data = response.json()
            logger.info(f"Margin Data received: {margin_data}")
            
            if margin_data.get('status') == 'SUCCESS' and margin_data.get('data'):
                # Parse Motilal Oswal margin summary data
                margin_items = margin_data['data']
                
                # Initialize values
                available_cash = 0.0
                collateral = 0.0
                total_margin_usage = 0.0
                mtm_pnl = 0.0
                bpl_pnl = 0.0
                
                # Parse the margin data based on srno (serial numbers)
                for item in margin_items:
                    srno = item.get('srno', 0)
                    amount = float(item.get('amount', 0))
                    
                    # Total Available Margin for Cash (srno: 102)
                    if srno == 102:
                        available_cash = amount
                    
                    # Non cash deposit - can be considered as collateral (srno: 220)
                    elif srno == 220:
                        collateral = amount
                    
                    # Total Margin Usage - sum of all usage types
                    elif srno in [301, 321, 340, 360, 381]:  # Cash, FO, Currency, Commodity, Brokerage
                        total_margin_usage += amount
                    
                    # Total Profit and Loss(MTM) (srno: 600)
                    elif srno == 600:
                        mtm_pnl = amount
                    
                    # Total Profit and Loss(BPL) (srno: 700)  
                    elif srno == 700:
                        bpl_pnl = amount
                
                # Map to OpenAlgo standard format
                filtered_data = {
                    "availablecash": "{:.2f}".format(available_cash),
                    "collateral": "{:.2f}".format(collateral),
                    "m2mrealized": "{:.2f}".format(bpl_pnl),  # BPL is realized P&L
                    "m2munrealized": "{:.2f}".format(mtm_pnl),  # MTM is unrealized P&L
                    "utiliseddebits": "{:.2f}".format(total_margin_usage)
                }
                
                logger.info(f"Processed margin data: {filtered_data}")
                return filtered_data
            else:
                logger.warning(f"Motilal margin API returned unsuccessful response: {margin_data}")
                # Return basic default data to prevent auth loop
                return {
                    "availablecash": "0.00",
                    "collateral": "0.00", 
                    "m2mrealized": "0.00",
                    "m2munrealized": "0.00",
                    "utiliseddebits": "0.00"
                }
        else:
            logger.error(f"Motilal margin API error: HTTP {response.status_code} - {response.text}")
            # Return basic default data to prevent auth loop
            return {
                "availablecash": "0.00",
                "collateral": "0.00",
                "m2mrealized": "0.00", 
                "m2munrealized": "0.00",
                "utiliseddebits": "0.00"
            }
            
    except Exception as e:
        logger.error(f"Error fetching Motilal margin data: {str(e)}")
        # Return basic default data to prevent auth loop
        return {
            "availablecash": "0.00",
            "collateral": "0.00",
            "m2mrealized": "0.00",
            "m2munrealized": "0.00", 
            "utiliseddebits": "0.00"
        }
