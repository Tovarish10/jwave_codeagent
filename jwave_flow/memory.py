"""Opt-in project memory with redaction, distillation and feedback."""
from __future__ import annotations

import json
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any

from .config import PROJECT_ROOT
from .knowledge import tokenize

DEFAULT_MEMORY_PATH = PROJECT_ROOT / "run" / "memories.jsonl"
_SECRET_PATTERNS = (
    (re.compile(r"(?i)\b(?:api[_-]?key|token|password|secret)\b\s*[:=]\s*['\"]?[\w./+=-]{8,}"), "[REDACTED_SECRET]"),
    (re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"), "[REDACTED_KEY]"),
    (re.compile(r"-----BEGIN [^-]+-----.*?-----END [^-]+-----", re.DOTALL), "[REDACTED_PRIVATE_KEY]"),
    (re.compile(r"(?<![\w])(?:/home|/Users)/[^ \n:'\"]+"), "<PROJECT_PATH>"),
    (re.compile(r"(?i)\b[\w.+-]+@[\w.-]+\.[a-z]{2,}\b"), "<EMAIL>"),
)


def redact(value: Any, limit: int = 4000) -> str:
    """Remove common credentials and local identifiers before persistence."""
    text = "" if value is None else str(value)
    for pattern, replacement in _SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    text = re.sub(r"\b(?:sess|run)_[A-Za-z0-9_-]+\b", "<ID>", text)
    return text[:limit]


def _tokens(text: str) -> set[str]:
    return set(tokenize(text))


def _as_list(value: Any, limit: int = 8) -> list[str]:
    if not value:
        return []
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, (list, tuple)):
        values = value
    else:
        values = [value]
    return [redact(item, 500) for item in values if str(item).strip()][:limit]


class MemoryStore:
    def __init__(self, path: str | Path | None = None):
        configured = os.environ.get("MEMORY_PATH")
        self.path = Path(path or configured or DEFAULT_MEMORY_PATH).expanduser()

    def _read(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        memories: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict) and not item.get("deleted_at"):
                memories.append(item)
        return memories

    def search(self, query: str, limit: int = 3) -> list[dict[str, Any]]:
        query_tokens = _tokens(query)
        ranked = []
        for item in self._read():
            problem = item.get("problem", {})
            solution = item.get("solution", {})
            haystack = " ".join(
                [
                    str(item.get("title", "")),
                    str(problem.get("query", "") if isinstance(problem, dict) else problem),
                    str(problem.get("requirement", "") if isinstance(problem, dict) else ""),
                    str(solution.get("approach", "") if isinstance(solution, dict) else ""),
                    str(item.get("insight", "")),
                ]
            )
            overlap = len(query_tokens & _tokens(haystack))
            if overlap:
                ranked.append((overlap * float(item.get("confidence", 0.0)), item))
        ranked.sort(key=lambda pair: pair[0], reverse=True)
        return [item for _, item in ranked[:limit]]

    def context(self, query: str, limit: int = 3) -> str:
        memories = self.search(query, limit)
        if not memories:
            return ""
        rendered = []
        for item in memories:
            problem = item.get("problem", {})
            solution = item.get("solution", {})
            validation = item.get("validation", {})
            rendered.append(
                "\n".join(
                    [
                        f"历史经验：{item.get('title', '历史经验')}",
                        f"问题：{problem.get('query', '') if isinstance(problem, dict) else problem}",
                        f"需求：{problem.get('requirement', '') if isinstance(problem, dict) else ''}",
                        f"方案：{solution.get('approach', '') if isinstance(solution, dict) else ''}",
                        "步骤：" + "；".join(solution.get("steps", [])) if isinstance(solution, dict) else "步骤：",
                        "参数：" + json.dumps(solution.get("parameters", ""), ensure_ascii=False),
                        f"经验：{item.get('insight', '')}",
                        "验证：" + json.dumps(validation, ensure_ascii=False),
                        "反模式：" + "；".join(item.get("anti_patterns", [])),
                        "注意：历史经验仅供参考，必须以当前需求和当前验证结果为准。",
                    ]
                )
            )
        return "\n\n".join(rendered)

    def distill(self, query: str, result: dict[str, Any], session_id: str = "") -> dict[str, Any]:
        """Create an auditable problem/solution/evidence card.

        The card intentionally stores a bounded, redacted code pattern rather
        than the full generated program.
        """
        success = bool(result.get("success"))
        verified = bool(result.get("verified"))
        requirement = redact(result.get("requirement"), 1600)
        params = redact(result.get("params_json"), 2400)
        code = redact(result.get("code_final") or result.get("text") or result.get("code"), 6000)
        errors = _as_list(
            (result.get("param_issues") or [])
            + (result.get("static_issues") or [])
            + (result.get("semantic_issues") or [])
        )
        issue = redact(result.get("last_error") or result.get("stderr"), 1600)
        warnings = _as_list(result.get("param_warnings"))
        constraints = _as_list(result.get("param_constraints"))
        steps = _as_list(result.get("trace"), 12)
        if not steps:
            steps = ["提取需求和参数", "生成代码", "执行并进行确定性校验"]
        approach = (
            "根据需求提取物理参数，满足参数约束后生成代码，"
            "再通过静态检查、执行和语义校验闭环验证。"
        )
        anti_patterns = []
        if errors or issue:
            anti_patterns.append("不要忽略本次记录中的失败原因或校验问题")
        if warnings:
            anti_patterns.extend(warnings[:3])
        title = "已验证的仿真工作流经验" if verified else "待人工确认的仿真工作流经验"
        insight = (
            "本经验可复用的核心是：先满足约束，再生成并验证；"
            f"本次 success={success}, verified={verified}。"
        )
        card = {
            "schema_version": 2,
            "id": f"mem_{uuid.uuid4().hex[:12]}",
            "title": title,
            "problem": {"query": redact(query, 1000), "requirement": requirement},
            "solution": {
                "approach": approach,
                "parameters": params,
                "steps": steps,
                "constraints": constraints,
                "code_pattern": code,
            },
            "validation": {
                "success": success,
                "verified": verified,
                "param_check_ok": result.get("param_check_ok"),
                "static_issues": _as_list(result.get("static_issues")),
                "semantic_issues": _as_list(result.get("semantic_issues")),
                "selfcheck": redact(result.get("selfcheck"), 1600),
                "stdout_summary": redact(result.get("stdout"), 800),
                "error_summary": issue,
            },
            "insight": redact(insight, 1600),
            "anti_patterns": anti_patterns,
            "applicability": "当前 jwave 项目",
            "confidence": 0.9 if success and verified else 0.45,
            "source_session_id": redact(session_id, 100),
            "user_feedback": None,
            "created_at": time.time(),
        }
        return card

    def add(self, card: dict[str, Any]) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(card, ensure_ascii=False) + "\n")
        return card

    def record(self, query: str, result: dict[str, Any], session_id: str = "") -> dict[str, Any]:
        return self.add(self.distill(query, result, session_id))

    def feedback(self, memory_id: str, helpful: bool) -> bool:
        memories = self._read()
        found = False
        for item in memories:
            if item.get("id") != memory_id:
                continue
            found = True
            item["user_feedback"] = "helpful" if helpful else "not_helpful"
            item["confidence"] = min(1.0, float(item.get("confidence", 0.0)) + 0.1) if helpful else max(0.0, float(item.get("confidence", 0.0)) - 0.3)
            if not helpful and item["confidence"] == 0:
                item["deleted_at"] = time.time()
        if found:
            self.path.write_text(
                "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in memories),
                encoding="utf-8",
            )
        return found
