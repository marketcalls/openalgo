"""
WhatsApp Bot Service — pair, connect, send, and command dispatch.

Wraps the `wars` library (PyO3 binding over whatsapp-rust). wars is a
synchronous, single-process WhatsApp Web client: one paired session per
process. OpenAlgo already runs `gunicorn -w 1` for SocketIO compatibility,
so the one-process-only constraint costs nothing.

Lifecycle:

    [unpaired]  --start_pair-->  [pairing: temp DB + QR loop]
                                          |
                              on_connected from wars
                                          |
                                          v
                        export_session bytes -> encrypt -> openalgo.db
                                          |
                                          v
    [paired, idle]  --start_bot-->  [paired, connected]
                                          |
                              wars background thread polls
                                          |
                              incoming msgs -> @on_message -> _dispatch_command
                                          |
                              outbound sends from alert_service -> send_sync
                                          |
                                       stop_bot
                                          |
                                          v
                                  [paired, idle]

wars imports happen lazily inside methods so missing wheels never block the
Flask app from booting; the /whatsapp UI surfaces a clear install hint instead.
"""

from __future__ import annotations

import os

# Quiet wars / whatsapp-rust / wacore log spam from WhatsApp's multi-device
# protocol. These are not actionable for the operator and contain no
# sensitive data (LIDs are not phone numbers — they're WhatsApp's privacy-
# preserving identifiers). Three sources need suppressing:
#
#   wacore::send                      WARN "Failed to encrypt for device:
#                                          <stale-LID>: session ... not found.
#                                          Skipping." — fires when sending to
#                                          contacts whose linked-device list
#                                          has stale entries; wars skips them
#                                          and delivery to live devices still
#                                          succeeds.
#   whatsapp_rust::message            WARN "Decryption still failed after
#                                          PN->LID migration: SessionNotFound"
#                                          / "Dispatching UndecryptableMessage
#                                          event" — fires when an incoming
#                                          message arrives from a device wars
#                                          has no Signal session for; wars
#                                          dispatches an UndecryptableMessage
#                                          event but keeps running.
#   wacore_libsignal::protocol::      ERROR "Message from <LID> failed to
#     session_cipher                        decrypt; ... No current session"
#                                          — the lower-level libsignal log
#                                          that whatsapp_rust::message already
#                                          handles above. Silence at source.
#
# Default policy: error for everything, off for the three noisy targets.
# Set RUST_LOG in the shell/.env to override for diagnostics (setdefault
# means an explicit operator-set value always wins).
_RUST_LOG_DEFAULT = (
    "error"
    ",wacore::send=off"
    ",whatsapp_rust::message=off"
    ",wacore_libsignal::protocol::session_cipher=off"
)
os.environ.setdefault("RUST_LOG", _RUST_LOG_DEFAULT)

import queue
import re
import tempfile
import threading
from collections.abc import Callable
from datetime import datetime
from typing import Any

from database.whatsapp_db import (
    clear_session_blob,
    get_bot_config,
    load_session_blob,
    log_command,
    save_session_blob,
    update_bot_config,
)
from utils.logging import get_logger

logger = get_logger(__name__)

# wars supports E.164 digit strings as JIDs anywhere a "to" is accepted.
# We still normalize internally so cached lookups are stable.
_PHONE_RE = re.compile(r"\D")

# E.164 spec allows up to 15 digits including country code. Minimum 7 is the
# shortest plausible national number (most countries are >= 8). Anything
# outside this band is almost certainly a typo; we reject early to avoid
# wars round-tripping garbage to WhatsApp.
_PHONE_MIN_DIGITS = 7
_PHONE_MAX_DIGITS = 15


def normalize_phone(raw) -> str:
    """Strip non-digits and validate E.164 length. Returns "" if the input
    can't plausibly be a phone number. wars accepts 919xxx or '+91 98xxx'
    equally; we canonicalize to bare digits.

    Accepts ``str`` or ``int`` — some JSON clients send a 12-digit phone as
    a bare number literal which Python's json parser hands us as an
    ``int``. We coerce defensively so the regex below never sees a non-str.

    Floats are **rejected** outright. ``str(919346668666.0)`` would produce
    ``"919346668666.0"``, and after stripping non-digits we'd silently send
    to ``9193466686660`` (a 13-digit number that is not the operator's
    actual contact). Better to fail the call than send to the wrong number.
    JSON has no integer/float distinction so any phone number above 2^53
    can also arrive as a float from a non-Python client; refusing is the
    correct response in both cases.
    """
    if raw is None or isinstance(raw, bool):
        # bool is a subclass of int, but `True`/`False` is never a phone.
        return ""
    if isinstance(raw, float):
        return ""
    text = raw if isinstance(raw, str) else str(raw)
    digits = _PHONE_RE.sub("", text)
    if not (_PHONE_MIN_DIGITS <= len(digits) <= _PHONE_MAX_DIGITS):
        return ""
    return digits


