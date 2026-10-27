# jwave 仿真工作流

一个面向 jwave 声学仿真的本地 AI 工作台，包含：

- **LangChain / LangGraph 内核**：将自然语言需求转换为可执行的 jwave Python 代码；
- **确定性质量检查**：参数物理预检、AST 静态检查、运行后语义数值门；
- **命令行与 TUI**：适合脚本化调用、调试和查看完整工作流状态；
- **jwave studio 网页前端**：通过浏览器提交任务，实时查看节点进度、验证结果、
  stdout、生成代码和历史任务。

典型流程是：

自然语言需求 → 需求分析 → 知识库检索 → 参数提取 → 物理预检 →
代码生成 → 静态检查 → 执行仿真 → 语义校验 → 代码纠错 → 输出结果。

```
① 需求分析 → ② 知识检索 → ③ 模板转换 → ④ 参数提取 → 参数物理预检 → ⑤ 代码生成
                                                                        ↓
       ⑧ 输出 ←── ⑥c 需求完成度评审 ←── 语义数值门 ←── ⑥ 执行 ←── 静态规则检查
                         │                         ↑                    │
                         └─────────────────── ⑤ 代码生成 ←───────────────┘   （评审 ≤ 3 轮）
```

网页前端和 Python 工作流共用同一个内核、`.env` 配置、知识库和
`run/history.jsonl` 历史记录；前端不是另一套仿真逻辑。


## 安装

```bash
conda activate jw                          # 请替换为本机的任意 Python >= 3.10 环境
pip install -r requirements.txt            # 编排层与 CLI/TUI
pip install -r requirements-runtime.txt    # jwave、JAX、matplotlib 等运行时
```

也可以使用 `pyproject.toml` 的可选依赖：

```bash
pip install -e ".[runtime]"                # 安装为本地包并包含仿真运行时
pip install -e ".[runtime,dev]"             # 额外安装测试依赖
```

网页前端使用 Python 标准库 HTTP server，不需要额外的 Node.js 构建步骤。

## 配置

配置全部来自环境变量，`.env` 可选（其值不会覆盖已存在的环境变量）：

```bash
cp .env.example .env
```

至少提供 API Key 与端点。只设 `DEEPSEEK_API_KEY` 时会自动指向
`https://api.deepseek.com/v1`：

```bash
export DEEPSEEK_API_KEY=sk-...
# 或者使用其它 OpenAI 兼容服务
export OPENAI_API_KEY=sk-...
export OPENAI_BASE_URL=https://api.deepseek.com/v1
```

