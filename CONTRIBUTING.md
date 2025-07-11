# Contributing to OpenAlgo

Welcome to OpenAlgo! We're thrilled that you're interested in contributing to our open-source algorithmic trading platform. OpenAlgo bridges traders with major trading platforms, and your contributions help make algotrading accessible to everyone.

## 🎯 Our Mission

OpenAlgo is built by traders, for traders. We believe in democratizing algorithmic trading by providing a broker-agnostic, open-source platform that puts control back in the hands of traders. Every contribution, no matter how small, helps us achieve this mission.

## 🛠️ Technology Stack

Before diving in, here's what powers OpenAlgo:

### Backend
- **Python 3.12+** - Core programming language
- **Flask** - Web framework
- **Flask-RESTX** - RESTful API with auto-documentation
- **SQLAlchemy** - Database ORM
- **Flask-SocketIO** - Real-time WebSocket connections

### Frontend
- **Jinja2** - Templating engine
- **TailwindCSS** - Utility-first CSS framework
- **DaisyUI** - Component library

### Trading & Data
- **pandas** - Data manipulation
- **numpy** - Numerical computing
- **pandas-ta** - Technical analysis
- **httpx** - Modern HTTP client with HTTP/2 support

## 🚀 Getting Started

### Prerequisites

- Python 3.10 or higher (3.12+ recommended)
- Node.js (v16 or higher)
- Git
- A code editor (VS Code recommended)
- Basic understanding of Flask and REST APIs

### Setting Up Your Development Environment

