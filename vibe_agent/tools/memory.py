"""Persistent project memory — markdown notes stored at <project>/.vibe/MEMORY.md.

This is how the agent accumulates durable knowledge across sessions:
decisions made, project conventions, gotchas discovered, open TODOs.
It is injected into the system prompt at the start of every turn.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from .base import ExecContext, Tool, ToolResult
from ..utils import now_stamp, truncate_middle

MEMORY_PATH = Path(".vibe") / "MEMORY.md"
MEMORY_TEMPLATE = (
    "# Project memory\n\n"
    "Durable notes the agent maintains across sessions: decisions, conventions, "
    "gotchas, TODOs. Human-editable.\n"
)

MEMORY_HEADER = "# Project memory"

MEMORY_LIMIT_CHARS = 4000


def read_memory(root: Path) -> str:
    path = root / MEMORY_PATH
    if not path.is_file():
        return ""
    try:
        return truncate_middle(path.read_text(encoding="utf-8", errors="replace"), MEMORY_LIMIT_CHARS)
    except OSError:
        return ""


def write_memory(root: Path, content: str) -> None:
    path = root / MEMORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class MemoryRead(Tool):
    name = "memory_read"
    description = "Read the persistent project memory (.vibe/MEMORY.md) in full."
    parameters = {"type": "object", "properties": {}}

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        content = read_memory(ctx.root)
        return ToolResult(content if content else "(memory is empty — nothing stored yet)")


class MemoryWrite(Tool):
    name = "memory_write"
    description = (
        "Update persistent project memory. Store durable facts only: decisions "
        "and their WHY, conventions, gotchas, TODOs. Not for conversation logs. "
        "Keep it short — it is injected into every future session."
    )
    parameters = {
        "type": "object",
        "properties": {
            "content": {"type": "string", "description": "The note to store (markdown)."},
            "mode": {"type": "string", "enum": ["append", "replace"], "description": "Default append."},
        },
        "required": ["content"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        content = str(args["content"]).strip()
        if not content:
            return ToolResult.error("empty memory note")
        mode = args.get("mode", "append")
        current = read_memory(ctx.root)
        stamp = now_stamp("%Y-%m-%d")

        if mode == "replace":
            new = f"{MEMORY_HEADER}\n\n{content}\n"
        else:
            entry = f"- [{stamp}] {content}"
            base = current if current else MEMORY_TEMPLATE
            new = base.rstrip("\n") + "\n" + entry + "\n"

        write_memory(ctx.root, new)
        return ToolResult(f"memory {mode}d ({len(new):,} chars total)")
