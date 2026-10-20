"""Sustained soak of Shoonya's market data, over REST and over the WebSocket feed.

Shoonya intermittently answers a valid GetQuotes request with a snapshot of a
*different* instrument on the same login. The reply is complete and carries
stat=Ok, so the only way to spot it is to compare the echoed exch/token against
what was asked for. In OpenAlgo this surfaces as a sandbox fill priced at the
NIFTY spot instead of the option price.

The proposed fix is to stop sourcing prices from REST GetQuotes and read them
from the WebSocket touchline feed instead, on the argument that the feed is
subscription-keyed and every tick names its own instrument. That argument is
structural, not measured. This script measures it: run both transports over the
same window, on the same session, against the same instruments, and compare.

  REST check  every reply's echoed exch/token must equal what was asked for
  WS check    every tick's token must belong to a scrip we subscribed to, and
              where the tick carries an exchange it must be that scrip's

Both talk to Shoonya directly, bypassing OpenAlgo's broker and streaming layers,
so what is recorded is the broker's behaviour and nothing else. Read-only: it
issues nothing but quote requests and touchline subscriptions.

Two files are written under log/, both timestamped so consecutive runs never
clobber each other's evidence:

  <out>.log    human-readable, session key and client id redacted, safe to
               attach to a broker support ticket or a GitHub issue
  <out>.jsonl  one record per request and per anomalous tick, for analysis

Deliberately named without the `test_` prefix: pytest's testpaths includes
test/, and an hour-long live-API run has no business being collected by
`uv run pytest test/`.

Usage:
    uv run python test/shoonya_getquotes_soak.py                     # 60 min, both
    uv run python test/shoonya_getquotes_soak.py --minutes 5
    uv run python test/shoonya_getquotes_soak.py --transport rest
    uv run python test/shoonya_getquotes_soak.py --transport ws
    uv run python test/shoonya_getquotes_soak.py --symbols NIFTY30DEC2526000CE:NFO,NIFTY:NSE_INDEX

Requires a live Shoonya session in the OpenAlgo database (log in through the
app first). Ctrl+C at any point writes the summary for what was captured.
"""

import argparse
import json
import os
import signal
import sqlite3
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

import httpx
import websocket
from dotenv import load_dotenv

# Run from the repo root regardless of where the script is invoked from: the
# database path, .env and the OpenAlgo imports below are all root-relative.
ROOT = Path(__file__).resolve().parent.parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / ".env")

from database.auth_db import decrypt_token  # noqa: E402

REST_URL = "https://api.shoonya.com/NorenWClientAPI/GetQuotes"
WS_URL = "wss://api.shoonya.com/NorenWSAPI/"

# Noren WebSocket message types. `t` on an outbound message is the command; on
# an inbound message it identifies the payload.
WS_CONNECT = "a"
WS_HEARTBEAT = "h"
WS_HEARTBEAT_ACK = "hk"  # what Noren answers a heartbeat with
WS_AUTH_ACK = "ak"
WS_TOUCHLINE_SUB = "t"
WS_TOUCHLINE_ACK = "tk"  # full snapshot, sent once per scrip on subscribe
WS_TOUCHLINE_UPDATE = "tf"  # incremental update, may omit the exchange field

WS_HEARTBEAT_INTERVAL = 30
# How often the feed monitor reports liveness. A silent socket has to be
# visible while the run is going, not only in the summary an hour later.
WS_STATUS_INTERVAL = 30

# Shoonya has no separate index exchange - indices live on the cash exchange
# under their own token range.
INDEX_EXCHANGE = {"NSE_INDEX": "NSE", "BSE_INDEX": "BSE", "MCX_INDEX": "MCX"}

# No contract names are fixed here. A hardcoded default silently soaks an
# expired symbol once the week rolls over - which happened twice while this was
# being written, producing runs that looked fine and measured nothing. The
# targets are discovered from the master contract and the live index instead.
DEFAULT_UNDERLYING = "NIFTY"
DEFAULT_OPTION_EXCHANGE = "NFO"


def fetch_quote(auth_token, uid, exch, token):
    """One raw GetQuotes call, outside the broker module.

    The soak deliberately does not import broker.shoonya.api.data: it measures
    what Shoonya sends, and going through the guarded path there would measure
    the guard instead.
    """
    body = "jData=" + json.dumps({"uid": uid, "exch": exch, "token": str(token)})
    headers = {
        "Content-Type": "text/plain",
        "Authorization": f"Bearer {auth_token}",
    }
    with httpx.Client(timeout=15.0) as client:
        return client.post(REST_URL, content=body, headers=headers).json()


