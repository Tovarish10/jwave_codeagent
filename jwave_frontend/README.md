# jwave studio

这是 `jwave_codeagent` 的本地网页前端。它通过
`SimulationWorkflow.stream()` 展示真实的 LangGraph 节点进度，并使用项目现有的
`run/history.jsonl` 保存任务记录。

## 启动

在 `jwave_codeagent` 仓库根目录下执行：

```bash
./jwave_frontend/start.sh
```

或者显式使用 `jw` 环境：

```bash
conda run -n jw python jwave_frontend/server.py
```

然后打开 <http://127.0.0.1:8765>。

运行前仍需按内核项目的说明配置仓库根目录下的 `.env`，至少提供
`OPENAI_API_KEY` 或 `DEEPSEEK_API_KEY`。API Key 只由 Python 内核读取，不会返回给
浏览器；浏览器只收到“是否已配置”的状态。

生成代码区域支持输入文件名并点击“另存为”，文件会由浏览器直接下载为
Python 文件，不经过服务器保存。

可通过环境变量修改监听地址和端口：

```bash
JWAVE_FRONTEND_HOST=0.0.0.0 JWAVE_FRONTEND_PORT=8765 ./jwave_frontend/start.sh
```
