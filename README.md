# jwave 仿真工作流 — Dify → LangChain/LangGraph

把 Dify 工作流应用 **「仿真」**（`dify_workflow/仿真.yml`）翻译成 **LangChain / LangGraph**
实现，可直接在本机运行。

流程保持不变：**自然语言需求 → 需求分析 → 检索知识库 → 提取参数 → 生成 jwave 代码
→ 反复「执行 / 纠错」直到跑通（≤10 轮）→ 输出最终代码**。

```
START → ① 需求分析 → ② 知识检索 → ③ 模板转换 → ④ 参数提取 → ④b 参数物理预检 ← 方案一
                                                              │
                                          ┌──── 不合格（可重试 ≤2）┘
                                          ▼
                                       回退 ④ ──────────────┐
                                                            │ 合格
                                                            ▼
                         ⑤ 代码生成 → ⑤b 静态规则检查 ← 方案二 ─问题─┐
                                            │ 合格                  │
                                            ▼                       │
                                      ⑥ 执行 ──── 运行报错 ────────┤
                                            │ 运行成功              │
                                            ▼                       │
                                    ⑥b 语义数值门 ← 方案三 ─ 未通过 ┤
                                            │ 通过                  │
                                            ▼                       ▼
                                       ⑧ 输出 → END          ⑦ 代码纠错 → 回到 ⑤b
```

> 粗看仍然是「生成→执行→纠错」的循环，但**退出条件从一层变成了三层**：
> 语法/运行通过 **≠** 语义通过。只有三道关都过，`verified` 才为 `True`。

节点/边与提示词的逐项对照见 **[docs/MAPPING.md](docs/MAPPING.md)**。

---

## 设计目标：可移植

| 关注点 | 做法 |
|--------|------|
| **模型** | 只依赖**通用 OpenAI 兼容接口**（`langchain-openai.ChatOpenAI` + `OPENAI_BASE_URL`）。默认 DeepSeek `deepseek-flash`，换 vLLM / Ollama / OpenAI / 通义 只改环境变量 |
| **路径** | 不硬编码绝对路径；根目录由 `__file__` 推导，其余全部走 `.env`，相对路径按项目根解析 |
| **检索** | 默认**纯 Python BM25**，零额外依赖、可离线；可切到 OpenAI embedding + 内存向量库 |
| **代码执行** | 可插拔执行器 `subprocess` / `jupyter` / `mcp` / `auto`，同一返回契约 |
| **结构化输出** | 支持则用 `with_structured_output`，不支持自动回退到文本解析 |

---

## 安装

```bash
conda activate jw            # 或在任何 Python >= 3.10 环境
pip install -r requirements.txt           # 编排层（langchain / langgraph / openai）
pip install -r requirements-runtime.txt   # jwave 仿真运行时 + 可选执行后端
```

## 配置

```bash
cp .env.example .env
# 至少填 OPENAI_API_KEY；国内直连 DeepSeek 时 BASE_URL 一般不用改
```

常用项（全部可选，见 `.env.example`）：

| 变量 | 默认 | 说明 |
|------|------|------|
| `OPENAI_API_KEY` | — | **必填**（也接受 `DEEPSEEK_API_KEY`） |
| `OPENAI_BASE_URL` | OpenAI 官方 | 任意 OpenAI 兼容端点 |
| `ANALYST_MODEL` | `deepseek-flash` | 需求分析 / 参数提取 |
| `CODER_MODEL` | `deepseek-flash` | 代码生成 / 代码纠错 |
| `KB_PATH` | `kb/jwave_kb_organized.md` | 知识库 markdown |
| `RETRIEVAL_BACKEND` | `bm25` | `bm25` \| `openai` |
| `RETRIEVAL_TOP_K` | `4` | 对应 Dify 的 `top_k` |
| `EXECUTOR_BACKEND` | `subprocess` | `subprocess` \| `jupyter` \| `mcp` \| `auto` |
| `EXEC_PYTHON` | 当前解释器 | 跑生成代码用的解释器 |
| `EXEC_TIMEOUT` | `600` | 单次执行超时（秒） |
| `LOOP_MAX_ITERATIONS` | `10` | 对应 Dify `loop_count` |

