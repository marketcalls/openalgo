# System Overview

## Purpose

This project is a reusable starter pack for a paper-trading advisory system that combines:

- multi-timeframe market data
- wrapped indicator and strategy outputs
- regime classification
- setup ranking
- risk-aware trade-plan generation
- feedback learning from paper-trade outcomes

## Operating Model

The system is split into two lanes:

- Offline research lane:
  - data preparation
  - feature engineering
  - training and validation
  - model bundle export
- Online advisory lane:
  - load approved model bundle
  - compute fresh features
  - classify market regime
  - rank candidate setups
  - emit paper-trade recommendations
  - log outcomes for retraining

## Core Entities

- `StrategyWrapper`: standard interface over a read-only strategy module
- `StrategyRunResult`: normalized output containing signal, confidence, and raw columns
- `Recommendation`: inference output passed to a paper-trade app
- `PaperTradeRecord`: executed or rejected paper-trade feedback
- `ModelBundleMetadata`: version and provenance metadata for a trained bundle

## Intended Rollout

1. Prototype with one stock and one horizon.
2. Validate on walk-forward historical data.
3. Run paper trading without real capital.
4. Ingest feedback and retrain daily.
5. Promote only manually approved candidate models.

## Local Source Libraries

The project treats `D:\test1` as a source workspace. This lets you:

- keep custom strategy files at the top level
- clone open-source indicator libraries under `D:\test1\opensource_indicators\`
- extend wrappers later without package-manager installs
