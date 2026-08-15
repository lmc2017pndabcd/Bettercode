#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#graphrag.py - Graph RAG:实体/关系抽取与图检索(PostgreSQL 存储,LLM 抽取,向量+多跳融合)
import json
import os
import re
import sys
from pathlib import Path

import dotenv
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

import llm  # noqa: E402
from rag import VECTOR_DIM, RAG_CHAT_MODEL, ensure_db, get_conn, get_embedder  # noqa: E402

cons = Console()
GRAPH_MAX_HOPS = int(os.getenv("GRAPH_MAX_HOPS", "2"))
GRAPH_ENTITY_TOP_K = int(os.getenv("GRAPH_ENTITY_TOP_K", "3"))
GRAPH_RELATION_LIMIT = int(os.getenv("GRAPH_RELATION_LIMIT", "20"))

EXTRACT_PROMPT = (
    "你是知识图谱抽取器。从文本中抽取命名实体及其关系,严格输出 JSON:\n"
    '{"entities":[{"name":"实体名","type":"实体类型"}],"relations":[{"source":"来源实体名","target":"目标实体名","type":"关系类型"}]}\n'
    "要求:\n"
    "1. 实体包括人名、组织、产品、技术、地点、概念等,名字用原文;\n"
    "2. 关系要语义明确,如\"开发了\"\"位于\"\"属于\";\n"
    "3. 不要编造文本中不存在的信息;\n"
    "4. 只输出 JSON,不要任何解释。\n\n文本:\n__TEXT__"
)


def ensure_graph_tables():
    """确保 entities / relations / entity_chunks 表与索引存在(幂等)"""
    ensure_db()
    with get_conn() as conn:
        conn.execute(
            f"""
            CREATE TABLE IF NOT EXISTS entities (
              id        BIGSERIAL PRIMARY KEY,
              name      TEXT NOT NULL UNIQUE,
              type      TEXT NOT NULL DEFAULT '',
              embedding vector({VECTOR_DIM}) NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS entities_hnsw_idx
              ON entities USING hnsw (embedding vector_cosine_ops)
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS relations (
              id        BIGSERIAL PRIMARY KEY,
              source_id BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
              target_id BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
              rel_type  TEXT NOT NULL,
              UNIQUE(source_id, target_id, rel_type)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS entity_chunks (
              entity_id BIGINT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
              chunk_id  BIGINT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
              PRIMARY KEY (entity_id, chunk_id)
            )
            """
        )
        conn.commit()


def _parse_json(raw: str):
    """宽容解析模型输出的 JSON(去掉代码围栏,取第一个 {..})"""
    if not raw:
        return None
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.S)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return None


def extract_entities(text: str) -> dict:
    """用 LLM 抽取实体与关系,返回 {"entities":[...], "relations":[...]}"""
    provider = llm.get_provider()
    model = llm.default_model() or RAG_CHAT_MODEL
    try:
        raw = provider.complete_text(
            [
                {"role": "system", "content": "你是知识图谱抽取器,只输出合法 JSON。"},
                {"role": "user", "content": EXTRACT_PROMPT.replace("__TEXT__", text[:2000])},
            ],
            model,
        )
    except Exception:
        return {"entities": [], "relations": []}
    data = _parse_json(raw)
    if not data:
        return {"entities": [], "relations": []}
    entities = [
        {"name": str(e.get("name", "")).strip(), "type": str(e.get("type", "")).strip()}
        for e in data.get("entities", []) if str(e.get("name", "")).strip()
    ]
    relations = [
        {
            "source": str(r.get("source", "")).strip(),
            "target": str(r.get("target", "")).strip(),
            "type": str(r.get("type", "")).strip(),
        }
        for r in data.get("relations", [])
        if str(r.get("source", "")).strip() and str(r.get("target", "")).strip()
    ]
    return {"entities": entities, "relations": relations}


def _upsert_entity(conn, name: str, etype: str, vec) -> int:
    row = conn.execute("SELECT id FROM entities WHERE name = %s", (name,)).fetchone()
    if row:
        return row[0]
    cur = conn.execute(
        "INSERT INTO entities (name, type, embedding) VALUES (%s, %s, %s::vector) RETURNING id",
        (name, etype, str(vec)),
    )
    return cur.fetchone()[0]


def store_chunk_graph(chunk_id: int, text: str) -> int:
    """抽取单个 chunk 的实体/关系并入库,返回新增实体数"""
    ensure_graph_tables()
    data = extract_entities(text)
    if not data["entities"]:
        return 0
    embedder = get_embedder()
    vecs = embedder.embed([e["name"] for e in data["entities"]])
    with get_conn() as conn:
        ids = {}
        for ent, vec in zip(data["entities"], vecs):
            eid = _upsert_entity(conn, ent["name"], ent["type"], vec)
            ids[ent["name"]] = eid
            conn.execute(
                "INSERT INTO entity_chunks (entity_id, chunk_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (eid, chunk_id),
            )
        for rel in data["relations"]:
            s, t = ids.get(rel["source"]), ids.get(rel["target"])
            if s and t and s != t:
                conn.execute(
                    "INSERT INTO relations (source_id, target_id, rel_type) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
                    (s, t, rel["type"]),
                )
        conn.commit()
    return len(ids)


