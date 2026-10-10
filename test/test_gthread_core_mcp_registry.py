"""mcp/mcpserver.py is executed once, however many first MCP requests arrive together.

The loaded module was cached on a function attribute with no lock, so two
concurrent first requests (initialize and tools/list) each executed the file,
replacing sys.modules["openalgo_mcp_server"] under the first and building
duplicate SDK clients and tool registrations. Under eventlet the load did not
yield, so they could not overlap.
"""

from __future__ import annotations

import threading
import time
import types

import pytest

import utils.mcp_tool_registry as registry


@pytest.fixture
def cold_registry(monkeypatch):
    monkeypatch.delattr(registry._load_mcpserver_module, "_module", raising=False)
    yield registry
    try:
        del registry._load_mcpserver_module._module
    except AttributeError:
        pass


def test_simultaneous_first_loads_execute_the_file_once(cold_registry, monkeypatch):
    import importlib.util

    executions = []
    real_module_from_spec = importlib.util.module_from_spec

    class SlowLoader:
        def exec_module(self, module):
            executions.append(1)
            time.sleep(0.05)
            module.ACTIVE_TOOL_NAMES = ["get_quote"]

    def fake_spec(name, location):
        return types.SimpleNamespace(loader=SlowLoader(), name=name)

    monkeypatch.setattr(importlib.util, "spec_from_file_location", fake_spec)
    monkeypatch.setattr(
        importlib.util, "module_from_spec", lambda spec: types.ModuleType(spec.name)
    )
    barrier = threading.Barrier(8)
    modules = []

    def first_request():
        barrier.wait()
        modules.append(registry._load_mcpserver_module())

    threads = [threading.Thread(target=first_request) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)

    assert executions == [1]
    assert len({id(m) for m in modules}) == 1
    assert registry.active_tool_names() == {"get_quote"}
    assert real_module_from_spec is not None
