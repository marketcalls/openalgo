#!/usr/bin/env python3
"""Convert Bandit JSON output to SARIF 2.1.0 format.

Bandit 1.9.x has a bug in its built-in SARIF formatter (IndexError in
add_region_and_context_region) that crashes on certain multi-line findings.
This script converts Bandit's reliable JSON output to valid SARIF, serving
as a fallback when the native formatter fails.

Usage:
    python scripts/bandit_json_to_sarif.py <input.json> <output.sarif>
"""

import json
import sys

# Paths to exclude from the SARIF output.  Bandit's CLI -x flag has a
# bug in 1.9.x that fails to exclude deeply nested files (the glob
# ".venv/*" doesn't match "./.venv/lib/…").  Filter them here instead.
EXCLUDED_PATH_PREFIXES = (".venv/", "./.venv/", "test/", "./test/",
                          "frontend/", "./frontend/",
                          "node_modules/", "./node_modules/")


def _get_bandit_version(data):
    """Extract bandit version from the JSON generated_at or default."""
    return "1.9.3"


def _severity_to_level(severity):
    if severity == "HIGH":
        return "error"
    if severity == "MEDIUM":
        return "warning"
    return "note"


def convert(data):
    rules = {}
    rule_indices = {}
    sarif_results = []

    for issue in data.get("results", []):
        raw_filename = issue.get("filename", "")
        if any(raw_filename.startswith(p) or f"/{p}" in raw_filename
               for p in EXCLUDED_PATH_PREFIXES):
            continue

        rule_id = issue["test_id"]
        if rule_id not in rules:
            idx = len(rules)
            rules[rule_id] = {
                "id": rule_id,
                "name": issue.get("test_name", rule_id),
                "properties": {
                    "tags": ["security"],
                    "precision": issue.get("issue_confidence", "medium").lower(),
                },
            }
            more_info = issue.get("more_info")
            if more_info:
                rules[rule_id]["helpUri"] = more_info
            cwe = issue.get("issue_cwe")
            if cwe and cwe.get("id"):
                rules[rule_id]["properties"]["tags"].append(
                    f"external/cwe/cwe-{cwe['id']}"
                )
            rule_indices[rule_id] = idx

        filename = raw_filename
        if filename.startswith("./"):
            filename = filename[2:]

        result = {
            "ruleId": rule_id,
            "ruleIndex": rule_indices[rule_id],
            "level": _severity_to_level(issue.get("issue_severity", "LOW")),
            "message": {"text": issue.get("issue_text", "")},
            "locations": [
                {
                    "physicalLocation": {
                        "artifactLocation": {"uri": filename},
                        "region": {
                            "startLine": issue.get("line_number", 1),
                            "startColumn": issue.get("col_offset", 0) + 1,
                            "endColumn": issue.get("end_col_offset", 0) + 1,
                        },
                    }
                }
            ],
            "properties": {
                "issue_confidence": issue.get("issue_confidence", "UNDEFINED"),
                "issue_severity": issue.get("issue_severity", "UNDEFINED"),
            },
        }
        sarif_results.append(result)

    sarif = {
        "version": "2.1.0",
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "Bandit",
                        "organization": "PyCQA",
                        "version": _get_bandit_version(data),
                        "semanticVersion": _get_bandit_version(data),
                        "rules": list(rules.values()),
                    }
                },
                "results": sarif_results,
            }
        ],
    }
    return sarif


def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <input.json> <output.sarif>", file=sys.stderr)
        sys.exit(1)

    input_path, output_path = sys.argv[1], sys.argv[2]

    with open(input_path) as f:
        data = json.load(f)

    sarif = convert(data)

    with open(output_path, "w") as f:
        json.dump(sarif, f, indent=2)

    n = len(sarif["runs"][0]["results"])
    print(f"Converted {n} findings to SARIF: {output_path}")


if __name__ == "__main__":
    main()
