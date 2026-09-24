"""Git tools — thin, safe wrappers around the most common read/commit flows.

Destructive git operations (reset --hard, clean -f, force-push, branch -D)
are NOT given dedicated tools on purpose: if the model really needs one it
goes through run_command, where the safety layer classifies it as ASK/DENY.
"""

from __future__ import annotations

import os
import subprocess
from typing import Any, Dict, Optional

from .base import ExecContext, Tool, ToolResult
from .terminal import ENV_OVERRIDES
from ..utils import truncate_middle


def _git(ctx: ExecContext, args: list, timeout: int = 60) -> subprocess.CompletedProcess:
    env = os.environ.copy()
    env.update(ENV_OVERRIDES)
    return subprocess.run(
        ["git"] + args, cwd=str(ctx.root), capture_output=True, text=True,
        timeout=timeout, env=env,
    )


def _result(proc: subprocess.CompletedProcess, max_chars: int = 8000) -> ToolResult:
    out = (proc.stdout or "") + (proc.stderr or "")
    out = out.strip() or "(no output)"
    ok = proc.returncode == 0
    return ToolResult(truncate_middle(out, max_chars), success=ok)


def _not_a_repo(ctx: ExecContext) -> Optional[ToolResult]:
    if not (ctx.root / ".git").is_dir():
        return ToolResult.error(
            f"not a git repository: {ctx.root} (run `git init` or check you're in the right project)"
        )
    return None


class GitStatus(Tool):
    name = "git_status"
    description = "Show git status: current branch, staged/unstaged changes, untracked files."
    parameters = {"type": "object", "properties": {}}

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        if r := _not_a_repo(ctx):
            return r
        return _result(_git(ctx, ["status", "--short", "--branch"]))


class GitDiff(Tool):
    name = "git_diff"
    description = "Show the diff of working-tree changes (what would be lost/committed right now)."
    parameters = {
        "type": "object",
        "properties": {
            "staged": {"type": "boolean", "description": "Show staged (--cached) diff instead. Default false."},
            "path": {"type": "string", "description": "Limit diff to a file/dir."},
        },
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        if r := _not_a_repo(ctx):
            return r
        git_args = ["diff", "--stat"] if args.get("staged") else ["diff"]
        if args.get("staged"):
            git_args.append("--cached")
        if args.get("path"):
            git_args += ["--", args["path"]]
        return _result(_git(ctx, git_args))


class GitLog(Tool):
    name = "git_log"
    description = "Show recent commit history (one line per commit)."
    parameters = {
        "type": "object",
        "properties": {"limit": {"type": "integer", "description": "Default 15."}},
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        if r := _not_a_repo(ctx):
            return r
        n = min(max(int(args.get("limit", 15)), 1), 100)
        return _result(_git(ctx, ["log", "--oneline", f"-n{n}"]))


class GitBranches(Tool):
    name = "git_branches"
    description = "List local/remote branches and mark the current one."
    parameters = {"type": "object", "properties": {}}

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        if r := _not_a_repo(ctx):
            return r
        return _result(_git(ctx, ["branch", "-a"]))


class GitCommit(Tool):
    name = "git_commit"
    description = (
        "Commit with a clear, conventional message (optionally `git add -A` "
        "first with stage_all=true). Never commit secrets; commit messages "
        "should explain WHY, not just WHAT."
    )
    parameters = {
        "type": "object",
        "properties": {
            "message": {"type": "string"},
            "stage_all": {"type": "boolean", "description": "Run `git add -A` first. Default false (commits what is staged)."},
        },
        "required": ["message"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        if r := _not_a_repo(ctx):
            return r
        message = str(args["message"]).strip()
        if not message:
            return ToolResult.error("empty commit message")
        if args.get("stage_all"):
            proc = _git(ctx, ["add", "-A"])
            if proc.returncode != 0:
                return _result(proc)
        proc = _git(ctx, ["commit", "-m", message])
        if "nothing to commit" in (proc.stdout or ""):
            return ToolResult.error("nothing to commit (working tree clean?) — check git_status first")
        return _result(proc)
