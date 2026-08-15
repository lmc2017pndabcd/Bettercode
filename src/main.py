#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#main.py - 本地 AI 助手:prompt_toolkit 全屏交互(固定计划面板 + 可滚动输出 + 输入框)
import importlib.util as ilib
import json
import logging
import os
import queue
import threading
from pathlib import Path

import dotenv
import llm
import mcp_client
import skill
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings, merge_key_bindings
from prompt_toolkit.key_binding.defaults import load_key_bindings
from prompt_toolkit.keys import Keys
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.containers import Float, FloatContainer
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.layout.menus import CompletionsMenuControl
from prompt_toolkit.lexers import Lexer
from prompt_toolkit.document import Document

logging.basicConfig(level=logging.DEBUG, filename="agent.log")
logging.getLogger("markdown-it").setLevel(logging.INFO)
dotenv.load_dotenv("../.env")
ROOT = Path(__file__).resolve().parent.parent
provider = llm.get_provider()
model = llm.default_model() or input("model:")
mcp_client.manager.start()
skill.check_skills()
SKILLS_DIR = os.path.expanduser("~/.bettercode/skills")

MAX_TOOL_ROUNDS = int(os.getenv("MAX_TOOL_ROUNDS", "30"))   # 单轮对话内最多连续调用工具的次数
MAX_HISTORY_CHARS = 6000   # 会话记忆保留的最大字符数,超出后丢弃最早的对话
SYSTEM_PROMPT = (
    "你是用户的本地 AI 助手。"
    "可用工具:knowledge_search(检索本地知识库)、remember(记住用户告知的重要信息)、recall_memory(回忆并汇总之前记住的信息)、run_func(在宿主机执行脚本函数,技能脚本用这个)、run_command(在安全沙箱中执行命令,执行前会请你审批)、allow_<skill>(技能工具)。"
    "当用户告知个人信息、偏好、任务背景或要求你记住某件事时,调用 remember;"
    "当回答需要此前记住的信息时,调用 recall_memory;"
    "当问题涉及本地知识库内容时,先调用 knowledge_search 再回答;"
    "需要实时信息且知识库没有时,调用 web_search(联网搜索);查看具体网页内容用 fetch_url(打开搜索结果链接,或天气类问题直接 fetch_url https://wttr.in/<城市>);"
    "技能脚本的绝对路径会由工具返回,直接用 run_func 执行,不要用 run_command 去 find 脚本位置;"
    "需要实际操作(构建、测试、写文件、查环境)时,调用 run_command;"
    "复杂多步任务:先 create_plan 拆解步骤,执行中 update_step 标记进度,完成后 complete_plan;"
    "所有 SKILL.md 都在 ~/.bettercode/skills 的子目录里"
)
history = []   # 会话记忆:仅存 user/assistant 纯文本消息
RUN_TEST_CMD = os.getenv("RUN_TEST_CMD", "make test")
MAX_RELEASE_ROUNDS = int(os.getenv("MAX_RELEASE_ROUNDS", "50"))   # 上线模式的工具调用轮次上限
release_mode = False
planning_mode = False
mode_instruction = ""
PLANNING_INSTRUCTIONS = (
    "当前处于任务规划模式。收到用户请求后:\n"
    "1. 必须先用 create_plan 拆解为可执行的步骤(标题 + 步骤列表),不得跳过规划直接执行;\n"
    "2. 然后逐步执行(run_command / read_file / write_file / web_search 等),开始某步标记 in_progress,每完成一步 update_step 标记 done,遇到阻塞标记 blocked;\n"
    "3. 全部完成后 complete_plan,并汇报计划编号与各步骤结果。"
)
RELEASE_INSTRUCTIONS = (
    f"当前处于上线模式。请按顺序执行:\n"
    f"1. 运行测试命令 `{RUN_TEST_CMD}`(用 run_command;沙箱内缺依赖就先安装)。若项目还没有测试,先编写最小可用的测试(如 pytest)再运行。\n"
    f"2. 测试失败则修复后重跑,直到全部通过。\n"
    f"3. 测试通过后生成:\n"
    f"   - docs/deploy-toB.md:企业部署文档(环境要求、依赖、构建方式、Docker 镜像打包与发布流程、部署步骤、配置项、升级与回滚);\n"
    f"   - docs/usage-toC.md:最终用户文档(安装、快速开始、功能与命令说明、常见问题);\n"
    f"   - 必要时补充 Dockerfile 与 .dockerignore,并写明镜像构建/打包命令。\n"
    f"4. 完成后汇报生成的文件清单。不要删除或覆盖用户已有的无关文件。"
)
DOCS_INSTRUCTIONS = (
    "当前处于文档生成模式。请生成:\n"
    "- docs/deploy-toB.md:企业部署文档(环境要求、依赖、构建方式、Docker 镜像打包与发布流程、部署步骤、配置项、升级与回滚);\n"
    "- docs/usage-toC.md:最终用户文档(安装、快速开始、功能与命令说明、常见问题);\n"
    "- 必要时补充 Dockerfile 与 .dockerignore。\n"
    "完成后汇报生成的文件清单。不要删除或覆盖用户已有的无关文件。"
)
COMMANDS = {
    "/bye": "Quit the agent",
    "/exit": "Exit the agent",
    "/quit": "Quit the agent",
    "/switchmodel": "Switch model, usage: /switchmodel or /switchmodel model-name",
    "/help": "Show all commands",
    "/skills": "List loaded skills",
    "/reload": "Reload skills from disk",
    "/new": "Clear conversation memory (start fresh)",
    "/memories": "List long-term memories",
    "/release": "Release mode: auto test until green, then generate toB/toC docs",
    "/docs": "Generate toB deployment + toC usage docs",
    "/normal": "Exit release/docs mode",
    "/provider": "Switch LLM backend, usage: /provider openai|anthropic",
    "/mcp": "Show MCP servers and tools",
    "/plan": "Plan mode: plan before executing complex tasks",
    "/tasks": "Show task plans and progress",
}


