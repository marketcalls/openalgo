#!/bin/bash
# Strategy Runner - Unsets problematic SSL environment variables
# This ensures API calls work correctly on macOS with Homebrew Python
#
# Usage:
#   ./run_strategy.sh nifty_optionsalpha.py
#   ./run_strategy.sh optionalpha_25.py

# Unset old SSL certificate paths
unset SSL_CERT_FILE
unset REQUESTS_CA_BUNDLE

# Check if strategy file provided
if [ -z "$1" ]; then
    echo "Usage: $0 <strategy_file.py>"
    echo "Examples:"
    echo "  $0 nifty_optionsalpha.py"
    echo "  $0 optionalpha_25.py"
    exit 1
fi

# Run the strategy
echo "Starting strategy: $1"
uv run python3 "$@"
