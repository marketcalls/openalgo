"""Import LiteLLM, or one of its submodules, without racing another request.

LiteLLM is imported on demand, never at module scope: it costs several seconds
and every route that does not run a model works without it. The first import
therefore happens inside whichever request needs it first, and opening
/agent/config sends several of those at once (the catalogue, the ChatGPT plan
status, the model list, a model test).

Two first imports running together deadlock inside Python's import system. One
thread runs ``import litellm``, whose ``__init__`` reaches ``litellm.llms``;
the other runs ``from litellm.llms.chatgpt.authenticator import ...``, which
holds ``litellm.llms`` and waits for ``litellm``. Python detects the cycle and
raises ``_DeadlockError`` in one thread, the other fails with
``KeyError: 'litellm'``, and the half-built package left in ``sys.modules`` has
no ``exceptions`` attribute. Every later model test then fails with
"module 'litellm' has no attribute 'exceptions'" until the process restarts.
Reproduced three times out of three with LiteLLM 1.106.6 and two plain threads.

So every import of LiteLLM in the agent goes through :func:`load`, which
serialises the imports that can still do work and leaves the finished ones
lock-free.

The lock is a plain ``threading.Lock`` on purpose. Under eventlet it is green,
which is what the import needs: LiteLLM fetches its remote model map while it
imports, so the greenlet holding the lock must be able to yield to the hub, and
a waiting greenlet must yield rather than block the only worker. Under gthread
and on the development server it is a real lock. The fast path takes no lock,
so a real thread reaching LiteLLM after the import (the eventlet asyncify hop)
never touches the green primitive.
"""

from __future__ import annotations

import importlib
import sys
import threading
from types import ModuleType

from utils.logging import get_logger

logger = get_logger(__name__)

_import_lock = threading.Lock()
# Set once the compatibility patches ran. Until then every call takes the lock,
# even when something else (agno, a test) already imported LiteLLM itself.
_compat_installed = False


def _loaded(name: str) -> ModuleType | None:
    """Return a module only when it and the litellm package finished importing.

    A module appears in ``sys.modules`` before its body has run, so presence
    alone does not mean ready. ``__spec__._initializing`` is what the import
    system sets while a module body is still executing.
    """
    root = sys.modules.get("litellm")
    module = sys.modules.get(name)
    for candidate in (root, module):
        if candidate is None:
            return None
        spec = getattr(candidate, "__spec__", None)
        if getattr(spec, "_initializing", False):
            return None
    return module


def load(name: str = "litellm") -> ModuleType:
    """Import ``litellm`` or one of its submodules, one importer at a time.

    Args:
        name: The dotted module name, ``litellm`` itself or a submodule such as
            ``litellm.llms.chatgpt.authenticator``.

    Returns:
        The imported module.

    Raises:
        ValueError: When ``name`` is not litellm or a submodule of it.
        Exception: Whatever the import raises, unchanged, so each caller keeps
            its own handling of a missing or broken install.
    """
    if name != "litellm" and not name.startswith("litellm."):
        raise ValueError(f"not a litellm module: {name}")

    module = _loaded(name) if _compat_installed else None
    if module is not None:
        return module

    with _import_lock:
        # The package first, on its own. This is a guard in its own right, not
        # just tidiness: a thread importing the bare package while another
        # runs its body waits on the package's import lock holding nothing
        # else, so no cycle can form, even against an importer that bypasses
        # this module (agno's own `import litellm`). Importing the submodule
        # directly is what deadlocked: it takes litellm.llms on the way to
        # litellm. The race test fails only with this line and the lock both
        # removed, so keep both.
        importlib.import_module("litellm")
        _install_compat()
        return importlib.import_module(name)


def _install_compat() -> None:
    """Apply the compatibility patches every LiteLLM caller depends on.

    Here rather than at each call site, so the model test, the catalogue and a
    chat turn all get them from whichever imports LiteLLM first. Idempotent;
    runs under the import lock. Never raises: a LiteLLM of an unexpected shape
    should cost the patch, not the import.
    """
    global _compat_installed
    if _compat_installed:
        return
    from services.agent import litellm_mcp_gateway

    try:
        litellm_mcp_gateway.install(importlib.import_module(litellm_mcp_gateway.RESPONSES_MODULE))
    except Exception:
        logger.exception("Could not install the LiteLLM MCP gateway gate")
    _compat_installed = True
