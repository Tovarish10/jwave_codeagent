"""The Dify "仿真" workflow, rebuilt with LangGraph.

Node order (identical to the Dify graph)::

    START → 需求分析 → 知识检索 → 模板转换 → 参数提取 → 代码生成 → 执行
                                                     ▲            │
                                                     │       stderr 为空?
                          代码纠错 ←──────── 否 ──────┘            │是
                                                            输出 → END

The Dify ``loop`` node (``loop_count = 10``) is expressed as a LangGraph cycle
that is capped by ``settings.max_iterations``.
"""
from __future__ import annotations

import sys
import time
from typing import Any

from langgraph.graph import END, START, StateGraph

from .config import Settings
from .executor import BaseExecutor, get_executor
from .knowledge import build_retriever, render_template_transform
from .llm import GeneratedCode, FixedCode, build_chat_model, invoke_code_llm
from .prompts import (
    code_fix_prompt,
    code_generate_prompt,
    param_extract_prompt,
    requirement_analyst_prompt,
)
from .state import WorkflowState


def _as_text(message: Any) -> str:
    content = getattr(message, "content", message)
    if isinstance(content, list):
        return "".join(
            part.get("text", "") if isinstance(part, dict) else str(part) for part in content
        )
    return str(content)


class SimulationWorkflow:
    """Owns the (reusable) LLM / retriever / executor resources."""

    def __init__(
        self,
        settings: Settings,
        *,
        analyst_llm: Any | None = None,
        coder_llm: Any | None = None,
        retriever: Any | None = None,
        executor: BaseExecutor | None = None,
    ):
        self.settings = settings
        self.analyst_llm = analyst_llm or build_chat_model(settings, settings.analyst_model)
        self.coder_llm = coder_llm or build_chat_model(settings, settings.coder_model)
        self.retriever = retriever or build_retriever(settings)
        self.executor = executor or get_executor(settings)
        self.graph = self._build()

    # -- nodes --------------------------------------------------------- #
    def _log(self, state: WorkflowState, message: str) -> list[str]:
        trace = list(state.get("trace") or [])
        trace.append(message)
        if self.settings.verbose:
            # stderr: keeps `--json` output on stdout machine-readable
            print(f"  · {message}", file=sys.stderr, flush=True)
        return trace

    def n_analyze(self, state: WorkflowState) -> dict:
        prompt = requirement_analyst_prompt().format_messages(query=state["query"])
        requirement = _as_text(self.analyst_llm.invoke(prompt))
        return {"requirement": requirement, "trace": self._log(state, "① 需求分析 完成")}

    def n_retrieve(self, state: WorkflowState) -> dict:
        docs = self.retriever.invoke(state["query"])
        return {
            "kb_docs": docs,
            "trace": self._log(state, f"② 知识检索 命中 {len(docs)} 个片段"),
        }

    def n_template(self, state: WorkflowState) -> dict:
        context = render_template_transform(state.get("kb_docs") or [])
        return {"kb_context": context, "trace": self._log(state, f"③ 模板转换 {len(context)} 字符")}

    def n_extract(self, state: WorkflowState) -> dict:
        prompt = param_extract_prompt().format_messages(
            query=state["query"], kb_context=state.get("kb_context", "")
        )
        params = _as_text(self.analyst_llm.invoke(prompt))
        return {"params_json": params, "trace": self._log(state, "④ 参数提取 完成")}

    def n_generate(self, state: WorkflowState) -> dict:
        prompt = code_generate_prompt().format_messages(
            query=state["query"], code_ref=state.get("params_json", "")
        )
        code = invoke_code_llm(self.coder_llm, prompt, GeneratedCode, ["code"])
        return {
            "code": code,
            "code_final": code,
            "iterations": 0,
            "trace": self._log(state, f"⑤ 代码生成 {len(code)} 字符"),
        }

    def n_run(self, state: WorkflowState) -> dict:
        code = state.get("code_final", "")
        result = self.executor.run(code)
        iterations = int(state.get("iterations", 0)) + 1
        status = "通过 ✅" if result.ok else "报错 ❌"
        return {
            **result.to_dict(),
            "success": result.ok,
            "iterations": iterations,
            "trace": self._log(
                state,
                f"⑥ 执行(第 {iterations} 次, {result.backend}) {status} "
                f"[{result.execution_time:.2f}s]",
            ),
        }

    def n_fix(self, state: WorkflowState) -> dict:
        prompt = code_fix_prompt().format_messages(
            code_final=state.get("code_final", ""),
            context=state.get("kb_context", ""),
            stderr=state.get("stderr", ""),
        )
        fixed = invoke_code_llm(self.coder_llm, prompt, FixedCode, ["code_2", "code"])
        return {
            "code_final": fixed,
            "trace": self._log(state, f"⑦ 代码纠错 {len(fixed)} 字符"),
        }

    def n_finalize(self, state: WorkflowState) -> dict:
        return {"text": state.get("code_final", ""), "trace": self._log(state, "⑧ 输出")}

    # -- routing ------------------------------------------------------- #
    def _route_after_run(self, state: WorkflowState) -> str:
        if state.get("success"):
            return "finalize"
        if int(state.get("iterations", 0)) >= self.settings.max_iterations:
            if self.settings.verbose:
                print(
                    f"  ! 达到最大迭代次数 {self.settings.max_iterations}，输出当前代码",
                    file=sys.stderr,
                    flush=True,
                )
            return "finalize"
        return "fix"

    # -- assembly ------------------------------------------------------ #
    def _build(self):
        g = StateGraph(WorkflowState)
        g.add_node("analyze", self.n_analyze)
        g.add_node("retrieve", self.n_retrieve)
        g.add_node("template", self.n_template)
        g.add_node("extract", self.n_extract)
        g.add_node("generate", self.n_generate)
        g.add_node("run_code", self.n_run)
        g.add_node("fix_code", self.n_fix)
        g.add_node("finalize", self.n_finalize)

        g.add_edge(START, "analyze")
        g.add_edge("analyze", "retrieve")
        g.add_edge("retrieve", "template")
        g.add_edge("template", "extract")
        g.add_edge("extract", "generate")
        g.add_edge("generate", "run_code")
        g.add_conditional_edges(
            "run_code", self._route_after_run, {"fix": "fix_code", "finalize": "finalize"}
        )
        g.add_edge("fix_code", "run_code")
        g.add_edge("finalize", END)
        return g.compile()

    # -- public API ---------------------------------------------------- #
    def invoke(self, query: str, **kwargs) -> WorkflowState:
        start = time.time()
        state: WorkflowState = {"query": query, "trace": [], "iterations": 0}
        out = self.graph.invoke(state, **kwargs)
        out["elapsed"] = time.time() - start  # type: ignore[index]
        return out

    def stream(self, query: str, **kwargs):
        yield from self.graph.stream({"query": query, "trace": [], "iterations": 0}, **kwargs)

    def close(self) -> None:
        self.executor.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


def run_workflow(query: str, settings: Settings | None = None, **kwargs) -> WorkflowState:
    """Convenience one-shot entry point."""
    settings = settings or Settings.from_env()
    with SimulationWorkflow(settings) as wf:
        return wf.invoke(query, **kwargs)
