"""Ollama backend (primary, local, no API key) using the native /api/chat API
with streaming and native tool calling.

Requires Ollama >= 0.3.x and a tool-capable model such as
qwen2.5-coder, llama3.1, mistral-nemo, or deepseek-coder-v2.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

from .base import LLMError, Message, OnText, ToolCall, ToolSpec


class OllamaBackend:
    name = "ollama"

    def __init__(self, host: str, model: str, stream: bool = True, timeout: int = 300):
        self.host = host.rstrip("/")
        self.model = model
        self.stream = stream
        self.timeout = timeout

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        messages: Sequence[Message],
        tools: Optional[List[ToolSpec]] = None,
        temperature: float = 0.2,
        on_text: OnText = None,
    ) -> Message:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [self._encode(m) for m in messages],
            "stream": self.stream,
            "options": {"temperature": temperature},
        }
        if tools:
            payload["tools"] = [
                {
                    "type": "function",
                    "function": {
                        "name": t["name"],
                        "description": t["description"],
                        "parameters": t["parameters"],
                    },
                }
                for t in tools
            ]

        data = self._post("/api/chat", payload)

        content_parts: List[str] = []
        calls: List[ToolCall] = []

        if self.stream:
            for raw in data.splitlines():
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    chunk = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                msg = chunk.get("message") or {}
                piece = msg.get("content") or ""
                if piece:
                    content_parts.append(piece)
                    if on_text:
                        on_text(piece)
                for tc in msg.get("tool_calls") or []:
                    calls.append(self._decode_call(tc, len(calls)))
        else:
            msg = data.get("message") or {}
            piece = msg.get("content") or ""
            content_parts.append(piece)
            if on_text and piece:
                on_text(piece)
            for tc in msg.get("tool_calls") or []:
                calls.append(self._decode_call(tc, len(calls)))

        return Message(
            role="assistant",
            content="".join(content_parts),
            tool_calls=calls or None,
        )

    # ----------------------------------------------------------------- check
    def check(self) -> str:
        try:
            body = self._request_json("GET", "/api/tags", None)
        except LLMError:
            raise
        except Exception as e:  # pragma: no cover
            raise LLMError(f"Ollama error: {e}") from e
        names = [m.get("name", "?") for m in body.get("models", [])]
        if not names:
            return f"Ollama reachable at {self.host}, but no models pulled yet. Run: ollama pull {self.model}"
        here = " (installed)" if any(n.startswith(self.model) for n in names) else ""
        return f"Ollama OK at {self.host} — models: {', '.join(names[:12])}{here}"

    # -------------------------------------------------------------- internal
    def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        req = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if self.stream:
                    return resp.read().decode("utf-8", errors="replace")
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", errors="replace")[:500]
            except Exception:
                pass
            raise LLMError(
                f"Ollama returned HTTP {e.code} for {self.model}: {detail}\n"
                f"Is '{self.model}' pulled and tool-capable? Try: ollama pull {self.model}"
            ) from e
        except urllib.error.URLError as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.host} ({e.reason}).\n"
                f"  1. Start it:        ollama serve\n"
                f"  2. Pull the model:  ollama pull {self.model}"
            ) from e

    def _request_json(self, method: str, path: str, payload: Optional[Dict[str, Any]]) -> Any:
        req = urllib.request.Request(
            self.host + path,
            data=json.dumps(payload).encode("utf-8") if payload else None,
            headers={"Content-Type": "application/json"},
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return json.loads(resp.read().decode("utf-8", errors="replace"))
        except urllib.error.URLError as e:
            raise LLMError(
                f"Cannot reach Ollama at {self.host} ({getattr(e, 'reason', e)}).\n"
                f"Start it with: ollama serve"
            ) from e

    @staticmethod
    def _encode(m: Message) -> Dict[str, Any]:
        if m.role == "tool":
            return {"role": "tool", "content": m.content, "tool_name": m.name or "tool"}
        if m.role == "assistant" and m.tool_calls:
            return {
                "role": "assistant",
                "content": m.content or "",
                "tool_calls": [
                    {"function": {"name": tc.name, "arguments": tc.arguments}}
                    for tc in m.tool_calls
                ],
            }
        return {"role": m.role, "content": m.content}

    @staticmethod
    def _decode_call(raw: Dict[str, Any], index: int) -> ToolCall:
        fn = raw.get("function") or {}
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"_raw": args}
        if not isinstance(args, dict):
            args = {}
        return ToolCall(id=f"call_{index}", name=fn.get("name", ""), arguments=args)
