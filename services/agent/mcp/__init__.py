"""External data servers reached over the Model Context Protocol.

* :mod:`services.agent.mcp.registry` declares the servers. Adding one is one
  entry in ``MCP_SERVERS``.
* :mod:`services.agent.mcp.client` is the synchronous streamable-HTTP client,
  with its timeouts, retry, circuit breaker and tool-list cache.
* :mod:`services.agent.mcp.prompt` writes the prompt section from the registry.
* ``services/agent/tools/mcp.py`` is the one toolkit that exposes every server
  to the model through two tools.

Importing this package does no network work and needs no agno.
"""
