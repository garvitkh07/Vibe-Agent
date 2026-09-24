"""Test runner tool — detects the project's test framework and runs it."""

from __future__ import annotations

from typing import Any, Dict

from .base import ExecContext, Tool, ToolResult
from .terminal import ENV_OVERRIDES
from ..utils import truncate_middle

import os
import subprocess


class RunTests(Tool):
    name = "run_tests"
    description = (
        "Detect and run the project's test suite (pytest/unittest/npm test/"
        "cargo test/go test) and return real results. Prefer this over raw "
        "run_command when verifying changes."
    )
    parameters = {
        "type": "object",
        "properties": {
            "framework": {
                "type": "string",
                "description": "Force a framework: pytest | unittest | npm | cargo | go. Default: auto-detect.",
            },
            "target": {
                "type": "string",
                "description": "Optional scope, e.g. 'tests/test_api.py' or a single test name.",
            },
        },
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        root = ctx.root
        framework = args.get("framework") or self._detect(root)
        target = args.get("target", "")

        if framework == "pytest":
            cmd = "python -m pytest -q" + (f" {target}" if target else "")
        elif framework == "unittest":
            cmd = "python -m unittest discover -v" + (f" -p {target}" if target else "")
        elif framework == "npm":
            cmd = "npm test" + (f" -- {target}" if target else "")
        elif framework == "cargo":
            cmd = "cargo test" + (f" {target}" if target else "")
        elif framework == "go":
            cmd = "go test ./..." + (f" -run {target}" if target else "")
        else:
            return ToolResult.error(
                "could not detect a test framework (looked for pytest.ini, "
                "pyproject.toml [tool.pytest], tests/, package.json, Cargo.toml, "
                "go.mod). Pass 'framework' explicitly."
            )

        env = os.environ.copy()
        env.update(ENV_OVERRIDES)
        try:
            proc = subprocess.run(
                cmd, shell=True, cwd=str(root), capture_output=True,
                text=True, timeout=300, env=env,
            )
        except subprocess.TimeoutExpired:
            return ToolResult.error(f"test run timed out: {cmd}")
        except OSError as e:
            return ToolResult.error(f"failed to run tests: {e}")

        out = (proc.stdout or "") + (("\n--- stderr ---\n" + proc.stderr) if proc.stderr.strip() else "")
        verdict = "PASS" if proc.returncode == 0 else "FAIL"
        body = truncate_middle(out.strip() or "(no output)", 6000)
        return ToolResult(f"tests {verdict} — `{cmd}` (exit {proc.returncode})\n{body}",
                          success=proc.returncode == 0)

    @staticmethod
    def _detect(root) -> str:
        if (root / "pytest.ini").is_file() or (root / "tests").is_dir():
            return "pytest"
        pp = root / "pyproject.toml"
        if pp.is_file() and "[tool.pytest" in pp.read_text(errors="replace"):
            return "pytest"
        pkg = root / "package.json"
        if pkg.is_file() and '"test"' in pkg.read_text(errors="replace"):
            return "npm"
        if (root / "Cargo.toml").is_file():
            return "cargo"
        if (root / "go.mod").is_file():
            return "go"
        if list(root.glob("test_*.py")):
            return "unittest"
        return ""
