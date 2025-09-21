# Python Strategies Installation Guide

## Prerequisites

### System Requirements
- Python 3.8 or higher
- OpenAlgo installed and running
- 2GB RAM minimum (4GB recommended)
- 1GB free disk space

### Operating System Support
- ✅ Windows 10/11
- ✅ Ubuntu 20.04/22.04
- ✅ macOS 11+
- ✅ Docker containers

## Installation Steps

### Step 1: Install Required Packages

#### Using pip
```bash
pip install apscheduler>=3.10.0
pip install psutil>=5.9.0
pip install pytz
pip install cryptography
```

#### Using requirements.txt
Create a `requirements.txt` file:
```txt
apscheduler>=3.10.0
psutil>=5.9.0
pytz
cryptography
```

Then install:
```bash
pip install -r requirements.txt
```

#### Using conda
```bash
conda install apscheduler psutil pytz
```

### Step 2: Verify Directory Structure

The following directories will be created automatically:

```
openalgo/
├── blueprints/
│   └── python_strategy.py      # Core module (should exist)
├── templates/
│   └── python_strategy/         # UI templates (should exist)
├── static/
│   ├── js/
│   │   └── python-editor-simple.js
│   └── css/
│       └── python-editor-simple.css
├── strategies/                  # Auto-created
│   ├── scripts/                 # Your strategy files go here (git-ignored)
│   ├── strategy_configs.json    # Configuration storage (git-ignored)
│   ├── strategy_env.json        # Regular environment variables (git-ignored)
│   ├── .secure_env              # Encrypted sensitive variables (git-ignored)
│   ├── .encryption_key          # Encryption key (auto-generated, git-ignored)
│   └── .gitignore               # Protects sensitive files from git commits
└── log/
    └── strategies/              # Log files
```

### Step 3: Verify Blueprint Registration

Check `app.py` includes the Python strategy blueprint:

```python
# In app.py
from blueprints.python_strategy import python_strategy_bp

# Register blueprint
app.register_blueprint(python_strategy_bp)
```

### Step 4: Database Setup (Optional)

If using database for strategy metadata:

```sql
CREATE TABLE IF NOT EXISTS strategies (
    id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    file_path VARCHAR(255) NOT NULL,
    is_running BOOLEAN DEFAULT FALSE,
    is_scheduled BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Configuration

### Environment Variables

Create `.env` file in OpenAlgo root:

```env
# Python Strategies Configuration
STRATEGY_LOG_LEVEL=INFO
STRATEGY_MAX_PROCESSES=10
STRATEGY_DEFAULT_TIMEOUT=3600
STRATEGY_TIMEZONE=Asia/Kolkata
```

### Application Configuration

In your OpenAlgo configuration:

```python
# config.py
class Config:
    # Python Strategy Settings
    STRATEGY_UPLOAD_FOLDER = 'strategies/scripts'
    STRATEGY_LOG_FOLDER = 'log/strategies'
    STRATEGY_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB
    STRATEGY_ALLOWED_EXTENSIONS = {'.py'}
    STRATEGY_TIMEZONE = 'Asia/Kolkata'
```

## Verification

### 1. Check Installation

Run this Python script to verify installation:

```python
#!/usr/bin/env python3
"""Verify Python Strategies Installation"""

import sys
import importlib

def check_module(module_name):
    try:
        module = importlib.import_module(module_name)
        version = getattr(module, '__version__', 'unknown')
        print(f"✓ {module_name} {version}")
        return True
    except ImportError:
        print(f"✗ {module_name} not found")
        return False

