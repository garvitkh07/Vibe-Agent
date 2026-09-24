"""Tool executor — the single choke point between the agent and the tools.

Responsibilities:
  * look up the requested tool
  * coerce/guard arguments (accept JSON-string args from weaker models)
  * run the tool, catch EVERYTHING (a tool crash must not kill the loop)
  * enforce the output size limit before results enter the context
"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from .tools.base import ExecContext, Registry, ToolResult
from .utils import truncate_middle


class ToolExecutor:
    def __init__(self, registry: Registry, ctx: ExecContext):
        self.registry = registry
        self.ctx = ctx

    def execute(self, name: str, arguments: Any) -> ToolResult:
        tool = self.registry.get(name)
        if tool is None:
            known = ", ".join(self.registry.names())
            return ToolResult.error(
                f"unknown tool '{name}'. Available tools: {known}"
            )

        args = self._coerce_args(arguments)
        if args is None:
            return ToolResult.error(
                f"arguments for '{name}' must be a JSON object, got: {type(arguments).__name__}"
            )

        try:
            result = tool.run(args, self.ctx)
        except Exception as e:  # noqa: BLE001 — tools must never crash the loop
            return ToolResult.error(f"tool '{name}' crashed: {type(e).__name__}: {e}")

        limit = getattr(self.ctx.config, "max_tool_output_chars", 12_000)
        if len(result.output) > limit:
            result.output = truncate_middle(result.output, limit) + \
                "\n[truncated by executor before entering context]"
        return result

    @staticmethod
    def _coerce_args(arguments: Any) -> Optional[Dict[str, Any]]:
        if arguments is None:
            return {}
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments or "{}")
            except json.JSONDecodeError:
                return None
        if isinstance(arguments, dict):
            return arguments
        return None
