"""
Minimal MQTT v3.1.1 client used by the IIFL Capital streaming adapter.

This is a hand-rolled, stdlib-only implementation modelled after the subset of
paho-mqtt that the official IIFL bridgePy SDK exercises. Only the control
packets required by IIFL's market-data broker are supported:

    CONNECT / CONNACK
    SUBSCRIBE / SUBACK
    UNSUBSCRIBE / UNSUBACK
    PUBLISH (QoS 0 only — incoming)
    PINGREQ / PINGRESP
    DISCONNECT

No QoS 1/2 inflight tracking, no retained messages, no will message, no
session resumption — the IIFL broker only publishes QoS 0 to subscribers and
expects clean_session=True clients.

The transport is a single TLS socket (TLSv1.2 minimum) verified against the
system trust store. A background reader thread parses frames off the wire and
dispatches to user callbacks; a second thread sends PINGREQ inside the
keepalive window so the broker does not drop us.
"""

from __future__ import annotations

import socket
import ssl
import struct
import threading
import time
from collections.abc import Callable
from typing import Optional

from utils.logging import get_logger

# Control packet types (high nibble of fixed-header byte 1)
_CONNECT = 0x10
_CONNACK = 0x20
_PUBLISH = 0x30
_SUBSCRIBE = 0x82  # type=8, flags=0010 (reserved bits required by spec)
_SUBACK = 0x90
_UNSUBSCRIBE = 0xA2  # type=10, flags=0010
_UNSUBACK = 0xB0
_PINGREQ = 0xC0
_PINGRESP = 0xD0
_DISCONNECT = 0xE0

_MQTT_PROTOCOL_NAME = b"MQTT"
_MQTT_PROTOCOL_LEVEL = 0x04  # MQTT v3.1.1

# CONNACK return codes (MQTT v3.1.1 §3.2.2.3)
CONNACK_ACCEPTED = 0
CONNACK_REASONS = {
    0: "Connection Accepted",
    1: "Connection Refused: unacceptable protocol version",
    2: "Connection Refused: identifier rejected",
    3: "Connection Refused: server unavailable",
    4: "Connection Refused: bad user name or password",
    5: "Connection Refused: not authorized",
}


def _encode_remaining_length(length: int) -> bytes:
    """Encode an MQTT variable-byte integer (1–4 bytes)."""
    if length < 0 or length > 268_435_455:
        raise ValueError(f"Remaining length out of range: {length}")
    out = bytearray()
    while True:
        byte = length & 0x7F
        length >>= 7
        if length:
            byte |= 0x80
            out.append(byte)
        else:
            out.append(byte)
            break
    return bytes(out)


def _encode_string(value: str) -> bytes:
    """Encode a UTF-8 string with a 2-byte big-endian length prefix."""
    data = value.encode("utf-8")
    return struct.pack(">H", len(data)) + data


class MqttError(Exception):
    """Raised for MQTT-level protocol failures."""


