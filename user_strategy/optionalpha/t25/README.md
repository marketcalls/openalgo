# OptionsAlpha 25 Strategy

## Quick Commands

### Run Strategy
```bash
strategy_25
# or manually:
cd /Users/sadhanandhann/Code/4 openalgo_v2/openalgo_dhan/user_strategy/optionalpha/t25
../run_strategy.sh optionalpha_25.py
```

### Unlock Files (before editing)
```bash
chmod -R u+w /Users/sadhanandhann/Code/4 openalgo_v2/openalgo_dhan/user_strategy/optionalpha/t25/
```

### Lock Files (after editing)
```bash
chmod -R a-w /Users/sadhanandhann/Code/4 openalgo_v2/openalgo_dhan/user_strategy/optionalpha/t25/
```

### Commit Changes
```bash
cd /Users/sadhanandhann/Code/4 openalgo_v2/openalgo_dhan
git add user_strategy/optionalpha/t25/
git commit -m "update optionalpha_25 strategy"
```

## Current Config

| Parameter | Value |
|-----------|-------|
| Target | 25 pts |
| Stop Loss | 8 pts |
| Breakeven | 20 pts |
| Lock Profit | OFF |
| Max Trades/Day | 2 |
| Max Daily Loss | 15% of initial capital |
| Capital | 95% of available (capped at 5L) |
| Entry Cutoff | 14:15 |
| Force Exit | 14:59 |

## Files

| File | Purpose |
|------|---------|
| `optionalpha_25.py` | Main strategy (NIFTY, synthetic future ATM) |
| `nifty_optionsalpha.py` | Alternate version |
| `run_strategy.sh` | Runner script (unsets SSL env vars for macOS) |
| `optionalpha_performance.xlsx` | Auto-generated trade log |
| `logs/` | Daily strategy logs |
