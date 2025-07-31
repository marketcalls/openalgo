# api/funds.py
import urllib.parse
import http.client
import json
from utils.logging import get_logger

logger = get_logger(__name__)


def get_margin_data(auth_token):
    """Fetch margin data from the broker's API using the provided auth token."""
    access_token_parts = auth_token.split(":::")
    token = access_token_parts[0]
    sid = access_token_parts[1]
    hsServerId = access_token_parts[2]
    access_token = access_token_parts[3]
    
    conn = http.client.HTTPSConnection("gw-napi.kotaksecurities.com")
    payload = 'jData=%7B%22seg%22%3A%22ALL%22%2C%22exch%22%3A%22ALL%22%2C%22prod%22%3A%22ALL%22%7D'
    query_params = {"sId": hsServerId}
    headers = {
    'accept': 'application/json',
    'Sid': sid,
    'Auth': token,
    'neo-fin-key': 'neotradeapi',
    'Content-Type': 'application/x-www-form-urlencoded',
    'Authorization': f'Bearer {access_token}'
    }
    conn.request("POST", "/Orders/2.0/quick/user/limits?" + urllib.parse.urlencode(query_params), payload, headers)
    try:
        res = conn.getresponse()
        data = res.read()
        logger.info(f"{data.decode('utf-8')}")
        margin_data = json.loads(data.decode("utf-8"))

        #logger.info(f"Margin Data {margin_data}")

        # Process and return the 'data' key from margin_data if it exists and is not None
        
        #TODO FIX realized and unrealized
        processed_margin_data = {
                "availablecash": f"{float(margin_data['Net']):.2f}",
                "collateral": f"{float(margin_data['Collateral']):.2f}",
                "m2munrealized": f"{(-float(margin_data['CurUnRlsMtomPrsnt'])+float(margin_data['ComUnRlsMtomPrsnt'])+float(margin_data['FoUnRlsMtomPrsnt'])+float(margin_data['CashUnRlsMtomPrsnt']))*-1}",
                "m2mrealized": f"{(-float(margin_data['CurRlsMtomPrsnt'])+float(margin_data['ComRlsMtomPrsnt'])+float(margin_data['FoRlsMtomPrsnt'])+float(margin_data['CashRlsMtomPrsnt']))*-1}",
                "utiliseddebits": f"{round(((float(margin_data['CurRlsMtomPrsnt'])+float(margin_data['ComRlsMtomPrsnt'])+float(margin_data['FoRlsMtomPrsnt'])+float(margin_data['CashRlsMtomPrsnt']))*-1)-(float(margin_data['MarginUsed'])*-1)-(float(margin_data['RealizedMtomPrsnt'])*-1),2)}"
            }
        return processed_margin_data
    except Exception as e:
        logger.error(f"Error fetching margin data: {e}")
        return {}