## 运行

### 交互式 CLI（推荐，可视化）

不带任何参数运行就会进入交互界面（也可以显式 `--tui`）：

```bash
python -m jwave_flow          # 无参数 -> 交互式界面
python -m jwave_flow --tui    # 显式进入
jwave-tui                     # 安装后等价的入口命令
```

```
  1  新建仿真任务（自然语言 → 代码 → 执行 → 校验）
  2  运行配置（模型 / 后端 / 三道关）
  3  知识库速览
  4  历史记录
  5  使用说明
  q  退出
```

任务运行时会**实时画出流水线**：每个节点（① 需求分析 … ⑧ 输出）的状态、用时、备注，
关卡计数与最新日志随 `LangGraph.stream()` 的节点事件逐条刷新；
跑完直接给出三道关结论、自检数据、stdout/stderr、带语法高亮的最终代码。

```
╭────────────────────────────── 流程 ──────────────────────────────╮
│ ✔ ① 需求分析 → ✔ ② 知识检索 → ✔ ③ 模板转换 → ✔ ④ 参数提取 →     │
│ ✔ ④b 参数物理预检 → ✔ ⑤ 代码生成 → ✔ ⑤b 静态检查 → ✔ ⑥ 执行 →  │
│ ✔ ⑥b 语义数值门 → · ⑦ 代码纠错 → ✔ ⑧ 输出                       │
│                                                                  │
│    ✔   ① 需求分析        0.83s  需求描述：二维时域声学仿真…      │
│ ┆  ✔   ② 知识检索        0.02s  命中 4 个片段                    │
│ ┆  ✔   ⑤b 静态检查 ×2     0.01s  无问题                         │
│ ┆  ✔   ⑥ 执行            3.21s  通过（subprocess 3.20s）         │
│ ████████████████████████████  9/11                               │
╰──────────────────────────────────────────────────────────────────╯
```

**在需求输入框里可以直接敲命令**：

| 输入 | 作用 |
|------|------|
| `:help` | 使用说明 |
| `:settings` | 打开配置编辑器（写入项目根的 `.env`，保留注释） |
| `:kb` | 知识库概览，可继续关键词检索 |
| `:history` | 历史记录列表 / 详情 / 清空 |
| `:preset` | 用内置示例需求（二维、三维、带探针、验证） |
| `@req.txt` | 从文件读取需求（适合长需求） |
| `:q` | 取消当前输入 |

「运行配置」里可直接改 API Key、模型、检索后端（`bm25`/`openai`）、执行后端
（`subprocess`/`jupyter`/`mcp`/`auto`）、最大迭代轮数与三道关开关，改完即写入 `.env` 并
**当场生效**；`v` 会做一次配置自检（Key / 端点 / 知识库 / 解释器 / 后端）。

每次跑完会自动往 `run/history.jsonl` 追加一条记录（需求、三道关结论、自检数据、
耗时、最终代码），可以在「历史记录」里回看或另存当时的代码。
`--tui "你的需求"` 会带着需求直接进入界面（仍会显示配置并确认后才运行）。

> 交互界面依赖 `rich` + `prompt_toolkit`（已在 `requirements.txt` / `pyproject.toml` 里）。
> 任一缺失时会打印安装提示，并提示改用下面的非交互模式。

### 非交互模式（脚本 / CI）

```bash
# 基本用法
python -m jwave_flow "生成一个 128x128 的二维时域声学仿真，声速 1500，5MHz 点源"

# 常用选项
python -m jwave_flow "..." --backend jupyter --top-k 6 --out sim.py
python -m jwave_flow "..." --json          # 打印完整状态
python -m jwave_flow --query-file req.txt --quiet
python -m jwave_flow --no-tui              # 强制不进入交互界面
python -m jwave_flow --check-api           # 只验证 API/网络连通性（排错用）
```

> 传入需求参数后默认走非交互路径；只有在**没有需求**且 stdin 是终端时才自动进入交互界面，
> 所以 `jwave_flow "..." | tee out.py` 这类管道用法不会被 TUI 打断。

