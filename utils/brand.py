"""FastAlgo brand for backend text: emails, bot messages, page titles.

Mirrors frontend/src/brand/brand.ts. Spec: docs/design/brand/design-language.md.

Per-instance white-label: custom_brand/brand.json at the repo root, for example
    {"displayName": "Sharma Capital", "logo": "sharma.png",
     "supportTelegramUrl": "https://t.me/SharmaDesk"}
can override the display name, the logo and the Telegram support link. The
product name, maker, and the AGPL attribution never change.
"""

import json
import re
from pathlib import Path

from utils.logging import get_logger

logger = get_logger(__name__)

PRODUCT_NAME = "FastAlgo"
TAGLINE = "Automate your trading strategy. Take fast trades."
MAKER_NAME = "TinyCompute"
MAKER_URL = "https://www.tinycompute.site"
PRODUCT_URL = "https://fastalgo.tinycompute.site"
SUPPORT_URL = "https://www.tinycompute.site"
# Default Telegram contact for support. Override per installation with
# "supportTelegramUrl" in custom_brand/brand.json.
SUPPORT_TELEGRAM_URL = "https://t.me/RanjT55"
SOURCE_URL = "https://github.com/ranjeetthorat/ai-algo"
ATTRIBUTION = "Based on OpenAlgo, licensed under AGPL-3.0"

CUSTOM_BRAND_DIR = Path(__file__).resolve().parent.parent / "custom_brand"
LOGO_EXTENSIONS = frozenset({".png", ".svg", ".jpg", ".jpeg", ".webp"})
NAME_MAX = 60
# A Telegram username link and nothing else: https only, t.me only, and a
# username as Telegram allows it (5 to 32 letters, digits or underscores).
TELEGRAM_URL = re.compile(r"https://t\.me/[A-Za-z0-9_]{5,32}")


def load_brand_override(brand_dir: Path | None = None) -> dict:
    """Read and validate brand.json. Returns only the fields that are safe to use.

    Keys in the result: ``displayName`` (str), ``logoUrl`` (a same-origin
    ``/custom-brand/<file>`` path, present only when the file exists) and
    ``supportTelegramUrl`` (a ``https://t.me/<username>`` link).
    """
    brand_dir = brand_dir or CUSTOM_BRAND_DIR
    path = brand_dir / "brand.json"
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.exception("custom_brand/brand.json could not be read, using the default brand")
        return {}
    if not isinstance(raw, dict):
        return {}

    override = {}
    name = raw.get("displayName")
    if isinstance(name, str) and name.strip():
        override["displayName"] = name.strip()[:NAME_MAX]

    logo = raw.get("logo")
    if isinstance(logo, str) and logo.strip():
        logo_name = Path(logo.strip()).name
        logo_path = brand_dir / logo_name
        # Advertise the logo only if it is really there: a missing file would
        # 404 on the login page, and unauthenticated 404s count toward an IP ban.
        if logo_path.suffix.lower() in LOGO_EXTENSIONS and logo_path.is_file():
            override["logoUrl"] = f"/custom-brand/{logo_name}"

    telegram = raw.get("supportTelegramUrl")
    if isinstance(telegram, str) and TELEGRAM_URL.fullmatch(telegram.strip()):
        override["supportTelegramUrl"] = telegram.strip()
    return override


def display_name() -> str:
    """The name to show: the client's name when white-labelled, otherwise FastAlgo."""
    return load_brand_override().get("displayName", PRODUCT_NAME)


def support_telegram_url() -> str:
    """The Telegram support link: this installation's override, otherwise the default."""
    return load_brand_override().get("supportTelegramUrl", SUPPORT_TELEGRAM_URL)


def endorsement() -> str:
    """'FastAlgo by TinyCompute', or 'Sharma Capital, powered by FastAlgo'."""
    name = display_name()
    if name == PRODUCT_NAME:
        return f"{PRODUCT_NAME} by {MAKER_NAME}"
    return f"{name}, powered by {PRODUCT_NAME}"


def email_signature() -> str:
    """Footer line for emails (decision Q7a): 'Sent by <name>, managed by TinyCompute'."""
    return f"Sent by {display_name()}, managed by {MAKER_NAME}"
