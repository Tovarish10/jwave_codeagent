"""Command line entry point: ``python -m jwave_flow "你的需求"``."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import Settings
from .graph import SimulationWorkflow


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="jwave_flow",
        description='Dify 「仿真」工作流的 LangChain/LangGraph 实现',
    )
    p.add_argument("query", nargs="?", help="自然语言仿真需求")
    p.add_argument("--query-file", type=Path, help="从文件读取需求（与 query 二选一）")
    p.add_argument("--kb", type=Path, help="知识库 markdown 路径")
    p.add_argument("--top-k", type=int, help="知识检索命中数量（默认 4）")
    p.add_argument(
        "--retrieval", choices=["bm25", "openai"], help="检索后端（默认 bm25）"
    )
    p.add_argument(
        "--backend",
        choices=["subprocess", "jupyter", "mcp", "auto"],
        help="代码执行后端（默认 subprocess）",
    )
    p.add_argument("--max-iterations", type=int, help="执行/纠错最大轮数（默认 10）")
    p.add_argument("--model", help="同时覆盖 analyst/coder 模型名")
    p.add_argument("--out", type=Path, help="把最终代码写到该文件")
    p.add_argument("--json", action="store_true", help="以 JSON 打印完整最终状态")
    p.add_argument("--quiet", action="store_true", help="不打印过程日志")
    p.add_argument("--tui", action="store_true", help="强制使用交互式界面（可视化流水线）")
    p.add_argument("--no-tui", action="store_true", help="禁用交互式界面（无需求时直接报错）")
    return p


def _overrides_from_args(args) -> dict:
    overrides: dict = {}
    if args.kb:
        overrides["kb_path"] = args.kb
    if args.top_k is not None:
        overrides["top_k"] = args.top_k
    if args.retrieval:
        overrides["retrieval_backend"] = args.retrieval
    if args.backend:
        overrides["executor_backend"] = args.backend
    if args.max_iterations is not None:
        overrides["max_iterations"] = args.max_iterations
    if args.model:
        overrides["analyst_model"] = args.model
        overrides["coder_model"] = args.model
    if args.quiet:
        overrides["verbose"] = False
    return overrides


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    query = args.query
    if args.query_file:
        query = Path(args.query_file).read_text(encoding="utf-8").strip()

    # 没有需求时（或显式 --tui）进入交互式界面；有 --json 说明是脚本场景，不自动进 TUI
    wants_tui = args.tui or (
        not query and not args.no_tui and not args.json and sys.stdin is not None and sys.stdin.isatty()
    )
    if wants_tui:
        from .tui import RICH_AVAILABLE, run_tui

        if not RICH_AVAILABLE:
            print(
                "交互式界面需要 rich：pip install rich prompt_toolkit\n"
                "或改用非交互模式：jwave_flow \"你的需求\"",
                file=sys.stderr,
            )
            return 2
        return run_tui(
            _overrides_from_args(args),
            initial_query=(query or "").strip(),
            auto_out=args.out,
        )

    if not query:
        print("错误：请提供需求（位置参数 query 或 --query-file）", file=sys.stderr)
        return 2

    overrides = _overrides_from_args(args)
    settings = Settings.from_env(**overrides)
    print(f"知识库: {settings.resolved_kb_path()}", file=sys.stderr)
    print(
        f"模型: analyst={settings.analyst_model} coder={settings.coder_model} "
        f"base_url={settings.openai_base_url or '(openai default)'}",
        file=sys.stderr,
    )
    print(f"执行后端: {settings.executor_backend} | 检索: {settings.retrieval_backend}", file=sys.stderr)

    try:
        with SimulationWorkflow(settings) as wf:
            result = wf.invoke(query)
    except KeyboardInterrupt:
        print("已中断", file=sys.stderr)
        return 130
    except (RuntimeError, ValueError, FileNotFoundError) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({k: v for k, v in result.items() if k != "kb_docs"}, ensure_ascii=False, indent=2, default=str))
    else:
        print("\n" + "=" * 60)
        print("最终代码：\n")
        print(result.get("text", ""))
        print("=" * 60)
        print(
            f"迭代 {result.get('iterations')} 次 | 成功: {result.get('success')} | "
            f"耗时 {result.get('elapsed', 0):.1f}s",
            file=sys.stderr,
        )
        # 方案一/二/三：把三道关卡的结论一并交代清楚
        for line in result.get("param_warnings") or []:
            print(f"  {line}", file=sys.stderr)
        if result.get("param_issues"):
            print(
                f"  ❌ 参数预检未通过（{len(result['param_issues'])} 项）",
                file=sys.stderr,
            )
        if result.get("static_issues"):
            print(f"  ❌ 静态检查仍有 {len(result['static_issues'])} 处问题", file=sys.stderr)
        for line in result.get("semantic_issues") or []:
            print(f"  ❌ 语义门: {line}", file=sys.stderr)
        print(
            "  ✅ 语义校验通过" if result.get("verified") else "  ⚠️ 未通过语义校验，请人工确认",
            file=sys.stderr,
        )

    if args.out:
        Path(args.out).write_text(result.get("text", ""), encoding="utf-8")
        print(f"已写入 {args.out}", file=sys.stderr)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
