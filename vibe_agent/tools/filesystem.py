"""Filesystem tools: list, tree, read, write, edit, delete.

Design notes:
  * edit_file is the workhorse — exact-match targeted replacement, the way
    careful humans edit code. Whole-file rewrites are opt-in via write_file.
  * write_file asks for confirmation before overwriting a non-empty file.
  * delete_file ALWAYS asks (unless the session runs with --yes).
  * All paths are confined to the project root (ExecContext.resolve).
"""

from __future__ import annotations

import difflib
from pathlib import Path
from typing import Any, Dict, List

from .base import ExecContext, Tool, ToolResult
from ..utils import BINARY_HINT_EXTS, IGNORE_DIRS, truncate_middle

MAX_READ_CHARS = 40_000
MAX_READ_LINES = 500


class ListDir(Tool):
    name = "list_dir"
    description = (
        "List the immediate children of a directory (name, type, size). "
        "Use project_tree for a deeper view."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Directory path, relative to project root. Default '.'"},
        },
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        path = ctx.resolve(args.get("path", "."))
        if not path.is_dir():
            return ToolResult.error(f"not a directory: {path}")
        entries = sorted(path.iterdir(), key=lambda p: (p.is_file(), p.name.lower()))
        if not entries:
            return ToolResult("(empty directory)")
        lines = []
        for entry in entries[:500]:
            if entry.is_dir():
                lines.append(f"{entry.name}/")
            else:
                try:
                    size = entry.stat().st_size
                except OSError:
                    size = 0
                lines.append(f"{entry.name}  ({size:,} B)")
        return ToolResult("\n".join(lines))


class ProjectTree(Tool):
    name = "project_tree"
    description = (
        "Print an ASCII tree of the project structure. Ignores node_modules, "
        ".git, venvs, build output, etc. Best first step to understand a repo."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Sub-branch to show. Default '.'"},
            "max_depth": {"type": "integer", "description": "Depth limit (default 3)."},
        },
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        base = ctx.resolve(args.get("path", "."))
        max_depth = int(args.get("max_depth", 3))
        lines: List[str] = [f"{base.name or '.'}/"]
        budget = [800]

        def walk(dir_path: Path, prefix: str, depth: int) -> None:
            if depth >= max_depth or budget[0] <= 0:
                return
            try:
                children = sorted(
                    dir_path.iterdir(), key=lambda p: (p.is_file(), p.name.lower())
                )
            except OSError:
                return
            children = [
                c for c in children
                if c.name not in IGNORE_DIRS and not c.name.endswith(".egg-info")
            ]
            for i, child in enumerate(children):
                if budget[0] <= 0:
                    lines.append(prefix + "...[more entries omitted]")
                    return
                budget[0] -= 1
                connector = "└── " if i == len(children) - 1 else "├── "
                if child.is_dir():
                    lines.append(prefix + connector + child.name + "/")
                    walk(child, prefix + ("    " if i == len(children) - 1 else "│   "), depth + 1)
                else:
                    lines.append(prefix + connector + child.name)

        walk(base, "", 0)
        return ToolResult("\n".join(lines))


