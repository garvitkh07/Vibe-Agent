"""Project inspection: a fast, dependency-aware summary of the codebase."""

from __future__ import annotations

import json
from collections import Counter
from typing import Any, Dict, List

from .base import ExecContext, Tool, ToolResult
from ..utils import IGNORE_DIRS

KEY_FILES = [
    "README.md", "pyproject.toml", "setup.py", "setup.cfg", "requirements.txt",
    "Pipfile", "package.json", "tsconfig.json", "Cargo.toml", "go.mod",
    "Dockerfile", "docker-compose.yml", "Makefile", "CMakeLists.txt",
    ".github/workflows", "tox.ini", "pytest.ini", ".env.example",
]

ENTRY_HINTS = [
    "main.py", "app.py", "manage.py", "run.py", "server.py", "cli.py",
    "index.js", "index.ts", "main.ts", "src/main.py", "src/index.ts",
    "src/app.py", "cmd/main.go", "src/main.rs",
]

LANG_BY_EXT = {
    ".py": "Python", ".ipynb": "Notebook", ".js": "JavaScript", ".jsx": "JSX",
    ".ts": "TypeScript", ".tsx": "TSX", ".rs": "Rust", ".go": "Go",
    ".c": "C", ".h": "C/C++ header", ".cpp": "C++", ".cc": "C++", ".hpp": "C++ header",
    ".java": "Java", ".kt": "Kotlin", ".rb": "Ruby", ".php": "PHP",
    ".cs": "C#", ".sql": "SQL", ".sh": "Shell", ".yaml": "YAML", ".yml": "YAML",
    ".toml": "TOML", ".json": "JSON", ".md": "Markdown", ".html": "HTML",
    ".css": "CSS", ".scss": "SCSS", ".swift": "Swift",
}


class ProjectSummary(Tool):
    name = "project_summary"
    description = (
        "One-screen overview of the project: languages used, stack hints, key "
        "files, likely entry points, and dependency files. The ideal first call "
        "on an unfamiliar repo — cheaper than reading many files."
    )
    parameters = {"type": "object", "properties": {}}

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        root = ctx.root
        ext_counts: Counter = Counter()
        file_count = 0
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            parts = path.parts
            if any(p in IGNORE_DIRS or p.endswith(".egg-info") for p in parts[:-1]):
                continue
            file_count += 1
            if path.suffix:
                ext_counts[path.suffix.lower()] += 1

        lines: List[str] = [f"project root: {root}", f"total files: {file_count:,}"]

        langs = [f"{LANG_BY_EXT.get(ext, ext)} ({n})" for ext, n in ext_counts.most_common(10)]
        lines.append("languages: " + (", ".join(langs) if langs else "(none found)"))

        present = [k for k in KEY_FILES if (root / k).exists()]
        lines.append("key files: " + (", ".join(present) if present else "(none)"))

        entries = [e for e in ENTRY_HINTS if (root / e).is_file()]
        lines.append("entry points: " + (", ".join(entries) if entries else "(not obvious — search for main/__main__)"))

        lines.append(f"git repo: {'yes' if (root / '.git').is_dir() else 'no'}")
        lines.append(f"virtualenv present: {'yes (.venv)' if (root / '.venv').is_dir() else 'no'}")

        req = root / "requirements.txt"
        if req.is_file():
            deps = [l.strip() for l in req.read_text(errors="replace").splitlines()
                    if l.strip() and not l.startswith("#")]
            lines.append(f"requirements.txt: {len(deps)} dependencies: {', '.join(deps[:20])}")

        pkg = root / "package.json"
        if pkg.is_file():
            try:
                data = json.loads(pkg.read_text(errors="replace"))
                deps = sorted((data.get("dependencies") or {}).keys())
                scripts = sorted((data.get("scripts") or {}).keys())
                lines.append(f"package.json deps: {', '.join(deps[:20]) or '(none)'}")
                lines.append(f"npm scripts: {', '.join(scripts) or '(none)'}")
            except json.JSONDecodeError:
                lines.append("package.json: present but invalid JSON")

        pyproj = root / "pyproject.toml"
        if pyproj.is_file():
            text = pyproj.read_text(errors="replace")
            for marker in ("[tool.pytest", "[project]", "[build-system]", "[tool.ruff]"):
                if marker in text:
                    lines.append(f"pyproject.toml contains {marker}]")

        return ToolResult("\n".join(lines))