class SlashCompleter(Completer):
    def __init__(self, commands_meta):
        self.commands_meta = commands_meta

    def get_completions(self, document, complete_event):
        text = document.text_before_cursor
        if text.startswith("/"):
            for command, meta in self.commands_meta.items():
                if command.startswith(text):
                    yield Completion(command, start_position=-len(text), display_meta=meta)


def load_skills():
    tools, name = skill.load_dir(SKILLS_DIR)
    return skill.load_default_functions() + tools + mcp_client.manager.tools, name


def run_func(fargs: dict) -> str:
    """执行 run_func:加载脚本并调用函数(参数键名与 default.function.json 一致)"""
    filetype = fargs.get("filetype")
    script = fargs.get("script")
    func = fargs.get("function")
    args = fargs.get("args") or {}
    if filetype == "python":
        spec = ilib.spec_from_file_location("ai_module", script)
        mod = ilib.module_from_spec(spec)
        spec.loader.exec_module(mod)
        target = getattr(mod, func)
        result = target(**args) if isinstance(args, dict) else target(*args)
        return str(result) if result is not None else "执行完成"
    if filetype == "javascript":
        import execjs
        with open(script) as f:
            code = f.read()
        compiled = execjs.compile(code)
        result = compiled.call(func, **args) if isinstance(args, dict) else compiled.call(func, *args)
        return str(result)
    if filetype == "shell":
        import shlex
        import subprocess
        proc = subprocess.run(shlex.split("source " + script))
        return f"shell 执行完成, 退出码 {proc.returncode}"
    raise ValueError(f"不支持的 filetype: {filetype}")


def run_skill(tool_name: str, namedict: dict) -> str:
    """allow_<skill> 工具:返回 SKILL.md 正文 + 脚本绝对路径(供 run_func 执行)"""
    key = tool_name[len("allow_"):]
    original = namedict.get(key, key)
    path = Path(SKILLS_DIR) / original / "SKILL.md"
    if not path.exists():
        return f"未找到 skill: {original}"
    md = skill.load_skill(str(path))
    content = md["content"]
    scripts = md.get("scripts") or []
    if scripts:
        lines = "\n".join(f"- {path.parent / 'scripts' / s}" for s in scripts)
        content += f"\n\n[脚本文件,用 run_func 在宿主机执行,不要用 find 找]\n{lines}"
    return content


# ============ TUI 组件 ============

