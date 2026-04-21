import os
import re
from typing import Any

import httpx

from database.auth_db import verify_api_key
from utils.httpx_client import get_httpx_client
from utils.logging import get_logger

logger = get_logger(__name__)

ADANOS_DOCS_URL = "https://api.adanos.org/docs/"
ADANOS_SUPPORTED_SOURCES = ("reddit", "x", "news", "polymarket")
TICKER_RE = re.compile(r"^[A-Z][A-Z0-9.]{0,9}$")


def _to_number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if not parsed.is_integer():
        return parsed
    return int(parsed)


def normalize_tickers(tickers: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []

    for raw_ticker in tickers:
        ticker = str(raw_ticker or "").strip().replace("$", "").upper()
        if not ticker or not TICKER_RE.match(ticker) or ticker in seen:
            continue
        seen.add(ticker)
        normalized.append(ticker)

    return normalized[:10]


def _pick(record: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in record:
            return record[key]
    return None


def normalize_compare_rows(source: str, payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, dict):
        rows = payload.get("stocks") or payload.get("data") or payload.get("results") or []
    else:
        rows = []

    if not isinstance(rows, list):
        return []

    normalized_rows: list[dict[str, Any]] = []
    for entry in rows:
        if not isinstance(entry, dict):
            continue

        ticker = str(_pick(entry, "ticker", "symbol") or "").strip().replace("$", "").upper()
        if not ticker or not TICKER_RE.match(ticker):
            continue

        trend_history = entry.get("trend_history")
        if isinstance(trend_history, list):
            normalized_history = [
                value for value in (_to_number(item) for item in trend_history) if value is not None
            ]
        else:
            normalized_history = []

        normalized_rows.append(
            {
                "ticker": ticker,
                "company_name": _pick(entry, "company_name", "name", "company"),
                "source": source,
                "sentiment_score": _to_number(
                    _pick(entry, "sentiment_score", "sentiment", "score")
                ),
                "buzz_score": _to_number(_pick(entry, "buzz_score", "buzz")),
                "bullish_pct": _to_number(entry.get("bullish_pct")),
                "bearish_pct": _to_number(entry.get("bearish_pct")),
                "mentions": _to_number(_pick(entry, "mentions", "mention_count")),
                "subreddit_count": _to_number(entry.get("subreddit_count")),
                "source_count": _to_number(entry.get("source_count")),
                "unique_tweets": _to_number(entry.get("unique_tweets")),
                "trade_count": _to_number(entry.get("trade_count")),
                "market_count": _to_number(entry.get("market_count")),
                "total_liquidity": _to_number(entry.get("total_liquidity")),
                "trend": entry.get("trend") if isinstance(entry.get("trend"), str) else None,
                "trend_history": normalized_history,
            }
        )

    return normalized_rows


def build_summary(snapshots: list[dict[str, Any]]) -> str:
    lines: list[str] = []

    for snapshot in snapshots:
        if not snapshot.get("success") or not snapshot.get("stocks"):
            if snapshot.get("error"):
                lines.append(f"- {snapshot['source']}: unavailable ({snapshot['error']})")
            else:
                lines.append(f"- {snapshot['source']}: no qualifying sentiment rows returned")
            continue

        ranked_rows = sorted(
            snapshot["stocks"],
            key=lambda row: row.get("buzz_score")
            if row.get("buzz_score") is not None
            else float("-inf"),
            reverse=True,
        )[:3]

        fragments = []
        for row in ranked_rows:
            metrics = []
            if row.get("sentiment_score") is not None:
                metrics.append(f"sentiment={float(row['sentiment_score']):.2f}")
            if row.get("buzz_score") is not None:
                metrics.append(f"buzz={float(row['buzz_score']):.1f}")
            if row.get("bullish_pct") is not None:
                metrics.append(f"bullish={float(row['bullish_pct']):.0f}%")
            if row.get("mentions") is not None:
                metrics.append(f"mentions={int(row['mentions'])}")
            if row.get("trade_count") is not None:
                metrics.append(f"trades={int(row['trade_count'])}")
            if row.get("trend"):
                metrics.append(f"trend={row['trend']}")

            label = row["ticker"]
            if row.get("company_name"):
                label = f"{label} ({row['company_name']})"
            fragments.append(f"{label}: {', '.join(metrics)}")

        lines.append(f"- {snapshot['source']}: {' | '.join(fragments)}")

    return "\n".join(lines)


def _get_adanos_base_url() -> str:
    return os.getenv("ADANOS_API_BASE_URL", "https://api.adanos.org").rstrip("/")


def _get_adanos_timeout_seconds() -> float:
    raw_timeout = os.getenv("ADANOS_API_TIMEOUT_MS", "10000")
    try:
        timeout_ms = int(raw_timeout)
    except ValueError:
        timeout_ms = 10000
    return max(timeout_ms, 1000) / 1000


def _get_default_days() -> int:
    raw_days = os.getenv("ADANOS_SENTIMENT_DEFAULT_DAYS", "7")
    try:
        parsed_days = int(raw_days)
    except ValueError:
        parsed_days = 7
    return min(max(parsed_days, 1), 30)


def _fetch_source_snapshot(
    client: httpx.Client,
    base_url: str,
    source: str,
    tickers: list[str],
    days: int,
    adanos_api_key: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    endpoint = f"{base_url}/{source}/stocks/v1/compare"

    try:
        response = client.get(
            endpoint,
            headers={
                "Accept": "application/json",
                "X-API-Key": adanos_api_key,
            },
            params={"tickers": ",".join(tickers), "days": days},
            timeout=timeout_seconds,
        )
    except httpx.TimeoutException:
        return {
            "source": source,
            "endpoint": endpoint,
            "success": False,
            "error": "Request timed out",
            "stocks": [],
        }
    except httpx.HTTPError as exc:
        return {
            "source": source,
            "endpoint": endpoint,
            "success": False,
            "error": str(exc),
            "stocks": [],
        }

    if response.status_code >= 400:
        return {
            "source": source,
            "endpoint": endpoint,
            "success": False,
            "error": f"HTTP {response.status_code}",
            "stocks": [],
        }

    try:
        payload = response.json()
    except ValueError:
        return {
            "source": source,
            "endpoint": endpoint,
            "success": False,
            "error": "Invalid JSON response",
            "stocks": [],
        }

    return {
        "source": source,
        "endpoint": endpoint,
        "success": True,
        "stocks": normalize_compare_rows(source, payload),
    }


def get_market_sentiment(
    api_key: str, tickers: list[str], source: str = "all", days: int | None = None
) -> tuple[bool, dict[str, Any], int]:
    if not api_key:
        return False, {"status": "error", "message": "Missing API Key"}, 401

    user_id = verify_api_key(api_key)
    if not user_id:
        return False, {"status": "error", "message": "Invalid openalgo apikey"}, 403

    normalized_tickers = normalize_tickers(tickers)
    if not normalized_tickers:
        return (
            False,
            {
                "status": "error",
                "message": "No valid stock tickers provided. Use raw tickers like AAPL, TSLA, MSFT.",
            },
            400,
        )

    adanos_api_key = os.getenv("ADANOS_API_KEY", "").strip()
    base_url = _get_adanos_base_url()
    lookback_days = days or _get_default_days()
    timeout_seconds = _get_adanos_timeout_seconds()

    if not adanos_api_key:
        return (
            True,
            {
                "status": "success",
                "data": {
                    "enabled": False,
                    "provider": "adanos",
                    "tickers": normalized_tickers,
                    "source": source,
                    "days": lookback_days,
                    "snapshots": [],
                    "summary": "Adanos market sentiment is disabled because ADANOS_API_KEY is not configured.",
                    "docs_url": ADANOS_DOCS_URL,
                },
            },
            200,
        )

    sources = list(ADANOS_SUPPORTED_SOURCES) if source == "all" else [source]
    client = get_httpx_client()
    snapshots = [
        _fetch_source_snapshot(
            client=client,
            base_url=base_url,
            source=entry,
            tickers=normalized_tickers,
            days=lookback_days,
            adanos_api_key=adanos_api_key,
            timeout_seconds=timeout_seconds,
        )
        for entry in sources
    ]
    has_rows = any(snapshot["success"] and snapshot["stocks"] for snapshot in snapshots)

    response_data = {
        "enabled": True,
        "provider": "adanos",
        "tickers": normalized_tickers,
        "source": source,
        "days": lookback_days,
        "snapshots": snapshots,
        "summary": build_summary(snapshots),
        "docs_url": ADANOS_DOCS_URL,
    }

    if not has_rows:
        response_data["message"] = "No Adanos sentiment rows were returned for the requested tickers."

    logger.info(
        "[AdanosSentiment] user=%s source=%s tickers=%s has_rows=%s",
        user_id,
        source,
        ",".join(normalized_tickers),
        has_rows,
    )
    return True, {"status": "success", "data": response_data}, 200
