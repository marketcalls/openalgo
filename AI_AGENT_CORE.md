# AI Agent Core Architecture - Foundation & Handover Manual

## 1. Project Overview
This project implements a Tier-1 Institutional Grade Trading Terminal for NSE intraday trading. It features a 12-panel dashboard powered by 9 specialized AI agents, 7 machine learning models, and a real-time self-learning feedback loop.

## 2. Component Architecture (The 12 Panels)
The dashboard is designed for 1920x1080 resolution with a zero-scroll CSS grid layout.
1.  **Command Center**: Real-time BUY/SELL/WAIT signals with confidence breakdowns.
2.  **Smart Chart**: TradingView integration with Volume Profile, GEX walls, and Liquidity Pools.
3.  **Timeframe Matrix**: Trend alignment across 1h, 15m, 5m, and 1m intervals.
4.  **Institutional Score**: A 0-100 gauge based on depth pressure and smart money signals.
5.  **AI Agents**: 3x3 grid of 9 specialist agents (Rakesh, Graham, Jesse, etc.).
6.  **ML/DL Models**: Compact table of 7 predictive models (XGBoost, LSTM, etc.).
7.  **Danger Alerts**: Priority feed (P0-P3) for stop hunts and regime changes.
8.  **Stock Scanner**: Sortable top-20 stocks based on predictability.
9.  **Depth Heatmap**: 5-level bid/ask horizontal bars updated every 100ms.
10. **OI Intelligence**: PCR gauge and Max Pain levels.
11. **Self-Learning Panel**: Live accuracy tracking and agent weight calibration.
12. **Risk Meter**: Real-time PnL, drawdown alerts, and circuit breakers.

## 3. AI Specialists (`openalgo/ai/specialist_agents.py`)
There are 9 specialized agents, each with a unique persona and framework:
*   **Rakesh (Growth)**: GQM Framework (Growth, Quality, Moat).
*   **Graham (Value)**: Deep value and safety margin.
*   **Jesse (Momentum)**: Trend following and breakout specialist.
*   **Simons (Quant)**: Mathematical and statistical arbitrage.
*   **Dalio (Macro)**: Economic indicators and global bias.
*   **Buzz (Sentiment)**: News and social sentiment analysis.
*   **Alpha (Sector)**: Rotational and sector-specific strength.
*   **Greeks (Options)**: Delta, Gamma, and Theta positioning.
*   **Taleb (Risk)**: Black-swan protection and tail-risk management.

## 4. Self-Learning Mechanism (`openalgo/ai/self_learning.py`)
The system employs a **Two-Speed Learning Loop**:
1.  **Fast Loop (Daily)**: 
    *   **Automation**: Triggered daily at 16:00 IST via `ai_learning_service.py`.
    *   **Verification**: The `OutcomeVerifier` checks "PENDING" signals against actual market prices (LTP).
    *   **Calibration**: The `WeightAdjuster` recalculates agent weights based on the last 100 trades. If an agent's accuracy increases, its weight is boosted (capped at 2.0x).
2.  **Slow Loop (Monthly)**:
    *   Success data is stored in `db/ai.db` for future LoRA fine-tuning in Colab.

## 5. Data Flow
**Zerodha WebSocket** → **OpenAlgo (OMS)** → **AAUM (Intelligence Layer)** → **React Dashboard**
*   **Backend**: Flask/Python 3.13.
*   **Persistence**: `ai_decisions` table in `db/ai.db` tracks every prediction, predicted price, and actual outcome.
*   **Real-time**: Socket.io broadcasts updates to the frontend.

## 6. How to Extend
*   **Add Agent**: Define a new class in `specialist_agents.py` and register it in `get_all_specialists()`.
*   **Update Model**: Add new model IDs to `ai/model_registry.py`.
*   **Fine-Tune**: Export the `ai_decisions` table where `outcome='CORRECT'` to use as training data.

## 7. Current Status
*   **Backend**: Core logic, database schemas, and daily scheduler are fully implemented.
*   **Next Phase**: Frontend visualization of the 12-panel grid and real-time agent streams.

---
*Created on Friday, 27 March 2026*
