"""Terminal tool — runs shell commands in the project root, guarded by the
safety classifier and human confirmation.

Every command goes through safety.classify():
    ALLOW -> run          ASK -> human approval          DENY -> refused
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict

from .base import ExecContext, Tool, ToolResult
from ..safety import ASK, DENY, classify
from ..utils import truncate_middle

# Keep interactive prompts and pagers from hanging the agent.
ENV_OVERRIDES = {
    "GIT_EDITOR": "true",
    "GIT_PAGER": "cat",
    "GIT_TERMINAL_PROMPT": "0",
    "PAGER": "cat",
    "PYTHONUNBUFFERED": "1",
    "TERM": "dumb",
    "NO_COLOR": "1",
}


class RunCommand(Tool):
    name = "run_command"
    description = (
        "Run a shell command in the project root and return stdout/stderr plus "
        "the exit code. Use for builds, tests, scripts, git, package managers. "
        "Keep commands non-interactive (pass -y). Clearly destructive commands "
        "are blocked; risky ones require user approval. Do not start long-running "
        "servers here — tell the user the command to run instead."
    )
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "The shell command to run."},
            "timeout": {"type": "integer", "description": "Seconds before killing the process. Default 120, max 600."},
        },
        "required": ["command"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        command = str(args["command"]).strip()
        timeout = min(max(int(args.get("timeout", 120)), 1), 600)

        verdict, reason = classify(command)
        if verdict == DENY:
            return ToolResult.error(
                f"[BLOCKED by safety layer] {reason}.\n"
                "The command was NOT executed. Choose a safer approach — if it is "
                "truly necessary, hand the exact command to the user to run themselves."
            )
        if verdict == ASK and ctx.config.confirm_mode != "auto":
            if not ctx.confirm("terminal", f"Run command ({reason}):\n    {command}"):
                return ToolResult(
                    "Cancelled by user — the command was NOT executed. Do not retry "
                    "it silently; ask the user how to proceed.", success=False,
                )

        env = os.environ.copy()
        env.update(ENV_OVERRIDES)
        try:
            proc = subprocess.run(
                command,
                shell=True,
                cwd=str(ctx.root),
                capture_output=True,
                text=True,
                timeout=timeout,
                env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.error(
                f"command timed out after {timeout}s and was killed. If it is a "
                "long-running process (server/watcher), do NOT run it here — give "
                "the command to the user to run in their own terminal."
            )
        except OSError as e:
            return ToolResult.error(f"failed to execute: {e}")

        parts = [f"exit code: {proc.returncode}"]
        if proc.stdout.strip():
            parts.append("--- stdout ---\n" + proc.stdout.strip())
        if proc.stderr.strip():
            parts.append("--- stderr ---\n" + proc.stderr.strip())
        if not proc.stdout.strip() and not proc.stderr.strip():
            parts.append("(no output)")
        return ToolResult(truncate_middle("\n".join(parts), ctx.config.max_tool_output_chars * 2))
