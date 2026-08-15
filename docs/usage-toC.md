# 使用文档(ToC)

> 面向终端用户,介绍 **本地 AI 助手 CLI** 的安装、快速开始、功能 / 命令与常见问题。
> 这是一个基于 DeepSeek 的 AI 助手,具备 **本地知识库问答(RAG)**、**长期记忆** 与 **命令执行** 能力。

---

## 1. 简介

本助手是一个运行在终端(命令行)的 AI 工具,你可以:

- 与 AI 对话,回答你提出的问题;
- 让它检索你的本地知识库(把资料文档入库后,可基于资料回答);
- 让它记住重要信息,并在后续对话中回忆起来;
- 在受控的沙箱环境中替你执行命令(构建、测试、查看环境等)。

---

## 2. 环境要求

- Python 3.12+
- PostgreSQL 17(可选,RAG 知识库功能需要)
- 一个 DeepSeek(或 OpenAI 兼容)API Key

---

## 3. 安装

### 3.1 获取代码与安装依赖

```bash
git clone <你的仓库地址> my-agent
cd my-agent

# 创建虚拟环境(推荐)
python3.12 -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -r requirements.txt
```

### 3.2 配置

```bash
cp .env.example .env
```

编辑 `.env`,至少填写两个必填项:

```env
OPENAI_API_KEY=sk-你的真实Key
DATABASE_URL=postgresql://postgres:postgres@localhost:5432/rag_kb
```

> `OPENAI_API_KEY` 是大模型的密钥;`DATABASE_URL` 是知识库存放位置(可选,不用 RAG 可暂不配置)。

---

## 4. 快速开始

### 4.1 启动助手

```bash
python src/main.py
```

启动时按提示输入:
1. **API Key**(可与 `.env` 中一致,直接回车使用配置项);
2. **模型名称**(如 `deepseek-chat`)。

看到输入提示符后即可开始对话。输入 `exit` 或 `Ctrl+D` 退出。

### 4.2 第一次用知识库(可选)

先帮你把资料文档“喂”给助手:

```bash
# 把一个文件或一个文件夹(自动递归)做成知识库
python src/rag.py ingest ./我的资料.md
python src/rag.py ingest ./docs/

# 查看库里有多少内容
python src/rag.py stats
```

然后回到对话,直接问资料相关问题,助手会自动检索并基于本地资料回答。

---

## 5. 常用功能

### 5.1 普通对话

直接输入问题即可,例如:

```
帮我总结一下最近的会议记录
```

### 5.2 知识库问答(RAG)

把资料入库后,提问会自动触发 `knowledge_search` 检索,回答会引用来源片段。

```bash
# 单独调试检索+回答(不走对话界面)
python src/rag.py ask "公司成立时间是什么时候"
```

### 5.3 长期记忆

- 告诉助理重要信息,它会调用 `remember` 记住;
- 之后相关问题会自动调用 `recall_memory` 回忆;
- 用 `/memories` 查看已记住的信息。

```
我的生日是 6 月 1 日。        # 让助手记住
我的生日是哪天?              # 之后这样问即可
```

### 5.4 命令执行(沙箱)

```bash
帮我跑一下测试
查看当前环境
```

助手会展示要执行的命令,需你**确认后才会执行**,结果反馈给你。执行环境默认是隔离的一次性 Docker 容器。

---

## 6. 命令一览

对话中输入斜杠命令:

| 命令 | 作用 |
| --- | --- |
| `/help` | 显示所有命令帮助 |
| `/new` | 清空当前对话记忆,重新开始 |
| `/memories` | 列出长期记忆 |
| `/skills` | 列出已加载的 skills |
| `/reload` | 重新加载 skills |
| `/switchmodel` | 切换模型(不接参数会列出可选) |
| `/bye` / `/exit` / `/quit` | 退出助手 |
| `/release` | 上线模式:自动跑测试并生成部署/使用文档 |
| `/docs` | 只生成 toB/toC 文档 |
| `/normal` | 退出上线/文档模式 |

---

## 7. 知识库管理命令

在**终端**(非对话界面)用 `src/rag.py` 管理知识库:

```bash
python src/rag.py ingest <文件或目录>   # 入库(同源会先删旧再写新)
python src/rag.py ask "问题"            # 检索 + 大模型生成回答
python src/rag.py stats                 # 查看统计(文档数 / chunk 数)
python src/rag.py clear                 # 清空全部知识库(会二次确认)
```

---

## 8. 常见问题(FAQ)

### Q1: 一定要配 PostgreSQL 才能用吗?
知识库(RAG)功能需要 PostgreSQL 17 + pgvector。如果只想普通对话,可以暂不配置,但知识库相关命令会报错。

### Q2: 提示数据库连不上?
检查 `DATABASE_URL` 是否正确、PostgreSQL 服务和端口是否启动、账号密码是否有误。参见部署文档第 7 节。

### Q3: 回答时总是没有本地资料?
确认已执行过 `ingest`,且提问内容与资料相关;可用 `python src/rag.py stats` 确认库里有内容,再用 `ask` 单独调试。

### Q4: 第一次运行时下载模型很慢 / 失败?
首次使用本地 embedding 模型会自动从 HuggingFace 下载(约 100MB)。网络受限时在 `.env` 加:

```env
HF_ENDPOINT=https://hf-mirror.com
HF_HUB_DISABLE_XET=1
```

### Q5: 让我执行命令安全吗?
默认在 `RUN_SANDBOX=docker` 的一次性隔离容器中执行,且**每一条命令都要你审批**后才运行,不会静默执行。

### Q6: 助手“忘事”怎么办?
记忆分两种:`/new` 只清当前对话;长期记忆用 `/memories` 查看,若想清空可删除记忆文件(`~/.bettercode/` 下的记忆存储)。

### Q7: 如何关闭某个功能?
无需用到 RAG / 记忆 / 沙箱时,可直接不提问相关场景;对应能力由模型按需调用,不会强制运行。

---

## 9. 隐私说明

- 你的 `OPENAI_API_KEY` 只在本地保存,仅用于调用大模型接口;
- 知识库与长期记忆均存储在本地(PostgreSQL / `~/.bettercode`),不会自动上传;
- 命令执行需要你逐条确认。
