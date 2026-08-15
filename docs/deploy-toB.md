# 企业部署文档(ToB)

> 本文档面向运维 / 平台工程师,说明如何将 **CLI Agent + RAG 知识库** 部署到企业环境。
> 系统是一个基于 DeepSeek(OpenAI 兼容协议)的本地 AI 助手 CLI,具备知识库检索(RAG)、长期记忆与沙箱命令执行能力。

---

## 1. 系统架构概览

```
┌────────────────────────────────────────────┐
│                调用方 / 终端                 │
└───────────────┬────────────────────────────┘
                │
┌───────────────▼────────────────────────────┐
│                  Agent CLI                 │
│  src/main.py / src/skill.py / src/runner.py │
│  - 工具调度(function calling)               │
│  - remember / recall_memory(长期记忆)       │
│  - run_command(沙箱执行,可选 docker)        │
└───────┬────────────────────────┬───────────┘
        │                        │ OpenAI 兼容协议
        │  SQL / pgvector        ▼
┌───────▼──────────┐   ┌─────────────────────┐
│ PostgreSQL 17    │   │   大模型 API         │
│ + pgvector 扩展   │   │   DeepSeek / 兼容   │
│ (RAG 知识库)      │   └─────────────────────┘
└──────────────────┘
```

| 组件 | 说明 |
| --- | --- |
| Agent CLI | Python 应用,通过 function calling 调用工具 |
| PostgreSQL 17 + pgvector | 存储 RAG 知识库向量数据 |
| 大模型 API | DeepSeek(OpenAI 兼容),提供对话与可选 embedding |
| fastembed | 本地 embedding 模型(`BAAI/bge-small-zh-v1.5`),首次运行自动下载 |

---

## 2. 环境要求

### 2.1 系统 / 运行环境

| 项 | 要求 |
| --- | --- |
| 操作系统 | Linux / macOS(Docker 部署建议 Linux 服务器) |
| Python | 3.12+ |
| PostgreSQL | 17 + `pgvector` 扩展 |
| Docker(可选) | 20.10+(容器化部署时) |
| 内存 | 建议 ≥ 4GB(本地 embedding 模型载入 + 应用) |
| 磁盘 | 建议 ≥ 4GB 空闲(本地 embedding 模型约 100MB + 知识库数据) |
| 网络 | 需可访问所选大模型 API;模型镜像地址可配置 |

### 2.2 软件依赖

`requirements.txt`:

```text
OpenAI
rich
psycopg[binary]
pgvector
fastembed
```

> **说明**:采用轻依赖方案,不引入 torch / LangChain。`psycopg[binary]` 自带二进制驱动,无需系统级 `libpq`。

---

## 3. 基础设施：PostgreSQL + pgvector

### 3.1 安装(Docker 方式)

```yaml
# docker-compose.deps.yml
services:
  postgres:
    image: pgvector/pgvector:pg17
    environment:
      POSTGRES_USER: postgres
      POSTGRES_PASSWORD: postgres
      POSTGRES_DB: rag_kb
    ports:
      - "5432:5432"
    volumes:
      - pgdata:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 10

volumes:
  pgdata:
```

### 3.2 本机安装(Homebrew / 源码)

```bash
# macOS(Homebrew)
brew install postgresql@17
brew install pgvector        # 若 brew formula 可用,否则从源码编译
```

> 应用启动时会**幂等**自动创建数据库 `rag_kb`、`vector` 扩展、`documents` 表与 HNSW 索引,无需手工建表。

---

## 4. 配置项

配置文件为项目根目录 `.env`(部署副本见图). 关键项:

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `OPENAI_BASE_URL` | ✅ | `https://api.deepseek.com/v1` | OpenAI 兼容接口地址(建议写到 `/v1`) |
| `OPENAI_API_KEY` | ✅ | — | 大模型 API 密钥(敏感,勿入库/镜像) |
| `DATABASE_URL` | ✅ | `postgresql://localhost:5432/rag_kb` | PostgreSQL 连接串 |
| `EMBEDDING_PROVIDER` | ❌ | `local` | `local`(fastembed)/ `api`(OpenAI 兼容 embeddings) |
| `EMBEDDING_MODEL` | ❌ | `BAAI/bge-small-zh-v1.5` | embedding 模型名 |
| `VECTOR_DIM` | ❌ | `512` | 向量维度,须与模型一致 |
| `CHUNK_SIZE` / `CHUNK_OVERLAP` | ❌ | `400` / `50` | RAG 切分参数(字符) |
| `RAG_CHAT_MODEL` | ❌ | `deepseek-chat` | `ask` 对话模型 |
| `HF_ENDPOINT` | ❌ | — | HuggingFace 镜像(网络受限时设 `https://hf-mirror.com`) |
| `HF_HUB_DISABLE_XET` | ❌ | — | 禁用 Xet 走普通 HTTP(`1`) |
| `RUN_SANDBOX` | ❌ | `docker` | `docker`(一次性容器)/ `local` |
| `RUN_TIMEOUT` | ❌ | `120` | 沙箱命令超时(秒) |
| `RUN_TEST_CMD` | ❌ | `make test` | 测试命令 |
| `RUN_DOCKER_IMAGE` | ❌ | `python:3.12-slim` | 沙箱镜像 |
| `RUN_MAX_OUTPUT` | ❌ | `8000` | 沙箱输出截断字符数 |