output_buffer = Buffer()
input_queue = queue.Queue()
approval_queue = queue.Queue()
awaiting_approval = [False]
app_running = [False]
output_lines = []          # 与输出 Buffer 行一一对应的 [(style, text), ...] 片段
_md_block_start = None     # 当前流式回答块的起始行号

_PT_ALLOWED = {"bold", "italic", "underline", "blink", "reverse", "hidden", "strike", "dim"}
_PT_COLORS = {
    "black", "red", "green", "yellow", "blue", "magenta", "cyan", "white",
    "ansiblack", "ansired", "ansigreen", "ansiyellow", "ansiblue",
    "ansimagenta", "ansicyan", "ansiwhite",
}


def _pt_style(rich_style) -> str:
    """rich Style -> prompt_toolkit style 字符串(未知 token 丢弃)"""
    s = str(rich_style or "")
    if s in ("", "none"):
        return ""
    toks = []
    parts = s.split()
    i = 0
    while i < len(parts):
        t = parts[i]
        if t in _PT_ALLOWED:
            toks.append(t)
        elif t == "on" and i + 1 < len(parts):
            toks.append("bg:" + parts[i + 1])
            i += 1
        elif t in _PT_COLORS:
            toks.append("fg:" + t)
        i += 1
    return " ".join(toks)


def render_markdown_lines(text: str) -> list:
    """用 rich 渲染 markdown,把 Segment 转成按行划分的 prompt_toolkit 片段列表"""
    try:
        width = app.output.get_size().columns - 1
    except Exception:
        width = 100
    width = max(40, width)
    from rich.console import Console
    from rich.markdown import Markdown

    console = Console(width=width, force_terminal=False, color_system="truecolor")
    lines = []
    cur = []
    for seg in Markdown(text).__rich_console__(console, console.options):
        style = _pt_style(seg.style)
        parts = seg.text.split("\n")
        for i, part in enumerate(parts):
            if i > 0:
                lines.append(cur)
                cur = []
            if part:
                cur.append((style, part))
    if cur:
        lines.append(cur)
    # 去掉每行尾部空白(rich 会用空格补齐行宽)
    out = []
    for ln in lines:
        if ln:
            st, t = ln[-1]
            out.append(ln[:-1] + [(st, t.rstrip())])
        else:
            out.append(ln)
    return out


class OutputLexer(Lexer):
    """把 output_lines 的样式片段按行交给 BufferControl 渲染"""

    def lex_document(self, document):
        def get_line(lineno):
            if lineno < len(output_lines):
                return output_lines[lineno]
            return []
        return get_line


def _rebuild_output():
    """按 output_lines 重建 Buffer 文本(光标置末尾,保持贴底)"""
    while output_lines and not output_lines[-1]:
        output_lines.pop()
    text = "\n".join("".join(t for _, t in line) for line in output_lines)
    output_buffer.set_document(Document(text, len(text)))
    if app_running[0]:
        app.invalidate()


def append_output(text: str):
    """追加纯文本行(状态/命令输出等)"""
    if not text:
        return
    for line in text.split("\n"):
        output_lines.append([("", line)])
    _rebuild_output()


def start_md_block():
    """开始一个流式回答块(记录起始行)"""
    global _md_block_start
    _md_block_start = len(output_lines)


def finish_md_block(md_text: str):
    """回答块结束:用 rich 整体渲染替换流式期间的纯文本行"""
    global _md_block_start
    if _md_block_start is None:
        return
    start = _md_block_start
    _md_block_start = None
    if md_text.strip():
        output_lines[start:] = render_markdown_lines(md_text)
    else:
        del output_lines[start:]
    _rebuild_output()


def append_output(text: str):
    """把文本追加到输出区(业务线程可调用)"""
    if not text:
        return
    output_buffer.insert_text(text + "\n")
    if app_running[0]:
        app.invalidate()


def ask_approval(prompt_text: str) -> bool:
    """在 UI 内请求审批,返回用户是否批准"""
    append_output(prompt_text)
    awaiting_approval[0] = True
    app.invalidate()
    ans = approval_queue.get().strip().lower()
    return ans in {"y", "yes"}


