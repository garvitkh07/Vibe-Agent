"""LLM message/data types shared by all backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# on_text receives incremental text chunks for streaming display.
OnText = Optional[Callable[[str], None]]

# Every tool exposes: name, description, parameters (JSON schema dict).
ToolSpec = Dict[str, Any]


@dataclass
class ToolCall:
    """A tool invocation requested by the model."""

    id: str
    name: str
    arguments: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name, "arguments": self.arguments}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ToolCall":
        return cls(
            id=data.get("id", "call_0"),
            name=data.get("name", ""),
            arguments=data.get("arguments") or {},
        )


@dataclass
class Message:
    """Provider-agnostic chat message.

    role: "system" | "user" | "assistant" | "tool"
    tool_calls: set on assistant messages that request tools
    name/tool_call_id: set on "tool" role messages (the result)
    """

    role: str
    content: str = ""
    tool_calls: Optional[List[ToolCall]] = None
    name: Optional[str] = None
    tool_call_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [tc.to_dict() for tc in self.tool_calls]
        if self.name is not None:
            d["name"] = self.name
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        calls = data.get("tool_calls")
        return cls(
            role=data.get("role", "user"),
            content=data.get("content", ""),
            tool_calls=[ToolCall.from_dict(c) for c in calls] if calls else None,
            name=data.get("name"),
            tool_call_id=data.get("tool_call_id"),
        )


class LLMError(Exception):
    """Raised for provider connectivity, auth, or protocol problems.

    The message should be friendly and actionable — it is shown to the user.
    """
