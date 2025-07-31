import requests
import json
import threading
import time
import websocket
import struct
from broker.pocketful.api.packet_decoder import decodeDetailedMarketData, decodeCompactMarketData, decodeSnapquoteData, decodeOrderUpdate, decodeTradeUpdate
from utils.logging import get_logger

logger = get_logger(__name__)


# Configure logging
logger = get_logger(__name__)

# Global variables for WebSocket communication
websock = None
ws_connected = False
ws_connect_lock = threading.Lock()  # Lock for thread-safe socket operations
snapquote_marketdata_response = {}
compact_marketdata_response = {}
detailed_marketdata_response = {}
order_update_response = {}
trade_update_response = {}
dtlmktdata_dict = {}
cmptmktdata_dict = {}
snpqtdata_dict = {}

# WebSocket message handlers
def on_message(ws, message):
    try:
        # Try to parse as JSON first
        try:
            data = json.loads(message)
            if isinstance(data, dict) and 'mode' in data:
                mode = data['mode']
            else:
                # If no mode in JSON, try binary parsing
                mode = struct.unpack('>b', message[0:1])[0]
        except:
            # If JSON parsing fails, assume binary
            mode = struct.unpack('>b', message[0:1])[0]
            
        # Process based on message mode
        if mode == 1:  # Detailed market data
            res = decodeDetailedMarketData(message)
            global detailed_marketdata_response, dtlmktdata_dict
            detailed_marketdata_response = res
            if bool(res):
                key = str(res["instrument_token"]) + "_" + str(res["exchange_code"])
                dtlmktdata_dict[key] = res
                
        elif mode == 2:  # Compact market data
            res = decodeCompactMarketData(message)
            global compact_marketdata_response, cmptmktdata_dict
            compact_marketdata_response = res
            if bool(res):
                key = str(res["instrument_token"]) + "_" + str(res["exchange_code"])
                cmptmktdata_dict[key] = res
                
        elif mode == 4:  # Snapquote data
            res = decodeSnapquoteData(message)
            global snapquote_marketdata_response, snpqtdata_dict
            snapquote_marketdata_response = res
            if bool(res):
                key = str(res["instrument_token"]) + "_" + str(res["exchange_code"])
                snpqtdata_dict[key] = res
                
        elif mode == 50:  # Order updates
            res = decodeOrderUpdate(message)
            global order_update_response
            order_update_response = res
            
        elif mode == 51:  # Trade updates
            res = decodeTradeUpdate(message)
            global trade_update_response
            trade_update_response = res
            
    except Exception as e:
        logger.error(f"Error processing WebSocket message: {str(e)}")

def on_error(ws, error):
    logger.error(f"WebSocket error: {str(error)}")
    global ws_connected
    ws_connected = False

def on_close(ws, close_status_code=None, close_msg=None):
    logger.info(f"WebSocket connection closed: code={close_status_code}, message={close_msg}")
    global ws_connected
    ws_connected = False

def on_open(ws):
    logger.info("WebSocket connection established")
    # Start heartbeat thread
    hb_thread = threading.Thread(target=heartbeat_thread, args=(ws,))
    hb_thread.daemon = True
    hb_thread.start()
    global ws_connected
    ws_connected = True

def heartbeat_thread(client_socket):
    """Send periodic heartbeats to keep the connection alive"""
    while True:
        try:
            if ws_connected and client_socket and client_socket.sock and client_socket.sock.connected:
                client_socket.send(json.dumps({"a": "h"}))
                logger.debug("Heartbeat sent")
            else:
                logger.debug("Skipping heartbeat, socket not connected")
            time.sleep(15)  # Send heartbeat every 15 seconds (reduced from 20)
        except Exception as e:
            logger.error(f"Error in heartbeat: {str(e)}")
            time.sleep(5)  # Wait a bit before retrying on error
        time.sleep(8)

def get_snapquotedata():
    """Get the latest snapquote data"""
    return snapquote_marketdata_response

def get_compact_marketdata():
    """Get the latest compact market data"""
    return compact_marketdata_response

def get_detailed_marketdata():
    """Get the latest detailed market data"""
    return detailed_marketdata_response

def get_order_update():
    """Get the latest order update"""
    return order_update_response

def get_trade_update():
    """Get the latest trade update"""
    return trade_update_response

