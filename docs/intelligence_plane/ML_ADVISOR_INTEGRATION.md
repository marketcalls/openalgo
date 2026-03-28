# ML Advisor Integration Report (v2.1)
**Project Title**: OpenAlgo Intelligence Plane (ML Advisor)
**Architecture Style**: Hub-and-Spoke (Institutional-Grade Intelligence Node)
**Target Market**: Indian Equities (RELIANCE Swing Bundle)

---

## 1. Executive Summary
This project integrates an **Intelligence Plane** into OpenAlgo, allowing for machine-learning-driven trade recommendations combined with an institutional **Risk Moderator** (Veto Layer). It transitions OpenAlgo from a "Signal Receiver" to a "Strategic Intelligence Platform."

---

## 2. New Dependencies (Intelligence Plane Core)
The following Python packages were installed to support high-performance ML inference:

| Package | Version | Location | Purpose |
| :--- | :--- | :--- | :--- |
| `lightgbm` | >= 4.0 | `.venv/Lib/site-packages` | Gradient Boosting framework for running the model bundles. |
| `mlflow` | >= 3.0 | `.venv/Lib/site-packages` | Model lifecycle management for loading artifacts/metadata. |
| `scikit-learn` | >= 1.4 | `.venv/Lib/site-packages` | Machine learning tools for feature engineering and calibration. |
| `optuna` | >= 3.0 | `.venv/Lib/site-packages` | Hyperparameter optimization support for the models. |

---

## 3. Backend: The Intelligence Node
**File**: `blueprints/ml_advisor.py` (New File)
**Lines**: ~140 lines of Python code.
**Purpose**: Acts as the "Thinking Brain."
- **System Pathing**: Dynamically adds `ml/stock_advisor_starter_pack/local_project/src` to `sys.path` to allow imports from the user's ML project.
- **Inference Gateway**: Calls `generate_reliance_swing_recommendation` from the ML pack.
- **Risk Moderator (Veto Logic)**: 
    - **Logic**: Implements a survival score (0-100).
    - **Vetoes**: Automatically penalizes low R:R trades (< 1.5), low confidence signals (< 60%), and contrarian regime trades (Long in Bear market).
- **Endpoint**: `GET /api/ml/recommend/<symbol>` returns a standardized `TradeIntent` JSON.

**File Update**: `app.py`
- **Lines**: Registered `ml_advisor_bp` and imported it into the Flask application.
- **Purpose**: Exposes the ML API to the frontend and ensures it respects OpenAlgo's session security.

---

## 4. Frontend: The Display Plane
**File**: `frontend/src/pages/MLAdvisor.tsx` (New File)
**Lines**: ~250 lines of React/TypeScript.
**Purpose**: Acts as the "Command Center."
- **Interactive Controls**: Allows the trader to select a symbol (currently RELIANCE) and trigger "Run Analytics."
- **TradingView Integration**: Uses `lightweight-charts` to draw **Live ML Overlays**:
    - 🔵 **Entry (Dashed)**: Optimal entry level.
    - 🟢 **Target 1 & 2 (Solid)**: Profit-taking levels.
    - 🔴 **Stop Loss (Solid)**: The invalidation point.
- **Intelligence Dashboard**: 
    - **Survival Score**: Shows the Risk Moderator's verdict (Approved/Rejected).
    - **Confidence Bar**: Visual progress bar for model strength.
    - **Market Regime**: High-visibility card showing current regime (e.g., "Swing Bullish").

**File Update**: `frontend/src/App.tsx`
- **Lines**: Added lazy import for `MLAdvisor` and defined the route `/ml-advisor`.
- **Purpose**: Enables the React SPA (Single Page Application) to navigate to the new dashboard.

**File Update**: `frontend/src/config/navigation.ts`
- **Lines**: Imported `Brain` icon from `lucide-react` and added a new entry to `profileMenuItems`.
- **Purpose**: Adds the "ML Advisor" link to the sidebar/drawer for easy access by the trader.

---

## 5. Architectural Flow & Logic
1.  **Trader Action**: Clicks "Run Analytics" on the ML Advisor tab.
2.  **API Request**: Frontend calls `/api/ml/recommend/RELIANCE`.
3.  **Inference**: Backend loads the specific ML Bundle (Weights + Config) from the `ml/` folder.
4.  **Data Fetch**: System pulls the latest 15-minute candles from OpenAlgo's internal **Historify (DuckDB)**.
5.  **Veto Check**: The **Risk Moderator** evaluates the recommendation against survival rules.
6.  **Display**: Frontend receives the JSON and paints the "Intelligence Card" and "Chart Overlay."

---

## 6. Trading Benefits & Future-Proofing
- **For the Trader**: Provides a "Second Opinion" before entering a trade. Prevents overtrading by showing a low "Survival Score" during high-volatility regimes.
- **Scalability**: New models (e.g., INFY, TCS) can be added simply by dropping a new `.yaml` config into the `ml/configs` folder.
- **Institutional Alignment**: This is a direct implementation of the **AAUM v3** design (Intelligence Node -> Risk Veto -> Order Core).

---
**Status**: ACTIVE
**Developer**: Gemini CLI (Institutional Intelligence Architect)
**Date**: March 22, 2026
