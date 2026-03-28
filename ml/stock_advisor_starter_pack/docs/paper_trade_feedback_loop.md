# Paper Trade Feedback Loop

## Goal

Use paper-trade outcomes to improve the model without risking capital.

## Daily Cycle

1. Generate recommendations during market hours.
2. Route them into the paper-trade app.
3. Export completed and rejected trade logs after market close.
4. Ingest the logs into the feedback store.
5. Rebuild training tables with feedback weighting.
6. Retrain candidate models.
7. Compare candidate versus active performance.
8. Manually approve or reject promotion.

## Minimum Feedback Fields

- recommendation id
- symbol
- horizon
- model version
- side
- entry time and price
- exit time and price
- quantity
- gross and net PnL
- stop loss / target hit flags
- manual reject flag and optional reject reason

## Safety Rule

Paper-trade feedback should never auto-promote a model. Promotion remains a manual review step.
