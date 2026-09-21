"""End-to-end run of the graph with a stub LLM (no API key required)."""
from __future__ import annotations

from pathlib import Path

from jwave_flow.config import Settings
from jwave_flow.graph import SimulationWorkflow

ROOT = Path(__file__).resolve().parent.parent

BUGGY = "import sys\nprint('simulating')\nsys.stderr.write('ValueError: bad positions\\n')\n"
FIXED = "print('simulation ok')\n"


class _Msg:
    def __init__(self, content):
        self.content = content


def _prompt_text(prompt) -> str:
    if isinstance(prompt, str):
        return prompt
    if hasattr(prompt, "to_string"):
        return prompt.to_string()
    return "\n".join(getattr(m, "content", str(m)) for m in prompt)


class FakeLLM:
    """Returns canned answers keyed off the prompt, like the real nodes would."""

    def __init__(self, gen_code=BUGGY, fixed=FIXED):
        self.gen_code = gen_code
        self.fixed = fixed
        self.seen: list[str] = []

    def invoke(self, prompt):
        text = _prompt_text(prompt)
        self.seen.append(text)
        if "需求分析师" in text:
            return _Msg("需求描述：一个二维时域声学仿真。")
        if "参数提取器" in text:
            return _Msg('{"sound_speed": 1500.0, "density": 1000.0}')
        if "代码生成器" in text:
            return _Msg(self.gen_code)
        if "代码改正器" in text:
            return _Msg(self.fixed)
        raise AssertionError(f"unexpected prompt: {text[:80]}")

    def with_structured_output(self, schema, **kwargs):
        raise NotImplementedError("stub: force the text fallback path")


def _settings(**kw):
    return Settings.from_env(
        kb_path=ROOT / "kb" / "jwave_kb_organized.md",
        executor_backend="subprocess",
        retrieval_backend="bm25",
        verbose=False,
        **kw,
    )


def test_loop_repairs_broken_code_and_succeeds():
    settings = _settings(max_iterations=10)
    llm = FakeLLM()
    with SimulationWorkflow(settings, analyst_llm=llm, coder_llm=llm) as wf:
        out = wf.invoke("做个二维时域仿真")

    assert out["iterations"] == 2           # 1 failing run + 1 repair
    assert out["success"] is True
    assert out["text"] == FIXED.rstrip("\n")
    trace = "\n".join(out["trace"])
    for marker in ["① 需求分析", "② 知识检索", "③ 模板转换", "④ 参数提取",
                   "⑤ 代码生成", "⑥ 执行", "⑦ 代码纠错", "⑧ 输出"]:
        assert marker in trace
    # the knowledge base was actually retrieved and injected (参数提取 prompt)
    assert any("知识库参考：" in p and "###" in p for p in llm.seen)


def test_loop_gives_up_after_max_iterations():
    settings = _settings(max_iterations=2)
    llm = FakeLLM(gen_code=BUGGY, fixed=BUGGY)  # repair keeps failing
    with SimulationWorkflow(settings, analyst_llm=llm, coder_llm=llm) as wf:
        out = wf.invoke("做个二维时域仿真")

    assert out["iterations"] == 2           # capped at loop_count
    assert out["success"] is False
    assert out["text"] == BUGGY.rstrip("\n")