# Attachment paths are server-local file paths the caller wants to forward
# over WhatsApp. Without bounds, a leaked API key could exfiltrate any file
# the OpenAlgo process can read (/etc/passwd, env files, broker token DB,
# etc.) by sending it to an attacker-controlled WhatsApp number.
#
# Defense in depth:
#   1. Reject anything that isn't an absolute path or that contains traversal
#      tokens (``..``).
#   2. Resolve the real path (follows one layer of symlinks) and require the
#      result to live under WHATSAPP_ATTACHMENT_ROOTS — a comma-separated
#      whitelist read from .env. If unset, we default to the project's
#      `db/attachments/` directory only.
#   3. Reject anything inside obviously sensitive system trees so a
#      misconfigured allowlist can't accidentally expose secrets.
_DENY_ROOTS = (
    "/etc",
    "/proc",
    "/sys",
    "/root",
    "/var/log",
    "C:\\Windows",
    "C:\\Users\\Default",
)


def _default_attachment_roots() -> list[str]:
    raw = os.getenv("WHATSAPP_ATTACHMENT_ROOTS", "")
    roots = [r.strip() for r in raw.split(",") if r.strip()] if raw else []
    if not roots:
        # Default sandbox: a single directory beside the project's db/.
        roots = [os.path.abspath(os.path.join(os.getcwd(), "db", "attachments"))]
    return [os.path.abspath(r) for r in roots]


def validate_attachment_path(path: str | None) -> str | None:
    """Return the resolved path if it is safe to read, else None.

    Callers should treat None as "reject" and bail out before passing the
    value to wars. Logs the rejection reason but never logs the raw path
    (which may itself be sensitive)."""
    if not path:
        return None
    try:
        if ".." in path.replace("\\", "/").split("/"):
            logger.warning("Attachment path rejected: contains traversal token")
            return None
        if not os.path.isabs(path):
            logger.warning("Attachment path rejected: not absolute")
            return None
        resolved = os.path.realpath(path)
        # Reject sensitive system paths up-front.
        for deny in _DENY_ROOTS:
            if resolved.lower().startswith(deny.lower()):
                logger.warning("Attachment path rejected: inside denied system tree")
                return None
        roots = _default_attachment_roots()
        if not any(
            resolved.lower().startswith(os.path.abspath(r).lower() + os.sep)
            or resolved.lower() == os.path.abspath(r).lower()
            for r in roots
        ):
            logger.warning(
                "Attachment path rejected: outside WHATSAPP_ATTACHMENT_ROOTS allowlist"
            )
            return None
        if not os.path.isfile(resolved):
            logger.warning("Attachment path rejected: not a regular file")
            return None
        return resolved
    except OSError:
        logger.warning("Attachment path rejected: stat failed")
        return None


def phone_to_jid(phone_digits: str) -> str:
    """Build the WhatsApp 1:1 JID from E.164 digits."""
    return f"{phone_digits}@s.whatsapp.net"


def jid_to_phone(jid: str) -> str:
    """Extract digits from a JID. Group JIDs (`...@g.us`) return empty."""
    if not jid or "@s.whatsapp.net" not in jid:
        return ""
    return jid.split("@", 1)[0]


# Sentinel exception raised when wars isn't installed. Callers catch this and
# surface a friendly install message instead of a stack trace.
class WarsNotInstalled(RuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "wars package is not installed. Run `uv sync` or `uv pip install wars` "
            "to enable the WhatsApp integration."
        )


def _import_wars():
    try:
        import wars  # type: ignore
        return wars
    except Exception as e:  # ImportError or compile errors on first install
        raise WarsNotInstalled() from e


