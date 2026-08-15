# main.py 交互层重构指南（prompt_toolkit 全屏布局）

目标：顶部**固定**计划面板（长输出也挤不走）、中间**可滚动**对话输出（鼠标滚轮/上下键）、底部输入框（补全 + 历史）。业务逻辑尽量不动。

> 状态：**已实现**（2026-08-15）。本文档保留为结构说明与排错参考。

### Markdown 渲染（已实现）

- 输出区仍是 Buffer（保证滚动/贴底），模型回答按"块"处理：流式期间显示纯文本，回答完成后用 **rich `Markdown.__rich_console__()`** 渲染成 `Segment`（style+text），替换为富文本行；
- 富文本行存放在 `output_lines`（与 Buffer 行一一对应），由 `OutputLexer` 提供给 `BufferControl`；
- rich 样式经 `_pt_style()` 过滤后映射为 prompt_toolkit 样式（标题加粗下划线、行内代码加色、围栏背景等）。

## 1. 现状 → 目标

| 现状 | 目标 |
| --- | --- |
| `prompt()`（单行输入，每轮循环） | `Application` + `Layout`（常驻全屏，事件驱动） |
| rich `Live` 渲染流式回答 | 输出 `Buffer`，`insert_text()` + `app.invalidate()` |
| `input()` 审批 | 输入框内确认（见 §5） |
| `cons.print(...)` | `append_output(...)` 写进输出区，或状态行 |

rich `Live` 和 prompt_toolkit 全屏应用不能共存：流式输出一律改走输出 Buffer。

## 2. 布局结构

```text
┌──────────────────────────────────────┐
│ 计划面板（固定，无计划时高度 0）        │  ← Window(FormattedTextControl)
├──────────────────────────────────────┤
│ 对话输出（可滚动，weight=1）           │  ← Window(BufferControl, wrap_lines, scrollbar)
│ ...                                  │
├──────────────────────────────────────┤
│ > 输入框                              │  ← Window(BufferControl, height=1)
└──────────────────────────────────────┘
```

## 3. 关键组件

```python
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.margins import ScrollbarMargin
from prompt_toolkit.history import FileHistory
```

- **输出 Buffer**：`output_buffer = Buffer()`；`append_output(text)` 内部 `output_buffer.insert_text(text + "\n")` + `app.invalidate()`。
- **计划面板**：`Window(content=FormattedTextControl(plan_render), height=D(max=8))`。`plan_render` 是**可调用对象**，重绘时自动取最新文本，所以工具调用后只需 `app.invalidate()`。
- **输入 Buffer**：`Buffer(multiline=False, history=FileHistory("~/.agent_history"), completer=SlashCompleter(COMMANDS))`，`accept_handler` 接管回车。
- **滚轮/上下键**：`Application(mouse_support=True)`；`@kb.add("scroll-up")` / `@kb.add("scroll-down")` 里调 `output_window._scroll_up()/_scroll_down()`（3.0.x 的私有但稳定方法，prompt_toolkit 内部滚动就是用它）再 `app.invalidate()`。
- **滚动条**：`Window(..., right_margins=[ScrollbarMargin()])`（`scrollbar` 不是 Window 参数）。

## 4. 主循环改造

原 `while True: prompt(...)` 整体换成：

```python
app = Application(layout=Layout(HSplit([plan_window, output_window, input_window])),
                  key_bindings=kb, mouse_support=True, full_screen=True)
app.run()
```

输入流用**后台线程 + 队列**：`accept_handler` 把文本放进 `input_queue`；业务线程取文本，处理一轮（复用现有 `chat_round`/`execute_tool`/命令逻辑），处理完继续取。跨线程写输出用 `app.invalidate()`（prompt_toolkit 线程安全地安排重绘）。

命令处理抽成函数：`def handle_input(text) -> None`，内部先走 `/commands`（`/plan`、`/tasks`、`/mcp`、`/new` 等），再走对话轮次。

## 5. 审批改造（重点）

现在 `execute_tool` 里 `input("批准执行? [y/N]")` 会阻塞 TUI，必须换掉：

1. 业务线程需要审批时：`append_output("Agent 请求执行: $ cmd\n原因: ...\n批准? [y/N]")`，然后 `approved = approval_queue.get()`；
2. 输入框 `accept_handler` 先检查"是否在等待审批"：是 → 解析 y/N 放入 `approval_queue`，重置输入框；否 → 走命令/对话处理；
3. `execute_tool` 的签名改为接收 `ask_approval(reason) -> bool` 回调，`run_command`/`write_file` 用它替代 `input()`。

## 6. 需要改动的函数清单

| 函数 | 改动 |
| --- | --- |
| `chat_round` | 删掉 rich `Live`，流式 chunk 改调 `append_output(content)`；计划面板不需要手动更新（`FormattedTextControl` 可调用对象自动重绘），但在工具轮次之间 `app.invalidate()` |
| `execute_tool` | `cons.print` → `append_output`；`input()` → `ask_approval` 回调 |
| `run_command` / `write_file` 分支 | 同上（审批回调） |
| `load_skills` / `run_func` / `run_skill` / `mcp_client` / `planner` | 不动 |
| 启动部分 | `cons`、`mcp_client.manager.start()`、`skill.check_skills()` 保留；删除 `prompt()` 循环 |

## 7. 坑

- **滚轮滚动**：开启 `mouse_support=True` 后滚轮事件归应用管，终端自身滚动条不再滚历史——只滚输出区，这是预期行为。输出自动跟随底部由 Window 默认逻辑保证（保持光标可见）；手动上滚后新内容到达时视图尽量保持，若想强制贴底可在 `append_output` 后补一次 `_scroll_down()`。
- **流式刷新频率**：逐 token `invalidate` 可能闪/卡，可在 `append_output` 里做小批量（攒 20~50 字符或 100ms 定时 flush）。
- **rich 与 prompt_toolkit 冲突**：删除所有 `live.Live`、`markdown.Markdown` 的 Live 用法；输出区如果还想要 markdown 渲染，用 prompt_toolkit 的 `FormattedTextControl` 手写 ANSI，或先用纯文本。
- **退出**：`@kb.add("c-c")` / 输入 `/bye` 时 `event.app.exit()`；业务线程用守护线程，随进程退出。
- **审批死锁**：审批等待期间输入框只接受 y/N，防止用户输入其他内容被误当聊天。
- **焦点**（已踩过）：全屏应用默认把焦点给第一个可聚焦控件——输出窗格在前面，会导致输入打进输出区、Enter 不触发。必须 `Layout(..., focused_element=input_buffer)` 并把输出 `BufferControl(focusable=False)`。

## 8. 验证

在真实终端跑（`python src/main.py`），不要用管道/脚本模拟。检查：面板钉住、长回答滚不丢计划、滚轮滚动输出、`/tasks`/`/plan` 正常、run_command 审批 y/N 生效、退出后终端恢复。

最小可运行骨架见 [tui_skeleton.py](/Users/daniel/Documents/Projects/ClaudeCode/docs/tui_skeleton.py)。
