"""Small local web adapter for jwave_codeagent.

Run this module from the repository's ``jw`` conda environment.  It keeps the
web layer deliberately thin: the agent remains the source of truth and the
browser receives newline-delimited JSON updates from ``SimulationWorkflow``.
"""
from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = Path(__file__).resolve().parent
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from jwave_flow.config import Settings  # noqa: E402
from jwave_flow.graph import SimulationWorkflow  # noqa: E402
from jwave_flow.history import append_record, load_records, make_record  # noqa: E402


def _json_default(value: Any) -> str:
    return str(value)


def _send_json(handler: SimpleHTTPRequestHandler, payload: dict[str, Any], status: int = 200) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=_json_default).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.end_headers()
    handler.wfile.write(body)


def _safe_settings(settings: Settings) -> dict[str, Any]:
    return {
        "analyst_model": settings.analyst_model,
        "coder_model": settings.coder_model,
        "base_url": settings.openai_base_url or "OpenAI default",
        "api_key_configured": bool(settings.openai_api_key),
        "retrieval_backend": settings.retrieval_backend,
        "top_k": settings.top_k,
        "executor_backend": settings.executor_backend,
        "exec_timeout": settings.exec_timeout,
        "max_iterations": settings.max_iterations,
        "gates": {
            "param": settings.param_check_enabled,
            "static": settings.static_check_enabled,
            "semantic": settings.semantic_check_enabled,
        },
    }


def _public_update(update: dict[str, Any]) -> dict[str, Any]:
    """Exclude bulky/non-serializable retrieval objects from browser updates."""
    allowed = {
        "requirement", "params_json", "param_check_ok", "param_check_rounds",
        "param_issues", "param_warnings", "param_constraints", "param_check_report",
        "static_issues", "static_rounds", "static_report", "code", "code_final",
        "stdout", "stderr", "last_error", "fix_reason", "results", "outputs",
        "new_files", "execution_time", "iterations", "success", "semantic_issues",
        "selfcheck", "verified", "text", "trace", "error", "error_hints",
    }
    return {key: update[key] for key in allowed if key in update}


class WebHandler(SimpleHTTPRequestHandler):
    """Serve the static app and a small JSON/NDJSON API."""

    server_version = "jwave-frontend/1.0"

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, directory=str(FRONTEND_ROOT), **kwargs)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[web] {format % args}", flush=True)

    def do_GET(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        if path == "/api/config":
            try:
                _send_json(self, {"settings": _safe_settings(Settings.from_env())})
            except Exception as exc:
                _send_json(self, {"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)
            return
        if path == "/api/history":
            _send_json(self, {"records": load_records(limit=30)})
            return
        if path.startswith("/api/"):
            _send_json(self, {"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if path == "/":
            self.path = "/index.html"
        super().do_GET()

    def do_POST(self) -> None:  # noqa: N802
        if urlparse(self.path).path != "/api/run":
            _send_json(self, {"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length) or b"{}")
            query = str(request.get("query", "")).strip()
            if not query:
                _send_json(self, {"error": "请输入仿真需求"}, HTTPStatus.BAD_REQUEST)
                return
        except (ValueError, json.JSONDecodeError) as exc:
            _send_json(self, {"error": f"请求格式错误：{exc}"}, HTTPStatus.BAD_REQUEST)
            return

        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/x-ndjson; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "close")
        self.end_headers()

        started = time.time()
        state: dict[str, Any] = {"query": query}

        def emit(event: dict[str, Any]) -> None:
            self.wfile.write((json.dumps(event, ensure_ascii=False, default=_json_default) + "\n").encode("utf-8"))
            self.wfile.flush()

        emit({"type": "start", "query": query})
        try:
            settings = Settings.from_env()
            emit({"type": "config", "settings": _safe_settings(settings)})
            with SimulationWorkflow(settings) as workflow:
                for update in workflow.stream(query):
                    if not isinstance(update, dict):
                        continue
                    for node, patch in update.items():
                        if isinstance(patch, dict):
                            state.update(patch)
                            emit({"type": "node", "node": node, "state": _public_update(patch)})
                state["elapsed"] = time.time() - started
                emit({"type": "complete", "state": _public_update(state)})
            append_record(make_record(state, query, settings, elapsed=state["elapsed"]))
        except Exception as exc:
            message = str(exc) or exc.__class__.__name__
            emit({"type": "error", "error": message})


def main() -> None:
    host = os.environ.get("JWAVE_FRONTEND_HOST", DEFAULT_HOST)
    port = int(os.environ.get("JWAVE_FRONTEND_PORT", str(DEFAULT_PORT)))
    try:
        server = ThreadingHTTPServer((host, port), WebHandler)
    except OSError as exc:
        if getattr(exc, "errno", None) == 98:
            raise SystemExit(
                f"端口 {port} 已被占用。若已有 jwave 前端在运行，请直接打开 "
                f"http://{host}:{port}；或使用其他端口："
                f"JWAVE_FRONTEND_PORT=8766 ./jwave_frontend/start.sh"
            ) from None
        raise
    print(f"jwave 前端已启动：http://{host}:{port}", flush=True)
    print(f"内核目录：{PROJECT_ROOT}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止", flush=True)
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
