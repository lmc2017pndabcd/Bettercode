#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#runner.py - 安全命令执行:沙箱(默认 docker)+ 超时 + 输出截断;审批在 main.py 层做
import os
import shlex
import subprocess
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

RUN_SANDBOX = os.getenv("RUN_SANDBOX", "docker")        # docker | local
RUN_TIMEOUT = int(os.getenv("RUN_TIMEOUT", "120"))
RUN_DOCKER_IMAGE = os.getenv("RUN_DOCKER_IMAGE", "python:3.12-slim")
MAX_OUTPUT_CHARS = int(os.getenv("RUN_MAX_OUTPUT", "8000"))
SKILLS_DIR = os.path.expanduser("~/.bettercode")


def run_command(command: str, cwd: str = None, timeout: int = RUN_TIMEOUT) -> dict:
    """执行命令,返回 {status, returncode, output};异常/超时不抛出,转成可读结果"""
    cwd = cwd or str(ROOT)
    if RUN_SANDBOX == "docker":
        return _run_docker(command, cwd, timeout)
    return _run_local(command, cwd, timeout)


def _run_local(command: str, cwd: str, timeout: int) -> dict:
    """本机直接执行:优先使用项目 .venv 的 Python/工具,结果截断"""
    env = dict(os.environ)
    venv_bin = ROOT / ".venv" / "bin"
    env["PATH"] = f"{venv_bin}:{env.get('PATH', '')}"
    try:
        proc = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = (proc.stdout or "")
        if proc.stderr:
            output += f"\n[stderr]\n{proc.stderr}"
        return {
            "status": "ok",
            "returncode": proc.returncode,
            "output": output[-MAX_OUTPUT_CHARS:],
        }
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "returncode": -1,
            "output": f"命令执行超时({timeout}s)",
        }
    except Exception as e:
        return {"status": "error", "returncode": -1, "output": str(e)}


def _run_docker(command: str, cwd: str, timeout: int) -> dict:
    """Docker 沙箱执行:挂载工作目录与宿主技能目录,容器用完即删,宿主隔离"""
    cmd = (
        f"docker run --rm "
        f"-v {shlex.quote(str(cwd))}:/workspace -w /workspace "
        f"-v {shlex.quote(SKILLS_DIR)}:{shlex.quote(SKILLS_DIR)} "
        f"-v {shlex.quote(SKILLS_DIR)}:/root/.bettercode "
        f"-v pip-cache:/root/.cache/pip "
        f"{shlex.quote(RUN_DOCKER_IMAGE)} sh -lc {shlex.quote(command)}"
    )
    return _run_local(cmd, ROOT, timeout)


if __name__ == "__main__":
    import json
    import sys

    if len(sys.argv) < 2:
        print("用法: runner.py <命令>")
        sys.exit(1)
    print(json.dumps(run_command(" ".join(sys.argv[1:])), ensure_ascii=False, indent=2))
