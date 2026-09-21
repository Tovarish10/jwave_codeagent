"""Shared state passed between LangGraph nodes."""
from __future__ import annotations

from typing import Annotated, Any, TypedDict


def _overwrite(_old, new):  # last-write-wins reducer (explicit, avoids surprises)
    return new


class WorkflowState(TypedDict, total=False):
    # --- inputs ---------------------------------------------------------
    query: str

    # --- ① 需求分析 ------------------------------------------------------
    requirement: str

    # --- ②③④ 知识检索 / 模板转换 ------------------------------------------
    kb_docs: Annotated[list[Any], _overwrite]
    kb_context: str

    # --- ④ 参数提取 ------------------------------------------------------
    params_json: str

    # --- ⑤ 代码生成 ------------------------------------------------------
    code: str

    # --- ⑥ 循环（执行 → 纠错） -------------------------------------------
    code_final: str
    stdout: str
    stderr: str
    results: Annotated[list[str], _overwrite]
    outputs: Annotated[list[str], _overwrite]
    new_files: Annotated[list[str], _overwrite]
    execution_time: float
    iterations: int
    success: bool

    # --- ⑧ 输出 / 观测 --------------------------------------------------
    text: str
    trace: Annotated[list[str], _overwrite]
