#!/bin/bash
# Helper script to run the option strategy backtester with proper environment setup

# Read API key from strategy_config.json
API_KEY=$(grep -o '"API_KEY": "[^"]*"' strategy_config.json | cut -d'"' -f4)

if [ -z "$API_KEY" ]; then
    echo "Error: Could not find API_KEY in strategy_config.json"
    exit 1
fi

# Export the API key for the backtester to use
export OPENALGO_API_KEY="$API_KEY"

# Ensure tmp_rovodev_backtest_config.json has config set to "strategy_config.json"
if [ -f "tmp_rovodev_backtest_config.json" ]; then
    sed -i.bak 's|"config": "[^"]*"|"config": "strategy_config.json"|' tmp_rovodev_backtest_config.json
    rm -f tmp_rovodev_backtest_config.json.bak
fi

echo "Running backtester with API key from strategy_config.json..."
echo "Using backtest config: tmp_rovodev_backtest_config.json"
echo ""

# Run the backtester
uv run option_strategy_backtester.py "$@"
