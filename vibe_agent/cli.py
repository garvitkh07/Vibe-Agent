"""CLI entry point: argument parsing, the interactive REPL, one-shot mode,
human confirmation prompts, and `--check` environment diagnostics."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .agent import Agent, AgentUI
from .config import load_config, save_example_config
from .context import SessionStore
from .llm.base import LLMError
from .llm.factory import create_backend
from .tools.base import ExecContext, ToolResult
from .tools.memory import MEMORY_TEMPLATE

# ANSI helpers ---------------------------------------------------------------
_TTY = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
if os.name == "nt":
    os.system("")  # enable VT escape codes on Windows terminals


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _TTY else text


def bold(t): return _c("1", t)
def dim(t): return _c("2", t)
def cyan(t): return _c("36", t)
def green(t): return _c("32", t)
def yellow(t): return _c("33", t)
def red(t): return _c("31", t)


# ---------------------------------------------------------------------------
def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vibe",
        description="Vibe — your local-first AI developer agent.",
        epilog="examples:  vibe | vibe --provider fake --yes \"run your demo\" | vibe --check",
    )
    p.add_argument("task", nargs="*", help="one-shot task (runs once, then exits)")
    p.add_argument("--provider", help="ollama | openai | anthropic | gemini | openai-compat | fake")
    p.add_argument("--model", help="model name, e.g. qwen2.5-coder:7b")
    p.add_argument("--project", default=".", help="project root (default: current directory)")
    p.add_argument("--yes", action="store_true", help="auto-approve risky operations (still blocks deny-list)")
    p.add_argument("--max-steps", type=int, help="max tool rounds per turn (default 30)")
    p.add_argument("--no-stream", action="store_true", help="disable token streaming")
    p.add_argument("--init", action="store_true", help="scaffold .vibe/ in the project and exit")
    p.add_argument("--check", action="store_true", help="diagnose your environment and exit")
    p.add_argument("--version", action="version", version=f"vibe {__version__}")
    return p


def make_confirm_fn(mode: str):
    """Human confirmation gate wired into every risky tool call."""

    def confirm(category: str, details: str) -> bool:
        if mode == "auto":
            print(yellow(f"  ⚠ auto-approved [{category}] {details.splitlines()[0]}"))
            return True
        print(yellow(f"\n⚠ CONFIRMATION REQUIRED [{category}]"))
        print(dim(details))
        try:
            answer = input(yellow("  approve? [y/N] ")).strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        return answer in ("y", "yes")

    return confirm


def make_ui() -> AgentUI:
    def on_text(chunk: str) -> None:
        print(chunk, end="", flush=True)

    def on_tool_call(name: str, args: str) -> None:
        print(cyan(f"\n⚙ {name}"), dim(args), flush=True)

    def on_tool_result(result: ToolResult) -> None:
        if result.success:
            preview = result.output.strip().splitlines()
            head = "\n".join(preview[:4])[:400]
            print(green("  ✓"), dim(head), flush=True)
        else:
            print(red("  ✗ " + result.output.strip()[:600]), flush=True)

    def on_error(msg: str) -> None:
        if _streaming():
            print()
        print(red(f"\nerror: {msg}"), flush=True)

    return AgentUI(on_text=on_text, on_tool_call=on_tool_call,
                   on_tool_result=on_tool_result, on_error=on_error)


def _streaming() -> bool:
    return False  # placeholder for future fine-grained tracking


# ---------------------------------------------------------------------------
def cmd_check(args) -> int:
    print(bold("Vibe environment check"), dim(f"v{__version__}"))
    print(f"  python      : {sys.version.split()[0]} {'✓' if sys.version_info >= (3, 9) else '✗ (need >= 3.9)'}")
    print(f"  git         : {'found' if os.path.exists(find_git()) else 'NOT FOUND (git tools will fail)'}")

    root = Path(args.project).expanduser().resolve()
    print(f"  project     : {root} {'✓' if root.is_dir() else '✗ missing'}")

    overrides = _overrides_from_args(args)
    ok_all = True
    for provider in ("ollama", "openai", "anthropic", "gemini", "fake"):
        overrides["provider"] = provider
        try:
            cfg = load_config(root, overrides)
            if provider == "openai" and not os.environ.get("OPENAI_API_KEY"):
                print(yellow("  openai      : skipped (OPENAI_API_KEY not set)"))
                continue
            if provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
                print(yellow("  anthropic   : skipped (ANTHROPIC_API_KEY not set)"))
                continue
            if provider == "gemini" and not os.environ.get("GEMINI_API_KEY"):
                print(yellow("  gemini      : skipped (GEMINI_API_KEY not set)"))
                continue
            backend = create_backend(cfg)
            status = backend.check()
            print(green(f"  {provider:11}: {status}"))
        except LLMError as e:
            ok_all = False
            if provider in ("ollama",):
                print(red(f"  {provider:11}: {e}"))
            else:
                print(yellow(f"  {provider:11}: {e}"))
        except Exception as e:  # noqa: BLE001
            ok_all = False
            print(red(f"  {provider:11}: unexpected error: {e}"))

    if not ok_all:
        print(dim("\nOllama not reachable? Install https://ollama.com then:"))
        print(dim("  ollama serve            (usually automatic on install)"))
        print(dim(f"  ollama pull {load_config(root, _overrides_from_args(args)).effective_model()}"))
    return 0


def find_git() -> str:
    from shutil import which

    return which("git") or ""


def cmd_init(root: Path) -> int:
    vibe_dir = root / ".vibe"
    vibe_dir.mkdir(parents=True, exist_ok=True)
    memory = vibe_dir / "MEMORY.md"
    if not memory.exists():
        memory.write_text(MEMORY_TEMPLATE, encoding="utf-8")
        print(green(f"created {memory}"))
    example = save_example_config(root)
    print(green(f"created {example}"))
    gitignore = root / ".gitignore"
    entry = ".vibe/sessions/"
    if gitignore.exists():
        text = gitignore.read_text(errors="replace")
        if ".vibe/sessions/" not in text:
            gitignore.write_text(text.rstrip("\n") + f"\n{entry}\n", encoding="utf-8")
            print(green(f"added {entry} to {gitignore}"))
    else:
        gitignore.write_text(f"{entry}\n", encoding="utf-8")
        print(green(f"created {gitignore}"))
    print("\nNext: pick a brain →")
    print(dim("  ollama pull qwen2.5-coder:7b   # local, no API key"))
    print(dim("  python vibe.py                 # start the agent"))
    return 0


def _overrides_from_args(args) -> dict:
    overrides = {}
    if getattr(args, "provider", None):
        overrides["provider"] = args.provider
    if getattr(args, "model", None):
        overrides["model"] = args.model
    if getattr(args, "max_steps", None):
        overrides["max_steps"] = args.max_steps
    if getattr(args, "no_stream", False):
        overrides["stream"] = False
    if getattr(args, "yes", False):
        overrides["confirm_mode"] = "auto"
    return overrides


# ---------------------------------------------------------------------------
def build_agent(args) -> Agent:
    root = Path(args.project).expanduser().resolve()
    config = load_config(root, _overrides_from_args(args))
    backend = create_backend(config)
    from .tools import build_default_registry

    registry = build_default_registry()
    ctx = ExecContext(root=root, config=config, confirm_fn=make_confirm_fn(config.confirm_mode))
    return Agent(backend=backend, registry=registry, ctx=ctx, config=config)


HELP_TEXT = """\
commands:
  /help              show this help
  /init              scaffold .vibe/ (memory + example config) in this project
  /model [NAME]      show or switch the model
  /provider [NAME]   show or switch the provider (ollama, openai, anthropic, gemini, fake)
  /tools             list available tools
  /memory            show project memory (.vibe/MEMORY.md)
  /tree              quick project tree
  /context           estimate current context size
  /clear             start a fresh conversation
  /resume            load a previous session transcript
  /quit              exit (also Ctrl-D)