> 配置模板见 `.env.example`。**密钥通过环境变量或 secret 挂载注入,不要写死在镜像/仓库。**

---

## 5. 构建方式

### 5.1 本地 Python 运行

```bash
# 1. 创建虚拟环境
python3.12 -m venv .venv
source .venv/bin/activate

# 2. 安装依赖
pip install -r requirements.txt

# 3. 配置 .env
cp .env.example .env
#    编辑 .env,填写 OPENAI_API_KEY 与 DATABASE_URL

# 4. 启动(交互式)
python src/main.py
```

### 5.2 Docker 镜像构建

```bash
docker build -t <registry>/<repo>/agent:latest .
```

> `.dockerignore` 已排除 `.env`、`.venv`、`docs`、日志与构建产物,避免密钥泄漏与镜像臃肿。

---

## 6. Docker 镜像打包与发布流程

### 6.1 构建 / 打标签

```bash
# 指定版本号与环境
VERSION=1.0.0
docker build -t <registry>/<repo>/agent:${VERSION} .
docker tag <registry>/<repo>/agent:${VERSION} <registry>/<repo>/agent:latest
```

### 6.2 登录私有仓库并推送

```bash
docker login <registry>          # 输入凭据
docker push <registry>/<repo>/agent:${VERSION}
docker push <registry>/<repo>/agent:latest
```

### 6.3 镜像安全检查(建议)

```bash
docker scout cves <registry>/<repo>/agent:${VERSION}   # Docker 内置漏洞扫描
# 或使用第三方扫描器(Trivy / Grype)
```

---

## 7. 部署步骤(Docker Compose 全栈)

创建 `docker-compose.yml`:

```yaml
services:
  postgres:
    image: pgvector/pgvector:pg17
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER:-postgres}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-postgres}
      POSTGRES_DB: rag_kb
    volumes:
      - pgdata:/var/lib/postgresql/data

  agent:
    image: <registry>/<repo>/agent:latest
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-postgres}@postgres:5432/rag_kb
    depends_on:
      postgres:
        condition: service_healthy
    stdin_open: true
    tty: true
    volumes:
      - ./knowledge:/home/appuser/knowledge   # 可选:知识库资料挂载
      - agent_mem:/home/appuser/.bettercode   # 长期记忆 / skills 持久化

volumes:
  pgdata:
  agent_mem:
```

启动:

```bash
docker compose up -d
docker compose logs -f agent
```

> `agent` 为交互式 CLI。生产若要无人值守,可封装入口脚本执行 `ingest`(入库)或 `ask`(批量问答),例如:
> `docker compose exec agent python src/rag.py ingest /home/appuser/knowledge`

---

## 8. 升级与回滚

### 8.1 升级

1. 拉取新镜像并重启:
   ```bash
   docker compose pull agent
   docker compose up -d agent
   ```
2. 若 `VECTOR_DIM` / embedding 模型变更,需**清空并重新 ingest** 知识库(维度不一致无法直接复用向量): `python src/rag.py clear && python src/rag.py ingest <knowledge>`

### 8.2 回滚

```bash
# 回退到上一版本
docker compose down agent
docker compose up -d --no-deps \
  --scale agent=1 agent \
  # 指定旧版本镜像
  # 或直接修改 compose 中 image 为旧 tag 后 up -d
docker compose up -d agent
```

### 8.3 数据库迁移建议

- `documents` 表结构与 HNSW 索引由应用幂等初始化,升级时无需手工 DDL。
- 若向量维度策略变化,建议先备份数据 / 明确重建策略。

---

## 9. 运维要点

| 关注点 | 建议 |
| --- | --- |
| 密钥管理 | `OPENAI_API_KEY` / `DB 密码` 用环境变量 / Vault / secret 注入 |
| 模型下载 | 首次运行自动下载 embedding 模型;受限网络配 `HF_ENDPOINT` |
| 日志 | `agent.log`;生产可用 `docker compose logs` + 集中日志 |
| 沙箱安全 | `RUN_SANDBOX=docker` 提供一次性隔离;`local` 模式仅限可信命令 |
| 健康检查 | 依赖 PostgreSQL `pg_isready`;agent 为交互式进程 |
| 数据持久化 | `pgdata`(向量库)、`agent_mem`(长期记忆)需持久卷 |

---

## 10. 常见部署问题

| 问题 | 排查 |
| --- | --- |
| 连接数据库失败 | 确认 `DATABASE_URL`、pg 服务地址与端口、密码 |
| embedding 模型下载失败 | 设置 `HF_ENDPOINT=https://hf-mirror.com`、`HF_HUB_DISABLE_XET=1` |
| 401 / 404 调用 API | 确认 `OPENAI_BASE_URL` 是否含多余 `/chat/completions` 后缀 |
| 维度不匹配 | 更换模型后确保 `VECTOR_DIM` 与 `EMBEDDING_MODEL` 匹配并重建库 |