class WhatsAppBotService:
    """One singleton per process. Owns the wars client, the pairing state
    machine, and the slash-command dispatcher."""

    # PyO3 thread-confinement: `wars.WhatsApp` is `#[pyclass(unsendable)]`,
    # which panics on every method call from a thread other than the one
    # that created it. We therefore park the long-lived wars instance on a
    # dedicated worker thread (`_bot_thread`) and funnel all `wa.*` calls
    # through `_cmd_queue`. Request threads enqueue and wait on an Event
    # for the result — the worker is the only thread that ever touches the
    # PyO3 object directly. Same pattern the Telegram service uses for PTB,
    # for the same reason.
    SEND_TIMEOUT: float = 30.0

    def __init__(self) -> None:
        self._wa = None  # owned exclusively by _bot_thread for its lifetime
        self._lock = threading.RLock()
        self._is_running = False
        self._is_paired = False

        # Worker thread + cross-thread command channel.
        self._bot_thread: threading.Thread | None = None
        self._bot_thread_id: int | None = None  # used for re-entrancy in send_sync
        self._cmd_queue: queue.Queue[tuple] = queue.Queue()
        self._stop_event = threading.Event()
        self._ready_event = threading.Event()

        # Pairing state — read by REST /pair/status, written by the pairing
        # thread. Protected by _lock.
        self._pair_state: dict[str, Any] = {
            "status": "idle",  # idle | starting | awaiting_scan | paired | failed
            "qr_data_url": None,
            "pair_code": None,
            "error": None,
            "started_at": None,
            "paired_at": None,
        }
        self._pair_thread: threading.Thread | None = None
        self._pair_temp_db: str | None = None
        self._pair_wa = None  # wars.WhatsApp instance owned by the pairing thread

    # ------------------------------------------------------------------
    # Public state
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def is_paired(self) -> bool:
        if self._is_paired:
            return True
        return bool(get_bot_config().get("is_paired"))

    def is_ready(self) -> bool:
        """True iff the bot can actually deliver a message right now —
        paired AND the wars background loop is connected. Callers in the
        send path should gate on this so callers see a clear "pair first"
        error instead of a silent queue."""
        return self._is_running and self._wa is not None and self.is_paired

    def get_pair_state(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._pair_state)

    # ------------------------------------------------------------------
    # Pairing — generates QR data URLs and emits them via SocketIO so the
    # frontend can render them inline without ever writing a PNG to disk.
    # ------------------------------------------------------------------

    def start_pair(
        self,
        phone: str | None = None,
        owner_user_id: int | None = None,
        owner_username: str | None = None,
    ) -> tuple[bool, str]:
        """Begin pairing. Non-blocking — runs in a background thread.

        If `phone` is provided (E.164 digits), wars will request a pair-code
        from WhatsApp instead of a QR. Both modes coexist; either works.

        `owner_user_id` + `owner_username` come from the Flask session of the
        logged-in admin who clicked Pair. Saved alongside the session blob
        so the bot's command handlers can resolve the operator's api_key
        without any per-WhatsApp-user linking flow.
        """
        with self._lock:
            if self._pair_state["status"] in ("starting", "awaiting_scan"):
                return False, "Pairing already in progress"
            if self._is_running:
                return False, "Bot is currently connected. Stop it before re-pairing."

            try:
                _import_wars()  # presence check; the worker thread imports again
            except WarsNotInstalled as e:
                return False, str(e)

            # File-backed temp DB — required because wars.export_session()
            # cannot snapshot an in-memory DB (Rust + Python use different
            # SQLite library instances). 0600 perms; deleted as soon as we
            # have the bytes.
            fd, tmp_path = tempfile.mkstemp(suffix=".db", prefix="openalgo_wa_pair_")
            os.close(fd)
            try:
                os.chmod(tmp_path, 0o600)
            except OSError:
                # Windows doesn't honor chmod the same way; best-effort.
                pass

            self._pair_temp_db = tmp_path
            self._pair_state = {
                "status": "starting",
                "qr_data_url": None,
                "pair_code": None,
                "error": None,
                "started_at": datetime.utcnow().isoformat(),
                "paired_at": None,
            }

            t = threading.Thread(
                target=self._run_pair,
                args=(tmp_path, phone, owner_user_id, owner_username),
                daemon=True,
                name="WhatsAppPairThread",
            )
            self._pair_thread = t
            t.start()
            return True, "Pairing started. Watch for QR or pair code."

    def _run_pair(
        self,
        temp_db_path: str,
        phone: str | None,
        owner_user_id: int | None = None,
        owner_username: str | None = None,
    ) -> None:
        """Worker thread: opens a temp-DB wars client, streams QR / pair code
        via SocketIO, waits for the phone-side scan, then exports + encrypts +
        persists the session blob and unlinks the temp file.

        The authoritative "paired" signal is ``wars.wait_until_ready()``: it
        unblocks only when WhatsApp has confirmed the device is paired AND
        the websocket is online. We do NOT register an on_connected callback
        — wars fires that on every socket-up event (including the initial
        handshake before pairing), which would race finalize with an empty
        session blob. We also skip on_disconnect because wars cycles the
        temp connection on its own after a successful pair, and that would
        otherwise flip our state back to "failed".
        """
        finalized = False
        try:
            wars = _import_wars()
            wa = wars.WhatsApp(temp_db_path)
            self._pair_wa = wa
            logger.info("WhatsApp pair: temp wars client created, registering handlers")

            @wa.on_qr
            def _on_qr(code: str) -> None:
                try:
                    data_url = wars.qr_to_data_url(code)
                except Exception:
                    logger.exception("WhatsApp pair: qr_to_data_url failed")
                    data_url = None
                with self._lock:
                    self._pair_state["status"] = "awaiting_scan"
                    self._pair_state["qr_data_url"] = data_url
                self._emit("whatsapp_qr", {"data_url": data_url})
                logger.info("WhatsApp pair: QR emitted (rotation)")

            @wa.on_pair_code
            def _on_pair_code(code: str) -> None:
                with self._lock:
                    self._pair_state["status"] = "awaiting_scan"
                    self._pair_state["pair_code"] = code
                self._emit("whatsapp_pair_code", {"code": code})
                logger.info("WhatsApp pair: pair code issued")

            logger.info("WhatsApp pair: calling wars.connect(phone=%r)", phone)
            wa.connect(phone=phone)

            logger.info("WhatsApp pair: waiting for phone-side scan (up to 300s)")
            wa.wait_until_ready(timeout=300)

            # If we got here, WhatsApp has confirmed the pair. Finalize
            # synchronously on this thread — the temp wars instance is
            # already in a "paired+online" state, so export_session has
            # everything it needs.
            logger.info("WhatsApp pair: wait_until_ready returned — pairing succeeded")
            self._finalize_pair(wa, temp_db_path, owner_user_id, owner_username)
            finalized = True

        except WarsNotInstalled as e:
            logger.warning("WhatsApp pair: wars not installed: %s", e)
            with self._lock:
                self._pair_state["status"] = "failed"
                self._pair_state["error"] = str(e)
            self._emit("whatsapp_pair_status", self.get_pair_state())
        except TimeoutError as e:
            logger.warning("WhatsApp pair: wait_until_ready timed out: %s", e)
            with self._lock:
                self._pair_state["status"] = "failed"
                self._pair_state["error"] = "Pairing timed out — please try again"
            self._emit("whatsapp_pair_status", self.get_pair_state())
        except Exception as e:
            logger.exception("WhatsApp pair: worker crashed")
            with self._lock:
                self._pair_state["status"] = "failed"
                self._pair_state["error"] = str(e)
            self._emit("whatsapp_pair_status", self.get_pair_state())
        finally:
            # Cleanup if we didn't reach "paired" state. _finalize_pair owns
            # the disconnect + unlink when it succeeds, so we only run this
            # branch on the failure paths.
            if not finalized:
                with self._lock:
                    if self._pair_wa is not None:
                        try:
                            self._pair_wa.disconnect()
                        except Exception:
                            logger.debug("pair: temp-DB disconnect raised", exc_info=True)
                    self._cleanup_pair_temp()

    def _finalize_pair(
        self,
        wa,
        temp_db_path: str,
        owner_user_id: int | None = None,
        owner_username: str | None = None,
    ) -> None:
        """Export the wars session from the temp client, encrypt+persist the
        blob into openalgo.db, then disconnect the temp client and auto-start
        the long-lived bot from the saved bytes."""
        try:
            logger.info("WhatsApp pair: exporting session bytes from temp client")
            blob = wa.export_session()
            if not blob:
                raise RuntimeError("wars export_session returned empty bytes")
            logger.info("WhatsApp pair: exported %d bytes", len(blob))

            own_phone = None
            own_jid = None
            bot_username = None
            # wars doesn't yet expose a stable "get my JID" API on every
            # version, so we try a few common attributes and gracefully skip
            # if none are present.
            for attr in ("own_jid", "self_jid", "my_jid"):
                if hasattr(wa, attr):
                    try:
                        own_jid = getattr(wa, attr)
                        if callable(own_jid):
                            own_jid = own_jid()
                    except Exception:
                        own_jid = None
                    if own_jid:
                        break
            if own_jid:
                own_phone = jid_to_phone(str(own_jid))
            logger.info("WhatsApp pair: identified own_jid=%r own_phone=%r", own_jid, own_phone)

            ok = save_session_blob(
                blob=blob,
                own_jid=str(own_jid) if own_jid else None,
                own_phone=own_phone,
                bot_username=bot_username,
                owner_user_id=owner_user_id,
                owner_username=owner_username,
            )
            if not ok:
                raise RuntimeError("Persisting WhatsApp session blob failed")
            logger.info("WhatsApp pair: session blob encrypted and saved to openalgo.db")

            with self._lock:
                self._pair_state["status"] = "paired"
                self._pair_state["paired_at"] = datetime.utcnow().isoformat()
                self._is_paired = True

            # Emit BOTH events. whatsapp_paired carries the identity; the
            # status event re-broadcasts the full pair_state for any client
            # that missed the first one.
            self._emit("whatsapp_paired", {"own_phone": own_phone, "own_jid": str(own_jid) if own_jid else None})
            self._emit("whatsapp_pair_status", self.get_pair_state())
            logger.info("WhatsApp pair: emitted whatsapp_paired + whatsapp_pair_status")

            # Disconnect the temp-DB instance — the long-lived bot connects
            # from the encrypted blob via from_bytes() and lives separately.
            try:
                wa.disconnect()
                logger.info("WhatsApp pair: temp client disconnected")
            except Exception:
                logger.debug("WhatsApp pair: temp-DB disconnect raised", exc_info=True)

            self._cleanup_pair_temp()

            # Auto-start the live bot so the user is immediately ready to send.
            ok_start, msg = self.start_bot()
            logger.info("WhatsApp pair: auto-start bot ok=%s msg=%s", ok_start, msg)

        except Exception as e:
            logger.exception("WhatsApp pair finalize failed")
            with self._lock:
                self._pair_state["status"] = "failed"
                self._pair_state["error"] = str(e)
            self._emit("whatsapp_pair_status", self.get_pair_state())

    def _cleanup_pair_temp(self) -> None:
        path = self._pair_temp_db
        self._pair_temp_db = None
        self._pair_wa = None
        if path and os.path.exists(path):
            try:
                os.unlink(path)
            except OSError:
                logger.debug("Could not unlink pair temp DB: %s", path)

    # ------------------------------------------------------------------
    # Long-lived connection — uses the encrypted session blob.
    # ------------------------------------------------------------------

    def start_bot(self) -> tuple[bool, str]:
        with self._lock:
            if self._is_running and self._wa is not None:
                return True, "Bot already running"

            blob = load_session_blob()
            if not blob:
                return False, "Device not paired. Pair from /whatsapp first."

            try:
                _import_wars()  # presence check; worker thread imports again
            except WarsNotInstalled as e:
                return False, str(e)

            self._stop_event.clear()
            self._ready_event.clear()
            # Drain any stale commands from a prior session.
            while True:
                try:
                    self._cmd_queue.get_nowait()
                except queue.Empty:
                    break

            self._bot_thread = threading.Thread(
                target=self._bot_loop,
                args=(blob,),
                daemon=True,
                name="WhatsAppBotThread",
            )
            self._bot_thread.start()

        # Block (outside the lock) until the worker either succeeds or fails.
        if not self._ready_event.wait(timeout=15):
            return False, "Bot thread did not come up within 15s"
        if not self._is_running:
            return False, "Bot thread exited during startup — check server logs"
        return True, "Bot started"

    def _bot_loop(self, blob: bytes) -> None:
        """Long-lived worker. Owns `self._wa` for its entire lifetime so all
        PyO3 method calls on the wars instance happen on this thread."""
        wars = None
        try:
            wars = _import_wars()
            wa = wars.WhatsApp.from_bytes(blob)
            self._register_handlers(wa)
            try:
                wa.connect()
            except Exception:
                logger.exception("WhatsApp bot loop: wars.connect failed")
                self._ready_event.set()
                return

            self._wa = wa
            self._bot_thread_id = threading.get_ident()
            with self._lock:
                self._is_running = True
                self._is_paired = True
            update_bot_config({"is_active": True})
            self._emit("whatsapp_status", {"is_running": True, "is_paired": True})
            logger.info("WhatsApp bot thread up and connected")
            self._ready_event.set()

            # Command-pumping loop. Short polling interval keeps stop latency
            # low without busy-spinning when the channel is idle.
            while not self._stop_event.is_set():
                try:
                    cmd = self._cmd_queue.get(timeout=0.5)
                except queue.Empty:
                    continue
                op, args, kwargs, result_holder, event = cmd
                try:
                    if op == "send":
                        result_holder["result"] = self._send_on_bot_thread(*args, **kwargs)
                    else:
                        result_holder["error"] = f"unknown op: {op}"
                except Exception as e:
                    logger.exception("WhatsApp bot loop: op '%s' raised", op)
                    result_holder["error"] = str(e)
                finally:
                    event.set()

        except Exception:
            logger.exception("WhatsApp bot loop crashed during startup")
        finally:
            # Clean shutdown — must happen on this same thread to satisfy
            # PyO3's unsendable check.
            try:
                if self._wa is not None:
                    self._wa.disconnect()
            except Exception:
                logger.debug("WhatsApp bot disconnect raised", exc_info=True)
            self._wa = None
            self._bot_thread_id = None
            with self._lock:
                self._is_running = False
            try:
                update_bot_config({"is_active": False})
            except Exception:
                pass
            self._emit("whatsapp_status", {"is_running": False, "is_paired": self.is_paired})
            self._ready_event.set()  # unblock any waiter on a failed startup

    def stop_bot(self) -> tuple[bool, str]:
        with self._lock:
            if not self._is_running:
                return True, "Bot is not running"
            self._stop_event.set()
        thread = self._bot_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
            if thread.is_alive():
                logger.warning("WhatsApp bot thread did not exit within 10s")
        self._bot_thread = None
        logger.info("WhatsApp bot stopped")
        return True, "Bot stopped"

    def unlink(self) -> tuple[bool, str]:
        """Stop, then wipe the encrypted session blob. User must re-pair."""
        try:
            self.stop_bot()
        except Exception:
            pass
        ok = clear_session_blob()
        with self._lock:
            self._is_paired = False
        self._emit("whatsapp_status", {"is_running": False, "is_paired": False})
        return ok, "Device unlinked" if ok else "Failed to unlink"

    # ------------------------------------------------------------------
    # Outbound — single trader-facing entry point. Text, image, document,
    # self-send, single-recipient, and small broadcast (up to 5) all flow
    # through one function. Sync; non-blocking dispatch happens in the
    # alert_executor pool.
    # ------------------------------------------------------------------

    # Conservative cap. WhatsApp's automated-behavior thresholds tolerate
    # a handful of distinct contacts per batch but flag bulk patterns; 5 is
    # well inside the "normal usage" envelope. The cap also stops a typo
    # from blasting a recipient list into a ToS-grade broadcast.
    MAX_RECIPIENTS: int = 5

    def _ensure_running(self) -> bool:
        return self._is_running and self._wa is not None

    # Sentinel returned by _resolve_recipients for the "send to self" case.
    # We don't know the operator's own JID because wars 0.1.3 doesn't expose
    # it as a Python attribute. wars.send() with no recipient — the
    # README-documented single-arg form — internally routes to the paired
    # device's own number, so we substitute this marker and special-case
    # it in _send_on_bot_thread.
    _SELF_MARKER = "<self>"

    def _resolve_recipients(self, to: Any) -> list[str]:
        """Normalize `to` into a list of recipient strings.

        Accepted shapes:
            None / "" / [] -> [_SELF_MARKER] (single-arg wars.send → owner)
            "9198..."      -> single recipient (digits, +91..., JID, or group JID)
            ["a", "b", ...] -> list (capped at MAX_RECIPIENTS)
        """
        if to is None or (isinstance(to, str) and not to.strip()) or (
            isinstance(to, list) and not to
        ):
            return [self._SELF_MARKER]
        if isinstance(to, str):
            # An explicit own_jid passed in (e.g. captured lazily from a
            # prior is_from_me=True message) is fine — wars.send(jid, text)
            # accepts a JID directly. The self-marker path is only for
            # callers who explicitly asked for "send to owner".
            return [to]
        if isinstance(to, (list, tuple)):
            return [str(x) for x in to if x]
        return []

    def send_sync(
        self,
        to: Any = None,
        text: str | None = None,
        image: str | None = None,
        document: str | None = None,
        caption: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """Unified WhatsApp send. Thread-safe entry point — request threads
        enqueue and wait for the bot worker thread to actually call wars.send
        (PyO3 requires wars to be touched only from its creator thread).

        Recipients (`to`):
            None / "" / []          send to self (paired device's own number)
            "919876543210"          digits, +91..., or a full JID
            "120363...@g.us"        group JID
            ["a", "b", "c"]         broadcast (capped at MAX_RECIPIENTS=5)

        Returns a small report dict so callers can detect partial failures:
            {"sent": [<jid>, ...],
             "failed": [{"to": <jid>, "error": "<msg>"}, ...],
             "skipped": int}
        """
        if not self._is_running or self._wa is None:
            logger.warning("WhatsApp send: bot not running, dropping message")
            return {"sent": [], "failed": [{"to": "<bot>", "error": "Bot not connected"}], "skipped": 0}

        # Re-entrancy: a slash-command handler (running on the bot thread
        # itself via wars's on_message dispatch) can call send_sync without
        # deadlocking on its own command queue.
        if threading.get_ident() == self._bot_thread_id:
            return self._send_on_bot_thread(to, text, image, document, caption, filename)

        result_holder: dict[str, Any] = {}
        event = threading.Event()
        self._cmd_queue.put(
            (
                "send",
                (to, text, image, document, caption, filename),
                {},
                result_holder,
                event,
            )
        )
        if not event.wait(timeout=self.SEND_TIMEOUT):
            return {
                "sent": [],
                "failed": [{"to": "<bot>", "error": "send timeout"}],
                "skipped": 0,
            }
        if "error" in result_holder:
            return {
                "sent": [],
                "failed": [{"to": "<bot>", "error": result_holder["error"]}],
                "skipped": 0,
            }
        return result_holder.get(
            "result", {"sent": [], "failed": [], "skipped": 0}
        )

    def _send_on_bot_thread(
        self,
        to: Any = None,
        text: str | None = None,
        image: str | None = None,
        document: str | None = None,
        caption: str | None = None,
        filename: str | None = None,
    ) -> dict[str, Any]:
        """The real wars.send dispatcher. Must only run on `_bot_thread`."""
        report: dict[str, Any] = {"sent": [], "failed": [], "skipped": 0}

        recipients = self._resolve_recipients(to)
        if not recipients:
            report["failed"].append({"to": "<self>", "error": "No recipient resolved"})
            return report
        if len(recipients) > self.MAX_RECIPIENTS:
            report["skipped"] = len(recipients) - self.MAX_RECIPIENTS
            recipients = recipients[: self.MAX_RECIPIENTS]

        media_kwargs: dict[str, Any] = {}
        if image:
            media_kwargs["image"] = image
        if document:
            media_kwargs["document"] = document
        if filename and document:
            media_kwargs["filename"] = filename
        if image:
            cap = caption or text
            if cap:
                media_kwargs["caption"] = cap

        for jid in recipients:
            try:
                if jid == self._SELF_MARKER:
                    # Self-send. Per wars docs, `send("text")` (single-arg)
                    # routes to the paired device's own number without
                    # needing us to know the JID. Media-to-self isn't
                    # supported in wars 0.1 single-arg form, so we require
                    # an explicit JID for that case — captured lazily from
                    # incoming is_from_me messages and surfaced after the
                    # first round-trip.
                    if media_kwargs:
                        cfg_jid = get_bot_config().get("own_jid")
                        if not cfg_jid:
                            raise RuntimeError(
                                "Self-send with media needs the owner JID. "
                                "Send any /command from your phone first so "
                                "we can capture it, then retry."
                            )
                        self._wa.send(cfg_jid, **media_kwargs)
                        if document and (text or caption):
                            self._wa.send(cfg_jid, text or caption)
                    else:
                        self._wa.send(text or "")  # single-arg → owner
                elif media_kwargs:
                    self._wa.send(jid, **media_kwargs)
                    if document and (text or caption):
                        self._wa.send(jid, text or caption)
                else:
                    self._wa.send(jid, text or "")
                report["sent"].append(jid)
            except Exception as e:
                logger.exception("WhatsApp send to %s failed", jid)
                report["failed"].append({"to": jid, "error": str(e)})

        return report

    # ------------------------------------------------------------------
    # Inbound command dispatch.
    # ------------------------------------------------------------------

    def _register_handlers(self, wa) -> None:
        @wa.on_message
        def _handle(msg) -> None:
            try:
                is_from_me = bool(getattr(msg, "is_from_me", False))

                # Lazy own-JID capture. wars 0.1.3 doesn't expose the paired
                # device's own JID as an attribute, so we sniff it from the
                # first is_from_me=True message we observe. The "sender" on
                # those events IS the operator's primary JID. Store once,
                # ignore re-captures.
                if is_from_me:
                    sender = getattr(msg, "sender", "") or getattr(msg, "chat", "") or ""
                    self._maybe_capture_own_jid(sender)

                text = (getattr(msg, "text", None) or "").strip()
                if not text or not text.startswith("/"):
                    return
                # Single-user OpenAlgo: the only identity allowed to drive
                # the bot is the operator's primary device. WhatsApp's
                # multi-device protocol marks messages from the paired
                # account itself (i.e., the operator typing on their phone
                # and the message being mirrored to this linked client) as
                # is_from_me=True. Anyone else who messages the operator's
                # WhatsApp number arrives as is_from_me=False — those are
                # silently ignored so a random contact cannot run /closeall.
                if not is_from_me:
                    logger.debug("WhatsApp command from non-owner ignored")
                    return
                self._dispatch_command(wa, msg, text)
            except Exception:
                logger.exception("WhatsApp message handler crashed")

    def _maybe_capture_own_jid(self, sender_jid: str) -> None:
        """Persist sender_jid as the device's own JID + own_phone if we
        don't have one yet. Idempotent — once set we never overwrite."""
        if not sender_jid or "@s.whatsapp.net" not in sender_jid:
            return
        cfg = get_bot_config()
        if cfg.get("own_jid"):
            return
        from database.whatsapp_db import save_session_blob  # local to avoid cycle
        # We don't want to re-encrypt the blob — there's no API for
        # "update identity only". Cheapest path: a tiny dedicated DB helper.
        from database.whatsapp_db import _persist_owner_identity  # noqa: E501

        try:
            _persist_owner_identity(sender_jid, jid_to_phone(sender_jid))
            self._emit(
                "whatsapp_status",
                {"is_running": self._is_running, "is_paired": self.is_paired},
            )
            logger.info("WhatsApp: captured own_jid=%s lazily", sender_jid)
        except Exception:
            logger.exception("Failed to persist own_jid")

        @wa.on_disconnect
        def _on_disconnect() -> None:
            logger.warning("WhatsApp wars on_disconnect fired")
            with self._lock:
                self._is_running = False
            self._emit(
                "whatsapp_status", {"is_running": False, "is_paired": self.is_paired}
            )

    def _dispatch_command(self, wa, msg, text: str) -> None:
        """Parse `/cmd arg1 arg2 ...` and route to the matching handler.
        Caller has already authenticated this as a message from the
        single-user operator (is_from_me=True)."""
        chat = getattr(msg, "chat", "")
        sender_jid = getattr(msg, "sender", chat)
        parts = text.split()
        cmd = parts[0].lower().lstrip("/")
        args = parts[1:]

        handlers: dict[str, Callable[..., None]] = {
            "start": self._cmd_help,
            "help": self._cmd_help,
            "menu": self._cmd_help,
            "status": self._cmd_status,
            "orderbook": self._cmd_orderbook,
            "tradebook": self._cmd_tradebook,
            "positions": self._cmd_positions,
            "holdings": self._cmd_holdings,
            "funds": self._cmd_funds,
            "pnl": self._cmd_pnl,
            "quote": self._cmd_quote,
            "closeall": self._cmd_closeall,
            "mode": self._cmd_mode,
        }
        handler = handlers.get(cmd)
        if not handler:
            self.send_sync(chat, "Unknown command. Send /help for the list.")
            return
        log_command(sender_jid, cmd, {"args": args})
        try:
            handler(wa, msg, chat, sender_jid, args)
        except Exception:
            logger.exception("WhatsApp command handler raised: %s", cmd)
            self.send_sync(chat, "An error occurred handling that command.")

    # ----- command handlers -----

    def _cmd_help(self, wa, msg, chat, sender_jid, args) -> None:
        self.send_sync(
            chat,
            "OpenAlgo WhatsApp Bot\n"
            "/status - connection + paired status\n"
            "/orderbook - today's orders\n"
            "/tradebook - today's trades\n"
            "/positions - open positions\n"
            "/holdings - holdings\n"
            "/funds - account funds\n"
            "/pnl - net P&L\n"
            "/quote <symbol> [exchange] - last traded price\n"
            "/closeall - square off all positions\n"
            "/mode - live or analyze mode",
        )

    def _cmd_status(self, wa, msg, chat, sender_jid, args) -> None:
        cfg = get_bot_config()
        lines = [
            f"Bot connected: {'yes' if cfg.get('is_active') else 'no'}",
            f"Device paired: {'yes' if cfg.get('is_paired') else 'no'}",
        ]
        if cfg.get("own_phone"):
            lines.append(f"Paired number: +{cfg['own_phone']}")
        if cfg.get("owner_username"):
            lines.append(f"Owner: {cfg['owner_username']}")
        self.send_sync(chat, "\n".join(lines))

    # SDK helpers. Single-user OpenAlgo — the operator who paired the device
    # is the only identity that can issue commands. We look up their api_key
    # from auth_db using the owner_user_id captured at pair time, so the
    # operator never has to /link or paste credentials from the phone.

    def _sdk_client_for_owner(self):
        cfg = get_bot_config()
        # The `api_keys` table's `user_id` column is keyed by **username**
        # (not the numeric users.id) — verified via PRAGMA on the live DB.
        # We must filter by owner_username, not owner_user_id, or the lookup
        # silently returns None and the command prints "No API key on file"
        # even when one clearly exists.
        owner_username = cfg.get("owner_username")
        if not owner_username:
            return None, (
                "No owner recorded for this paired device. Re-pair from the "
                "/whatsapp page while logged in to OpenAlgo."
            )
        try:
            from database.auth_db import get_api_key_for_tradingview
            api_key = get_api_key_for_tradingview(owner_username)
        except Exception:
            logger.exception("Failed to load owner api_key from auth_db")
            return None, "Could not load OpenAlgo API key for the owner."
        if not api_key:
            return None, (
                "No API key on file for the owner. Generate one at /apikey "
                "on the web UI, then try again."
            )
        host_url = os.getenv("HOST_SERVER", "http://127.0.0.1:5000")
        try:
            from openalgo import api as openalgo_api  # type: ignore
        except Exception:
            return None, "openalgo SDK not available on this server."
        try:
            return openalgo_api(api_key=api_key, host=host_url), None
        except Exception as e:
            logger.exception("Failed to create openalgo client")
            return None, f"SDK error: {e}"

    def _sdk_client(self, sender_jid: str):
        # Backward-compatible alias kept for the existing command handlers
        # below; ignores sender_jid (single-user gate is enforced upstream
        # in _register_handlers via is_from_me=True).
        return self._sdk_client_for_owner()

    def _cmd_orderbook(self, wa, msg, chat, sender_jid, args) -> None:
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            resp = client.orderbook()
            self._send_truncated(chat, "Orderbook", resp)
        except Exception as e:
            self.send_sync(chat, f"Failed to fetch orderbook: {e}")

    def _cmd_tradebook(self, wa, msg, chat, sender_jid, args) -> None:
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            resp = client.tradebook()
            self._send_truncated(chat, "Tradebook", resp)
        except Exception as e:
            self.send_sync(chat, f"Failed to fetch tradebook: {e}")

    def _cmd_positions(self, wa, msg, chat, sender_jid, args) -> None:
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            resp = client.positionbook()
            self._send_truncated(chat, "Positions", resp)
        except Exception as e:
            self.send_sync(chat, f"Failed to fetch positions: {e}")

    def _cmd_holdings(self, wa, msg, chat, sender_jid, args) -> None:
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            resp = client.holdings()
            self._send_truncated(chat, "Holdings", resp)
        except Exception as e:
            self.send_sync(chat, f"Failed to fetch holdings: {e}")

    def _cmd_funds(self, wa, msg, chat, sender_jid, args) -> None:
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            resp = client.funds()
            self._send_truncated(chat, "Funds", resp)
        except Exception as e:
            self.send_sync(chat, f"Failed to fetch funds: {e}")

    def _cmd_pnl(self, wa, msg, chat, sender_jid, args) -> None:
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            # The SDK exposes a per-symbol P&L via the pnl namespace; fall
            # back to positionbook aggregate if it's not present.
            if hasattr(client, "pnl"):
                resp = client.pnl()
            else:
                resp = client.positionbook()
            self._send_truncated(chat, "P&L", resp)
        except Exception as e:
            self.send_sync(chat, f"Failed to fetch P&L: {e}")

    def _cmd_quote(self, wa, msg, chat, sender_jid, args) -> None:
        if not args:
            self.send_sync(chat, "Usage: /quote <symbol> [exchange]")
            return
        symbol = args[0].upper()
        exchange = args[1].upper() if len(args) > 1 else "NSE"
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            resp = client.quotes(symbol=symbol, exchange=exchange)
            self._send_truncated(chat, f"Quote {symbol} {exchange}", resp)
        except Exception as e:
            self.send_sync(chat, f"Failed to fetch quote: {e}")

    def _cmd_closeall(self, wa, msg, chat, sender_jid, args) -> None:
        client, err = self._sdk_client(sender_jid)
        if err:
            self.send_sync(chat, err)
            return
        try:
            resp = client.closeposition()
            self.send_sync(chat, f"Close-all response:\n{self._format_dict(resp)}")
        except Exception as e:
            self.send_sync(chat, f"Close-all failed: {e}")

    def _cmd_mode(self, wa, msg, chat, sender_jid, args) -> None:
        try:
            from database.settings_db import get_analyze_mode

            mode = "analyze" if get_analyze_mode() else "live"
        except Exception:
            mode = "unknown"
        self.send_sync(chat, f"Trading mode: {mode}")

    # ----- formatting helpers -----

    def _format_dict(self, value: Any, depth: int = 0) -> str:
        if isinstance(value, dict):
            return "\n".join(f"{k}: {self._format_dict(v, depth + 1)}" for k, v in value.items())
        if isinstance(value, list):
            if not value:
                return "(empty)"
            return "\n".join(f"- {self._format_dict(v, depth + 1)}" for v in value[:10])
        return str(value)

    def _send_truncated(self, chat: str, title: str, payload: Any) -> None:
        body = self._format_dict(payload)
        if len(body) > 3500:
            body = body[:3500] + "\n...(truncated)"
        self.send_sync(chat, f"*{title}*\n{body}")

    # ------------------------------------------------------------------
    # SocketIO push helper — used by pair flow and status updates.
    # ------------------------------------------------------------------

    def _emit(self, event: str, payload: Any) -> None:
        try:
            from extensions import socketio

            socketio.emit(event, payload)
        except Exception:
            # Don't let a missing SocketIO context break the bot. The REST
            # /pair/status endpoint serves the same data via polling.
            logger.debug("SocketIO emit failed for %s", event, exc_info=True)


whatsapp_bot_service = WhatsAppBotService()
