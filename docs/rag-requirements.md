# RAG 工具需求文档（v0.1）

## 1. 背景

现有项目是一个基于 DeepSeek API（OpenAI 兼容协议）的 CLI agent（`src/main.py`），支持：

- skills 工具：扫描 `~/.bettercode/skills`，注册为 `allow_<skill_name>` 工具；
- 自定义函数工具：从项目根目录 `default.function.json` 读取（`src/skill.py` 的 `load_default_functions()`），注册为普通 function calling 工具。

目标：让 agent 具备**基于本地知识库的检索增强生成（RAG）**能力。RAG 不是一个独立应用，而是 agent 的一个 function calling 工具：模型判断需要时调用检索工具，拿到相关片段后由 DeepSeek 生成最终回答。

## 2. 设计原则

- **RAG 即工具**：检索能力以 `knowledge_search` 函数形式注册进 `default.function.json`，agent 按需调用；不单独做 Web 服务或微服务。
- **不用 Docker**：PostgreSQL 17 + pgvector 用 Homebrew 本机安装。
- **DeepSeek 无 embedding API**：DeepSeek 只提供 chat/reasoner，没有向量接口，所以向量化必须用其他来源。默认采用本地 embedding 模型（fastembed + `BAAI/bge-small-zh-v1.5`，512 维），不依赖 OpenAI/DeepSeek key，不引入 torch 重依赖；同时抽象 `Embedder` 接口，后续可切换到任意 OpenAI 兼容的 embedding API（如硅基流动、阿里 DashScope）。
- **轻依赖**：RAG 只新增 `psycopg`、`pgvector`、`fastembed`，不引入 LangChain 等重框架。

## 3. 功能需求

### 3.1 知识库入库（CLI，`src/rag.py`）

提供命令行入口：

```bash
python src/rag.py ingest <文件或目录>    # 入库：切分 → 向量化 → 写入 pgvector
python src/rag.py ask "问题"             # 调试用：直接检索 + DeepSeek 生成回答
python src/rag.py stats                  # 查看知识库统计（文档数、chunk 数）
python src/rag.py clear                  # 清空知识库（需二次确认）
```

入库细节：

- 支持 `.md` / `.txt` 文本；目录递归扫描。
- 切分策略：按段落/句子切分，chunk 目标长度与重叠可配置（默认约 400 字，重叠 50 字），保留 `source`（文件路径）和 `chunk_index` 元数据。
- 已入库的同一 `source` 重新 ingest 时先删旧再写新（增量更新）。

### 3.2 检索工具（agent 集成）

在 `default.function.json` 的 `funcs` 中注册：

```json
{
  "funcs": {
    "knowledge_search": {
      "type": "function",
      "function": {
        "name": "knowledge_search",
        "description": "在本地知识库中做语义检索，返回与问题最相关的文本片段，用于回答用户问题时补充背景知识",
        "parameters": {
          "type": "object",
          "properties": {
            "query": { "type": "string", "description": "要检索的问题或关键词" },
            "top_k": { "type": "integer", "description": "返回片段数，默认 5" }
          },
          "required": ["query"]
        }
      }
    }
  }
}
```

`src/main.py` 处理工具调用：执行 `src/rag.py` 的 `search(query, top_k)`，把结果（JSON 数组：`content`、`source`、`chunk_index`、`similarity`）作为 `role=tool` 消息回传，再发起一次补全让模型基于片段生成最终回答。

### 3.3 数据模型（PostgreSQL + pgvector）

```sql
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS documents (
  id          BIGSERIAL PRIMARY KEY,
  content     TEXT NOT NULL,
  source      TEXT NOT NULL DEFAULT '',
  chunk_index INT  NOT NULL DEFAULT 0,
  embedding   vector(512) NOT NULL,          -- 与 embedding 模型维度一致
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS documents_hnsw_idx
  ON documents USING hnsw (embedding vector_cosine_ops);
```

### 3.4 配置（`.env` 追加）

```env
DATABASE_URL=postgresql://<user>@localhost:5432/rag_kb
EMBEDDING_PROVIDER=local            # local | api
EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
VECTOR_DIM=512
```

数据库 `rag_kb` 由代码启动时自动创建（连到默认库后 `CREATE DATABASE`）。

