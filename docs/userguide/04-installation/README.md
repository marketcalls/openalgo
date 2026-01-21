# 04 - Installation Guide

## Introduction

This guide walks you through installing OpenAlgo on your system. We'll cover Windows, Ubuntu, and macOS installations.

## Quick Install (All Platforms)

If you're comfortable with command line, here's the fastest way:

```bash
# 1. Clone the repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# 2. Install UV package manager
pip install uv

# 3. Create configuration
cp .sample.env .env

# 4. Run OpenAlgo
uv run app.py
```

Open `http://127.0.0.1:5000` in your browser. That's it!

## Detailed Installation

### Windows Installation

#### Step 1: Install Python

1. Go to [python.org/downloads](https://www.python.org/downloads/)
2. Download Python 3.12 (or 3.11/3.13)
3. **Important**: Check "Add Python to PATH" during installation
4. Click "Install Now"

**Verify installation**:
```cmd
python --version
# Should show: Python 3.12.x
```

#### Step 2: Install Git

1. Go to [git-scm.com](https://git-scm.com/download/win)
2. Download and install with default options

**Verify installation**:
```cmd
git --version
# Should show: git version 2.x.x
```

#### Step 3: Download OpenAlgo

Open Command Prompt (search "cmd") and run:

```cmd
# Navigate to where you want OpenAlgo
cd C:\Users\YourName\Documents

# Clone the repository
git clone https://github.com/marketcalls/openalgo.git

# Enter the folder
cd openalgo
```

#### Step 4: Install UV Package Manager

```cmd
pip install uv
```

#### Step 5: Configure Environment

```cmd
# Create configuration file
copy .sample.env .env
```

**Edit the .env file** (use Notepad):
- Right-click `.env` → Open with → Notepad
- We'll configure this in the next chapter

#### Step 6: Run OpenAlgo

```cmd
uv run app.py
```

You should see:
```
* Running on http://127.0.0.1:5000
```

Open your browser and go to `http://127.0.0.1:5000`

### Ubuntu/Linux Installation

#### Step 1: Update System

```bash
sudo apt update && sudo apt upgrade -y
```

#### Step 2: Install Python and Dependencies

```bash
# Install Python and pip
sudo apt install python3.12 python3.12-venv python3-pip git -y

# Verify
python3.12 --version
```

#### Step 3: Download OpenAlgo

```bash
# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo
```

#### Step 4: Install UV and Configure

```bash
# Install UV
pip install uv

# Create configuration
cp .sample.env .env
```

#### Step 5: Run OpenAlgo

```bash
uv run app.py
```

Access at `http://your-server-ip:5000`

### macOS Installation

#### Step 1: Install Homebrew (if not installed)

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
```

#### Step 2: Install Python and Git

```bash
brew install python@3.12 git
```

#### Step 3: Download and Run OpenAlgo

```bash
# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Install UV
pip3 install uv

# Configure
cp .sample.env .env

# Run
uv run app.py
```

## Docker Installation (Alternative)

If you prefer Docker:

```bash
# Clone repository
git clone https://github.com/marketcalls/openalgo.git
cd openalgo

# Build and run
docker-compose up -d
```

Access at `http://localhost:5000`

## Verifying Installation

### Check 1: Web Interface

Open browser → Go to `http://127.0.0.1:5000`

You should see the OpenAlgo login page.

### Check 2: API Docs

Go to `http://127.0.0.1:5000/api/docs`

You should see Swagger API documentation.

### Check 3: No Errors

Check terminal/command prompt for errors. Common issues:

**Port in use**:
```
Error: Address already in use
```
Solution: Change port in `.env` or stop other applications

**Python not found**:
```
'python' is not recognized
```
Solution: Reinstall Python with "Add to PATH" checked

## Folder Structure After Installation

```
openalgo/
├── app.py              # Main application
├── .env                # Your configuration (edit this)
├── .sample.env         # Example configuration
├── broker/             # Broker integrations
├── blueprints/         # Application routes
├── frontend/           # React frontend
├── database/           # Database models
├── db/                 # Database files (created on first run)
├── logs/               # Log files
└── ...
```

## Configuration Overview

The `.env` file contains all your settings. Key sections:

```ini
# Application Settings
FLASK_HOST=127.0.0.1
FLASK_PORT=5000

# Security (CHANGE THESE!)
APP_KEY=your-secret-key-here
API_KEY_PEPPER=your-pepper-here

# Broker Selection
BROKER=zerodha

# Broker Credentials
BROKER_API_KEY=your-api-key
BROKER_API_SECRET=your-api-secret
```

**Important**: Generate new APP_KEY and API_KEY_PEPPER:
```bash
uv run python -c "import secrets; print(secrets.token_hex(32))"
```

Run this twice - once for APP_KEY, once for API_KEY_PEPPER.

## Running OpenAlgo

### Development Mode (Default)

```bash
uv run app.py
```

### Production Mode (Linux with Gunicorn)

```bash
uv run gunicorn --worker-class eventlet -w 1 -b 0.0.0.0:5000 app:app
```

### Running in Background (Linux)

```bash
# Using screen
screen -S openalgo
uv run app.py
# Press Ctrl+A, then D to detach

# To reattach
screen -r openalgo
```

### Auto-Start on Boot (Linux with systemd)

Create `/etc/systemd/system/openalgo.service`:

```ini
[Unit]
Description=OpenAlgo Trading Platform
After=network.target

[Service]
User=your-username
WorkingDirectory=/path/to/openalgo
ExecStart=/path/to/openalgo/.venv/bin/python app.py
Restart=always

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable openalgo
sudo systemctl start openalgo
```

## Updating OpenAlgo

To get the latest version:

```bash
cd openalgo

# Stop OpenAlgo first

# Pull latest changes
git pull origin main

# Sync dependencies
uv sync

# Restart OpenAlgo
uv run app.py
```

## Troubleshooting Installation

### Issue: "Module not found"

```bash
# Sync dependencies
uv sync
```

### Issue: "Permission denied"

```bash
# Linux/Mac
chmod +x app.py
```

### Issue: "Database locked"

Close all OpenAlgo instances and restart.

### Issue: "Port 5000 in use"

```bash
# Find what's using port 5000
# Windows
netstat -ano | findstr :5000

# Linux/Mac
lsof -i :5000

# Either stop that process or change port in .env
```

## Next Steps

Installation complete! Now:

1. **First-Time Setup**: Configure your credentials
2. **Connect Broker**: Link your trading account
3. **Test with Analyzer**: Practice with virtual money

---

**Previous**: [03 - System Requirements](../03-system-requirements/README.md)

**Next**: [05 - First-Time Setup](../05-first-time-setup/README.md)
