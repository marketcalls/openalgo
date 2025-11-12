# Quick Setup Guide for New Improvements

## 🚀 Quick Start

### Step 1: Install Development Dependencies
```bash
pip install -r requirements-dev.txt
```

### Step 2: Set Up Pre-commit Hooks
```bash
pre-commit install

# Test it (optional)
pre-commit run --all-files
```

### Step 3: Test Health Endpoints
```bash
# Start your application
python app.py

# In another terminal, test the endpoints
curl http://localhost:5000/health/
curl http://localhost:5000/health/ready
curl http://localhost:5000/health/metrics
```

### Step 4: Run Tests
```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov-report=html

# Open coverage report
# Open htmlcov/index.html in your browser
```

---

## 📋 Daily Development Workflow

### Before You Code
```bash
# Pull latest changes
git pull origin main

# Create a new branch
git checkout -b feature/your-feature-name
```

### While Coding
```bash
# Format code (optional - pre-commit will do this)
black .
isort .

# Run tests frequently
pytest -v
```

### Before Committing
```bash
# Pre-commit hooks will run automatically
git add .
git commit -m "Your commit message"

# If hooks fail, fix issues and try again
# The hooks will auto-format most issues
```

### Before Pushing
```bash
# Run full test suite
pytest

# Check for security issues
bandit -r .
pip-audit

# Push your changes
git push origin feature/your-feature-name
```

---

## 🔧 Common Commands

### Code Formatting
```bash
# Format all Python files
black .

# Check without modifying
black --check .

# Sort imports
isort .

# Check import sorting
isort --check-only .
```

### Linting
```bash
# Run Flake8
flake8 .

# Run Flake8 on specific file
flake8 path/to/file.py

# Run mypy type checking
mypy .
```

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest test/test_specific.py

# Run tests with specific marker
pytest -m unit
pytest -m integration
pytest -m api

# Run tests in parallel (faster)
pytest -n auto

# Run with verbose output
pytest -v

# Stop on first failure
pytest -x

# Show local variables on failure
pytest -l
```

### Coverage
```bash
# Generate coverage report
pytest --cov=. --cov-report=html

# View coverage in terminal
pytest --cov=. --cov-report=term-missing

# Fail if coverage below threshold
pytest --cov=. --cov-fail-under=50
```

### Security Scanning
```bash
# Scan for security issues
bandit -r .

# Check for vulnerable dependencies
pip-audit

# Alternative dependency checker
safety check
```

### Pre-commit
```bash
# Run all pre-commit hooks
pre-commit run --all-files

# Run specific hook
pre-commit run black --all-files
pre-commit run flake8 --all-files

# Update hook versions
pre-commit autoupdate

# Skip hooks (not recommended)
git commit --no-verify
```

---

## 🐛 Troubleshooting

### Issue: Pre-commit hooks fail
**Solution:**
```bash
# Let hooks auto-fix what they can
pre-commit run --all-files

# Review changes
git diff

# Add and commit
git add .
git commit -m "Your message"
```

### Issue: Tests fail locally
**Solution:**
```bash
# Check .env file exists
ls -la .env

# Run tests with verbose output to see error
pytest -v

# Run specific failing test
pytest test/test_file.py::test_specific_test -v
```

### Issue: Import errors when running tests
**Solution:**
```bash
# Make sure you're in the project root
cd /home/user/openalgo

# Reinstall requirements
pip install -r requirements.txt
pip install -r requirements-dev.txt
```

### Issue: Health endpoints return 500
**Solution:**
```bash
# Check if database is initialized
ls db/openalgo.db

# Check application logs
# Look for error messages
```

### Issue: mypy complains about missing types
**Solution:**
```bash
# Install type stubs
mypy --install-types

# Or ignore specific errors (add to pyproject.toml)
# type: ignore
```

---

## 📊 Understanding Test Output

### Pytest Output
```bash
test/test_example.py::test_something PASSED        [ 50%]
test/test_example.py::test_another FAILED          [100%]

======================== FAILURES =========================
________________________ test_another _____________________
    # Error details here
