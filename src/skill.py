#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#skill.py
import frontmatter
import json
import os
from pathlib import Path
import importlib.util
import execjs
import inspect

def load_skill(skill_path:str):
    ans = frontmatter.load(skill_path)
    metadata = dict(ans.metadata)
    metadata["content"] = ans.content
    path = Path(skill_path)
    scripts = []
    if (path.parent/"scripts").exists():
        for i in (path.parent/"scripts").glob("*.py"):
            scripts.append(i.name)
        for i in (path.parent/"scripts").glob("*.js"):
            scripts.append(i.name)
        for i in (path.parent/"scripts").glob("*.sh"):
            scripts.append(i.name) 
    metadata["scripts"] = scripts
    return metadata
def load_dir(dir:str)->tuple:
    pth = Path(dir)
    ans = []
    name = dict()
    for md in pth.rglob("SKILL.md"):
        skill_md = load_skill(str(md))
        name[str(skill_md["name"]).replace("-","_")] = str(skill_md["name"])
        ans.append({
            "type":"function",
            "function":{
                "name":"allow_"+skill_md["name"],
                "description":skill_md["description"],
                "parameters":{
                    "type":"object",
                    "properties":{},
                    "required":[]
                }
            }
        })
    return ans,name
def check_skills(dir:str=os.path.expanduser("~/.bettercode/skills")):
    pth = Path(dir)
    for i in pth.rglob("SKILL.md"):
        skill = load_skill(str(i))
        if skill["name"] != i.parent.name:
            with open(str(i),encoding="utf-8")as f:
                text = f.read()
            with open(str(i),"w",encoding="utf-8")as f:
                f.write(text.replace(skill["name"],i.parent.name,1))

def load_default_functions(path:str=None)->list:
    """从项目根目录 default.function.json 读取函数工具定义。

    文件格式: {"funcs": {"函数名": {OpenAI function tool 定义}, ...}}
    返回 OpenAI tools 列表(即 funcs 字典的 values)。
    文件缺失或 JSON 解析失败时返回空列表,不影响 agent 启动。
    """
    if path is None:
        path = str(Path(__file__).resolve().parent.parent / "default.function.json")
    pth = Path(path)
    if not pth.exists():
        return []
    try:
        data = json.loads(pth.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    funcs = data.get("funcs", {})
    if not isinstance(funcs, dict):
        return []
    return list(funcs.values())