### 代码里调用

```python
from jwave_flow import SimulationWorkflow, Settings

with SimulationWorkflow(Settings.from_env()) as wf:
    result = wf.invoke("做个二维时域仿真")
    print(result["text"])          # 最终代码
    print(result["iterations"], result["success"])
```

---

## 语义正确性校验（方案一 / 二 / 三）

原工作流（以及最初的翻译版本）把「没报错」当成了「正确」——实测跑通过一次，产出的代码
能跑、场也非零，但里面有两处**不报错却物理错误**的写法（对已是压力场的返回值又做了一次
`pressure_from_density`、把 `dt` 当成 `tone_burst` 的采样频率）。为补上这个缺口，加了
三道**确定性**关卡（都不依赖「用 LLM 判断 LLM」）：

| 关卡 | 时机 | 做什么 | 抓到什么 |
|------|------|--------|----------|
| **④b 参数物理预检**（方案一） | 生成代码**之前** | 纯算术：每波长网格点数 `c/(f·dx)`、Nyquist `1/dt>2f`（`dt` 按 jwave 的 `cfl·dx/c` 估算）、仿真时长是否够几个周期、PML 是否比域还厚、源是否落在 PML 里 | 参数层面的不合理；不合格**不进入代码生成**，回退「参数提取」重试（≤2 轮）。参数里没有 `dx` 时（该节点本来就不输出 dx），改为**反算合规上限** `dx ≤ c/(f·Nppw)` 注入代码生成提示词 |
| **⑤b 静态规则检查**（方案二） | 生成之后、运行之前 | 用标准库 `ast` 把知识库那张「禁止 API 黑名单」变成 8 条可执行规则（`tone_burst(dt,…)`、二次转换、浮点 `positions`、`Sources` 关键字参数、`jw.np.*`、`time_axis.t`、`FourierSeries.from_array`、`jw.show_field`…） | 已知的历史错误模式，**零 API 成本**，且能直接给出修法；有问题的代码一次都不会被执行 |
| **⑥b 语义数值门**（方案三） | 运行之后 | 要求生成代码打印一行 `__JWAVE_SELFCHECK__{...}` 自检结果，据此判定：有限性、`|p|max` 非零、量级在合理范围、形状存在、`f0` 与需求一致（防串参） | 「能跑但结果无意义」：全零场、`nan/inf`、数值发散、参数串味 |

失败原因（而非只有 `stderr`）会**原样回灌**给「代码纠错」节点。达到迭代上限仍未通过时，
输出会被显式标注 **⚠️ 未通过语义校验**，`--json` 里的 `verified` 字段为 `false`——
把"成功"这个词变得诚实。

```bash
# 单独关掉某一关（排查/对比用）
PARAM_CHECK=0  STATIC_CHECK=0  REQUIRE_SELFCHECK=0 python -m jwave_flow "..."
```

> 说明：这三道关都**超出**了原 Dify 工作流的能力（它同样只查 `stderr`），属于
> 「忠实翻译」之外的增强。想要完全对齐原行为，把上面三个开关置 0 即可。

---

## 关于失效的 `RUN_PYTHON_CODE` MCP 工具

原工作流用的 `RUN_PYTHON_CODE`（MCP 服务器 `python运行mcp`）已失效，本实现用
**可插拔执行器**顶替，并把「工具调用」+「代码执行 2」两个节点的返回契约
（`stdout / stderr / results / outputs / new_files / execution_time`）统一到
`ExecutionResult`：

| 后端 | 机制 | 依赖 | 备注 |
|------|------|------|------|
| `subprocess`（默认） | 一次性 `python <临时脚本>` | 无 | 最省事、最可移植；每次都是完整脚本，无需状态保持 |
| `jupyter` | 常驻 `ipykernel`（`jupyter_client`） | `ipykernel` | 有状态，最接近原 MCP 工具 |
| `mcp` | 启动 `python-mcp-server`，走 stdio 调用 `run_python_code` | `mcp`, `python-mcp-server` | 与原 Dify 配置**最接近**（该工具内部同样是常驻 kernel） |
| `auto` | 先试 `jupyter`，失败自动降级 `subprocess` | — | 不确定环境时用 |