======================== 1 failed, 1 passed ==============
```

**Green dots (.)** = Passed tests
**Red F** = Failed tests
**Yellow s** = Skipped tests
**Blue x** = Expected failure (xfail)

### Coverage Output
```bash
Name                 Stmts   Miss  Cover   Missing
--------------------------------------------------
app.py                 150     30    80%   45-50, 60-65
blueprints/auth.py      80     10    88%   100-105
--------------------------------------------------
TOTAL                 2300    300    87%
```

**Stmts** = Total statements
**Miss** = Statements not covered
**Cover** = Coverage percentage
**Missing** = Line numbers not covered

---

## 🎯 CI/CD Pipeline

### What Runs Automatically

When you push code, GitHub Actions will:

1. **Lint Job** (2-3 min)
   - Check code formatting (Black)
   - Check import sorting (isort)
   - Run Flake8 linting
   - Run mypy type checking

2. **Security Job** (3-4 min)
   - Scan code with Bandit
   - Check dependencies with pip-audit
   - Check dependencies with Safety

3. **Test Job** (5-7 min)
   - Run all tests
   - Generate coverage report
   - Upload to Codecov (if configured)

4. **Docker Job** (3-5 min)
   - Build Docker image
   - Scan with Trivy
   - Upload security results

**Total time:** ~15 minutes

### Viewing CI Results

1. Go to your repository on GitHub
2. Click **Actions** tab
3. Click on your commit/PR
4. View job results

**Green checkmark** = All checks passed
**Red X** = Some checks failed
**Yellow dot** = Running

### If CI Fails

1. Click on the failed job
2. Expand the failing step
3. Read error messages
4. Fix locally and push again

---

## 🔐 Security Best Practices

### Never Commit Secrets
```bash
# Bad (will be caught by pre-commit)
API_KEY = "abc123"

# Good
API_KEY = os.getenv('API_KEY')
```

### Use Environment Variables
```bash
# Create .env file (already in .gitignore)
SECRET_KEY=your-secret-here
API_KEY=your-api-key

# Load in code
from dotenv import load_dotenv
load_dotenv()
```

### Check for Vulnerabilities
```bash
# Before deploying
pip-audit
bandit -r .

# Update vulnerable packages
pip install --upgrade package-name
```

---

## 📚 Learning Resources

### For Testing
- [pytest documentation](https://docs.pytest.org/)
- [pytest fixtures](https://docs.pytest.org/en/stable/fixture.html)
- [pytest markers](https://docs.pytest.org/en/stable/example/markers.html)

### For Code Quality
- [Black style guide](https://black.readthedocs.io/)
- [PEP 8](https://pep8.org/)
- [Type hints guide](https://docs.python.org/3/library/typing.html)

### For CI/CD
- [GitHub Actions](https://docs.github.com/en/actions)
- [YAML syntax](https://yaml.org/spec/1.2/spec.html)

---

## 🎓 Tips for New Contributors

1. **Start Small**
   - Fix a small bug or add a test
   - Get familiar with the workflow

2. **Read the Docs**
   - Check ARCHITECTURE.md
   - Understand the codebase structure

3. **Write Tests First**
   - TDD (Test-Driven Development)
   - Tests document expected behavior

4. **Ask Questions**
   - Open an issue if confused
   - Check existing issues/PRs

5. **Follow Conventions**
   - Let pre-commit hooks guide you
   - Study existing code patterns

---

## 🆘 Getting Help

### If You're Stuck

1. **Check Documentation**
   - ARCHITECTURE.md
   - IMPROVEMENTS_SUMMARY.md
   - Code comments

2. **Search Issues**
   - GitHub Issues tab
   - Someone may have faced the same problem

3. **Ask the Community**
   - Discord server
   - GitHub Discussions

4. **Open an Issue**
   - Describe the problem clearly
   - Include error messages
   - Show what you tried

---

## ✅ Ready to Start?

```bash
# 1. Install dependencies
pip install -r requirements-dev.txt

# 2. Set up pre-commit
pre-commit install

# 3. Run tests to verify setup
pytest

# 4. Start coding!
git checkout -b feature/my-awesome-feature
```

**Happy coding! 🎉**
