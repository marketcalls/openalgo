# Training Guide

## Where To Train

Use a separate training environment from the live paper-trade app. This can be:

- local machine in `local_project/`
- Kaggle notebooks using `kaggle_kit/`

Do not retrain inside the live inference loop.

## What Is Needed

- canonical OHLCV data with `symbol` and `timeframe`
- strategy source files from `D:\test1`
- configuration for horizons, costs, and strategies
- historical labels for regime and setup outcomes
- later, paper-trade feedback for continuous learning

## Training Steps

1. Prepare and clean market data.
2. Build strategy features and regime features.
3. Create regime labels and setup labels.
4. Train the starter regime model.
5. Train the starter setup ranker.
6. Calibrate recommendation confidence.
7. Evaluate on a chronological holdout.
8. Export the bundle for staging or paper trading.

## Outputs

Each training run should produce:

- saved model objects
- feature schema
- model metadata
- validation metrics
- walk-forward report
- top setup report