1. **Fork the Repository**
   
   Click the "Fork" button on the [OpenAlgo GitHub repository](https://github.com/marketcalls/openalgo) to create your own copy.

2. **Clone Your Fork**
   ```bash
   git clone https://github.com/YOUR_USERNAME/openalgo.git
   cd openalgo
   ```

3. **Add Upstream Remote**
   ```bash
   git remote add upstream https://github.com/marketcalls/openalgo.git
   ```

4. **Install Python Dependencies**
   ```bash
   # Create a virtual environment
   python -m venv venv
   
   # Activate it
   # On Windows:
   venv\Scripts\activate
   # On Linux/Mac:
   source venv/bin/activate
   
   # Install dependencies
   pip install -r requirements.txt
   ```

5. **Install Node Dependencies**
   ```bash
   npm install
   ```

6. **Configure Environment**
   ```bash
   # Copy the sample environment file
   cp .sample.env .env
   
   # Edit .env with your configuration
   # At minimum, set a SECRET_KEY
   ```

7. **Build CSS**
   ```bash
   # For development (with watch mode)
   npm run dev
   
   # For production build
   npm run build
   ```

8. **Run the Application**
   ```bash
   python app.py
   ```

   The application will be available at `http://localhost:5000`

## 🔧 Development Workflow

### 1. Create a Feature Branch
```bash
# Update your main branch
git checkout main
git pull upstream main

# Create a new branch for your feature
git checkout -b feature/your-feature-name
```

### 2. Make Your Changes

Keep these guidelines in mind:

- **Code Style**: Follow PEP 8 for Python code
- **Commit Messages**: Use clear, descriptive commit messages
- **Documentation**: Update documentation for any new features
- **Tests**: Add tests for new functionality (if applicable)

### 3. Test Your Changes

```bash
# Run the application
python app.py

# Test specific features
# For API endpoints, use the built-in Swagger UI at /api/docs
```

#### Important: CSS Compilation for UI Changes

If you're making any UI changes using Tailwind or DaisyUI classes, you MUST compile the CSS:

```bash
# For development (watches for changes and auto-compiles)
npm run dev

# For production (minified build)
npm run build
```

**Note**: The compiled CSS files are in `/static/css/`. Never edit these directly - always modify the source in `/src/css/styles.css` and Tailwind classes in templates.

### 4. Commit Your Changes
```bash
git add .
git commit -m "feat: add support for new broker XYZ"
```

We follow conventional commits:
- `feat:` for new features
- `fix:` for bug fixes
- `docs:` for documentation
- `style:` for formatting changes
- `refactor:` for code restructuring
- `test:` for test additions
- `chore:` for maintenance tasks

### 5. Push to Your Fork
```bash
git push origin feature/your-feature-name
```

### 6. Create a Pull Request

1. Go to your fork on GitHub
2. Click "Compare & pull request"
3. Fill out the PR template with:
   - Clear description of changes
   - Related issue numbers (if any)
   - Screenshots (for UI changes)
   - Testing steps

## 🎯 What Can You Contribute?

### For First-Time Contributors

- **Documentation**: Improve README, add tutorials, fix typos
- **Bug Fixes**: Check the [issues](https://github.com/marketcalls/openalgo/issues) labeled "good first issue"
- **Examples**: Add new strategy examples in `/strategies`
- **UI Improvements**: Enhance the user interface with better styling or UX

### For Experienced Contributors

- **New Broker Integration**: Add support for new brokers in `/broker`
- **API Endpoints**: Implement new trading functionality
- **Performance**: Optimize existing code for better performance
- **Testing**: Add unit tests and integration tests
- **WebSocket Features**: Enhance real-time capabilities

## 📁 Project Structure Overview

Understanding the codebase structure will help you contribute effectively:

```
openalgo/
├── broker/           # Broker-specific implementations
├── blueprints/       # Flask blueprints for web routes
├── database/         # Database models and utilities
├── restx_api/        # REST API endpoints
├── services/         # Business logic layer
├── strategies/       # Trading strategy examples
├── templates/        # Jinja2 HTML templates
├── static/          # Static assets (CSS, JS, images)
├── utils/           # Utility functions and helpers
├── docs/            # Documentation
└── app.py           # Main application entry point
```

## 🎨 UI Development with Tailwind & DaisyUI

When working on the user interface:

### CSS Workflow
1. **Never edit** `/static/css/main.css` directly - it's auto-generated
2. **Make changes** in:
   - `/src/css/styles.css` for custom CSS
   - HTML templates in `/templates/` for Tailwind/DaisyUI classes
3. **Run the compiler**:
   ```bash
   # Development mode - watches for changes
   npm run dev
   
   # Keep this running in a separate terminal while developing
   ```
4. **Before committing**, run production build:
   ```bash
   npm run build
   ```

### Using DaisyUI Components
- Check [DaisyUI documentation](https://daisyui.com/components/) for available components
- The project uses three themes: light, dark, and garden (for analyzer)
- Use theme-aware classes like `bg-base-100` instead of hardcoded colors

### Tailwind Tips
- Use utility classes directly in templates
- Custom styles go in `/src/css/styles.css`
- The Tailwind config is in `tailwind.config.js`

## 🏗️ Adding a New Broker

One of the most valuable contributions is adding support for new brokers:

1. Create a new directory under `/broker/your_broker_name/`
2. Implement required modules:
   - `api/auth_api.py` - Authentication logic
   - `api/order_api.py` - Order management
   - `api/data.py` - Market data access
   - `database/master_contract_db.py` - Symbol management
   - `mapping/order_data.py` - Data transformation
   - `plugin.json` - Broker configuration

3. Follow the existing broker implementations as reference
4. Update documentation with setup instructions

## 🧪 Testing Guidelines

While formal testing infrastructure is being developed, please:

1. **Manual Testing**: Thoroughly test your changes locally
2. **API Testing**: Use the Swagger UI at `/api/docs`
3. **Cross-Browser**: Test UI changes in multiple browsers
4. **Error Handling**: Ensure proper error messages and handling

## 📝 Documentation

Good documentation is crucial:

- **Code Comments**: Add docstrings to functions and classes
- **README Updates**: Update README.md for new features
- **API Documentation**: Use proper Flask-RESTX decorators
- **User Guides**: Add guides in `/docs` for complex features

## 🤝 Code Review Process

After submitting a PR:

1. **Automated Checks**: Ensure all checks pass
2. **Review Feedback**: Address reviewer comments promptly
3. **Updates**: Push additional commits to your branch
4. **Patience**: Reviews may take a few days

## 💡 Best Practices

### Security
- Never commit sensitive data (API keys, passwords)
- Validate all user inputs
- Use parameterized queries for database operations
- Follow OWASP guidelines for web security

### Performance
- Optimize database queries
- Use caching where appropriate
- Minimize API calls to external services
- Profile code for performance bottlenecks

### Code Quality
- Write self-documenting code
- Keep functions small and focused
- Use meaningful variable names
- Handle errors gracefully

## 🐛 Reporting Issues

Found a bug? Here's how to report it:

1. Check if the issue already exists
2. Create a new issue with:
   - Clear title and description
   - Steps to reproduce
   - Expected vs actual behavior
   - Environment details (OS, Python version, broker)
   - Screenshots or error logs

## 🌟 Recognition

We value all contributions! Contributors will be:
- Listed in our contributors section
- Mentioned in release notes
- Part of the OpenAlgo community

## 📞 Getting Help

Need assistance? We're here to help:

- **Discord**: Join our [Discord server](https://discord.com/invite/UPh7QPsNhP)
- **GitHub Discussions**: Ask questions in the Discussions tab
- **Documentation**: Check [docs.openalgo.in](https://docs.openalgo.in)

## 🎉 Thank You!

Thank you for contributing to OpenAlgo! Your efforts help democratize algorithmic trading and empower traders worldwide. Every line of code, documentation improvement, and bug report makes a difference.

Happy coding, and welcome to the OpenAlgo community! 🚀

---

## Quick Links

- [Project Repository](https://github.com/marketcalls/openalgo)
- [Issue Tracker](https://github.com/marketcalls/openalgo/issues)
- [Documentation](https://docs.openalgo.in)
- [Discord Community](https://discord.com/invite/UPh7QPsNhP)