""".sample.env documents the web server setting without changing any install.

The setting is one commented-out line. An active line would pin every new
install's web server, and a bump of ENV_CONFIG_VERSION would stop every
existing server at its next restart (the version check asks a question no
service can answer). update.sh lists new variables from .sample.env, so a
commented line must not show up there either.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / ".sample.env"

KEYS = ("OPENALGO_WORKER_CLASS", "OPENALGO_GUNICORN_THREADS")


def _text() -> str:
    return SAMPLE.read_text(encoding="utf-8").replace("\r\n", "\n")


def test_the_setting_is_documented_but_not_set():
    text = _text()
    for key in KEYS:
        assert not re.search(rf"(?m)^[ \t]*(export[ \t]+)?{key}[ \t]*=", text), key
    assert "# OPENALGO_WORKER_CLASS = 'eventlet'" in text
    assert "OPENALGO_GUNICORN_THREADS" not in text, "the thread count is not a setting"


def test_update_sh_does_not_report_it_as_a_new_variable():
    """update.sh step 4: grep -oP "^[A-Z_][A-Z_0-9]+ *=" .sample.env."""
    listed = set(re.findall(r"(?m)^([A-Z_][A-Z_0-9]+) *=", _text()))
    assert "OPENALGO_WORKER_CLASS" not in listed


def test_the_config_version_header_matches_the_key():
    """The version is not bumped for this setting; header and key still agree."""
    text = _text()
    header = re.search(r"(?m)^# Version: (\S+)$", text).group(1)
    key = re.search(r"(?m)^ENV_CONFIG_VERSION = '([^']+)'$", text).group(1)
    assert header == key


def test_the_block_reads_as_plain_trader_language():
    text = _text()
    start = text.index("# Web server (optional")
    block = text[start : text.index("# OPENALGO_WORKER_CLASS = 'eventlet'", start)]
    assert "23:30 IST" in block
    assert "docs/gthread/README.md" in block
    for dash in ("–", "—"):
        assert dash not in block
