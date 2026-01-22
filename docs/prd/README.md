# Product Requirements Document - OpenAlgo

## Product Overview

**Product Name:** OpenAlgo
**Version:** 2.0
**Type:** Open-source algorithmic trading platform

## Vision

Democratize algorithmic trading for Indian retail traders by providing a free, self-hosted platform that bridges trading signals from any source to any broker.

## Problem Statement

Indian retail traders face:
- Manual order execution delays (2-3 minutes per trade)
- No affordable automation solutions
- Vendor lock-in with expensive platforms
- Data privacy concerns with cloud-based solutions

## Solution

A unified API layer that:
- Connects 24+ Indian brokers through standardized API
- Accepts signals from TradingView, Amibroker, Python, Excel, AI agents
- Executes orders in under 1 second
- Runs entirely on user's own infrastructure

## Target Users

| Segment | Needs |
|---------|-------|
| Retail Traders | Fast execution, low cost |
| Technical Traders | TradingView/Amibroker integration |
| Algo Developers | Python API, backtesting |
| Investment Advisors | Order approval workflow, audit trail |

## Core Features

| Feature | Priority | Status |
|---------|----------|--------|
| Multi-broker support (24+) | P0 | Complete |
| REST API for orders | P0 | Complete |
| TradingView webhooks | P0 | Complete |
| Real-time WebSocket streaming | P0 | Complete |
| Sandbox testing mode | P0 | Complete |
| Visual workflow builder (Flow) | P1 | Complete |
| Historical data manager (Historify) | P1 | Complete |
| Action Center (order approval) | P1 | Complete |
| Python strategy execution | P1 | Complete |
| Telegram notifications | P2 | Complete |

## Non-Functional Requirements

| Requirement | Target |
|-------------|--------|
| Order latency | < 500ms |
| Concurrent symbols | 3000+ |
| Uptime | 99.9% during market hours |
| Data privacy | 100% self-hosted |

## Success Metrics

- Active GitHub stars: 1000+
- Supported brokers: 24+
- Daily order volume capability: 10,000+

## Detailed PRDs

- [Historify PRD](./historify.md) - Historical data management
- [Flow PRD](./flow.md) - Visual workflow automation
- [Sandbox PRD](./sandbox.md) - Paper trading environment
- [WebSocket Proxy PRD](./websocket-proxy.md) - Real-time market data streaming
