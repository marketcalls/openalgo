# OpenAlgo Constitution

<!-- Sync Impact Report -->
<!-- Version change: 1.0.0 → 1.1.0 -->
<!-- Modified principles: All principles updated to reflect OpenAlgo architecture -->
<!-- Added sections: Technology Stack, Security Standards, Broker Integration Standards -->
<!-- Templates requiring updates: ✅ plan-template.md, ✅ spec-template.md, ✅ tasks-template.md -->
<!-- Follow-up TODOs: None -->

## Core Principles

### I. Python-First Backend Architecture
All backend services MUST be implemented using Python and Flask. This ensures consistency with the OpenAlgo open-source foundation, leverages the extensive Python ecosystem for financial data processing, and maintains compatibility with the existing broker integration layer. The Flask framework provides the RESTful API structure that supports 25+ broker integrations through a unified interface.

### II. DaisyUI Frontend Standards
The user interface MUST adhere to the DaisyUI component library standard as specified in the project. This ensures a consistent, modern, and accessible user experience across all trading interfaces, supports the theme system (Light/Dark/Garden modes), and maintains responsive design principles for both desktop and mobile trading.

### III. Test-Driven Development (NON-NEGOTIABLE)
All new features MUST include comprehensive test cases and follow the Test-Driven Development (TDD) process. This is critical for a financial trading platform where accuracy and reliability are paramount. Every feature must be fully tested during development with accuracy as the top priority. Test coverage must include unit tests, integration tests, and end-to-end testing for trading operations.

### IV. Feature Independence and Modularity
Each new feature MUST be developed as an independent file and method to avoid conflicts when syncing with the upstream OpenAlgo branch. This ensures modularity, reduces merge conflicts, and maintains compatibility with the open-source foundation. Features should be self-contained with clear interfaces and minimal dependencies.

### V. API Key and Security Management
All API keys (Open API, Grok API, Gemini API, Screener email password, Groq API) MUST be properly managed through the .env configuration system. Security is paramount in financial applications, requiring encrypted storage, secure session management, and comprehensive audit logging. All sensitive data must use Fernet encryption and Argon2 hashing.

### VI. Broker Integration Standards
All broker integrations MUST follow the established adapter pattern with standardized interfaces for order management, market data, and authentication. Each broker adapter must implement the base interface, handle broker-specific protocols, and transform data to the unified OpenAlgo format. Integration must support both REST APIs and WebSocket streaming where available.

## Technology Stack Requirements

### Backend Architecture
- **Framework**: Flask 3.0.3 with Flask-RESTX for API documentation
- **Database**: SQLAlchemy 2.0+ with connection pooling (50 base, 100 max overflow)
- **Authentication**: Argon2 password hashing with Fernet encryption for sensitive data
- **Real-time**: WebSocket proxy with ZeroMQ message broker
- **Security**: CSRF protection, rate limiting, secure headers, session management

### Frontend Standards
- **CSS Framework**: TailwindCSS with DaisyUI components
- **Theme Support**: 20+ themes including Light, Dark, and Garden modes
- **JavaScript**: Vanilla ES6+ with Socket.IO for real-time updates
- **Responsive Design**: Mobile-first approach with drawer navigation

### Database Architecture
- **Development**: SQLite with separate databases for different functions
- **Production**: PostgreSQL/MySQL with optimized connection pooling
- **Security**: Encrypted storage for sensitive data, audit logging
- **Performance**: Indexed queries, connection pooling, query optimization

## Security Standards

### Authentication and Authorization
- **Password Security**: Argon2id hashing with pepper for enhanced security
- **API Keys**: Secure generation, hashed storage, encrypted retrieval
- **Session Management**: Secure cookies with daily expiry at 3:30 AM IST
- **2FA Support**: TOTP-based two-factor authentication
- **CSRF Protection**: Comprehensive token validation for state-changing operations

### Data Protection
- **Encryption**: Fernet symmetric encryption for sensitive data storage
- **API Security**: Rate limiting, IP-based restrictions, secure headers
- **Audit Logging**: Comprehensive logging of all trading operations
- **Compliance**: GDPR compliance features, data portability, right to be forgotten

## Development Workflow

### Code Quality Standards
- **Testing**: TDD mandatory with comprehensive test coverage
- **Documentation**: All APIs must include OpenAPI/Swagger documentation
- **Code Review**: All changes must be reviewed for security and compliance
- **Performance**: Response times < 100ms for order placement, < 200ms for data retrieval

### Integration Requirements
- **Broker APIs**: Must support 25+ Indian brokers with unified interface
- **Market Data**: Real-time WebSocket streaming with ZeroMQ backend
- **Strategy Hosting**: Python strategy execution with process isolation
- **Sandbox Mode**: Complete simulated trading environment for testing

## Governance

This constitution supersedes all other development practices and must be followed for all OpenAlgo development activities. Amendments require documentation, approval from the core development team, and a migration plan for existing features.

All pull requests and code reviews must verify compliance with these principles. Complexity must be justified and documented. Use the established design documents in the `/design` directory for runtime development guidance.

**Version**: 1.1.0 | **Ratified**: 2025-01-15 | **Last Amended**: 2025-01-15