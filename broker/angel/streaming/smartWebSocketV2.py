import json
import logging
import os
import ssl
import struct
import threading
import time

import logzero
import websocket
from logzero import logger


class SmartWebSocketV2:
    """
    SmartAPI Web Socket version 2

    Enhanced with proper resource management and file descriptor cleanup.
    """

    ROOT_URI = "wss://smartapisocket.angelone.in/smart-stream"
    HEART_BEAT_MESSAGE = "ping"
    HEART_BEAT_INTERVAL = 10  # Adjusted to 10s
    LITTLE_ENDIAN_BYTE_ORDER = "<"

    # Available Actions
    SUBSCRIBE_ACTION = 1
    UNSUBSCRIBE_ACTION = 0

    # Possible Subscription Mode
    LTP_MODE = 1
    QUOTE = 2
    SNAP_QUOTE = 3
    DEPTH = 4

    # Exchange Type
    NSE_CM = 1
    NSE_FO = 2
    BSE_CM = 3
    BSE_FO = 4
    MCX_FO = 5
    NCX_FO = 7
    CDE_FO = 13

    # Subscription Mode Map
    SUBSCRIPTION_MODE_MAP = {1: "LTP", 2: "QUOTE", 3: "SNAP_QUOTE", 4: "DEPTH"}

    # Thread cleanup timeout
    THREAD_JOIN_TIMEOUT = 5

    # Health check settings - detect silent stalls
    HEALTH_CHECK_INTERVAL = 30  # Check every 30 seconds
    DATA_TIMEOUT = 90  # Consider stalled if no data for 90 seconds

    # Class-level flag to prevent log file handler leak
    _logging_initialized = False
    _logging_lock = threading.Lock()

    def __init__(
        self,
        auth_token,
        api_key,
        client_code,
        feed_token,
        max_retry_attempt=1,
        retry_strategy=0,
        retry_delay=10,
        retry_multiplier=2,
        retry_duration=60,
    ):
        """
        Initialise the SmartWebSocketV2 instance
        Parameters
        ------
        auth_token: string
            jwt auth token received from Login API
        api_key: string
            api key from Smart API account
        client_code: string
            angel one account id
        feed_token: string
            feed token received from Login API
        """
        self.auth_token = auth_token
        self.api_key = api_key
        self.client_code = client_code
        self.feed_token = feed_token

        # Instance-level state (moved from class-level to prevent cross-instance interference)
        self.wsapp = None
        self.input_request_dict = {}
        self.current_retry_attempt = 0
        self.RESUBSCRIBE_FLAG = False
        self.DISCONNECT_FLAG = True

        # Connection state tracking
        self.last_pong_timestamp = None
        self.last_ping_timestamp = None
        self._last_message_time = None  # Track last data received for health check
        self._is_running = False
        self._reconnecting = False
        self._lock = threading.Lock()

        # Health check thread
        self._health_check_thread = None
        self._health_check_stop_event = threading.Event()

        # WebSocket thread tracking for proper cleanup
        self._ws_thread = None

        # Retry configuration
        self.MAX_RETRY_ATTEMPT = max_retry_attempt
        self.retry_strategy = retry_strategy
        self.retry_delay = retry_delay
        self.retry_multiplier = retry_multiplier
        self.retry_duration = retry_duration

        # Initialize logging only once to prevent file handler leaks
        # Each SmartWebSocketV2 instance was creating a new file handler, leaking FDs
        with SmartWebSocketV2._logging_lock:
            if not SmartWebSocketV2._logging_initialized:
                log_folder = time.strftime("%Y-%m-%d", time.localtime())
                log_folder_path = os.path.join("logs", log_folder)
                os.makedirs(log_folder_path, exist_ok=True)
                log_path = os.path.join(log_folder_path, "app.log")
                logzero.logfile(log_path, loglevel=logging.INFO)
                SmartWebSocketV2._logging_initialized = True

        if not self._sanity_check():
            logger.error(
                "Invalid initialization parameters. Provide valid values for all the tokens."
            )
            raise Exception("Provide valid value for all the tokens")

    def _sanity_check(self):
        if not all([self.auth_token, self.api_key, self.client_code, self.feed_token]):
            return False
        return True

    def _on_message(self, wsapp, message):
        # Update last message time for health check
        self._last_message_time = time.time()

        logger.info(f"Received message: {message}")
        if message != "pong":
            parsed_message = self._parse_binary_data(message)
            # Check if it's a control message (e.g., heartbeat)
            if self._is_control_message(parsed_message):
                self._handle_control_message(parsed_message)
            else:
                self.on_data(wsapp, parsed_message)
        else:
            self.on_message(wsapp, message)

    def _is_control_message(self, parsed_message):
        return "subscription_mode" not in parsed_message

    def _handle_control_message(self, parsed_message):
        if parsed_message["subscription_mode"] == 0:
            self._on_pong(self.wsapp, "pong")
        elif parsed_message["subscription_mode"] == 1:
            self._on_ping(self.wsapp, "ping")
        # Invoke on_control_message callback with the control message data
        if hasattr(self, "on_control_message"):
            self.on_control_message(self.wsapp, parsed_message)

    def _on_data(self, wsapp, data, data_type, continue_flag):
        # Update last message time for health check
        self._last_message_time = time.time()

        if data_type == 2:
            parsed_message = self._parse_binary_data(data)
            self.on_data(wsapp, parsed_message)

    def _on_open(self, wsapp):
        # Initialize last message time and start health check
        self._last_message_time = time.time()
        self._start_health_check()

        if self.RESUBSCRIBE_FLAG:
            self.resubscribe()
        else:
            self.on_open(wsapp)

    def _on_pong(self, wsapp, data):
        if data == self.HEART_BEAT_MESSAGE:
            timestamp = time.time()
            formatted_timestamp = time.strftime("%d-%m-%y %H:%M:%S", time.localtime(timestamp))
            logger.info(f"In on pong function ==> {data}, Timestamp: {formatted_timestamp}")
            self.last_pong_timestamp = timestamp

    def _on_ping(self, wsapp, data):
        timestamp = time.time()
        formatted_timestamp = time.strftime("%d-%m-%y %H:%M:%S", time.localtime(timestamp))
        logger.info(f"In on ping function ==> {data}, Timestamp: {formatted_timestamp}")
        self.last_ping_timestamp = timestamp

    def subscribe(self, correlation_id, mode, token_list):
        """
        This Function subscribe the price data for the given token
        Parameters
        ------
        correlation_id: string
            A 10 character alphanumeric ID client may provide which will be returned by the server in error response
            to indicate which request generated error response.
            Clients can use this optional ID for tracking purposes between request and corresponding error response.
        mode: integer
            It denotes the subscription type
            possible values -> 1, 2 and 3
            1 -> LTP
            2 -> Quote
            3 -> Snap Quote
        token_list: list of dict
            Sample Value ->
                [
                    { "exchangeType": 1, "tokens": ["10626", "5290"]},
                    {"exchangeType": 5, "tokens": [ "234230", "234235", "234219"]}
                ]
                exchangeType: integer
                possible values ->
                    1 -> nse_cm
                    2 -> nse_fo
                    3 -> bse_cm
                    4 -> bse_fo
                    5 -> mcx_fo
                    7 -> ncx_fo
                    13 -> cde_fo
                tokens: list of string
        """
        try:
            request_data = {
                "correlationID": correlation_id,
                "action": self.SUBSCRIBE_ACTION,
                "params": {"mode": mode, "tokenList": token_list},
            }
            if mode == 4:
                for token in token_list:
                    if token.get("exchangeType") != 1:
                        error_message = f"Invalid ExchangeType:{token.get('exchangeType')} Please check the exchange type and try again it support only 1 exchange type"
                        logger.error(error_message)
                        raise ValueError(error_message)

            if self.input_request_dict.get(mode) is None:
                self.input_request_dict[mode] = {}

            for token in token_list:
                if token["exchangeType"] in self.input_request_dict[mode]:
                    self.input_request_dict[mode][token["exchangeType"]].extend(token["tokens"])
                else:
                    self.input_request_dict[mode][token["exchangeType"]] = token["tokens"]

            if mode == self.DEPTH:
                total_tokens = sum(len(token["tokens"]) for token in token_list)
                quota_limit = 50
                if total_tokens > quota_limit:
                    error_message = f"Quota exceeded: You can subscribe to a maximum of {quota_limit} tokens only."
                    logger.error(error_message)
                    raise Exception(error_message)

            self.wsapp.send(json.dumps(request_data))
            self.RESUBSCRIBE_FLAG = True

        except Exception as e:
            logger.error(f"Error occurred during subscribe: {e}")
            raise e

    def unsubscribe(self, correlation_id, mode, token_list):
        """
        This function unsubscribe the data for given token
        Parameters
        ------
        correlation_id: string
            A 10 character alphanumeric ID client may provide which will be returned by the server in error response
            to indicate which request generated error response.
            Clients can use this optional ID for tracking purposes between request and corresponding error response.
        mode: integer
            It denotes the subscription type
            possible values -> 1, 2 and 3
            1 -> LTP
            2 -> Quote
            3 -> Snap Quote
        token_list: list of dict
            Sample Value ->
                [
                    { "exchangeType": 1, "tokens": ["10626", "5290"]},
                    {"exchangeType": 5, "tokens": [ "234230", "234235", "234219"]}
                ]
                exchangeType: integer
                possible values ->
                    1 -> nse_cm
                    2 -> nse_fo
                    3 -> bse_cm
                    4 -> bse_fo
                    5 -> mcx_fo
                    7 -> ncx_fo
                    13 -> cde_fo
                tokens: list of string
        """
        try:
            request_data = {
                "correlationID": correlation_id,
                "action": self.UNSUBSCRIBE_ACTION,
                "params": {"mode": mode, "tokenList": token_list},
            }
            self.input_request_dict.update(request_data)
            self.wsapp.send(json.dumps(request_data))
            self.RESUBSCRIBE_FLAG = True
        except Exception as e:
            logger.error(f"Error occurred during unsubscribe: {e}")
            raise e

    def resubscribe(self):
        try:
            for key, val in self.input_request_dict.items():
                token_list = []
                for key1, val1 in val.items():
                    temp_data = {"exchangeType": key1, "tokens": val1}
                    token_list.append(temp_data)
                request_data = {
                    "action": self.SUBSCRIBE_ACTION,
                    "params": {"mode": key, "tokenList": token_list},
                }
                self.wsapp.send(json.dumps(request_data))
        except Exception as e:
            logger.error(f"Error occurred during resubscribe: {e}")
            raise e

    def connect(self):
        """
        Make the web socket connection with the server
        """
        headers = {
            "Authorization": self.auth_token,
            "x-api-key": self.api_key,
            "x-client-code": self.client_code,
            "x-feed-token": self.feed_token,
        }

        try:
            with self._lock:
                self._is_running = True

            self.wsapp = websocket.WebSocketApp(
                self.ROOT_URI,
                header=headers,
                on_open=self._on_open,
                on_error=self._on_error,
                on_close=self._on_close,
                on_data=self._on_data,
                on_ping=self._on_ping,
                on_pong=self._on_pong,
            )
            self.wsapp.run_forever(
                sslopt={"cert_reqs": ssl.CERT_NONE},
                ping_interval=self.HEART_BEAT_INTERVAL,
                ping_payload=self.HEART_BEAT_MESSAGE,
            )
        except Exception as e:
            logger.error(f"Error occurred during WebSocket connection: {e}")
            raise e
        finally:
            with self._lock:
                self._is_running = False

    def close_connection(self):
        """
        Closes the connection and releases resources
        """
        with self._lock:
            self.RESUBSCRIBE_FLAG = False
            self.DISCONNECT_FLAG = True
            self._is_running = False

        # Stop health check thread first
        self._stop_health_check()

        with self._lock:
            # Clear subscription tracking to prevent memory leak
            self.input_request_dict.clear()

            if self.wsapp:
                try:
                    self.wsapp.close()
                except Exception as e:
                    logger.debug(f"Error closing WebSocket: {e}")
                finally:
                    self.wsapp = None  # Release reference to prevent stale usage

            # Reset state
            self._last_message_time = None
            self.current_retry_attempt = 0

    def is_running(self) -> bool:
        """Check if WebSocket is currently running"""
        with self._lock:
            return self._is_running

    def _on_error(self, wsapp, error):
        """
        Handle WebSocket errors with proper reconnection management.
        Prevents concurrent reconnection attempts and properly cleans up resources.
        """
        # Check if we should attempt reconnection
        with self._lock:
            if self._reconnecting:
                logger.debug("Reconnection already in progress, skipping duplicate attempt")
                return

            if not self.DISCONNECT_FLAG:
                # User initiated disconnect, don't reconnect
                return

            self.RESUBSCRIBE_FLAG = True

        if self.current_retry_attempt < self.MAX_RETRY_ATTEMPT:
            logger.warning(
                f"Attempting to resubscribe/reconnect (Attempt {self.current_retry_attempt + 1})..."
            )
            self.current_retry_attempt += 1

            # Calculate delay based on retry strategy
            if self.retry_strategy == 0:  # Simple retry
                delay = self.retry_delay
            elif self.retry_strategy == 1:  # Exponential backoff
                delay = self.retry_delay * (
                    self.retry_multiplier ** (self.current_retry_attempt - 1)
                )
            else:
                logger.error(f"Invalid retry strategy {self.retry_strategy}")
                self._safe_call_on_error("Invalid Retry Strategy", f"Strategy {self.retry_strategy} not supported")
                return

            time.sleep(delay)

            # Attempt reconnection with proper locking
            with self._lock:
                if self._reconnecting:
                    return
                self._reconnecting = True

            try:
                # Clean up old connection before creating new one
                self._cleanup_websocket()
                self.connect()
            except Exception as e:
                logger.error(f"Error occurred during resubscribe/reconnect: {e}")
                self._safe_call_on_error("Reconnect Error", str(e) if str(e) else "Unknown error")
            finally:
                with self._lock:
                    self._reconnecting = False
        else:
            # Max retries reached
            self.close_connection()
            self._safe_call_on_error("Max retry attempt reached", "Connection closed")

            if self.retry_duration is not None and (
                self.last_pong_timestamp is not None
                and time.time() - self.last_pong_timestamp > self.retry_duration * 60
            ):
                logger.warning("Connection closed due to inactivity.")
            else:
                logger.warning("Connection closed due to max retry attempts reached.")

    def _cleanup_websocket(self):
        """Clean up WebSocket resources without triggering reconnection"""
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception as e:
                logger.debug(f"Error during WebSocket cleanup: {e}")
            finally:
                self.wsapp = None

    def _safe_call_on_error(self, error_type: str, error_msg: str):
        """Safely call the on_error callback"""
        if hasattr(self, "on_error") and callable(self.on_error):
            try:
                self.on_error(error_type, error_msg)
            except Exception as e:
                logger.debug(f"Error in on_error callback: {e}")

    def _start_health_check(self):
        """Start health check thread to detect silent stalls"""
        # Stop existing health check thread first
        self._stop_health_check()

        # Clear stop event before starting new thread
        self._health_check_stop_event.clear()

        self._health_check_thread = threading.Thread(
            target=self._health_check_loop, daemon=True, name="AngelWSHealthCheck"
        )
        self._health_check_thread.start()
        logger.debug("Angel health check thread started")

    def _stop_health_check(self):
        """Stop health check thread"""
        # Signal thread to stop immediately
        self._health_check_stop_event.set()

        if self._health_check_thread and self._health_check_thread.is_alive():
            # Wait for thread to notice the stop event
            self._health_check_thread.join(timeout=self.THREAD_JOIN_TIMEOUT)
            if self._health_check_thread.is_alive():
                logger.warning("Health check thread did not stop within timeout")
        self._health_check_thread = None

    def _health_check_loop(self):
        """
        Health check loop - detects silent stalls where connection appears alive
        but no data is flowing (common in VPS/cloud environments with NAT timeouts)
        """
        while self._is_running:
            try:
                # Use event.wait() instead of time.sleep() so thread can be interrupted
                if self._health_check_stop_event.wait(timeout=self.HEALTH_CHECK_INTERVAL):
                    # Event was set - stop requested
                    logger.debug("Health check thread received stop signal")
                    break

                if not self._is_running:
                    break

                # Check if we've received data recently
                if self._last_message_time:
                    elapsed = time.time() - self._last_message_time
                    if elapsed > self.DATA_TIMEOUT:
                        logger.error(
                            f"Angel data stall detected - no data for {elapsed:.1f}s "
                            f"(timeout: {self.DATA_TIMEOUT}s). Forcing reconnect..."
                        )
                        self._force_reconnect()
                        break
                    else:
                        logger.debug(f"Angel health check OK - last data {elapsed:.1f}s ago")

            except Exception as e:
                logger.error(f"Angel health check error: {e}")
                break

        logger.debug("Angel health check loop exited")

    def _force_reconnect(self):
        """Force a reconnection by closing the current WebSocket"""
        logger.info("Forcing Angel WebSocket reconnection...")

        # Close current connection - this will trigger _on_close
        # and the reconnection will be handled by error handler
        if self.wsapp:
            try:
                self.wsapp.close()
            except Exception as e:
                logger.warning(f"Error closing WebSocket during force reconnect: {e}")

    def _on_close(self, wsapp, close_status_code=None, close_msg=None):
        # Stop health check on close
        self._stop_health_check()
        # Pass only the wsapp to the on_close handler to maintain backward compatibility
        self.on_close(wsapp)

    def _parse_binary_data(self, binary_data):
        parsed_data = {
            "subscription_mode": self._unpack_data(binary_data, 0, 1, byte_format="B")[0],
            "exchange_type": self._unpack_data(binary_data, 1, 2, byte_format="B")[0],
            "token": SmartWebSocketV2._parse_token_value(binary_data[2:27]),
            "sequence_number": self._unpack_data(binary_data, 27, 35, byte_format="q")[0],
            "exchange_timestamp": self._unpack_data(binary_data, 35, 43, byte_format="q")[0],
            "last_traded_price": self._unpack_data(binary_data, 43, 51, byte_format="q")[0],
        }
        try:
            parsed_data["subscription_mode_val"] = self.SUBSCRIPTION_MODE_MAP.get(
                parsed_data["subscription_mode"]
            )

            if parsed_data["subscription_mode"] in [self.QUOTE, self.SNAP_QUOTE]:
                parsed_data["last_traded_quantity"] = self._unpack_data(
                    binary_data, 51, 59, byte_format="q"
                )[0]
                parsed_data["average_traded_price"] = self._unpack_data(
                    binary_data, 59, 67, byte_format="q"
                )[0]
                parsed_data["volume_trade_for_the_day"] = self._unpack_data(
                    binary_data, 67, 75, byte_format="q"
                )[0]
                parsed_data["total_buy_quantity"] = self._unpack_data(
                    binary_data, 75, 83, byte_format="d"
                )[0]
                parsed_data["total_sell_quantity"] = self._unpack_data(
                    binary_data, 83, 91, byte_format="d"
                )[0]
                parsed_data["open_price_of_the_day"] = self._unpack_data(
                    binary_data, 91, 99, byte_format="q"
                )[0]
                parsed_data["high_price_of_the_day"] = self._unpack_data(
                    binary_data, 99, 107, byte_format="q"
                )[0]
                parsed_data["low_price_of_the_day"] = self._unpack_data(
                    binary_data, 107, 115, byte_format="q"
                )[0]
                parsed_data["closed_price"] = self._unpack_data(
                    binary_data, 115, 123, byte_format="q"
                )[0]

            if parsed_data["subscription_mode"] == self.SNAP_QUOTE:
                parsed_data["last_traded_timestamp"] = self._unpack_data(
                    binary_data, 123, 131, byte_format="q"
                )[0]
                parsed_data["open_interest"] = self._unpack_data(
                    binary_data, 131, 139, byte_format="q"
                )[0]
                parsed_data["open_interest_change_percentage"] = self._unpack_data(
                    binary_data, 139, 147, byte_format="q"
                )[0]
                parsed_data["upper_circuit_limit"] = self._unpack_data(
                    binary_data, 347, 355, byte_format="q"
                )[0]
                parsed_data["lower_circuit_limit"] = self._unpack_data(
                    binary_data, 355, 363, byte_format="q"
                )[0]
                parsed_data["52_week_high_price"] = self._unpack_data(
                    binary_data, 363, 371, byte_format="q"
                )[0]
                parsed_data["52_week_low_price"] = self._unpack_data(
                    binary_data, 371, 379, byte_format="q"
                )[0]
                best_5_buy_and_sell_data = self._parse_best_5_buy_and_sell_data(
                    binary_data[147:347]
                )
                parsed_data["best_5_buy_data"] = best_5_buy_and_sell_data["best_5_sell_data"]
                parsed_data["best_5_sell_data"] = best_5_buy_and_sell_data["best_5_buy_data"]

            if parsed_data["subscription_mode"] == self.DEPTH:
                parsed_data.pop("sequence_number", None)
                parsed_data.pop("last_traded_price", None)
                parsed_data.pop("subscription_mode_val", None)
                parsed_data["packet_received_time"] = self._unpack_data(
                    binary_data, 35, 43, byte_format="q"
                )[0]
                depth_data_start_index = 43
                depth_20_data = self._parse_depth_20_buy_and_sell_data(
                    binary_data[depth_data_start_index:]
                )
                parsed_data["depth_20_buy_data"] = depth_20_data["depth_20_buy_data"]
                parsed_data["depth_20_sell_data"] = depth_20_data["depth_20_sell_data"]

            return parsed_data
        except Exception as e:
            logger.error(f"Error occurred during binary data parsing: {e}")
            raise e

    def _unpack_data(self, binary_data, start, end, byte_format="I"):
        """
        Unpack Binary Data to the integer according to the specified byte_format.
        This function returns the tuple
        """
        return struct.unpack(self.LITTLE_ENDIAN_BYTE_ORDER + byte_format, binary_data[start:end])

    @staticmethod
    def _parse_token_value(binary_packet):
        token = ""
        for i in range(len(binary_packet)):
            if chr(binary_packet[i]) == "\x00":
                return token
            token += chr(binary_packet[i])
        return token

    def _parse_best_5_buy_and_sell_data(self, binary_data):
        def split_packets(binary_packets):
            packets = []

            i = 0
            while i < len(binary_packets):
                packets.append(binary_packets[i : i + 20])
                i += 20
            return packets

        best_5_buy_sell_packets = split_packets(binary_data)

        best_5_buy_data = []
        best_5_sell_data = []

        for packet in best_5_buy_sell_packets:
            each_data = {
                "flag": self._unpack_data(packet, 0, 2, byte_format="H")[0],
                "quantity": self._unpack_data(packet, 2, 10, byte_format="q")[0],
                "price": self._unpack_data(packet, 10, 18, byte_format="q")[0],
                "no of orders": self._unpack_data(packet, 18, 20, byte_format="H")[0],
            }

            if each_data["flag"] == 0:
                best_5_buy_data.append(each_data)
            else:
                best_5_sell_data.append(each_data)

        return {"best_5_buy_data": best_5_buy_data, "best_5_sell_data": best_5_sell_data}

    def _parse_depth_20_buy_and_sell_data(self, binary_data):
        depth_20_buy_data = []
        depth_20_sell_data = []

        for i in range(20):
            buy_start_idx = i * 10
            sell_start_idx = 200 + i * 10

            # Parse buy data
            buy_packet_data = {
                "quantity": self._unpack_data(
                    binary_data, buy_start_idx, buy_start_idx + 4, byte_format="i"
                )[0],
                "price": self._unpack_data(
                    binary_data, buy_start_idx + 4, buy_start_idx + 8, byte_format="i"
                )[0],
                "num_of_orders": self._unpack_data(
                    binary_data, buy_start_idx + 8, buy_start_idx + 10, byte_format="h"
                )[0],
            }

            # Parse sell data
            sell_packet_data = {
                "quantity": self._unpack_data(
                    binary_data, sell_start_idx, sell_start_idx + 4, byte_format="i"
                )[0],
                "price": self._unpack_data(
                    binary_data, sell_start_idx + 4, sell_start_idx + 8, byte_format="i"
                )[0],
                "num_of_orders": self._unpack_data(
                    binary_data, sell_start_idx + 8, sell_start_idx + 10, byte_format="h"
                )[0],
            }

            depth_20_buy_data.append(buy_packet_data)
            depth_20_sell_data.append(sell_packet_data)

        return {"depth_20_buy_data": depth_20_buy_data, "depth_20_sell_data": depth_20_sell_data}

    def on_message(self, wsapp, message):
        pass

    def on_data(self, wsapp, data):
        pass

    def on_control_message(self, wsapp, message):
        pass

    def on_close(self, wsapp):
        pass

    def on_open(self, wsapp):
        pass

    def on_error(self, error_type=None, error_msg=None):
        pass

    def __del__(self):
        """
        Destructor - ensures resources are released when object is garbage collected.
        This is a safety net; callers should explicitly call close_connection().
        """
        try:
            self.close_connection()
        except Exception:
            # Can't reliably log in __del__, just ensure we don't raise
            pass
