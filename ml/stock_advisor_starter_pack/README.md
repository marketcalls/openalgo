# Stock Advisor Starter Pack

This starter pack is a reusable foundation for building a stock advisory system that:

- prepares Excel, CSV, and Parquet market data
- wraps read-only strategy files from `D:\test1`
- builds features and labels for historical training
- trains regime and setup-ranking starter models
- exports model bundles for paper-trade inference
- ingests paper-trade feedback for daily retraining
- supports an offline Kaggle workflow for experimentation

It assumes `D:\test1` is a local source-code workspace, not just a flat strategy folder. That means:

- top-level strategy files are wrapped as read-only strategies
- local source trees under `D:\test1\opensource_indicators\` can be imported directly
- the project does not rely on `pip install` for those cloned indicator libraries

## Pack Layout

- `docs/`: operator guides and design notes
- `local_project/`: local code scaffold for training, validation, inference, and feedback loops
- `kaggle_kit/`: dataset templates and notebook skeletons for Kaggle workflows
- `artifacts_template/`: expected output layout for models, reports, logs, and feature stores

## Recommended Workflow

1. Place historical data into the canonical schema described in `docs/data_requirements.md`.
2. Use the scripts in `local_project/scripts/` to prepare data and build starter training tables.
3. Train the regime model and setup ranker locally or in Kaggle.
4. Export an approved model bundle into `artifacts_template/models/active/`.
5. Use the inference modules to create recommendations for your paper-trade app.
6. Export paper-trade logs from the app and ingest them with the feedback pipeline.
7. Review the promotion report before activating a new candidate model.

## First Target

The included examples are RELIANCE-first so the scaffold is usable immediately with:

- source data: `D:\TV_proj\output\reliance_timeframes`
- read-only strategies: `D:\test1`

The structure is intended to scale to more symbols once additional data is available.

## Local Quick Start

```powershell
cd D:\ml\stock_advisor_starter_pack\local_project
.\scripts\run_prepare.ps1
.\scripts\run_train_regime.ps1
.\scripts\run_train_setup.ps1
.\scripts\run_validate.ps1
.\scripts\run_train_reliance_swing.ps1
.\scripts\run_recommend_reliance_swing.ps1
.\scripts\run_export_source_catalog.ps1
python -m pytest -q
```

## Kaggle Quick Start

1. Upload the `kaggle_kit/dataset_template/` contents as a private Kaggle dataset.
2. Copy the notebook skeletons from `kaggle_kit/notebooks/`.
3. Run the notebooks in order from `01_prepare_data.ipynb` to `05_export_bundle.ipynb`.
4. Download the exported bundle and place it under `artifacts_template/models/candidate/` for review.