常用变量（完整列表见 `.env.example`）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` | — | 必填，二者取其一 |
| `OPENAI_BASE_URL` | OpenAI 官方 | 任意 OpenAI 兼容端点 |
| `ANALYST_MODEL` | `deepseek-flash` | 需求分析 / 参数提取 |
| `CODER_MODEL` | `deepseek-flash` | 代码生成 / 代码纠错 |
| `KB_PATH` | `kb/jwave_kb_organized.md` | 知识库 markdown |
| `RETRIEVAL_BACKEND` | `bm25` | `bm25`（离线）/ `openai`（embedding 向量检索） |
| `RETRIEVAL_TOP_K` | `4` | 检索命中数 |
| `EXECUTOR_BACKEND` | `subprocess` | `subprocess` / `jupyter` / `mcp` / `auto` |
| `EXEC_PYTHON` | 当前解释器 | 执行生成代码的解释器 |
| `EXEC_TIMEOUT` | `600` | 单次执行超时（秒） |
| `LOOP_MAX_ITERATIONS` | `10` | 执行 / 纠错最大轮数 |
| `COMPLETION_MAX_ROUNDS` | `3` | 需求完成度评审最大轮数（代码中硬上限为 3） |

## 使用

### 命令行

```bash
python -m jwave_flow "生成一个 128x128 的二维时域声学仿真，声速 1500，5MHz 点源"
jwave-flow "..."            # 等价的入口命令
```

| 选项 | 说明 |
|------|------|
| `--out FILE` | 把最终代码写入文件 |
| `--json` | 输出完整状态（`verified` / `semantic_issues` / `stdout` / `trace`） |
| `--query-file FILE` | 从文件读取需求 |
| `--kb FILE` `--top-k N` `--retrieval {bm25,openai}` | 覆盖检索配置 |
| `--backend {subprocess,jupyter,mcp,auto}` | 覆盖执行后端 |
| `--model NAME` | 同时覆盖 analyst / coder 模型 |
| `--max-iterations N` | 循环上限 |
| `--quiet` | 不打印过程日志 |
| `--check-api` | 只发一个最小请求，验证 API 与网络可达 |
| `--tui` / `--no-tui` | 强制进入 / 禁用交互界面 |

### 交互式界面

不带需求参数、且 stdin 是终端时自动进入；也可显式启动：

```bash
python -m jwave_flow --tui
```

菜单为：新建任务 / 运行配置 / 知识库速览 / 历史记录 / 使用说明。
运行中实时刷新各节点状态、关卡计数与日志，结束后给出四道关结论、自检数据与最终代码。

需求输入框支持：`:help`、`:settings`（配置编辑器，写回 `.env`）、`:kb`、`:history`、
`:preset`（内置示例需求）、`@file.txt`（从文件读取需求）。
每次运行追加一条记录到 `run/history.jsonl`。

交互界面依赖 `rich` 与 `prompt_toolkit`；两者缺失时非交互模式仍可正常使用。

### 网页前端：jwave studio

前端位于 [`jwave_frontend/`](./jwave_frontend/)，用于本地浏览器操作工作流。
它通过 `SimulationWorkflow.stream()` 接收每个节点的进度更新，并以 NDJSON 流式
发送到浏览器，因此执行较慢的仿真也能实时显示状态。

在仓库根目录启动：

```bash
./jwave_frontend/start.sh
```

脚本默认使用 conda 环境 `jw`。如果当前环境名称不同，可以直接指定解释器：

```bash
python jwave_frontend/server.py
```

然后打开 <http://127.0.0.1:8765>。启动前必须完成本节的 `.env` 配置；API Key
只在 Python 服务端读取，不会发送到浏览器。监听地址和端口可通过环境变量覆盖：

```bash
JWAVE_FRONTEND_HOST=0.0.0.0 \
JWAVE_FRONTEND_PORT=8766 \
./jwave_frontend/start.sh
```

前端提供的主要功能：

| 功能 | 说明 |
|------|------|
| 实时进度 | 展示需求分析、检索、生成、执行、校验和纠错节点 |
| 四道关卡 | 显示参数预检、AST 检查、语义数值门、需求完成度评审的状态和原因 |
| 仿真输出 | 展示 stdout、stderr、自检数据和执行产物路径 |
| 代码下载 | 在浏览器中复制或另存为 `.py`，不会由服务器写入用户指定文件 |
| 历史任务 | 读取主项目的 `run/history.jsonl` |

前端 API 仅面向本机使用场景设计，当前没有用户认证，也不是生产部署方案。
不要将它直接暴露到不可信网络；若绑定 `0.0.0.0`，应在外层增加访问控制和反向
代理。生成代码仍以当前用户权限执行，执行器不是安全沙箱。

### 代码里调用

```python
from jwave_flow import SimulationWorkflow, Settings

with SimulationWorkflow(Settings.from_env()) as wf:
    result = wf.invoke("做个二维时域仿真")
    print(result["text"])       # 最终代码
    print(result["verified"])   # 是否通过语义校验
