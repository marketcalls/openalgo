# Kaggle Handoff for Opus + Playwright

Use this file as the operator handoff when you want a browser agent to run the Kaggle flow.

## Goal

Train or validate the RELIANCE swing starter bundle on Kaggle using the dataset and notebook sequence in this repo.

## Inputs

- dataset template: `kaggle_kit/dataset_template/`
- notebooks:
  - `01_prepare_data.ipynb`
  - `02_build_features.ipynb`
  - `03_train_models.ipynb`
  - `04_validate_backtest.ipynb`
  - `05_export_bundle.ipynb`

## Rules

- treat `D:\test1` as source code, not a package install requirement
- keep strategy files read-only
- export the final bundle and reports for local manual review
- do not assume live trading or broker execution is part of Kaggle

## Expected Outputs

- candidate model bundle
- feature schema
- validation reports
- top setup summary
