# OpenAlgo Design Documentation

## Introduction

Welcome to the design documentation for OpenAlgo, a comprehensive broker-agnostic algorithmic trading platform with advanced strategy hosting capabilities.

### Purpose

This documentation provides a comprehensive understanding of the OpenAlgo system architecture, core components, design patterns, data flows, and operational considerations. It serves as a guide for developers, architects, and maintainers involved in the development and extension of the platform.

### Overview

OpenAlgo is a full-featured trading platform that provides:
* **RESTful API Interface**: Built with Flask for programmatic trading
* **Python Strategy Hosting**: Complete strategy management system with scheduling and monitoring
* **Multi-Broker Support**: Unified interface for 20+ Indian brokers
* **Real-time Market Data**: WebSocket infrastructure for live market feeds
* **Web Dashboard**: Intuitive UI for manual trading and monitoring
* **Advanced Order Management**: Smart orders, basket orders, and position management

### Key Features

#### Trading Capabilities
* Place, modify, and cancel orders across multiple brokers
* Smart order types (SL, Target, Trailing SL)
* Basket orders for multi-leg strategies
* Position management and P&L tracking
* Real-time order and trade book

#### Strategy Management
* Upload and host Python trading strategies
* Process isolation for each strategy
* Scheduled execution with cron-like scheduling
* Real-time strategy logs and monitoring
* Environment variable management for API keys
* Automatic restart on system reboot

#### Market Data
* Real-time quotes and market depth
* Historical data with multiple timeframes
* WebSocket streaming for live updates
* Symbol search and contract management

### Goals

* **Broker Agnosticism:** Provide a unified API layer abstracting the complexities of different broker APIs
* **Strategy Hosting:** Enable traders to deploy and manage automated strategies easily
* **Extensibility:** Easily integrate new brokers and trading strategies
* **Performance:** Ensure efficient handling of API requests and trading operations
* **Reliability:** Maintain stable connections with automatic reconnection and error recovery
* **Security:** Implement robust authentication, encryption, and data protection
* **Usability:** Offer clear APIs and intuitive web interface

### Target Users

* **Algorithmic Traders**: Deploy and manage automated trading strategies
* **Developers**: Build custom trading applications using the API
* **Quantitative Analysts**: Backtest and deploy quantitative strategies
* **Trading Firms**: Manage multiple accounts and strategies
* **Individual Traders**: Execute trades across multiple brokers from one platform

## Documentation Structure

### Core Architecture
- **[01_architecture.md](01_architecture.md)** - Overall system architecture and technology stack
- **[02_api_layer.md](02_api_layer.md)** - RESTful API design and request handling
- **[03_broker_integration.md](03_broker_integration.md)** - Broker-specific integrations and adapters

### Data and Storage
- **[04_database_layer.md](04_database_layer.md)** - Database design and data access patterns
- **[05_strategies.md](05_strategies.md)** - Trading strategy implementation and management
- **[11_python_strategy_hosting.md](11_python_strategy_hosting.md)** - Python strategy hosting system architecture

### Security and Configuration
- **[06_authentication_platform.md](06_authentication_platform.md)** - Authentication and authorization systems
- **[07_configuration.md](07_configuration.md)** - Configuration management and environment setup
- **[12_deployment_architecture.md](12_deployment_architecture.md)** - Deployment options and infrastructure

### Infrastructure and Utilities
- **[08_utilities.md](08_utilities.md)** - Common utilities and helper functions
- **[09_websocket_architecture.md](09_websocket_architecture.md)** - Real-time WebSocket infrastructure
- **[10_logging_system.md](10_logging_system.md)** - Centralized logging system

