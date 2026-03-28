# Kaggle Workflow

## Suitable Use Cases

Kaggle is appropriate for:

- Excel and CSV cleanup
- historical feature engineering
- model training
- backtesting and validation
- bundle export

Kaggle is not appropriate for:

- live paper-trade serving
- broker integration
- intraday production inference

## Suggested Order

1. Upload the dataset template as a private dataset.
2. Run `01_prepare_data.ipynb`.
3. Run `02_build_features.ipynb`.
4. Run `03_train_models.ipynb`.
5. Run `04_validate_backtest.ipynb`.
6. Run `05_export_bundle.ipynb`.

## Export Rule

Only export bundles that passed validation. Move the downloaded bundle into the local candidate folder for manual review.

## Opus + Playwright Note

If you use Opus with Playwright to operate Kaggle:

- upload the dataset template from `kaggle_kit/dataset_template/`
- run the notebooks in order
- export the trained bundle and reports
- move the bundle into `artifacts_template/models/candidate/` for local review

The model logic stays in this starter pack. Opus and Playwright are the notebook operator, not the training codebase.
