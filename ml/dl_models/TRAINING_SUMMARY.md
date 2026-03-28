# AAUM DL Model Training — Colab Session Summary (2026-03-28)

## What Was Done
Trained 7 ML/DL models on Google Colab (Tesla T4 GPU) for AAUM stock direction prediction (UP/DOWN/FLAT).

### Models Trained
| Model | Type | File | Size |
|-------|------|------|------|
| XGBoost | ML (tree) | xgboost_model.joblib | 2.6 MB |
| LightGBM | ML (tree) | lightgbm_model.joblib | 10.1 MB |
| RandomForest | ML (tree) | randomforest_model.joblib | 53.2 MB |
| CatBoost | ML (tree) | catboost_model.cbm | 942 KB |
| LSTM | DL (recurrent) | lstm_model.pt | 865 KB |
| 1D-CNN | DL (convolutional) | cnn_model.pt | 223 KB |
| Transformer | DL (attention) | transformer_model.pt | 467 KB |

### Supporting Files
| File | Purpose |
|------|---------|
| scaler.joblib | StandardScaler fitted on training data |
| feature_columns.json | 26 feature column names |
| features.csv | Full feature matrix (46,143 rows, 96 stocks) |
| model_comparison.json | ML model metrics |
| training_report.json | Full training metadata |
| model_comparison.png | Visual comparison chart |
| best_model_confusion_matrix.png | Confusion matrix of best model |

### All files location: `C:\Users\sakth\Desktop\aaum\data\models\`

---

## Training Data
- **Source**: HSTRY 1h CSVs (96 NSE stocks), resampled to daily
- **Predictions**: 46,143 unique (symbol, date) pairs from backtest
- **Features**: 26 technical indicators (RSI, MACD, BB, EMA, ATR, volume, returns, etc.)
- **Labels**: UP (0) = 47.7%, DOWN (1) = 41.0%, FLAT (2) = 11.3%
- **Train/Test split**: Train ≤ 2022-12-31 / Test ≥ 2023-01-01
- **Train**: 178,008 rows / **Test**: 76,608 rows

## DL Architecture Details

### LSTM
- 2-layer LSTM, hidden=128, dropout=0.3
- FC: 128→64→ReLU→Dropout(0.2)→3
- Input: (batch, 30, 26) sliding window

### 1D-CNN
- 3 Conv1d layers: channels→64→128→64, kernel=3
- BatchNorm before ReLU (Conv→BN→ReLU order)
- AdaptiveAvgPool1d(1) → FC→3

### Transformer
- Linear projection to d_model=64, nhead=4, 2 encoder layers
- Learnable positional encoding (max_win=200)
- Embedding scaling: sqrt(d_model)
- FC: 64→32→ReLU→3

### Training Config
- Optimizer: Adam (lr=0.001, weight_decay=1e-5)
- Scheduler: ReduceLROnPlateau (factor=0.5, patience=5)
- Loss: CrossEntropyLoss with balanced class weights
- Early stopping: patience=10
- Batch size: 256
- Max epochs: 50
- Gradient clipping: max_norm=1.0
- Sliding window: 30 trading days

---

## Current Performance (NOT production ready)

| Model | Accuracy | F1 |
|-------|----------|-----|
| XGBoost | 36.1% | 0.316 |
| LightGBM | 36.2% | 0.333 |
| RandomForest | 36.2% | 0.320 |
| CatBoost | 36.1% | 0.313 |
| LSTM | Best DL | (see Colab output) |
| 1D-CNN | DL | (see Colab output) |
| Transformer | DL | (see Colab output) |

**Random baseline (3-class) = 33%.** Models are ~36% — barely above random.

---

## What Needs Improvement to Reach Production (target >45% accuracy)

### Feature Engineering
1. **Market microstructure**: bid-ask spread, open interest, delivery %
2. **Sector/index relative strength**: stock vs Nifty50 ratio
3. **Macro features**: VIX, FII/DII flows, USD/INR
4. **Order flow**: buy/sell volume imbalance
5. **Cross-stock features**: sector momentum, correlation regime

### Model Improvements
1. **Ensemble voting** across all 7 models (not single best)
2. **Reduce to 2-class** (UP vs DOWN, drop FLAT) — easier, more actionable
3. **Confidence threshold** — only trade when model >60% confident
4. **Per-stock model selection** — different stocks may suit different models
5. **Walk-forward validation** instead of single train/test split

### Data Improvements
1. Add more stocks (currently 96)
2. Use intraday features (15m/1h bars) not just daily
3. Add alternative data (news sentiment, social media)
4. Longer training history

---

## Colab Notebook Fixes Applied
These bugs were fixed during the session:

1. `torch.cuda.get_device_properties(0).total_mem` → `.total_memory`
2. `dir()` → `globals()` for variable existence checks in notebooks
3. CNN BatchNorm order: `Conv→ReLU→BN` → `Conv→BN→ReLU`
4. Transformer positional encoding: hardcoded 100 → `max_win=200` parameter
5. Transformer: added `sqrt(d_model)` embedding scaling
6. `class_weight_dict` keys: numpy int64 → Python int (silent `.get()` failure)
7. `d_model % nhead == 0` assertion added
8. Missing imports in Cells 6-9: `confusion_matrix`, `datetime`
9. Drive re-mount needed at Cell 5 (disconnects after long Cell 2 compute)
10. Variable recovery guards for `MODELS_DIR`, `scaler`, `y_train`, `test_df`

## Notebook Cell Structure
| Cell | Purpose | Time |
|------|---------|------|
| 1 | Setup, mount Drive, load HSTRY CSVs | ~2 min |
| 2 | Feature engineering (25+ technicals per prediction) | ~65 min |
| 3 | Train/test split, scaler, class weights | ~10 sec |
| 4 | Train 4 ML models (XGB, LGBM, RF, CatBoost) | ~2 min |
| 5 | Train 3 DL models (LSTM, CNN, Transformer) on GPU | ~5 min |
| 6 | Compare all 7 models, charts | ~10 sec |
| 7 | Per-stock model performance | ~10 sec |
| 8 | Feature importance analysis | ~10 sec |
| 9 | Export all models & artifacts to Drive | ~10 sec |

## Google Drive Path
`MyDrive/aaum_trained_models/`

## Local Path (after download)
`C:\Users\sakth\Desktop\aaum\data\models\`
