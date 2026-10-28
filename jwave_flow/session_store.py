"""Small file-backed store for task-level conversation sessions."""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT

DEFAULT_SESSIONS_DIR = PROJECT_ROOT / "run" / "sessions"
MAX_CODE_CHARS = 200_000
MAX_TEXT_CHARS = 12_000


def _clip(value: Any, limit: int) -> str:
    text = "" if value is None else str(value)
    return text if len(text) <= limit else text[:limit] + "\n…（已截断）"


class SessionStore:
    def __init__(self, directory: str | Path | None = None):
        self.directory = Path(directory or DEFAULT_SESSIONS_DIR).expanduser()

    def _path(self, session_id: str) -> Path:
        if not session_id or "/" in session_id or "\\" in session_id or ".." in session_id:
            raise ValueError("无效的 session_id")
        return self.directory / f"{session_id}.json"

    def create(self, title: str = "未命名仿真", *, collect_memory: bool = False) -> dict[str, Any]:
        now = time.time()
        session = {
            "id": f"sess_{time.strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
            "title": _clip(title.strip() or "未命名仿真", 100),
            "created_at": now,
            "updated_at": now,
            "consent": {"collect_memory": bool(collect_memory)},
            "turns": [],
            "current": {},
        }
        self.save(session)
        return session

    def save(self, session: dict[str, Any]) -> None:
        path = self._path(str(session["id"]))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(session, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def get(self, session_id: str) -> dict[str, Any] | None:
        path = self._path(session_id)
        if not path.exists():
            return None
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"会话文件无法读取：{path}") from exc
        return value if isinstance(value, dict) else None

    def list(self) -> list[dict[str, Any]]:
        if not self.directory.exists():
            return []
        result = []
        for path in self.directory.glob("sess_*.json"):
            try:
                session = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if isinstance(session, dict):
                result.append({
                    "id": session.get("id", path.stem),
                    "title": session.get("title", "未命名仿真"),
                    "created_at": session.get("created_at", 0),
                    "updated_at": session.get("updated_at", 0),
                    "turn_count": len(session.get("turns") or []),
                })
        return sorted(result, key=lambda item: item["updated_at"], reverse=True)

    def append_turn(self, session: dict[str, Any], query: str, result: dict[str, Any]) -> dict[str, Any]:
        turns = session.setdefault("turns", [])
        turn = {
            "index": len(turns) + 1,
            "query": query,
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "success": bool(result.get("success")),
            "verified": bool(result.get("verified")),
            "code": _clip(result.get("text") or result.get("code_final"), MAX_CODE_CHARS),
            "params_json": _clip(result.get("params_json"), MAX_TEXT_CHARS),
            "stdout": _clip(result.get("stdout"), MAX_TEXT_CHARS),
            "stderr": _clip(result.get("stderr"), MAX_TEXT_CHARS),
            "error": _clip(result.get("error") or result.get("last_error"), MAX_TEXT_CHARS),
            "trace": list(result.get("trace") or [])[-20:],
        }
        turns.append(turn)
        session["updated_at"] = time.time()
        session["current"] = {
            "code": turn["code"],
            "params_json": turn["params_json"],
            "requirement": _clip(result.get("requirement"), MAX_TEXT_CHARS),
            "stdout": turn["stdout"],
            "stderr": turn["stderr"],
            "success": turn["success"],
            "verified": turn["verified"],
            "last_query": query,
            "turn_index": turn["index"],
        }
        self.save(session)
        return session
