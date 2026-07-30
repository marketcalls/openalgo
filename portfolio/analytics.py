"""
Investor-facing analytics: correlation, diversification, and the metric summary.

Formulas that openstatz owns are delegated to it rather than reimplemented, so
a number shown here cannot drift from the same number shown in a tearsheet.
What lives here is the portfolio-shaped analysis openstatz does not cover:
how holdings move together, whether the portfolio is diversified in substance
rather than in name, and how it behaves in up markets versus down ones.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def correlation_matrix(returns: pd.DataFrame, min_overlap: int = 20) -> pd.DataFrame:
    """
    Pairwise correlation of holding returns — the heatmap's data.

    Pairs with fewer than ``min_overlap`` common observations come back NaN
    rather than as a number: a correlation computed from a handful of sessions
    is noise, and rendering it as a confident colour in a heatmap is worse than
    rendering a gap.
    """
    if returns.shape[1] == 0:
        return pd.DataFrame()
    corr = returns.corr(min_periods=min_overlap)
    return corr


def average_pairwise_correlation(returns: pd.DataFrame) -> float:
    """
    Mean of the off-diagonal correlations.

    The single most useful diversification number: a portfolio of ten holdings
    that all move together is one bet wearing ten names, and weight-based
    measures like HHI cannot see that.
    """
    if returns.shape[1] < 2:
        return float("nan")
    corr = returns.corr().to_numpy()
    upper = corr[np.triu_indices_from(corr, k=1)]
    upper = upper[~np.isnan(upper)]
    return float(upper.mean()) if upper.size else float("nan")


def concentration(weights: dict[str, float] | pd.Series) -> dict[str, float]:
    """
    Herfindahl-Hirschman concentration of the weights.

    ``effective_holdings`` (1/HHI) is the headline: it answers "how many
    holdings is this portfolio really", so 20 names with one at 80% correctly
    reports about 1.5 rather than 20.
    """
    w = pd.Series(weights, dtype=float)
    total = w.sum()
    if total <= 0:
        raise ValueError("weights sum to zero")
    w = w / total
    hhi = float((w**2).sum())
    return {
        "hhi": hhi,
        "effective_holdings": float(1.0 / hhi),
        "largest_weight": float(w.max()),
        "holdings": int(len(w)),
    }


def diversification_ratio(weights: pd.Series, returns: pd.DataFrame) -> float:
    """
    Weighted average of holding volatilities divided by portfolio volatility.

    1.0 means the holdings gave no diversification at all; higher is better.
    Unlike HHI this uses actual co-movement, so it distinguishes ten banks from
    ten unrelated businesses even at identical weights.
    """
    common = [c for c in returns.columns if c in weights.index]
    if len(common) < 2:
        return float("nan")
    w = weights[common].to_numpy(dtype=float)
    w = w / w.sum()
    cov = returns[common].cov().to_numpy() * TRADING_DAYS
    port_vol = float(np.sqrt(w @ cov @ w))
    if port_vol <= 0:
        return float("nan")
    weighted_vol = float(w @ np.sqrt(np.diag(cov)))
    return weighted_vol / port_vol


def capture_ratios(returns: pd.Series, benchmark: pd.Series) -> dict[str, float]:
    """
    Up- and down-market capture against a benchmark.

    Not in openstatz, and one of the few numbers that tells an investor what
    they actually want to know: how much of the market's gains this portfolio
    caught, and how much of its losses it took. Up 90 / down 60 is a very
    different product from up 110 / down 115 even at identical CAGR.

    Computed as the ratio of *mean* returns over the up and down sessions, not
    of compounded ones. Compounding only the sessions that went one way
    diverges with the length of the window -- over five years a benchmark's
    up-days-only product reaches five figures, and every ratio against it
    collapses toward zero regardless of how the portfolio actually behaved.
    The mean-ratio form is scale-stable and is what fund analysts report.
    """
    joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
    if joined.empty:
        return {"up_capture": float("nan"), "down_capture": float("nan")}
    port, bench = joined.iloc[:, 0], joined.iloc[:, 1]

    def _capture(mask: pd.Series) -> float:
        if not mask.any():
            return float("nan")
        b = float(bench[mask].mean())
        if b == 0:
            return float("nan")
        return float(port[mask].mean()) / b

    return {
        "up_capture": _capture(bench > 0),
        "down_capture": _capture(bench < 0),
    }


def summary(
    returns: pd.Series,
    benchmark: pd.Series | None = None,
    *,
    rf: float = 0.0,
) -> dict[str, float]:
    """
    The headline metrics, delegated to openstatz so the formulas stay in one
    place. Benchmark-relative figures are omitted rather than faked when no
    benchmark is supplied.

    openstatz is imported lazily: it pulls matplotlib and scipy, and a caller
    that only wants an equity curve should not pay for them.
    """
    import openstatz.stats as st

    out: dict[str, float] = {
        "cagr": float(st.cagr(returns, rf=rf)),
        "volatility": float(st.volatility(returns)),
        "sharpe": float(st.sharpe(returns, rf=rf)),
        "sortino": float(st.sortino(returns, rf=rf)),
        "calmar": float(st.calmar(returns)),
        "max_drawdown": float(st.max_drawdown((1.0 + returns).cumprod())),
        "win_rate": float(st.win_rate(returns)),
        "best_day": float(st.best(returns)),
        "worst_day": float(st.worst(returns)),
        "value_at_risk": float(st.value_at_risk(returns)),
        "cvar": float(st.conditional_value_at_risk(returns)),
        "ulcer_index": float(st.ulcer_index(returns)),
        "recovery_factor": float(st.recovery_factor(returns)),
        "tail_ratio": float(st.tail_ratio(returns)),
        "skew": float(st.skew(returns)),
        "kurtosis": float(st.kurtosis(returns)),
    }

    if benchmark is not None and len(benchmark) > 0:
        joined = pd.concat([returns, benchmark], axis=1, join="inner").dropna()
        if not joined.empty:
            port, bench = joined.iloc[:, 0], joined.iloc[:, 1]
            greeks = st.greeks(port, bench)
            out["alpha"] = float(greeks["alpha"])
            out["beta"] = float(greeks["beta"])
            out["information_ratio"] = float(st.information_ratio(port, bench))
            out["benchmark_cagr"] = float(st.cagr(bench, rf=rf))
            out["excess_cagr"] = out["cagr"] - out["benchmark_cagr"]
            out.update(capture_ratios(port, bench))
    return out
