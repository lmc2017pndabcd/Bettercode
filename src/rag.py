#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#rag.py - RAG 工具:知识库入库 / 语义检索 / 问答,供 CLI 与 agent 调用
import json
import os
import re
import sys
from pathlib import Path

import dotenv
import psycopg
from psycopg.conninfo import conninfo_to_dict
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://localhost:5432/rag_kb")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "local")   # local | api
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5")
VECTOR_DIM = int(os.getenv("VECTOR_DIM", "512"))
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "400"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))
RAG_CHAT_MODEL = os.getenv("RAG_CHAT_MODEL", "deepseek-chat")

cons = Console()


class Embedder:
    """向量化抽象基类:embed(texts) -> list[list[float]]"""

    def embed(self, texts):
        raise NotImplementedError


class LocalEmbedder(Embedder):
    """fastembed 本地模型(默认,不依赖外部 API)"""

    def __init__(self):
        from fastembed import TextEmbedding  # 延迟导入,避免无 embedding 场景也加载模型

        self._model = TextEmbedding(model_name=EMBEDDING_MODEL)

    def embed(self, texts):
        # 转成普通 float:np.float32 的 str 是 "np.float32(...)",pgvector 解析不了
        return [[float(x) for x in v] for v in self._model.embed(list(texts))]


class ApiEmbedder(Embedder):
    """OpenAI 兼容 embeddings API(EMBEDDING_PROVIDER=api 时启用,仅留接口)"""

    def __init__(self):
        import openai

        self._client = chat_client()  # 使用 .env 的 OPENAI_BASE_URL / OPENAI_API_KEY
        self._model = EMBEDDING_MODEL

    def embed(self, texts):
        resp = self._client.embeddings.create(model=self._model, input=list(texts))
        return [[float(x) for x in d.embedding] for d in resp.data]


def get_embedder() -> Embedder:
    return ApiEmbedder() if EMBEDDING_PROVIDER == "api" else LocalEmbedder()


def chat_client():
    """构造 OpenAI 兼容客户端;兼容 OPENAI_BASE_URL 直接存完整接口路径的写法"""
    import openai

    base = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    return openai.OpenAI(base_url=base)


def conn_params() -> dict:
    """DATABASE_URL 转 psycopg.connect 参数(过滤空值)"""
    return {k: v for k, v in conninfo_to_dict(DATABASE_URL).items() if v is not None}


def auto_start_postgres() -> bool:
    """连接失败时尝试用 brew services 自动启动 PostgreSQL,等待就绪"""
    import shutil
    import subprocess
    import time

    service = os.getenv("PG_SERVICE", "postgresql@17")
    if not shutil.which("brew"):
        return False
    subprocess.run(["brew", "services", "start", service], capture_output=True, text=True)
    for _ in range(20):
        time.sleep(1)
        try:
            with psycopg.connect(**conn_params(), connect_timeout=2) as conn:
                conn.execute("SELECT 1")
                return True
        except psycopg.OperationalError:
            continue
    return False


def get_conn(params: dict = None, autocommit: bool = False):
    """统一连接入口;连接失败时自动启动 PostgreSQL 并重试"""
    params = params or conn_params()
    try:
        return psycopg.connect(**params, autocommit=autocommit)
    except psycopg.OperationalError:
        if not auto_start_postgres():
            raise
        return psycopg.connect(**params, autocommit=autocommit)


