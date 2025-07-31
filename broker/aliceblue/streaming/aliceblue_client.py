import requests
import json
import hashlib
import enum
import logging
from datetime import time, datetime
from time import sleep
from collections import namedtuple
import os
import websocket
import ssl
import threading

logger = logging.getLogger(__name__)

Instrument = namedtuple('Instrument', ['exchange', 'token', 'symbol', 'name', 'expiry', 'lot_size'])


class TransactionType(enum.Enum):
    Buy = 'BUY'
    Sell = 'SELL'


class LiveFeedType(enum.IntEnum):
    MARKET_DATA = 1
    COMPACT = 2
    SNAPQUOTE = 3
    FULL_SNAPQUOTE = 4


class OrderType(enum.Enum):
    Market = 'MKT'
    Limit = 'L'
    StopLossLimit = 'SL'
    StopLossMarket = 'SL-M'


class ProductType(enum.Enum):
    Intraday = 'MIS'
    Delivery = 'CNC'
    CoverOrder = 'CO'
    BracketOrder = 'BO'
    Normal = 'NRML'


def encrypt_string(hashing):
    sha = hashlib.sha256(hashing.encode()).hexdigest()
    return sha


class Aliceblue:
    base_url = "https://ant.aliceblueonline.com/rest/AliceBlueAPIService/api/"
    api_name = "Codifi API Connect - Python Lib "
    version = "1.0.29"
    base_url_c = "https://v2api.aliceblueonline.com/restpy/static/contract_master/%s.csv"
    websocket_url = "wss://ant.aliceblueonline.com/order-notify/websocket"
    create_websocket_url = "https://ant.aliceblueonline.com/order-notify/ws/createWsToken"
    PRODUCT_INTRADAY = "MIS"
    PRODUCT_COVER_ODRER = "CO"
    PRODUCT_CNC = "CNC"
    PRODUCT_BRACKET_ORDER = "BO"
    PRODUCT_NRML = "NRML"
    REGULAR_ORDER = "REGULAR"
    LIMIT_ORDER = "L"
    STOPLOSS_ORDER = "SL"
    MARKET_ORDER = "MKT"
    BUY_ORDER = "BUY"
    SELL_ORDER = "SELL"
    RETENTION_DAY = "DAY"
    EXCHANGE_NSE = "NSE"
    EXCHANGE_NFO = "NFO"
    EXCHANGE_CDS = "CDS"
    EXCHANGE_BSE = "BSE"
    EXCHANGE_BFO = "BFO"
    EXCHANGE_BCD = "BCD"
    EXCHANGE_MCX = "MCX"
    STATUS_COMPLETE = "COMPLETE"
    STATUS_REJECTED = "REJECTED"
    STATUS_CANCELLED = "CANCELLED"
    ENC = None
    ws = None
    subscriptions = None
    __subscribe_callback = None
    __subscribers = None
    script_subscription_instrument = []
    ws_connection = False
    __ws_thread = None
    __stop_event = None
    market_depth = None
    _sub_urls = {
        # Authorization
        "encryption_key": "customer/getAPIEncpkey",
        "getsessiondata": "customer/getUserSID",

        # Market Watch
        "marketwatch_scrips": "marketWatch/fetchMWScrips",
        "addscrips": "marketWatch/addScripToMW",
        "getmarketwatch_list": "marketWatch/fetchMWList",
        "scripdetails": "ScripDetails/getScripQuoteDetails",
        "getdelete_scrips": "marketWatch/deleteMWScrip",

        # OrderManagement
        "squareoffposition": "positionAndHoldings/sqrOofPosition",
        "position_conversion": "positionAndHoldings/positionConvertion",
        "placeorder": "placeOrder/executePlaceOrder",
        "modifyorder": "placeOrder/modifyOrder",
        "marketorder": "placeOrder/executePlaceOrder",
        "exitboorder": "placeOrder/exitBracketOrder",
        "bracketorder": "placeOrder/executePlaceOrder",
        "positiondata": "positionAndHoldings/positionBook",
        "orderbook": "placeOrder/fetchOrderBook",
        "tradebook": "placeOrder/fetchTradeBook",
        "holding": "positionAndHoldings/holdings",
        "orderhistory": "placeOrder/orderHistory",
        "cancelorder": "placeOrder/cancelOrder",
        "profile": "customer/accountDetails",
        "basket_margin": "basket/getMargin",
        # Websocket
        "base_url_socket": "wss://ws1.aliceblueonline.com/NorenWS/"

    }

    def __init__(self,
                 user_id,
                 api_key,
                 base=None,
                 session_id=None,
                 disable_ssl=False):

        self.user_id = user_id.upper()
        self.api_key = api_key
        self.disable_ssl = disable_ssl
        self.session_id = session_id
        self.base = base or self.base_url
        self.__on_error = None
        self.__on_disconnect = None
        self.__on_open = None
        self.__exchange_codes = None

    # Get method declaration
    def _get(self, sub_url, data=None):

        url = self.base + sub_url
        headers = self._user_agent()

        response = requests.get(url, headers=headers, params=data, verify=not self.disable_ssl)

        if response.status_code == 200:
            if 'json' in response.headers.get('content-type'):
                return response.json()
            else:
                return response.content
        else:
            return self._error_response(response.status_code)

    # Post method declaration
    def _post(self, sub_url, data=None):

        url = self.base + sub_url
        headers = self._user_agent()
        response = requests.post(url, json=data, headers=headers, verify=not self.disable_ssl)

        if response.status_code == 200:
            if 'json' in response.headers.get('content-type'):
                return response.json()
            else:
                return response.content
        else:
            return self._error_response(response.status_code)

    # Post method declaration
    def _dummypost(self, url, data=None):

        headers = self._user_agent()
        response = requests.post(url, json=data, headers=headers, verify=not self.disable_ssl)

        if response.status_code == 200:
            if 'json' in response.headers.get('content-type'):
                return response.json()
            else:
                return response.content
        else:
            return self._error_response(response.status_code)

    def _user_agent(self):

        return {
            'X-API-KEY': self.api_key,
            'Content-Type': 'application/json'
        }

    def _user_authorization(self):

        return {
            'Authorization': f'Bearer {self.session_id}'
        }

    # 
    #     Headers with authorization. For some requests authorization
    #     is not required. It will be send as empty String
    #     
    def _request(self, method, req_type, data=None):

        headers = self._user_agent()
        
        if req_type != '':
            headers.update(self._user_authorization())

        url = self.base + method
        
        response = requests.post(url, json=data, headers=headers, verify=not self.disable_ssl)

        if response.status_code == 200:
            if 'json' in response.headers.get('content-type'):
                return response.json()
            else:
                return response.content
        else:
            return self._error_response(response.status_code)

    def _error_response(self, message):
        return {
            'status': 'error',
            'message': message
        }

    def get_session_id(self, data=None):
        response = self._post(self._sub_urls["getsessiondata"], data)
        if response['stat'] == 'Ok':
            return response['result']
        else:
            return response

    def get_order_history(self, nextorder):
        response = self._request(self._sub_urls["orderhistory"], "A", nextorder)
        return response

    def cancel_order(self, nextorder):
        response = self._request(self._sub_urls["cancelorder"], "A", nextorder)
        return response

    def place_order(self, transaction_type, instrument, quantity, order_type,
                    product_type, price=0.0, trigger_price=None,
                    stop_loss=None, square_off=None, trailing_sl=None,
                    is_amo=False,
                    order_tag=None,
                    is_ioc=False):

        data = {
            "prctyp": order_type,
            "qty": str(quantity),
            "pCode": product_type,
            "prc": str(price),
            "discqty": "0",
            "exch": instrument.exchange,
            "tsym": instrument.symbol,
            "trantype": transaction_type,
            "ret": "DAY",
            "uid": self.user_id
        }

        if trigger_price:
            data['trgprc'] = str(trigger_price)

        if order_tag:
            data['ordenttag'] = order_tag

        response = self._request(self._sub_urls["placeorder"], "A", data)
        return response

    def modify_order(self, transaction_type, instrument, product_type, order_id, order_type, quantity, price=0.0,
                     trigger_price=0.0):

        data = {
            "norenordno": order_id,
            "prctyp": order_type,
            "qty": str(quantity),
            "pCode": product_type,
            "prc": str(price),
            "exch": instrument.exchange,
            "tsym": instrument.symbol,
            "trantype": transaction_type,
            "ret": "DAY",
            "uid": self.user_id
        }

        if trigger_price:
            data['trgprc'] = str(trigger_price)

        response = self._request(self._sub_urls["modifyorder"], "A", data)
        return response

    def get_contract_master(self, exchange):
        url = self.base_url_c % exchange
        response = requests.get(url)
        
        if response.status_code == 200:
            return response.content
        else:
            return None

    def get_instrument_by_symbol(self, exchange, symbol):
        # Implementation for getting instrument by symbol
        pass

    def get_instrument_by_token(self, exchange, token):
        # Implementation for getting instrument by token
        pass

    def start_websocket(self, socket_open_callback=None, socket_close_callback=None, socket_error_callback=None,
                        subscription_callback=None, check_subscription_callback=None, run_in_background=False,
                        market_depth=False):
        """
        Start the WebSocket connection for live data streaming
        """
        def on_message(ws, message):
            if subscription_callback:
                subscription_callback(message)

        def on_error(ws, error):
            if socket_error_callback:
                socket_error_callback(error)

        def on_close(ws, close_status_code, close_msg):
            if socket_close_callback:
                socket_close_callback()

        def on_open(ws):
            if socket_open_callback:
                socket_open_callback()

        # Create WebSocket session first
        session_data = {"loginType": "API"}
        session_response = self._request("ws/createWsSession", "A", session_data)
        
        if session_response.get('stat') == 'Ok':
            ws_session = session_response['result']['wsSess']
            
            # Connect to WebSocket
            websocket.enableTrace(True)
            self.ws = websocket.WebSocketApp("wss://ws1.aliceblueonline.com/NorenWS",
                                           on_open=on_open,
                                           on_message=on_message,
                                           on_error=on_error,
                                           on_close=on_close)
            
            if run_in_background:
                self.__ws_thread = threading.Thread(target=self.ws.run_forever)
                self.__ws_thread.daemon = True
                self.__ws_thread.start()
            else:
                self.ws.run_forever()

    def subscribe(self, instrument, feed_type="t"):
        """
        Subscribe to live data for an instrument
        """
        if self.ws and self.ws.sock and self.ws.sock.connected:
            subscription_msg = {
                "k": f"{instrument.exchange}|{instrument.token}",
                "t": feed_type
            }
            self.ws.send(json.dumps(subscription_msg))
            return True
        return False

    def unsubscribe(self, instrument):
        """
        Unsubscribe from live data for an instrument
        """
        if self.ws and self.ws.sock and self.ws.sock.connected:
            unsubscription_msg = {
                "k": f"{instrument.exchange}|{instrument.token}",
                "t": "u"
            }
            self.ws.send(json.dumps(unsubscription_msg))
            return True
        return False

    def stop_websocket(self):
        """
        Stop the WebSocket connection
        """
        if self.ws:
            self.ws.close()
        if self.__ws_thread and self.__ws_thread.is_alive():
            self.__ws_thread.join()

    def create_websocket_session(self):
        """
        Create a WebSocket session
        """
        session_data = {"loginType": "API"}
        response = self._request("ws/createWsSession", "A", session_data)
        return response
