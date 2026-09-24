"""Tool base classes, execution context and registry.

Adding a new tool = subclass Tool, fill in name/description/parameters,
implement run(), register it in tools/__init__.py. That's it — it is
immediately available to every backend (native tools or JSON protocol).
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolResult:
    output: str
    success: bool = True

    @classmethod
    def error(cls, message: str) -> "ToolResult":
        return cls(output=message, success=False)


ConfirmFn = Callable[[str, str], bool]  # (category, details) -> approved?


class ExecContext:
    """Everything a tool may need at run time."""

    def __init__(self, root: Path, config, confirm_fn: ConfirmFn):
        self.root = root.resolve()
        self.config = config
        self.confirm = confirm_fn

    def resolve(self, path_str: str) -> Path:
        """Resolve a user/model-supplied path INSIDE the project root.

        File tools are confined to the project root — this is a deliberate
        security boundary (the terminal tool is the documented escape hatch,
        and it is guarded by the safety layer).
        """
        raw = Path(path_str).expanduser()
        if not raw.is_absolute():
            raw = self.root / raw
        resolved = Path(os.path.normpath(str(raw)))
        root_str = str(self.root)
        if resolved != self.root and not str(resolved).startswith(root_str + os.sep):
            raise ValueError(
                f"path escapes the project root ({root_str}): {path_str}"
            )
        return resolved


class Tool(ABC):
    """One capability the agent can invoke."""

    name: str = "tool"
    description: str = ""
    # JSON Schema for the arguments object:
    parameters: Dict[str, Any] = {"type": "object", "properties": {}, "required": []}

    @abstractmethod
    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        ...

    def spec(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }


class Registry:
    """Named collection of tools."""

    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, *tools: Tool) -> None:
        for tool in tools:
            if tool.name in self._tools:
                raise ValueError(f"duplicate tool name: {tool.name}")
            self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def all(self) -> List[Tool]:
        return list(self._tools.values())

    def names(self) -> List[str]:
        return sorted(self._tools)

    def specs(self) -> List[Dict[str, Any]]:
        return [t.spec() for t in self._tools.values()]
