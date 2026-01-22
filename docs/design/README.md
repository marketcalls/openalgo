# OpenAlgo Developer Documentation

Welcome to the OpenAlgo Developer Bible - a comprehensive guide for understanding and working with the OpenAlgo algorithmic trading platform.

## What is OpenAlgo?

OpenAlgo is a production-ready algorithmic trading platform built with Flask (backend) and React 19 (frontend). It provides a unified API layer across 24+ Indian brokers, enabling seamless integration with TradingView, Amibroker, Excel, Python, and AI agents.

## Documentation Index

### Core Architecture
| Module | Description |
|--------|-------------|
| [00-Directory Structure](./00-directory-structure/) | Complete project directory map and navigation guide |
| [01-Frontend](./01-frontend/) | React 19 SPA architecture, components, state management |
| [02-Backend](./02-backend/) | Flask application structure, blueprints, services |
| [18-Database](./18-database/) | Database schema, 5-DB architecture, optimization |
| [20-Design Principles](./20-design-principles/) | Architectural patterns and coding conventions |

### Authentication & Security
| Module | Description |
|--------|-------------|
| [03-Login & Broker Flow](./03-login-broker-flow/) | User auth, OAuth2, broker integration |
| [05-Security Architecture](./05-security-architecture/) | Overall security design |
| [23-IP Security](./23-ip-security/) | IP banning and rate limiting |
| [24-Browser Security](./24-browser-security/) | CORS, CSP, CSRF protection |

### Trading Operations
| Module | Description |
|--------|-------------|
| [09-REST API](./09-rest-api/) | Complete API endpoint documentation |
| [19-PlaceOrder Flow](./19-placeorder-flow/) | Order execution pipeline |
| [15-UI Elements](./15-ui-elements/) | OrderBook, TradeBook, Positions, Holdings, Dashboard |

### Real-Time & Data
| Module | Description |
|--------|-------------|
| [06-WebSockets](./06-websockets/) | Market data streaming architecture |
| [04-Cache Architecture](./04-cache-architecture/) | Caching strategies and TTL |
| [08-Historify](./08-historify/) | Historical data management |
| [17-Connection Pooling](./17-connection-pooling/) | HTTP and WebSocket pooling |

### Strategies & Automation
| Module | Description |
|--------|-------------|
| [10-Flow Architecture](./10-flow/) | Visual workflow builder |
| [13-Chartink](./13-chartink/) | Chartink scanner integration |
| [14-TradingView & GoCharting](./14-tradingview-gocharting/) | Alert webhook setup |

### Paper Trading
| Module | Description |
|--------|-------------|
| [07-Sandbox](./07-sandbox/) | Analyzer mode with virtual capital |

### Monitoring & Logs
| Module | Description |
|--------|-------------|
| [16-Centralized Logging](./16-centralized-logging/) | Logging architecture |
| [22-Log Section](./22-log-section/) | Live and Sandbox logs UI |
| [25-Latency Monitor](./25-latency-monitor/) | API latency tracking |
| [26-Traffic Logs](./26-traffic-logs/) | HTTP traffic monitoring |

### Administration
| Module | Description |
|--------|-------------|
| [21-Admin Section](./21-admin-section/) | Admin features and controls |

### Deployment
| Module | Description |
|--------|-------------|
| [11-Docker](./11-docker/) | Docker containerization |
| [12-Ubuntu Installation](./12-ubuntu-installation/) | Server deployment guide |

## Quick Start

```bash
# Install uv package manager
pip install uv

# Configure environment
cp .sample.env .env

# Run application
uv run app.py
```

## Key Files Reference

| File | Purpose |
|------|---------|
| `app.py` | Main Flask entry point |
| `frontend/src/App.tsx` | React router configuration |
| `restx_api/__init__.py` | REST API namespace registry |
| `broker/*/plugin.json` | Broker plugin metadata |

## Progress Tracker

See [TRACKER.md](./TRACKER.md) for documentation completion status.