> ⚠️ **安全提示**：生成出来的代码以当前用户权限执行，仅做了超时与独立工作目录隔离，
> **不是安全沙箱**。请不要把不可信输入喂给该工作流。

> ⚠️ **JAX 后端**：本机默认走 CUDA 会 **段错误**，执行器已默认注入
> `JAX_PLATFORMS=cpu`（可在 `Settings.exec_env` 覆盖）。

> 💡 **首次运行建议先热身**：循环的退出条件是「`stderr` 为空」，而 matplotlib
> 第一次构建字体缓存时会往 `stderr` 打一行提示，可能被误判为失败并多跑一轮纠错。
> 跑一次即可消除：
> ```bash
> python tools/warm_env.py
> ```
> （默认 `exec_env` 已含 `MPLBACKEND=Agg` 与可写的 `MPLCONFIGDIR`，就是为了这个。）

---

## 知识库

`kb/jwave_kb_organized.md`。**已按需修正**并在 `tools/fix_kb.py` 中固化，
原文件备份为 `kb/jwave_kb_organized.md.bak`：

```bash
python tools/fix_kb.py --check      # 查看会改什么
python tools/fix_kb.py --revert     # 一键还原为原始知识库
```

改动原因、逐条清单与验证结果见 **[kb/FIXES.md](kb/FIXES.md)**（共 24 处），完整 diff 见 `kb/CHANGES.diff`。
简言之：原知识库是按较旧的 jwave 写的，`jw.np.*`、`jw.show_field`、
`TimeHarmonicSource(...)`、`helmholtz_solver` 的源类型等写法在 **jwave 0.2.1** 下都不成立。
修正后两个「典型工作流」示例均已**实跑通过**。

---

## 真实试运行记录（DeepSeek）

用系统环境变量 `DEEPSEEK_API_KEY` + `OPENAI_BASE_URL=https://api.deepseek.com/v1` 实跑过一次：

```bash
export OPENAI_API_KEY="$DEEPSEEK_API_KEY"
export OPENAI_BASE_URL=https://api.deepseek.com/v1
export ANALYST_MODEL=deepseek-flash CODER_MODEL=deepseek-flash
python tools/warm_env.py          # 先热身，避免字体缓存污染 stderr
python -m jwave_flow "生成一个 64x64 的二维时域声学仿真：水中声速 1500 m/s，5 MHz 点源，仿真 20 微秒，最终输出压力场。"
```

结果：**5 轮收敛**（第 1 轮报错 → 4 次自我纠错 → 第 5 轮通过），耗时约 185s，
产出代码实跑得到 `(1001, 64, 64, 1)` 的有限压力场（`|p|max ≈ 5016`）。

该 endpoint（`https://api.deepseek.com/v1`）可用模型为 `deepseek-flash` 与 `deepseek-v4-pro`。
⚠️ `deepseek-flash` **已弃用**（服务端只做重定向），本项目默认模型已改为 `deepseek-flash`。

> ⚠️ 这次试运行也暴露了一个**本质限制**：「成功」的判定是 *stderr 为空*（与原 Dify 一致），
> **只保证能跑不报错，不保证物理正确**。当次产出的代码里就有两处不报错但语义不对的写法
> （对已是压力场的返回值又做了一次 `pressure_from_density`、把 `dt` 当成 `tone_burst` 的采样频率），
> 已据此在知识库里补了两条醒目说明（见 `kb/FIXES.md` 第 8、9 条）。

---

## 测试

```bash
python -m pytest tests -q
```

覆盖：提示词/YAML 保真度、图拓扑、知识库切分与检索、执行器契约、
以及**用 stub LLM 跑通整张图**（含「首轮报错 → 纠错 → 第二轮通过」与「达到上限放弃」两条路径）——
全部无需 API Key。

## 目录结构