def discover_symbols(auth_token, uid, underlying, exchange):
    """The nearest-expiry ATM call and put for an underlying, as (symbol, exchange).

    ATM because those are the contracts that actually trade, so a quiet strike
    cannot make a run look clean by never producing a price to check.

    The index level used to locate the strikes is read straight from GetQuotes
    and verified against the token that was asked for, so a leaked reply cannot
    quietly send the discovery to the wrong strikes.
    """
    from database.symbol import SymToken, db_session
    from database.token_db import get_token

    index_token = get_token(underlying, "NSE_INDEX")
    if not index_token:
        sys.exit(f"no token in the symbol master for {underlying}@NSE_INDEX")

    reply = fetch_quote(auth_token, uid, "NSE", str(index_token))
    if reply.get("stat") != "Ok":
        sys.exit(f"could not read {underlying} spot: {reply.get('emsg')}")
    if str(reply.get("token", "")) != str(index_token):
        sys.exit(
            f"discovery asked for NSE|{index_token} and got "
            f"{reply.get('exch')}|{reply.get('token')} - re-run"
        )
    spot = float(reply["lp"])

    today = datetime.now().date()
    rows = (
        db_session.query(SymToken.symbol, SymToken.expiry, SymToken.strike, SymToken.instrumenttype)
        .filter(
            SymToken.exchange == exchange,
            SymToken.name == underlying,
            SymToken.instrumenttype.in_(("CE", "PE")),
        )
        .all()
    )

    def as_date(value):
        try:
            return datetime.strptime(value, "%d-%b-%y").date()
        except (TypeError, ValueError):
            return None

    live = [(as_date(e), sym, strike, kind) for sym, e, strike, kind in rows]
    live = [r for r in live if r[0] and r[0] >= today]
    if not live:
        sys.exit(f"every {underlying} contract on {exchange} has expired")

    nearest = min(r[0] for r in live)
    front = [r for r in live if r[0] == nearest]

    picked = []
    for kind in ("CE", "PE"):
        leg = [r for r in front if r[3] == kind]
        if leg:
            picked.append((min(leg, key=lambda r: abs(r[2] - spot))[1], exchange))
    if not picked:
        sys.exit(f"could not resolve an ATM pair for {underlying} {nearest}")

    print(
        f"discovered {underlying} spot {spot}, expiry {nearest}: "
        f"{', '.join(sym for sym, _ in picked)}"
    )
    return picked


stop = threading.Event()


def _handle_sigint(signum, frame):
    """Stop every loop cleanly so the summary still gets written."""
    stop.set()


