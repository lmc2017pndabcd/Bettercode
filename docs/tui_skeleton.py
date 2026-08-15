#!/usr/bin/env python3
"""最小可运行骨架:顶部固定面板 + 中间可滚动输出 + 底部输入(prompt_toolkit)
运行:python docs/tui_skeleton.py
"""
from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import D
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.layout.margins import ScrollbarMargin

kb = KeyBindings()
output_buffer = Buffer()
input_buffer = Buffer(multiline=False, history=InMemoryHistory())


def plan_render():
    """计划面板文本:可调用对象,重绘时自动取最新"""
    return [
        ("bold", " 计划 1: 示例任务 "),
        ("", "● "),
        ("", "○ "),
        ("", "○ "),
        ("dim", " (1/3 完成)"),
    ]


plan_window = Window(
    content=FormattedTextControl(plan_render),
    height=D(max=5),
    style="bg:ansiblue",
)
output_window = Window(
    content=BufferControl(buffer=output_buffer),
    wrap_lines=True,
    always_hide_cursor=True,
    right_margins=[ScrollbarMargin()],
)
input_window = Window(content=BufferControl(buffer=input_buffer), height=1)


def append_output(text: str):
    output_buffer.insert_text(text + "\n")
    app.invalidate()


@kb.add("scroll-up")
def _(event):
    output_window._scroll_up()
    app.invalidate()


@kb.add("scroll-down")
def _(event):
    output_window._scroll_down()
    app.invalidate()


@kb.add("c-c")
def _(event):
    event.app.exit()


def on_accept(buff: Buffer):
    text = buff.text
    buff.reset()
    append_output(f"You: {text}")
    # 这里接业务逻辑:命令分发 / 对话轮次 / 审批


input_buffer.accept_handler = on_accept

app = Application(
    layout=Layout(HSplit([plan_window, output_window, input_window])),
    key_bindings=kb,
    mouse_support=True,
    full_screen=True,
)

if __name__ == "__main__":
    app.run()
