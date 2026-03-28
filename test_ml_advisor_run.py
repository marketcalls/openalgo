
import sys
import os
import json
from pathlib import Path

# 1. Setup paths to the ML project
ML_PROJECT_ROOT = Path("ml/stock_advisor_starter_pack/local_project").resolve()
SRC_PATH = ML_PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

# 2. Setup paths to OpenAlgo blueprints
sys.path.insert(0, str(Path(".").resolve()))

print("\n🚀 [INTELLIGENCE NODE] INITIALIZING ML RECOMMENDATION...")

try:
    # Import the inference logic
    from inference.generate_reliance_swing_recommendation import generate_reliance_swing_recommendation
    from blueprints.ml_advisor import calculate_risk_score
    
    # Define the config path
    config_path = ML_PROJECT_ROOT / "configs" / "reliance_swing.yaml"
    
    # 3. RUN INFERENCE
    print(f"📊 Running model for RELIANCE (15m Swing)...")
    result = generate_reliance_swing_recommendation(config_path)
    
    # 4. LOAD & PROCESS RECOMMENDATION
    output_path = Path(result["output_path"])
    rec_data = json.loads(output_path.read_text())
    
    # 5. RUN RISK MODERATOR (VETO NODE)
    risk_assessment = calculate_risk_score(rec_data)
    
    # 6. DISPLAY DASHBOARD DATA (SIMULATION)
    print("\n" + "="*50)
    print("      OPENALGO ML ADVISOR - COMMAND CENTER      ")
    print("="*50)
    print(f"SYMBOL:      RELIANCE")
    print(f"ACTION:      {rec_data['strategy_combo'][0].upper()}")
    print(f"REGIME:      {rec_data['regime'].upper()} (Confirmed)")
    print("-" * 50)
    print(f"ENTRY:       {rec_data['entry']:.2f}")
    print(f"TARGET 1:    {rec_data['target_1']:.2f} (Profit Level 1)")
    print(f"TARGET 2:    {rec_data['target_2']:.2f} (Profit Level 2)")
    print(f"STOP LOSS:   {rec_data['stop_loss']:.2f} (Risk Control)")
    print("-" * 50)
    print(f"CONFIDENCE:  {(rec_data['confidence']*100):.1f}%")
    print(f"SURVIVAL:    {risk_assessment['score']}/100")
    print(f"RISK STATUS: {risk_assessment['status']}")
    
    if risk_assessment['vetoes']:
        print("\n🚫 VETO TRIGGERS DETECTED:")
        for v in risk_assessment['vetoes']:
            print(f"  - {v}")
    
    print("="*50)
    print(f"LOG: Generated recommendation id: {rec_data['recommendation_id']}")
    print("STATUS: Intelligence Plane Operational ✅")

except Exception as e:
    print(f"\n❌ ERROR RUNNING INTELLIGENCE NODE: {e}")
    import traceback
    traceback.print_exc()
