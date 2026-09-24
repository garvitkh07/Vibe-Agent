"""Search tools: ripgrep-style content search and file-name finding.

Both walk the project root, skipping IGNORE_DIRS (node_modules, .git,
venvs, build output...) and binary-looking files.
"""

from __future__ import annotations

import fnmatch
import re
from pathlib import Path
from typing import Any, Dict, List

from .base import ExecContext, Tool, ToolResult
from ..utils import BINARY_HINT_EXTS, IGNORE_DIRS

LINE_CLIP = 200
MAX_OUTPUT_CHARS = 30_000


def _walk(root: Path):
    """Yield text files under root, skipping ignored/binary dirs."""
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            if path.name in IGNORE_DIRS or path.name.endswith(".egg-info"):
                # rglob keeps descending anyway; prune via parts check below
                continue
            continue
        parts = path.parts
        if any(part in IGNORE_DIRS or part.endswith(".egg-info") for part in parts[:-1]):
            continue
        if path.suffix.lower() in BINARY_HINT_EXTS:
            continue
        yield path


def _read_head(path: Path, max_bytes: int = 1_500_000) -> str:
    try:
        data = path.read_bytes()[:max_bytes]
        if b"\x00" in data:
            return ""
        return data.decode("utf-8", errors="replace")
    except OSError:
        return ""


class SearchFiles(Tool):
    name = "search_files"
    description = (
        "Regex search across project files. Returns 'path:line: text' matches. "
        "Use for finding definitions, usages, TODOs, error strings, config keys. "
        "Ignore dirs (node_modules, .git, venvs...) are skipped automatically."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regex, e.g. 'def train\\(' or 'TODO'."},
            "glob": {"type": "string", "description": "Optional filename filter, e.g. '*.py' or '*.ts'."},
            "path": {"type": "string", "description": "Subdirectory to search. Default '.'."},
            "ignore_case": {"type": "boolean", "description": "Default true."},
            "max_results": {"type": "integer", "description": "Default 80."},
        },
        "required": ["pattern"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        try:
            flags = re.IGNORECASE if args.get("ignore_case", True) else 0
            rx = re.compile(args["pattern"], flags)
        except re.error as e:
            return ToolResult.error(f"invalid regex: {e}")
        glob = args.get("glob")
        base = ctx.resolve(args.get("path", "."))
        if not base.is_dir():
            return ToolResult.error(f"not a directory: {args.get('path', '.')}")
        limit = min(int(args.get("max_results", 80)), 400)

        hits: List[str] = []
        truncated = False
        for path in _walk(base):
            if glob and not fnmatch.fnmatch(path.name, glob):
                continue
            rel = path.relative_to(ctx.root)
            for lineno, line in enumerate(_read_head(path).splitlines(), 1):
                if rx.search(line):
                    clipped = line.strip()[:LINE_CLIP]
                    hits.append(f"{rel}:{lineno}: {clipped}")
                    if len(hits) >= limit or sum(len(h) for h in hits) > MAX_OUTPUT_CHARS:
                        truncated = True
                        break
            if truncated:
                break
            if len(hits) >= limit:
                truncated = True
                break

        if not hits:
            return ToolResult(f"no matches for /{args['pattern']}/")
        out = "\n".join(hits)
        if truncated:
            out += f"\n...[stopped at {len(hits)} results — narrow the pattern or glob]"
        return ToolResult(out)


class FindFiles(Tool):
    name = "find_files"
    description = (
        "Find files by name pattern (fnmatch), e.g. '*.py', 'Dockerfile*', "
        "'test_*.py'. Returns paths sorted by depth."
    )
    parameters = {
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Filename glob, e.g. '*.ts'."},
            "path": {"type": "string", "description": "Subdirectory. Default '.'."},
            "max_results": {"type": "integer", "description": "Default 120."},
        },
        "required": ["pattern"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        pattern = args["pattern"]
        base = ctx.resolve(args.get("path", "."))
        if not base.is_dir():
            return ToolResult.error(f"not a directory: {args.get('path', '.')}")
        limit = min(int(args.get("max_results", 120)), 500)
        matches: List[str] = []
        for path in _walk(base):
            if fnmatch.fnmatch(path.name, pattern) or fnmatch.fnmatch(str(path.relative_to(ctx.root)), pattern):
                matches.append(str(path.relative_to(ctx.root)))
                if len(matches) >= limit:
                    break
        if not matches:
            return ToolResult(f"no files matching '{pattern}'")
        return ToolResult("\n".join(matches) + (f"\n...[capped at {limit}]" if len(matches) >= limit else ""))
