#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#planner.py - 任务规划:创建/跟踪/完成多步任务计划(PostgreSQL 持久化)
import json
import sys
from pathlib import Path

import dotenv
from rich.console import Console
from rich.panel import Panel

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

from rag import ensure_db, get_conn  # noqa: E402

cons = Console()
STEP_STATUSES = {"pending", "in_progress", "done", "blocked"}
PLAN_STATUSES = {"active", "done", "cancelled"}


def ensure_plan_tables():
    """确保 task_plans / task_steps 表存在(幂等)"""
    ensure_db()
    with get_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_plans (
              id         BIGSERIAL PRIMARY KEY,
              title      TEXT NOT NULL,
              status     TEXT NOT NULL DEFAULT 'active',
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS task_steps (
              id          BIGSERIAL PRIMARY KEY,
              plan_id     BIGINT NOT NULL REFERENCES task_plans(id) ON DELETE CASCADE,
              seq         INT NOT NULL,
              description TEXT NOT NULL,
              status      TEXT NOT NULL DEFAULT 'pending',
              updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
              UNIQUE(plan_id, seq)
            )
            """
        )
        conn.commit()


def create_plan(title: str, steps: list) -> dict:
    """创建计划,返回 {plan_id, title, steps:[...]}"""
    ensure_plan_tables()
    steps = [s for s in (steps or []) if str(s).strip()]
    if not title.strip():
        raise ValueError("计划标题不能为空")
    if not steps:
        raise ValueError("计划至少需要一个步骤")
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO task_plans (title) VALUES (%s) RETURNING id", (title.strip(),)
        )
        pid = cur.fetchone()[0]
        for i, s in enumerate(steps):
            conn.execute(
                "INSERT INTO task_steps (plan_id, seq, description) VALUES (%s, %s, %s)",
                (pid, i, str(s).strip()),
            )
        conn.commit()
    return get_plan(pid)


def get_plan(plan_id: int) -> dict:
    """计划详情 {plan_id, title, status, steps:[{seq,description,status}]}"""
    ensure_plan_tables()
    with get_conn() as conn:
        row = conn.execute(
            "SELECT id, title, status FROM task_plans WHERE id = %s", (plan_id,)
        ).fetchone()
        if not row:
            return None
        steps = conn.execute(
            """
            SELECT seq, description, status FROM task_steps
            WHERE plan_id = %s ORDER BY seq
            """,
            (plan_id,),
        ).fetchall()
    return {
        "plan_id": row[0],
        "title": row[1],
        "status": row[2],
        "steps": [
            {"seq": r[0], "description": r[1], "status": r[2]} for r in steps
        ],
    }


def list_plans(limit: int = 10, active_only: bool = True) -> list:
    """计划列表,含完成步数统计"""
    ensure_plan_tables()
    cond = "WHERE p.status = 'active'" if active_only else ""
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT p.id, p.title, p.status,
                   count(s.id) AS total,
                   count(*) FILTER (WHERE s.status = 'done') AS done
            FROM task_plans p LEFT JOIN task_steps s ON s.plan_id = p.id
            {cond}
            GROUP BY p.id ORDER BY p.id DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
    return [
        {"plan_id": r[0], "title": r[1], "status": r[2], "total": r[3], "done": r[4]}
        for r in rows
    ]


def update_step(plan_id: int, seq: int, status: str) -> dict:
    """更新某一步状态,返回计划摘要;非法状态/不存在的步骤会报错"""
    ensure_plan_tables()
    status = str(status).strip().lower()
    if status not in STEP_STATUSES:
        raise ValueError(f"非法状态: {status}(可选 {sorted(STEP_STATUSES)})")
    with get_conn() as conn:
        cur = conn.execute(
            """
            UPDATE task_steps SET status = %s, updated_at = now()
            WHERE plan_id = %s AND seq = %s
            """,
            (status, plan_id, seq),
        )
        if cur.rowcount == 0:
            raise ValueError(f"计划 {plan_id} 中不存在步骤 {seq}")
        conn.commit()
    return get_plan(plan_id)


def complete_plan(plan_id: int) -> dict:
    """把整个计划标记为完成"""
    ensure_plan_tables()
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE task_plans SET status = 'done' WHERE id = %s", (plan_id,)
        )
        if cur.rowcount == 0:
            raise ValueError(f"计划不存在: {plan_id}")
        conn.execute(
            "UPDATE task_steps SET status = 'done', updated_at = now()"
            " WHERE plan_id = %s AND status <> 'done'",
            (plan_id,),
        )
        conn.commit()
    return get_plan(plan_id)


def clear_plans(confirm: bool = True) -> int:
    """清空所有计划,默认需二次确认"""
    if confirm:
        ans = input("确认清空所有任务计划? (y/N): ").strip().lower()
        if ans not in {"y", "yes"}:
            cons.print("已取消")
            return 0
    ensure_plan_tables()
    with get_conn() as conn:
        n = conn.execute("DELETE FROM task_plans").rowcount
        conn.commit()
        return n


def _fmt(plan: dict) -> str:
    if not plan:
        return "计划不存在"
    lines = [f"[bold]计划 {plan['plan_id']}: {plan['title']}[/bold] ({plan['status']})"]
    for s in plan["steps"]:
        mark = {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "×"}.get(s["status"], "?")
        lines.append(f"  {mark} [{s['seq']}] {s['description']} - {s['status']}")
    return "\n".join(lines)


def plan_panel(limit: int = 8):
    """返回最新进行中计划的 rich Panel(无计划或出错时返回 None)"""
    try:
        plans = list_plans(limit=1)
        if not plans:
            return None
        detail = get_plan(plans[0]["plan_id"])
    except Exception:
        return None
    if not detail:
        return None
    lines = [f"{detail['title']} ({plans[0]['done']}/{plans[0]['total']} 完成)"]
    for s in detail["steps"][:limit]:
        mark = {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "×"}.get(s["status"], "?")
        lines.append(f"{mark} [{s['seq']}] {s['description']}")
    if len(detail["steps"]) > limit:
        lines.append(f"... 共 {len(detail['steps'])} 步(完整进度见 /tasks)")
    return Panel("\n".join(lines), title=f"计划 {detail['plan_id']}", border_style="cyan")


def plan_status_line():
    """紧凑进度行,用于输入框上方常显;无进行中计划时返回 None"""
    try:
        plans = list_plans(limit=1)
        if not plans:
            return None
        detail = get_plan(plans[0]["plan_id"])
    except Exception:
        return None
    if not detail:
        return None
    marks = "".join(
        {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "×"}.get(s["status"], "?")
        for s in detail["steps"]
    )
    return f"[cyan]计划 {detail['plan_id']}[/cyan] {detail['title']} {marks} ({plans[0]['done']}/{plans[0]['total']})"


def plan_lines(limit: int = 8) -> list:
    """计划面板纯文本行(供 TUI 顶部窗格渲染),无进行中计划返回空列表"""
    try:
        plans = list_plans(limit=1)
        if not plans:
            return []
        detail = get_plan(plans[0]["plan_id"])
    except Exception:
        return []
    if not detail:
        return []
    lines = [f"计划 {detail['plan_id']} {detail['title']} ({plans[0]['done']}/{plans[0]['total']})"]
    for s in detail["steps"][:limit]:
        mark = {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "×"}.get(s["status"], "?")
        lines.append(f"{mark} [{s['seq']}] {s['description']}")
    if len(detail["steps"]) > limit:
        lines.append(f"... 共 {len(detail['steps'])} 步(/tasks 查看全部)")
    return lines


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in {"create", "list", "show", "update", "complete", "clear"}:
        cons.print(
            "用法:\n"
            "  planner.py create \"标题\" 步骤1 步骤2...\n"
            "  planner.py list\n"
            "  planner.py show <plan_id>\n"
            "  planner.py update <plan_id> <seq> <pending|in_progress|done|blocked>\n"
            "  planner.py complete <plan_id>\n"
            "  planner.py clear"
        )
        return 1
    cmd = argv[0]
    try:
        if cmd == "create":
            if len(argv) < 3:
                raise ValueError("用法: planner.py create \"标题\" 步骤1 步骤2...")
            cons.print(_fmt(create_plan(argv[1], argv[2:])))
        elif cmd == "list":
            for p in list_plans():
                cons.print(f"[dim]{p['plan_id']}[/dim] {p['title']} - {p['done']}/{p['total']} 完成 ({p['status']})")
        elif cmd == "show":
            if len(argv) < 2:
                raise ValueError("用法: planner.py show <plan_id>")
            cons.print(_fmt(get_plan(int(argv[1]))))
        elif cmd == "update":
            if len(argv) < 4:
                raise ValueError("用法: planner.py update <plan_id> <seq> <status>")
            cons.print(_fmt(update_step(int(argv[1]), int(argv[2]), argv[3])))
        elif cmd == "complete":
            if len(argv) < 2:
                raise ValueError("用法: planner.py complete <plan_id>")
            cons.print(_fmt(complete_plan(int(argv[1]))))
        elif cmd == "clear":
            n = clear_plans()
            cons.print(f"[green]已清空 {n} 个计划[/green]")
    except Exception as e:
        cons.print(f"[red]错误: {e}[/red]")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
