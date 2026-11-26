"""Backtest a strategy file over history, through the strategy's own code.

    uv run python .claude/skills/python-strategy/backtest.py <strategy.py>
        [--days N | --from YYYY-MM-DD [--to YYYY-MM-DD]] [--source api|db]

The file is imported, not copied: its signals(), its kit's risk translation,
entry window, square-off and daily limits are the ones exercised here, and
stops, targets and trails are decided by OpenAlgo's risk engine exactly as in
live trading. What this adds is only the replay of history:

* a signal on a bar acts at the next bar's open (live: an order sent when the
  bar closes); a daily strategy acts at the bar's close (live: DECISION_TIME)
* each bar is replayed open, adverse extreme, favourable extreme, close, so a
  stop and a target inside one bar resolve against the trader
* a stop or target fills at its level, or at the open when price gaps past it
* charges and slippage are applied to every order (COST_PCT,
  BROKERAGE_PER_ORDER, SLIPPAGE_PCT in the strategy's settings)

It also checks that signals() does not read future bars: a flag that changes
when later bars are added is reported, because live trading cannot see them.

Writes trades.csv and equity.csv to a backtest/ folder beside the strategy.
No order is placed; only history and symbol details are requested.
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _host  # noqa: E402


def _path(bar, side):
    """Open, adverse extreme, favourable extreme, close."""
    o, h, low, c = (float(bar[k]) for k in ("open", "high", "low", "close"))
    return [o, low, h, c] if side == "BUY" else [o, h, low, c]


@dataclass(frozen=True)
class Costs:
    capital: float
    cost_pct: float
    brokerage_pct: float | None
    brokerage_per_order: float
    slippage_pct: float
    days: int
    source: str

    @classmethod
    def of(cls, m):
        pct = m.setting("BROKERAGE_PCT")
        return cls(
            capital=float(m.setting("CAPITAL", 100000)),
            cost_pct=float(m.setting("COST_PCT", 0.02)),
            brokerage_pct=None if pct is None else float(pct),
            brokerage_per_order=float(m.setting("BROKERAGE_PER_ORDER", 20.0)),
            slippage_pct=float(m.setting("SLIPPAGE_PCT", 0.02)),
            days=int(m.setting("BACKTEST_DAYS", 60)),
            source=str(m.setting("BACKTEST_SOURCE", "api")),
        )

    def per_order(self, price, qty):
        """Statutory charges on turnover plus brokerage: a flat fee per order,
        or a percentage capped at that fee when BROKERAGE_PCT is set."""
        turnover = price * qty
        brokerage = self.brokerage_per_order
        if self.brokerage_pct is not None:
            brokerage = min(brokerage, turnover * self.brokerage_pct / 100.0)
        return turnover * self.cost_pct / 100.0 + brokerage


def _reason(m, decision, state):
    if decision.reason == m.risk.BreachReason.STOP:
        moved = state.initial_stop_price is not None and decision.stop_price != (
            state.initial_stop_price
        )
        return "trailing stop" if moved else "stop loss"
    if decision.reason == m.risk.BreachReason.TARGET:
        return "target"
    return decision.reason.value


def _fill_level(m, decision, point, is_open):
    if is_open:
        return point
    if decision.reason == m.risk.BreachReason.STOP:
        return decision.stop_price
    if decision.reason == m.risk.BreachReason.TARGET:
        return decision.target_price
    return point


def lookahead(m, bars):
    """The first bar whose flags change when later bars are added, or None."""
    if len(bars) < 120:
        return None
    full = m.signal_frame(bars)
    for cut in np.linspace(len(bars) * 0.5, len(bars) - 2, 6).astype(int):
        part = m.signal_frame(bars.iloc[: cut + 1]).iloc[-1]
        if not part.equals(full.iloc[cut]):
            return bars.index[cut], dict(part), dict(full.iloc[cut])
    return None


def simulate(m, cfg, costs, bars, sig):
    daily = cfg.interval == "D"
    step = m.interval_step(cfg.interval)
    slip = costs.slippage_pct / 100.0
    trades, curve = [], []
    pos = {"side": None, "qty": 0, "entry": 0.0, "time": None, "risk": None}
    book = {"total": 0.0, "day_pnl": 0.0, "count": 0, "halted": False, "day": None}
    limits0 = m.day_limits(cfg)
    limits = limits0
    pending = None

    def close(price, when, reason):
        side, qty, entry = pos["side"], pos["qty"], pos["entry"]
        sign = 1 if side == "BUY" else -1
        fill = price * (1 - slip) if side == "BUY" else price * (1 + slip)
        gross = sign * (fill - entry) * qty
        cost = costs.per_order(entry, qty) + costs.per_order(fill, qty)
        trades.append(
            {
                "entry_time": pos["time"],
                "exit_time": when,
                "side": "long" if sign > 0 else "short",
                "quantity": qty,
                "entry": round(entry, 2),
                "exit": round(fill, 2),
                "gross_pnl": round(gross, 2),
                "charges": round(cost, 2),
                "net_pnl": round(gross - cost, 2),
                "reason": reason,
            }
        )
        book["total"] += gross - cost
        book["day_pnl"] += gross - cost
        pos.update(side=None, qty=0, entry=0.0, time=None, risk=None)

    def open_(side, price, when):
        entry = price * (1 + slip) if side == "BUY" else price * (1 - slip)
        pos.update(side=side, qty=cfg.quantity, entry=entry, time=when)
        pos["risk"] = m.position_risk(cfg, side, entry, cfg.quantity)
        book["count"] += 1

    for i in range(len(bars)):
        bar, ts = bars.iloc[i], bars.index[i]
        moment = m._aware(ts)
        if book["day"] != moment.date():
            if pending and cfg.square_off and not daily:
                pending = None  # an intraday order never carries into the next session
            book.update(day=moment.date(), day_pnl=0.0, count=0, halted=False)
            limits = limits0
        opening = float(bar["open"])
        if pending and not daily:
            if pending.startswith(("EXIT", "REVERSE")) and pos["side"]:
                close(opening, ts, "exit signal")
            if (pending in ("BUY", "SELL") or pending.startswith("REVERSE")) and not pos["side"]:
                if not book["halted"]:
                    open_(pending.split(":")[-1], opening, ts)
            pending = None
        if not daily and cfg.square_off and moment.time() >= cfg.square_off and pos["side"]:
            close(opening, ts, "square-off time")
        if pos["side"]:
            for n, point in enumerate(_path(bar, pos["side"])):
                before = pos["risk"]
                pos["risk"], decision = m.step_risk(before, point)
                if decision.breached:
                    level = _fill_level(m, decision, point, n == 0)
                    close(level, ts, _reason(m, decision, before))
                    break
                if limits is not None:
                    sign = 1 if pos["side"] == "BUY" else -1
                    open_pnl = sign * (point - pos["entry"]) * pos["qty"]
                    limits, verdict = m.step_day_limits(limits, book["day_pnl"], open_pnl)
                    if verdict.breached:
                        close(point, ts, "daily limit")
                        book["halted"] = True
                        break
        decided_at = moment + (timedelta(0) if daily else step)
        row = sig.iloc[i]
        want = None
        if (pos["side"] == "BUY" and row.long_exit) or (pos["side"] == "SELL" and row.short_exit):
            want = "EXIT"
        if pos["side"] == "BUY" and row.short_entry and m._allowed(cfg, "SELL"):
            want = "REVERSE:SELL"
        elif pos["side"] == "SELL" and row.long_entry and m._allowed(cfg, "BUY"):
            want = "REVERSE:BUY"
        can_enter = (
            not book["halted"]
            and m._in_entry_window(cfg, decided_at)
            and not (cfg.max_trades_per_day and book["count"] >= cfg.max_trades_per_day)
        )
        if pos["side"] is None and can_enter:
            if row.long_entry and m._allowed(cfg, "BUY"):
                want = "BUY"
            elif row.short_entry and m._allowed(cfg, "SELL"):
                want = "SELL"
        if want and want.startswith("REVERSE") and not can_enter:
            want = "EXIT"
        closing = float(bar["close"])
        if daily and want:
            if want.startswith(("EXIT", "REVERSE")) and pos["side"]:
                close(closing, ts, "exit signal")
            if (want in ("BUY", "SELL") or want.startswith("REVERSE")) and not pos["side"]:
                open_(want.split(":")[-1], closing, ts)
        elif want:
            pending = want
        sign = 1 if pos["side"] == "BUY" else -1
        marked = sign * (closing - pos["entry"]) * pos["qty"] if pos["side"] else 0.0
        curve.append((ts, costs.capital + book["total"] + marked, bool(pos["side"])))
    if pos["side"]:
        close(float(bars["close"].iloc[-1]), bars.index[-1], "end of data")
        curve[-1] = (curve[-1][0], costs.capital + book["total"], False)
    equity = pd.DataFrame(curve, columns=["time", "equity", "in_market"]).set_index("time")
    return pd.DataFrame(trades), equity


def report(cfg, costs, bars, trades, equity, start, end, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    trades.to_csv(out / "trades.csv", index=False)
    equity.to_csv(out / "equity.csv")
    values = equity["equity"]
    drawdown = (values / values.cummax() - 1.0).min() * 100 if len(values) else 0.0
    first, last = float(bars["close"].iloc[0]), float(bars["close"].iloc[-1])
    lines = [
        f"Backtest {cfg.name}: {cfg.symbol} {cfg.exchange} {cfg.interval}, {start} to {end}",
        f"  Bars                {len(bars)}",
        f"  Capital             {costs.capital:,.0f}   quantity {cfg.quantity}",
    ]
    if trades.empty:
        lines.append("  Trades              0  (no signal fired in this period)")
    else:
        net = trades["net_pnl"]
        wins, losses = net[net > 0], net[net <= 0]
        factor = wins.sum() / abs(losses.sum()) if losses.sum() else float("inf")
        reasons = ", ".join(f"{k} {v}" for k, v in trades["reason"].value_counts().items())
        lines += [
            f"  Trades              {len(trades)}   won {len(wins)} ({len(wins) / len(trades):.0%})",
            f"  Net P&L             {net.sum():,.2f}   ({net.sum() / costs.capital:+.2%} of capital)",
            f"  Charges paid        {trades['charges'].sum():,.2f}",
            f"  Profit factor       {factor:.2f}",
            f"  Average win / loss  {wins.mean() if len(wins) else 0:,.2f} / "
            f"{losses.mean() if len(losses) else 0:,.2f}",
            f"  Largest loss        {net.min():,.2f}",
            f"  Max drawdown        {drawdown:.2f}%",
            f"  Time in market      {equity['in_market'].mean():.0%} of bars",
            f"  Exits               {reasons}",
        ]
    lines += [
        f"  Buy and hold        {last / first - 1:+.2%} on {cfg.symbol} over the same bars",
        f"  Files               {out / 'trades.csv'}",
        f"                      {out / 'equity.csv'}",
    ]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest an OpenAlgo strategy file")
    parser.add_argument("strategy", type=Path)
    parser.add_argument("--days", type=int, help="this many calendar days back from --to")
    parser.add_argument("--from", dest="start", help="first day, YYYY-MM-DD")
    parser.add_argument("--to", help="last day, YYYY-MM-DD (default today)")
    parser.add_argument("--source", choices=("api", "db"), help="api = broker, db = Historify")
    args = parser.parse_args()
    path = args.strategy.resolve()

    os.environ.update(_host.strategy_env({"STRATEGY_NAME": ""}))
    os.environ.pop("STRATEGY_NAME", None)
    sys.argv = [str(path)]
    m = _host.load_strategy(path)
    m._setup_logging()
    if getattr(m, "NO_BACKTEST_REASON", None):
        print(m.NO_BACKTEST_REASON)
        return 2
    if not callable(getattr(m, "signals", None)):
        print("This file has no signals(df), so there is nothing to backtest.")
        return 2
    cfg = m.load_config()
    costs = Costs.of(m)
    client = m.connect()
    try:
        cfg = m.prepare(client, cfg)
        end = datetime.strptime(args.to, "%Y-%m-%d").date() if args.to else m.now_ist().date()
        start = (
            datetime.strptime(args.start, "%Y-%m-%d").date()
            if args.start
            else end - timedelta(days=args.days or costs.days)
        )
        source = args.source or costs.source
        raw = m.history(client, cfg, start, end, source=source)
    finally:
        client.close()
    if raw is None or len(raw) < 30:
        print(
            f"Not enough history for {cfg.symbol} {cfg.interval} from {start} to {end} "
            f"({'Historify' if source == 'db' else 'broker'} data). Try fewer days, another "
            "interval, or --source db after downloading the symbol in Historify."
        )
        return 1
    bars = m.closed_bars(raw, cfg.interval, m.now_ist(), cfg.exchange)
    found = lookahead(m, bars)
    sig = m.signal_frame(bars)
    trades, equity = simulate(m, cfg, costs, bars, sig)
    print(report(cfg, costs, bars, trades, equity, start, end, path.parent / "backtest"))
    if found:
        stamp, short, full = found
        print(
            f"\nLOOKAHEAD: the flags on the {stamp} bar change when later bars are added "
            f"({short} with history up to that bar, {full} with all of it). signals() reads "
            "future bars, so these results cannot be reproduced live. Fix it before trusting them."
        )
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