def get_multiple_detailed_marketdata():
    """Get multiple detailed market data"""
    return dtlmktdata_dict

def get_multiple_compact_marketdata():
    """Get multiple compact market data"""
    return cmptmktdata_dict

def get_multiple_snapquotedata():
    """Get multiple snapquote data"""
    return snpqtdata_dict

def get_ws_connection_status():
    """Check if WebSocket is connected"""
    return ws_connected

class PocketfulSocket(object):
    base_url = "https://trade.pocketful.in"
    
    def __init__(self, client_id, access_token):
        self.headers = {'Content-type': 'application/json'}
        self.access_token = access_token
        self.client_id = client_id
        
        # Generate WebSocket URL
        if "https" in self.base_url:
            url = self.base_url.replace("https", "wss")
        else:
            url = self.base_url.replace("http", "ws")
        self.websocket_url = url



    def print_access_token(self):
        return self.access_token

    def set_access_token(self, access_token):
        self.access_token = access_token

    def get_request(self, url, params):
        headers = self.headers
        headers['Authorization'] = f'Bearer {self.access_token}'
        res = requests.get(f'{self.base_url}{url}' , params=params, headers=headers)
        return res.json()

    def post_request(self, url, data):
        headers = self.headers
        headers['Authorization'] = f'Bearer {self.access_token}'
        res = requests.post(f'{self.base_url}{url}', headers=headers, data=json.dumps(data))
        logger.info(f"{res}")
        return res.json()

    def put_request(self, url, data):
        headers = self.headers
        headers['Authorization'] = f'Bearer {self.access_token}'
        res = requests.put(f'{self.base_url}{url}', headers=headers, data=json.dumps(data))
        logger.info(f"{res}")
        return res.json()

    def delete_request(self, url, params):
        headers = self.headers
        headers['Authorization'] = f'Bearer {self.access_token}'
        res = requests.delete(f'{self.base_url}{url}' , params=params, headers=headers)
        return res.json()

    

    def run_socket(self):
        """Connect to the WebSocket server with proper thread safety"""
        global websock, ws_connected, ws_connect_lock
        
        # Use a lock to prevent multiple simultaneous connection attempts
        with ws_connect_lock:
            # Check if we already have a working connection
            if websock and ws_connected:
                logger.info("WebSocket already connected, reusing existing connection")
                return True
                
            # If we have a socket but it's not connected, close it properly
            if websock and not ws_connected:
                try:
                    logger.info("Closing stale WebSocket connection")
                    websock.close()
                    time.sleep(1)  # Small delay to ensure socket closes
                except Exception as e:
                    logger.warning(f"Error closing stale connection: {str(e)}")
                websock = None
            
            try:
                client_id = self.client_id
                access_token = self.access_token
                websocket_url = self.websocket_url
                
                # Create WebSocket connection URL
                full_url = f'{websocket_url}/ws/v1/feeds?login_id={client_id}&access_token={access_token}'
                logger.info(f"Connecting to WebSocket: {full_url}")
                
                # Connect to WebSocket
                websock = self._connect(full_url)
                
                # Start WebSocket in a thread
                ws_thread = threading.Thread(target=self._webs_start, args=(websock,))
                ws_thread.daemon = True
                ws_thread.start()
                
                # Wait for connection to establish with increased timeout
                counter = 0
                max_attempts = 10  # Increased from 5
                while counter < max_attempts:
                    status = get_ws_connection_status()
                    if status:
                        logger.info("WebSocket connection successful")
                        return True
                    time.sleep(0.5)  # Shorter interval checks
                    counter += 1
                    
                logger.error("Failed to establish WebSocket connection (timeout)")
                return False
                
            except Exception as e:
                logger.error(f"WebSocket connection error: {str(e)}")
                return False
            
    def _connect(self, url):
        """Create WebSocket connection"""
        websocket.enableTrace(False)
        ws = websocket.WebSocketApp(url,
                                   on_message=on_message,
                                   on_error=on_error,
                                   on_close=on_close)
        ws.on_open = on_open
        return ws
        
    def _webs_start(self, ws):
        """Start WebSocket connection"""
        ws.run_forever()


    def subscribe_detailed_marketdata(self, detailedmarketdata_payload):
        """Subscribe to detailed market data"""
        try:
            subscription_pkt = [[detailedmarketdata_payload['exchangeCode'], detailedmarketdata_payload['instrumentToken']]]
            global websock
            sub_packet = {
                "a": "subscribe",
                "v": subscription_pkt,
                "m": "marketdata"
            }
            websock.send(json.dumps(sub_packet))
            logger.info(f"Subscribed to detailed market data: {detailedmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to detailed market data: {str(e)}")
            return False

    def read_detailed_marketdata(self):
        """Read the latest detailed market data"""
        data = get_detailed_marketdata()
        return data

    def unsubscribe_detailed_marketdata(self, detailedmarketdata_payload):
        """Unsubscribe from detailed market data"""
        try:
            unsubscription_pkt = [[detailedmarketdata_payload['exchangeCode'], detailedmarketdata_payload['instrumentToken']]]
            global websock
            sub_packet = {
                "a": "unsubscribe",
                "v": unsubscription_pkt,
                "m": "marketdata"
            }
            websock.send(json.dumps(sub_packet))
            # Clear data
            global detailed_marketdata_response, dtlmktdata_dict
            detailed_marketdata_response = {}
            dtlmktdata_dict = {}
            logger.info(f"Unsubscribed from detailed market data: {detailedmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from detailed market data: {str(e)}")
            return False


    def subscribe_compact_marketdata(self, compactmarketdata_payload):
        """Subscribe to compact market data with reconnection support"""
        global websock, ws_connected
        
        # Try to subscribe up to 3 times
        for attempt in range(3):
            try:
                # Check if we need to reconnect
                if not ws_connected or not websock or not hasattr(websock, 'sock') or not websock.sock or not getattr(websock.sock, 'connected', False):
                    logger.warning(f"WebSocket not connected on attempt {attempt+1}, reconnecting...")
                    self.run_socket()
                    time.sleep(1)  # Give it time to connect
                    
                if not ws_connected:
                    logger.error("Failed to reconnect WebSocket")
                    continue  # Try again
                
                # Proceed with subscription
                subscription_pkt = [[compactmarketdata_payload['exchangeCode'], compactmarketdata_payload['instrumentToken']]]
                sub_packet = {
                    "a": "subscribe",
                    "v": subscription_pkt,
                    "m": "compact_marketdata"
                }
                websock.send(json.dumps(sub_packet))
                logger.info(f"Subscribed to compact market data: {compactmarketdata_payload}")
                return True
                
            except Exception as e:
                logger.error(f"Error subscribing to compact market data (attempt {attempt+1}): {str(e)}")
                # Force reconnection on next attempt
                ws_connected = False
                time.sleep(0.5 * (attempt + 1))  # Increasing backoff
        
        # If we get here, all attempts failed
        return False

    def unsubscribe_compact_marketdata(self, compactmarketdata_payload):
        """Unsubscribe from compact market data with error handling"""
        global websock, ws_connected, compact_marketdata_response, cmptmktdata_dict
        
        try:
            # Only attempt to unsubscribe if we have a connection
            if not ws_connected or not websock or not hasattr(websock, 'sock') or not websock.sock or not getattr(websock.sock, 'connected', False):
                logger.warning("Cannot unsubscribe from compact market data, WebSocket not connected")
                # Still clear data even if we can't unsubscribe
                compact_marketdata_response = {}
                cmptmktdata_dict = {}
                return False
                
            unsubscription_pkt = [[compactmarketdata_payload['exchangeCode'], compactmarketdata_payload['instrumentToken']]]
            sub_packet = {
                "a": "unsubscribe",
                "v": unsubscription_pkt,
                "m": "compact_marketdata"
            }
            websock.send(json.dumps(sub_packet))
            
            # Clear data
            compact_marketdata_response = {}
            cmptmktdata_dict = {}
            
            logger.info(f"Unsubscribed from compact market data: {compactmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from compact market data: {str(e)}")
            # Still clear data even on error
            compact_marketdata_response = {}
            cmptmktdata_dict = {}
            return False
    
    def read_compact_marketdata(self):
        """Read the latest compact market data"""
        data = get_compact_marketdata()
        return data

    def subscribe_snapquote_data(self, snapquotedata_payload):
        """Subscribe to snapquote data with reconnection support"""
        global websock, ws_connected
        
        # Try to subscribe up to 3 times
        for attempt in range(3):
            try:
                # Check if we need to reconnect
                if not ws_connected or not websock or not websock.sock or not websock.sock.connected:
                    logger.warning(f"WebSocket not connected on attempt {attempt+1}, reconnecting...")
                    self.run_socket()
                    time.sleep(1)  # Give it time to connect
                    
                if not ws_connected:
                    logger.error("Failed to reconnect WebSocket")
                    continue  # Try again
                
                # Proceed with subscription
                subscription_pkt = [[snapquotedata_payload['exchangeCode'], snapquotedata_payload['instrumentToken']]]
                sub_packet = {
                    "a": "subscribe",
                    "v": subscription_pkt,
                    "m": "full_snapquote"  # Try full_snapquote instead of snapquote
                }
                websock.send(json.dumps(sub_packet))
                logger.info(f"Subscribed to snapquote data: {snapquotedata_payload}")
                return True
                
            except Exception as e:
                logger.error(f"Error subscribing to snapquote data (attempt {attempt+1}): {str(e)}")
                # Force reconnection on next attempt
                ws_connected = False
                time.sleep(0.5 * (attempt + 1))  # Increasing backoff
        
        # If we get here, all attempts failed
        return False
    
    def unsubscribe_snapquote_data(self, snapquotedata_payload):
        """Unsubscribe from snapquote data with error handling"""
        global websock, ws_connected, snapquote_marketdata_response, snpqtdata_dict
        
        try:
            # Only attempt to unsubscribe if we have a connection
            if not ws_connected or not websock or not hasattr(websock, 'sock') or not websock.sock or not getattr(websock.sock, 'connected', False):
                logger.warning("Cannot unsubscribe, WebSocket not connected")
                # Still clear data even if we can't unsubscribe
                snapquote_marketdata_response = {}
                snpqtdata_dict = {}
                return False
                
            unsubscription_pkt = [[snapquotedata_payload['exchangeCode'], snapquotedata_payload['instrumentToken']]]
            sub_packet = {
                "a": "unsubscribe",
                "v": unsubscription_pkt,
                "m": "full_snapquote"  # Match subscription mode
            }
            websock.send(json.dumps(sub_packet))
            
            # Clear data
            snapquote_marketdata_response = {}
            snpqtdata_dict = {}
            
            logger.info(f"Unsubscribed from snapquote data: {snapquotedata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from snapquote data: {str(e)}")
            # Still clear data even on error
            snapquote_marketdata_response = {}
            snpqtdata_dict = {}
            return False

    def read_snapquote_data(self):
        """Read the latest snapquote data"""
        data = get_snapquotedata()
        return data

    def subscribe_order_update(self, orderupdate_payload):
        subscription_pkt = [orderupdate_payload['client_id'], "web"]
        th_order_update = threading.Thread(target=send_message, args=('OrderUpdateMessage', subscription_pkt))
        th_order_update.start()
    
    def unsubscribe_order_update(self, orderupdate_payload):
        unsubscription_pkt = [orderupdate_payload['client_id'], "web"]
        th_order_update = threading.Thread(target=unsubscribe_update, args=('OrderUpdateMessage', unsubscription_pkt))
        th_order_update.start()

    def read_order_update_data(self):
        data = get_order_update()
        return data
    
    def subscribe_trade_update(self, tradeupdate_payload):
        subscription_pkt = [tradeupdate_payload['client_id'], "web"]
        th_trade_update = threading.Thread(target=send_message, args=('TradeUpdateMessage', subscription_pkt))
        th_trade_update.start()
    
    def unsubscribe_trade_update(self, tradeupdate_payload):
        unsubscription_pkt = [tradeupdate_payload['client_id'], "web"]
        th_trade_update = threading.Thread(target=unsubscribe_update, args=('OrderUpdateMessage', unsubscription_pkt))
        th_trade_update.start()

    def read_trade_update_data(self):
        data = get_trade_update()
        return data

    def subscribe_multiple_detailed_marketdata(self, detailedmarketdata_payload):
        """Subscribe to multiple detailed market data"""
        try:
            subscription_pkt = []
            for payload in detailedmarketdata_payload:
                pkt = [payload['exchangeCode'], payload['instrumentToken']]
                subscription_pkt.append(pkt)
                
            global websock
            sub_packet = {
                "a": "subscribe",
                "v": subscription_pkt,
                "m": "marketdata"
            }
            websock.send(json.dumps(sub_packet))
            logger.info(f"Subscribed to multiple detailed market data: {detailedmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to multiple detailed market data: {str(e)}")
            return False

    def unsubscribe_multiple_detailed_marketdata(self, detailedmarketdata_payload):
        """Unsubscribe from multiple detailed market data"""
        try:
            unsubscription_pkt = []
            for payload in detailedmarketdata_payload:
                pkt = [payload['exchangeCode'], payload['instrumentToken']]
                unsubscription_pkt.append(pkt)
                
            global websock
            sub_packet = {
                "a": "unsubscribe",
                "v": unsubscription_pkt,
                "m": "marketdata"
            }
            websock.send(json.dumps(sub_packet))
            # Clear data
            global detailed_marketdata_response, dtlmktdata_dict
            detailed_marketdata_response = {}
            dtlmktdata_dict = {}
            logger.info(f"Unsubscribed from multiple detailed market data: {detailedmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from multiple detailed market data: {str(e)}")
            return False

    def read_multiple_detailed_marketdata(self):
        """Read multiple detailed market data"""
        data = get_multiple_detailed_marketdata()
        return data

    def subscribe_multiple_compact_marketdata(self, compactmarketdata_payload):
        """Subscribe to multiple compact market data"""
        try:
            subscription_pkt = []
            for payload in compactmarketdata_payload:
                pkt = [payload['exchangeCode'], payload['instrumentToken']]
                subscription_pkt.append(pkt)
                
            global websock
            sub_packet = {
                "a": "subscribe",
                "v": subscription_pkt,
                "m": "compact_marketdata"
            }
            websock.send(json.dumps(sub_packet))
            logger.info(f"Subscribed to multiple compact market data: {compactmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to multiple compact market data: {str(e)}")
            return False

    def unsubscribe_multiple_compact_marketdata(self, compactmarketdata_payload):
        """Unsubscribe from multiple compact market data"""
        try:
            unsubscription_pkt = []
            for payload in compactmarketdata_payload:
                pkt = [payload['exchangeCode'], payload['instrumentToken']]
                unsubscription_pkt.append(pkt)
                
            global websock
            sub_packet = {
                "a": "unsubscribe",
                "v": unsubscription_pkt,
                "m": "compact_marketdata"
            }
            websock.send(json.dumps(sub_packet))
            # Clear data
            global compact_marketdata_response, cmptmktdata_dict
            compact_marketdata_response = {}
            cmptmktdata_dict = {}
            logger.info(f"Unsubscribed from multiple compact market data: {compactmarketdata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from multiple compact market data: {str(e)}")
            return False

    def read_multiple_compact_marketdata(self):
        """Read multiple compact market data"""
        data = get_multiple_compact_marketdata()
        return data

    def subscribe_multiple_snapquote_data(self, snapquotedata_payload):
        """Subscribe to multiple snapquote data"""
        try:
            subscription_pkt = []
            for payload in snapquotedata_payload:
                pkt = [payload['exchangeCode'], payload['instrumentToken']]
                subscription_pkt.append(pkt)
                
            global websock
            sub_packet = {
                "a": "subscribe",
                "v": subscription_pkt,
                "m": "full_snapquote"
            }
            websock.send(json.dumps(sub_packet))
            logger.info(f"Subscribed to multiple snapquote data: {snapquotedata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error subscribing to multiple snapquote data: {str(e)}")
            return False
    
    def unsubscribe_multiple_snapquote_data(self, snapquotedata_payload):
        """Unsubscribe from multiple snapquote data"""
        try:
            unsubscription_pkt = []
            for payload in snapquotedata_payload:
                pkt = [payload['exchangeCode'], payload['instrumentToken']]
                unsubscription_pkt.append(pkt)
                
            global websock
            sub_packet = {
                "a": "unsubscribe",
                "v": unsubscription_pkt,
                "m": "full_snapquote"
            }
            websock.send(json.dumps(sub_packet))
            # Clear data
            global snapquote_marketdata_response, snpqtdata_dict
            snapquote_marketdata_response = {}
            snpqtdata_dict = {}
            logger.info(f"Unsubscribed from multiple snapquote data: {snapquotedata_payload}")
            return True
        except Exception as e:
            logger.error(f"Error unsubscribing from multiple snapquote data: {str(e)}")
            return False
    
    def read_multiple_snapquote_data(self):
        """Read multiple snapquote data"""
        data = get_multiple_snapquotedata()
        return data