def _as_float(value):
    """Noren sends every number as a string, and omits fields rather than
    sending a null. Anything that will not parse is treated as absent."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class Recorder:
    """Shared, thread-safe sink for both transports.

    REST runs on the main thread and the WebSocket on its own, so a single run
    has two writers. Holding one lock over both files keeps a mismatch block
    from being interleaved with a tick line halfway through.
    """

    def __init__(self, log, jsonl, redact):
        self._log = log
        self._jsonl = jsonl
        self._lock = threading.Lock()
        self.redact = redact

    def emit(self, line=""):
        with self._lock:
            self._log.write(line + "\n")

    def emit_block(self, lines):
        with self._lock:
            for line in lines:
                self._log.write(line + "\n")

    def record(self, obj):
        with self._lock:
            self._jsonl.write(json.dumps(obj) + "\n")


def load_session():
    """Return (auth_token, uid) for the logged-in Shoonya session."""
    db = ROOT / "db" / "openalgo.db"
    if not db.exists():
        sys.exit(f"database not found at {db} - is this the OpenAlgo root?")

    with sqlite3.connect(db) as conn:
        row = conn.execute("select auth, broker from auth where id = 1").fetchone()
    if not row:
        sys.exit("no session in the auth table - log in through OpenAlgo first")

    encrypted, broker = row
    if broker != "shoonya":
        sys.exit(f"logged-in broker is '{broker}', not shoonya")

    full_api_key = os.getenv("BROKER_API_KEY", "")
    if ":::" not in full_api_key:
        sys.exit("BROKER_API_KEY is missing or malformed in .env")

    return decrypt_token(encrypted), full_api_key.split(":::")[0]


def resolve(symbols):
    """Turn (symbol, exchange) pairs into the (label, exch, token, br_symbol) the APIs want."""
    from database.token_db import get_br_symbol, get_token

    targets = []
    for symbol, exchange in symbols:
        token = get_token(symbol, exchange)
        if not token:
            sys.exit(f"no token in the symbol master for {symbol}@{exchange}")
        targets.append(
            (
                f"{symbol}@{exchange}",
                INDEX_EXCHANGE.get(exchange, exchange),
                str(token),
                get_br_symbol(symbol, exchange),
            )
        )
    return targets


def parse_symbols(raw):
    pairs = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            sys.exit(f"expected SYMBOL:EXCHANGE, got '{chunk}'")
        symbol, exchange = chunk.split(":", 1)
        pairs.append((symbol.strip(), exchange.strip()))
    return pairs


def run_rest_soak(rec, targets, auth_token, uid, rate, deadline, stats, verbose):
    """Poll GetQuotes in a strict round-robin, checking the echoed instrument.

    A matching reply is counted and written to the .jsonl but stays out of
    the .log unless asked for. At 2 req/sec against a live touchline feed the
    routine lines bury the mismatch blocks, which are the only thing in here
    that needs reading. Nothing is lost: the .jsonl still holds every request.
    """
    headers = {"Content-Type": "text/plain", "Authorization": f"Bearer {auth_token}"}
    interval = 1.0 / rate
    our_tokens = {t[2] for t in targets}
    i = 0

    with httpx.Client(timeout=15.0) as client:
        while not stop.is_set() and time.monotonic() < deadline:
            label, exch, token, br_symbol = targets[i % len(targets)]
            i += 1
            stats["total"] += 1
            stats["requested"][label] += 1
            n = stats["total"]

            body = "jData=" + json.dumps({"uid": uid, "exch": exch, "token": token})
            ts = datetime.now()
            t0 = time.monotonic()
            try:
                response = client.post(REST_URL, content=body, headers=headers)
                raw = response.text
                parsed = response.json()
            except Exception as e:
                stats["errors"] += 1
                rec.emit(f"[{ts:%H:%M:%S}] REST #{n:05d} TRANSPORT ERROR {exch}|{token}: {e}")
                rec.record(
                    {
                        "transport": "rest",
                        "n": n,
                        "ts": ts.isoformat(),
                        "asked": f"{exch}|{token}",
                        "outcome": "transport_error",
                        "error": str(e),
                    }
                )
                stop.wait(interval)
                continue

            elapsed_ms = round((time.monotonic() - t0) * 1000)
            stats["latencies"].append(elapsed_ms)

            record = {
                "transport": "rest",
                "n": n,
                "ts": ts.isoformat(),
                "label": label,
                "asked": f"{exch}|{token}",
                "ms": elapsed_ms,
                "stat": parsed.get("stat"),
                "got": f"{parsed.get('exch', '')}|{parsed.get('token', '')}",
                "tsym": parsed.get("tsym"),
                "lp": parsed.get("lp"),
                "request_time": parsed.get("request_time"),
            }

            if parsed.get("stat") != "Ok":
                stats["notok"] += 1
                record["outcome"] = "not_ok"
                record["emsg"] = parsed.get("emsg")
                rec.emit(
                    f"[{ts:%H:%M:%S}] REST #{n:05d} NOT-OK   {exch}|{token} "
                    f"-> {rec.redact(raw)[:200]}"
                )
                rec.record(record)
                stop.wait(interval)
                continue

            got_exch = str(parsed.get("exch", "") or "")
            got_token = str(parsed.get("token", "") or "")

            if got_exch == exch and got_token == token:
                record["outcome"] = "match"
                if verbose:
                    rec.emit(
                        f"[{ts:%H:%M:%S}] REST #{n:05d} ok       {exch}|{token} {label} "
                        f"lp={parsed.get('lp')} {elapsed_ms}ms"
                    )
            else:
                stats["mismatched"][label] += 1
                stats["leaked_as"][f"{got_exch}|{got_token} {parsed.get('tsym')}"] += 1
                record["outcome"] = "wrong_instrument"
                record["from_our_cycle"] = got_token in our_tokens
                record["raw"] = rec.redact(raw)
                rec.emit_block(
                    [
                        "",
                        f"[{ts:%H:%M:%S}] REST #{n:05d} *** WRONG INSTRUMENT RETURNED ***",
                        f"    asked for : {exch}|{token}  ({label}, {br_symbol})",
                        f"    got back  : {got_exch}|{got_token}  {parsed.get('tsym')}  "
                        f"lp={parsed.get('lp')}",
                        f"    in our request cycle: {got_token in our_tokens}",
                        f"    latency   : {elapsed_ms}ms",
                        f"    REQUEST   : {rec.redact(body)}",
                        "    HEADERS   : Content-Type: text/plain, "
                        "Authorization: Bearer <SESSION_KEY_REDACTED>",
                        f"    RESPONSE  : {rec.redact(raw)}",
                        "",
                    ]
                )

            rec.record(record)
            stop.wait(interval)


def run_ws_soak(rec, targets, auth_token, uid, deadline, stats, verbose_ticks):
    """Subscribe to the touchline feed and capture every frame that crosses it.

    The REST failure has no direct analogue here - there is no request to echo
    back - so the equivalent question is whether the stream ever delivers a
    scrip that was never subscribed. The adapter already has to cope with feed
    messages that omit the exchange (shoonya_adapter.py, _token_to_scrips), so
    a tick is matched on token first and on exchange only when one is present.

    Capture matches the REST side. Every frame, sent or received, gets a
    numbered line in the .log and a full redacted record in the .jsonl, the
    same way every GetQuotes request does. The first live run logged only
    anomalies, and because the feed delivered nothing at all there was no way
    afterwards to tell a silent socket from a healthy one that simply never
    misbehaved. A quiet socket is not a correct one, and the log has to be able
    to tell the two apart.
    """
    subscribed = {
        f"{exch}|{token}": (label, br_symbol) for label, exch, token, br_symbol in targets
    }
    token_to_scrip = {token: f"{exch}|{token}" for _, exch, token, _ in targets}
    scrip_list = "#".join(subscribed)

    # What the feed itself says each scrip is, pinned from the snapshot it
    # sends on subscribe. A tf update carries only e/tk/lp, so the snapshot is
    # the only place the feed ever states the symbol name or the circuit band
    # a price has to fall inside. Without it there is nothing on an update to
    # check a price against.
    pinned = {}

    state = {
        "authed": False,
        "connects": 0,
        "rx": 0,
        "tx": 0,
        "last_tick": None,
        "reported": 0,
    }

    def sent(kind, frame):
        """Log an outbound frame the way the REST side logs its request."""
        state["tx"] += 1
        stats["ws_sent"] += 1
        ts = datetime.now()
        body = rec.redact(json.dumps(frame))
        rec.emit(f"[{ts:%H:%M:%S}] WS   SENT #{state['tx']:05d} {kind}: {body}")
        rec.record(
            {
                "transport": "ws",
                "dir": "sent",
                "n": state["tx"],
                "ts": ts.isoformat(),
                "kind": kind,
                "frame": body,
            }
        )

    def received(n, ts, msg_type, outcome, raw, **extra):
        stats["ws_received"] += 1
        rec.record(
            {
                "transport": "ws",
                "dir": "recv",
                "n": n,
                "ts": ts.isoformat(),
                "t": msg_type,
                "outcome": outcome,
                "raw": raw,
                **extra,
            }
        )

    def on_open(ws):
        state["connects"] += 1
        state["authed"] = False
        ts = datetime.now()
        if state["connects"] > 1:
            stats["ws_reconnects"] += 1
            rec.emit(f"[{ts:%H:%M:%S}] WS   reconnected (#{state['connects']})")
        else:
            rec.emit(f"[{ts:%H:%M:%S}] WS   socket open to {WS_URL}")
        frame = {
            "t": WS_CONNECT,
            "uid": uid,
            "actid": uid,
            "source": "API",
            "accesstoken": auth_token,
        }
        ws.send(json.dumps(frame))
        sent("connect", frame)

    def on_message(ws, message):
        ts = datetime.now()
        state["rx"] += 1
        n = state["rx"]
        raw = rec.redact(message)

        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            rec.emit(f"[{ts:%H:%M:%S}] WS   #{n:05d} UNPARSEABLE: {raw}")
            received(n, ts, None, "unparseable", raw)
            return

        msg_type = data.get("t")

        if msg_type == WS_AUTH_ACK:
            if data.get("s") != "OK":
                rec.emit(f"[{ts:%H:%M:%S}] WS   #{n:05d} AUTH FAILED: {raw}")
                received(n, ts, msg_type, "auth_failed", raw)
                stop.set()
                return
            state["authed"] = True
            rec.emit(f"[{ts:%H:%M:%S}] WS   #{n:05d} AUTH OK: {raw}")
            received(n, ts, msg_type, "auth_ok", raw)
            frame = {"t": WS_TOUCHLINE_SUB, "k": scrip_list}
            ws.send(json.dumps(frame))
            sent("touchline subscribe", frame)
            return

        if msg_type in (WS_HEARTBEAT, WS_HEARTBEAT_ACK):
            # Noren answers {"t":"h"} with {"t":"hk"}. Worth a line of its own:
            # during a dead feed it is the only evidence the socket is still up.
            rec.emit(f"[{ts:%H:%M:%S}] WS   #{n:05d} heartbeat ack: {raw}")
            received(n, ts, msg_type, "heartbeat_ack", raw)
            return

        if msg_type not in (WS_TOUCHLINE_ACK, WS_TOUCHLINE_UPDATE):
            rec.emit(f"[{ts:%H:%M:%S}] WS   #{n:05d} other msg t={msg_type}: {raw}")
            received(n, ts, msg_type, "other", raw)
            return

        stats["ws_ticks"] += 1
        state["last_tick"] = time.monotonic()
        if stats["ws_first_tick"] is None:
            stats["ws_first_tick"] = ts

        got_token = str(data.get("tk", "") or "")
        got_exch = str(data.get("e", "") or "")

        if not got_token:
            stats["ws_untokened"] += 1
            rec.emit(f"[{ts:%H:%M:%S}] WS   #{n:05d} TICK WITH NO TOKEN: {raw}")
            received(n, ts, msg_type, "tick_without_token", raw)
            return

        known_scrip = token_to_scrip.get(got_token)

        if known_scrip is None:
            # A token we never subscribed to. This is the WebSocket analogue of
            # the REST leak: data for an instrument this client never asked for.
            stats["ws_unsolicited"] += 1
            stats["ws_unsolicited_as"][f"{got_exch}|{got_token} {data.get('ts')}"] += 1
            rec.emit_block(
                [
                    "",
                    f"[{ts:%H:%M:%S}] WS   #{n:05d} *** UNSOLICITED SCRIP ON THE FEED ***",
                    f"    subscribed to : {scrip_list}",
                    f"    received      : {got_exch}|{got_token}  {data.get('ts')}  "
                    f"lp={data.get('lp')}",
                    f"    RAW           : {raw}",
                    "",
                ]
            )
            received(
                n,
                ts,
                msg_type,
                "unsolicited_scrip",
                raw,
                got=f"{got_exch}|{got_token}",
                tsym=data.get("ts"),
                lp=data.get("lp"),
            )
            return

        if got_exch and known_scrip != f"{got_exch}|{got_token}":
            # Right token, wrong exchange - the token namespace is per exchange,
            # so this would route the price onto the wrong instrument.
            stats["ws_exchange_mismatch"] += 1
            rec.emit_block(
                [
                    "",
                    f"[{ts:%H:%M:%S}] WS   #{n:05d} *** EXCHANGE MISMATCH ON A KNOWN TOKEN ***",
                    f"    subscribed as : {known_scrip}",
                    f"    tick says     : {got_exch}|{got_token}  {data.get('ts')}",
                    f"    RAW           : {raw}",
                    "",
                ]
            )
            received(
                n,
                ts,
                msg_type,
                "exchange_mismatch",
                raw,
                subscribed=known_scrip,
                got=f"{got_exch}|{got_token}",
            )
            return

        label, expected_symbol = subscribed[known_scrip]
        stats["ws_per_scrip"][label] += 1
        lp = _as_float(data.get("lp"))
        if data.get("lp") is not None:
            stats["ws_last_lp"][label] = data.get("lp")
            stats["ws_priced"][label] += 1

        # A band can be revised intraday, so take a new one whenever the feed
        # publishes it rather than trusting the first snapshot forever.
        ref = pinned.setdefault(got_token, {"tsym": None, "lc": None, "uc": None})
        for field in ("lc", "uc"):
            if data.get(field) is not None:
                ref[field] = _as_float(data.get(field))
        if ref["lc"] is not None and ref["uc"] is not None:
            stats["ws_banded"][label] = 1

        if msg_type == WS_TOUCHLINE_ACK:
            # One per scrip on subscribe, and the only full snapshot the feed
            # ever sends. Captured whole, the way a REST reply is captured.
            got_tsym = str(data.get("ts", "") or "")
            rec.emit_block(
                [
                    "",
                    f"[{ts:%H:%M:%S}] WS   #{n:05d} SNAPSHOT {known_scrip} {label}",
                    f"    RAW       : {raw}",
                    "",
                ]
            )
            if got_tsym and ref["tsym"] is None:
                # First sight of this token. Pin the feed's own name for it and
                # compare later payloads against that, not against the symbol
                # master: the two use different conventions for the same
                # instrument - the feed calls token 26000 "Nifty 50" where the
                # master calls it "NIFTY INDEX" - and flagging that would put a
                # false positive in the one record that has to stay clean.
                ref["tsym"] = got_tsym
                if got_tsym != expected_symbol:
                    rec.emit(
                        f"[{ts:%H:%M:%S}] WS   note: feed calls {known_scrip} "
                        f"'{got_tsym}', symbol master calls it '{expected_symbol}' - "
                        "naming convention, not a mismatch; identity is pinned to the "
                        "feed's name from here"
                    )
            elif got_tsym and got_tsym != ref["tsym"]:
                # The feed has changed its mind about what this token is. That
                # is the same shape as the REST leak - one identifier answered
                # for two instruments - and the adapter routes on token alone,
                # so nothing downstream would ever notice.
                stats["ws_wrong_symbol"] += 1
                stats["ws_wrong_as"][f"{got_exch}|{got_token} {got_tsym}"] += 1
                rec.emit_block(
                    [
                        "",
                        f"[{ts:%H:%M:%S}] WS   #{n:05d} *** WRONG INSTRUMENT ON THE FEED ***",
                        f"    subscribed to : {known_scrip}  ({label}, {expected_symbol})",
                        f"    feed called it: {ref['tsym']}",
                        f"    feed now says : {got_exch}|{got_token}  {got_tsym}  "
                        f"lp={data.get('lp')}",
                        "    the token is unchanged but the name is not - one of these "
                        "two payloads describes a different instrument",
                        f"    RAW           : {raw}",
                        "",
                    ]
                )
                received(
                    n,
                    ts,
                    msg_type,
                    "wrong_symbol",
                    raw,
                    scrip=known_scrip,
                    label=label,
                    expected_tsym=expected_symbol,
                    pinned_tsym=ref["tsym"],
                    tsym=got_tsym,
                    lp=data.get("lp"),
                )
                return
        elif (
            lp is not None
            and ref["lc"] is not None
            and ref["uc"] is not None
            and not (ref["lc"] <= lp <= ref["uc"])
        ):
            # The WebSocket has no request to echo, so a wrong instrument can
            # only show up as a price that cannot belong to this one. The band
            # is the exchange's own circuit limit, published by the feed in the
            # snapshot - the option that started all this traded 14.95-25.70
            # while being served 24307.30, decades outside its band.
            stats["ws_out_of_band"] += 1
            stats["ws_wrong_as"][f"{known_scrip} lp={lp} outside {ref['lc']}-{ref['uc']}"] += 1
            rec.emit_block(
                [
                    "",
                    f"[{ts:%H:%M:%S}] WS   #{n:05d} *** PRICE CANNOT BELONG TO THIS INSTRUMENT ***",
                    f"    scrip         : {known_scrip}  ({label}, {ref['tsym'] or expected_symbol})",
                    f"    lp            : {lp}",
                    f"    circuit band  : {ref['lc']} - {ref['uc']}  "
                    "(from this scrip's own snapshot)",
                    f"    RAW           : {raw}",
                    "",
                ]
            )
            received(
                n,
                ts,
                msg_type,
                "price_out_of_band",
                raw,
                scrip=known_scrip,
                label=label,
                lp=lp,
                lc=ref["lc"],
                uc=ref["uc"],
            )
            return
        else:
            rec.emit(
                f"[{ts:%H:%M:%S}] WS   #{n:05d} tick     {known_scrip} {label} "
                f"lp={data.get('lp')} t={msg_type}"
            )
            if verbose_ticks:
                rec.emit(f"    RAW       : {raw}")

        received(
            n,
            ts,
            msg_type,
            "match",
            raw,
            scrip=known_scrip,
            label=label,
            tsym=data.get("ts"),
            lp=data.get("lp"),
        )

    def on_error(ws, error):
        stats["ws_errors"] += 1
        ts = datetime.now()
        rec.emit(f"[{ts:%H:%M:%S}] WS   ERROR: {error}")
        rec.record(
            {
                "transport": "ws",
                "dir": "event",
                "ts": ts.isoformat(),
                "outcome": "error",
                "detail": str(error),
            }
        )

    def on_close(ws, code, msg):
        ts = datetime.now()
        rec.emit(f"[{ts:%H:%M:%S}] WS   closed code={code} msg={msg}")
        rec.record(
            {
                "transport": "ws",
                "dir": "event",
                "ts": ts.isoformat(),
                "outcome": "closed",
                "code": code,
                "detail": str(msg),
            }
        )

    app = websocket.WebSocketApp(
        WS_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )

    def heartbeat():
        # Noren drops an idle socket; the adapter sends {"t":"h"} every 30s.
        while not stop.is_set() and time.monotonic() < deadline:
            if stop.wait(WS_HEARTBEAT_INTERVAL):
                return
            if state["authed"]:
                frame = {"t": WS_HEARTBEAT}
                try:
                    app.send(json.dumps(frame))
                    sent("heartbeat", frame)
                except Exception as e:
                    rec.emit(f"[{datetime.now():%H:%M:%S}] WS   heartbeat failed: {e}")

    def feed_monitor():
        # The first live run authenticated, subscribed, traded heartbeats for
        # six minutes and received no market data at all - and nothing in the
        # log said so until the summary. This says so while it is happening, so
        # a dead feed can be noticed inside the window rather than after it.
        while not stop.is_set() and time.monotonic() < deadline:
            if stop.wait(WS_STATUS_INTERVAL):
                return
            seen = stats["ws_ticks"]
            ts = datetime.now()
            if state["last_tick"] is None:
                rec.emit(
                    f"[{ts:%H:%M:%S}] WS   NO DATA YET - authed={state['authed']}, "
                    f"subscribed to {scrip_list}, {state['rx']} frames in, zero ticks"
                )
            else:
                gap = time.monotonic() - state["last_tick"]
                rec.emit(
                    f"[{ts:%H:%M:%S}] WS   feed alive - {seen} ticks "
                    f"(+{seen - state['reported']} since last check), last one {gap:.0f}s ago"
                )
            state["reported"] = seen

    def watchdog():
        # run_forever() blocks until the socket dies, so something has to close
        # it when the window ends or Ctrl+C is pressed.
        while not stop.is_set() and time.monotonic() < deadline:
            stop.wait(1.0)
        try:
            app.close()
        except Exception:
            pass

    threading.Thread(target=heartbeat, daemon=True).start()
    threading.Thread(target=feed_monitor, daemon=True).start()
    threading.Thread(target=watchdog, daemon=True).start()
    app.run_forever(ping_interval=30, ping_timeout=10, reconnect=5)


def write_summary(rec, targets, stats, started, transport):
    ended = datetime.now()
    rec.emit("-" * 78)
    rec.emit("SUMMARY")
    rec.emit(f"  window               : {started:%H:%M:%S} -> {ended:%H:%M:%S}")

    if transport in ("rest", "both"):
        wrong = sum(stats["mismatched"].values())
        ok = stats["total"] - stats["notok"] - stats["errors"]
        pct = (wrong / ok * 100) if ok else 0.0
        rec.emit()
        rec.emit("  REST GetQuotes")
        rec.emit(f"    requests           : {stats['total']}")
        rec.emit(f"    stat=Ok            : {ok}")
        rec.emit(f"    wrong instrument   : {wrong}  ({pct:.2f}% of stat=Ok)")
        rec.emit(f"    broker errors      : {stats['notok']}")
        rec.emit(f"    transport errors   : {stats['errors']}")
        lat = sorted(stats["latencies"])
        if lat:
            rec.emit(
                f"    latency ms         : p50 {lat[len(lat) // 2]}  "
                f"p95 {lat[int(len(lat) * 0.95)]}  max {lat[-1]}"
            )
        rec.emit("    per instrument:")
        for label, _, token, _ in targets:
            asked = stats["requested"][label]
            bad = stats["mismatched"][label]
            share = (bad / asked * 100) if asked else 0.0
            rec.emit(f"      {label:<30} {bad:>5}/{asked:<5} ({share:5.2f}%)  token {token}")
        if stats["leaked_as"]:
            rec.emit("    what came back instead:")
            for what, count in stats["leaked_as"].most_common():
                rec.emit(f"      {count:>5}x  {what}")

    if transport in ("ws", "both"):
        ticks = stats["ws_ticks"]
        bad = (
            stats["ws_unsolicited"]
            + stats["ws_wrong_symbol"]
            + stats["ws_out_of_band"]
            + stats["ws_exchange_mismatch"]
            + stats["ws_untokened"]
        )
        pct = (bad / ticks * 100) if ticks else 0.0
        rec.emit()
        rec.emit("  WebSocket touchline")
        rec.emit(f"    frames sent        : {stats['ws_sent']}")
        rec.emit(f"    frames received    : {stats['ws_received']}")
        rec.emit(f"    ticks              : {ticks}")
        first = stats["ws_first_tick"]
        rec.emit(
            f"    first tick         : {first:%H:%M:%S}"
            if first
            else "    first tick         : never"
        )
        rec.emit(f"    wrong instrument   : {bad}  ({pct:.2f}% of ticks)")
        rec.emit(f"      unsolicited scrip: {stats['ws_unsolicited']}")
        rec.emit(f"      wrong symbol     : {stats['ws_wrong_symbol']}")
        rec.emit(f"      price out of band: {stats['ws_out_of_band']}")
        rec.emit(f"      exchange mismatch: {stats['ws_exchange_mismatch']}")
        rec.emit(f"      tick w/o token   : {stats['ws_untokened']}")
        rec.emit(f"    reconnects         : {stats['ws_reconnects']}")
        rec.emit(f"    socket errors      : {stats['ws_errors']}")
        rec.emit("    per instrument:")
        for label, exch, token, _ in targets:
            got = stats["ws_per_scrip"][label]
            priced = stats["ws_priced"][label]
            last = stats["ws_last_lp"].get(label, "-")
            rec.emit(
                f"      {label:<30} {got:>5} ticks ({priced} priced)  "
                f"last lp={last}  {exch}|{token}"
            )
        if stats["ws_unsolicited_as"]:
            rec.emit("    scrips never subscribed to:")
            for what, count in stats["ws_unsolicited_as"].most_common():
                rec.emit(f"      {count:>5}x  {what}")
        if stats["ws_wrong_as"]:
            rec.emit("    what the feed got wrong:")
            for what, count in stats["ws_wrong_as"].most_common():
                rec.emit(f"      {count:>5}x  {what}")
        banded = sum(1 for label in stats["ws_banded"] if stats["ws_banded"][label])
        rec.emit(f"    price band checked on {banded}/{len(targets)} scrips - only the ones")
        rec.emit("    whose snapshot carried circuit limits could be checked this way;")
        rec.emit("    indices do not publish them, so a zero there proves nothing.")

    if transport == "both":
        rest_ok = stats["total"] - stats["notok"] - stats["errors"]
        rest_pct = (sum(stats["mismatched"].values()) / rest_ok * 100) if rest_ok else 0.0
        ws_bad = (
            stats["ws_unsolicited"]
            + stats["ws_wrong_symbol"]
            + stats["ws_out_of_band"]
            + stats["ws_exchange_mismatch"]
            + stats["ws_untokened"]
        )
        ws_pct = (ws_bad / stats["ws_ticks"] * 100) if stats["ws_ticks"] else 0.0
        rec.emit()
        rec.emit("  SIDE BY SIDE (same session, same window, same instruments)")
        rec.emit(f"    REST wrong-instrument rate : {rest_pct:.2f}%")
        rec.emit(f"    WS   wrong-instrument rate : {ws_pct:.2f}%")
        rec.emit("    REST is checked against the request it answered; WS against the")
        rec.emit("    identity and circuit band the feed published for that scrip itself.")
        if stats["ws_ticks"] == 0:
            rec.emit("    WS saw no ticks at all - a zero rate here means nothing.")
            if stats["ws_received"]:
                # The socket answered heartbeats but never delivered data. On
                # Noren a second WebSocket on the same uid authenticates
                # cleanly and is then starved, so the usual cause is another
                # client - OpenAlgo itself - already holding the feed.
                rec.emit(f"    The socket was alive ({stats['ws_received']} frames in) and the")
                rec.emit("    subscribe was accepted, so this is a starved feed, not a dead")
                rec.emit("    socket. Check whether another client holds a WebSocket on the")
                rec.emit("    same login, then re-run with that client stopped.")
            else:
                rec.emit("    Nothing came back at all. Re-run during market hours before")
                rec.emit("    drawing any conclusion.")

    rec.emit()
    rec.emit("Every REST mismatch above carried stat=Ok and a complete price payload.")
    rec.emit("-" * 78)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--minutes", type=float, default=60, help="run duration (default 60)")
    p.add_argument(
        "--transport",
        choices=("rest", "ws", "both"),
        default="both",
        help="which transport to soak (default both, so the rates are comparable)",
    )
    p.add_argument(
        "--rate", type=float, default=2, help="REST requests per second (default 2, max 9)"
    )
    p.add_argument(
        "--underlying",
        default=DEFAULT_UNDERLYING,
        help=f"underlying to discover contracts from (default {DEFAULT_UNDERLYING})",
    )
    p.add_argument(
        "--symbols",
        default=None,
        help="comma-separated SYMBOL:EXCHANGE list (default: discover the nearest-expiry ATM pair)",
    )
    p.add_argument(
        "--verbose-rest",
        action="store_true",
        help="log every matching GetQuotes reply too, not just the mismatches",
    )
    p.add_argument(
        "--verbose-ticks",
        action="store_true",
        help="dump each tick's full raw JSON as well as its one-line entry",
    )
    # Timestamped by default: a fixed name silently clobbers a previous run's
    # evidence, and these runs take an hour to reproduce.
    p.add_argument(
        "--out",
        default=f"log/shoonya_getquotes_soak_{datetime.now():%Y%m%d_%H%M%S}",
        help="output path, no extension (default is timestamped)",
    )
    args = p.parse_args()

    if args.rate > 9:
        sys.exit("--rate above 9 risks tripping Shoonya's 10/sec cap; refusing")

    auth_token, uid = load_session()
    targets = resolve(
        parse_symbols(args.symbols)
        if args.symbols
        else discover_symbols(auth_token, uid, args.underlying, DEFAULT_OPTION_EXCHANGE)
    )

    def redact(text):
        return text.replace(auth_token, "<SESSION_KEY_REDACTED>").replace(uid, "<CLIENT_ID>")

    out = ROOT / args.out
    out.parent.mkdir(parents=True, exist_ok=True)
    log_path = out.with_suffix(".log")
    jsonl_path = out.with_suffix(".jsonl")

    deadline = time.monotonic() + args.minutes * 60
    started = datetime.now()

    stats = {
        "total": 0,
        "notok": 0,
        "errors": 0,
        "latencies": [],
        "requested": Counter(),
        "mismatched": Counter(),
        "leaked_as": Counter(),
        "ws_sent": 0,
        "ws_received": 0,
        "ws_ticks": 0,
        "ws_first_tick": None,
        "ws_unsolicited": 0,
        "ws_wrong_symbol": 0,
        "ws_out_of_band": 0,
        "ws_wrong_as": Counter(),
        "ws_banded": Counter(),
        "ws_unsolicited_as": Counter(),
        "ws_exchange_mismatch": 0,
        "ws_untokened": 0,
        "ws_reconnects": 0,
        "ws_errors": 0,
        "ws_per_scrip": Counter(),
        "ws_priced": Counter(),
        "ws_last_lp": {},
    }

    signal.signal(signal.SIGINT, _handle_sigint)

    # Line-buffered: an hour-long run should be readable while it is running,
    # and survive a hard kill with everything up to that point intact.
    with (
        open(log_path, "w", encoding="utf-8", buffering=1) as log,
        open(jsonl_path, "w", encoding="utf-8", buffering=1) as jsonl,
    ):
        rec = Recorder(log, jsonl, redact)

        rec.emit("Shoonya market data soak - does a request get the instrument it asked for?")
        rec.emit("=" * 78)
        rec.emit(f"Started     : {started.isoformat(timespec='seconds')} IST")
        rec.emit(f"Transport   : {args.transport}")
        rec.emit(f"REST        : {REST_URL}")
        rec.emit(f"WS          : {WS_URL}")
        rec.emit(f"Duration    : {args.minutes:g} minutes, REST at {args.rate:g} req/sec")
        rec.emit("Method      : REST strictly sequential on one connection; WS one touchline")
        rec.emit("              subscription. Read-only, same session for both.")
        rec.emit("Client id   : redacted")
        rec.emit(f"Instruments : {', '.join(f'{t[0]} ({t[1]}|{t[2]})' for t in targets)}")
        rec.emit()
        rec.emit("REST: every reply's echoed exch/token is checked against the request. A")
        rec.emit("mismatch means Shoonya answered with a different instrument's snapshot,")
        rec.emit("with stat=Ok, so the caller cannot detect it except by this comparison.")
        rec.emit(
            "      Only mismatches and errors appear below"
            + ("; --verbose-rest is on, so matches do too." if args.verbose_rest else ".")
        )
        rec.emit("      Every request, matching or not, is in the .jsonl either way.")
        rec.emit("WS:   every tick's token must belong to a subscribed scrip. A tick for")
        rec.emit("anything else is data this client never asked for. Every frame in either")
        rec.emit("direction is logged - a feed that goes quiet has to be distinguishable")
        rec.emit("from one that behaved, and only a captured stream can do that.")
        rec.emit("-" * 78)

        ws_thread = None
        try:
            if args.transport in ("ws", "both"):
                ws_thread = threading.Thread(
                    target=run_ws_soak,
                    args=(rec, targets, auth_token, uid, deadline, stats, args.verbose_ticks),
                    daemon=True,
                )
                ws_thread.start()

            if args.transport in ("rest", "both"):
                run_rest_soak(
                    rec, targets, auth_token, uid, args.rate, deadline, stats, args.verbose_rest
                )
            else:
                # WS only: idle here until the window closes.
                while not stop.is_set() and time.monotonic() < deadline:
                    stop.wait(1.0)
        finally:
            # In a finally block so Ctrl+C, an exception or a clean finish all
            # leave a usable summary behind.
            stop.set()
            if ws_thread is not None:
                ws_thread.join(timeout=10)
            write_summary(rec, targets, stats, started, args.transport)

    print(f"log   : {log_path}")
    print(f"jsonl : {jsonl_path}")


if __name__ == "__main__":
    main()
