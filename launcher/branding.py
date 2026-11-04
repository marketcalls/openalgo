"""The product name for launcher messages, from the same source as the app.

``utils/brand.py`` is the backend's single source of the brand, but it imports
the app's logging, which the launcher must not (see ``launcher/__init__.py``).
So this reads the two facts it needs without importing it: the
``PRODUCT_NAME`` constant from that file's text, and the client's
``displayName`` from ``custom_brand/brand.json``, validated as
``utils.brand.load_brand_override`` does.
"""

import json
import re
from pathlib import Path

_PRODUCT_NAME = re.compile(r'^PRODUCT_NAME\s*=\s*"([^"]+)"', re.MULTILINE)

#: Same limit as utils.brand.NAME_MAX.
NAME_MAX = 60


def product_name(app: Path) -> str:
    try:
        match = _PRODUCT_NAME.search((app / "utils" / "brand.py").read_text(encoding="utf-8"))
    except OSError:
        match = None
    # Without the source there is no name to show; say what the thing is instead.
    return match.group(1) if match else "Trading platform"


def display_name(app: Path) -> str:
    """The client's white-label name when set, otherwise the product name."""
    try:
        raw = json.loads((app / "custom_brand" / "brand.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raw = None
    if isinstance(raw, dict):
        name = raw.get("displayName")
        if isinstance(name, str) and name.strip():
            return name.strip()[:NAME_MAX]
    return product_name(app)