anything else you type is sent to the agent as your instruction.
"""


def repl(agent: Agent, args) -> int:
    cfg = agent.config
    print(bold(f"\n◆ Vibe v{__version__}") + dim(f"  provider={cfg.provider}  model={cfg.effective_model()}"))
    print(dim(f"  project={agent.ctx.root}  confirm={cfg.confirm_mode}  /help for commands\n"))
    while True:
        try:
            line = input(cyan("you › ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(dim("\nbye"))
            return 0
        if not line:
            continue
        if line.startswith("/"):
            cmd, *rest = line.split(maxsplit=1)
            arg = rest[0].strip() if rest else ""
            if cmd in ("/quit", "/exit", "/q"):
                print(dim("bye"))
                return 0
            elif cmd == "/help":
                print(HELP_TEXT)
            elif cmd == "/clear":
                agent.reset()
                print(green("conversation cleared (memory kept)"))
            elif cmd == "/tools":
                for t in agent.registry.all():
                    name = f"{t.name:<18}"
                    print(f"  {cyan(name)} {dim(t.description[:90])}")
            elif cmd == "/memory":
                from .tools.memory import read_memory

                content = read_memory(agent.ctx.root)
                print(content or dim("(memory empty — /init creates it)"))
            elif cmd == "/tree":
                result = agent.executor.execute("project_tree", {})
                print(result.output)
            elif cmd == "/context":
                print(dim(f"history ≈ {agent.context_size():,} tokens (budget {agent.config.max_context_tokens:,})"))
            elif cmd == "/model":
                if arg:
                    agent.config.model = arg
                    agent.backend = create_backend(agent.config)
                    print(green(f"model → {arg}"))
                else:
                    print(f"model: {agent.config.effective_model()}")
            elif cmd == "/provider":
                if arg:
                    agent.config.provider = arg.lower()
                    agent.config.model = None
                    try:
                        agent.backend = create_backend(agent.config)
                        print(green(f"provider → {agent.backend.name} (model {agent.config.effective_model()})"))
                    except LLMError as e:
                        print(red(str(e)))
                else:
                    print(f"provider: {agent.config.provider}")
            elif cmd == "/resume":
                sessions = SessionStore.list_sessions(agent.ctx.root)
                if not sessions:
                    print(dim("no saved sessions yet"))
                    continue
                for i, s in enumerate(sessions[:10]):
                    print(f"  [{i}] {s.name}")
                try:
                    pick = input("index to resume (empty=cancel): ").strip()
                    if pick:
                        msgs = SessionStore.load(sessions[int(pick)])
                        agent.load_history(msgs)
                        print(green(f"loaded {len(msgs)} messages"))
                except (ValueError, IndexError, EOFError):
                    print(yellow("cancelled"))
            elif cmd == "/init":
                cmd_init(agent.ctx.root)
            else:
                print(yellow(f"unknown command {cmd} — /help lists commands"))
            continue

        try:
            agent.run_turn(line)
            print(dim(f"\n[turn done · ctx ≈ {agent.context_size():,} tk]"))
        except KeyboardInterrupt:
            print(yellow("\n[interrupted — partial turn kept in history]"))
        print()


def main(argv=None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.check:
        return cmd_check(args)

    root = Path(args.project).expanduser().resolve()

    if args.init:
        return cmd_init(root)

    if not root.is_dir():
        print(red(f"project root not found: {root}"))
        return 1

    try:
        agent = build_agent(args)
    except (LLMError, ValueError) as e:
        print(red(f"startup failed: {e}"))
        return 1

    ui = make_ui()
    agent.ui = ui

    task = " ".join(args.task).strip()
    if task:
        try:
            agent.run_turn(task)
            print()
            return 0
        except KeyboardInterrupt:
            print(yellow("\n[interrupted]"))
            return 130

    return repl(agent, args)


if __name__ == "__main__":
    sys.exit(main())
