"""The agent loop — Vibe's reasoning/orchestration core.

One user turn:

    system prompt (+ fresh project memory)
        |
        v
    LLM chat --> assistant message
        |-- no tool calls --> final answer, turn ends
        |-- tool calls ----> execute each via ToolExecutor (safety + confirmation)
        |                    append results, loop back to LLM  (<= max_steps)

Everything provider-specific lives in the LLM backend; everything
capability-specific lives in the tool registry. This loop only orchestrates.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, List, Optional

from .config import AgentConfig
from .context import SessionStore, estimate_context_tokens, trim_messages
from .executor import ToolExecutor
from .llm.base import LLMError, Message
from .prompts import build_system_prompt
from .tools.base import ExecContext, Registry, ToolResult
from .tools.memory import read_memory


@dataclass
class TurnStats:
    tool_calls: int = 0
    steps: int = 0
    cancelled: bool = False

    def summary(self) -> str:
        return f"steps: {self.steps}, tool calls: {self.tool_calls}"


@dataclass
class AgentUI:
    """Sink for everything the user should see. Swap for a web UI later."""

    on_text: Callable[[str], None] = print
    on_tool_call: Callable[[str, str], None] = lambda name, args: None
    on_tool_result: Callable[[ToolResult], None] = lambda result: None
    on_error: Callable[[str], None] = print


class Agent:
    def __init__(
        self,
        backend,
        registry: Registry,
        ctx: ExecContext,
        config: AgentConfig,
        session: Optional[SessionStore] = None,
        ui: Optional[AgentUI] = None,
    ):
        self.backend = backend
        self.registry = registry
        self.ctx = ctx
        self.config = config
        self.executor = ToolExecutor(registry, ctx)
        self.session = session or SessionStore(ctx.root)
        self.ui = ui or AgentUI()
        self.history: List[Message] = []
        self._streamed: bool = False

    # ------------------------------------------------------------ main turn
    def run_turn(self, user_text: str) -> TurnStats:
        stats = TurnStats()
        system = Message(role="system", content=self._build_system())
        messages: List[Message] = [system] + self.history + [Message(role="user", content=user_text)]
        self.session.log(messages[-1])

        for _ in range(self.config.max_steps):
            stats.steps += 1
            self._streamed = False
            try:
                reply = self.backend.chat(
                    messages,
                    tools=self.registry.specs(),
                    temperature=self.config.temperature,
                    on_text=self._emit_text,
                )
            except LLMError as e:
                self.ui.on_error(str(e))
                stats.cancelled = True
                return stats

            messages.append(reply)
            self.session.log(reply)

            if not reply.tool_calls:
                self._save_history(messages)
                return stats

            for call in reply.tool_calls:
                stats.tool_calls += 1
                self.ui.on_tool_call(call.name, _short_args(call.arguments))
                result = self.executor.execute(call.name, call.arguments)
                self.ui.on_tool_result(result)

                tool_msg = Message(
                    role="tool",
                    content=result.output,
                    name=call.name,
                    tool_call_id=call.id,
                )
                messages.append(tool_msg)
                self.session.log(tool_msg)

            if stats.steps >= self.config.max_steps:
                self.ui.on_error(
                    f"reached max_steps ({self.config.max_steps}) mid-task. "
                    "Continue with a follow-up message, or raise max_steps in config."
                )
                self._save_history(messages)
                return stats
        self._save_history(messages)
        return stats

    # -------------------------------------------------------------- helpers
    def _build_system(self) -> str:
        model = getattr(self.backend, "model", "?")
        memory = read_memory(self.ctx.root)
        return build_system_prompt(
            root=str(self.ctx.root),
            backend=self.backend.name,
            model=model,
            memory=memory or None,
        )

    def _save_history(self, messages: List[Message]) -> None:
        self.history = trim_messages(messages[1:], self.config.max_context_tokens)

    def _emit_text(self, chunk: str) -> None:
        self._streamed = True
        self.ui.on_text(chunk)

    def context_size(self) -> int:
        return estimate_context_tokens(self.history)

    def reset(self) -> None:
        self.history = []
        self.session = SessionStore(self.ctx.root)

    def load_history(self, messages: List[Message]) -> None:
        self.history = trim_messages(messages, self.config.max_context_tokens)


def _short_args(args: dict, limit: int = 160) -> str:
    try:
        import json

        text = json.dumps(args, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(args)
    return text if len(text) <= limit else text[:limit] + "…"
