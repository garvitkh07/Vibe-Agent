"""OpenAI-compatible backend.

Works with OpenAI and any OpenAI-compatible endpoint: Ollama (/v1),
LM Studio, Groq, Together, OpenRouter, vLLM, and Google Gemini's
OpenAI-compatible endpoint. Non-streaming for v1 (robust + simple).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional, Sequence

from .base import LLMError, Message, OnText, ToolCall, ToolSpec


class OpenAICompatBackend:
    name = "openai-compat"

    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: Optional[str] = None,
        label: str = "openai-compat",
        timeout: int = 300,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.name = label
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
            "temperature": temperature,
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

        body = self._post("/chat/completions", payload)
        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}

        calls: List[ToolCall] = []
        for i, tc in enumerate(msg.get("tool_calls") or []):
            fn = tc.get("function") or {}
            raw_args = fn.get("arguments")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            except json.JSONDecodeError:
                args = {"_raw": raw_args}
            calls.append(ToolCall(id=tc.get("id") or f"call_{i}", name=fn.get("name", ""), arguments=args))

        content = msg.get("content") or ""
        if on_text and content:
            on_text(content)
        return Message(role="assistant", content=content, tool_calls=calls or None)

    # ----------------------------------------------------------------- check
    def check(self) -> str:
        key_state = "key set" if self.api_key else "no API key (local endpoint?)"
        try:
            self._post(
                "/chat/completions",
                {
                    "model": self.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 1,
                },
            )
            return f"{self.name} OK at {self.base_url} ({key_state}, model '{self.model}' responded)"
        except LLMError as e:
            return f"{self.name} at {self.base_url}: {e}"

    # -------------------------------------------------------------- internal
    @staticmethod
    def _encode(m: Message) -> Dict[str, Any]:
        if m.role == "tool":
            return {
                "role": "tool",
                "tool_call_id": m.tool_call_id or "",
                "content": m.content,
            }
        if m.role == "assistant" and m.tool_calls:
            return {
                "role": "assistant",
                "content": m.content or "",
                "tool_calls": [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": json.dumps(tc.arguments),
                        },
                    }
                    for tc in m.tool_calls
                ],
            }
        return {"role": m.role, "content": m.content}

    def _post(self, path: str, payload: Dict[str, Any]) -> Any:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        req = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
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
            raise LLMError(f"{self.name} HTTP {e.code}: {detail}") from e
        except urllib.error.URLError as e:
            raise LLMError(f"Cannot reach {self.name} at {self.base_url} ({getattr(e, 'reason', e)})") from e
