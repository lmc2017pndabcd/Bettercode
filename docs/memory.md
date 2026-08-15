# Agent 记忆功能说明

## 两层记忆

### 1. 会话记忆（短期）

- `src/main.py` 在会话内保留聊天历史（`history`，仅存 user/assistant 纯文本），下一轮提问时一并发送给模型，让 agent 能引用上下文。
- 上限 `MAX_HISTORY_CHARS = 6000` 字符，超出后按"最早的一问一答"整对丢弃。
- 命令：`/new` 清空会话记忆，重新开始。

### 2. 长期记忆（跨会话，PostgreSQL 持久化）

- 模块：`src/memory.py`，复用 `rag.py` 的数据库连接与 embedding（pgvector）。
- 表：`memories(id, content, embedding, created_at)` + HNSW 索引（cosine）。
- 工具（注册在 `default.function.json`）：
  - `remember(fact)`：保存一条记忆。用户告知个人信息、偏好、任务背景或要求记住某事时，模型应调用。
  - `recall_memory(query, top_k=2-10)`：检索 2-10 条相关记忆 → 用 LLM 忠实汇总成**一条**完整记忆返回给模型（不丢失信息）。
- CLI：
  ```bash
  python src/memory.py add "我的名字叫小明"
  python src/memory.py recall "我叫什么"
  python src/memory.py search "我叫什么"   # 查看原始检索结果（调试）
  python src/memory.py list
  python src/memory.py clear
  ```
- agent 命令：`/memories` 列出长期记忆。

## 工作方式

系统提示（`SYSTEM_PROMPT`）引导模型：

- 用户告知个人信息/偏好 → 调用 `remember`；
- 回答需要此前记住的信息 → 调用 `recall_memory`（内部：向量检索 2-10 条 → LLM 汇总成一条，汇总失败时自动原样拼接，保证不丢信息）；
- 问题涉及本地知识库 → 先调用 `knowledge_search`。

`/new` 只清空会话记忆，不删除长期记忆；长期记忆需用 `memory.py clear` 或手动删除。
