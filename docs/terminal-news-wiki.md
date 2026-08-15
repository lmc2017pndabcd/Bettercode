# 终端可用的新闻 / 百科资源清单

> 用途：当用户问"哪些新闻/百科网站可以在终端用"时，直接引用本清单，无需联网搜索。
> 更新时间：2026-08-14

## 百科类（Wikipedia 及其 CLI）

- **wikit**：最经典的维基摘要 CLI。安装 `npm i -g wikit`；用法 `wikit <词条>`，`-lang zh` 可指定中文。
- **wiky**：美化版维基 CLI（Markdown 渲染、配色、交互式搜索）。安装 `cargo install wiky`。
- **wiki-cli / wikipedia-cli / wiclipedia**：同类摘要工具，npm/pip 安装后进交互模式。
- **wikitool**：基于 MediaWiki REST API，可取整篇文章源码、传 URL、搜索。
- **手动 curl**：任何百科都能这样用：`curl "https://zh.wikipedia.org/api/rest_v1/page/summary/人工智能"`。
- **Kiwix 离线包**：下载维基 ZIM 包后用 `kiwix-serve` 在本地起 HTTP 服务，再用 `curl`/`lynx`/`w3m` 阅读；可绕开网络封锁，推荐给中国大陆用户。

## 新闻类

### 通用 RSS 聚合器

- **newsboat**：终端 RSS 阅读器事实标准（newsbeuter 继任者）。`brew install newsboat` 或 `apt install newsboat`；任何提供 RSS/Atom 的新闻源都能订阅（BBC、Reuters、澎湃等）。
- **sfeed / newsraft / nom**：同类轻量替代。

### 中文新闻专用 CLI

- **xw-news-cli**：`npm i -g xw-news-cli`；一条命令聚合 17 个中文源：微博热搜、澎湃新闻、中国新闻网、IT之家、腾讯新闻、虎嗅、汽车之家、Google News 中英文版等。
- **腾讯新闻官方 CLI**：`npm i @tencentnews/cli@latest -g`；支持热点、早晚报、AI 订阅；需要去腾讯新闻官网申请 API Key。

### 纯文本版新闻网站（无需客户端）

- **text.npr.org**：NPR 官方文本版，`lynx text.npr.org` 或 `curl -s text.npr.org | less`。
- **lite.cnn.com**：CNN 极简文本版，同样可直接用文本浏览器/curl 读取。

### 社区 / 程序员新闻

- **Hacker News**：hn-term、hacktui、sup-tui（聚合 HN + Lobsters + dev.to）。
- **Reddit**：tuir（原 rtv），`pip install tuir-continued`，vim 键位浏览。

## 通用兜底方案

- **文本浏览器**：lynx、w3m、links/elinks，可打开任何不依赖 JS 的网页。
- **终端搜索引擎**：googler（Google）、ddgr（DuckDuckGo）。
- **Gopher / Gemini 协议**：bombadillo、amfora、AV-98 等客户端，天然终端友好。

## 中国大陆访问注意事项

- 维基百科所有语言版本自 2019 年起被 GFW 封锁，维基词典、维基新闻等维基媒体项目也基本全被封；官方帮助页确认"中国大陆无法直接访问"。
- 因此 wikit 等终端 CLI（走维基 API）直连同样不可用，需要代理：`export HTTPS_PROXY=http://127.0.0.1:端口`。
- 第三方镜像（如 kfd.me、zhwk.kkwiki.win）不稳定，随时失效，不建议当主力。
- 推荐方案：代理，或 Kiwix 离线包。
- 现代新闻网站普遍 JS 重，lynx/w3m 经常打不开；优先找提供 RSS 的源或用官方 CLI。