## 4. 非功能需求

- 不引入 Docker；不引入 torch；总新增依赖控制在 3 个以内。
- 失败降级：数据库未启动 / embedding 模型不可用时，`knowledge_search` 返回明确错误信息，不让 agent 崩溃。
- 检索性能：小数据量（万级 chunk 内）单次检索 < 100ms（依赖 HNSW 索引）。
- 可扩展：新函数继续往 `default.function.json` 的 `funcs` 里加，`main.py` 只需补对应的执行分支。

## 5. 验收标准

1. `python src/rag.py ingest docs/` 后，`stats` 显示的 chunk 数与文件内容一致。
2. `python src/rag.py ask "xxx"` 能引用知识库内容作答，并标注引用来源。
3. 在 agent 对话中提问知识库相关问题时，模型能自动触发 `knowledge_search`，且最终回答基于检索片段（可抽查回答与片段的相关性）。
4. 数据库或模型不可用时，agent 不崩溃，错误信息可读。

## 6. 里程碑

| 阶段 | 内容 | 依赖 |
| --- | --- | --- |
| M1 | PostgreSQL 17 + pgvector 本机就绪，建库建表 | 无 |
| M2 | `src/rag.py`：embedding 抽象 + ingest 入库 | M1 |
| M3 | `knowledge_search` 接入 agent，工具调用闭环 | M2 + main.py 工具调用修复 |
| M4 | 效果调优：chunk 大小、top_k、检索阈值、system prompt | M3 |

## 7. 已知问题与决策记录

### 7.1 `src/main.py` 现有工具调用闭环不完整（M3 必须处理）

当前 `main.py` 收到 `tool_calls` 后会执行工具并把结果发给模型，但存在三个问题：

1. 工具执行后发起的补全（`role=tool`）**结果被丢弃**，用户看不到最终回答；
2. 回传消息里缺少 assistant 的 `tool_calls` 上下文（OpenAI/DeepSeek 协议要求携带）；
3. 工具参数用的是 `file_type`（JSON 里定义），但 `run_func` 执行分支读的是 `file_type` 变体（实际是 `filetype`，见 `default.function.json`），一旦模型真的调用 `run_func` 会 KeyError。

实现时需重写工具调用处理：收集完整 arguments → 执行 → 携带正确上下文回传 → 流式展示最终回答。

### 7.2 embedding 选型

默认 `fastembed` + `BAAI/bge-small-zh-v1.5`（512 维，约 100MB，中文效果好、首次运行自动下载模型）。`Embedder` 抽象预留 API 模式（`EMBEDDING_PROVIDER=api` 时走 OpenAI 兼容 `/embeddings` 接口）。

### 7.3 待确认

- 知识库目录默认放哪里？（建议 `~/.bettercode/knowledge/`，与 skills 一致，也可用项目内 `knowledge/`）
- 是否需要支持 PDF / URL 抓取？（v0.1 不做，后续再加）

## 8. 实现补充记录（2026-08-11）

- **网络适配**：huggingface.co 直连被重置，`.env` 已加 `HF_ENDPOINT=https://hf-mirror.com` 与 `HF_HUB_DISABLE_XET=1`（Xet CDN 401，禁用后走普通 HTTP 镜像）。若网络环境变化可删除。
- **API 地址兼容**：本机 `.env` 的 `OPENAI_BASE_URL` 存的是完整接口路径（`.../v1/chat/completions`），OpenAI SDK 会自动再拼一次导致 404。`rag.py` 的 `chat_client()` 会自动剥离尾部 `/chat/completions`；`OPENAI_*` 值未改动。
- **聊天模型**：`rag.py ask` 使用 `RAG_CHAT_MODEL`（默认 `deepseek-chat`），可在 `.env` 覆盖。
- **run_func 修正**：python 分支调用方式由 `func(*args)(args)`（双调用，明显 bug）改为 `func(**args)`；`filetype` 参数键名与 `default.function.json` 对齐。
- **skill 工具定位修复**：`allow_<skill>` 结果改为按 `~/.bettercode/skills/<名称>/SKILL.md` 定位（原实现把 skill 名称当路径传入，实际会报错）。
- **测试数据**：`/tmp/rag_demo`（3 个 md），可用 `python src/rag.py clear` 清空后删除。
