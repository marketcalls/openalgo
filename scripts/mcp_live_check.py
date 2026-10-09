"""Live connectivity check for the agent's external data (MCP) servers.

Opt-in and never run by the test suite: it calls the real servers over the
network. For each registered server it initialises a session, lists the tools,
and makes one read-only call, printing how long each step took.

    uv run python scripts/mcp_live_check.py
    uv run python scripts/mcp_live_check.py --server nse_live --repeat 3

It goes through the same client the agent uses, with the same timeouts, retry
and circuit breaker, so a failure here is what a trader would see in a
conversation. Exit status is 0 when every server answered every step, else 1.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

# Run from anywhere: the repository root is one level up.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.agent.mcp import client as mcp_client  # noqa: E402
from services.agent.mcp.registry import registered_servers, server_by_key  # noqa: E402

#: One cheap, read-only call per server, keyed by the registry's server key,
#: with arguments that server's schema accepts. A registered server with no
#: entry here is connected to and listed, and its call step is skipped. A key
#: here that names no registered server is reported and ignored.
#: One cheap, read-only call per server key, run after the tool list. A server
#: without an entry is checked for connection and listing only.
SAMPLE_CALLS: dict[str, tuple[str, dict]] = {}


def check(key: str) -> bool:
    """Run the three steps against one server and print the outcome.

    Args:
        key: The server key.

    Returns:
        True when every step succeeded.
    """
    client = mcp_client.get_client(key)
    if client is None:
        print("  not a registered server")
        return False
    ok = True

    result = client.check()
    print(
        f"  connect + list: {'OK  ' if result.ok else 'FAIL'} {result.latency_ms:6d} ms  "
        f"tools={result.tool_count}  server={result.server_name or '-'}"
    )
    if not result.ok:
        print(f"    {result.message}")
        return False

    sample = SAMPLE_CALLS.get(key)
    if sample is None:
        print("  call: skipped (no sample call registered for this server)")
        return ok
    tool, arguments = sample
    started = time.monotonic()
    try:
        answer = client.call_tool(tool, arguments)
    except mcp_client.McpError as exc:
        elapsed = int((time.monotonic() - started) * 1000)
        print(f"  call {tool}: FAIL {elapsed:6d} ms  {type(exc).__name__}")
        print(f"    {exc}")
        if isinstance(exc, mcp_client.McpToolError) and exc.text:
            print(f"    server said: {exc.text[:300]}")
        return False
    elapsed = int((time.monotonic() - started) * 1000)
    preview = " ".join(answer.text.split())[:160]
    print(f"  call {tool}: OK   {elapsed:6d} ms  chars={len(answer.text)}")
    print(f"    {preview}")
    return ok


def main() -> int:
    """Parse arguments and check each selected server.

    Returns:
        The process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--server", action="append", help="server key; repeat for several")
    parser.add_argument("--repeat", type=int, default=1, help="rounds to run (default 1)")
    args = parser.parse_args()

    keys = [spec.key for spec in registered_servers()]
    if not keys:
        print("No MCP servers are registered (services/agent/mcp/registry.py).")
        return 0
    stale = sorted(key for key in SAMPLE_CALLS if server_by_key(key) is None)
    if stale:
        print(f"Sample calls for unregistered server(s) ignored: {', '.join(stale)}")
    if args.server:
        unknown = sorted(set(args.server) - set(keys))
        if unknown:
            print(f"Unknown server(s): {', '.join(unknown)}. Registered: {', '.join(keys)}")
            return 2
        keys = [key for key in keys if key in args.server]

    all_ok = True
    for round_number in range(1, max(1, args.repeat) + 1):
        for key in keys:
            spec = server_by_key(key)
            print(f"[round {round_number}] {spec.key} ({spec.title}) {spec.url}")
            all_ok = check(key) and all_ok
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