class IiflMqttClient:
    """
    Synchronous MQTT v3.1.1 client tailored for IIFL Capital's bridge.

    Usage:
        client = IiflMqttClient(host="bridge.iiflcapital.com", port=8883,
                                client_id="...", username="...", password="...",
                                keepalive=20)
        client.on_message = lambda topic, payload: ...
        client.on_connect = lambda rc, reason: ...
        client.connect()
        client.subscribe(["prod/marketfeed/mw/v1/nseeq/2885"])

    The client owns one TLS socket and two daemon threads (reader + keepalive).
    All sends are serialised by an internal lock so subscribe/unsubscribe calls
    from the adapter layer are thread-safe.
    """

    # Reader keeps grabbing packets until it sees stop_event or the socket dies.
    # We never timeout the socket; PINGREQ keeps the broker happy and a dead
    # socket surfaces as a read returning b"".
    _RECV_BUF = 65536

    def __init__(
        self,
        host: str,
        port: int,
        client_id: str,
        username: str,
        password: str,
        keepalive: int = 20,
    ) -> None:
        self.host = host
        self.port = port
        self.client_id = client_id
        self.username = username
        self.password = password
        self.keepalive = max(5, int(keepalive))

        self.logger = get_logger("iifl_mqtt")
        self._sock: ssl.SSLSocket | None = None
        self._send_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._connected = threading.Event()
        self._reader_thread: threading.Thread | None = None
        self._keepalive_thread: threading.Thread | None = None

        # Packet identifier for SUBSCRIBE/UNSUBSCRIBE (1..65535, wraps).
        self._packet_id = 0
        self._packet_id_lock = threading.Lock()

        # Callbacks. All are optional; missing ones are simply skipped.
        self.on_connect: Callable[[int, str], None] | None = None
        self.on_disconnect: Callable[[Optional[Exception]], None] | None = None
        self.on_message: Callable[[str, bytes], None] | None = None
        self.on_subscribe: Callable[[int, list[int]], None] | None = None
        self.on_unsubscribe: Callable[[int], None] | None = None
        self.on_error: Callable[[Exception], None] | None = None

    # ------------------------------------------------------------------ public
    def is_connected(self) -> bool:
        return self._connected.is_set() and self._sock is not None

    def connect(self, timeout: float = 15.0) -> int:
        """
        Open the TLS socket, send CONNECT, wait for CONNACK.

        Returns the CONNACK return code (0 = accepted). Raises on socket or
        TLS failure before the MQTT layer is reached.
        """
        # Defensive cleanup if the caller is reusing the instance.
        self._stop_event.clear()
        self._connected.clear()

        raw = socket.create_connection((self.host, self.port), timeout=timeout)
        try:
            ctx = ssl.create_default_context()
            ctx.minimum_version = ssl.TLSVersion.TLSv1_2
            self._sock = ctx.wrap_socket(raw, server_hostname=self.host)
        except Exception:
            raw.close()
            raise

        # Anything below here happens AFTER we own a live TLS FD — any
        # exception in send_connect / read_packet / CONNACK parsing must
        # close that FD before propagating, otherwise we leak a socket on
        # every failed handshake (caller will just create a new client and
        # retry — the abandoned socket sits in CLOSE_WAIT until GC).
        try:
            # Now switch to blocking with no read deadline — reader thread blocks.
            self._sock.settimeout(None)

            self._send_connect()

            # Read CONNACK inline; we need its return code before we start the
            # reader thread. Use a temporary deadline so a broker that hangs at
            # this stage does not block the caller forever.
            self._sock.settimeout(timeout)
            try:
                packet_type, _flags, body = self._read_packet()
            finally:
                # Restore blocking mode only if we still own the socket; the
                # close-on-failure branch below nulls it out.
                if self._sock is not None:
                    self._sock.settimeout(None)

            if packet_type != _CONNACK >> 4:
                raise MqttError(f"Expected CONNACK, got packet type {packet_type}")
            if len(body) < 2:
                raise MqttError("Truncated CONNACK")
        except BaseException:
            # Cover both regular exceptions and bare control-flow exits
            # (timeouts, KeyboardInterrupt) — we must not leave a TLS FD
            # behind regardless of how we got here.
            sock = self._sock
            self._sock = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
            raise

        # Byte 0: session present flag (ignored — we use clean_session)
        # Byte 1: return code
        rc = body[1]
        reason = CONNACK_REASONS.get(rc, f"Unknown CONNACK code {rc}")

        if rc != CONNACK_ACCEPTED:
            # Surface the auth failure to the caller; close the socket.
            try:
                self._sock.close()
            finally:
                self._sock = None
            if self.on_connect:
                try:
                    self.on_connect(rc, reason)
                except Exception:
                    pass
            return rc

        # Reader and keepalive threads come up only after we know the broker
        # accepted us — avoids spurious "connection closed" callbacks on a
        # rejected handshake.
        self._connected.set()
        self._reader_thread = threading.Thread(
            target=self._reader_loop, daemon=True, name="IiflMqttReader"
        )
        self._reader_thread.start()
        self._keepalive_thread = threading.Thread(
            target=self._keepalive_loop, daemon=True, name="IiflMqttKeepalive"
        )
        self._keepalive_thread.start()

        if self.on_connect:
            try:
                self.on_connect(rc, reason)
            except Exception as e:
                self.logger.exception(f"on_connect callback raised: {e}")

        return rc

    def disconnect(self) -> None:
        """Send DISCONNECT (best-effort), close socket, stop threads."""
        self._stop_event.set()
        self._connected.clear()

        sock = self._sock
        self._sock = None
        if sock is not None:
            # MQTT DISCONNECT is 0xE0 0x00 — try to send it, but tolerate
            # the broker having already dropped the socket.
            try:
                sock.sendall(bytes([_DISCONNECT, 0x00]))
            except OSError:
                pass
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

        # Daemon threads exit on their own when stop_event is set; we do not
        # join them here to keep teardown non-blocking under eventlet.

    def subscribe(self, topics: list[str], qos: int = 0) -> int:
        """
        Send SUBSCRIBE for a list of topic filters. Returns the packet id
        used, so callers can correlate with on_subscribe(packet_id, granted_qos).
        """
        if not topics:
            return 0
        if not self.is_connected():
            raise MqttError("Cannot subscribe — not connected")

        pkt_id = self._next_packet_id()

        # Variable header: packet identifier (u16)
        # Payload: for each topic, (u16 len + utf-8) + u8 requested QoS
        body = struct.pack(">H", pkt_id)
        for topic in topics:
            body += _encode_string(topic)
            body += bytes([qos & 0x03])

        self._send_packet(_SUBSCRIBE, body)
        return pkt_id

    def unsubscribe(self, topics: list[str]) -> int:
        if not topics:
            return 0
        if not self.is_connected():
            raise MqttError("Cannot unsubscribe — not connected")

        pkt_id = self._next_packet_id()
        body = struct.pack(">H", pkt_id)
        for topic in topics:
            body += _encode_string(topic)

        self._send_packet(_UNSUBSCRIBE, body)
        return pkt_id

    # ------------------------------------------------------------------ private
    def _next_packet_id(self) -> int:
        with self._packet_id_lock:
            self._packet_id = (self._packet_id % 65535) + 1
            return self._packet_id

    def _send_connect(self) -> None:
        """
        Build & send the MQTT CONNECT packet matching bridgePy's parameters:
          - Protocol name "MQTT", level 0x04 (v3.1.1)
          - Connect flags: clean_session | username | password (no will)
          - Keep alive: self.keepalive
          - Payload: client_id, username, password
        """
        # Variable header
        var_header = _encode_string(_MQTT_PROTOCOL_NAME.decode())  # "MQTT"
        var_header += bytes([_MQTT_PROTOCOL_LEVEL])
        # Connect flags:
        #   bit 7 username, bit 6 password, bit 1 clean_session.
        connect_flags = 0b11000010
        var_header += bytes([connect_flags])
        var_header += struct.pack(">H", self.keepalive)

        # Payload
        payload = _encode_string(self.client_id)
        payload += _encode_string(self.username)
        payload += _encode_string(self.password)

        body = var_header + payload
        frame = bytes([_CONNECT]) + _encode_remaining_length(len(body)) + body

        # CONNECT bypasses the send lock — there is no reader running yet, and
        # nothing else writes to the socket before CONNACK comes back.
        assert self._sock is not None
        self._sock.sendall(frame)

    def _send_packet(self, fixed_header_byte: int, body: bytes) -> None:
        """
        Serialise outbound traffic on the socket. Reader thread never writes,
        but subscribe/unsubscribe and PINGREQ can race each other.
        """
        frame = bytes([fixed_header_byte]) + _encode_remaining_length(len(body)) + body
        with self._send_lock:
            sock = self._sock
            if sock is None:
                raise MqttError("Socket closed")
            sock.sendall(frame)

    def _send_pingreq(self) -> None:
        # PINGREQ has no variable header or payload — just 0xC0 0x00.
        with self._send_lock:
            sock = self._sock
            if sock is None:
                return
            try:
                sock.sendall(bytes([_PINGREQ, 0x00]))
            except OSError as e:
                self.logger.debug(f"PINGREQ send failed: {e}")

    def _read_exact(self, n: int) -> bytes:
        """Read exactly n bytes from the socket; b"" if the peer closed."""
        sock = self._sock
        if sock is None:
            return b""
        chunks: list[bytes] = []
        remaining = n
        while remaining > 0:
            try:
                chunk = sock.recv(min(remaining, self._RECV_BUF))
            except (InterruptedError, OSError) as e:
                # Socket closed from another thread (typically our own
                # disconnect) or recv interrupted. On Windows this surfaces
                # as WSACancelBlockingCall (WinError 10004); on POSIX as
                # EBADF/ECONNRESET. Treat as clean close so the reader loop
                # exits via its MqttError handler instead of crashing.
                raise MqttError(f"Socket recv interrupted: {e}") from e
            if not chunk:
                return b""
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _read_remaining_length(self) -> int:
        """
        Decode the MQTT variable-byte integer that follows the fixed-header
        first byte. Up to 4 continuation bytes.
        """
        multiplier = 1
        value = 0
        for _ in range(4):
            byte = self._read_exact(1)
            if not byte:
                raise MqttError("Socket closed while reading remaining length")
            digit = byte[0]
            value += (digit & 0x7F) * multiplier
            if (digit & 0x80) == 0:
                return value
            multiplier *= 128
        raise MqttError("Malformed remaining length (more than 4 bytes)")

    def _read_packet(self) -> tuple[int, int, bytes]:
        """
        Read one MQTT control packet. Returns (packet_type_nibble, flags_nibble, body_bytes).
        Raises MqttError if the stream is closed.
        """
        header = self._read_exact(1)
        if not header:
            raise MqttError("Socket closed")
        first = header[0]
        packet_type = (first & 0xF0) >> 4
        flags = first & 0x0F

        remaining = self._read_remaining_length()
        body = self._read_exact(remaining) if remaining else b""
        if remaining and len(body) != remaining:
            raise MqttError("Truncated MQTT body")
        return packet_type, flags, body

    def _reader_loop(self) -> None:
        """
        Background reader. Decodes inbound packets and dispatches callbacks.
        Exits when the socket is closed or stop_event is set.
        """
        try:
            while not self._stop_event.is_set():
                try:
                    packet_type, flags, body = self._read_packet()
                except MqttError:
                    # Clean close — peer hung up or we shut down.
                    break

                if packet_type == _PUBLISH >> 4:
                    self._handle_publish(flags, body)
                elif packet_type == _SUBACK >> 4:
                    self._handle_suback(body)
                elif packet_type == _UNSUBACK >> 4:
                    self._handle_unsuback(body)
                elif packet_type == _PINGRESP >> 4:
                    # No-op; the keepalive thread does not currently check
                    # for pong arrival — broker drop surfaces as recv == b"".
                    pass
                else:
                    self.logger.debug(
                        f"Unexpected MQTT packet type {packet_type} (flags={flags}, len={len(body)})"
                    )
        except Exception as e:  # noqa: BLE001 — surface to on_error callback
            self.logger.exception(f"Reader loop crashed: {e}")
            if self.on_error:
                try:
                    self.on_error(e)
                except Exception:
                    pass
        finally:
            self._connected.clear()
            # Close the FD here, not in disconnect(), because the broker
            # FIN path (or any reader-side exception) gets us here without
            # any external code knowing the socket is dead. Without this
            # explicit close, the FD sits in CLOSE_WAIT until garbage
            # collection — one leaked FD per reconnect cycle. disconnect()
            # remains idempotent because it nulls _sock and tolerates a
            # None value.
            sock = self._sock
            self._sock = None
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass

            # Wake the keepalive thread so it exits promptly instead of
            # blocking on its next wait(keepalive/2) tick. `_stop_event`
            # is per-instance, so signalling here only affects this
            # client; a fresh IiflMqttClient on reconnect has its own
            # event and is unaffected.
            self._stop_event.set()

            if self.on_disconnect:
                try:
                    self.on_disconnect(None)
                except Exception as e:
                    self.logger.exception(f"on_disconnect callback raised: {e}")

    def _handle_publish(self, flags: int, body: bytes) -> None:
        """
        PUBLISH variable header:
            Topic Name (u16 len + utf-8)
            [Packet Identifier (u16) — only if QoS > 0; we only see QoS 0]
        Payload:
            remaining bytes after the variable header
        """
        if len(body) < 2:
            self.logger.debug("PUBLISH too short to contain topic length")
            return

        topic_len = struct.unpack(">H", body[0:2])[0]
        if len(body) < 2 + topic_len:
            self.logger.debug("PUBLISH truncated topic")
            return

        topic = body[2:2 + topic_len].decode("utf-8", errors="replace")
        qos = (flags & 0x06) >> 1

        # We negotiated QoS 0 on subscribe, so the broker should never send
        # us QoS 1/2. If it does, skip the packet identifier defensively so
        # we don't mis-parse the payload.
        offset = 2 + topic_len
        if qos > 0:
            offset += 2

        payload = body[offset:]

        if self.on_message:
            try:
                self.on_message(topic, payload)
            except Exception as e:
                self.logger.exception(f"on_message callback raised: {e}")

    def _handle_suback(self, body: bytes) -> None:
        if len(body) < 3:
            return
        packet_id = struct.unpack(">H", body[0:2])[0]
        granted = list(body[2:])
        if self.on_subscribe:
            try:
                self.on_subscribe(packet_id, granted)
            except Exception as e:
                self.logger.exception(f"on_subscribe callback raised: {e}")

    def _handle_unsuback(self, body: bytes) -> None:
        if len(body) < 2:
            return
        packet_id = struct.unpack(">H", body[0:2])[0]
        if self.on_unsubscribe:
            try:
                self.on_unsubscribe(packet_id)
            except Exception as e:
                self.logger.exception(f"on_unsubscribe callback raised: {e}")

    def _keepalive_loop(self) -> None:
        """
        Send PINGREQ every keepalive/2 seconds while connected. This is a
        defensive interval — the broker disconnects after 1.5 × keepalive
        with no traffic, so pinging at the half-period gives us slack.
        """
        interval = max(2, self.keepalive // 2)
        while not self._stop_event.is_set():
            if self._stop_event.wait(interval):
                break
            if not self.is_connected():
                break
            self._send_pingreq()
