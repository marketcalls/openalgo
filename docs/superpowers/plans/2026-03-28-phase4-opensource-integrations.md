# Phase 4: Open Source Integrations for OpenAlgo

## Date: 2026-03-28
## Status: PLAN WRITTEN — Implementation pending
## Priority: After Phase 3 live testing

---

## 5 Projects to Integrate

### 1. NVIDIA Quantitative Portfolio Optimization
- **Source**: https://github.com/NVIDIA-AI-Blueprints/quantitative-portfolio-optimization
- **What**: GPU-accelerated portfolio optimization (Mean-CVaR, scenario generation, backtesting)
- **Key Tech**: RAPIDS cuML/cuDF, NVIDIA cuOpt, CUDA 13.0+
- **Useful For OpenAlgo**: Position sizing, portfolio allocation, risk modeling (CVaR)
- **Hardware**: Requires NVIDIA GPU (RTX 5050 8GB available)
- **Integration Plan**:
  - Extract Mean-CVaR optimization logic (Python, remove cuOpt dependency for CPU fallback)
  - Add as `ai/portfolio_optimizer.py`
  - API endpoint: `POST /api/v1/agent/portfolio-optimize`
  - Frontend: Portfolio Optimizer tab or section in Decision tab
  - Inputs: symbols[], weights, risk_tolerance, constraints
  - Outputs: optimal_weights, expected_return, cvar_95, sharpe_ratio
- **Effort**: Medium (2 sessions)
- **Dependencies**: numpy, scipy (CPU fallback), optional cupy/cuml (GPU)

### 2. NVIDIA-KX Model Distillation for Financial Data
- **Source**: https://github.com/KxSystems/nvidia-kx-samples/tree/main/ai-model-distillation-for-financial-data
- **What**: Fine-tune smaller LLMs (1B-8B) using teacher model (70B) knowledge for financial news classification
- **Key Tech**: NVIDIA NeMo, KDB-X, LoRA fine-tuning, FastAPI, Celery
- **Useful For OpenAlgo**: Train local Qwen3.5-9B to classify financial events (13 types) from news
- **Hardware**: RTX 5050 8GB + WSL2 + vLLM already setup
- **Integration Plan**:
  - Extract the 13-class financial event classifier logic
  - Create training pipeline: collect news → label with Gemini/Claude → fine-tune Qwen3.5-9B with LoRA
  - Add as `ai/financial_classifier.py`
  - Integrate with existing `ai/news_sentiment.py` (enhance with event classification)
  - Events: earnings, M&A, dividend, restructuring, litigation, regulatory, etc.
  - API endpoint: `POST /api/v1/agent/classify-news`
  - Frontend: Enhance NewsTab with event classification badges
- **Effort**: High (3-4 sessions — training pipeline is complex)
- **Dependencies**: transformers, peft (LoRA), datasets, existing vLLM setup

### 3. FinRL — Reinforcement Learning for Trading
- **Source**: https://github.com/AI4Finance-Foundation/FinRL
- **What**: Train DRL agents (A2C, PPO, DDPG, TD3, SAC) for automated stock trading
- **Key Tech**: Stable Baselines 3, Gym environments, Yahoo Finance data
- **Useful For OpenAlgo**: Train RL agents that learn optimal buy/sell timing
- **Integration Plan**:
  - Install: `pip install finrl stable-baselines3`
  - Create `ai/rl_agents.py` — wrapper around FinRL's DRL agents
  - Train agents on Indian stocks using OpenAlgo's OHLCV data (via data_bridge)
  - Add 5 agent strategies: A2C, PPO, DDPG, TD3, SAC
  - Each agent outputs: action (buy/sell/hold), confidence, position_size
  - API endpoint: `POST /api/v1/agent/rl-predict`
  - Frontend: Add RL Agent section to Strategies tab (6th strategy alongside Fibonacci, Harmonic, etc.)
  - Backtesting: Compare RL agents vs traditional signals
- **Effort**: Medium-High (2-3 sessions)
- **Dependencies**: finrl, stable-baselines3, gymnasium
- **Note**: Training takes GPU time — pre-train on NIFTY50, store models in data/models/

### 4. Dexter — Autonomous Financial Research Agent
- **Source**: https://github.com/virattt/dexter
- **What**: AI agent that breaks complex financial questions into research tasks, executes them, validates results
- **Key Tech**: TypeScript/Bun, LangSmith, OpenAI/Anthropic, Financial Datasets API
- **Useful For OpenAlgo**: Deep research reports for stocks (fundamental + news + market structure)
- **Integration Plan**:
  - Port Dexter's research logic from TypeScript to Python (or run as subprocess)
  - Create `ai/research_agent.py` — autonomous research that:
    1. Takes a question: "Should I buy RELIANCE?"
    2. Plans research tasks (fundamentals, news, technicals, sector comparison)
    3. Executes each task using OpenAlgo's existing modules
    4. Self-validates and refines
    5. Returns structured research report
  - Use existing Ollama/Gemini as LLM backbone (no OpenAI dependency)
  - API endpoint: `POST /api/v1/agent/research`
  - Frontend: Add Research tab or enhance LLM Commentary section
  - Integrate with news_sentiment, strategy_decision, multi_timeframe for data