## System Architecture Overview

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Client Layer                         │
├──────────────┬──────────────┬──────────────┬──────────────┤
│   Web UI     │  REST API    │  WebSocket   │   Strategy   │
│  Dashboard   │   Clients    │   Clients    │   Scripts    │
└──────────────┴──────────────┴──────────────┴──────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    OpenAlgo Platform                        │
├─────────────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Application Layer (Flask)               │   │
│  ├───────────────┬─────────────┬───────────────────────┤   │
│  │  Web Routes   │  REST API   │  Strategy Manager     │   │
│  │  (Blueprints) │ (Flask-RESTX)│  (/python route)     │   │
│  └───────────────┴─────────────┴───────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Business Logic Layer                    │   │
│  ├──────────┬──────────┬──────────┬──────────────────┤   │
│  │  Order   │ Position │ Strategy │   Market Data    │   │
│  │  Manager │ Manager  │  Engine  │    Manager       │   │
│  └──────────┴──────────┴──────────┴──────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │            Broker Integration Layer                  │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │  Broker Adapters (20+ brokers)                      │   │
│  │  WebSocket Adapters | REST API Adapters             │   │
│  └─────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Infrastructure Layer                    │   │
│  ├──────────┬──────────┬──────────┬──────────────────┤   │
│  │ Database │ Logging  │ WebSocket│    Security      │   │
│  │   ORM    │  System  │   Proxy  │   & Auth         │   │
│  └──────────┴──────────┴──────────┴──────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    External Systems                         │
├──────────────┬──────────────┬──────────────┬──────────────┤
│   Database   │ Broker APIs  │ Market Data  │   Cloud      │
│   (SQLite/   │  (REST/WS)   │   Feeds      │  Services    │
│   PostgreSQL)│              │              │   (AWS)      │
└──────────────┴──────────────┴──────────────┴──────────────┘
```

## Recent Architecture Enhancements

### Python Strategy Hosting System (New)
A comprehensive strategy hosting system that enables traders to:
- **Upload and Deploy**: Upload Python scripts through web interface
- **Process Isolation**: Each strategy runs in its own process for safety
- **Scheduling**: Cron-like scheduling with IST timezone support
- **Monitoring**: Real-time logs and status monitoring
- **Environment Management**: Secure storage of API keys and configuration
- **Cross-Platform**: Works on Windows, Linux, and macOS

### Enhanced WebSocket Infrastructure
- **WebSocket Proxy Server**: Central hub for managing client connections
- **Broker Adapter Factory**: Dynamic loading of broker-specific adapters
- **ZeroMQ Message Broker**: High-performance internal messaging
- **Auto-Reconnection**: Automatic reconnection with exponential backoff
- **Multi-Symbol Streaming**: Subscribe to multiple symbols simultaneously

### Advanced Order Management
- **Smart Orders**: Implement SL, target, and trailing stop-loss orders
- **Basket Orders**: Execute multiple orders as a single transaction
- **Split Orders**: Automatically split large orders into smaller chunks
- **Order Validation**: Client-side and server-side validation

### Security Enhancements
- **API Key Management**: Secure storage with encryption
- **CSRF Protection**: Comprehensive CSRF token validation
- **Rate Limiting**: Per-user and per-IP rate limiting
- **Session Security**: Secure session handling with expiry
- **Audit Logging**: Detailed logging for compliance
- **Sensitive Data Protection**: Automatic redaction in logs

### Deployment Options
- **Docker Support**: Containerized deployment with docker-compose
- **AWS Elastic Beanstalk**: Automated deployment to AWS
- **Ubuntu VPS**: Production-ready installation scripts
- **Nginx Integration**: Reverse proxy with SSL support
- **Systemd Services**: Reliable process management

### Performance Optimizations
- **Connection Pooling**: Database connection pooling
- **Caching**: In-memory caching for frequently accessed data
- **Async Processing**: WebSocket and background task processing
- **Lazy Loading**: On-demand loading of broker modules
- **Resource Management**: Automatic cleanup of idle resources

## Supported Brokers

OpenAlgo currently supports 20+ Indian brokers including:
- Zerodha, Angel One, Upstox, Groww
- 5Paisa, IIFL, Kotak Securities
- Dhan, Fyers, Alice Blue
- Shoonya (Finvasia), Flattrade
- And many more...

Each broker integration includes:
- Order placement and management
- Position and holdings retrieval
- Market data access
- WebSocket streaming (where available)
- Master contract management

## Getting Started

1. **Installation**: Use provided installation scripts for Ubuntu/VPS deployment
2. **Configuration**: Set up broker API credentials in .env file
3. **Authentication**: Login through web interface or API
4. **Trading**: Use web dashboard or REST API for trading
5. **Strategy Deployment**: Upload Python strategies via /python route

For detailed setup instructions, refer to the INSTALL.md file in the root directory.