$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$env:PYTHONPATH = Join-Path $root "src"
python -c "import pandas as pd; from features.build_regime_features import build_regime_features; from labels.build_regime_labels import build_regime_labels; from models.train_regime_model import train_regime_model; from models.evaluate_walk_forward import evaluate_simple_walk_forward; df=pd.read_csv(r'$root\\examples\\sample_market_data.csv'); features=build_regime_features(df); labeled=build_regime_labels(features); model, cols=train_regime_model(df); labeled['prediction']=model.predict(labeled[cols]); print(evaluate_simple_walk_forward(labeled, 'regime_label', 'prediction'))"
