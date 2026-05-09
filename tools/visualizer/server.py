#!/usr/bin/env python3
"""Lean backtest result visualizer server with run history."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from archive import archive_run
from parser import ParseError, extract_orders_from_detailed, parse_lean_results


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RESULTS_DIR = REPO_ROOT / "results"
DEFAULT_STATIC_DIR = Path(__file__).resolve().parent / "static"
RESULTS_DIR_HELP = "Archive root directory"


def _json_response(handler: SimpleHTTPRequestHandler, payload: Any, status: int = 200) -> None:
    content = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(content)))
    handler.end_headers()
    handler.wfile.write(content)


def _read_index(results_dir: Path) -> list[dict[str, Any]]:
    path = results_dir / "index.json"
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        return []
    return [entry for entry in data if isinstance(entry, dict)]


def _load_run_payload(results_dir: Path, run_id: str) -> dict[str, Any] | None:
    run_file = results_dir / "runs" / run_id / "normalized.json"
    if not run_file.exists():
        return None
    with run_file.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        return None

    # Backward compatibility: older normalized payloads don't include parsed orders
    # or have an empty orders list. Enrich from raw-detailed.json when needed.
    if not data.get("orders"):
        detailed_path = results_dir / "runs" / run_id / "raw-detailed.json"
        if detailed_path.exists():
            with detailed_path.open("r", encoding="utf-8") as handle:
                detailed = json.load(handle)
            if isinstance(detailed, dict):
                data["orders"] = extract_orders_from_detailed(detailed)

    if "orders" not in data:
        data["orders"] = []

    return data


def _latest_run_id(results_dir: Path) -> str | None:
    entries = _read_index(results_dir)
    if not entries:
        return None
    latest = entries[0]
    run_id = latest.get("runId")
    return str(run_id) if isinstance(run_id, str) and run_id else None


class VisualizerHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, results_dir: Path, static_dir: Path, **kwargs: Any) -> None:
        self.results_dir = results_dir
        super().__init__(*args, directory=str(static_dir), **kwargs)

    def end_headers(self) -> None:
        # Prevent caching of static assets so code changes are picked up immediately.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/api/runs":
            return _json_response(self, {"runs": _read_index(self.results_dir)})

        if path == "/api/latest":
            run_id = _latest_run_id(self.results_dir)
            if run_id is None:
                return _json_response(self, {"runId": None, "message": "No runs found"})
            return _json_response(self, {"runId": run_id})

        if path.startswith("/api/runs/"):
            return self._handle_run_endpoint(path)

        if path == "/" or path == "/index.html":
            return super().do_GET()

        return super().do_GET()

    def _handle_run_endpoint(self, path: str) -> None:
        parts = [part for part in path.split("/") if part]
        # /api/runs/{run_id}/{section}
        if len(parts) < 3:
            return _json_response(self, {"error": "Invalid run API path"}, status=HTTPStatus.BAD_REQUEST)

        run_id = parts[2]
        payload = _load_run_payload(self.results_dir, run_id)
        if payload is None:
            return _json_response(
                self,
                {"error": f"Run not found: {run_id}"},
                status=HTTPStatus.NOT_FOUND,
            )

        if len(parts) == 3:
            return _json_response(self, payload)

        section = parts[3]
        mapping = {
            "summary": payload.get("summary", {}),
            "equity": payload.get("equity", []),
            "drawdown": payload.get("drawdown", []),
            "trades": payload.get("trades", []),
            "orders": payload.get("orders", []),
            "raw": payload.get("raw", {}),
            "meta": {
                "runId": payload.get("runId"),
                "algorithmType": payload.get("algorithmType"),
                "dateRange": payload.get("dateRange", {}),
                "status": payload.get("status", "Unknown"),
                "startedAt": payload.get("startedAt", ""),
                "finishedAt": payload.get("finishedAt", ""),
            },
        }

        if section not in mapping:
            return _json_response(
                self,
                {"error": f"Unknown section: {section}"},
                status=HTTPStatus.BAD_REQUEST,
            )

        return _json_response(self, {section: mapping[section]})

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        # Keep stdout focused on useful runtime information.
        return


def _open_browser(port: int, run_id: str | None = None) -> None:
    url = f"http://localhost:{port}/"
    if run_id:
        url = f"{url}?run={run_id}"
    webbrowser.open(url)


def _cmd_ingest(args: argparse.Namespace) -> int:
    launcher_dir = Path(args.launcher_dir).expanduser().resolve()
    results_dir = Path(args.results_dir).expanduser().resolve()

    payload, artifacts = parse_lean_results(launcher_dir=launcher_dir, algorithm_type=args.algorithm_type)

    archive = archive_run(
        results_dir=results_dir,
        normalized_payload=payload,
        artifacts={
            "summary_json": artifacts.summary_json,
            "detailed_json": artifacts.detailed_json,
            "log_txt": artifacts.log_txt,
        },
    )

    if args.print_json:
        print(
            json.dumps(
                {
                    "runId": archive.run_id,
                    "runDir": str(archive.run_dir),
                    "index": str(archive.index_path),
                }
            )
        )
    else:
        print(archive.run_id)

    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    results_dir = Path(args.results_dir).expanduser().resolve()
    static_dir = Path(args.static_dir).expanduser().resolve()

    results_dir.mkdir(parents=True, exist_ok=True)
    (results_dir / "runs").mkdir(parents=True, exist_ok=True)

    handler = lambda *h_args, **h_kwargs: VisualizerHandler(  # noqa: E731
        *h_args,
        results_dir=results_dir,
        static_dir=static_dir,
        **h_kwargs,
    )

    server = ThreadingHTTPServer(("127.0.0.1", args.port), handler)

    run_id = args.run_id
    if not run_id:
        run_id = _latest_run_id(results_dir)

    if args.open:
        timer = threading.Timer(0.35, _open_browser, args=(args.port, run_id))
        timer.daemon = True
        timer.start()

    print(f"Visualizer running on http://localhost:{args.port}")
    if run_id:
        print(f"Selected run: {run_id}")
    print("Press Ctrl+C to stop.")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

    return 0


def _cmd_archive_and_serve(args: argparse.Namespace) -> int:
    try:
        payload, artifacts = parse_lean_results(
            launcher_dir=Path(args.launcher_dir).expanduser().resolve(),
            algorithm_type=args.algorithm_type,
        )
        archive = archive_run(
            results_dir=Path(args.results_dir).expanduser().resolve(),
            normalized_payload=payload,
            artifacts={
                "summary_json": artifacts.summary_json,
                "detailed_json": artifacts.detailed_json,
                "log_txt": artifacts.log_txt,
            },
        )
    except ParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    serve_args = argparse.Namespace(
        results_dir=args.results_dir,
        static_dir=args.static_dir,
        port=args.port,
        open=args.open,
        run_id=archive.run_id,
    )

    return _cmd_serve(serve_args)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Lean backtest visualizer")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest = subparsers.add_parser("ingest", help="Parse and archive latest Lean run")
    ingest.add_argument("--launcher-dir", required=True, help="Lean launcher output directory")
    ingest.add_argument("--algorithm-type", required=True, help="Algorithm type/class name")
    ingest.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help=RESULTS_DIR_HELP)
    ingest.add_argument("--print-json", action="store_true", help="Print JSON output instead of run id")
    ingest.set_defaults(handler=_cmd_ingest)

    serve = subparsers.add_parser("serve", help="Serve visualizer UI and API")
    serve.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help=RESULTS_DIR_HELP)
    serve.add_argument("--static-dir", default=str(DEFAULT_STATIC_DIR), help="Static asset directory")
    serve.add_argument("--port", type=int, default=3000, help="HTTP port")
    serve.add_argument("--open", action="store_true", help="Open browser automatically")
    serve.add_argument("--run-id", default="", help="Run id to open by default")
    serve.set_defaults(handler=_cmd_serve)

    archive_and_serve = subparsers.add_parser(
        "archive-and-serve",
        help="Parse, archive latest run, then serve the visualizer",
    )
    archive_and_serve.add_argument("--launcher-dir", required=True, help="Lean launcher output directory")
    archive_and_serve.add_argument("--algorithm-type", required=True, help="Algorithm type/class name")
    archive_and_serve.add_argument("--results-dir", default=str(DEFAULT_RESULTS_DIR), help=RESULTS_DIR_HELP)
    archive_and_serve.add_argument("--static-dir", default=str(DEFAULT_STATIC_DIR), help="Static asset directory")
    archive_and_serve.add_argument("--port", type=int, default=3000, help="HTTP port")
    archive_and_serve.add_argument("--open", action="store_true", help="Open browser automatically")
    archive_and_serve.set_defaults(handler=_cmd_archive_and_serve)

    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        return int(args.handler(args))
    except ParseError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"Server/IO error: {exc}", file=sys.stderr)
        return 3


if __name__ == "__main__":
    raise SystemExit(main())