```
jwave-dify-langchain/
├── dify_workflow/仿真.yml      # 原始 Dify 工作流（只读参考）
├── jwave_flow/
│   ├── config.py               # 环境变量配置
│   ├── prompts.py              # 从 YAML 逐字提取的提示词
│   ├── llm.py                  # OpenAI 兼容模型 + 结构化输出回退
│   ├── knowledge.py            # 知识库切分 + BM25/embedding 检索
│   ├── executor.py             # subprocess / jupyter / mcp 执行器
│   ├── state.py                # LangGraph 状态
│   ├── physics.py              # 方案一 参数物理预检
│   ├── static_check.py         # 方案二 AST 静态规则检查
│   ├── semantic.py             # 方案三 输出契约 + 数值门
│   ├── graph.py                # 工作流图（含循环）
│   ├── cli.py                  # python -m jwave_flow（TUI / 非交互两条路径）
│   ├── tui.py                  # 交互式界面：菜单 / 向导 / 实时流水线 / 配置编辑器
│   ├── panels.py               # Rich 渲染件（流程、关卡、报告、知识库、历史）
│   ├── errors.py               # 异常 -> 人话（网络/鉴权/模型名/限流归因）
│   └── history.py              # run/history.jsonl 读写
├── kb/                         # 知识库 + 备份 + 修改记录
├── tools/fix_kb.py             # 知识库修正工具（幂等 / 可回滚）
├── docs/MAPPING.md             # Dify ↔ LangGraph 映射表
└── tests/
```

## 排错：先分清「网络问题」和「生成代码的问题」

LLM 调用失败（例如 `OpenAIConnectionError: Connection error.`，根因多为
`httpcore.ConnectError: [Errno 104] Connection reset by peer`）与工作流本身无关，
**先单独验证连通性**：

```bash
python -m jwave_flow --check-api
```

```
探测 https://api.deepseek.com/v1
  模型: deepseek-flash
  API Key: 已配置
❌ 连通性测试失败（0.57s）
  OpenAIConnectionError: Connection error.

  这是网络层失败（连接被重置 / TLS 握手失败），不是生成代码的问题。
  · 先确认能不能直连 endpoint：curl -v $OPENAI_BASE_URL/models
  · 国内直连 DeepSeek 用 https://api.deepseek.com/v1；需要代理时先设好代理再启动
  · WSL 里常见的「Connection reset by peer」多为 MTU/代理问题：可在 Windows 侧开代理，或调小 WSL 的 MTU
  · httpx 会自动读取 HTTPS_PROXY / ALL_PROXY；确认它们对当前终端生效，或先 unset 掉错误的代理
```

交互界面里等价的操作是：`2 运行配置` → 按 `t`。

其他约定：

* 任何节点抛错都**不会**再以 traceback 收场。流程图会把出错的节点标成 ✖，
  下方给出归因（网络 / 鉴权 / 模型名 / 限流）与建议，然后回到主菜单；
  失败运行同样写入 `run/history.jsonl`（含 `error` / `error_hints`），便于回看。
* 非交互模式同类错误输出同样的文案并返回退出码 `2`，方便 CI 判断。
* 想看清真正的堆栈（开发用）：`JWAVE_DEBUG=1 python -m jwave_flow ...`。

`errors.py` 里的归类是纯字符串/异常链判断，不依赖网络，也方便你自己加规则。

## 已知限制

* 执行器不是安全沙箱（见上）。
* `bm25` 后端是词法检索，不含 Dify 的 `qwen3-rerank` 重排；需要重排请用 `openai` embedding 后端或自行换 vector store。
* 「需求分析」节点在原图中输出未被下游引用，此处忠实保留（见 `docs/MAPPING.md`）。
* 若生成的 jwave 代码长期无法自愈，多半是知识库与所装 jwave 版本仍有差异——用 `--json` 看 `stderr` / `trace` 定位。
* 交互界面里的「执行用时」是相邻节点事件的时间差，因此包含了该节点内的 LLM 调用耗时；
  它用于观察节奏，不是精确的 profiler。
* `rich` / `prompt_toolkit` 仅交互界面需要；两者缺失时非交互模式依然可用。
