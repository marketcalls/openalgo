# py_vollib Python 3.14 Compatibility Fix

## Problem
When running the application with Python 3.14, the option Greeks calculation fails with the error:
```
ERROR in option_greeks_service: py_vollib library not installed. Install with: pip install py_vollib
```

Even after installing `py_vollib`, the import fails with:
```
ModuleNotFoundError: No module named '_testcapi'
```

## Root Cause
The PyPI versions of `py-vollib` (1.0.1) and `py-lets-be-rational` (1.0.1) are not compatible with Python 3.14. The dependency `py-lets-be-rational` tries to import `_testcapi` from Python's internal test modules, which is not available in Python 3.14's standard installation.

## Solution
Use the GitHub versions of both packages, which have been updated with Python 3.14 support.

### Step 1: Update pyproject.toml
Replace the PyPI versions with GitHub repository references:

```toml
# Before:
"py_lets_be_rational==1.0.1",
"py-vollib==1.0.1",

# After:
"py-lets-be-rational @ git+https://github.com/vollib/py_lets_be_rational.git",
"py-vollib @ git+https://github.com/vollib/py_vollib.git",
```

### Step 2: Sync Dependencies
Run the following command to update the virtual environment:

```bash
uv sync
```

### Step 3: Verify Installation
Test that the import works:

```bash
uv run python -c "from py_vollib.black.implied_volatility import implied_volatility; print('Success!')"
```

If successful, you should see:
```
Success!
```

### Step 4: Restart Application
Restart your application:

```bash
uv run ./app.py
```

## Alternative: Manual Installation (Not Recommended)
If you need to manually install without updating pyproject.toml:

```bash
# Remove old versions
uv pip uninstall py-vollib py-lets-be-rational

# Install from GitHub
uv pip install git+https://github.com/vollib/py_lets_be_rational.git
uv pip install git+https://github.com/vollib/py_vollib.git
```

**Note:** This approach is not recommended because `uv sync` will overwrite these installations based on what's in `pyproject.toml`.

## Verification
After applying the fix, option Greeks calculations should work without errors. The service will be able to import and use:
- `py_vollib.black.implied_volatility`
- `py_vollib.black.greeks.analytical` (delta, gamma, theta, vega, rho)

## Related Issues
- Python 3.14 compatibility with `_testcapi` module
- PyPI versions lagging behind GitHub repository updates
- Dependency resolution with `py-lets-be-rational`

## Future Notes
If this issue occurs again with newer Python versions, check the GitHub repositories for updated versions:
- https://github.com/vollib/py_vollib
- https://github.com/vollib/py_lets_be_rational
