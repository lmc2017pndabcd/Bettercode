# syntax=docker/dockerfile:1
# ------------------------------------------------------------------
# 企业部署镜像:CLI Agent + RAG 知识库(配套 PostgreSQL 17 + pgvector)
# 构建: docker build -t <registry>/<repo>/agent:latest .
# ------------------------------------------------------------------
FROM python:3.12-slim AS base

WORKDIR /app

# 系统级依赖(psycopg[binary] 自带二进制,无需 libpq-dev;此处保持精简)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# 先拷贝依赖清单,利用 Docker 层缓存
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用源码与默认工具函数
COPY src/ ./src/
COPY default.function.json ./
# RAG 依赖 .env,但密钥不入镜像:通过 -e / 挂载注入
COPY .env.example ./.env.example

# 使用非 root 运行(最小权限原则)
RUN useradd --create-home --uid 1000 appuser
USER appuser

# 默认命令:进入交互式 agent
CMD ["python", "src/main.py"]
