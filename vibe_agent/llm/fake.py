"""Scripted fake brain — no network, no model.

Used by:
  * the test-suite (deterministic end-to-end loop tests)
  * `vibe --provider fake` — a self-demo that exercises the whole
    pipeline (tools, executor, confirmation, terminal) on your machine.
"""

from __future__ import annotations

from typing import List, Optional, Sequence

from .base import Message, OnText, ToolSpec


class FakeBackend:
    """Plays back a scripted list of assistant messages, including tool calls."""

    name = "fake"

    def __init__(self, script: Optional[List[Message]] = None, model: str = "fake-1"):
        self.script = script if script is not None else self.default_demo()
        self.model = model
        self._i = 0

    # ------------------------------------------------------------- scripting
    @staticmethod
    def default_demo() -> List[Message]:
        from .fake_script import DEMO_STEPS

        return list(DEMO_STEPS)

    # ------------------------------------------------------------------ chat
    def chat(
        self,
        messages: Sequence[Message],
        tools: Optional[List[ToolSpec]] = None,
        temperature: float = 0.2,
        on_text: OnText = None,
    ) -> Message:
        if self._i >= len(self.script):
            return Message(
                role="assistant",
                content="(fake brain exhausted its script — switch to a real provider, "
                        "e.g. `vibe --provider ollama`)",
            )
        msg = self.script[self._i]
        self._i += 1
        if on_text and msg.content:
            on_text(msg.content)
        # return a copy so replays don't mutate the script
        return Message(
            role="assistant",
            content=msg.content,
            tool_calls=list(msg.tool_calls) if msg.tool_calls else None,
        )

    # ----------------------------------------------------------------- check
    def check(self) -> str:
        return "fake backend ready (scripted, offline)"