def chat_round(messages: list, tools: list):
    """发起一次流式补全,内容实时写入输出区。
    返回 (assistant_msg, 文本):若模型要求调用工具,assistant_msg 含完整 tool_calls;否则为 None。"""
    resp = provider.create(messages, tools, model)
    tool_calls = []
    buf = ""
    pending = ""
    start_md_block()

    def flush():
        nonlocal pending
        if pending:
            append_output(pending)
            pending = ""

    for ev in resp:
        if ev.get("notice"):
            flush()
            append_output("⚠ " + ev["notice"])
            start_md_block()   # 提示之后的内容属于新的回答块
            continue
        content = ev.get("content")
        if content:
            buf += content
            pending += content
            if len(pending) >= 30:
                flush()
        tc = ev.get("tool_calls")
        if tc is None:
            continue
        flush()
        idx = tc["index"]
        while len(tool_calls) <= idx:
            tool_calls.append({"id": None, "name": None, "arguments": ""})
        if tc.get("id"):
            tool_calls[idx]["id"] = tc["id"]
        if tc.get("name"):
            tool_calls[idx]["name"] = tc["name"]
        if tc.get("arguments"):
            tool_calls[idx]["arguments"] += tc["arguments"]
    flush()
    finish_md_block(buf)
    if not tool_calls:
        return None, buf
    return (
        {
            "role": "assistant",
            "content": buf or None,
            "tool_calls": [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in tool_calls
            ],
        },
        buf,
    )


def execute_tool(tc: dict, namedict: dict) -> str:
    """执行单个工具调用,异常统一捕获,返回给模型的文本结果"""
    name = tc["function"]["name"]
    raw = tc["function"]["arguments"]
    try:
        fargs = json.loads(raw) if raw.strip() else {}
        if name == "knowledge_search":
            import rag
            results = rag.search(fargs.get("query", ""), int(fargs.get("top_k", 5)))
            return json.dumps(results, ensure_ascii=False)
        if name == "remember":
            import memory
            fact = fargs.get("fact", "")
            if not fact:
                raise ValueError("remember 的 fact 参数不能为空")
            memory.remember(fact)
            return f"已记住:{fact}"
        if name == "recall_memory":
            import memory
            return memory.recall(fargs.get("query", ""), int(fargs.get("top_k", 5)))
        if name == "run_command":
            command = fargs.get("command", "")
            reason = fargs.get("reason", "")
            if not command:
                raise ValueError("run_command 的 command 参数不能为空")
            if not ask_approval(
                f"Agent 请求执行命令:\n  $ {command}\n原因: {reason}\n批准? [y/N]"
            ):
                return f"用户拒绝了执行命令: {command}"
            import runner
            result = runner.run_command(command, fargs.get("cwd"))
            out = (result["output"] or "").strip()
            return f"退出码: {result['returncode']}\n{out}" if out else f"退出码: {result['returncode']}"
        if name == "web_search":
            import search
            return search.web_search(fargs.get("query", ""), int(fargs.get("top_n", 5)))
        if name == "fetch_url":
            import search
            return search.fetch_url(fargs.get("url", ""), int(fargs.get("max_chars", 6000)))
        if name == "read_file":
            path = fargs.get("path", "")
            if not path:
                raise ValueError("read_file 的 path 参数不能为空")
            p = Path(path).expanduser()
            if not p.is_absolute():
                p = ROOT / p
            if not p.exists():
                return f"文件不存在: {p}"
            text = p.read_text(encoding="utf-8", errors="replace")
            lines = text.splitlines()
            return f"[{len(lines)} 行 / {len(text)} 字符]\n{text[:8000]}"
        if name == "write_file":
            path = fargs.get("path", "")
            content = fargs.get("content", "")
            if not path:
                raise ValueError("write_file 的 path 参数不能为空")
            p = Path(path).expanduser()
            if not p.is_absolute():
                p = ROOT / p
            preview = content[:200].replace("\n", "\\n")
            if not ask_approval(
                f"Agent 请求写入文件: {p}\n内容预览: {preview}...\n批准? [y/N]"
            ):
                return f"用户拒绝写入: {p}"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content, encoding="utf-8")
            return f"已写入 {p} ({len(content)} 字符)"
        if name.startswith("mcp_"):
            return mcp_client.manager.call_tool(name, fargs)
        if name == "create_plan":
            import planner
            plan = planner.create_plan(fargs.get("title", ""), fargs.get("steps", []))
            return json.dumps(plan, ensure_ascii=False)
        if name == "update_step":
            import planner
            plan = planner.update_step(
                int(fargs.get("plan_id", 0)), int(fargs.get("seq", -1)), fargs.get("status", "")
            )
            return json.dumps(plan, ensure_ascii=False)
        if name == "get_plan":
            import planner
            plan = planner.get_plan(int(fargs.get("plan_id", 0)))
            return json.dumps(plan, ensure_ascii=False) if plan else "计划不存在"
        if name == "complete_plan":
            import planner
            plan = planner.complete_plan(int(fargs.get("plan_id", 0)))
            return f"计划 {plan['plan_id']} 已完成,共 {len(plan['steps'])} 步"
        if name == "run_func":
            return run_func(fargs)
        if name.startswith("allow_"):
            return run_skill(name, namedict)
        return f"未知工具: {name}"
    except Exception as e:
        logging.exception("工具 %s 执行失败", name)
        return f"工具 {name} 执行失败: {e}"