def build_all() -> int:
    """对 documents 里所有 chunk 抽取并建图,返回处理的实体总数"""
    ensure_graph_tables()
    with get_conn() as conn:
        rows = conn.execute("SELECT id, content FROM documents ORDER BY id").fetchall()
    if not rows:
        return 0
    total = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=cons,
    ) as prog:
        task = prog.add_task("抽取实体/关系...", total=len(rows))
        for cid, content in rows:
            total += store_chunk_graph(cid, content)
            prog.advance(task)
    return total


def _expand(conn, seed_ids: list) -> tuple:
    """从种子实体做多跳扩展,返回 (节点集合, 遍历到的边列表)"""
    eids = set(seed_ids)
    frontier = set(seed_ids)
    edges = []
    for _ in range(GRAPH_MAX_HOPS):
        if not frontier:
            break
        rows = conn.execute(
            """
            SELECT source_id, target_id, rel_type FROM relations
            WHERE source_id = ANY(%s) OR target_id = ANY(%s)
            LIMIT %s
            """,
            (list(frontier), list(frontier), GRAPH_RELATION_LIMIT),
        ).fetchall()
        nxt = set()
        for s, t, rtype in rows:
            edges.append((s, t, rtype))
            for node in (s, t):
                if node not in eids:
                    nxt.add(node)
        eids.update(nxt)
        frontier = nxt
    return list(eids), edges


def graph_search(query: str, top_k: int = 5) -> dict:
    """图检索:实体向量匹配 + 多跳扩展,返回关联片段与实体路径"""
    ensure_graph_tables()
    embedder = get_embedder()
    qvec = embedder.embed([query])[0]
    with get_conn() as conn:
        ent_rows = conn.execute(
            """
            SELECT id, name, type, 1 - (embedding <=> %s::vector) AS sim
            FROM entities
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (str(qvec), str(qvec), GRAPH_ENTITY_TOP_K),
        ).fetchall()
        seeds = [r[0] for r in ent_rows if r[3] >= 0.35]
        eids, edges = _expand(conn, seeds)
        chunks = []
        if eids:
            rows = conn.execute(
                """
                SELECT DISTINCT d.id, d.content, d.source, d.chunk_index
                FROM entity_chunks ec JOIN documents d ON d.id = ec.chunk_id
                WHERE ec.entity_id = ANY(%s)
                ORDER BY d.id
                LIMIT %s
                """,
                (eids, top_k),
            ).fetchall()
            chunks = [
                {"chunk_id": r[0], "content": r[1], "source": r[2], "chunk_index": r[3]}
                for r in rows
            ]
        name_map = dict(
            conn.execute(
                "SELECT id, name FROM entities WHERE id = ANY(%s)", (list(eids) or [0],)
            ).fetchall()
        )
    paths = [
        f"{name_map.get(s, '?')} -[{r}]-> {name_map.get(t, '?')}"
        for s, t, r in edges
        if s in name_map and t in name_map
    ]
    entities = [{"name": r[1], "type": r[2]} for r in ent_rows]
    return {"chunks": chunks, "entities": entities, "paths": paths[:20]}


def clear_graph(confirm: bool = True) -> int:
    """清空图数据,默认需二次确认"""
    if confirm:
        ans = input("确认清空知识图谱? (y/N): ").strip().lower()
        if ans not in {"y", "yes"}:
            cons.print("已取消")
            return 0
    ensure_graph_tables()
    with get_conn() as conn:
        conn.execute("DELETE FROM relations")
        conn.execute("DELETE FROM entity_chunks")
        n = conn.execute("DELETE FROM entities").rowcount
        conn.commit()
        return n


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in {"build", "search", "clear"}:
        cons.print(
            "用法:\n"
            "  graphrag.py build                对全部文档建图(LLM 抽取实体/关系)\n"
            "  graphrag.py search \"问题\" [k]     图检索\n"
            "  graphrag.py clear                清空图(二次确认)"
        )
        return 1
    cmd = argv[0]
    try:
        if cmd == "build":
            n = build_all()
            cons.print(f"[green]建图完成,共处理 {n} 个实体[/green]")
        elif cmd == "search":
            if len(argv) < 2:
                raise ValueError("用法: graphrag.py search \"问题\" [top_k]")
            top_k = int(argv[2]) if len(argv) > 2 else 5
            g = graph_search(argv[1], top_k)
            cons.print("[bold]匹配实体:[/bold] " + ", ".join(e["name"] for e in g["entities"]))
            for p in g["paths"]:
                cons.print(f"[dim]{p}[/dim]")
            for c in g["chunks"]:
                cons.print(f"\n[cornflower_blue]{c['source']}#{c['chunk_index']}[/cornflower_blue]\n{c['content'][:200]}")
        elif cmd == "clear":
            n = clear_graph()
            cons.print(f"[green]已清空 {n} 个实体[/green]")
    except Exception as e:
        cons.print(f"[red]错误: {e}[/red]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