```

## 语义校验

「执行不报错」不等于「结果正确」，因此流水线在生成与运行前后加了三道确定性检查，
并在语义门之后增加需求完成度评审；
全部通过时 `result["verified"]` 才为 `True`，否则输出会标注「未通过语义校验」，
且失败原因会回灌给「代码纠错」节点。

| 关卡 | 时机 | 检查内容 |
|------|------|----------|
| 参数物理预检 | 生成代码之前 | 每波长网格点数、Nyquist 采样、仿真时长、PML 厚度、源位置。不合格则不进入代码生成，回退重试参数提取（≤2 轮）；参数中没有 `dx` 时反算合规上限并注入提示词 |
| 静态规则检查 | 运行之前 | 8 条 AST 规则拦截已知的错误用法：`tone_burst(dt,…)`、对压力场的二次转换、浮点 `positions`、`Sources` 关键字参数、`signals`/`positions` 传 list 等。命中的代码一次都不会被执行 |
| 语义数值门 | 运行之后 | 要求代码输出用户可读结果和 `__JWAVE_SELFCHECK__{...}` 自检行，校验有限性、`|p|max` 非零与量级、形状、频率是否与需求一致 |
| 需求完成度评审 | 语义数值门之后 | 将用户问题、需求分析和程序实际输出发送给 LLM，以结构化 JSON 判断需求是否完成；不通过时把意见回传给代码生成，最多评审 3 轮，仍不通过则在最终代码前加入未完成标记 |

自检行是工作流解析用的机器输出，不是仿真结果，不能作为唯一 stdout。
生成代码还必须打印与需求对应的数值结果；用户要求二维场、快照或可视化时，
必须使用 matplotlib 的 `Agg` 后端将图片保存到执行器当前工作目录的 `outputs/`，
并打印生成的文件路径。执行器会在 `new_files` 和 `outputs` 字段中返回这些产物。

```bash
# 单独关闭某一道（排查时用）
PARAM_CHECK=0 STATIC_CHECK=0 REQUIRE_SELFCHECK=0 python -m jwave_flow "..."
```

## 代码执行后端


| 后端 | 机制 | 依赖 |
|------|------|------|
| `subprocess`（默认） | 一次性执行完整脚本 | 无 |
| `jupyter` | 常驻 `ipykernel` | `ipykernel` |
| `mcp` | 启动 `python-mcp-server` 并走 stdio 调用 | `mcp`、`python-mcp-server` |
| `auto` | 先试 `jupyter`，失败降级 `subprocess` | — |

生成的代码以当前用户权限运行，仅有超时与独立工作目录隔离，**不是安全沙箱**。
执行器默认注入 `JAX_PLATFORMS=cpu`与 `MPLCONFIGDIR`
（否则 matplotlib 字体缓存会写 stderr，被循环误判为失败）。首次运行可先执行
`python tools/warm_env.py` 完成预热。

生成代码如果需要向用户交付数值结果或图片，必须同时：

1. 用 `print` 输出与需求对应的数值结果；
2. 保留 `__JWAVE_SELFCHECK__{...}` 机器自检行；
3. 使用 matplotlib 的 `Agg` 后端，并将图片保存到执行工作目录的 `outputs/`；
4. 打印保存后的图片路径。

前端会把这些 stdout 和产物路径显示在运行结果中；命令行使用 `--json` 时也可
从 `stdout`、`outputs`、`new_files` 字段读取。

## 知识库

知识库为 `kb/jwave_kb_organized.md`，原始文件备份在 `kb/jwave_kb_organized.md.bak`，
修改清单见 `kb/FIXES.md`。

```bash
python tools/fix_kb.py            # 应用修正（幂等）
python tools/fix_kb.py --check    # 只报告
python tools/fix_kb.py --revert   # 回滚到原始知识库
```

## 目录结构

```
jwave_codeagent/
├── jwave_flow/
│   ├── config.py               # 环境变量配置与端点解析
│   ├── prompts.py              # 从 YAML 逐字提取的提示词
│   ├── llm.py                  # OpenAI 兼容模型 + 结构化输出回退
│   ├── knowledge.py            # 知识库切分 + BM25 / embedding 检索
│   ├── executor.py             # subprocess / jupyter / mcp 执行器
│   ├── physics.py              # 参数物理预检
│   ├── static_check.py         # AST 静态规则检查
│   ├── semantic.py             # 输出契约与数值门
│   ├── state.py / graph.py     # LangGraph 状态与工作流图
│   ├── cli.py                  # 命令行入口
│   ├── tui.py / panels.py      # 交互式界面与渲染
│   ├── errors.py               # 异常归因（网络 / 鉴权 / 模型名 / 限流）
│   └── history.py              # run/history.jsonl 读写
├── kb/                         # 知识库、备份与修改记录
├── tools/                      # fix_kb.py / warm_env.py
├── jwave_frontend/             # jwave studio 本地网页前端
│   ├── server.py               # 静态文件服务与 /api/run 流式接口
│   ├── index.html              # 页面结构
│   ├── app.js / styles.css     # 浏览器交互与样式
│   ├── start.sh                # conda jw 环境启动脚本
│   └── README.md               # 前端单独说明
├── docs/MAPPING.md             # Dify ↔ LangGraph 映射表
└── tests/
```

## 测试

```bash
python -m pytest tests -q
```

覆盖提示词与 YAML 的逐字保真、图拓扑、知识库检索、执行器契约、静态与语义规则，
以及用 stub LLM 和本地 mock OpenAI 服务跑通整张图；不需要 API Key。

前端的手工验证：

```bash
./jwave_frontend/start.sh
# 浏览器打开 http://127.0.0.1:8765，提交一个示例需求
```

前端启动后可检查 `/api/config` 和 `/api/history` 是否返回 JSON；提交任务时
`/api/run` 会返回逐行 JSON 事件，最后发送 `complete` 或 `error` 事件。

## 排错

模型调用失败与工作流本身无关时，先单独验证连通性：

```bash
python -m jwave_flow --check-api
```

它会先检查 API Key 与端点是否属于同一服务商（例如 `DEEPSEEK_API_KEY` 配了 OpenAI 地址，
会直接指出而不是报成网络问题），再发一个最小请求。交互界面里等价操作是
「运行配置」→ 按 `t`。

* 节点异常不会以 traceback 收场：流程图会标出出错的节点并给出归因与建议；
  非交互模式输出同样的文案并返回退出码 `2`。
* 失败的运行同样写入 `run/history.jsonl`（含 `error` / `error_hints`）。
* 需要原始堆栈时用 `JWAVE_DEBUG=1 python -m jwave_flow ...`。

## 已知限制

* 执行器不是安全沙箱，请勿将不可信输入交给该工作流。
* `bm25` 是词法检索，不含 Dify 的 `qwen3-rerank` 重排；需要重排可用 `openai` embedding 后端或自行替换 vector store。
* 若生成的代码长期无法自愈，多半是知识库与所装 jwave 版本仍有差异，可用 `--json` 查看 `stderr` 与 `trace`。
* 交互界面显示的「执行用时」是相邻节点事件的时间差，包含该节点内的 LLM 调用耗时，仅供观察节奏。