def plan_window_render():
    try:
        import planner
        return "\n".join(planner.plan_lines())
    except Exception:
        return ""


def handle_input(text: str) -> bool:
    """处理一行用户输入;返回 False 表示退出"""
    global provider, model, release_mode, planning_mode, mode_instruction
    cont = text.strip()
    if not cont:
        return True
    if cont in ("/bye", "/exit", "/quit"):
        return False
    if cont == "/help":
        append_output("可用命令:")
        for cmd, meta in COMMANDS.items():
            append_output(f"  {cmd} - {meta}")
        return True
    if cont == "/skills":
        _, namedict = load_skills()
        append_output("已加载 skills: " + ", ".join(namedict) if namedict else "没有 skills")
        return True
    if cont == "/reload":
        skill.check_skills(SKILLS_DIR)
        load_skills()
        append_output("Skills reloaded")
        return True
    if cont == "/new":
        history.clear()
        append_output("会话记忆已清空")
        return True
    if cont == "/memories":
        try:
            import memory
            items = memory.list_memories()
            append_output("暂无长期记忆" if not items else "长期记忆:")
            for m in items:
                append_output(f"  [{m['id']}] {m['content']} ({m['created_at']})")
        except Exception as e:
            append_output(f"读取记忆失败: {e}")
        return True
    if cont == "/mcp":
        servers = mcp_client.manager.config.get("servers", {})
        if not servers:
            append_output("未配置 MCP 服务器(mcp_servers.json)")
        else:
            for name in servers:
                status = "已连接" if name in mcp_client.manager.sessions else "未连接"
                transport = servers[name].get("type", "stdio")
                append_output(f"MCP {name} ({transport}) - {status}")
            append_output(f"MCP 工具数: {len(mcp_client.manager.tools)}")
        for e in mcp_client.manager.errors:
            append_output(f"  {e}")
        return True
    if cont == "/plan":
        planning_mode = True
        mode_instruction = PLANNING_INSTRUCTIONS
        append_output("任务规划模式开启:先拆解计划,再逐步执行")
        return True
    if cont == "/tasks":
        try:
            import planner
            plans = planner.list_plans()
            if not plans:
                append_output("暂无进行中的计划")
            else:
                for p in plans:
                    append_output(f"计划 {p['plan_id']}: {p['title']} - {p['done']}/{p['total']} 完成")
                    detail = planner.get_plan(p["plan_id"])
                    for s in detail["steps"]:
                        mark = {"pending": "○", "in_progress": "◐", "done": "●", "blocked": "×"}.get(s["status"], "?")
                        append_output(f"  {mark} [{s['seq']}] {s['description']} - {s['status']}")
        except Exception as e:
            append_output(f"读取计划失败: {e}")
        return True
    if cont == "/release":
        release_mode = True
        mode_instruction = RELEASE_INSTRUCTIONS
        append_output("上线模式开启:自动测试直到通过,并生成 toB/toC 文档")
        return True
    if cont == "/docs":
        release_mode = True
        mode_instruction = DOCS_INSTRUCTIONS
        append_output("文档生成模式开启:生成 toB 部署文档与 toC 使用文档")
        return True
    if cont == "/normal":
        release_mode = False
        planning_mode = False
        mode_instruction = ""
        append_output("已退出上线/文档模式")
        return True
    if cont.startswith("/switchmodel"):
        parts = cont.split(" ", maxsplit=1)
        model = parts[1].strip() if len(parts) > 1 else input("New model name:")
        append_output(f"已切换到模型: {model}")
        return True
    if cont.startswith("/provider"):
        parts = cont.split(" ", maxsplit=1)
        name = parts[1].strip() if len(parts) > 1 else ""
        if name in {"openai", "anthropic"}:
            provider = llm.get_provider(name)
            append_output(f"已切换到 {name} 后端")
        else:
            append_output(f"当前后端: {llm.LLM_PROVIDER};用法: /provider openai|anthropic")
        return True
    if cont.startswith("/") and cont.split()[0] not in COMMANDS:
        append_output(f"未知命令: {cont.split()[0]},输入 /help 查看可用命令")
        return True
    # 对话轮次
    tools, namedict = load_skills()
    rounds = MAX_RELEASE_ROUNDS if (release_mode or planning_mode) else MAX_TOOL_ROUNDS
    system_prompt = SYSTEM_PROMPT + (f"\n{mode_instruction}" if mode_instruction else "")
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": cont}]
    append_output(f"\n[You] {cont}")
    final_text = ""
    for _ in range(rounds):
        assistant_msg, buf = chat_round(messages, tools)
        if buf:
            final_text = buf
        if assistant_msg is None:
            break
        messages.append(assistant_msg)
        for tc in assistant_msg["tool_calls"]:
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": execute_tool(tc, namedict)})
    else:
        append_output("⚠ 工具调用轮次过多,已停止")
    history.append({"role": "user", "content": cont})
    if final_text:
        history.append({"role": "assistant", "content": final_text})
    while sum(len(m.get("content") or "") for m in history) > MAX_HISTORY_CHARS and len(history) > 2:
        history.pop(0)
        history.pop(0)
    return True


