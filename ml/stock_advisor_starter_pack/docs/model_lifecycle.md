# Model Lifecycle

## States

- `draft`: training artifacts still being assembled
- `candidate`: trained and evaluated, waiting for review
- `active`: approved for paper-trade inference
- `archived`: kept for audit or rollback reference

## Recommended Lifecycle

1. Train a candidate model.
2. Run validation and walk-forward checks.
3. Store the bundle under `models/candidate/`.
4. Review the promotion report.
5. Move the approved model to `models/active/`.
6. Archive superseded models instead of deleting them.

## Approval Checklist

- positive expectancy after costs
- reasonable drawdown
- stable confidence calibration
- no schema drift between training and inference
- better paper-trade or holdout results than the current active bundle
