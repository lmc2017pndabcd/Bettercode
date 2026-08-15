#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#mcp_client.py - MCP(Model Context Protocol)客户端:连接 stdio/http/sse MCP 服务器并合并工具
import asyncio
import json
import os
import re
import threading
import time
import traceback
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

_env_cfg = os.getenv("MCP_CONFIG", "").strip()
CONFIG_PATHS = ([Path(_env_cfg)] if _env_cfg else []) + [
    ROOT / "mcp_servers.json",
    Path.home() / ".bettercode" / "mcp.json",
]

_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _expand_env(value):
    """把字符串里的 ${VAR} 替换成环境变量值,支持嵌套在 url/headers/env/args 中。"""
    if isinstance(value, str):
        return _ENV_PATTERN.sub(lambda m: os.getenv(m.group(1), m.group(0)), value)
    if isinstance(value, list):
        return [_expand_env(v) for v in value]
    if isinstance(value, dict):
        return {k: _expand_env(v) for k, v in value.items()}
    return value


class MCPManager:
    """管理 stdio/http/sse MCP 服务器连接、工具注册与调用(后台线程 + 独立事件循环)"""

    def __init__(self):
        self.config = {}
        self.sessions = {}   # 服务器名 -> ClientSession
        self.tools = []      # OpenAI tools 格式
        self.tool_map = {}   # mcp_<server>_<tool> -> (server, 工具原名)
        self.errors = []
        self.loop = None

    def load_config(self):
        for p in CONFIG_PATHS:
            if p.exists():
                try:
                    self.config = json.loads(p.read_text(encoding="utf-8"))
                except Exception as e:
                    self.errors.append(f"配置解析失败 {p}: {e}")
                    self.config = {}
                break
        return self.config.get("servers", {})

    def start(self, wait_timeout: int = 8):
        servers = self.load_config()
        if not servers:
            return
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run, daemon=True).start()
        # 等待服务器连接就绪,保证第一轮对话就能看到 MCP 工具
        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            if len(self.sessions) >= len(servers):
                break
            time.sleep(0.2)

    def _run(self):
        asyncio.set_event_loop(self.loop)
        self.loop.run_until_complete(self._connect_all())
        self.loop.run_forever()

    async def _connect_all(self):
        servers = self.config.get("servers", {})
        for name, cfg in servers.items():
            asyncio.create_task(self._connect_one(name, cfg))
        for _ in range(20):
            if len(self.sessions) >= len(servers):
                break
            await asyncio.sleep(1)

    async def _connect_one(self, name, cfg):
        from mcp import ClientSession

        try:
            transport = cfg.get("type", "stdio")
            if transport == "http":
                # Streamable HTTP:可携带 Authorization 等自定义请求头
                import httpx2
                from mcp.client.streamable_http import streamable_http_client

                url = _expand_env(cfg.get("url", ""))
                headers = _expand_env(cfg.get("headers") or {})
                http_client = httpx2.AsyncClient(headers=headers) if headers else None
                cm = streamable_http_client(url, http_client=http_client)
            elif transport == "sse":
                from mcp.client.sse import sse_client

                url = _expand_env(cfg.get("url", ""))
                headers = _expand_env(cfg.get("headers") or {})
                cm = sse_client(url, headers=headers)
            else:
                # stdio(默认):启动子进程,command/args/env 支持 ${VAR} 展开
                from mcp import StdioServerParameters
                from mcp.client.stdio import stdio_client

                params = StdioServerParameters(
                    command=_expand_env(cfg.get("command", "python")),
                    args=_expand_env(cfg.get("args", [])),
                    env=_expand_env(cfg.get("env")),
                )
                cm = stdio_client(params)

            async with cm as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    res = await session.list_tools()
                    for t in res.tools:
                        fname = f"mcp_{name}_{t.name}"
                        self.tool_map[fname] = (name, t.name)
                        self.tools.append(
                            {
                                "type": "function",
                                "function": {
                                    "name": fname,
                                    "description": t.description or f"MCP 工具 {name}.{t.name}",
                                    "parameters": t.input_schema
                                    or {"type": "object", "properties": {}},
                                },
                            }
                        )
                    self.sessions[name] = session
                    await asyncio.Event().wait()  # 保持连接直到进程退出
        except Exception as e:
            self.errors.append(f"{name}: {e}\n{traceback.format_exc()}")

    def call_tool(self, tool_name: str, args: dict) -> str:
        if tool_name not in self.tool_map:
            return f"未知 MCP 工具: {tool_name}"
        server, tool = self.tool_map[tool_name]

        async def _call():
            session = self.sessions.get(server)
            if session is None:
                return f"MCP 服务器 {server} 未连接: {'; '.join(self.errors) or '未知原因'}"
            try:
                result = await session.call_tool(tool, arguments=args or {})
                texts = []
                for block in result.content or []:
                    btype = getattr(block, "type", None)
                    if btype == "text":
                        texts.append(getattr(block, "text", ""))
                    elif btype == "image":
                        texts.append(
                            f"[图片 {getattr(block, 'mimeType', '?')} "
                            f"{len(getattr(block, 'data', b''))} bytes]"
                        )
                    else:
                        texts.append(str(block))
                return "\n".join(texts) if texts else f"(空结果 isError={result.isError})"
            except Exception as e:
                return f"MCP 工具调用失败: {e}"

        if self.loop is None:
            return "MCP 未启动"
        try:
            return asyncio.run_coroutine_threadsafe(_call(), self.loop).result(timeout=60)
        except Exception as e:
            return f"MCP 调用超时/失败: {e}"


manager = MCPManager()