- **Effort**: Medium (2 sessions)
- **Dependencies**: Existing Ollama/Gemini LLM, no new deps

### 5. Daily Stock Analysis / Automated Market Report
- **Source**: https://github.com/hgnx/automated-market-report (most relevant)
- **Also**: https://github.com/DMTSource/daily-stock-forecast, https://github.com/LastAncientOne/SimpleStockAnalysisPython
- **What**: Automated daily market reports with data from multiple sources
- **Key Tech**: Python, yfinance, matplotlib, PDF generation
- **Useful For OpenAlgo**: Daily market summary report (NIFTY, top movers, signals, news)
- **Integration Plan**:
  - Create `ai/daily_report.py` — generates daily market analysis
  - Data sources: OpenAlgo's existing OHLCV + signals + news_sentiment
  - Report includes:
    1. Market overview (NIFTY50/BANKNIFTY levels, change, regime)
    2. Top 5 gainers/losers with signals
    3. Sector rotation analysis
    4. News sentiment summary
    5. AI signals summary (bullish/bearish/neutral counts)
    6. Key levels for next day (pivots, Fibonacci)
  - Output: JSON (for frontend) + optional PDF export
  - API endpoint: `POST /api/v1/agent/daily-report`
  - Frontend: Add Dashboard/Report tab showing daily summary
  - Scheduled task: Auto-generate after market close (3:30 PM IST)
- **Effort**: Low-Medium (1-2 sessions)
- **Dependencies**: Existing modules, optional reportlab for PDF

---

## Implementation Order (Recommended)

| Session | Project | Why First |
|---------|---------|-----------|
| **Session 1** | Daily Stock Analysis | Easiest, uses all existing modules, immediate value |
| **Session 2** | Dexter Research Agent | Builds on existing LLM + analysis modules |
| **Session 3** | FinRL Agents | Adds ML-based trading signals |
| **Session 4** | Portfolio Optimization | Advanced position sizing |
| **Session 5** | Model Distillation | Most complex, needs training pipeline |

---

## Architecture: How They All Fit Together

```
OpenAlgo AI Layer
├── ai/
│   ├── indicators.py           ✅ EXISTS — 20+ technical indicators
│   ├── indicators_advanced.py  ✅ EXISTS — SMC, harmonics, divergence
│   ├── signals.py              ✅ EXISTS — Composite signal engine
│   ├── news_sentiment.py       ✅ EXISTS — VADER + Google News/ET
│   ├── daily_report.py         🆕 Phase 4.1 — Daily market summary
│   ├── research_agent.py       🆕 Phase 4.2 — Dexter-style autonomous research
│   ├── rl_agents.py            🆕 Phase 4.3 — FinRL DRL trading agents
│   ├── portfolio_optimizer.py  🆕 Phase 4.4 — NVIDIA-style CVaR optimization
│   └── financial_classifier.py 🆕 Phase 4.5 — Distilled news event classifier
├── services/
│   ├── ai_analysis_service.py  ✅ EXISTS — Main analysis orchestrator
│   ├── strategy_analysis_service.py ✅ EXISTS — Strategy endpoints
│   └── daily_report_service.py 🆕 Phase 4.1
├── restx_api/
│   └── ai_agent.py             ✅ EXISTS — All endpoints live here
└── frontend/src/components/ai-analysis/tabs/
    ├── TechnicalTab.tsx         ✅ EXISTS
    ├── StrategiesTab.tsx        ✅ EXISTS (add RL Agent as 6th strategy)
    ├── DecisionTab.tsx          ✅ EXISTS (add portfolio optimization)
    ├── NewsTab.tsx              ✅ EXISTS (enhance with event classification)
    ├── DailyReportTab.tsx       🆕 Phase 4.1
    └── ResearchTab.tsx          🆕 Phase 4.2
```

---

## Frontend Tab Structure After Phase 4

```
Technical | Strategies | Decision | Fundamental | Why Not | Multi-TF | News | Research | Report | Scanner | History
           (+ RL Agent)  (+ Portfolio)            (data!)            (+ events)  (NEW)    (NEW)
```

---

## Quick Reference: Git Repos

| Project | URL | License |
|---------|-----|---------|
| NVIDIA Portfolio Opt | https://github.com/NVIDIA-AI-Blueprints/quantitative-portfolio-optimization | Apache 2.0 |
| NVIDIA-KX Distillation | https://github.com/KxSystems/nvidia-kx-samples/tree/main/ai-model-distillation-for-financial-data | Apache 2.0 |
| FinRL | https://github.com/AI4Finance-Foundation/FinRL | MIT |
| Dexter | https://github.com/virattt/dexter | MIT |
| Automated Market Report | https://github.com/hgnx/automated-market-report | MIT |
| Daily Stock Forecast | https://github.com/DMTSource/daily-stock-forecast | MIT |

---

## Hardware Available

- **GPU**: NVIDIA RTX 5050 Laptop (8GB VRAM), CUDA 13.0
- **WSL2**: Ubuntu with GPU passthrough
- **vLLM**: v0.16.0 installed, Qwen3-14B-AWQ ready
- **Ollama**: qwen3.5:9b (primary model)
- **Python**: 3.11.9

All 5 projects are feasible on this hardware. FinRL and Model Distillation will use the GPU most.
