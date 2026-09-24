"""JSON tool-protocol adapter.

Wraps ANY backend so models WITHOUT native tool-calling support can still
drive the agent. The adapter injects a JSON protocol into the system prompt,
parses the model's JSON replies into ToolCall objects, and feeds tool results
back as user messages. The agent loop never knows the difference.

Enable with `use_native_tools: false` in config (or if your local model
doesn't support Ollama's tools API).
"""

from __future__ import annotations

import json
from typing import List, Optional, Sequence

from .base import LLMError, Message, OnText, ToolCall, ToolSpec

PROTOCOL = """

# Tool use protocol (JSON mode)
You can call tools. Respond with ONLY a JSON object (no prose, no code fences)
when you want to call one:
    {"tool": "<tool-name>", "arguments": { ... }}

To call several tools at once:
    {"tool_calls": [{"tool": "...", "arguments": {...}}, ...]}

Tool results arrive as user messages shaped like:
    {"tool_result": {"tool": "<name>", "ok": true, "output": "..."}}

When you are NOT calling a tool, reply with plain text — that is your final
answer for this step.

# Available tools
"""


class JsonToolAdapter:
    """Implements the LLMBackend interface on top of a plain chat backend."""

    def __init__(self, inner):
        self.inner = inner
        self.name = f"{getattr(inner, 'name', 'chat')}+jsonproto"

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        messages: Sequence[Message],
        tools: Optional[List[ToolSpec]] = None,
        temperature: float = 0.2,
        on_text: OnText = None,
    ) -> Message:
        converted: List[Message] = []
        protocol_injected = False

        for m in messages:
            if m.role == "system":
                content = m.content
                if tools and not protocol_injected:
                    content += PROTOCOL + self._tool_docs(tools)
                    protocol_injected = True
                converted.append(Message(role="system", content=content))
            elif m.role == "tool":
                converted.append(
                    Message(
                        role="user",
                        content=json.dumps(
                            {"tool_result": {"tool": m.name, "output": m.content}}
                        ),
                    )
                )
            elif m.role == "assistant" and m.tool_calls:
                payload = (
                    {"tool_calls": [{"tool": tc.name, "arguments": tc.arguments}
                                    for tc in m.tool_calls]}
                )
                converted.append(Message(role="assistant", content=json.dumps(payload)))
            else:
                converted.append(Message(role=m.role, content=m.content))

        if tools and not protocol_injected:
            converted.insert(
                0, Message(role="system", content=PROTOCOL + self._tool_docs(tools))
            )

        reply = self.inner.chat(converted, tools=None, temperature=temperature, on_text=on_text)
        return self._parse(reply)

    # ----------------------------------------------------------------- check
    def check(self) -> str:
        return self.inner.check()

    # -------------------------------------------------------------- internal
    @staticmethod
    def _tool_docs(tools: List[ToolSpec]) -> str:
        parts = []
        for t in tools:
            parts.append(
                f"- {t['name']}: {t['description']}\n"
                f"  arguments JSON schema: {json.dumps(t['parameters'])}"
            )
        return "\n".join(parts) + "\n"

    def _parse(self, reply: Message) -> Message:
        obj = extract_json_object(reply.content)
        if isinstance(obj, dict):
            if isinstance(obj.get("tool_calls"), list):
                calls = [
                    ToolCall(id=f"call_{i}", name=c.get("tool", ""), arguments=c.get("arguments") or {})
                    for i, c in enumerate(obj["tool_calls"])
                    if isinstance(c, dict) and c.get("tool")
                ]
                if calls:
                    return Message(role="assistant", content="", tool_calls=calls)
            elif obj.get("tool"):
                return Message(
                    role="assistant",
                    content="",
                    tool_calls=[ToolCall(id="call_0", name=obj["tool"],
                                         arguments=obj.get("arguments") or {})],
                )
        # No (valid) tool call -> plain final answer; strip trailing fences.
        text = reply.content.strip()
        return Message(role="assistant", content=text)


def extract_json_object(text: str) -> Optional[dict]:
    """Best-effort extraction of the first JSON object from model text.

    Tries: whole-text parse, fenced ```json blocks, then a balanced-brace scan.
    """
    text = text.strip()
    if not text:
        return None
    try:
        obj = json.loads(text)
        return obj if isinstance(obj, dict) else None
    except json.JSONDecodeError:
        pass

    # fenced blocks
    for fence in ("```json", "```"):
        if fence in text:
            for chunk in text.split(fence)[1::2]:
                chunk = chunk.split("```", 1)[0].strip()
                try:
                    obj = json.loads(chunk)
                    if isinstance(obj, dict):
                        return obj
                except json.JSONDecodeError:
                    continue

    # balanced-brace scan (skips braces inside strings)
    start = text.find("{")
    while start != -1:
        depth, in_str, esc = 0, False, False
        for i in range(start, len(text)):
            ch = text[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    try:
                        obj = json.loads(text[start:i + 1])
                        if isinstance(obj, dict):
                            return obj
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None
