# FastAlgo Version Management
# This file is the single source of truth for version information.
#
# FastAlgo numbers its own releases (decision Q5). It was forked from
# OpenAlgo 2.0.2.5, which is recorded in NOTICE. pyproject.toml keeps the
# upstream package metadata and is not shown to users.

VERSION = "1.2.0"


def get_version() -> str:
    """Return the current FastAlgo version.

    Returns:
        str: The current version string (e.g. '1.0.0')
    """
    return VERSION
