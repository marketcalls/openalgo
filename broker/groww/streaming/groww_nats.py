"""
Minimal NATS protocol implementation for Groww WebSocket
Implements core NATS protocol without external dependencies
"""

import json
import random
import string
import logging
from typing import Dict, Any, Optional, Callable, List, Union, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# NATS Protocol Commands
INFO = "INFO"
CONNECT = "CONNECT"
PUB = "PUB"
SUB = "SUB"
UNSUB = "UNSUB"
MSG = "MSG"
PING = "PING"
PONG = "PONG"
OK = "+OK"
ERR = "-ERR"

@dataclass
class Subscription:
    """Represents a NATS subscription"""
    sid: str  # Subscription ID
    subject: str  # Topic/subject
    queue_group: Optional[str] = None
    max_msgs: Optional[int] = None
    received_msgs: int = 0


class NATSProtocol:
    """
    Minimal NATS protocol handler for WebSocket communication
    """
    
    def __init__(self, on_message: Optional[Callable] = None):
        """
        Initialize NATS protocol handler
        
        Args:
            on_message: Callback for processed messages
        """
        self.on_message = on_message
        self.subscriptions: Dict[str, Subscription] = {}
        self.server_info: Dict[str, Any] = {}
        self.pending_data = ""  # Buffer for incomplete messages
        self.next_sid = 1
        
    def generate_sid(self) -> str:
        """Generate unique subscription ID"""
        sid = str(self.next_sid)
        self.next_sid += 1
        return sid
    
    def create_connect(self, jwt: str, nkey: str = None, sig: str = None) -> str:
        """
        Create CONNECT message
        
        Args:
            jwt: JWT token for authentication
            nkey: Public nkey (optional)
            sig: Signed nonce (optional)
        
        Returns:
            NATS CONNECT command
        """
        # Match the official Python NATS client identification exactly
        # The official nats.py library uses these parameters
        connect_opts = {
            "verbose": False,
            "pedantic": False,
            "tls_required": True,
            "jwt": jwt,
            "protocol": 1,
            "version": "2.10.18",  # Latest nats.py version used by SDK
            "lang": "python3",
            "name": "nats.py",  # Official NATS Python client name
            "headers": True,  # Enable headers support
            "no_responders": True  # Enable no responders detection
        }
        
        if nkey:
            connect_opts["nkey"] = nkey
        if sig:
            connect_opts["sig"] = sig
            
        return f"CONNECT {json.dumps(connect_opts)}\r\n"
    
    def create_subscribe(self, subject: str, queue_group: str = None) -> tuple[str, str]:
        """
        Create SUB message
        
        Args:
            subject: Subject/topic to subscribe
            queue_group: Optional queue group
        
        Returns:
            Tuple of (subscription_id, NATS SUB command)
        """
        sid = self.generate_sid()
        
        # Store subscription
        self.subscriptions[sid] = Subscription(
            sid=sid,
            subject=subject,
            queue_group=queue_group
        )
        
        if queue_group:
            sub_cmd = f"SUB {subject} {queue_group} {sid}\r\n"
        else:
            sub_cmd = f"SUB {subject} {sid}\r\n"
            
        logger.debug(f"Created subscription: {sub_cmd.strip()}")
        return sid, sub_cmd
    
    def create_unsubscribe(self, sid: str, max_msgs: int = None) -> str:
        """
        Create UNSUB message
        
        Args:
            sid: Subscription ID
            max_msgs: Optional max messages before auto-unsub
        
        Returns:
            NATS UNSUB command
        """
        if max_msgs:
            unsub_cmd = f"UNSUB {sid} {max_msgs}\r\n"
        else:
            unsub_cmd = f"UNSUB {sid}\r\n"
            
        # Remove subscription if no max_msgs
        if not max_msgs and sid in self.subscriptions:
            del self.subscriptions[sid]
            
        return unsub_cmd
    
    def create_ping(self) -> str:
        """Create PING message"""
        return "PING\r\n"
    
    def create_pong(self) -> str:
        """Create PONG message"""
        return "PONG\r\n"
    
    def parse_message(self, data: Union[str, bytes], original_binary: bytes = None) -> List[Dict[str, Any]]:
        """
        Parse NATS protocol messages
        
        Args:
            data: Raw data from WebSocket (decoded string)
            original_binary: Original binary data if available
        
        Returns:
            List of parsed messages
        """
        # Add to pending data
        self.pending_data += data
        # Store original binary for payload extraction
        self.original_binary = original_binary
        messages = []
        
        # Log if we have data to parse
        if self.pending_data:
            logger.debug(f"NATS Parser: Processing {len(self.pending_data)} bytes")
        
        while self.pending_data:
            # Try to find complete messages
            if self.pending_data.startswith(INFO):
                # INFO message
                end_idx = self.pending_data.find('\r\n')
                if end_idx == -1:
                    break  # Incomplete message
                    
                info_line = self.pending_data[:end_idx]
                self.pending_data = self.pending_data[end_idx + 2:]
                
                # Extract JSON from INFO
                json_start = info_line.find('{')
                if json_start != -1:
                    try:
                        info_data = json.loads(info_line[json_start:])
                        self.server_info = info_data
                        messages.append({
                            'type': 'INFO',
                            'data': info_data
                        })
                    except json.JSONDecodeError as e:
                        logger.error(f"Failed to parse INFO: {e}")
                        
            elif self.pending_data.startswith(MSG):
                # MSG format: MSG <subject> <sid> [reply-to] <#bytes>\r\n<payload>\r\n
                logger.info(f"🔍 Found MSG in data stream")
                end_idx = self.pending_data.find('\r\n')
                if end_idx == -1:
                    logger.debug(f"MSG header incomplete, waiting for more data")
                    break  # Incomplete header
                    
                msg_header = self.pending_data[:end_idx]
                remaining = self.pending_data[end_idx + 2:]
                
                # Parse MSG header
                parts = msg_header.split(' ')
                if len(parts) < 4:
                    logger.error(f"Invalid MSG header: {msg_header}")
                    self.pending_data = remaining
                    continue
                
                subject = parts[1]
                sid = parts[2]
                
                # Check if there's a reply-to
                if len(parts) == 4:
                    # No reply-to
                    size = int(parts[3])
                    reply_to = None
                else:
                    # Has reply-to
                    reply_to = parts[3]
                    size = int(parts[4])
                
                # Check if we have enough data for payload
                if len(remaining) < size + 2:  # +2 for \r\n
                    logger.debug(f"MSG payload incomplete: need {size + 2} bytes, have {len(remaining)}")
                    break  # Incomplete payload
                
                # Extract payload - keep it as bytes when possible
                if self.original_binary:
                    # We have the original binary data
                    # Find where this MSG starts in the original binary
                    msg_pattern = f"MSG {subject} {sid}".encode('utf-8')
                    
                    try:
                        # Find the MSG header in binary data
                        idx = self.original_binary.find(msg_pattern)
                        if idx != -1:
                            # Find the end of header (after size and \r\n)
                            header_end = self.original_binary.find(b'\r\n', idx)
                            if header_end != -1:
                                payload_start = header_end + 2  # Skip \r\n
                                payload_end = payload_start + size
                                
                                if payload_end <= len(self.original_binary):
                                    # Extract binary payload directly
                                    payload = self.original_binary[payload_start:payload_end]
                                else:
                                    # Incomplete data, use what we have
                                    payload = remaining[:size].encode('latin-1', errors='ignore')
                            else:
                                payload = remaining[:size].encode('latin-1', errors='ignore')
                        else:
                            # MSG not found in binary, use string data
                            payload = remaining[:size].encode('latin-1', errors='ignore')
                    except Exception as e:
                        logger.warning(f"Failed to extract binary payload: {e}")
                        payload = remaining[:size].encode('latin-1', errors='ignore')
                else:
                    # No binary data available, encode the string
                    payload = remaining[:size].encode('latin-1', errors='ignore')
                
                self.pending_data = remaining[size + 2:]  # Skip payload and \r\n
                
                logger.info(f"📊 MSG parsed - Subject: {subject}, SID: {sid}, Size: {size}")
                
                # Process the message
                if sid in self.subscriptions:
                    sub = self.subscriptions[sid]
                    sub.received_msgs += 1
                    logger.info(f"✅ Subscription found for SID {sid}: {sub.subject}")
                    
                    messages.append({
                        'type': 'MSG',
                        'subject': subject,
                        'sid': sid,
                        'reply_to': reply_to,
                        'size': size,
                        'payload': payload,  # Now this is bytes
                        'subscription': sub
                    })
                    
                    # Check if we should auto-unsub
                    if sub.max_msgs and sub.received_msgs >= sub.max_msgs:
                        del self.subscriptions[sid]
                else:
                    logger.warning(f"⚠️ No subscription for SID {sid}, still adding message")
                    messages.append({
                        'type': 'MSG',
                        'subject': subject,
                        'sid': sid,
                        'reply_to': reply_to,
                        'size': size,
                        'payload': payload,  # Now this is bytes
                        'subscription': None
                    })
                        
            elif self.pending_data.startswith(PING):
                # PING message
                end_idx = self.pending_data.find('\r\n')
                if end_idx == -1:
                    break
                    
                self.pending_data = self.pending_data[end_idx + 2:]
                messages.append({'type': 'PING'})
                
            elif self.pending_data.startswith(PONG):
                # PONG message
                end_idx = self.pending_data.find('\r\n')
                if end_idx == -1:
                    break
                    
                self.pending_data = self.pending_data[end_idx + 2:]
                messages.append({'type': 'PONG'})
                
            elif self.pending_data.startswith(OK):
                # +OK message
                end_idx = self.pending_data.find('\r\n')
                if end_idx == -1:
                    break
                    
                self.pending_data = self.pending_data[end_idx + 2:]
                messages.append({'type': 'OK'})
                
            elif self.pending_data.startswith(ERR):
                # -ERR message
                end_idx = self.pending_data.find('\r\n')
                if end_idx == -1:
                    break
                    
                err_line = self.pending_data[:end_idx]
                self.pending_data = self.pending_data[end_idx + 2:]
                
                # Extract error message
                error_msg = err_line[4:].strip().strip("'\"")
                messages.append({
                    'type': 'ERR',
                    'error': error_msg
                })
            else:
                # Unknown or incomplete message, try to find next known command
                next_cmd_idx = -1
                for cmd in [INFO, MSG, PING, PONG, OK, ERR]:
                    idx = self.pending_data.find(cmd)
                    if idx > 0 and (next_cmd_idx == -1 or idx < next_cmd_idx):
                        next_cmd_idx = idx
                
                if next_cmd_idx > 0:
                    # Skip unknown data
                    logger.debug(f"Skipping unknown data: {self.pending_data[:next_cmd_idx]}")
                    self.pending_data = self.pending_data[next_cmd_idx:]
                else:
                    # No known command found, wait for more data
                    break
        
        return messages
    
    def format_topic_for_groww(self, exchange: str, segment: str, token: str, mode: str) -> str:
        """
        Format subscription topic for Groww

        Args:
            exchange: Exchange (NSE, BSE)
            segment: Segment (CASH, FNO)
            token: Exchange token
            mode: Subscription mode (ltp, depth, index, index_depth)

        Returns:
            Formatted NATS subject
        """
        exchange = exchange.upper()
        segment = segment.upper()

        # Log for debugging
        logger.info(f"Formatting topic - Exchange: {exchange}, Segment: {segment}, Token: {token}, Mode: {mode}")

        # Handle index modes
        if mode == "index" or mode == "index_ltp":
            # Format: /ld/indices/nse/price.{token}
            # Exchange should be NSE or BSE (not NSE_INDEX or BSE_INDEX)
            clean_exchange = exchange.replace('_INDEX', '').lower()
            topic = f"/ld/indices/{clean_exchange}/price.{token}"
            logger.info(f"Index LTP topic generated: {topic}")
            return topic
        elif mode == "index_depth":
            # Try depth format for indices: /ld/indices/nse/book.{token}
            clean_exchange = exchange.replace('_INDEX', '').lower()
            topic = f"/ld/indices/{clean_exchange}/book.{token}"
            logger.info(f"Index DEPTH topic generated (experimental): {topic}")
            return topic

        # Determine segment prefix based on segment
        if segment == "CASH":
            seg_prefix = "eq"
        elif segment == "FNO":
            seg_prefix = "fo"
        elif segment == "COMM":
            seg_prefix = "comm"
        elif segment == "CDS":
            seg_prefix = "cds"
        else:
            seg_prefix = segment.lower()

        if mode == "ltp":
            # Format: /ld/eq/nse/price.{token}
            topic = f"/ld/{seg_prefix}/{exchange.lower()}/price.{token}"
        elif mode == "depth":
            # Format: /ld/eq/nse/book.{token}
            topic = f"/ld/{seg_prefix}/{exchange.lower()}/book.{token}"
        else:
            # Default to price
            topic = f"/ld/{seg_prefix}/{exchange.lower()}/price.{token}"

        logger.info(f"Topic generated: {topic}")
        return topic