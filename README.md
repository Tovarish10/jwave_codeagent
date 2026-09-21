# jwave 仿真工作流 — Dify → LangChain/LangGraph

把 Dify 工作流应用 **「仿真」**（`dify_workflow/仿真.yml`）翻译成 **LangChain / LangGraph**
实现，可直接在本机运行。

流程保持不变：**自然语言需求 → 需求分析 → 检索知识库 → 提取参数 → 生成 jwave 代码
→ 反复「执行 / 纠错」直到跑通（≤10 轮）→ 输出最终代码**。

```
START → ① 需求分析 → ② 知识检索 → ③ 模板转换 → ④ 参数提取 → ⑤ 代码生成 → ⑥ 执行
                                                    ▲                        │
                                                    │                  stderr 为空?
                              ⑦ 代码纠错 ←──── 否 ───┘                        │是
                                                                        ⑧ 输出 → END
```

节点/边与提示词的逐项对照见 **[docs/MAPPING.md](docs/MAPPING.md)**。

---

## 设计目标：可移植

| 关注点 | 做法 |
|--------|------|
| **模型** | 只依赖**通用 OpenAI 兼容接口**（`langchain-openai.ChatOpenAI` + `OPENAI_BASE_URL`）。默认 DeepSeek `deepseek-v4-flash`，换 vLLM / Ollama / OpenAI / 通义 只改环境变量 |
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
| `ANALYST_MODEL` | `deepseek-v4-flash` | 需求分析 / 参数提取 |
| `CODER_MODEL` | `deepseek-v4-flash` | 代码生成 / 代码纠错 |
| `KB_PATH` | `kb/jwave_kb_organized.md` | 知识库 markdown |
| `RETRIEVAL_BACKEND` | `bm25` | `bm25` \| `openai` |
| `RETRIEVAL_TOP_K` | `4` | 对应 Dify 的 `top_k` |
| `EXECUTOR_BACKEND` | `subprocess` | `subprocess` \| `jupyter` \| `mcp` \| `auto` |
| `EXEC_PYTHON` | 当前解释器 | 跑生成代码用的解释器 |
| `EXEC_TIMEOUT` | `600` | 单次执行超时（秒） |
| `LOOP_MAX_ITERATIONS` | `10` | 对应 Dify `loop_count` |

## 运行

```bash
# 基本用法
python -m jwave_flow "生成一个 128x128 的二维时域声学仿真，声速 1500，5MHz 点源"

# 常用选项
python -m jwave_flow "..." --backend jupyter --top-k 6 --out sim.py
python -m jwave_flow "..." --json          # 打印完整状态
python -m jwave_flow --query-file req.txt --quiet
```

代码里调用：

```python
from jwave_flow import SimulationWorkflow, Settings

with SimulationWorkflow(Settings.from_env()) as wf:
    result = wf.invoke("做个二维时域仿真")
    print(result["text"])          # 最终代码
    print(result["iterations"], result["success"])
```

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
export ANALYST_MODEL=deepseek-v4-flash CODER_MODEL=deepseek-v4-flash
python tools/warm_env.py          # 先热身，避免字体缓存污染 stderr
python -m jwave_flow "生成一个 64x64 的二维时域声学仿真：水中声速 1500 m/s，5 MHz 点源，仿真 20 微秒，最终输出压力场。"
```

结果：**5 轮收敛**（第 1 轮报错 → 4 次自我纠错 → 第 5 轮通过），耗时约 185s，
产出代码实跑得到 `(1001, 64, 64, 1)` 的有限压力场（`|p|max ≈ 5016`）。

该 endpoint（`https://api.deepseek.com/v1`）可用模型为 `deepseek-flash` 与 `deepseek-v4-pro`；
`deepseek-v4-flash` 会被服务端映射到 `deepseek-flash`，可直接用。

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
│   ├── graph.py                # 工作流图（含循环）
│   └── cli.py                  # python -m jwave_flow
├── kb/                         # 知识库 + 备份 + 修改记录
├── tools/fix_kb.py             # 知识库修正工具（幂等 / 可回滚）
├── docs/MAPPING.md             # Dify ↔ LangGraph 映射表
└── tests/
```

## 已知限制

* 执行器不是安全沙箱（见上）。
* `bm25` 后端是词法检索，不含 Dify 的 `qwen3-rerank` 重排；需要重排请用 `openai` embedding 后端或自行换 vector store。
* 「需求分析」节点在原图中输出未被下游引用，此处忠实保留（见 `docs/MAPPING.md`）。
* 若生成的 jwave 代码长期无法自愈，多半是知识库与所装 jwave 版本仍有差异——用 `--json` 看 `stderr` / `trace` 定位。
