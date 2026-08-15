# LLM 后端兼容（DeepSeek / OpenAI / Anthropic）

`src/llm.py` 提供统一的 LLM 后端抽象，agent 对话、`rag.py ask`、记忆汇总共用同一套接口。

## 两种后端

### 1. OpenAI 兼容端点（`LLM_PROVIDER=openai`，默认）

适用于 DeepSeek、OpenAI、任意 OpenAI 兼容中转，以及 Anthropic 官方的 OpenAI 兼容端点。

```env
LLM_PROVIDER=openai
LLM_API_KEY=            # 可选,优先于 OPENAI_API_KEY
OPENAI_BASE_URL=https://api.deepseek.com/v1   # 兼容完整 /chat/completions 路径(自动剥离)
LLM_MODEL=              # 可选,设置后启动不再询问模型名
```

### 2. Anthropic 原生（`LLM_PROVIDER=anthropic`）

使用官方 `anthropic` SDK（`/v1/messages`，流式 + 工具调用 + tool_result 均支持）。

```env
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_BASE_URL=     # 可选,走中转/代理时填写
ANTHROPIC_MAX_TOKENS=4096
LLM_MODEL=claude-...    # 建议设置,否则启动时询问
```

## 使用

- 启动时自动读取 `.env`；Key 缺失才交互询问。
- 会话中切换后端：`/provider openai` 或 `/provider anthropic`；`/provider` 查看当前后端。
- 切换模型：`/switchmodel <模型名>`。

## 说明

- Anthropic 后端的工具调用会归一化成与 OpenAI 一致的流式事件，agent 的工具闭环无需改动。
- `EMBEDDING_PROVIDER=api` 的 embedding 仍走 OpenAI 兼容接口（Anthropic 无 embedding API）。
- 部分本地模型（如 Ollama 的 `dscv2lite`）不支持工具调用：agent 检测到后会提示并自动降级为纯对话模式重试，不崩溃。
