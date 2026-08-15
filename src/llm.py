#!/Users/daniel/Documents/Projects/ClaudeCode/.venv/bin/python3.12
#llm.py - LLM 后端抽象:OpenAI 兼容端点(DeepSeek/OpenAI/中转/Anthropic 兼容端点)与 Anthropic 原生 SDK
import json
import os
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parent.parent
dotenv.load_dotenv(ROOT / ".env")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")   # openai | anthropic
LLM_MODEL = os.getenv("LLM_MODEL", "")
ANTHROPIC_MAX_TOKENS = int(os.getenv("ANTHROPIC_MAX_TOKENS", "4096"))


def default_model() -> str:
    """默认模型名:LLM_MODEL > RAG_CHAT_MODEL;都没有则返回空串(由调用方询问用户)"""
    return LLM_MODEL or os.getenv("RAG_CHAT_MODEL", "")


def get_provider(name=None):
    """按 LLM_PROVIDER(可覆盖)返回 Provider 实例"""
    if (name or LLM_PROVIDER) == "anthropic":
        return AnthropicProvider()
    return OpenAIProvider()


def to_anthropic_tools(tools) -> list:
    """OpenAI tools 格式 -> Anthropic tools 格式"""
    out = []
    for t in tools or []:
        fn = t.get("function", {})
        out.append(
            {
                "name": fn.get("name", ""),
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters") or {"type": "object", "properties": {}},
            }
        )
    return out


def _append_user(conv, content):
    """追加 user 消息;连续的 user 消息合并成一条(Anthropic 要求角色交替)"""
    if conv and conv[-1]["role"] == "user":
        prev = conv[-1]["content"]
        if isinstance(prev, list) and isinstance(content, list):
            prev.extend(content)
        else:
            blocks = [{"type": "text", "text": prev}] if isinstance(prev, str) else prev
            if isinstance(content, str):
                blocks.append({"type": "text", "text": content})
            else:
                blocks.extend(content)
            conv[-1]["content"] = blocks
    else:
        conv.append({"role": "user", "content": content})


def to_anthropic_messages(messages) -> list:
    """统一的 OpenAI 风格消息列表 -> Anthropic /v1/messages 格式"""
    conv = []
    for m in messages:
        role = m.get("role")
        if role == "system":
            continue  # system 单独提取
        if role == "user":
            _append_user(conv, m.get("content") or "")
        elif role == "assistant":
            tcs = m.get("tool_calls")
            if tcs:
                blocks = []
                if m.get("content"):
                    blocks.append({"type": "text", "text": m["content"]})
                for tc in tcs:
                    fn = tc.get("function", {})
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id"),
                            "name": fn.get("name"),
                            "input": args,
                        }
                    )
                conv.append({"role": "assistant", "content": blocks})
            else:
                conv.append({"role": "assistant", "content": m.get("content") or ""})
        elif role == "tool":
            _append_user(
                conv,
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.get("tool_call_id"),
                        "content": m.get("content") or "",
                    }
                ],
            )
    return conv


class OpenAIProvider:
    """OpenAI 兼容端点:DeepSeek / OpenAI / 任意中转 / Anthropic 的 OpenAI 兼容端点"""

    def __init__(self):
        import openai

        base = os.getenv("OPENAI_BASE_URL", "https://api.deepseek.com/v1").rstrip("/")
        if base.endswith("/chat/completions"):
            base = base[: -len("/chat/completions")]
        key = os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or input("Key:")
        self.client = openai.OpenAI(api_key=key, base_url=base)

    def create(self, messages, tools, model):
        """流式补全,产出归一化事件:{"content": str} 或 {"tool_calls": {index,id,name,arguments}}"""
        try:
            resp = self.client.chat.completions.create(
                model=model, stream=True, messages=messages, tools=tools or None
            )
            yield from self._iter_chunks(resp)
        except Exception as e:
            if tools and "does not support tools" in str(e):
                # 本地模型常不支持工具调用:降级为纯对话模式重试
                yield {"notice": "当前模型不支持工具调用,已降级为纯对话模式"}
                resp2 = self.client.chat.completions.create(
                    model=model, stream=True, messages=messages
                )
                yield from self._iter_chunks(resp2)
            else:
                raise

    def _iter_chunks(self, resp):
        for chunk in resp:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta is None:
                continue
            if delta.content:
                yield {"content": delta.content}
            for tc in (delta.tool_calls or []):
                ev = {"tool_calls": {"index": tc.index}}
                if tc.id:
                    ev["tool_calls"]["id"] = tc.id
                if tc.function:
                    if tc.function.name:
                        ev["tool_calls"]["name"] = tc.function.name
                    if tc.function.arguments:
                        ev["tool_calls"]["arguments"] = tc.function.arguments
                yield ev

    def complete_text(self, messages, model) -> str:
        """非流式补全,返回文本(记忆汇总等场景用)"""
        resp = self.client.chat.completions.create(model=model, messages=messages)
        return resp.choices[0].message.content or ""


class AnthropicProvider:
    """Anthropic 原生 SDK:/v1/messages,流式与工具调用归一化为 OpenAI 风格事件"""

    def __init__(self):
        import anthropic

        kwargs = {}
        base = os.getenv("ANTHROPIC_BASE_URL", "").strip()
        if base:
            kwargs["base_url"] = base
        key = os.getenv("ANTHROPIC_API_KEY") or input("Anthropic Key:")
        self.client = anthropic.Anthropic(api_key=key, **kwargs)

    def create(self, messages, tools, model):
        import anthropic

        system = "\n".join(
            m["content"] for m in messages
            if m.get("role") == "system" and isinstance(m.get("content"), str)
        )
        stream = self.client.messages.create(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system or anthropic.NOT_GIVEN,
            messages=to_anthropic_messages(messages),
            tools=to_anthropic_tools(tools) if tools else anthropic.NOT_GIVEN,
            stream=True,
        )
        for event in stream:
            etype = getattr(event, "type", None)
            if etype == "content_block_start":
                block = getattr(event, "content_block", None)
                if getattr(block, "type", None) == "tool_use":
                    yield {
                        "tool_calls": {
                            "index": event.index,
                            "id": block.id,
                            "name": block.name,
                            "arguments": "",
                        }
                    }
            elif etype == "content_block_delta":
                delta = getattr(event, "delta", None)
                dtype = getattr(delta, "type", None)
                if dtype == "text_delta":
                    yield {"content": delta.text}
                elif dtype == "input_json_delta":
                    yield {
                        "tool_calls": {
                            "index": event.index,
                            "arguments": delta.partial_json,
                        }
                    }
            elif etype == "message_stop":
                break

    def complete_text(self, messages, model) -> str:
        import anthropic

        system = "\n".join(
            m["content"] for m in messages
            if m.get("role") == "system" and isinstance(m.get("content"), str)
        )
        resp = self.client.messages.create(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=system or anthropic.NOT_GIVEN,
            messages=to_anthropic_messages(messages),
        )
        return "".join(
            b.text for b in resp.content if getattr(b, "type", None) == "text"
        )
