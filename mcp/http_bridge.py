"""HTTP Bridge for OpenAlgo MCP — exposes all MCP tools as REST endpoints.

Allows Ollama, custom agents, and any HTTP client to use MCP tools.

Usage:
    python http_bridge.py YOUR_API_KEY http://127.0.0.1:5000 [--port 5100]

Endpoints:
    GET  /              → Welcome + list tools
    GET  /tools         → List all tools with OpenAI function-calling schema
    POST /tools/<name>  → Call a tool with JSON body
    GET  /health        → Bridge health check
"""
import argparse
import inspect
import json
import sys
from functools import wraps

from flask import Flask, jsonify, request
from flask_cors import CORS

# Import all tool modules
from tools import paper_trading, strategies, historify, options_analytics, ml_intelligence, testing

app = Flask(__name__)
CORS(app)

# Globals set at startup
API_KEY = ""
HOST = ""

# Registry: tool_name → {func, description, params}
TOOL_REGISTRY = {}


def _register_module_tools(module, prefix=""):
    """Register all public functions from a module as tools."""
    for name, func in inspect.getmembers(module, inspect.isfunction):
        if name.startswith("_"):
            continue
        tool_name = f"{prefix}{name}" if prefix else name
        sig = inspect.signature(func)
        params = {}
        for pname, param in sig.parameters.items():
            if pname in ("host", "api_key", "cookies"):
                continue
            ptype = "string"
            if param.annotation == int:
                ptype = "integer"
            elif param.annotation == float:
                ptype = "number"
            elif param.annotation == bool:
                ptype = "boolean"
            elif param.annotation == dict:
                ptype = "object"
            params[pname] = {
                "type": ptype,
                "required": param.default is inspect.Parameter.empty,
            }
            if param.default is not inspect.Parameter.empty and param.default is not None:
                params[pname]["default"] = param.default

        TOOL_REGISTRY[tool_name] = {
            "func": func,
            "description": (func.__doc__ or "").strip().split("\n")[0],
            "full_description": (func.__doc__ or "").strip(),
            "parameters": params,
        }


def _init_registry():
    """Register all tool modules."""
    _register_module_tools(paper_trading)
    _register_module_tools(strategies)
    _register_module_tools(historify)
    _register_module_tools(options_analytics)
    _register_module_tools(ml_intelligence)
    _register_module_tools(testing)


def _require_api_key(f):
    """Middleware to check API key."""
    @wraps(f)
    def decorated(*args, **kwargs):
        key = request.headers.get("X-API-Key") or request.args.get("apikey")
        if not key or key != API_KEY:
            return jsonify({"error": "Invalid or missing API key. Use X-API-Key header."}), 401
        return f(*args, **kwargs)
    return decorated


@app.route("/")
def index():
    return jsonify({
        "name": "OpenAlgo MCP HTTP Bridge",
        "version": "1.0.0",
        "tools": len(TOOL_REGISTRY),
        "docs": "GET /tools for full tool list, POST /tools/<name> to call a tool",
    })


@app.route("/tools")
def list_tools():
    """List all tools in OpenAI function-calling compatible format."""
    tools = []
    for name, info in sorted(TOOL_REGISTRY.items()):
        properties = {}
        required = []
        for pname, pinfo in info["parameters"].items():
            properties[pname] = {"type": pinfo["type"]}
            if "default" in pinfo:
                properties[pname]["default"] = pinfo["default"]
            if pinfo.get("required"):
                required.append(pname)

        tools.append({
            "type": "function",
            "function": {
                "name": name,
                "description": info["full_description"],
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        })
    return jsonify({"tools": tools, "count": len(tools)})


@app.route("/tools/<tool_name>", methods=["POST"])
@_require_api_key
def call_tool(tool_name):
    """Call a specific tool with JSON body parameters."""
    if tool_name not in TOOL_REGISTRY:
        return jsonify({"error": f"Tool '{tool_name}' not found. GET /tools for available tools."}), 404

    info = TOOL_REGISTRY[tool_name]
    func = info["func"]
    body = request.get_json(force=True, silent=True) or {}

    # Inject host, api_key, cookies
    sig = inspect.signature(func)
    kwargs = {}
    for pname in sig.parameters:
        if pname == "host":
            kwargs["host"] = HOST
        elif pname == "api_key":
            kwargs["api_key"] = API_KEY
        elif pname == "cookies":
            kwargs["cookies"] = None
        elif pname in body:
            kwargs[pname] = body[pname]
        elif sig.parameters[pname].default is not inspect.Parameter.empty:
            kwargs[pname] = sig.parameters[pname].default

    try:
        result = func(**kwargs)
        # Parse JSON string result
        try:
            return jsonify({"result": json.loads(result)})
        except (json.JSONDecodeError, TypeError):
            return jsonify({"result": result})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/health")
def health():
    return jsonify({"status": "ok", "tools": len(TOOL_REGISTRY), "host": HOST})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OpenAlgo MCP HTTP Bridge")
    parser.add_argument("api_key", help="OpenAlgo API key")
    parser.add_argument("host", help="OpenAlgo host URL (e.g., http://127.0.0.1:5000)")
    parser.add_argument("--port", type=int, default=5100, help="HTTP bridge port (default: 5100)")

    args = parser.parse_args()
    API_KEY = args.api_key
    HOST = args.host

    _init_registry()
    print(f"OpenAlgo MCP HTTP Bridge")
    print(f"  Tools: {len(TOOL_REGISTRY)}")
    print(f"  OpenAlgo: {HOST}")
    print(f"  Bridge: http://127.0.0.1:{args.port}")
    print(f"  Docs: http://127.0.0.1:{args.port}/tools")
    app.run(host="127.0.0.1", port=args.port, debug=False)
