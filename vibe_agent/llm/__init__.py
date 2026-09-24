"""Abstract LLM backend interface.

Every provider (Ollama, OpenAI, Anthropic, Gemini, LM Studio, vLLM, ...)
implements this one method, so the "brain" can be swapped without touching
the agent loop or any tool.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional, Sequence

from .base import LLMError, Message, OnText, ToolSpec  # noqa: F401  (re-exported)


class LLMBackend(ABC):
    """A chat-completion backend with optional native tool calling."""

    name: str = "abstract"

    @abstractmethod
    def chat(
        self,
        messages: Sequence[Message],
        tools: Optional[List[ToolSpec]] = None,
        temperature: float = 0.2,
        on_text: OnText = None,
    ) -> Message:
        """Send the conversation, return the assistant message
        (with .tool_calls set if the model wants to run tools)."""

    @abstractmethod
    def check(self) -> str:
        """Verify the backend is reachable/configured.
        Return a human-readable status; raise LLMError with an actionable
        message if not."""
