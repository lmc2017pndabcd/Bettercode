# 文件读写与 MCP

## 文件读写工具

- `read_file(path)`：读取文本文件（UTF-8，自动截断到 8000 字符），相对路径基于项目根目录；无需审批。
- `write_file(path, content)`：写入/覆盖文本文件（自动建目录），**写入前需用户在终端审批**（展示路径 + 内容预览）。

## MCP（Model Context Protocol）

agent 启动时自动连接配置里的 MCP 服务器（支持 **stdio / Streamable HTTP / SSE** 三种传输），把服务器工具合并进自己的工具列表：

- 工具命名：`mcp_<服务器名>_<工具名>`，避免与原生工具冲突；
- 会话中 `/mcp` 查看服务器连接状态、工具数与错误；
- 配置优先级：`MCP_CONFIG` 环境变量指定文件 > 项目根 `mcp_servers.json` > `~/.bettercode/mcp.json`。

### 配置格式（`mcp_servers.json`）

```json
{
  "servers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/allowed"]
    },
    "demo": {
      "command": "/path/to/python",
      "args": ["/path/to/mcp_server.py"],
      "env": {"KEY": "VALUE"}
    },
    "feishu": {
      "type": "http",
      "url": "http://localhost:3333/mcp?userKey=${MCP_USER_KEY}",
      "headers": {
        "Authorization": "Bearer ${MCP_BEARER_TOKEN}"
      }
    },
    "sse_demo": {
      "type": "sse",
      "url": "https://example.com/mcp/sse",
      "headers": {"Authorization": "Bearer ${MCP_BEARER_TOKEN}"}
    }
  }
}
```

字段说明：

- `type`：`stdio`（默认）/ `http`（Streamable HTTP）/ `sse`；不写则按 stdio 处理。
- `http` / `sse` 必须提供 `url`；`headers` 可选，用于携带 `Authorization` 等认证头。
- 配置里所有字符串都支持 `${环境变量名}` 展开，密钥（Bearer token、userKey 等）放 `.env` 或环境变量里，**不要提交到 git**。

### 飞书（Lark）文档读取

飞书支持 MCP 的 Streamable HTTP 传输，配合 Bearer token 使用。两种接入方式：

1. **远程 MCP（openable / 飞书开放平台提供的 MCP 端点）**：直接填官方给的 URL，token 放 `headers.Authorization`。
2. **本地 lark-mcp（`@larksuiteoapi/lark-mcp`，需要 app id / secret）**：

   ```bash
   npm i -g @larksuiteoapi/lark-mcp
   mcp -a <APP_ID> -s <APP_SECRET> -m streamable
   ```

   默认监听 `http://localhost:3333/mcp`，`userKey` 是文档访问身份标识，可放在 url 的 query 里。

   配置示例：

   ```json
   {
     "servers": {
       "feishu": {
         "type": "http",
         "url": "http://localhost:3333/mcp?userKey=${MCP_USER_KEY}",
         "headers": {"Authorization": "Bearer ${MCP_BEARER_TOKEN}"}
       }
     }
   }
   ```

   `.env` 里配置 `MCP_USER_KEY` 与 `MCP_BEARER_TOKEN` 后，启动 agent 即可看到 `mcp_feishu_*` 工具，让模型读取/搜索飞书文档。

### 说明

- 使用官方 `mcp` SDK（当前环境为 2.0）。客户端 API 已适配 2.0：工具 schema 属性为 `input_schema`。
- MCP 服务器进程与 agent 同生命周期，在后台线程的事件循环里常驻，启动时最多等待 8 秒确保第一轮对话即可用。
- HTTP/SSE 服务器连接失败会在 `/mcp` 里显示错误详情，不会导致 agent 崩溃。
- 服务器工具需要模型能理解其入参；描述不清晰时可在工具描述里补充用法。
- 安全：MCP 服务器在宿主机上以当前用户权限运行，只连接可信服务器；`write_file`/`run_command` 等写操作仍走审批。
