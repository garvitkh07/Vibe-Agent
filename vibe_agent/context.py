"""Context management: token budgeting, history trimming, session transcripts.

The conversation can grow unbounded with tool results, so we:
  * cap every tool result at write time (executor + config.max_tool_output_chars)
  * trim HISTORY by atomic blocks (an assistant message with tool calls plus
    its tool results are never separated) when the budget is exceeded
  * persist every session as JSONL under <project>/.vibe/sessions/ for
    auditing and /resume
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

from .llm.base import Message
from .utils import estimate_tokens, now_stamp


# --------------------------------------------------------------------- trim
def trim_messages(messages: List[Message], max_tokens: int) -> List[Message]:
    """Keep the most recent messages that fit in the token budget.

    Blocks: [user] or [assistant + following tool results] are atomic —
    we never orphan a tool result from its request.
    """
    if not messages:
        return messages

    blocks: List[List[Message]] = []
    i = 0
    while i < len(messages):
        msg = messages[i]
        block = [msg]
        if msg.role == "assistant" and msg.tool_calls:
            i += 1
            while i < len(messages) and messages[i].role == "tool":
                block.append(messages[i])
                i += 1
        else:
            i += 1
        blocks.append(block)

    kept: List[List[Message]] = []
    budget = max_tokens
    for block in reversed(blocks):
        cost = sum(estimate_tokens(m.content) for m in block)
        if cost > budget and kept:
            break
        budget -= cost
        kept.append(block)
    kept.reverse()

    out = [m for block in kept for m in block]
    return out


def estimate_context_tokens(messages: List[Message]) -> int:
    return sum(estimate_tokens(m.content) for m in messages)


# ------------------------------------------------------------------ sessions
class SessionStore:
    """JSONL transcript of one session, stored in <project>/.vibe/sessions/."""

    def __init__(self, project_root: Path):
        self.dir = project_root / ".vibe" / "sessions"
        self.dir.mkdir(parents=True, exist_ok=True)
        stamp = now_stamp("%Y%m%d-%H%M%S")
        self.path = self.dir / f"session-{stamp}.jsonl"

    def log(self, message: Message) -> None:
        try:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(message.to_dict(), ensure_ascii=False) + "\n")
        except OSError:
            pass  # transcript loss must never break the agent

    @staticmethod
    def load(path: Path, limit: int = 200) -> List[Message]:
        messages: List[Message] = []
        try:
            for line in path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    msg = Message.from_dict(json.loads(line))
                except (json.JSONDecodeError, KeyError):
                    continue
                if msg.role == "system":
                    continue
                messages.append(msg)
        except OSError:
            return []
        return messages[-limit:]

    @staticmethod
    def list_sessions(project_root: Path) -> List[Path]:
        d = project_root / ".vibe" / "sessions"
        if not d.is_dir():
            return []
        return sorted(d.glob("session-*.jsonl"), reverse=True)
