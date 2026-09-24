"""Default tool registry assembly.

To add your own tool:
    1. subclass Tool in a module here (name/description/parameters/run)
    2. import it and register it in build_default_registry below
Every backend (native or JSON protocol) picks it up automatically.
"""

from __future__ import annotations

from .base import ExecContext, Registry, Tool, ToolResult  # noqa: F401
from .filesystem import DeletePath, EditFile, ListDir, ProjectTree, ReadFile, WriteFile
from .git_tools import GitBranches, GitCommit, GitDiff, GitLog, GitStatus
from .memory import MemoryRead, MemoryWrite
from .project import ProjectSummary
from .search import FindFiles, SearchFiles
from .terminal import RunCommand
from .testing import RunTests
from .web import FetchUrl


def build_default_registry() -> Registry:
    registry = Registry()
    registry.register(
        # project inspection
        ProjectSummary(),
        ProjectTree(),
        ListDir(),
        # files
        ReadFile(),
        WriteFile(),
        EditFile(),
        DeletePath(),
        # search
        SearchFiles(),
        FindFiles(),
        # execution
        RunCommand(),
        RunTests(),
        # git
        GitStatus(),
        GitDiff(),
        GitLog(),
        GitBranches(),
        GitCommit(),
        # memory
        MemoryRead(),
        MemoryWrite(),
        # web
        FetchUrl(),
    )
    return registry
