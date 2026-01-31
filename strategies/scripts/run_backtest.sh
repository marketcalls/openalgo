#!/bin/bash
set -euo pipefail
# Helper script to run the option strategy backtester with proper environment setup

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo "Error: jq is required but not installed. Please install it first."
    echo "  macOS: brew install jq"
    echo "  Ubuntu/Debian: sudo apt-get install jq"
    exit 1
fi

# Check if strategy_config.json exists
if [ ! -f "strategy_config.json" ]; then
    echo "Error: strategy_config.json not found in current directory"
    exit 1
fi

# Read API key from strategy_config.json using jq for robust parsing
API_KEY=$(jq -r '.API_KEY // empty' strategy_config.json)

if [ -z "$API_KEY" ]; then
    echo "Error: Could not find API_KEY in strategy_config.json"
    exit 1
fi

# Export the API key for the backtester to use
export OPENALGO_API_KEY="$API_KEY"

# Ensure tmp_rovodev_backtest_config.json has config set to "strategy_config.json"
if [ -f "tmp_rovodev_backtest_config.json" ]; then
    # Use jq for safe JSON manipulation with atomic write
    TMP_FILE=$(mktemp)
    jq '.config = "strategy_config.json"' tmp_rovodev_backtest_config.json > "$TMP_FILE"
    mv "$TMP_FILE" tmp_rovodev_backtest_config.json
    echo "Updated tmp_rovodev_backtest_config.json to reference strategy_config.json"
fi

echo "Running backtester with API key from strategy_config.json..."
echo "Using backtest config: tmp_rovodev_backtest_config.json"
echo ""

# Run the backtester
uv run option_strategy_backtester.py "$@"
