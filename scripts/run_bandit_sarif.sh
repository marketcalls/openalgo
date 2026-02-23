#!/usr/bin/env bash
# Run Bandit security scan and produce a valid SARIF report.
#
# Bandit 1.9.x has a bug in its SARIF formatter (IndexError in
# add_region_and_context_region) that can crash mid-write and leave
# the output file empty.  This wrapper validates the output and
# substitutes a minimal valid SARIF document when the formatter fails,
# so that downstream steps (e.g. github/codeql-action/upload-sarif)
# never receive broken JSON.
#
# Usage:
#   scripts/run_bandit_sarif.sh [output-path]
#
# The output path defaults to bandit.sarif.

set -euo pipefail

OUTPUT="${1:-bandit.sarif}"

# Run bandit; exit code is non-zero when findings exist, so don't fail.
uv run bandit -r . \
  -x .venv,test,frontend,node_modules \
  -f sarif \
  -o "$OUTPUT" || true

# Validate: file must be non-empty and parseable JSON.
if [ ! -s "$OUTPUT" ] || \
   ! python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$OUTPUT" 2>/dev/null; then

  echo "::warning::Bandit SARIF output was empty or invalid — substituting an empty report"

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
fi
