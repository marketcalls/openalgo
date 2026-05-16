#!/usr/bin/env python3
"""Streamlit UI for browsing archived Lean backtest runs."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import streamlit as st

from data_store import latest_run_id, load_run_payload, read_index


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"


@dataclass(frozen=True)
class AppOptions:
    results_dir: Path
    run_id: str


def _parse_args() -> AppOptions:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR))
    parser.add_argument("--run-id", default="")
    args, _unknown = parser.parse_known_args()
    return AppOptions(results_dir=Path(args.results_dir).expanduser().resolve(), run_id=args.run_id)


@st.cache_data(show_spinner=False)
def _cached_index(results_dir_str: str, _index_mtime_ns: int) -> list[dict[str, Any]]:
    return read_index(Path(results_dir_str))


@st.cache_data(show_spinner=False)
def _cached_run_payload(
    results_dir_str: str,
    run_id: str,
    _normalized_mtime_ns: int,
    _detailed_mtime_ns: int,
) -> dict[str, Any] | None:
    return load_run_payload(Path(results_dir_str), run_id)


def _safe_mtime_ns(path: Path) -> int:
    try:
        return path.stat().st_mtime_ns
    except OSError:
        return 0


def _as_datetime(value: str) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
    except ValueError:
        return None


def _score(entry: dict[str, Any], key: str) -> float:
    metrics = entry.get("metrics", {})
    value = metrics.get(key, 0)
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _apply_filters(
    entries: list[dict[str, Any]],
    search_text: str,
    date_from: date | None,
    date_to: date | None,
    sort_mode: str,
) -> list[dict[str, Any]]:
    normalized_search = search_text.strip().lower()
    filtered: list[dict[str, Any]] = []

    for entry in entries:
        run_id = str(entry.get("runId", ""))
        algo = str(entry.get("algorithmType", ""))
        haystack = f"{run_id} {algo}".lower()
        if normalized_search and normalized_search not in haystack:
            continue

        ts = _as_datetime(str(entry.get("timestamp", "")))
        if date_from and (ts is None or ts.date() < date_from):
            continue
        if date_to and (ts is None or ts.date() > date_to):
            continue

        filtered.append(entry)

    if sort_mode == "Newest":
        filtered.sort(key=lambda item: str(item.get("timestamp", "")), reverse=True)
    elif sort_mode == "Oldest":
        filtered.sort(key=lambda item: str(item.get("timestamp", "")))
    elif sort_mode == "Best Net Profit":
        filtered.sort(key=lambda item: _score(item, "netProfitPct"), reverse=True)
    elif sort_mode == "Worst Drawdown":
        filtered.sort(key=lambda item: _score(item, "drawdownPct"), reverse=True)

    return filtered


def _format_pct(value: Any) -> str:
    try:
        return f"{float(value):.2f}%"
    except (TypeError, ValueError):
        return "-"


def _format_num(value: Any) -> str:
    try:
        return f"{float(value):,.2f}"
    except (TypeError, ValueError):
        return "-"


def _to_datetime_any(value: Any) -> datetime | None:
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 10_000_000_000:
            ts = ts / 1000.0
        return datetime.fromtimestamp(ts, tz=UTC)
    if isinstance(value, str) and value.strip():
        parsed = _as_datetime(value)
        return parsed if parsed is not None else None
    return None


def _derive_effective_window(payload: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    start: datetime | None = None
    end: datetime | None = None

    trades = payload.get("trades") if isinstance(payload.get("trades"), list) else []
    orders = payload.get("orders") if isinstance(payload.get("orders"), list) else []

    for trade in trades:
        if not isinstance(trade, dict):
            continue
        trade_start = _to_datetime_any(trade.get("startDateTime"))
        trade_end = _to_datetime_any(trade.get("endDateTime"))

        if trade_start is not None:
            start = trade_start if start is None else min(start, trade_start)
        if trade_end is not None:
            end = trade_end if end is None else max(end, trade_end)

    for order in orders:
        if not isinstance(order, dict):
            continue
        order_time = _to_datetime_any(order.get("time"))
        if order_time is None:
            continue
        start = order_time if start is None else min(start, order_time)
        end = order_time if end is None else max(end, order_time)

    if start is not None and end is not None:
        return start, end

    date_range = payload.get("dateRange") if isinstance(payload.get("dateRange"), dict) else {}
    configured_start = _to_datetime_any(date_range.get("start"))
    configured_end = _to_datetime_any(date_range.get("end"))
    if configured_start is not None and configured_end is not None:
        return configured_start, configured_end

    equity = payload.get("equity") if isinstance(payload.get("equity"), list) else []
    if equity:
        first = _to_datetime_any(equity[0].get("t") if isinstance(equity[0], dict) else None)
        last = _to_datetime_any(equity[-1].get("t") if isinstance(equity[-1], dict) else None)
        return first, last

    return None, None


def _is_in_window(value: Any, start: datetime | None, end: datetime | None) -> bool:
    dt = _to_datetime_any(value)
    if dt is None:
        return False
    if start is not None and dt < start:
        return False
    if end is not None and dt > end:
        return False
    return True


def _filter_points_window(points: list[dict[str, Any]], start: datetime | None, end: datetime | None) -> list[dict[str, Any]]:
    if start is None or end is None:
        return points
    return [p for p in points if isinstance(p, dict) and _is_in_window(p.get("t"), start, end)]


def _build_chart_series(points: list[dict[str, Any]]) -> tuple[list[datetime], list[float]]:
    xs: list[datetime] = []
    ys: list[float] = []

    for point in points:
        if not isinstance(point, dict):
            continue
        t_raw = point.get("t")
        v_raw = point.get("v")
        timestamp = _to_datetime_any(t_raw)
        if timestamp is None:
            continue
        try:
            value = float(v_raw)
        except (TypeError, ValueError):
            continue
        xs.append(timestamp)
        ys.append(value)
    return xs, ys


def _build_candle_series(
    candles: list[dict[str, Any]],
    fallback_equity: list[dict[str, Any]],
) -> tuple[list[datetime], list[float], list[float], list[float], list[float]]:
    xs: list[datetime] = []
    opens: list[float] = []
    highs: list[float] = []
    lows: list[float] = []
    closes: list[float] = []

    for candle in candles:
        if not isinstance(candle, dict):
            continue
        dt = _to_datetime_any(candle.get("t"))
        if dt is None:
            continue

        try:
            open_v = float(candle.get("o"))
            high_v = float(candle.get("h"))
            low_v = float(candle.get("l"))
            close_v = float(candle.get("c"))
        except (TypeError, ValueError):
            continue

        xs.append(dt)
        opens.append(open_v)
        highs.append(high_v)
        lows.append(low_v)
        closes.append(close_v)

    if xs:
        return xs, opens, highs, lows, closes

    # Fallback for older normalized runs that only include equity close values.
    eq_x, eq_y = _build_chart_series(fallback_equity)
    if not eq_x:
        return [], [], [], [], []

    previous_close = eq_y[0]
    for dt, close_v in zip(eq_x, eq_y):
        open_v = previous_close
        high_v = max(open_v, close_v)
        low_v = min(open_v, close_v)

        xs.append(dt)
        opens.append(open_v)
        highs.append(high_v)
        lows.append(low_v)
        closes.append(close_v)
        previous_close = close_v

    return xs, opens, highs, lows, closes


def _render_equity_chart(
    equity: list[dict[str, Any]],
    equity_candles: list[dict[str, Any]],
    drawdown: list[dict[str, Any]],
    orders: list[dict[str, Any]],
    start: datetime | None,
    end: datetime | None,
) -> None:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    filtered_equity = _filter_points_window(equity, start, end)
    filtered_candles = _filter_points_window(equity_candles, start, end)
    filtered_drawdown = _filter_points_window(drawdown, start, end)
    filtered_orders = [
        order
        for order in orders
        if isinstance(order, dict) and _is_in_window(order.get("time"), start, end)
    ]

    eq_x, eq_o, eq_h, eq_l, eq_c = _build_candle_series(filtered_candles, filtered_equity)
    dd_x, dd_y = _build_chart_series(filtered_drawdown)

    if not eq_x:
        st.info("No equity data available.")
        return

    # Keep equity candles framed with a small top/bottom padding so zoom starts in a readable state.
    y_min = min(eq_l)
    y_max = max(eq_h)
    y_pad = max((y_max - y_min) * 0.08, 1.0)

    fig = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        row_heights=[0.72, 0.28],
        vertical_spacing=0.03,
    )

    # ── Equity area curve ──────────────────────────────────────────────────
    fig.add_trace(
        go.Candlestick(
            x=eq_x,
            open=eq_o,
            high=eq_h,
            low=eq_l,
            close=eq_c,
            name="Equity Candles",
            increasing_line_color="#26a69a",
            decreasing_line_color="#ef5350",
            increasing_fillcolor="rgba(38,166,154,0.75)",
            decreasing_fillcolor="rgba(239,83,80,0.75)",
            hovertemplate=(
                "Date: %{x|%Y-%m-%d}<br>"
                "Open: $%{open:,.2f}<br>"
                "High: $%{high:,.2f}<br>"
                "Low: $%{low:,.2f}<br>"
                "Close: $%{close:,.2f}<extra></extra>"
            ),
        ),
        row=1,
        col=1,
    )

    # ── Trade markers ──────────────────────────────────────────────────────
    buy_x, buy_y, buy_text = [], [], []
    sell_x, sell_y, sell_text = [], [], []

    equity_lookup: dict[str, float] = {x.strftime("%Y-%m-%d"): y for x, y in zip(eq_x, eq_c)}
    eq_y = eq_c

    def _nearest_equity(dt_str: str) -> float | None:
        if not dt_str:
            return None
        day = dt_str[:10]
        if day in equity_lookup:
            return equity_lookup[day]
        # fall back to closest available date
        for x, y in zip(eq_x, eq_y):
            if x.strftime("%Y-%m-%d") >= day:
                return y
        return eq_c[-1] if eq_c else None

    for order in filtered_orders:
        if not isinstance(order, dict):
            continue

        order_time_raw = order.get("time")
        order_dt = _as_datetime(str(order_time_raw)) if order_time_raw is not None else None
        if order_dt is None:
            continue

        direction = str(order.get("direction", "")).lower()
        symbol = str(order.get("symbol", ""))
        qty = order.get("quantity", 0)
        price = order.get("price")

        try:
            qty_val = float(qty)
        except (TypeError, ValueError):
            qty_val = 0.0

        marker_price = _nearest_equity(order_dt.date().isoformat())
        if marker_price is None:
            try:
                marker_price = float(price)
            except (TypeError, ValueError):
                continue

        label = f"{symbol} {direction.title()} {qty_val:,.0f} @ ${marker_price:,.2f}".strip()
        is_buy = "buy" in direction or "long" in direction
        marker_dt = order_dt.date().isoformat()

        if is_buy:
            buy_x.append(marker_dt)
            buy_y.append(marker_price)
            buy_text.append(f"Entry: {label}")
        else:
            sell_x.append(marker_dt)
            sell_y.append(marker_price)
            sell_text.append(f"Exit: {label}")

    if buy_x:
        fig.add_trace(
            go.Scatter(
                x=buy_x,
                y=buy_y,
                mode="markers",
                name="Entry",
                marker={
                    "symbol": "triangle-up",
                    "size": 9,
                    "color": "#26a69a",
                    "line": {"width": 1, "color": "#ffffff"},
                },
                text=buy_text,
                hovertemplate="%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    if sell_x:
        fig.add_trace(
            go.Scatter(
                x=sell_x,
                y=sell_y,
                mode="markers",
                name="Exit",
                marker={
                    "symbol": "triangle-down",
                    "size": 9,
                    "color": "#ef5350",
                    "line": {"width": 1, "color": "#ffffff"},
                },
                text=sell_text,
                hovertemplate="%{text}<extra></extra>",
            ),
            row=1,
            col=1,
        )

    # ── Drawdown bars ──────────────────────────────────────────────────────
    if dd_x:
        fig.add_trace(
            go.Bar(
                x=dd_x,
                y=dd_y,
                name="Drawdown",
                marker_color="#ef5350",
                opacity=0.7,
                hovertemplate="%{x|%Y-%m-%d}<br><b>%{y:.2f}%</b><extra></extra>",
            ),
            row=2,
            col=1,
        )

    # ── Layout ─────────────────────────────────────────────────────────────
    fig.update_layout(
        height=540,
        margin={"l": 8, "r": 8, "t": 24, "b": 8},
        dragmode="pan",
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.01,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 12},
        },
        hovermode="x unified",
        plot_bgcolor="#0e1117",
        paper_bgcolor="#0e1117",
        font={"color": "#fafafa", "size": 12},
        xaxis={
            "showgrid": True,
            "gridcolor": "#1f2937",
            "zeroline": False,
            "rangeslider": {"visible": False},
        },
        yaxis={
            "showgrid": True,
            "gridcolor": "#1f2937",
            "zeroline": False,
            "tickprefix": "$",
            "tickformat": ",.0f",
            "title": "Equity",
            "autorange": True,
            "range": [y_min - y_pad, y_max + y_pad],
            "fixedrange": False,
        },
        xaxis2={"showgrid": True, "gridcolor": "#1f2937"},
        yaxis2={
            "showgrid": True,
            "gridcolor": "#1f2937",
            "zeroline": False,
            "tickformat": ".1f",
            "title": "Drawdown %",
        },
        bargap=0,
    )

    st.plotly_chart(
        fig,
        width="stretch",
        config={
            "scrollZoom": True,
            "displaylogo": False,
            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        },
    )


def _render_kpis(summary: dict[str, Any]) -> None:
    a, b, c, d = st.columns(4)
    a.metric("Net Profit", _format_pct(summary.get("netProfitPct")))
    b.metric("Drawdown", _format_pct(summary.get("drawdownPct")))
    c.metric("Sharpe", _format_num(summary.get("sharpeRatio")))
    d.metric("Orders", str(summary.get("totalOrders", "-")))

    e, f, g, h = st.columns(4)
    e.metric("Start Equity", _format_num(summary.get("startEquity")))
    f.metric("End Equity", _format_num(summary.get("endEquity")))
    g.metric("Win Rate", _format_pct(summary.get("winRatePct")))
    h.metric("Profit Factor", _format_num(summary.get("profitFactor")))


def _render_tables(payload: dict[str, Any]) -> None:
    st.subheader("Trades")
    trades = payload.get("trades", [])
    st.dataframe(trades if isinstance(trades, list) else [], width="stretch", hide_index=True)

    st.subheader("Orders")
    orders = payload.get("orders", [])
    st.dataframe(orders if isinstance(orders, list) else [], width="stretch", hide_index=True)


def _query_param_run_id() -> str:
    try:
        params = st.query_params
        run_value = params.get("run", "")
    except AttributeError:
        params = st.experimental_get_query_params()
        run_value = params.get("run", "")
    if isinstance(run_value, list):
        return run_value[0] if run_value else ""
    return str(run_value)


def main() -> None:
    options = _parse_args()
    results_dir = options.results_dir
    results_dir.mkdir(parents=True, exist_ok=True)

    st.set_page_config(page_title="Lean Backtest Visualizer", layout="wide")
    st.title("Lean Backtest Visualizer")
    st.caption(f"Results: {results_dir}")

    index_mtime_ns = _safe_mtime_ns(results_dir / "index.json")
    index_entries = _cached_index(str(results_dir), index_mtime_ns)
    if not index_entries:
        st.warning("No archived runs found in results/index.json.")
        return

    st.sidebar.header("Run History")
    search_text = st.sidebar.text_input("Search", value="", placeholder="Strategy name or run id")
    date_from = st.sidebar.date_input("From", value=None)
    date_to = st.sidebar.date_input("To", value=None)
    sort_mode = st.sidebar.selectbox(
        "Sort by",
        options=["Newest", "Oldest", "Best Net Profit", "Worst Drawdown"],
        index=0,
    )

    initial_run_id = options.run_id or _query_param_run_id() or latest_run_id(results_dir) or ""

    filtered = _apply_filters(index_entries, search_text, date_from, date_to, sort_mode)
    if not filtered:
        st.info("No runs match the current filters.")
        return

    run_ids = [str(entry.get("runId", "")) for entry in filtered if entry.get("runId")]
    if not run_ids:
        st.info("Filtered runs contain no valid run ids.")
        return

    default_index = 0
    if initial_run_id in run_ids:
        default_index = run_ids.index(initial_run_id)

    selected_run_id = st.sidebar.selectbox("Run", options=run_ids, index=default_index)

    run_dir = results_dir / "runs" / selected_run_id
    normalized_mtime_ns = _safe_mtime_ns(run_dir / "normalized.json")
    detailed_mtime_ns = _safe_mtime_ns(run_dir / "raw-detailed.json")
    payload = _cached_run_payload(
        str(results_dir),
        selected_run_id,
        normalized_mtime_ns,
        detailed_mtime_ns,
    )
    if not payload:
        st.error(f"Run not found: {selected_run_id}")
        return

    summary = payload.get("summary", {}) if isinstance(payload.get("summary"), dict) else {}
    effective_start, effective_end = _derive_effective_window(payload)

    algo_name = payload.get("algorithmType", "Unknown")
    run_status = payload.get("status", "Unknown")
    st.subheader(f"{algo_name} • {selected_run_id}")
    st.caption(f"Status: {run_status}")

    _render_kpis(summary)

    st.subheader("Strategy Equity & Drawdown")
    if effective_start is not None and effective_end is not None:
        st.caption(f"Window: {effective_start.date().isoformat()} to {effective_end.date().isoformat()}")
    _render_equity_chart(
        payload.get("equity", []),
        payload.get("equityCandles", []),
        payload.get("drawdown", []),
        payload.get("orders", []),
        effective_start,
        effective_end,
    )

    _render_tables(payload)


if __name__ == "__main__":
    main()
