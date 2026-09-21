"""交互式 CLI（TUI）的单元测试：不联网、不调用真实模型。

覆盖三块：
  * 渲染（panels）—— 给一堆假的 state，必须不抛异常且含关键信息
  * 历史（history）—— 追加 / 读取 / 损坏行容错
  * 交互（tui）—— 用假 workflow + 脚本化输入跑一遍完整菜单流程
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from jwave_flow import panels
from jwave_flow.config import Settings
from jwave_flow.history import append_record, clear_records, load_records, make_record
from jwave_flow.panels import Step
from jwave_flow.tui import (
    FIELDS,
    STEP_DEFS,
    Runner,
    TuiApp,
    next_node,
    step_outcome,
    upsert_env,
)

ROOT = Path(__file__).resolve().parent.parent

FAKE_RESULT = {
    "requirement": "需求描述：二维时域声学仿真。",
    "params_json": '{"sound_speed": 1500, "source_frequency": 5e6}',
    "param_check_ok": True,
    "param_check_rounds": 1,
    "param_warnings": ["网格欠采样：每波长仅 4 个网格点"],
    "param_issues": [],
    "param_constraints": ["dx ≤ 5e-5 m"],
    "param_check_report": {"scalars": {"sound_speed": 1500.0, "frequency": 5e6}},
    "static_issues": [],
    "static_rounds": 1,
    "semantic_issues": [],
    "verified": True,
    "selfcheck": {"finite": True, "abs_max": 5016.6},
    "success": True,
    "iterations": 2,
    "execution_time": 1.5,
    "executor_backend": "subprocess",
    "stdout": "run ok\n",
    "stderr": "",
    "new_files": [],
    "kb_context": "…",
    "kb_docs": [],
    "text": "import jwave as jw\nprint('ok')\n",
    "trace": ["① 需求分析 完成", "⑥ 执行(第 1 次, subprocess) 报错 ❌ [0.4s]"],
}


def _console():
    from rich.console import Console

    return Console(width=100, force_terminal=False, record=True)


def _settings(**kw) -> Settings:
    return Settings.from_env(
        kb_path=ROOT / "kb" / "jwave_kb_organized.md",
        openai_api_key="sk-test",
        verbose=False,
        **kw,
    )


# --------------------------------------------------------------------------- #
# 路由 / 状态推断
# --------------------------------------------------------------------------- #
def test_next_node_follows_graph_routes():
    assert next_node("analyze", {}, 10) == "retrieve"
    assert next_node("template", {}, 10) == "extract"
    # 参数预检失败 -> 回退参数提取；重试到上限 -> 继续生成
    assert next_node("param_check", {"param_check_ok": False, "param_check_rounds": 1}, 10) == "extract"
    assert next_node("param_check", {"param_check_ok": False, "param_check_rounds": 2}, 2) == "generate"
    assert next_node("param_check", {"param_check_ok": True}, 10) == "generate"
    # 静态检查发现问题 -> 纠错；修到上限 -> 仍然执行
    assert next_node("static_check", {"static_issues": ["R1"]}, 10) == "fix_code"
    assert next_node("static_check", {"static_issues": ["R1"], "static_rounds": 3}, 3) == "run_code"
    assert next_node("static_check", {"static_issues": []}, 10) == "run_code"
    # 执行失败 -> 纠错；成功 -> 语义门
    assert next_node("run_code", {"success": False, "iterations": 1}, 10) == "fix_code"
    assert next_node("run_code", {"success": True}, 10) == "semantic_gate"
    # 语义门 -> 输出 / 纠错
    assert next_node("semantic_gate", {"verified": True}, 10) == "finalize"
    assert next_node("semantic_gate", {"verified": False, "iterations": 1}, 10) == "fix_code"
    assert next_node("fix_code", {}, 10) == "static_check"
    assert next_node("finalize", {}, 10) is None


def test_step_outcome_maps_state_to_status():
    assert step_outcome("param_check", {"param_check_ok": True, "param_warnings": ["w"]})[0] == "done"
    assert step_outcome("param_check", {"param_check_ok": False, "param_issues": ["e"]})[0] == "fail"
    assert step_outcome("static_check", {"static_issues": ["R1"]})[0] == "fail"
    assert step_outcome("run_code", {"success": True, "backend": "subprocess"})[0] == "done"
    assert step_outcome("run_code", {"success": False})[0] == "fail"
    assert step_outcome("semantic_gate", {"verified": True, "selfcheck": {"abs_max": 3.0}})[0] == "done"
    assert step_outcome("semantic_gate", {"verified": False, "semantic_issues": ["S1"]})[0] == "fail"
    for key, _ in STEP_DEFS:
        step_outcome(key, FAKE_RESULT)  # 全节点都必须能渲染备注


# --------------------------------------------------------------------------- #
# 渲染
# --------------------------------------------------------------------------- #
def test_panels_render_without_error():
    console = _console()
    console.print(panels.banner("0.1.0"))
    console.print(panels.config_panel(_settings()))
    console.print(panels.task_panel("二维仿真", _settings()))
    steps = [Step(k, l) for k, l in STEP_DEFS]
    steps[0].mark("done", elapsed=0.1, note="ok")
    steps[1].mark("running")
    console.print(panels.pipeline_panel(steps))
    console.print(panels.counters_panel({"iterations": 1, "success": True}, 10))
    console.print(panels.log_panel(["a", "b"]))
    console.print(panels.params_panel(FAKE_RESULT))
    console.print(panels.gates_table(FAKE_RESULT))
    console.print(panels.selfcheck_panel(FAKE_RESULT))
    console.print(panels.execution_panel(FAKE_RESULT))
    console.print(panels.code_panel(FAKE_RESULT["text"]))
    console.print(panels.requirement_panel(FAKE_RESULT))
    console.print(panels.kb_stats_panel(FAKE_RESULT))
    console.print(panels.final_report(FAKE_RESULT, elapsed=9.9))
    text = console.export_text()
    assert "三道关" in text or "方案一" in text
    assert "最终代码" in text
    assert "运行成功 ✅" in text


def test_panels_survives_empty_state():
    """半成品 state（甚至全空）也不能炸。"""
    console = _console()
    console.print(panels.final_report({}, elapsed=0))
    console.print(panels.params_panel({}))
    console.print(panels.selfcheck_panel({}))
    console.print(panels.execution_panel({}))
    console.print(panels.history_table([]))
    assert "最终代码" in console.export_text()


def test_try_parse_json_strips_code_fence():
    assert panels.try_parse_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert panels.try_parse_json('前面的话 {"b": 2} 后面') == {"b": 2}
    assert panels.try_parse_json("不是 JSON") is None


# --------------------------------------------------------------------------- #
# 历史
# --------------------------------------------------------------------------- #
def test_history_roundtrip_and_corrupt_lines(tmp_path):
    path = tmp_path / "history.jsonl"
    rec = make_record(FAKE_RESULT, "二维仿真", _settings(), elapsed=3.0)
    append_record(rec, path)
    append_record(make_record(FAKE_RESULT, "第二个任务", None, elapsed=1.0), path)
    # 人为写入一行坏数据，读取端必须跳过而不是崩溃
    with path.open("a", encoding="utf-8") as fh:
        fh.write("{ this is not json }\n")

    records = load_records(path)
    assert len(records) == 2
    assert records[0]["title"] == "第二个任务"      # 最新的在前
    assert records[1]["gates"]["semantic_ok"] is True
    assert records[1]["model"]["analyst"] == "deepseek-v4-flash"
    assert clear_records(path) is True
    assert load_records(path) == []


def test_history_missing_file_is_empty(tmp_path):
    assert load_records(tmp_path / "nope.jsonl") == []


# --------------------------------------------------------------------------- #
# .env 写入
# --------------------------------------------------------------------------- #
def test_upsert_env_updates_in_place_and_appends(tmp_path):
    template = tmp_path / "example.env"
    template.write_text("# 注释\nRETRIEVAL_TOP_K=4   # top_k\nLOOP_MAX_ITERATIONS=10\n", encoding="utf-8")
    env = tmp_path / ".env"

    upsert_env(env, {"RETRIEVAL_TOP_K": "8"}, template=template)
    text = env.read_text(encoding="utf-8")
    assert "RETRIEVAL_TOP_K=8" in text
    assert "# 注释" in text                       # 注释被保留
    assert "RETRIEVAL_TOP_K=4" not in text

    upsert_env(env, {"ANALYST_MODEL": "gpt-4o-mini"})
    text = env.read_text(encoding="utf-8")
    assert "ANALYST_MODEL=gpt-4o-mini" in text
    assert "LOOP_MAX_ITERATIONS=10" in text        # 其它键原样保留

    upsert_env(env, {"RETRIEVAL_TOP_K": "16"})     # 二次更新不应重复追加
    assert env.read_text(encoding="utf-8").count("RETRIEVAL_TOP_K=") == 1


def test_field_catalog_matches_settings_attributes():
    settings = _settings()
    for field in FIELDS:
        assert hasattr(settings, field.attr), field.attr


# --------------------------------------------------------------------------- #
# 执行器（Runner）
# --------------------------------------------------------------------------- #
class FakeWorkflow:
    """最小可用的 workflow 替身：只实现 stream() 与上下文管理。"""

    def __init__(self, chunks):
        self.chunks = chunks
        self.closed = False
        self.queries: list[str] = []

    def stream(self, query):
        self.queries.append(query)
        for chunk in self.chunks:
            yield chunk

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.closed = True
        return False


CHUNKS = [
    {"analyze": {"requirement": "需求描述：二维仿真。", "trace": ["① 需求分析 完成"]}},
    {"retrieve": {"kb_docs": [], "trace": ["① 需求分析 完成", "② 知识检索 命中 0 个片段"]}},
    {"template": {"kb_context": "", "trace": ["③ 模板转换 0 字符"]}},
    {"extract": {"params_json": '{"sound_speed": 1500}', "trace": ["④ 参数提取 完成"]}},
    {"param_check": {"param_check_ok": True, "param_check_rounds": 1, "param_issues": [],
                     "param_warnings": [], "param_check_report": {}, "trace": ["④b 参数预检 通过"]}},
    {"generate": {"code": "print(1)", "code_final": "print(1)", "iterations": 0,
                  "trace": ["⑤ 代码生成 8 字符"]}},
    {"static_check": {"static_issues": [], "static_rounds": 1, "static_report": {},
                      "trace": ["⑤b 静态检查 通过"]}},
    {"run_code": {"stdout": "1", "stderr": "", "success": True, "iterations": 1,
                  "execution_time": 0.1, "backend": "subprocess", "trace": ["⑥ 执行 通过 ✅"]}},
    {"semantic_gate": {"verified": True, "semantic_issues": [], "selfcheck": {"abs_max": 1.0},
                       "trace": ["⑥b 语义门 通过"]}},
    {"finalize": {"text": "print(1)", "verified": True, "trace": ["⑧ 输出"]}},
]


def test_runner_streams_and_merges_state():
    console = _console()
    wf_holder: dict = {}

    def factory(settings):
        wf = FakeWorkflow(CHUNKS)
        wf_holder["wf"] = wf
        return wf

    runner = Runner(_settings(), console, workflow_factory=factory)
    state, elapsed = runner.run("二维仿真")

    assert state["text"] == "print(1)"
    assert state["success"] is True
    assert state["verified"] is True
    assert state["iterations"] == 1
    assert elapsed >= 0
    assert wf_holder["wf"].closed is True          # 上下文管理器被正确关闭
    assert wf_holder["wf"].queries == ["二维仿真"]

    out = console.export_text()
    for _, label in STEP_DEFS:
        assert label in out                        # 每个节点都出现在流程面板里
    assert "⑧ 输出" in out


def test_runner_propagates_errors_and_close():
    console = _console()

    class Boom(FakeWorkflow):
        def stream(self, query):
            raise RuntimeError("no api key")

    runner = Runner(_settings(), console, workflow_factory=lambda s: Boom([]))
    with pytest.raises(RuntimeError):
        runner.run("x")


# --------------------------------------------------------------------------- #
# 完整交互流程（脚本化输入）
# --------------------------------------------------------------------------- #
class ScriptedPrompter:
    """把一段脚本喂给 TuiApp，替代真实键盘输入。"""

    def __init__(self, answers):
        self.answers = list(answers)
        self.seen: list[str] = []

    def _next(self):
        if not self.answers:
            raise AssertionError("脚本答案用完了（可能问了预期之外的问题）")
        return self.answers.pop(0)

    def ask(self, message="", *, default=None, completions=None):
        self.seen.append(message)
        return self._next()

    def confirm(self, message, *, default=True):
        self.seen.append(message)
        return self._next()

    def choose(self, question, options, *, default=None):
        self.seen.append(question)
        return self._next()


def test_app_runs_a_task_end_to_end_offline(tmp_path):
    console = _console()
    settings = _settings()
    wf_holder: dict = {}

    def factory(s):
        wf = FakeWorkflow(CHUNKS)
        wf_holder["wf"] = wf
        return wf

    app = TuiApp(
        settings,
        console=console,
        workflow_factory=factory,
        auto_out=tmp_path / "sim.py",
    )
    app.hist_file = tmp_path / "history.jsonl"
    # 新建任务 -> 输入需求 -> 确认运行 -> 返回主菜单 -> 退出
    app.prompter = ScriptedPrompter(["1", "做个二维仿真", True, "m", "q"])
    assert app.run() == 0

    # 代码被 --out 写盘
    assert (tmp_path / "sim.py").read_text(encoding="utf-8") == "print(1)"
    # 历史也落了盘
    records = load_records(tmp_path / "history.jsonl")
    assert len(records) == 1
    assert records[0]["title"] == "做个二维仿真"
    assert records[0]["verified"] is True

    out = console.export_text()
    assert "三道关" in out and "最终代码" in out


def test_app_with_initial_query_short_circuits_menu(tmp_path):
    console = _console()
    app = TuiApp(
        _settings(),
        console=console,
        workflow_factory=lambda s: FakeWorkflow(CHUNKS),
        initial_query="直接跑这个需求",
        auto_out=tmp_path / "out.py",
    )
    app.hist_file = tmp_path / "history.jsonl"
    # 初始需求已在手：只需确认运行 + 退出
    app.prompter = ScriptedPrompter([True, "m", "q"])
    assert app.run() == 0
    assert (tmp_path / "out.py").read_text(encoding="utf-8") == "print(1)"


def test_app_blocks_run_without_api_key():
    console = _console()
    settings = Settings.from_env(openai_api_key="", kb_path=ROOT / "kb" / "jwave_kb_organized.md", verbose=False)
    app = TuiApp(settings, console=console)
    # 新建任务 -> 输入需求 -> 拒绝打开配置编辑器 -> 退出
    app.prompter = ScriptedPrompter(["1", "需求", False, "q"])
    app.run()
    assert "缺少 API Key" in console.export_text()


def test_app_history_view_and_clear(tmp_path):
    console = _console()
    hist = tmp_path / "history.jsonl"
    append_record(make_record(FAKE_RESULT, "历史任务", _settings(), elapsed=2.0), hist)

    app = TuiApp(_settings(), console=console)
    app.hist_file = hist
    app.prompter = ScriptedPrompter(["4", "1", False, "q"])   # 历史 -> 看第 1 条 -> 不另存 -> 返回
    app.show_history()
    out = console.export_text()
    assert "历史任务" in out
    assert "方案三 语义门" in out

    app.prompter = ScriptedPrompter(["c", True])              # 清空
    app.show_history()
    assert load_records(hist) == []


def test_cli_help_and_no_query_behaviour(capsys):
    from jwave_flow.cli import main

    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0

    # 非交互（stdin 不是 tty）+ 没有需求 -> 报错返回 2
    assert main(["--no-tui"]) == 2
    assert "请提供需求" in capsys.readouterr().err


def test_cli_help_mentions_tui(capsys):
    from jwave_flow.cli import _build_parser

    help_text = _build_parser().format_help()
    assert "--tui" in help_text and "--no-tui" in help_text
    assert "--json" in help_text


# --------------------------------------------------------------------------- #
# 知识库速览
# --------------------------------------------------------------------------- #
def test_kb_outline_filters_body_callouts():
    """知识库里用 `# ✅ 正确: …` 当正文，不能当成章节。"""
    text = (
        "# 标题\n"
        "### Medium 类 — 计算域定义\n"
        "# ✅ 正确: 4 个位置参数\n"
        "# ❌ 错误: 使用关键字参数会导致 TypeError\n"
        "### Sources 类 — 激励源\n"
    )
    sections, entries, total = panels.kb_outline(text)
    assert sections == ["标题"]
    assert entries == ["Medium 类 — 计算域定义", "Sources 类 — 激励源"]
    assert total == 3                       # ✅/❌ 那两行被剔除


def test_kb_overview_panel_on_real_and_missing_files(tmp_path):
    console = _console()
    console.print(panels.kb_overview_panel(ROOT / "kb" / "jwave_kb_organized.md"))
    text = console.export_text()
    assert "知识库" in text
    assert "Medium 类" in text

    console2 = _console()
    console2.print(panels.kb_overview_panel(tmp_path / "no-such.md"))
    assert "知识库不存在" in console2.export_text()


def test_config_self_check_panel_runs(tmp_path):
    console = _console()
    app = TuiApp(_settings(), console=console)
    app.validate_settings()
    out = console.export_text()
    assert "配置自检" in out
    assert "API Key" in out and "知识库" in out
