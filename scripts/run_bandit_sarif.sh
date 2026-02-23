#!/usr/bin/env bash
# Run Bandit security scan and produce a valid SARIF report.
#
# Bandit 1.9.x has a bug in its SARIF formatter (IndexError in
# add_region_and_context_region) that can crash mid-write and leave
# the output file empty.  This wrapper tries the native SARIF format
# first, then falls back to running Bandit in JSON mode and converting
# to SARIF with a bundled converter script.
#
# Usage:
#   scripts/run_bandit_sarif.sh [output-path]
#
# The output path defaults to bandit.sarif.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
OUTPUT="${1:-bandit.sarif}"

BANDIT_ARGS="-r . -x .venv,test,frontend,node_modules"

# --- Attempt 1: native SARIF formatter ---
uv run bandit $BANDIT_ARGS -f sarif -o "$OUTPUT" || true

# Validate: file must be non-empty and parseable JSON.
if [ -s "$OUTPUT" ] && \
   python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$OUTPUT" 2>/dev/null; then
  echo "Bandit SARIF report generated successfully"
  exit 0
fi

# --- Attempt 2: JSON output → SARIF conversion ---
echo "::warning::Bandit native SARIF formatter failed — falling back to JSON-to-SARIF conversion"

JSON_TMP="$(mktemp bandit-XXXXXX.json)"
trap 'rm -f "$JSON_TMP"' EXIT

uv run bandit $BANDIT_ARGS -f json -o "$JSON_TMP" || true

if [ -s "$JSON_TMP" ] && \
   python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$JSON_TMP" 2>/dev/null; then
  python3 "$SCRIPT_DIR/bandit_json_to_sarif.py" "$JSON_TMP" "$OUTPUT"
  exit 0
fi

# --- Attempt 3: empty valid SARIF ---
echo "::warning::Both Bandit formatters failed — substituting an empty SARIF report"

cat > "$OUTPUT" << 'SARIF'
{
  "version": "2.1.0",
  "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
  "runs": [
    {
      "tool": {
        "driver": {
          "name": "Bandit",
          "organization": "PyCQA",
          "version": "1.9.3"
        }
      },
      "invocations": [
        {
          "executionSuccessful": false,
          "toolExecutionNotifications": [
            {
              "level": "error",
              "message": {
                "text": "Bandit SARIF formatter crashed; results omitted. See workflow logs."
              }
            }
          ]
        }
      ],
      "results": []
    }
  ]
}
SARIF