class ReadFile(Tool):
    name = "read_file"
    description = (
        "Read a text file (source code, config, docs, logs). Returns up to 500 "
        "lines / 40k chars; pass start_line to page through bigger files."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path relative to project root."},
            "start_line": {"type": "integer", "description": "1-based line to start from. Default 1."},
        },
        "required": ["path"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        path = ctx.resolve(args["path"])
        if not path.is_file():
            return ToolResult.error(f"file not found: {args['path']}")
        if path.suffix.lower() in BINARY_HINT_EXTS:
            return ToolResult.error(f"refusing to read binary file: {args['path']}")
        try:
            data = path.read_bytes()
        except OSError as e:
            return ToolResult.error(f"cannot read {args['path']}: {e}")
        if b"\x00" in data[:8192]:
            return ToolResult.error(f"looks binary, not text: {args['path']}")
        text = data.decode("utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        start = max(1, int(args.get("start_line", 1)))
        window = lines[start - 1: start - 1 + MAX_READ_LINES]
        body = "\n".join(window)
        header = f"{args['path']} — lines {start}-{start + len(window) - 1} of {total}"
        if len(body) > MAX_READ_CHARS:
            body = truncate_middle(body, MAX_READ_CHARS)
        return ToolResult(f"{header}\n{'-' * len(header)}\n{body}")


class WriteFile(Tool):
    name = "write_file"
    description = (
        "Create a new file (parent dirs auto-created) or REPLACE an existing "
        "file's full contents. For small changes to existing files prefer "
        "edit_file — it is safer and easier to review."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "description": "Full file content."},
        },
        "required": ["path", "content"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        try:
            path = ctx.resolve(args["path"])
        except ValueError as e:
            return ToolResult.error(str(e))
        content = args["content"]
        existed = path.exists() and path.stat().st_size > 0
        if existed:
            if not ctx.confirm(
                "file-overwrite",
                f"OVERWRITE existing file {path.name}? ({path.stat().st_size:,} B -> {len(content):,} B)",
            ):
                return ToolResult(
                    "Cancelled by user — file NOT overwritten. Read it and propose "
                    "a targeted edit_file instead.", success=False,
                )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        except OSError as e:
            return ToolResult.error(f"cannot write {args['path']}: {e}")
        n_lines = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
        action = "overwrote" if existed else "created"
        return ToolResult(f"{action} {path} ({n_lines} lines, {len(content):,} bytes)")


class EditFile(Tool):
    name = "edit_file"
    description = (
        "Make a targeted edit: replace an EXACT old_string with new_string in a "
        "file. Copy old_string verbatim from read_file output (no line numbers). "
        "If it appears multiple times, include more surrounding lines or set "
        "replace_all=true. Always re-read the file first if unsure of exact text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to find."},
            "new_string": {"type": "string", "description": "Replacement text ('' deletes)."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence. Default false."},
        },
        "required": ["path", "old_string", "new_string"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        try:
            path = ctx.resolve(args["path"])
        except ValueError as e:
            return ToolResult.error(str(e))
        if not path.is_file():
            return ToolResult.error(f"file not found: {args['path']}")
        old, new = args["old_string"], args["new_string"]
        if old == new:
            return ToolResult.error("old_string and new_string are identical — nothing to do")
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as e:
            return ToolResult.error(f"cannot read {args['path']}: {e}")

        text = text.replace("\r\n", "\n")
        old = old.replace("\r\n", "\n")
        new = new.replace("\r\n", "\n")
        count = text.count(old)
        if count == 0:
            return ToolResult.error(
                "old_string not found in file. Re-read the file and copy the exact "
                "text (check whitespace/indentation), then retry."
            )
        replace_all = bool(args.get("replace_all", False))
        if count > 1 and not replace_all:
            return ToolResult.error(
                f"old_string matches {count} locations. Add surrounding lines to make "
                "it unique, or pass replace_all=true."
            )
        new_text = text.replace(old, new) if replace_all else text.replace(old, new, 1)

        diff_lines = list(difflib.unified_diff(
            text.splitlines(), new_text.splitlines(),
            fromfile="before", tofile="after", lineterm="", n=2,
        ))
        shown = diff_lines if len(diff_lines) <= 40 else \
            diff_lines[:20] + ["...[diff truncated]..."] + diff_lines[-10:]
        path.write_text(new_text, encoding="utf-8")
        n = count if replace_all else 1
        return ToolResult(f"edit applied ({n} replacement{'s' if n > 1 else ''}):\n" + "\n".join(shown))


class DeletePath(Tool):
    name = "delete_path"
    description = (
        "Delete a file or (with recursive=true) a directory. ALWAYS asks the "
        "human for confirmation. Never use on anything you haven't inspected."
    )
    parameters = {
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "recursive": {"type": "boolean", "description": "Required true to delete a directory tree."},
        },
        "required": ["path"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        import shutil

        try:
            path = ctx.resolve(args["path"])
        except ValueError as e:
            return ToolResult.error(str(e))
        if not path.exists() and not path.is_symlink():
            return ToolResult.error(f"not found: {args['path']}")
        if path.is_dir() and not args.get("recursive"):
            return ToolResult.error(
                f"{args['path']} is a directory — pass recursive=true to delete it with contents"
            )
        kind = "directory tree" if path.is_dir() else "file"
        if not ctx.confirm("file-delete", f"DELETE {kind}: {path}?"):
            return ToolResult("Cancelled by user — nothing deleted.", success=False)
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as e:
            return ToolResult.error(f"delete failed: {e}")
        return ToolResult(f"deleted {kind}: {path}")
