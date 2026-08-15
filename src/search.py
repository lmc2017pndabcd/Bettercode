#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#search.py - 联网搜索:复用 bing-search 技能脚本,暴露为可靠的 web_search 工具
import os
import re
import sys
import urllib.request
from urllib.parse import quote
from pathlib import Path

SKILL_SCRIPT = os.path.expanduser("~/.bettercode/skills/bing-search/scripts/search.py")
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/124 Safari/537.36"


def web_search(query: str, top_n: int = 5) -> str:
    """调用 bing-search 技能的 search_bing(query),返回格式化结果文本"""
    script_dir = str(Path(SKILL_SCRIPT).parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    try:
        from search import search_bing
    except Exception as e:
        return f"搜索技能加载失败: {e}"
    result = search_bing(query)
    # 每条结果约 4 行(标题/摘要/链接/空行),按 top_n 截断
    lines = [l for l in str(result).splitlines() if l.strip()]
    return "\n".join(lines[: max(top_n, 1) * 4])


def fetch_url(url: str, max_chars: int = 6000) -> str:
    """抓取网页并提取可读正文(标题 + 文本),供模型阅读"""
    if not url:
        return "fetch_url 缺少 url 参数"
    try:
        # 中文等非 ASCII 字符需要百分号编码,否则 urllib 发不出去
        try:
            url.encode("ascii")
        except UnicodeEncodeError:
            url = quote(url, safe=":/?#[]@!$&'()*+,;=~%")
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
                "Accept-Encoding": "identity",
            },
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read()
            try:
                charset = resp.headers.get_content_charset() or "utf-8"
                html = raw.decode(charset, "ignore")
            except LookupError:
                html = raw.decode("utf-8", "ignore")
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        title = soup.title.get_text(strip=True) if soup.title else ""
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "aside"]):
            tag.decompose()
        text = " ".join(soup.stripped_strings)
        text = re.sub(r"\s+", " ", text).strip()
        if not text:
            text = html[:max_chars]
        head = f"标题: {title}" if title else "标题: (无)"
        return f"{head}\n正文:\n{text[:max_chars]}"
    except Exception as e:
        return f"网页访问失败: {e}"


if __name__ == "__main__":
    import sys as _sys

    if len(_sys.argv) < 2:
        print("用法: search.py <查询词> [top_n] | search.py fetch <url>")
        _sys.exit(1)
    if _sys.argv[1] == "fetch":
        print(fetch_url(_sys.argv[2] if len(_sys.argv) > 2 else ""))
        _sys.exit(0)
    top_n = int(_sys.argv[2]) if len(_sys.argv) > 2 else 5
    print(web_search(_sys.argv[1], top_n))
