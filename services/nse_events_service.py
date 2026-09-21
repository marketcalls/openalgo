# services/nse_events_service.py
"""
NSE corporate-event client — board meetings, results and corporate actions,
keyed by symbol so a scanner row can be flagged before it is traded.

Why this lives server-side: nseindia.com rejects API calls without the cookies
its homepage sets, and the browser cannot warm that session cross-origin. It
also means one fetch serves every client instead of each tab hammering NSE.

Cached for the trading day. Results dates and board meetings are announced days
ahead and do not change intraday, so a single morning fetch is enough; the cache
key is the IST date, so the first request after midnight refetches.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from utils.logging import get_logger

logger = get_logger(__name__)

NSE_BASE = "https://www.nseindia.com"
# Board meetings carry the "purpose" text (Results / Dividend / Fund Raising),
# corporate actions carry ex-dates for splits, bonuses and dividends.
_ENDPOINTS = {
    "board_meeting": "/api/event-calendar",
    "corporate_action": "/api/corporates-corporateActions?index=equities",
}
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{NSE_BASE}/companies-listing/corporate-filings-event-calendar",
}
_TIMEOUT = 15

_IST = timezone(timedelta(hours=5, minutes=30))

_lock = threading.Lock()
_cache: dict[str, Any] = {"date": None, "events": {}}


def _today_ist() -> str:
    return datetime.now(_IST).strftime("%Y-%m-%d")


def _new_session() -> requests.Session:
    """A session carrying NSE's homepage cookies. Without this warm-up every
    /api/ call returns 401."""
    session = requests.Session()
    session.headers.update(_HEADERS)
    session.get(NSE_BASE, timeout=_TIMEOUT)
    return session


def _parse_date(value: str) -> str | None:
    """NSE mixes formats across endpoints. Returns ISO date, or None if the
    field is unparseable — an event with no usable date is dropped rather than
    guessed, since a wrong date on a trading flag is worse than no flag."""
    if not value:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d-%b-%Y %H:%M:%S"):
        try:
            return datetime.strptime(value.strip()[:20], fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _collect(session: requests.Session, kind: str, path: str) -> list[dict[str, str]]:
    resp = session.get(f"{NSE_BASE}{path}", timeout=_TIMEOUT)
    resp.raise_for_status()
    rows = resp.json()
    if isinstance(rows, dict):  # some endpoints wrap the list
        rows = rows.get("data") or []

    out: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        symbol = (row.get("symbol") or row.get("Symbol") or "").strip().upper()
        date = _parse_date(
            row.get("date")
            or row.get("meetingDate")
            or row.get("exDate")
            or row.get("exdate")
            or ""
        )
        if not symbol or not date:
            continue
        out.append(
            {
                "symbol": symbol,
                "kind": kind,
                "date": date,
                "purpose": (row.get("purpose") or row.get("subject") or row.get("comp") or "")[:120],
            }
        )
    return out


def fetch_events(force: bool = False) -> dict[str, list[dict[str, str]]]:
    """symbol -> list of upcoming events, cached for the IST day.

    Returns whatever it managed to collect: NSE frequently serves one endpoint
    and 401s the other, and a partial calendar is far more useful than none.
    Never raises — a failed fetch degrades the badge, it must not take down the
    scanner's own request path.
    """
    today = _today_ist()
    with _lock:
        if not force and _cache["date"] == today and _cache["events"]:
            return _cache["events"]

    events: dict[str, list[dict[str, str]]] = {}
    try:
        session = _new_session()
        for kind, path in _ENDPOINTS.items():
            try:
                for row in _collect(session, kind, path):
                    events.setdefault(row["symbol"], []).append(row)
            except Exception as err:  # one endpoint failing must not lose the other
                logger.warning("NSE %s fetch failed: %s", kind, err)
    except Exception as err:
        logger.warning("NSE session warm-up failed: %s", err)
        return _cache["events"] if _cache["date"] == today else {}

    if events:
        with _lock:
            _cache["date"] = today
            _cache["events"] = events
        logger.info("NSE events cached for %s: %d symbols", today, len(events))
    return events


def events_for(symbols: list[str], within_days: int = 2) -> dict[str, dict[str, str]]:
    """The single most relevant event per symbol inside the window.

    One event per symbol, soonest first: the caller is drawing a badge, not a
    calendar. `within_days` counts from today, so 0 = today only.
    """
    all_events = fetch_events()
    if not all_events:
        return {}

    today = datetime.now(_IST).date()
    horizon = today + timedelta(days=within_days)
    wanted = {s.strip().upper() for s in symbols}

    out: dict[str, dict[str, str]] = {}
    for symbol in wanted:
        upcoming = []
        for ev in all_events.get(symbol, []):
            try:
                day = datetime.strptime(ev["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            if today <= day <= horizon:
                upcoming.append((day, ev))
        if upcoming:
            upcoming.sort(key=lambda pair: pair[0])
            day, ev = upcoming[0]
            out[symbol] = {
                "kind": ev["kind"],
                "date": ev["date"],
                "purpose": ev["purpose"],
                "daysAway": (day - today).days,
            }
    return out
