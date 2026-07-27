# backtests/

Backtest runs and their results.

Keep the strategy definition alongside its results so a number is always
traceable to the code that produced it. Record the data range and symbol set —
a return figure without them is not reproducible.

Watch for lookahead bias: if a signal uses a bar that had not closed, the
backtest is measuring hindsight rather than edge. The `custom-indicator`
skill documents a test for it.
