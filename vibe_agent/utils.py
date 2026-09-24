"""Small shared helpers: truncation, token estimation, timestamps, ignore dirs."""

from __future__ import annotations

import datetime as _dt

# Directories that are almost never interesting to search or walk.
IGNORE_DIRS = {
    ".git", ".hg", ".svn",
    "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    ".venv", "venv", "env",
    "dist", "build", "out", "target", ".next", ".nuxt", ".output",
    ".cache", ".tox", ".eggs", "htmlcov", "coverage",
    ".idea", ".vscode", ".vibe",
}

BINARY_HINT_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".bmp", ".pdf",
    ".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar",
    ".exe", ".dll", ".so", ".dylib", ".bin", ".o", ".a", ".class",
    ".mp3", ".mp4", ".mkv", ".wav", ".flac", ".avi", ".mov",
    ".woff", ".woff2", ".ttf", ".otf", ".eot", ".sqlite", ".db", ".parquet",
}


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars per token). Good enough for budgeting."""
    return max(1, (len(text) + 3) // 4)


def truncate_middle(text: str, limit: int) -> str:
    """Truncate long output but keep both the beginning (context) and the end
    (where errors usually are)."""
    if limit <= 0 or len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = max(0, limit - head)
    omitted = len(text) - head - tail
    return f"{text[:head]}\n...[{omitted} characters truncated]...\n{text[-tail:]}"


def now_stamp(fmt: str = "%Y-%m-%d %H:%M:%S") -> str:
    return _dt.datetime.now().strftime(fmt)


def today_iso() -> str:
    return _dt.date.today().isoformat()
