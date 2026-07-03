---
okf_version: "0.1"
---

# OpenAlgo Knowledge Bundle

An Open Knowledge Format (OKF) bundle for **OpenAlgo**, the self-hosted
algorithmic trading platform. It captures the unified broker REST API, the
Python SDK and symbology/format references, and the technical-indicator library
as plain markdown concepts that humans and agents can read, diff, and traverse.

Start with the [platform overview](overview.md).

# Subdirectories

* [api](api/index.md) - The unified broker REST API (`/api/v1/`): orders, market data, options, account, calendar, streaming, and more.
* [sdk](sdk/index.md) - The OpenAlgo Python SDK plus symbol-format, order-constant, lot-size, and websocket format references.
* [indicators](indicators/index.md) - The `ta` technical-indicator library (trend, momentum, volatility, volume, statistical, hybrid, utility).
* [tools](tools/index.md) - In-browser trading & analytics surfaces: the Scalping Terminal (`/scalping`) and Options Trading Suite (`/tools`).
* [skills](skills/index.md) - Agentic skill packages that teach AI coding agents to drive OpenAlgo (execution, indicators, backtesting).
* [installation](installation/index.md) - Operational guides: upgrade, SMTP email, TOTP, and password recovery.

# Concepts

* [overview](overview.md) - What OpenAlgo is, its product surfaces, and how the API is authenticated.
* [responsibilities](responsibilities.md) - The responsibilities every OpenAlgo user accepts (transparency, compliance, security, risk ownership).
