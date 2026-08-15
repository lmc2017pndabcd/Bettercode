# 上线 / 文档生成模式

## run_command 工具

- 注册在 `default.function.json`，agent 需要实际操作（构建、测试、装依赖、写文件、查环境）时调用。
- **用户审批**：执行前在终端展示命令与原因，输入 `y` 才执行，否则返回"用户拒绝"。
- **沙箱**：`RUN_SANDBOX=docker`（默认）在一次性容器中执行（挂载项目目录，宿主隔离，pip 缓存走 `pip-cache` 卷）；`RUN_SANDBOX=local` 在本机执行（优先用项目 `.venv`）。
- 超时 `RUN_TIMEOUT`（默认 120s），输出截断 `RUN_MAX_OUTPUT`（默认 8000 字符），超时/异常转成可读结果返回，不崩溃。

## 指令

- `/release`：上线模式。agent 依次：跑测试（`RUN_TEST_CMD`，默认 `make test`；没有测试就先写最小 pytest）→ 失败修复重跑直到全绿 → 生成 `docs/deploy-toB.md`（企业部署：环境、依赖、构建、Docker 镜像打包/发布、部署、配置、升级回滚）与 `docs/usage-toC.md`（用户文档：安装、快速开始、功能命令、FAQ），必要时补 `Dockerfile`/`.dockerignore`。工具轮次上限默认 50（可用 `MAX_RELEASE_ROUNDS` 调整）。
- `/docs`：只生成 toB/toC 文档，不跑测试。
- `/normal`：退出上线/文档模式。

## 配置（`.env`）

```env
RUN_SANDBOX=docker            # docker | local
RUN_TIMEOUT=120
RUN_TEST_CMD=make test
RUN_DOCKER_IMAGE=python:3.12-slim
RUN_MAX_OUTPUT=8000
MAX_TOOL_ROUNDS=30
MAX_RELEASE_ROUNDS=50
```

## 说明

- Docker 沙箱是一次性的：容器内 `pip install` 的依赖不会持久化（pip 下载缓存会保留），每次运行需重新安装；需要持久依赖或不想用 Docker 时把 `RUN_SANDBOX` 改为 `local`。
- 审批是唯一的人为闸门；`local` 模式下请只批准你确认安全的命令。
- 国内网络下 `docker.io` 直连不通：先 `docker pull docker.m.daocloud.io/library/python:3.12-slim && docker tag docker.m.daocloud.io/library/python:3.12-slim python:3.12-slim`，之后沙箱即可用本地标签，无需每次走公网。
