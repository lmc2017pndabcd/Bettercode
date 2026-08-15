# Graph RAG

在向量检索之上叠加知识图谱（实体 + 关系），让检索能利用**多跳关系**而不是只靠语义相似度。

## 存储（PostgreSQL，无新服务）

- `entities(id, name UNIQUE, type, embedding)` + HNSW 索引：实体及其向量；
- `relations(source_id, target_id, rel_type)`：实体间关系（外键级联删除）；
- `entity_chunks(entity_id, chunk_id)`：实体 ↔ 文档片段关联。

## 流程

1. **抽取**：用当前 LLM 后端（DeepSeek/OpenAI/Anthropic/本地模型）对每个 chunk 抽取实体与关系（严格 JSON，宽容解析）；
2. **入库**：实体按名称去重、向量化，关系与片段关联写入；
3. **检索**：查询向量 → 匹配 top-3 实体（相似度阈值 0.35）→ 图内多跳扩展（默认 2 跳）→ 取关联片段，与向量检索结果**去重合并**（`via: vector|graph` 标记）。

## 使用

```bash
# 1. 建图(处理全部已有文档)
python src/rag.py graph build
# 或入库时直接建图
python src/rag.py ingest <目录> --graph

# 2. 单独看图谱检索结果
python src/rag.py graph search "pgvector 是什么"

# 3. 普通检索自动融合图谱(GRAP_RAG=1 时)
python src/rag.py search "PostgreSQL 向量检索"
```

## 配置（`.env`）

```env
GRAPH_RAG=1               # 0 关闭融合
GRAPH_MAX_HOPS=2          # 图扩展跳数
GRAPH_ENTITY_TOP_K=3      # 种子实体数
GRAPH_RELATION_LIMIT=20   # 每跳关系上限
```

## 注意

- 建图会逐 chunk 调用 LLM 抽取，耗时与 token 消耗按文档量线性增长；小知识库很快，大库建议分批。
- 本地小模型（如 dscv2lite）抽取 JSON 质量可能不稳定；效果不佳时换 DeepSeek/Claude 或调低 `GRAPH_ENTITY_TOP_K`。
- 清空图谱：`python src/rag.py graph clear`（不影响 documents 向量数据）。
