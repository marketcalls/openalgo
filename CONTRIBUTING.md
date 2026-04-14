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
9. [Frontend Development](#frontend-development)
10. [Documentation](#documentation)
11. [Best Practices](#best-practices)
12. [Getting Help](#getting-help)

---

## Technology Stack

OpenAlgo uses a **Python Flask** backend with a **React 19** single-page application frontend.

### Backend Technologies

- **Python 3.12+** - Core programming language
- **uv** - Fast Python package manager (replaces pip/venv)
- **Flask 3.1+** - Lightweight web framework
- **Flask-RESTX** - RESTful API with auto-generated Swagger documentation
- **SQLAlchemy 2.0+** - Database ORM for data persistence
- **Flask-SocketIO 5.6+** - Real-time WebSocket connections for live updates
- **Flask-Login** - User session management and authentication
- **Flask-WTF** - Form validation and CSRF protection
- **Ruff** - Fast Python linter and formatter

### Frontend Technologies

- **React 19** - Component-based UI library
- **TypeScript 5.9+** - Type-safe JavaScript
- **Vite 7+** - Fast build tool and dev server
- **TailwindCSS 4** - Utility-first CSS framework
- **shadcn/ui** (Radix UI) - Accessible component primitives
- **TanStack Query 5** - Server state management
- **Zustand 5** - Client state management
- **React Router 7** - Client-side routing
- **Plotly.js / Lightweight Charts** - Data visualization
- **Socket.IO Client** - Real-time communication
- **Biome.js** - Fast linter and formatter
- **Vitest** - Unit testing framework
- **Playwright** - End-to-end testing

### Trading & Data Libraries

- **pandas 2.3+** - Data manipulation and analysis
- **numpy 2.0+** - Numerical computing
- **DuckDB** - Historical market data storage
- **httpx** - Modern HTTP client with HTTP/2 support
- **websockets 15.0+** - WebSocket client and server
- **pyzmq** - ZeroMQ for high-performance message queue
- **APScheduler** - Background task scheduling
- **scipy / py_vollib / numba** - Options analytics and Greeks

### Security & Performance

- **argon2-cffi** - Secure password hashing
- **cryptography** - Token encryption
- **Flask-Limiter** - Rate limiting
- **Flask-CORS** - CORS protection

> [!IMPORTANT]
> You will need **Python 3.12+**, **Node.js 20/22/24**, and the **uv** package manager.

---

## Development Setup

### Prerequisites

Before you begin, make sure you have the following installed:

- **Python 3.12+** - [Download Python](https://www.python.org/downloads/)
- **Node.js 20, 22, or 24** - [Download Node.js](https://nodejs.org/)
- **Git** - [Download Git](https://git-scm.com/downloads)
- **Code Editor** - VS Code recommended with extensions:
  - Python
  - Pylance
  - Biome
  - Tailwind CSS IntelliSense
- **Basic Knowledge** of Flask and React

### Install Dependencies

```bash
# Clone the repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Install uv package manager (if not already installed)
pip install uv

# Sync Python dependencies (uv handles virtualenv automatically)
uv sync

# Build React frontend (required before first run)
cd frontend
npm install
npm run build
cd ..
```

> [!IMPORTANT]
> **Always use `uv run` to run Python commands.** Never use global Python or manually manage virtual environments. The `uv` tool automatically creates and manages a `.venv` for the project.

### Configure Environment

```bash
# Copy the sample environment file
cp .sample.env .env

# Generate secure random keys for APP_KEY and API_KEY_PEPPER:
uv run python -c "import secrets; print(secrets.token_hex(32))"

# Edit .env and update:
# 1. APP_KEY (paste generated key)
# 2. API_KEY_PEPPER (paste another generated key)
# 3. VALID_BROKERS (comma-separated list of brokers to enable)
# 4. Broker API credentials
```

> [!NOTE]
> **Static IP whitelisting:** Many Indian brokers require you to whitelist a static IP address when generating API keys and secrets. If you are developing locally, you may need to whitelist your public IP. For cloud/VPS deployments, use the server's static IP. Check your broker's API documentation for specific requirements.

---

## Local Development

### Run the Application

```bash
# Development mode (auto-reloads on backend code changes)
uv run app.py

# Application will be available at http://127.0.0.1:5000
```

### Development Workflow with Multiple Terminals

For the best development experience when working on the frontend, use two terminals:

**Terminal 1 - React Dev Server (hot reload):**
```bash
cd frontend
npm run dev
# Frontend dev server at http://localhost:5173 with hot module replacement
```

**Terminal 2 - Flask Backend:**
```bash
uv run app.py
# Backend API at http://127.0.0.1:5000
```

> **Note:** The React dev server proxies API requests to the Flask backend. For production testing, build the frontend with `npm run build` and access everything through Flask at port 5000.

### Production Mode (Linux only)

```bash
# Run with Gunicorn
uv run gunicorn --worker-class eventlet -w 1 app:app

# IMPORTANT: Use -w 1 (one worker) for WebSocket compatibility
```

### First Time Setup

1. **Access the application**: Navigate to `http://127.0.0.1:5000`
2. **Setup account**: Go to `http://127.0.0.1:5000/setup`
3. **Create admin user**: Fill in the setup form
4. **Login**: Use your credentials to access the dashboard
5. **Configure broker**: Navigate to Settings and set up your broker

### Access Points

- **Main app**: http://127.0.0.1:5000
- **React frontend**: http://127.0.0.1:5000/react
- **Swagger API docs**: http://127.0.0.1:5000/api/docs
- **API Analyzer**: http://127.0.0.1:5000/analyzer

---

## Project Structure

Understanding the codebase structure will help you contribute effectively:

```
openalgo/
├── app.py                    # Main Flask application entry point
├── pyproject.toml            # Python dependencies & tool config (uv/ruff/pytest)
├── frontend/                 # React 19 SPA (TypeScript + Vite)
│   ├── src/
│   │   ├── components/       # React components (shadcn/ui based)
│   │   ├── pages/            # Route-level page components
│   │   ├── hooks/            # Custom React hooks
│   │   ├── api/              # API client functions
│   │   ├── stores/           # Zustand state stores
│   │   ├── lib/              # Utility functions
│   │   └── App.tsx           # Root component with routing
│   ├── package.json          # Node.js dependencies
│   ├── biome.json            # Biome linter/formatter config
│   ├── tsconfig.json         # TypeScript configuration
│   ├── vite.config.ts        # Vite build configuration
│   └── dist/                 # Production build output (gitignored)
├── blueprints/               # Flask blueprints for web routes
│   ├── auth.py               # Authentication routes
│   ├── react_app.py          # Serves React SPA from frontend/dist/
│   └── ...
├── broker/                   # Broker integrations (24+ brokers)
│   ├── zerodha/              # Reference implementation
│   ├── dhan/                 # Modern API design
│   ├── angel/                # AngelOne integration
│   └── .../                  # Each broker follows standardized structure
├── restx_api/                # REST API endpoints (/api/v1/)
├── services/                 # Business logic layer
├── database/                 # SQLAlchemy models and database utilities
├── utils/                    # Shared utilities and helpers
├── websocket_proxy/          # Unified WebSocket server (port 8765)
├── test/                     # Python test files
├── strategies/               # Trading strategy examples
├── db/                       # SQLite/DuckDB database files
└── .env                      # Environment config (create from .sample.env)
```

### Key Directories

- **`frontend/`**: React 19 SPA with TypeScript, built with Vite and served by Flask via `blueprints/react_app.py`
- **`broker/`**: Each subdirectory contains a complete broker integration with `api/`, `database/`, `mapping/`, `streaming/`, and `plugin.json`
- **`restx_api/`**: RESTful API endpoints with automatic Swagger documentation at `/api/docs`
- **`blueprints/`**: Flask route handlers for UI pages and webhooks
- **`services/`**: Business logic separated from route handlers
- **`websocket_proxy/`**: Real-time market data streaming via unified WebSocket proxy
- **`database/`**: 5 separate databases for isolation (main, logs, latency, sandbox, historify)

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

> **Important: Disable GitHub Actions on Your Fork**
>
> After forking, go to your fork's **Settings → Actions → General** (`https://github.com/YOUR_USERNAME/openalgo/settings/actions`) and select **"Disable actions"** under Actions permissions. This prevents CI workflows (frontend builds, Docker pushes) from running on your fork unnecessarily — those workflows are only meant to run on the upstream repository.

### 2. Frontend Build Assets (Auto-Built by CI)

The `/frontend/dist` directory is **gitignored** and not tracked in the repository. CI automatically builds the frontend when changes are merged to main.

**How it works:**
- PRs are tested with a fresh frontend build (but not committed)
- When merged to main, CI automatically:
  1. Builds the frontend (`cd frontend && npm run build`)
  2. Pushes Docker image to Docker Hub

**For Contributors:**
- Build locally for development: `cd frontend && npm install && npm run build`
- Do NOT commit `frontend/dist/` — it is gitignored
- Focus on source code changes — CI handles production builds

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

#### Python Code Style

- Follow PEP 8 style guide
- Use 4 spaces for indentation
- Maximum 100 characters line length (configured in Ruff)
- Imports: Standard library → Third-party → Local
- Use Google-style docstrings

Run the linter:
```bash
# Check Python code
uv run ruff check .

# Auto-fix issues
uv run ruff check --fix .

# Format code
uv run ruff format .
```

#### React/TypeScript Code Style

- Follow Biome.js rules (configured in `frontend/biome.json`)
- Use functional components with hooks
- Component files use PascalCase: `MyComponent.tsx`
- Use TanStack Query for server state, Zustand for client state

Run the linter:
```bash
cd frontend

# Lint code
npm run lint

# Format code
npm run format

# Lint + format in one command
npm run check
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
# Run Python tests
uv run pytest test/ -v

# Run React tests
cd frontend
npm test

# Run end-to-end tests
npm run e2e

# Manual testing:
# 1. Web UI: http://127.0.0.1:5000
# 2. React UI: http://127.0.0.1:5000/react
# 3. API Docs: http://127.0.0.1:5000/api/docs
# 4. API Analyzer: http://127.0.0.1:5000/analyzer
```

#### Testing Checklist

- [ ] Application starts without errors (`uv run app.py`)
- [ ] All existing features still work
- [ ] New feature works as expected
- [ ] Python tests pass (`uv run pytest test/ -v`)
- [ ] Frontend tests pass (`cd frontend && npm test`)
- [ ] No TypeScript errors (`cd frontend && npm run build`)
- [ ] No linting errors (Ruff for Python, Biome for frontend)
- [ ] API endpoints return correct responses
- [ ] WebSocket connections work (if applicable)

### 6. Push to Your Fork

```bash
# Add your changes
git add .

# Commit with conventional commit message
git commit -m "feat: add your feature description"

# Push to your fork
git push origin feature/your-feature-name
```

### 7. Create a Pull Request

1. Go to your fork on GitHub
2. Click **"Compare & pull request"**
3. Fill out the PR template:
   - **Title**: Clear, descriptive title
   - **Description**: What does this PR do?
   - **Related Issues**: Link related issues (e.g., "Closes #123")
   - **Screenshots**: For UI changes, include before/after screenshots
   - **Testing**: Describe how you tested the changes
   - **Checklist**: Complete the PR checklist

---

## Contributing Guidelines

### Contribution Policy: One Feature or One Fix at a Time

OpenAlgo follows a strict **incremental contribution** standard. We require all contributions to be submitted as:

- **One feature** per pull request, OR
- **One fix** per pull request

**Why this matters:**

OpenAlgo supports **a growing list of brokers**, and every change must be validated across this broad surface area. Large integrations submitted in a single PR require extensive manual testing and verification that is not practical for the maintainers to review all at once.

Additionally, many contributions today are developed with AI assistance, which can accelerate development substantially but also increases the need for careful human review, testing, and incremental verification before acceptance into a shared upstream project.

**What this means in practice:**

- Break large features into small, self-contained pull requests
- Each PR should be independently reviewable and testable
- Submit them sequentially — wait for one to be reviewed before sending the next
- Large monolithic PRs or full-project integrations will not be accepted in their current form
- **Exception — New broker integrations** may be submitted as a single PR since they are self-contained within their own `broker/` directory and don't modify core platform code

**If you have a large integration or project built on OpenAlgo:**

We appreciate and encourage projects built on top of OpenAlgo (it's why we're open-source!). However, we cannot merge large codebases as a single contribution. Instead, extract individual improvements, fixes, or self-contained features and submit them separately. This gives each contribution a much better chance of being reviewed and accepted.

---

### What Can You Contribute?

#### For First-Time Contributors

Great ways to get started:

1. **Documentation**
   - Fix typos in README or docs
   - Improve installation instructions
   - Add examples and tutorials

2. **Bug Fixes**
   - Check [issues labeled "good first issue"](https://github.com/marketcalls/openalgo/labels/good%20first%20issue)
   - Fix minor bugs and edge cases
   - Improve error messages

3. **UI Improvements**
   - Enhance React components
   - Improve mobile responsiveness
   - Add loading states and animations
   - Fix layout issues

4. **Examples**
   - Add strategy examples in `/strategies`
   - Create tutorial notebooks
   - Document common use cases

#### For Experienced Contributors

More advanced contributions:

1. **New Broker Integration**
   - Add support for new brokers
   - Complete implementation guide in next section
   - Requires understanding of broker APIs

2. **API Endpoints**
   - Implement new trading features
   - Enhance existing endpoints
   - Add new data sources

3. **React Frontend Features**
   - Build new pages or components
   - Add data visualizations with Plotly/Lightweight Charts
   - Improve real-time updates via Socket.IO

4. **Performance Optimization**
   - Optimize database queries
   - Improve caching strategies
   - Reduce API latency

5. **WebSocket Features**
   - Add new streaming capabilities
   - Improve real-time performance
   - Add broker WebSocket adapters

6. **Testing**
   - Write Vitest unit tests for React components
   - Write Playwright end-to-end tests
   - Write pytest tests for backend services
   - Improve test coverage

7. **Security Enhancements**
   - Audit security vulnerabilities
   - Improve authentication
   - Enhance encryption

---

## Testing

### Python Backend Tests

```bash
# Run all tests
uv run pytest test/ -v

# Run specific test file
uv run pytest test/test_broker.py -v

# Run single test function
uv run pytest test/test_broker.py::test_function_name -v

# Run tests with coverage
uv run pytest test/ --cov
```

### React Frontend Tests

```bash
cd frontend

# Run unit tests (watch mode)
npm test

# Run tests once
npm run test:run

# Run tests with coverage
npm run test:coverage

# Run accessibility tests
npm run test:a11y

# Run end-to-end tests (Playwright)
npm run e2e

# Run e2e tests with UI
npm run e2e:ui
```

### Writing Python Tests

```python
# test/test_feature.py
import pytest

def test_feature():
    """Test your feature here."""
    result = some_function()
    assert result == expected_value
```

### Writing React Tests

```typescript
// frontend/src/components/__tests__/MyComponent.test.tsx
import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import { MyComponent } from '../MyComponent';

describe('MyComponent', () => {
  it('renders correctly', () => {
    render(<MyComponent />);
    expect(screen.getByText('Expected Text')).toBeInTheDocument();
  });
});
```

### Writing E2E Tests

```typescript
// frontend/e2e/my-feature.spec.ts
import { test, expect } from '@playwright/test';

test('feature works end to end', async ({ page }) => {
  await page.goto('/react');
  await expect(page.getByText('Dashboard')).toBeVisible();
});
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
├── streaming/
│   └── broker_adapter.py     # WebSocket adapter for live data
└── plugin.json               # Broker configuration metadata
```

### 2. Implement Required Modules

#### 2.1 Authentication API (`api/auth_api.py`)

```python
"""Authentication module for BrokerName."""

def authenticate_broker(data):
    """Authenticate user with broker.

    Args:
        data (dict): Authentication credentials

    Returns:
        dict: Authentication response with status and token
    """
    pass

def get_auth_token():
    """Retrieve stored authentication token.

    Returns:
        str: Active auth token or None
    """
    pass
```

#### 2.2 Order API (`api/order_api.py`)

```python
"""Order management module for BrokerName."""

def place_order_api(data):
    """Place a new order with the broker."""
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
2. Configure broker credentials in `.env`
3. Test authentication flow
4. Test each API endpoint via Swagger UI at `/api/docs`
5. Test WebSocket streaming (if supported)
6. Validate error handling

### 4. Reference Implementations

Study existing broker implementations:
- `/broker/zerodha/` - Most complete implementation
- `/broker/dhan/` - Modern API design
- `/broker/angel/` - WebSocket streaming

---

## Frontend Development

### React + shadcn/ui Architecture

The frontend is a React 19 SPA located in `/frontend/`. It is built with Vite and served by Flask in production via `blueprints/react_app.py`.

#### Development Server

```bash
cd frontend

# Start Vite dev server with hot reload
npm run dev
# Available at http://localhost:5173

# Build for production
npm run build
# Output goes to frontend/dist/
```

#### Component Library

OpenAlgo uses [shadcn/ui](https://ui.shadcn.com/) built on Radix UI primitives with Tailwind CSS:

```tsx
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';

function PortfolioCard() {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Portfolio Value</CardTitle>
      </CardHeader>
      <CardContent>
        <p className="text-2xl font-bold">₹1,25,000</p>
      </CardContent>
    </Card>
  );
}
```

#### Server State with TanStack Query

```tsx
import { useQuery } from '@tanstack/react-query';

function Positions() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['positions'],
    queryFn: () => api.getPositions(),
  });

  if (isLoading) return <div>Loading...</div>;
  // render positions...
}
```

#### Client State with Zustand

```tsx
import { create } from 'zustand';

interface AppState {
  selectedBroker: string;
  setSelectedBroker: (broker: string) => void;
}

const useAppStore = create<AppState>((set) => ({
  selectedBroker: '',
  setSelectedBroker: (broker) => set({ selectedBroker: broker }),
}));
```

#### Styling with Tailwind CSS 4

Use Tailwind utility classes directly. Always use responsive and theme-aware patterns:

```tsx
{/* Responsive grid */}
<div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  <div>Column 1</div>
  <div>Column 2</div>
  <div>Column 3</div>
</div>

{/* Use CSS variables for theme colors — adapts to light/dark mode */}
<div className="bg-background text-foreground">
  Automatically adapts to theme
</div>
```

#### Linting and Formatting

```bash
cd frontend

# Lint
npm run lint

# Format
npm run format

# Both (with auto-fix)
npm run check
```

---

## Documentation

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
       """
       pass
   ```

2. **TypeScript** - Use JSDoc where types alone aren't sufficient:
   ```typescript
   /**
    * Fetches positions for the current user.
    * Requires active broker authentication.
    */
   async function getPositions(): Promise<Position[]> {
     // ...
   }
   ```

3. **API Documentation** - Use Flask-RESTX decorators:
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

---

## Best Practices

### Security

1. **Never commit sensitive data**
   ```python
   # Bad - Never do this!
   API_KEY = 'abc123xyz'

   # Good - Use environment variables
   import os
   API_KEY = os.getenv('BROKER_API_KEY')
   ```

2. **Validate all inputs at system boundaries**
   ```python
   def place_order(data):
       if data.get('quantity', 0) <= 0:
           raise ValueError('Quantity must be positive')

       valid_types = ['MARKET', 'LIMIT', 'SL', 'SLM']
       if data.get('order_type') not in valid_types:
           raise ValueError('Invalid order type')
   ```

3. **Use parameterized queries (SQLAlchemy ORM)**
   ```python
   # Bad - SQL injection vulnerability!
   query = f"SELECT * FROM orders WHERE user_id = {user_id}"

   # Good - SQLAlchemy ORM
   orders = Order.query.filter_by(user_id=user_id).all()
   ```

4. **Follow OWASP guidelines**
   - Enable CSRF protection (already configured)
   - Use HTTPS in production
   - Rate limiting is configured per endpoint
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

   symbol_cache = TTLCache(maxsize=1000, ttl=300)

   def get_symbol_info(symbol):
       if symbol in symbol_cache:
           return symbol_cache[symbol]
       info = fetch_symbol_from_db(symbol)
       symbol_cache[symbol] = info
       return info
   ```

3. **Minimize API calls — use batch endpoints**
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
   # Bad
   def calc(s, q, p):
       return s * q * p * 0.1

   # Good
   def calculate_order_value(symbol_price, quantity, price, multiplier):
       return symbol_price * quantity * price * multiplier
   ```

2. **Keep functions small and focused**

3. **Return consistent JSON responses from API endpoints**
   ```python
   return {
       'status': 'success' | 'error',
       'message': 'Human-readable message',
       'data': {...}  # Optional payload
   }
   ```

---

## Troubleshooting

### Common Issues

#### Frontend Build Errors

```bash
# Ensure correct Node.js version (20, 22, or 24)
node --version

# Clean install
cd frontend
rm -rf node_modules
npm install
npm run build

# Check for TypeScript errors
npx tsc --noEmit
```

#### Python Dependency Issues

```bash
# Sync dependencies with uv
uv sync

# If issues persist, recreate the environment
rm -rf .venv
uv sync
```

#### WebSocket Connection Issues

```bash
# Check WebSocket configuration in .env:
WEBSOCKET_HOST='127.0.0.1'
WEBSOCKET_PORT='8765'

# Ensure only one worker with Gunicorn:
uv run gunicorn --worker-class eventlet -w 1 app:app

# Check firewall settings for port 8765
```

#### Database Locked Errors

```bash
# SQLite doesn't handle high concurrency well
# Close all connections and restart the app
uv run app.py
```

---

## Getting Help

### Support Channels

- **Discord**: Join our [Discord server](https://discord.com/invite/UPh7QPsNhP) for real-time help
- **GitHub Discussions**: Ask questions in [GitHub Discussions](https://github.com/marketcalls/openalgo/discussions)
- **Documentation**: Check [docs.openalgo.in](https://docs.openalgo.in)
- **GitHub Issues**: Report bugs in [Issues](https://github.com/marketcalls/openalgo/issues)

### Before Asking for Help

1. **Search existing issues** — your question might already be answered
2. **Check documentation** — review docs at docs.openalgo.in
3. **Review error logs** — include error messages when asking for help
4. **Provide context** — share your environment (OS, Python version, Node version, broker)

### Asking Good Questions

When asking for help, include:

1. **Clear description** of the problem
2. **Steps to reproduce** the issue
3. **Expected behavior** vs **actual behavior**
4. **Error messages** (full stack trace)
5. **Environment details**:
   - OS and version
   - Python version (`python --version`)
   - Node.js version (`node --version`)
   - OpenAlgo version
   - Broker being used

---

## Code Review Process

After submitting your pull request:

1. **Automated Checks**
   - CI will build the frontend and run linting
   - Ensure all checks pass before requesting review

2. **Review Feedback**
   - Address reviewer comments promptly
   - Ask questions if feedback is unclear
   - Make requested changes in new commits

3. **Updates**
   - Push additional commits to your branch
   - No need to create a new PR

4. **Approval & Merge**
   - Once approved, maintainers will merge
   - CI will automatically build the frontend for production

5. **Be Patient**
   - Reviews may take a few days
   - Maintainers are volunteers
   - Ping politely if no response after a week

---

## Recognition & Community

We value all contributions! Contributors will be:

- **Listed in contributors section** on GitHub
- **Mentioned in release notes** for significant contributions
- **Part of the OpenAlgo community** on Discord

### Community Guidelines

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

*Built by traders, for traders — making algo trading accessible to everyone.*