def ensure_db():
    """确保数据库 / 扩展 / 表 / 索引存在(幂等,可重复调用)"""
    info = conninfo_to_dict(DATABASE_URL)
    dbname = info.get("dbname") or "rag_kb"
    admin = {k: v for k, v in info.items() if v is not None}
    admin["dbname"] = "postgres"
    with get_conn(admin, autocommit=True) as conn:
        exists = conn.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s", (dbname,)
        ).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{dbname}"')
    with get_conn() as conn:
        conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS documents (
              id          BIGSERIAL PRIMARY KEY,
              content     TEXT NOT NULL,
              source      TEXT NOT NULL DEFAULT '',
              chunk_index INT  NOT NULL DEFAULT 0,
              embedding   vector({VECTOR_DIM}) NOT NULL,
              created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS documents_hnsw_idx
              ON documents USING hnsw (embedding vector_cosine_ops)
            """
        )
        conn.commit()


def chunk_text(text: str, size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list:
    """按段落 / 句子切分文本,块长不超过 size,相邻块重叠 overlap 字符"""
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    units = []  # (句子, 是否段落开头)
    for p in paragraphs:
        parts = [s.strip() for s in re.split(r"(?<=[。！？!?；;])", p) if s.strip()]
        if not parts:
            continue
        units.append((parts[0], True))
        units.extend((s, False) for s in parts[1:])
    if not units:
        return []
    chunks = []
    cur = ""
    for s, para_start in units:
        if len(s) > size:
            # 超长句按 size 硬切
            if cur:
                chunks.append(cur)
                cur = ""
            for i in range(0, len(s), size):
                chunk = s[i:i + size]
                if chunk:
                    chunks.append(chunk)
            continue
        sep = "\n\n" if (para_start and cur) else ""
        if cur and len(cur) + len(sep) + len(s) > size:
            chunks.append(cur)
            tail = cur[-overlap:] if overlap else ""
            cur = tail + sep if tail else ""
        elif cur:
            cur += sep
        cur += s
    if cur:
        chunks.append(cur)
    return chunks


def collect_files(path) -> list:
    """收集待入库文件:单文件或目录递归(.md/.txt)"""
    p = Path(path)
    if p.is_file():
        return [p] if p.suffix.lower() in {".md", ".txt"} else []
    if p.is_dir():
        return [
            f for f in sorted(p.rglob("*"))
            if f.is_file() and f.suffix.lower() in {".md", ".txt"}
        ]
    return []


def ingest(path: str, with_graph: bool = False) -> dict:
    """入库:切分 -> 向量化 -> 写入;同一 source 先删旧再写新(增量更新)"""
    ensure_db()
    files = collect_files(path)
    if not files:
        raise ValueError(f"未找到可入库的 .md/.txt 文件: {path}")
    embedder = get_embedder()
    total = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=cons,
    ) as prog:
        task = prog.add_task("入库中...", total=len(files))
        with get_conn() as conn:
            for f in files:
                prog.update(task, description=f"处理 {f.name}")
                text = f.read_text(encoding="utf-8", errors="replace")
                chunks = chunk_text(text)
                if chunks:
                    vectors = embedder.embed(chunks)
                    source = str(f)
                    conn.execute("DELETE FROM documents WHERE source = %s", (source,))
                    inserted = []
                    with conn.cursor() as cur:
                        for idx, (content, vec) in enumerate(zip(chunks, vectors)):
                            rid = cur.execute(
                                "INSERT INTO documents (content, source, chunk_index, embedding)"
                                " VALUES (%s, %s, %s, %s::vector) RETURNING id",
                                (content, source, idx, str(vec)),
                            ).fetchone()[0]
                            inserted.append((rid, content))
                    conn.commit()
                    total += len(chunks)
                    if with_graph:
                        import graphrag
                        for rid, content in inserted:
                            graphrag.store_chunk_graph(rid, content)
                prog.advance(task)
    return {"files": len(files), "chunks": total}


def search(query: str, top_k: int = 5) -> list:
    """语义检索(+ Graph RAG 融合),返回 [{content, source, chunk_index, similarity, via, ...}]"""
    ensure_db()
    embedder = get_embedder()
    qvec = embedder.embed([query])[0]
    # 图谱有数据时预留约 1/3 槽位,保证图结果真的能进入结果集
    graph_slots = 0
    graph = None
    if os.getenv("GRAPH_RAG", "1") != "0":
        try:
            import graphrag
            graph = graphrag.graph_search(query, top_k)
            graph_slots = max(1, top_k // 3) if graph["chunks"] and top_k >= 3 else 0
        except Exception:
            graph = None
    vector_limit = max(top_k - graph_slots, 1)
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT content, source, chunk_index,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM documents
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (str(qvec), str(qvec), vector_limit),
        ).fetchall()
    results = [
        {
            "content": r[0],
            "source": r[1],
            "chunk_index": r[2],
            "similarity": round(float(r[3]), 4),
            "via": "vector",
        }
        for r in rows
    ]
    if graph:
        seen = {(r["source"], r["chunk_index"]) for r in results}
        for c in graph["chunks"]:
            if len(results) >= top_k:
                break
            key = (c["source"], c["chunk_index"])
            if key in seen:
                continue
            seen.add(key)
            results.append(
                {
                    "content": c["content"],
                    "source": c["source"],
                    "chunk_index": c["chunk_index"],
                    "similarity": None,
                    "via": "graph",
                    "entities": [e["name"] for e in graph["entities"]],
                    "paths": graph["paths"],
                }
            )
    return results


def stats() -> dict:
    """知识库统计:文档数 / 片段数"""
    ensure_db()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT count(*), count(DISTINCT source) FROM documents"
        ).fetchone()
    return {"chunks": row[0], "documents": row[1]}


def clear(confirm: bool = True) -> int:
    """清空知识库,默认需二次确认"""
    if confirm:
        ans = input("确认清空知识库?所有文档将被删除 (y/N): ").strip().lower()
        if ans not in {"y", "yes"}:
            cons.print("已取消")
            return 0
    ensure_db()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM documents")
        conn.commit()
        return cur.rowcount


def ask(question: str, top_k: int = 5) -> str:
    """检索 + DeepSeek 生成回答(调试用,效果与 agent 内调用一致)"""
    results = search(question, top_k)
    if not results:
        return "知识库中没有相关内容,无法回答。"
    context = "\n\n".join(
        f"[{i + 1}] (来源:{r['source']}#{r['chunk_index']}) {r['content']}"
        for i, r in enumerate(results)
    )
    import llm

    provider = llm.get_provider()  # 与 agent 共用同一 LLM 后端(DeepSeek/OpenAI/Anthropic)
    model = llm.default_model() or RAG_CHAT_MODEL
    messages = [
        {
            "role": "system",
            "content": "你是知识库问答助手。请仅基于提供的检索片段回答;片段不足以回答时明确说明。"
                       "回答结尾列出引用的来源编号。",
        },
        {
            "role": "user",
            "content": f"检索片段:\n{context}\n\n问题:{question}",
        },
    ]
    buf = ""
    for ev in provider.create(messages, tools=None, model=model):
        content = ev.get("content")
        if content:
            buf += content
            print(content, end="", flush=True)
    print()
    return buf


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        cons.print(__doc__)
        cons.print(
            "用法:\n"
            "  rag.py ingest <文件或目录> [--graph]  入库(加 --graph 同时建图)\n"
            "  rag.py ask \"问题\"                    检索 + 生成回答\n"
            "  rag.py search \"问题\" [k]             仅检索(调试)\n"
            "  rag.py graph build|search|clear       知识图谱操作\n"
            "  rag.py stats                         统计\n"
            "  rag.py clear                         清空(二次确认)"
        )
        return 1
    cmd = argv[0]
    try:
        if cmd == "ingest":
            if len(argv) < 2:
                raise ValueError("用法: rag.py ingest <文件或目录> [--graph]")
            with_graph = "--graph" in argv
            path = [a for a in argv[1:] if a != "--graph"][0]
            r = ingest(path, with_graph)
            cons.print(f"[green]入库完成:{r['files']} 个文件, {r['chunks']} 个片段[/green]")
        elif cmd == "ask":
            if len(argv) < 2:
                raise ValueError("用法: rag.py ask \"问题\"")
            ask(argv[1])
        elif cmd == "search":
            if len(argv) < 2:
                raise ValueError("用法: rag.py search \"问题\" [top_k]")
            top_k = int(argv[2]) if len(argv) > 2 else 5
            for r in search(argv[1], top_k):
                cons.print(
                    f"[cyan]{r['similarity']:.4f}[/cyan] {r['source']}#{r['chunk_index']}\n{r['content']}\n"
                )
        elif cmd == "stats":
            s = stats()
            cons.print(f"[green]文档数: {s['documents']}, 片段数: {s['chunks']}[/green]")
        elif cmd == "clear":
            n = clear()
            cons.print(f"[green]已删除 {n} 个片段[/green]")
        elif cmd == "graph":
            import graphrag
            return graphrag.main(argv[1:])
        else:
            raise ValueError(f"未知命令: {cmd}")
    except Exception as e:
        cons.print(f"[red]错误: {e}[/red]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