def main():
    print("Python Strategies Installation Check")
    print("-" * 40)
    
    required = ['apscheduler', 'psutil', 'pytz', 'flask', 'cryptography']
    success = all(check_module(m) for m in required)
    
    print("-" * 40)
    if success:
        print("✓ All requirements satisfied")
        return 0
    else:
        print("✗ Missing requirements. Please install.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
```

### 2. Test Access

Navigate to: `http://127.0.0.1:5000/python`

You should see the Python Strategies dashboard.

### 3. Test Upload

Create a test strategy:

```python
# test_strategy.py
import time
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def main():
    logger.info("Test strategy started")
    for i in range(5):
        logger.info(f"Iteration {i+1}/5")
        time.sleep(1)
    logger.info("Test strategy completed")

if __name__ == "__main__":
    main()
```

Upload via web interface and verify it runs.

## Docker Installation

### Dockerfile Addition

Add to your Dockerfile:

```dockerfile
# Install Python strategy requirements
RUN pip install apscheduler>=3.10.0 \
                psutil>=5.9.0 \
                pytz \
                cryptography

# Create strategy directories
RUN mkdir -p /app/strategies/scripts \
             /app/log/strategies

# Set permissions
RUN chmod -R 755 /app/strategies \
                 /app/log
```

### Docker Compose

```yaml
version: '3.8'

services:
  openalgo:
    build: .
    ports:
      - "5000:5000"
    volumes:
      - ./strategies:/app/strategies
      - ./log:/app/log
    environment:
      - STRATEGY_TIMEZONE=Asia/Kolkata
      - PYTHONUNBUFFERED=1
```

## Upgrading

### From Existing Installation

1. **Backup your strategies**:
```bash
cp -r strategies strategies_backup
cp strategies/strategy_configs.json strategy_configs_backup.json
```

2. **Update packages**:
```bash
pip install --upgrade apscheduler psutil pytz cryptography
```

3. **Run upgrade script**:
```python
# upgrade_python_strategies.py
import os
import json
from pathlib import Path

def upgrade():
    # Ensure directories exist
    Path('strategies/scripts').mkdir(parents=True, exist_ok=True)
    Path('log/strategies').mkdir(parents=True, exist_ok=True)
    
    # Migrate old configs if exist
    old_config = Path('strategy_configs.json')
    new_config = Path('strategies/strategy_configs.json')
    
    if old_config.exists() and not new_config.exists():
        old_config.rename(new_config)
        print("✓ Migrated configuration")
    
    print("✓ Upgrade complete")

if __name__ == "__main__":
    upgrade()
```

## Troubleshooting

### Common Installation Issues

#### ImportError: No module named 'apscheduler'
```bash
# Solution
pip install apscheduler
```

#### Permission Denied on Linux/Mac
```bash
# Solution
sudo chmod -R 755 strategies log
sudo chown -R $USER:$USER strategies log
```

#### Port 5000 Already in Use
```bash
# Find process
lsof -i :5000  # Linux/Mac
netstat -ano | findstr :5000  # Windows

# Change port in app.py
app.run(port=5001)
```

#### Timezone Issues
```bash
# Install timezone data
pip install tzdata

# Set system timezone (Linux)
timedatectl set-timezone Asia/Kolkata
```

### Verification Commands

```bash
# Check Python version
python --version

# Check installed packages
pip list | grep -E "apscheduler|psutil|pytz"

# Check directory permissions
ls -la strategies/
ls -la log/

# Test import
python -c "import apscheduler, psutil, pytz, cryptography; print('OK')"
```

## Security Considerations

### File Permissions

```bash
# Recommended permissions
chmod 755 strategies/
chmod 755 strategies/scripts/
chmod 644 strategies/scripts/*.py
chmod 644 strategies/strategy_env.json      # Regular env vars
chmod 600 strategies/.secure_env            # Secure env vars (restricted)
chmod 600 strategies/.encryption_key        # Encryption key (restricted)
chmod 755 log/
chmod 644 log/strategies/*.log
```

### Git Security

The `strategies/.gitignore` file automatically protects:
- Strategy configuration files (`strategy_configs.json`)
- Environment variables (`strategy_env.json`, `.secure_env`)
- Encryption keys (`.encryption_key`)
- Uploaded strategy scripts (`scripts/*.py`)

This prevents accidental commits of sensitive data to version control.

### Firewall Rules

If accessing remotely:

```bash
# Allow port 5000 (Linux)
sudo ufw allow 5000/tcp

# Windows Firewall
netsh advfirewall firewall add rule name="OpenAlgo" dir=in action=allow protocol=TCP localport=5000
```

### Process Limits

Set resource limits for strategy processes:

```python
# In python_strategy.py
import resource

# Limit memory usage (1GB)
resource.setrlimit(resource.RLIMIT_AS, (1024*1024*1024, 1024*1024*1024))

# Limit CPU time (1 hour)
resource.setrlimit(resource.RLIMIT_CPU, (3600, 3600))
```

## Next Steps

After successful installation:

1. Read the [Usage Guide](README.md#usage-guide)
2. Upload your first strategy
3. Configure scheduling
4. Monitor logs
5. Export strategies for backup

## Support

If you encounter issues:

1. Check the [Troubleshooting Guide](README.md#troubleshooting)
2. Review application logs
3. Open an issue on GitHub
4. Contact support team

---

*Installation Guide v1.0.0*
*Last Updated: September 2024*