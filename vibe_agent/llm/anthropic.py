"""Anthropic Claude backend using the native /v1/messages API."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

from .base import LLMError, Message, OnText, ToolCall, ToolSpec


class AnthropicBackend:
    name = "anthropic"

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        max_tokens: int = 4096,
        base_url: str = "https://api.anthropic.com",
        timeout: int = 300,
    ):
        self.model = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self.max_tokens = max_tokens
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        messages: Sequence[Message],
        tools: Optional[List[ToolSpec]] = None,
        temperature: float = 0.2,
        on_text: OnText = None,
    ) -> Message:
        system_parts: List[str] = []
        convo: List[Message] = []
        for m in messages:
            if m.role == "system":
                system_parts.append(m.content)
            else:
                convo.append(m)
        convo = self._merge_consecutive(convo)

        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": temperature,
            "messages": [self._encode(m) for m in convo],
        }
        if system_parts:
            payload["system"] = "\n\n".join(system_parts)
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
                for t in tools
            ]

        body = self._post("/v1/messages", payload)

        text_parts: List[str] = []
        calls: List[ToolCall] = []
        for block in body.get("content", []):
            btype = block.get("type")
            if btype == "text":
                text_parts.append(block.get("text", ""))
            elif btype == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.get("id", "call_0"),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )
        content = "".join(text_parts)
        if on_text and content:
            on_text(content)
        return Message(role="assistant", content=content, tool_calls=calls or None)

    # ----------------------------------------------------------------- check
    def check(self) -> str:
        if not self.api_key:
            raise LLMError(
                "ANTHROPIC_API_KEY is not set.\n  export ANTHROPIC_API_KEY=sk-ant-..."
            )
        return f"anthropic configured (key set, model '{self.model}')"

    # -------------------------------------------------------------- internal
    @staticmethod
    def _merge_consecutive(messages: List[Message]) -> List[Message]:
        """Anthropic requires strictly alternating user/assistant roles."""
        merged: List[Message] = []
        for m in messages:
            if merged and merged[-1].role == m.role:
                merged[-1] = Message(role=m.role, content=merged[-1].content + "\n\n" + m.content)
            else:
                merged.append(Message(role=m.role, content=m.content))
        return merged

    @staticmethod
    def _encode(m: Message) -> Dict[str, Any]:
        if m.role == "tool":
            return {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": m.tool_call_id or "",
                        "content": m.content,
                    }
                ],
            }
        if m.role == "assistant" and m.tool_calls:
            blocks: List[Dict[str, Any]] = []
            if m.content:
                blocks.append({"type": "text", "text": m.content})
            for tc in m.tool_calls:
                blocks.append(
                    {"type": "tool_use", "id": tc.id, "name": tc.name, "input": tc.arguments}
                )
            return {"role": "assistant", "content": blocks}
        return {"role": m.role, "content": m.content}

    def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        if not self.api_key:
            raise LLMError("ANTHROPIC_API_KEY is not set.\n  export ANTHROPIC_API_KEY=sk-ant-...")
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                err = json.loads(e.read().decode("utf-8", errors="replace"))
                detail = str(err.get("error", {}).get("message", err))[:400]
            except Exception:
                pass
            raise LLMError(f"anthropic HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Cannot reach anthropic ({getattr(e, 'reason', e)})") from e
