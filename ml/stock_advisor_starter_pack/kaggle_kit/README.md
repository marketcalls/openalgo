# Kaggle Kit

This folder contains a Kaggle-ready scaffold for offline experimentation.

## Contents

- `dataset_template/`: upload-ready structure for market data, strategies, and config
- `notebooks/`: notebook skeletons to run in order
- `exports/`: expected folder structure for exported bundles and reports

## Usage

1. Copy your prepared data into `dataset_template/market_data/`.
2. Copy the strategy files you want to ship into `dataset_template/strategies/`.
3. Upload the dataset as a private Kaggle dataset.
4. Paste the notebook skeletons into Kaggle notebooks and adjust input paths from `/kaggle/input/...`.
5. Download exported bundles and move them into your local candidate model folder.
