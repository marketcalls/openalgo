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

### Flow - Visual Workflow Automation
- [Flow PRD](./flow.md) - Main product requirements
- [Node Creation Guide](./flow-node-creation.md) - How to create new nodes
- [Node Reference](./flow-node-reference.md) - Complete list of 50+ nodes
- [UI Components](./flow-ui-components.md) - React components guide
- [Execution Engine](./flow-execution.md) - Backend execution details

### Sandbox - Paper Trading Environment
- [Sandbox PRD](./sandbox.md) - Main product requirements
- [Architecture](./sandbox-architecture.md) - System architecture
- [Execution Engine](./sandbox-execution-engine.md) - Order matching engine
- [Margin System](./sandbox-margin-system.md) - Margin calculation and funds

### Python Strategies - Strategy Hosting
- [Python Strategies PRD](./python-strategies.md) - Main product requirements
- [Process Management](./python-strategies-process-management.md) - Subprocess handling
- [Scheduling](./python-strategies-scheduling.md) - Market-aware scheduling
- [API Reference](./python-strategies-api-reference.md) - Complete API documentation

### Historify - Historical Data Management
- [Historify PRD](./historify.md) - Main product requirements
- [Data Model](./historify-data-model.md) - DuckDB schema
- [Download Engine](./historify-download-engine.md) - Bulk download management
- [API Reference](./historify-api-reference.md) - Complete API documentation

### WebSocket Proxy
- [WebSocket Proxy PRD](./websocket-proxy.md) - Real-time market data streaming

### CI/CD Pipeline
- [CI/CD PRD](./ci-cd.md) - Main product requirements
- [Workflows Reference](./ci-cd-workflows.md) - Detailed job documentation
- [Security Scanning](./ci-cd-security.md) - Security tools and configuration
- [Local Development](./ci-cd-local-development.md) - Pre-commit setup guide
