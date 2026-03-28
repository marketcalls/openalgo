"""
ML Advisor Service - The Intelligence Node
Wraps the ML Bundle execution and provides institutional-grade risk scoring.
"""

import sys
import os
import json
import logging
from pathlib import Path
from flask import Blueprint, jsonify, request, current_app
from database.historify_db import get_ohlcv
from utils.session import check_session_validity

# --- ML Project Integration ---
# Dynamically add the ML project to the Python path
ML_PROJECT_ROOT = Path("ml/stock_advisor_starter_pack/local_project").resolve()
SRC_PATH = ML_PROJECT_ROOT / "src"

if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# Now we can import from your ML project
try:
    from inference.generate_reliance_swing_recommendation import generate_reliance_swing_recommendation
except ImportError as e:
    logging.error(f"Failed to import ML module: {e}")

# Create Blueprint
ml_advisor_bp = Blueprint("ml_advisor_bp", __name__, url_prefix="/api/ml")
logger = logging.getLogger(__name__)

# --- Risk Moderator Logic (Lite Version) ---
def calculate_risk_score(recommendation):
    """
    Implements a simplified version of the 'RiskModerator' logic.
    Returns a Survival Score (0-100) and a Veto Status.
    """
    score = 100
    vetoes = []
    
    # 1. R:R Ratio Check (Tactical Execution)
    entry = recommendation.get("entry", 0)
    stop_loss = recommendation.get("stop_loss", 0)
    target_1 = recommendation.get("target_1", 0)
    
    if entry > 0 and stop_loss > 0:
        risk = abs(entry - stop_loss)
        reward = abs(target_1 - entry)
        rr_ratio = reward / risk if risk > 0 else 0
        
        if rr_ratio < 1.5:
            score -= 20
            vetoes.append(f"Low R:R Ratio ({rr_ratio:.2f} < 1.5)")
        if rr_ratio < 1.0:
            score -= 30
            vetoes.append("Negative Expectancy (R:R < 1)")
            
    # 2. Confidence Check (Model Quality)
    confidence = recommendation.get("confidence", 0.5)
    if confidence < 0.60:
        score -= 25
        vetoes.append("Low Model Confidence (< 60%)")
        
    # 3. Market Regime Penalty (Context)
    # If the regime is '0' (Bearish/Neutral) but signal is LONG, penalize
    regime = recommendation.get("regime", "0")
    side = "LONG" if target_1 > entry else "SHORT"
    
    if regime == "0" and side == "LONG":
        score -= 15
        vetoes.append("Contrarian Trade (Long in Bear Regime)")

    return {
        "score": max(0, score),
        "status": "APPROVED" if score >= 70 else "REJECTED" if score < 40 else "WARNING",
        "vetoes": vetoes
    }

@ml_advisor_bp.route("/recommend/<symbol>")
@check_session_validity
def get_recommendation(symbol):
    """
    Generates a fresh recommendation for the symbol using the ML bundle.
    """
    try:
        # 1. Configuration (In a real system, this comes from a config file/DB)
        # We point to the specific config file for RELIANCE provided in your ML pack
        config_path = ML_PROJECT_ROOT / "configs" / f"{symbol.lower()}_swing.yaml"
        
        if not config_path.exists():
            return jsonify({
                "status": "error",
                "message": f"No ML configuration found for {symbol}. Only RELIANCE is currently supported."
            }), 404

        # 2. Run Inference (The Intelligence Node)
        # This calls your code which loads the bundle, builds artifacts, and predicts
        logger.info(f"Running ML inference for {symbol}...")
        result = generate_reliance_swing_recommendation(config_path)
        
        # 3. Load the output JSON
        # Your function returns the path to the JSON output
        output_path = Path(result["output_path"])
        if not output_path.exists():
             return jsonify({"status": "error", "message": "ML Inference failed to produce output."}), 500
             
        recommendation_data = json.loads(output_path.read_text(encoding="utf-8"))
        
        # 4. Apply Risk Moderator (The Veto Node)
        risk_assessment = calculate_risk_score(recommendation_data)
        
        # 5. Construct Final Response (The Display Plane Contract)
        response = {
            "symbol": symbol.upper(),
            "model_version": recommendation_data.get("model_version", "unknown"),
            "timestamp": result.get("timestamp", ""),
            "trade_intent": {
                "action": "BUY" if recommendation_data["target_1"] > recommendation_data["entry"] else "SELL",
                "entry": recommendation_data["entry"],
                "stop_loss": recommendation_data["stop_loss"],
                "target_1": recommendation_data["target_1"],
                "target_2": recommendation_data["target_2"],
                "confidence": recommendation_data["confidence"]
            },
            "intelligence": {
                "market_regime": recommendation_data.get("regime", "Unknown"),
                "strategy_logic": recommendation_data.get("reason_codes", []),
                "parameters": recommendation_data.get("parameters", {})
            },
            "risk_moderator": risk_assessment
        }
        
        return jsonify({"status": "success", "data": response})

    except Exception as e:
        logger.exception(f"ML Advisor Error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@ml_advisor_bp.route("/bundles")
@check_session_validity
def list_bundles():
    """List available ML model bundles"""
    try:
        models_dir = Path("ml/stock_advisor_starter_pack/artifacts_template/models/candidate")
        if not models_dir.exists():
            return jsonify({"status": "success", "data": []})
            
        bundles = [d.name for d in models_dir.iterdir() if d.is_dir()]
        return jsonify({"status": "success", "data": sorted(bundles, reverse=True)})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500