def business_loop():
    """后台线程:从输入队列取用户消息并处理"""
    while True:
        text = input_queue.get()
        if text is None:
            break
        try:
            if not handle_input(text):
                break
        except Exception as e:
            logging.exception("处理输入失败")
            append_output(f"错误: {e}")
    append_output("Agent 已退出")
    app.exit()


def on_accept(buff: Buffer):
    """输入框回车:审批模式下只收 y/N,否则进入业务队列"""
    text = buff.text.strip()
    buff.reset()
    if not text:
        return
    if awaiting_approval[0]:
        awaiting_approval[0] = False
        approval_queue.put(text)
        return
    input_queue.put(text)


plan_window = Window(
    content=FormattedTextControl(plan_window_render),
    height=D(max=8),
    style="bg:ansiblue",
)
output_window = Window(
    content=BufferControl(buffer=output_buffer, focusable=False, lexer=OutputLexer()),
    wrap_lines=True,
    always_hide_cursor=True,
    right_margins=[ScrollbarMargin()],
)
input_buffer = Buffer(
    multiline=False,
    completer=SlashCompleter(COMMANDS),
    history=FileHistory(str(ROOT / ".agent_history")),
    accept_handler=on_accept,
    complete_while_typing=True,
)
input_window = Window(content=BufferControl(buffer=input_buffer), height=1)

kb = KeyBindings()


@kb.add(Keys.ScrollUp)
def _scroll_up(event):
    output_window._scroll_up()
    app.invalidate()


@kb.add(Keys.ScrollDown)
def _scroll_down(event):
    output_window._scroll_down()
    app.invalidate()


@kb.add("c-c")
def _exit(event):
    event.app.exit()


bindings = merge_key_bindings([kb, load_key_bindings()])

root_container = FloatContainer(
    HSplit([plan_window, output_window, input_window]),
    floats=[
        Float(
            xcursor=True,
            ycursor=True,
            content=Window(content=CompletionsMenuControl()),
        ),
    ],
)
app = Application(
    layout=Layout(root_container, focused_element=input_buffer),
    key_bindings=bindings,
    mouse_support=True,
    full_screen=True,
)

if __name__ == "__main__":
    append_output("[Agent] 已启动,输入 /help 查看命令")
    threading.Thread(target=business_loop, daemon=True).start()
    app_running[0] = True
    app.run()
    app_running[0] = False
