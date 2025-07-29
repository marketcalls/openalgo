from utils.logging import get_logger
import json
import threading
import websocket
import time
import uuid

class FlattradeWebSocket:
    """Enhanced Flattrade WebSocket client with improved heartbeat management"""
    
    WS_URL = "wss://piconnect.flattrade.in/PiConnectWSTp/"
    HEARTBEAT_INTERVAL = 30  # Send heartbeat every 30 seconds
    HEARTBEAT_TIMEOUT = 120   # Consider connection dead if no response for 2 minutes (more lenient)
    CONNECTION_CHECK_INTERVAL = 5  # Check connection health every 5 seconds
    
    def __init__(self, user_id, actid, susertoken, on_message=None, on_error=None, on_close=None, on_open=None):
        # Create unique instance identifier
        self.instance_id = str(uuid.uuid4())[:8]
        self.logger = get_logger(f"flattrade_websocket_{self.instance_id}")
        
        self.user_id = user_id
        self.actid = actid
        self.susertoken = susertoken
        
        # Connection state
        self.ws = None
        self.connected = False
        self._thread = None
        self._stop_event = threading.Event()
        self._heartbeat_thread = None
        
        # Callbacks
        self.on_message = on_message
        self.on_error = on_error
        self.on_close = on_close
        self.on_open = on_open
        
        # Enhanced heartbeat tracking
        self._last_heartbeat_sent = None
        self._last_message_received = None  # Track ANY message, not just pongs
        self._heartbeat_enabled = True
        self._connection_dead = False
        
        # Connection metadata
        self._connection_start_time = None
        self._message_count = 0
        
        self.logger.debug(f"Initialized WebSocket instance: {self.instance_id}")

    def connect(self) -> bool:
        """Enhanced connection with heartbeat support"""
        try:
            self.logger.debug(f"Instance {self.instance_id} attempting connection")
            self._connection_start_time = time.time()
            self._connection_dead = False
            
            self.ws = websocket.WebSocketApp(
                self.WS_URL,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close,
                on_open=self._on_open,
                on_ping=self._on_ping,
                on_pong=self._on_pong
            )
            
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_with_heartbeat,
                daemon=True, 
                name=f"FlattradeWS-{self.instance_id}"
            )
            self._thread.start()
            
            # Wait for connection with timeout
            connection_timeout = 15
            start_time = time.time()
            
            while time.time() - start_time < connection_timeout:
                if self.connected:
                    connection_time = time.time() - self._connection_start_time
                    self.logger.debug(f"Instance {self.instance_id} connected in {connection_time:.2f}s")
                    return True
                    
                if not self._thread.is_alive():
                    self.logger.error(f"Instance {self.instance_id} thread died during connection")
                    return False
                    
                time.sleep(0.1)
            
            self.logger.error(f"Instance {self.instance_id} connection timeout after {connection_timeout}s")
            self.stop()
            return False
            
        except Exception as e:
            self.logger.error(f"Instance {self.instance_id} connection error: {e}")
            self.stop()
            return False

    def _run_with_heartbeat(self):
        """Run WebSocket with heartbeat monitoring"""
        try:
            # Start heartbeat thread
            self._start_heartbeat()
            
            # Run WebSocket
            self.ws.run_forever(
                ping_interval=0,  # Disable default ping, we handle it ourselves
                ping_timeout=10
            )
        except Exception as e:
            self.logger.error(f"Instance {self.instance_id} run_forever error: {e}")
        finally:
            self._stop_heartbeat()

    def _start_heartbeat(self):
        """Start heartbeat thread"""
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            return
            
        self._heartbeat_enabled = True
        self._heartbeat_thread = threading.Thread(
            target=self._heartbeat_worker,
            daemon=True,
            name=f"Heartbeat-{self.instance_id}"
        )
        self._heartbeat_thread.start()
        self.logger.debug(f"Instance {self.instance_id} heartbeat started")

    def _stop_heartbeat(self):
        """Stop heartbeat thread"""
        self._heartbeat_enabled = False
        if self._heartbeat_thread:
            self._heartbeat_thread.join(timeout=2)
        self.logger.debug(f"Instance {self.instance_id} heartbeat stopped")

    def _heartbeat_worker(self):
        """Enhanced heartbeat worker with better connection detection and fast shutdown response"""
        while self._heartbeat_enabled and not self._stop_event.is_set():
            try:
                if self.connected and self.ws and not self._connection_dead:
                    current_time = time.time()

                    # Send heartbeat if interval has passed
                    if (self._last_heartbeat_sent is None or 
                        current_time - self._last_heartbeat_sent >= self.HEARTBEAT_INTERVAL):
                        
                        if self._send_heartbeat():
                            self._last_heartbeat_sent = current_time

                    # **IMPROVED: Check for ANY message activity, not just pongs**
                    if self._last_message_received:
                        time_since_last_message = current_time - self._last_message_received

                        if time_since_last_message > self.HEARTBEAT_TIMEOUT:
                            self.logger.error(
                                f"Instance {self.instance_id} no messages received for {time_since_last_message:.1f}s - connection appears dead"
                            )
                            self._connection_dead = True
                            # Force close the connection to trigger reconnection
                            self._force_reconnect()
                            break
                        elif time_since_last_message > self.HEARTBEAT_TIMEOUT * 0.7:  # 70% of timeout
                            self.logger.warning(
                                f"Instance {self.instance_id} no messages for {time_since_last_message:.1f}s - connection may be unstable"
                            )

                # Sleep in small increments for responsiveness
                total_sleep = 0
                step = 0.25  # 250ms steps for fast shutdown response
                while total_sleep < self.CONNECTION_CHECK_INTERVAL:
                    if not self._heartbeat_enabled or self._stop_event.is_set():
                        break
                    time.sleep(step)
                    total_sleep += step

            except Exception as e:
                self.logger.error(f"Instance {self.instance_id} heartbeat error: {e}")
                # Also sleep in small steps on error
                total_sleep = 0
                step = 0.25
                while total_sleep < self.CONNECTION_CHECK_INTERVAL:
                    if not self._heartbeat_enabled or self._stop_event.is_set():
                        break
                    time.sleep(step)
                    total_sleep += step


    def _send_heartbeat(self):
        """Send heartbeat message with better error handling"""
        try:
            if self.ws and self.connected and not self._connection_dead:
                # Send Flattrade-specific heartbeat format
                heartbeat_msg = {"t": "h"}
                self.ws.send(json.dumps(heartbeat_msg))
                self.logger.debug(f"Instance {self.instance_id} sent heartbeat")
                return True
        except Exception as e:
            self.logger.error(f"Instance {self.instance_id} failed to send heartbeat: {e}")
            self._connection_dead = True
        return False

    def _force_reconnect(self):
        """Force connection closure to trigger reconnection"""
        try:
            self.logger.warning(f"Instance {self.instance_id} forcing reconnection due to dead connection")
            self.connected = False
            if self.ws:
                self.ws.close()
        except Exception as e:
            self.logger.error(f"Instance {self.instance_id} error forcing reconnect: {e}")

    def _on_ping(self, ws, message):
        """Handle incoming ping"""
        self._last_message_received = time.time()
        self.logger.debug(f"Instance {self.instance_id} received ping")

    def _on_pong(self, ws, message):
        """Handle incoming pong"""
        self._last_message_received = time.time()
        self.logger.debug(f"Instance {self.instance_id} received pong")

    def stop(self):
        """Enhanced stop with heartbeat cleanup"""
        self.logger.debug(f"Stopping instance {self.instance_id}")
        
        self._stop_event.set()
        self.connected = False
        self._connection_dead = True
        
        # Stop heartbeat first
        self._stop_heartbeat()
        
        if self.ws:
            try:
                self.ws.close()
            except Exception as e:
                self.logger.warning(f"Error closing WebSocket for instance {self.instance_id}: {e}")
        
        if self._thread and self._thread.is_alive():
            self.logger.debug(f"Waiting for thread termination for instance {self.instance_id}")
            self._thread.join(timeout=5)
            
            if self._thread.is_alive():
                self.logger.warning(f"Thread did not terminate cleanly for instance {self.instance_id}")
        
        # Clean up references
        self.ws = None
        self._thread = None
        self._heartbeat_thread = None
        
        self.logger.debug(f"Instance {self.instance_id} stopped")

    def _on_open(self, ws):
        """Connection opened callback with heartbeat initialization"""
        self.connected = True
        self._last_message_received = time.time()  # Initialize message timestamp
        self._connection_dead = False
        
        self.logger.debug(f"Instance {self.instance_id} WebSocket opened, sending auth")
        
        auth_msg = {
            "t": "c",
            "uid": self.user_id,
            "actid": self.actid,
            "source": "API",
            "susertoken": self.susertoken
        }
        
        try:
            ws.send(json.dumps(auth_msg))
            self.logger.debug(f"Instance {self.instance_id} auth message sent")
        except Exception as e:
            self.logger.error(f"Instance {self.instance_id} failed to send auth: {e}")
            return
        
        # Call external callback
        if self.on_open:
            try:
                self.on_open(ws)
            except Exception as e:
                self.logger.error(f"Instance {self.instance_id} on_open callback error: {e}")

    def _on_message(self, ws, message):
        """Message received callback with heartbeat tracking"""
        self._last_message_received = time.time()  # **KEY: Update on ANY message**
        self._message_count += 1
        
        try:
            # Handle auth acknowledgment and heartbeat responses
            data = json.loads(message)
            msg_type = data.get('t')
            
            if msg_type == 'ck':
                if data.get('s') == 'OK':
                    self.logger.debug(f"Instance {self.instance_id} authenticated successfully")
                else:
                    self.logger.error(f"Instance {self.instance_id} authentication failed: {data}")
                    return
            elif msg_type == 'h':
                # Handle heartbeat response
                self.logger.debug(f"Instance {self.instance_id} received heartbeat response")
                return  # Don't pass heartbeat messages to the adapter
                
        except (json.JSONDecodeError, KeyError):
            pass  # Not a JSON message or doesn't have expected structure
        
        # Call external callback
        if self.on_message:
            try:
                self.on_message(ws, message)
            except Exception as e:
                self.logger.error(f"Instance {self.instance_id} on_message callback error: {e}")

    def _on_error(self, ws, error):
        """Error callback"""
        self.logger.error(f"Instance {self.instance_id} WebSocket error: {error}")
        self._connection_dead = True
        
        if self.on_error:
            try:
                self.on_error(ws, error)
            except Exception as e:
                self.logger.error(f"Instance {self.instance_id} on_error callback error: {e}")

    def _on_close(self, ws, close_status_code, close_msg):
        """Connection closed callback"""
        self.connected = False
        self.logger.warning(f"Instance {self.instance_id} closed: {close_status_code} - {close_msg}")
        
        if self.on_close:
            try:
                self.on_close(ws, close_status_code, close_msg)
            except Exception as e:
                self.logger.error(f"Instance {self.instance_id} on_close callback error: {e}")

    # Keep existing subscription methods unchanged
    def subscribe_touchline(self, scrip_list):
        """Subscribe to touchline data"""
        self._send_message({"t": "t", "k": scrip_list}, "touchline subscription")

    def unsubscribe_touchline(self, scrip_list):
        """Unsubscribe from touchline data"""
        self._send_message({"t": "u", "k": scrip_list}, "touchline unsubscription")

    def subscribe_depth(self, scrip_list):
        """Subscribe to depth data"""
        self._send_message({"t": "d", "k": scrip_list}, "depth subscription")

    def unsubscribe_depth(self, scrip_list):
        """Unsubscribe from depth data"""
        self._send_message({"t": "ud", "k": scrip_list}, "depth unsubscription")

    def _send_message(self, message_dict, operation_name):
        """Send message with error handling"""
        if not self.ws or not self.connected or self._connection_dead:
            self.logger.warning(f"Instance {self.instance_id} cannot send {operation_name}: not connected")
            return False
        
        try:
            message_json = json.dumps(message_dict)
            self.ws.send(message_json)
            self.logger.debug(f"Instance {self.instance_id} sent {operation_name}: {message_dict}")
            return True
        except Exception as e:
            self.logger.error(f"Instance {self.instance_id} failed to send {operation_name}: {e}")
            self._connection_dead = True
            return False
    
    def get_connection_stats(self):
        """Get connection statistics for monitoring"""
        current_time = time.time()
        return {
            'instance_id': self.instance_id,
            'connected': self.connected,
            'connection_dead': self._connection_dead,
            'message_count': self._message_count,
            'uptime': current_time - self._connection_start_time if self._connection_start_time else 0,
            'last_message_age': current_time - self._last_message_received if self._last_message_received else None,
            'thread_alive': self._thread.is_alive() if self._thread else False
        }
