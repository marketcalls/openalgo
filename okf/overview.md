---
type: Reference
title: OpenAlgo Platform Overview
description: What OpenAlgo is, its four product surfaces, and how the unified broker API is authenticated and organized.
resource: https://github.com/marketcalls/openalgo/blob/main/CLAUDE.md
tags:
- openalgo
- overview
- architecture
- api
timestamp: '2026-07-03T00:00:00+00:00'
---

# What OpenAlgo is

OpenAlgo is a production-ready, self-hosted algorithmic trading platform (Flask
backend + React 19 frontend). It is **four products in one instance**, all
sharing a single broker session and WebSocket feed:

| Surface | Route | Purpose |
| --- | --- | --- |
| Unified Broker API | `/api/v1/` | External platforms (TradingView, Amibroker, ChartInk, Excel, Python, MCP) |
| Python Strategy Host | `/python` | In-browser editor to paste, schedule (IST), and run parallel strategies with process isolation and live logs |
| Flow (No-Code Builder) | `/flow` | Drag-and-drop nodes: market data → indicators → conditions → order execution; JSON import/export |
| Options Trading Suite | `/tools` | 12 analytical tools: Strategy Builder, Option Chain, IV Smile, Max Pain, Vol Surface, GEX, OI Tracker, Straddle Chart, and more |

All surfaces share the Sandbox engine (₹1 Crore sandbox capital, exchange-aligned
auto square-off) and support Telegram alerts.

# The unified broker API

- **Base URL:** `http://127.0.0.1:5000/api/v1` (local host; also reachable via
  ngrok or a custom domain).
- **Authentication:** every request includes your API key in the JSON body:
  `{ "apikey": "<your_app_apikey>" }`.
- **Response shape:** `{ "status": "success", "data": { ... } }` on success;
  `{ "status": "error", "message": "..." }` on error.
- **Rate limits** are differentiated per operation — see [rate limiting](api/rate-limiting.md).

Browse the full API surface in the [API reference](api/index.md), the
[Python SDK & format references](sdk/index.md), and the
[technical indicator library](indicators/index.md).

# Where to start

- Place your first order with [PlaceOrder](api/order-management/placeorder.md).
- Learn the [symbol format](sdk/symbol-format.md) and
  [order constants](sdk/order-constants.md) that every order API uses.
- Fetch data with [History](api/market-data/history.md) and compute signals with
  the [indicator library](indicators/introduction.md).
- Drive everything from Python with the [OpenAlgo Python SDK](sdk/python-sdk.md).

# Deployment & security model (highlights)

- **Single user per deployment** — one user, one broker session per instance;
  self-hosted on your own server (no SaaS).
- **SEBI static-IP mandate (effective 2026-04-01):** transactional API orders
  require broker-side static-IP whitelisting; stolen credentials cannot be used
  from an unregistered IP.
- Indian broker tokens expire daily at ~03:00 AM IST; session management aligns
  to this schedule.
- 30+ broker integrations; the local-only MCP server speaks stdio to Claude
  Desktop / Cursor / Windsurf and is not remotely exposed.

# Citations
- Official docs: https://docs.openalgo.in
- Repository: https://github.com/marketcalls/openalgo
- Source: https://github.com/marketcalls/openalgo/blob/main/CLAUDE.md
