# RAG 实现 prompt（可直接粘贴给编码 agent）

> 使用方式：把下面整段内容发给编码 agent（Codex / Claude Code 等）。需求细节见同目录 `rag-requirements.md`，代码改动以本 prompt 为准。

---

请为我的项目实现一个 RAG 工具并接入现有 agent。项目根目录：`/Users/daniel/Documents/Projects/ClaudeCode`。先完整阅读 `docs/rag-requirements.md` 和以下文件再动手：`src/main.py`、`src/skill.py`、`default.function.json`、`.env`（只读，不要改动其中的 key 值）。

## 项目背景

- Python 3.12 项目，虚拟环境 `.venv`（使用 `/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python`）。
- `src/main.py` 是基于 DeepSeek API（OpenAI 兼容）的 CLI agent，支持 function calling；`src/skill.py` 负责加载 skills 和 `default.function.json` 的函数工具定义（`load_default_functions()` 已实现）。
- 本机已用 Homebrew 安装 PostgreSQL 17 + pgvector 0.8.0（**不要用 Docker**）。
- DeepSeek API 没有 embedding 接口，向量化必须用本地模型，默认 `fastembed` + `BAAI/bge-small-zh-v1.5`（512 维）。禁止引入 torch / LangChain 等重依赖。

## 任务清单

1. **`src/rag.py`（新建）**
   - 启动时确保数据库存在：连默认库 → `CREATE DATABASE IF NOT EXISTS rag_kb`（PostgreSQL 没有 IF NOT EXISTS 时先查 `pg_database`）→ 建 `documents` 表 + HNSW 索引（表结构见需求文档 3.3，维度取 `VECTOR_DIM`）。
   - `Embedder` 抽象：`LocalEmbedder`（fastembed，默认）与 `ApiEmbedder`（OpenAI 兼容 `/embeddings`，`EMBEDDING_PROVIDER=api` 时启用，仅留接口）。
   - 切分函数：按段落/句切分，`CHUNK_SIZE` 默认 400 字、`CHUNK_OVERLAP` 默认 50 字，保留 `source` + `chunk_index`。
   - `ingest(path)`：支持文件或目录（递归 `.md`/`.txt`），同一 `source` 先删旧再写新；进度打印（rich）。
   - `search(query, top_k=5)`：query 向量化 → `ORDER BY embedding <=> %s::vector LIMIT top_k`，返回 `[{content, source, chunk_index, similarity}]`，`similarity = 1 - distance`。
   - `stats()` / `clear()`（clear 需二次确认）。
   - CLI：`python src/rag.py ingest <path>` / `ask "<问题>"` / `stats` / `clear`；`ask` 用 `.env` 里的 DeepSeek 配置生成回答并标注引用来源。

2. **`default.function.json`**：在 `funcs` 中新增 `knowledge_search`（定义见需求文档 3.2），保留现有 `run_func` 不动。

3. **`src/main.py`**：修复并实现工具调用闭环
   - 现有 `load_skills()` 已合并 `load_default_functions()`，无需再改加载逻辑。
   - 重写 tool_calls 处理（现有实现有 bug，见需求文档 7.1）：
     - 流式收集完整 arguments（按 `tool_call.id` 聚合）；
     - `finish_reason == "tool_calls"` 后逐个执行：`knowledge_search` → 调用 `src/rag.py` 的 `search`；`run_func` 与 skills 保持现有行为（但修正参数键名 bug：JSON 定义的是 `filetype`）；
     - 回传消息必须带 assistant 的 `tool_calls` 上下文 + `role=tool` 结果，再发起一次补全，**把最终回答流式展示给用户**（现有代码丢弃了这次响应）；
     - 工具执行异常要捕获并作为 `role=tool` 错误信息回传，不能崩溃。

4. **依赖与配置**
   - `requirements.txt` 增加 `psycopg[binary]`、`pgvector`、`fastembed`。
   - `.env` 增加 `DATABASE_URL`、`EMBEDDING_PROVIDER`、`EMBEDDING_MODEL`、`VECTOR_DIM`（不要动现有 `OPENAI_*` 的值）。

## 硬性约束

- 不用 Docker；不引入 torch；不引入 LangChain。
- 不修改 `src/skill.py` 的 skills 加载逻辑，不改变 `~/.bettercode/skills` 的机制。
- 不破坏现有 `/switchmodel`、`/skills` 等命令。
- 代码用中文注释，风格与现有文件一致。

## 验收标准

1. `.venv/bin/python src/rag.py ingest <测试目录>` 成功入库，`stats` 数量正确。
2. `.venv/bin/python src/rag.py ask "测试问题"` 能基于知识库回答并给出来源。
3. 启动 agent 对话，问知识库相关问题时自动触发 `knowledge_search`，最终回答完整显示。
4. 停掉 PostgreSQL 再检索，agent 不崩溃，返回可读错误。

完成后请汇报：改动的文件清单、`ingest`/`ask` 的实测输出、以及遗留问题。
