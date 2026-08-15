#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#memory.py - 长期记忆:记住/回忆用户信息,持久化到 PostgreSQL(pgvector)
import sys
from pathlib import Path

import dotenv
from rich.console import Console

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

from rag import VECTOR_DIM, ensure_db, get_conn, get_embedder  # noqa: E402

cons = Console()


def ensure_memory_table():
    """确保 memories 表与 HNSW 索引存在(幂等)"""
    ensure_db()
    with get_conn() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS memories (
              id         BIGSERIAL PRIMARY KEY,
              content    TEXT NOT NULL,
              embedding  vector({VECTOR_DIM}) NOT NULL,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS memories_hnsw_idx
              ON memories USING hnsw (embedding vector_cosine_ops)
            """
        )
        conn.commit()


def remember(text: str) -> int:
    """保存一条长期记忆,返回写入行数"""
    ensure_memory_table()
    embedder = get_embedder()
    vec = embedder.embed([text])[0]
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO memories (content, embedding) VALUES (%s, %s::vector)",
            (text, str(vec)),
        )
        conn.commit()
        return cur.rowcount


def retrieve(query: str, top_k: int = 5) -> list:
    """语义检索与 query 最相关的原始记忆,返回 [{content, similarity}]"""
    ensure_memory_table()
    embedder = get_embedder()
    qvec = embedder.embed([query])[0]
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT content, 1 - (embedding <=> %s::vector) AS similarity
            FROM memories
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (str(qvec), str(qvec), top_k),
        ).fetchall()
    return [
        {"content": r[0], "similarity": round(float(r[1]), 4)} for r in rows
    ]


def summarize_memories(contents: list) -> str:
    """用 LLM 把多条记忆片段合并成一条完整记忆,要求不丢失任何信息"""
    prompt = (
        "下面是用户之前留下的多条记忆片段。请把它们合并成一条完整、不丢失任何信息的记忆文本。\n"
        "要求:\n"
        "1. 保留所有事实细节:人名、数字、时间、地点、偏好、任务背景、待办事项等全部保留;\n"
        "2. 不要删减、不要概括掉任何具体信息,只做去重与合并;\n"
        "3. 片段间如有矛盾,全部保留并注明存在冲突;\n"
        "4. 只输出合并后的记忆文本,不要任何解释、前缀或编号。\n\n"
        "记忆片段:\n" + "\n".join(f"- {c}" for c in contents)
    )
    try:
        import llm

        provider = llm.get_provider()
        model = llm.default_model() or "deepseek-chat"
        text = provider.complete_text(
            [
                {
                    "role": "system",
                    "content": "你是一个忠实的信息合并器,绝不遗漏或篡改任何事实。",
                },
                {"role": "user", "content": prompt},
            ],
            model,
        )
        return text.strip() or "\n".join(contents)
    except Exception:
        # 汇总失败时原样拼接,保证不丢信息
        return "\n".join(contents)


def recall(query: str, top_k: int = 5) -> str:
    """回忆:检索 2-10 条相关记忆,汇总成一条完整记忆返回(不丢失信息)"""
    top_k = min(max(int(top_k), 2), 10)
    items = retrieve(query, top_k)
    if not items:
        return "暂无相关记忆"
    contents = [i["content"] for i in items]
    if len(contents) == 1:
        return contents[0]
    return summarize_memories(contents)


def list_memories(limit: int = 50) -> list:
    """列出最近保存的记忆,返回 [{id, content, created_at}]"""
    ensure_memory_table()
    with get_conn() as conn:
        rows = conn.execute(
            """
            SELECT id, content, created_at
            FROM memories
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        {"id": r[0], "content": r[1], "created_at": r[2].isoformat()} for r in rows
    ]


def clear_memories(confirm: bool = True) -> int:
    """清空长期记忆,默认需二次确认"""
    if confirm:
        ans = input("确认清空所有长期记忆? (y/N): ").strip().lower()
        if ans not in {"y", "yes"}:
            cons.print("已取消")
            return 0
    ensure_memory_table()
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM memories")
        conn.commit()
        return cur.rowcount


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        cons.print(
            "用法:\n"
            "  memory.py add \"内容\"        保存一条记忆\n"
            "  memory.py recall \"问题\" [k]  检索并汇总成一条完整记忆(2-10 条)\n"
            "  memory.py search \"问题\" [k]  查看原始检索结果(调试)\n"
            "  memory.py list               列出最近记忆\n"
            "  memory.py clear              清空(二次确认)"
        )
        return 1
    cmd = argv[0]
    try:
        if cmd == "add":
            if len(argv) < 2:
                raise ValueError("用法: memory.py add \"内容\"")
            n = remember(argv[1])
            cons.print(f"[green]已记住 {n} 条[/green]")
        elif cmd == "recall":
            if len(argv) < 2:
                raise ValueError("用法: memory.py recall \"问题\" [top_k]")
            top_k = int(argv[2]) if len(argv) > 2 else 5
            cons.print(recall(argv[1], top_k))
        elif cmd == "search":
            if len(argv) < 2:
                raise ValueError("用法: memory.py search \"问题\" [top_k]")
            top_k = int(argv[2]) if len(argv) > 2 else 5
            for r in retrieve(argv[1], top_k):
                cons.print(f"[cyan]{r['similarity']:.4f}[/cyan] {r['content']}")
        elif cmd == "list":
            for m in list_memories():
                cons.print(f"[dim]{m['id']} {m['created_at']}[/dim] {m['content']}")
        elif cmd == "clear":
            n = clear_memories()
            cons.print(f"[green]已删除 {n} 条记忆[/green]")
        else:
            raise ValueError(f"未知命令: {cmd}")
    except Exception as e:
        cons.print(f"[red]错误: {e}[/red]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
