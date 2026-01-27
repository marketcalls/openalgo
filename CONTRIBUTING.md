# Contributing to OpenAlgo


## Let's democratize algorithmic trading, together!

We're thrilled that you're interested in contributing to OpenAlgo! This guide will help you get started, whether you're fixing a bug, adding a new broker, improving documentation, or building new features.

Below you'll find everything you need to set up OpenAlgo on your computer and start contributing.

---

## Our Mission

OpenAlgo is built **by traders, for traders**. We believe in democratizing algorithmic trading by providing a broker-agnostic, open-source platform that puts control back in the hands of traders. Every contribution, no matter how small, helps us achieve this mission.

---

## Table of Contents

1. [Technology Stack](#technology-stack)
2. [Development Setup](#development-setup)
3. [Local Development](#local-development)
4. [Project Structure](#project-structure)
5. [Development Workflow](#development-workflow)
6. [Contributing Guidelines](#contributing-guidelines)
7. [Testing](#testing)
8. [Adding a New Broker](#adding-a-new-broker)
9. [UI Development](#ui-development)
10. [Documentation](#documentation)
11. [Best Practices](#best-practices)
12. [Getting Help](#getting-help)

---

## Technology Stack

OpenAlgo is built using **Python Flask** for the backend and **TailwindCSS + DaisyUI** for the frontend.

### Backend Technologies

- **Python 3.12+** - Core programming language (requires Python 3.10 or higher, 3.12+ recommended)
- **Flask 3.0+** - Lightweight web framework
- **Flask-RESTX** - RESTful API with auto-generated Swagger documentation
- **SQLAlchemy 2.0+** - Database ORM for data persistence
- **Flask-SocketIO 5.3+** - Real-time WebSocket connections for live updates
- **Flask-Login** - User session management and authentication
- **Flask-WTF** - Form validation and CSRF protection

### Frontend Technologies

- **Jinja2** - Server-side templating engine
- **TailwindCSS 4.1+** - Utility-first CSS framework
- **DaisyUI 5.1+** - Beautiful component library for Tailwind
- **PostCSS** - CSS processing and compilation
- **Chart.js** - Data visualization and charting

### Trading & Data Libraries

- **pandas 2.2+** - Data manipulation and analysis
- **numpy 2.2+** - Numerical computing
- **httpx** - Modern HTTP client with HTTP/2 support
- **websockets 15.0+** - WebSocket client and server
- **pyzmq 26.3+** - ZeroMQ for high-performance message queue
- **APScheduler** - Background task scheduling

### Security & Performance

- **argon2-cffi** - Secure password hashing
- **cryptography** - Token encryption
- **Flask-Limiter** - Rate limiting
- **Flask-CORS** - CORS protection

> [!IMPORTANT]
> You will need **Node.js v16+** and **Python 3.12** or the latest Python version.

---

## Development Setup

### Prerequisites

Before you begin, make sure you have the following installed:

- **Python 3.10 or higher** (3.12+ recommended) - [Download Python](https://www.python.org/downloads/)
- **Node.js v16 or higher** - [Download Node.js](https://nodejs.org/)
- **Git** - [Download Git](https://git-scm.com/downloads)
- **Code Editor** - VS Code recommended with extensions:
  - Python
  - Pylance
  - Jupyter
- **Basic Knowledge** of Flask and REST APIs

### Install Dependencies

```bash
# Clone the repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Create and activate virtual environment
# On Windows:
python -m venv venv
venv\Scripts\activate

# On Linux/Mac:
python -m venv venv
source venv/bin/activate

# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies
npm install
```

### Configure Environment

```bash
# Copy the sample environment file
# On Windows:
copy .sample.env .env

# On Linux/Mac:
cp .sample.env .env

# Edit .env and update at minimum:
# 1. Generate new APP_KEY and API_KEY_PEPPER
# 2. Configure database URLs
# 3. Set Flask host/port settings
```

**Important Security Note**: Generate secure random keys:
```bash
# Generate APP_KEY
python -c "import secrets; print(secrets.token_hex(32))"

# Generate API_KEY_PEPPER
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## Local Development

### Build Packages

OpenAlgo requires CSS compilation before running. You have two options:

#### Option 1: Manual Build

```bash
# Build CSS for production
npm run build:css

# Or watch for changes during development
npm run watch:css
```

#### Option 2: Automated Development

```bash
# Runs CSS watch in development mode
npm run dev
```

### Run the Application

#### Option 1: Flask Development Server

```bash
# Activate virtual environment (if not already active)
# Windows:
venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Run the Flask application
python app.py

# Application will be available at http://127.0.0.1:5000
```

#### Option 2: Production with Gunicorn (Linux only)

```bash
# Install production requirements
pip install -r requirements-nginx.txt

# Run with Gunicorn
gunicorn --worker-class eventlet -w 1 app:app

# Note: Use -w 1 (one worker) for WebSocket compatibility
```

### Development Workflow with Multiple Terminals

For the best development experience, use two terminals:

**Terminal 1 - CSS Watch Mode:**
```bash
npm run dev
# Keep this running to auto-compile CSS on changes
```

**Terminal 2 - Flask Server:**
```bash
python app.py
# Your application server
```

### First Time Setup

1. **Access the application**: Navigate to `http://127.0.0.1:5000`
2. **Setup account**: Go to `http://127.0.0.1:5000/setup`
3. **Create admin user**: Fill in the setup form
4. **Login**: Use your credentials to access the dashboard
5. **Configure broker**: Navigate to Settings → Broker Setup

---

## Project Structure

Understanding the codebase structure will help you contribute effectively:

```
openalgo/
├── app.py                    # Main Flask application entry point
├── blueprints/               # Flask blueprints for web routes
│   ├── auth.py              # Authentication routes (login, logout, setup)
│   ├── dashboard.py         # Main dashboard views
│   ├── settings.py          # Settings and configuration pages
│   └── ...
├── broker/                   # Broker-specific implementations
│   ├── aliceblue/           # AliceBlue broker integration
│   ├── angel/               # AngelOne broker integration
│   ├── dhan/                # Dhan broker integration
│   ├── zerodha/             # Zerodha broker integration
│   └── .../                 # 20+ other brokers
├── database/                 # Database models and utilities
│   ├── auth_db.py           # User authentication models
│   ├── apilog_db.py         # API logging models
│   └── ...
├── restx_api/                # REST API endpoints (Flask-RESTX)
│   ├── account/             # Account and portfolio APIs
│   ├── order/               # Order management APIs
│   ├── data/                # Market data APIs
│   └── ...
├── services/                 # Business logic layer
│   ├── order_service.py     # Order processing logic
│   ├── data_service.py      # Market data handling
│   └── ...
├── utils/                    # Utility functions and helpers
│   ├── api_utils.py         # API helper functions
│   ├── encryption.py        # Security and encryption
│   └── ...
├── templates/                # Jinja2 HTML templates
│   ├── auth/                # Authentication pages
│   ├── dashboard/           # Dashboard views
│   └── layouts/             # Base layouts
├── static/                   # Static assets
│   ├── css/                 # Compiled CSS (don't edit directly!)
│   ├── js/                  # JavaScript files
│   └── images/              # Image assets
├── src/                      # Source files for compilation
│   └── css/
│       └── styles.css       # Source CSS (edit this!)
├── strategies/               # Trading strategy examples
│   ├── data.ipynb           # Data analysis examples
│   └── ...
├── websocket_proxy/          # WebSocket server implementation
│   ├── server.py            # Main WebSocket proxy server
│   └── adapters/            # Broker-specific WebSocket adapters
├── sandbox/                  # Sandbox/paper trading mode
├── test/                     # Test files
├── docs/                     # Documentation files
├── mcp/                      # Model Context Protocol integration
├── requirements.txt          # Python dependencies
├── package.json              # Node.js dependencies
├── tailwind.config.mjs       # Tailwind configuration
└── .env                      # Environment configuration (create from .sample.env)
```

### Key Directories

- **`broker/`**: Each subdirectory contains a complete broker integration with authentication, order APIs, data APIs, and symbol mapping
- **`restx_api/`**: RESTful API endpoints with automatic Swagger documentation at `/api/docs`
- **`blueprints/`**: Web routes and views for the UI
- **`templates/`**: HTML templates using Jinja2 and Tailwind/DaisyUI classes
- **`websocket_proxy/`**: Real-time market data streaming infrastructure
- **`services/`**: Business logic separated from route handlers
- **`utils/`**: Shared utility functions used across the application

---

## Development Workflow

### 1. Fork and Clone

```bash
# Fork the repository on GitHub (click Fork button)
# Clone your fork
git clone https://github.com/YOUR_USERNAME/openalgo.git
cd openalgo

# Add upstream remote
git remote add upstream https://github.com/marketcalls/openalgo.git

# Verify remotes
git remote -v
```

### 2. Frontend Build Assets (Auto-Built by CI)

The `/frontend/dist` folder contains pre-built frontend assets. **CI automatically rebuilds and commits these assets** when changes are merged to main.

**How it works:**
- PRs are tested with a fresh frontend build (but not committed)
- When merged to main, CI automatically:
  1. Builds the frontend (`npm run build`)
  2. Commits the updated `/frontend/dist` to the repo
  3. Pushes Docker image to Docker Hub

**For Contributors:**
- You can include `/frontend/dist` changes in your PR, OR
- Let CI auto-build after merge (recommended)
- Focus on source code changes - CI handles the build

**Setup (optional - to ignore local dist changes):**
```bash
git update-index --skip-worktree frontend/dist/*
```

> **Note:** The CI uses `[skip ci]` when auto-committing dist to prevent infinite loops.

### 3. Create a Feature Branch

```bash
# Update your main branch
git checkout main
git pull upstream main

# Create a new branch for your feature
# Branch naming convention:
# - feature/feature-name    : New features
# - bugfix/bug-name         : Bug fixes
# - docs/doc-name           : Documentation
# - refactor/refactor-name  : Code refactoring
git checkout -b feature/your-feature-name
```

### 4. Make Your Changes

Follow these guidelines while developing:

#### Code Style

- **Python**: Follow PEP 8 style guide
- **Formatting**: Use 4 spaces for indentation
- **Line Length**: Maximum 100 characters recommended
- **Imports**: Group by standard library, third-party, local
- **Docstrings**: Use Google-style docstrings

Example:
```python
def calculate_margin(symbol, quantity, price, product_type):
    """Calculate margin requirement for an order.

    Args:
        symbol (str): Trading symbol (e.g., 'NSE:SBIN-EQ')
        quantity (int): Number of shares
        price (float): Order price
        product_type (str): Product type ('CNC', 'MIS', 'NRML')

    Returns:
        dict: Margin details with required margin and available margin

    Raises:
        ValueError: If invalid product type provided
    """
    # Implementation here
    pass
```

#### Commit Messages

We follow **Conventional Commits** specification:

- `feat:` - New features
- `fix:` - Bug fixes
- `docs:` - Documentation changes
- `style:` - Code style changes (formatting, no logic change)
- `refactor:` - Code refactoring
- `test:` - Adding or updating tests
- `chore:` - Maintenance tasks

Examples:
```bash
git commit -m "feat: add Groww broker integration"
git commit -m "fix: correct margin calculation for options"
git commit -m "docs: update WebSocket setup instructions"
git commit -m "refactor: optimize order processing pipeline"
```

### 5. Test Your Changes

```bash
# Run the application in development mode
python app.py

# Test specific features:
# 1. Web UI: http://127.0.0.1:5000
# 2. API Docs: http://127.0.0.1:5000/api/docs
# 3. API Analyzer: http://127.0.0.1:5000/analyzer
```

#### Testing Checklist

- [ ] Application starts without errors
- [ ] All existing features still work
- [ ] New feature works as expected
- [ ] Error handling is proper
- [ ] UI is responsive on mobile
- [ ] Browser console has no errors
- [ ] API endpoints return correct responses
- [ ] WebSocket connections work (if applicable)

### 6. CSS Compilation (for UI changes)

If you modified any HTML templates or Tailwind classes:

```bash
# Development: Auto-compile on changes
npm run dev

# Production: Create minified build
npm run build

# Never edit static/css/main.css directly!
# Only edit src/css/styles.css
```

### 7. Push to Your Fork

```bash
# Add your changes
git add .

# Commit with conventional commit message
git commit -m "feat: add your feature description"

# Push to your fork
git push origin feature/your-feature-name
```

### 8. Create a Pull Request

1. Go to your fork on GitHub
2. Click **"Compare & pull request"**
3. Fill out the PR template:
   - **Title**: Clear, descriptive title
   - **Description**: What does this PR do?
   - **Related Issues**: Link related issues (e.g., "Closes #123")
   - **Screenshots**: For UI changes, include before/after screenshots
   - **Testing**: Describe how you tested the changes
   - **Checklist**: Complete the PR checklist

Example PR Description:
```markdown
## Description
Adds integration for Groww broker with all standard APIs.

## Related Issues
Closes #456

## Changes Made
- Implemented Groww authentication API
- Added order placement and management
- Integrated market data APIs
- Created symbol mapping utilities
- Added Groww-specific WebSocket adapter

## Testing
- Tested on Python 3.12
- Verified all API endpoints work correctly
- Tested order flow from placement to execution
- Validated WebSocket streaming

## Screenshots
[Attach screenshots if UI changes]

## Checklist
- [x] Code follows PEP 8 guidelines
- [x] Added docstrings to all functions
- [x] Tested locally and verified working
- [x] Updated documentation
- [x] No breaking changes to existing code
```

---

## Contributing Guidelines

### What Can You Contribute?

#### For First-Time Contributors 🌱

Great ways to get started:

1. **Documentation**
   - Fix typos in README or docs
   - Improve installation instructions
   - Add examples and tutorials
   - Translate documentation to other languages

2. **Bug Fixes**
   - Check [issues labeled "good first issue"](https://github.com/marketcalls/openalgo/labels/good%20first%20issue)
   - Fix minor bugs and edge cases
   - Improve error messages

3. **UI Improvements**
   - Enhance styling with Tailwind/DaisyUI
   - Improve mobile responsiveness
   - Add loading states and animations
   - Fix layout issues

4. **Examples**
   - Add strategy examples in `/strategies`
   - Create tutorial notebooks
   - Document common use cases

#### For Experienced Contributors 🚀

More advanced contributions:

1. **New Broker Integration**
   - Add support for new brokers
   - Complete implementation guide in next section
   - Requires understanding of broker APIs

2. **API Endpoints**
   - Implement new trading features
   - Enhance existing endpoints
   - Add new data sources

3. **Performance Optimization**
   - Optimize database queries
   - Improve caching strategies
   - Reduce API latency
   - Profile and optimize bottlenecks

4. **WebSocket Features**
   - Add new streaming capabilities
   - Improve real-time performance
   - Add broker adapters

5. **Testing Infrastructure**
   - Write unit tests
   - Add integration tests
   - Set up CI/CD pipelines
   - Create test fixtures

6. **Security Enhancements**
   - Audit security vulnerabilities
   - Improve authentication
   - Enhance encryption
   - Add security features

---

## Testing

### Manual Testing

OpenAlgo primarily uses manual testing currently:

1. **Application Testing**
   ```bash
   # Start the application
   python app.py

   # Test your changes through the UI
   ```

2. **API Testing**
   - Use the built-in Swagger UI at `http://127.0.0.1:5000/api/docs`
   - Test API endpoints with Postman or curl
   - Verify request/response formats

3. **Cross-Browser Testing**
   - Test in Chrome, Firefox, Safari, Edge
   - Verify mobile responsiveness
   - Check for console errors

4. **Error Handling**
   - Test with invalid inputs
   - Verify proper error messages
   - Ensure graceful degradation

### Automated Testing

Some test files are available in the `/test` directory:

```bash
# Run specific test files
python -m pytest test/test_broker.py
python -m pytest test/test_cache_performance.py

# Run all tests (if pytest is configured)
python -m pytest test/ -v
```

### Writing Tests

When adding tests, follow this structure:

```python
# test/test_feature.py
import pytest
from app import create_app

@pytest.fixture
def client():
    app = create_app()
    app.config['TESTING'] = True
    with app.test_client() as client:
        yield client

def test_feature(client):
    """Test your feature here."""
    response = client.get('/api/v1/endpoint')
    assert response.status_code == 200
    assert 'expected_key' in response.json
```

---

## Adding a New Broker

One of the most valuable contributions is adding support for new brokers. Here's a comprehensive guide:

### 1. Broker Integration Structure

Create a new directory under `/broker/your_broker_name/`:

```
broker/your_broker_name/
├── api/
│   ├── auth_api.py           # Authentication and session management
│   ├── order_api.py          # Order placement, modification, cancellation
│   ├── data.py               # Market data, quotes, historical data
│   └── funds.py              # Account balance and margin
├── database/
│   └── master_contract_db.py # Symbol master contract management
├── mapping/
│   ├── order_data.py         # Transform OpenAlgo format to broker format
│   └── transform_data.py     # General data transformations
├── websocket/
│   └── broker_adapter.py     # WebSocket adapter for live data
└── plugin.json               # Broker configuration metadata
```

### 2. Implement Required Modules

#### 2.1 Authentication API (`api/auth_api.py`)

```python
"""Authentication module for BrokerName."""

from flask import request, jsonify, session
import http.client
import json

def authenticate_broker(data):
    """Authenticate user with broker.

    Args:
        data (dict): Authentication credentials

    Returns:
        dict: Authentication response with status and token
    """
    # Implementation here
    pass

def get_auth_token():
    """Retrieve stored authentication token.

    Returns:
        str: Active auth token or None
    """
    # Implementation here
    pass
```

#### 2.2 Order API (`api/order_api.py`)

```python
"""Order management module for BrokerName."""

def place_order_api(data):
    """Place a new order with the broker.

    Args:
        data (dict): Order details (symbol, quantity, price, etc.)

    Returns:
        dict: Order response with order_id and status
    """
    pass

def modify_order_api(data):
    """Modify an existing order."""
    pass

def cancel_order_api(order_id):
    """Cancel an order."""
    pass

def get_order_book():
    """Get all orders for the day."""
    pass

def get_trade_book():
    """Get all executed trades."""
    pass

def get_positions():
    """Get current open positions."""
    pass

def get_holdings():
    """Get demat holdings."""
    pass
```

#### 2.3 Data API (`api/data.py`)

```python
"""Market data module for BrokerName."""

def get_quotes(symbols):
    """Get real-time quotes for symbols."""
    pass

def get_market_depth(symbol):
    """Get market depth/order book."""
    pass

def get_historical_data(symbol, interval, start_date, end_date):
    """Get historical OHLC data."""
    pass
```

#### 2.4 Plugin Configuration (`plugin.json`)

```json
{
  "broker_name": "brokername",
  "display_name": "Broker Name",
  "version": "1.0.0",
  "auth_type": "oauth2",
  "api_base_url": "https://api.broker.com",
  "features": {
    "place_order": true,
    "modify_order": true,
    "cancel_order": true,
    "websocket": true,
    "market_depth": true,
    "historical_data": true
  }
}
```

### 3. Testing Your Broker Integration

1. Add broker to `VALID_BROKERS` in `.env`
2. Configure broker credentials
3. Test authentication flow
4. Test each API endpoint via Swagger UI
5. Test WebSocket streaming (if supported)
6. Validate error handling

### 4. Documentation

Create a setup guide in `/docs/broker_brokername.md`:

```markdown
# Broker Name Integration Guide

## Prerequisites
- Active trading account with Broker Name
- API credentials (API Key, Secret)

## Setup Steps
1. Login to Broker Name dashboard
2. Generate API credentials
3. Configure in OpenAlgo settings

## Features Supported
- [x] Order placement
- [x] Market data
- [x] WebSocket streaming
- [ ] Basket orders (planned)

## Known Limitations
- Maximum 100 orders per minute
- Historical data limited to 1 year
```

### 5. Reference Implementation

Study existing broker implementations as reference:
- `/broker/zerodha/` - Most complete implementation
- `/broker/dhan/` - Modern API design
- `/broker/angel/` - WebSocket streaming

---

## UI Development

### Working with Tailwind & DaisyUI

#### CSS Workflow

1. **NEVER edit** `/static/css/main.css` directly (it's auto-generated!)

2. **Edit source files**:
   - Custom CSS: `/src/css/styles.css`
   - Tailwind classes: Directly in HTML templates (`/templates/`)

3. **Compile CSS**:
   ```bash
   # Development mode with auto-watch
   npm run dev

   # Production build (minified)
   npm run build
   ```

4. **Before committing**: Always run production build
   ```bash
   npm run build
   git add static/css/main.css
   ```

#### Using DaisyUI Components

OpenAlgo uses [DaisyUI](https://daisyui.com/components/) component library:

```html
<!-- Button component -->
<button class="btn btn-primary">Place Order</button>

<!-- Card component -->
<div class="card bg-base-100 shadow-xl">
  <div class="card-body">
    <h2 class="card-title">Portfolio Value</h2>
    <p>₹1,25,000</p>
  </div>
</div>

<!-- Alert component -->
<div class="alert alert-success">
  <span>Order placed successfully!</span>
</div>
```

#### Theme System

OpenAlgo uses three themes:

1. **Light** - Default theme
2. **Dark** - Dark mode
3. **Garden** - Analyzer/testing mode

Use theme-aware classes:
```html
<!-- Use semantic colors, not hardcoded -->
<div class="bg-base-100 text-base-content">
  <!-- Automatically adapts to theme -->
</div>

<!-- Don't use hardcoded colors -->
<div class="bg-white text-black">
  <!-- Wrong: Won't adapt to dark theme -->
</div>
```

#### Responsive Design

Always use responsive Tailwind classes:
```html
<!-- Mobile-first responsive grid -->
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  <div>Column 1</div>
  <div>Column 2</div>
  <div>Column 3</div>
</div>

<!-- Responsive text sizes -->
<h1 class="text-2xl md:text-3xl lg:text-4xl">Heading</h1>
```

#### Tailwind Configuration

The Tailwind config is in `tailwind.config.mjs`:

```javascript
export default {
  content: [
    './templates/**/*.html',
    './static/js/**/*.js',
  ],
  plugins: [
    require('daisyui'),
  ],
  daisyui: {
    themes: ["light", "dark", "garden"],
  },
}
```

---

## Documentation

Good documentation is crucial for open-source projects.

### Code Documentation

1. **Python Docstrings** - Use Google-style:
   ```python
   def place_order(symbol, quantity, price, order_type):
       """Place a trading order.

       Args:
           symbol (str): Trading symbol in OpenAlgo format
           quantity (int): Number of shares/contracts
           price (float): Order price (0 for market orders)
           order_type (str): Order type ('MARKET', 'LIMIT', 'SL')

       Returns:
           dict: Order response with order_id and status

       Raises:
           ValueError: If invalid order_type provided
           ConnectionError: If broker API unreachable
       """
       pass
   ```

2. **Inline Comments** - Explain complex logic:
   ```python
   # Calculate margin multiplier based on product type
   # MIS (intraday) requires 20% margin, CNC requires 100%
   margin_multiplier = 0.2 if product_type == 'MIS' else 1.0
   ```

3. **Type Hints** - Use for better IDE support:
   ```python
   from typing import Dict, List, Optional

   def get_positions(user_id: int) -> List[Dict[str, any]]:
       """Get user positions."""
       pass
   ```

### User Documentation

1. **README Updates** - For new features, update main README.md

2. **API Documentation** - Use Flask-RESTX decorators:
   ```python
   @api.route('/placeorder')
   class PlaceOrder(Resource):
       @api.doc(description='Place a new order')
       @api.expect(order_model)
       @api.marshal_with(order_response_model)
       def post(self):
           """Place a trading order."""
           pass
   ```

3. **Feature Guides** - Create detailed guides in `/docs`:
   - `/docs/websocket_usage.md`
   - `/docs/broker_integration_guide.md`
   - `/docs/security_best_practices.md`

---

## Best Practices

### Security

1. **Never commit sensitive data**
   ```bash
   # Bad - Never do this!
   API_KEY = 'abc123xyz'

   # Good - Use environment variables
   import os
   API_KEY = os.getenv('BROKER_API_KEY')
   ```

2. **Validate all inputs**
   ```python
   def place_order(data):
       # Validate quantity is positive
       if data.get('quantity', 0) <= 0:
           raise ValueError('Quantity must be positive')

       # Validate order type
       valid_types = ['MARKET', 'LIMIT', 'SL', 'SLM']
       if data.get('order_type') not in valid_types:
           raise ValueError('Invalid order type')
   ```

3. **Use parameterized queries**
   ```python
   # Bad - SQL injection vulnerability!
   query = f"SELECT * FROM orders WHERE user_id = {user_id}"

   # Good - Parameterized with SQLAlchemy
   orders = Order.query.filter_by(user_id=user_id).all()
   ```

4. **Follow OWASP guidelines**
   - Enable CSRF protection (already configured)
   - Use HTTPS in production
   - Implement rate limiting (already configured)
   - Sanitize user inputs

### Performance

1. **Optimize database queries**
   ```python
   # Bad - N+1 query problem
   for user in users:
       orders = Order.query.filter_by(user_id=user.id).all()

   # Good - Use eager loading
   from sqlalchemy.orm import joinedload
   users = User.query.options(joinedload(User.orders)).all()
   ```

2. **Use caching**
   ```python
   from cachetools import TTLCache

   # Cache symbol data for 5 minutes
   symbol_cache = TTLCache(maxsize=1000, ttl=300)

   def get_symbol_info(symbol):
       if symbol in symbol_cache:
           return symbol_cache[symbol]

       # Fetch from database
       info = fetch_symbol_from_db(symbol)
       symbol_cache[symbol] = info
       return info
   ```

3. **Minimize API calls**
   ```python
   # Bad - Multiple API calls
   for symbol in symbols:
       quote = broker.get_quote(symbol)

   # Good - Batch API call
   quotes = broker.get_quotes_batch(symbols)
   ```

### Code Quality

1. **Write self-documenting code**
   ```python
   # Bad - Unclear variable names
   def calc(s, q, p):
       return s * q * p * 0.1

   # Good - Clear and descriptive
   def calculate_order_value(symbol_price, quantity, price, multiplier):
       """Calculate total order value with multiplier."""
       return symbol_price * quantity * price * multiplier
   ```

2. **Keep functions small and focused**
   ```python
   # Bad - Function does too many things
   def process_order(order_data):
       validate_data(order_data)
       calculate_margin(order_data)
       check_balance(order_data)
       place_with_broker(order_data)
       log_order(order_data)
       send_notification(order_data)

   # Good - Single responsibility
   def process_order(order_data):
       """Process and place order."""
       validated_data = validate_order(order_data)
       if has_sufficient_margin(validated_data):
           return place_order_with_broker(validated_data)
       raise InsufficientMarginError()
   ```

3. **Handle errors gracefully**
   ```python
   try:
       response = broker_api.place_order(order_data)
       return {'status': 'success', 'data': response}
   except ConnectionError as e:
       logger.error(f"Broker API connection failed: {e}")
       return {'status': 'error', 'message': 'Unable to connect to broker'}
   except ValueError as e:
       logger.warning(f"Invalid order data: {e}")
       return {'status': 'error', 'message': str(e)}
   except Exception as e:
       logger.exception(f"Unexpected error: {e}")
       return {'status': 'error', 'message': 'An unexpected error occurred'}
   ```

---

## Troubleshooting

### Common Issues

#### CSS Not Updating

```bash
# Clear browser cache
# Then rebuild CSS:
npm run build

# If still not working, check:
# 1. Is npm installed? (node --version)
# 2. Are node_modules present? (npm install)
# 3. Check for build errors in terminal
```

#### Python Dependencies

```bash
# Create fresh virtual environment
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows

# Upgrade pip
pip install --upgrade pip

# Reinstall dependencies
pip install -r requirements.txt
```

#### WebSocket Connection Issues

```bash
# Check WebSocket configuration in .env:
WEBSOCKET_HOST='127.0.0.1'
WEBSOCKET_PORT='8765'

# Ensure only one worker with Gunicorn:
gunicorn --worker-class eventlet -w 1 app:app

# Check firewall settings
```

#### Database Locked Errors

```bash
# SQLite database locked - close all connections
# Restart the application
python app.py
```

---

## Getting Help

### Support Channels

- **Discord**: Join our [Discord server](https://discord.com/invite/UPh7QPsNhP) for real-time help
- **GitHub Discussions**: Ask questions in [GitHub Discussions](https://github.com/marketcalls/openalgo/discussions)
- **Documentation**: Check [docs.openalgo.in](https://docs.openalgo.in)
- **GitHub Issues**: Report bugs in [Issues](https://github.com/marketcalls/openalgo/issues)

### Before Asking for Help

1. **Search existing issues** - Your question might already be answered
2. **Check documentation** - Review docs at docs.openalgo.in
3. **Review error logs** - Include error messages when asking for help
4. **Provide context** - Share your environment (OS, Python version, broker)

### Asking Good Questions

When asking for help, include:

1. **Clear description** of the problem
2. **Steps to reproduce** the issue
3. **Expected behavior** vs **actual behavior**
4. **Error messages** (full stack trace)
5. **Environment details**:
   - OS and version
   - Python version (`python --version`)
   - OpenAlgo version
   - Broker being used

Example:
```
**Problem**: WebSocket connection fails when using Zerodha broker

**Steps to reproduce**:
1. Start OpenAlgo with `python app.py`
2. Login with Zerodha credentials
3. Navigate to Market Watch
4. WebSocket connection shows "Disconnected"

**Expected**: WebSocket should connect and stream live data

**Actual**: Connection fails with error "Connection refused"

**Environment**:
- OS: Windows 11
- Python: 3.12.1
- OpenAlgo: Latest main branch
- Broker: Zerodha
- Error log: [attach error log]
```

---

## Code Review Process

After submitting your pull request:

1. **Automated Checks**
   - Ensure all checks pass
   - Fix any failing checks before requesting review

2. **Review Feedback**
   - Address reviewer comments promptly
   - Ask questions if feedback is unclear
   - Make requested changes in new commits

3. **Updates**
   - Push additional commits to your branch
   - No need to create a new PR
   - Use `git push origin feature/your-feature-name`

4. **Approval & Merge**
   - Once approved, maintainers will merge
   - Your contribution will be in the next release!

5. **Be Patient**
   - Reviews may take a few days
   - Maintainers are volunteers
   - Ping politely if no response after a week

---

## Recognition & Community

### Contributors

We value all contributions! Contributors will be:

- **Listed in contributors section** on GitHub
- **Mentioned in release notes** for significant contributions
- **Part of the OpenAlgo community** on Discord
- **Eligible for contributor benefits** (coming soon)

### Community Guidelines

Be respectful and follow these principles:

1. **Be Respectful** - Treat everyone with respect
2. **Be Constructive** - Provide helpful feedback
3. **Be Patient** - Remember everyone is learning
4. **Be Inclusive** - Welcome contributors of all skill levels
5. **Be Professional** - Keep discussions focused on code

---

## Quick Reference Links

- **Repository**: [github.com/marketcalls/openalgo](https://github.com/marketcalls/openalgo)
- **Issue Tracker**: [github.com/marketcalls/openalgo/issues](https://github.com/marketcalls/openalgo/issues)
- **Documentation**: [docs.openalgo.in](https://docs.openalgo.in)
- **Discord**: [discord.com/invite/UPh7QPsNhP](https://discord.com/invite/UPh7QPsNhP)
- **PyPI Package**: [pypi.org/project/openalgo](https://pypi.org/project/openalgo)
- **YouTube**: [youtube.com/@openalgoHQ](https://youtube.com/@openalgoHQ)
- **Twitter/X**: [@openalgoHQ](https://twitter.com/openalgoHQ)

---

## License

OpenAlgo is released under the **AGPL v3.0 License**. See the [LICENSE](License.md) file for details.

By contributing to OpenAlgo, you agree that your contributions will be licensed under the AGPL v3.0 License.

---

## Thank You! 

Thank you for contributing to OpenAlgo! Your efforts help democratize algorithmic trading and empower traders worldwide. Every line of code, documentation improvement, and bug report makes a difference.

**Happy coding, and welcome to the OpenAlgo community!** 

---

*Built by traders, for traders - making algo trading accessible to everyone.*
