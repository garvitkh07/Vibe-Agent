"""Configuration with layered defaults:

    built-in defaults  <-  ~/.vibe/config.json  <-  <project>/.vibe/config.json  <-  CLI flags

Secrets (API keys) are NEVER stored in config files — they are read from
environment variables only (see factory.py). This keeps keys out of repos
and out of backups.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
DEFAULT_OPENAI_BASE = "https://api.openai.com/v1"
DEFAULT_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta/openai"
DEFAULT_ANTHROPIC_BASE = "https://api.anthropic.com"

# Sensible defaults per provider; always overridable with --model or config.
DEFAULT_MODELS = {
    "ollama": "qwen2.5-coder:7b",
    "openai": "gpt-4o-mini",
    "anthropic": "claude-sonnet-4-20250514",
    "gemini": "gemini-2.0-flash",
    "fake": "fake-1",
}

PROVIDERS = ("ollama", "openai", "anthropic", "gemini", "openai-compat", "fake")

CONFIRM_MODES = ("ask", "auto", "strict")


@dataclass
class AgentConfig:
    provider: str = "ollama"
    model: Optional[str] = None            # None -> DEFAULT_MODELS[provider]
    ollama_host: str = ""                  # "" -> OLLAMA_HOST env or default
    openai_base_url: str = ""              # "" -> OPENAI_BASE_URL env or default
    gemini_base_url: str = ""
    temperature: float = 0.2
    max_steps: int = 30                    # max tool-call rounds per user turn
    max_context_tokens: int = 32_000
    max_tool_output_chars: int = 12_000
    # ask    = confirm operations classified as needing human approval (default)
    # auto   = auto-approve those (still blocks deny-listed commands) — --yes
    # strict = confirm every command/file mutation
    confirm_mode: str = "ask"
    stream: bool = True
    use_native_tools: bool = True          # False -> JSON protocol adapter

    def effective_model(self) -> str:
        return self.model or DEFAULT_MODELS.get(self.provider, "unknown")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (json.JSONDecodeError, OSError) as e:
        print(f"[vibe] warning: could not read config {path}: {e}")
        return {}


def _apply(cfg: AgentConfig, data: Dict[str, Any]) -> None:
    known = {f for f in cfg.__dataclass_fields__}  # type: ignore[attr-defined]
    for key, value in data.items():
        if key in known and value is not None:
            setattr(cfg, key, value)


def load_config(project_root: Path, overrides: Optional[Dict[str, Any]] = None) -> AgentConfig:
    cfg = AgentConfig()
    home_file = Path.home() / ".vibe" / "config.json"
    proj_file = project_root / ".vibe" / "config.json"
    _apply(cfg, _read_json(home_file))
    _apply(cfg, _read_json(proj_file))
    if overrides:
        _apply(cfg, overrides)

    if cfg.provider not in PROVIDERS:
        raise ValueError(
            f"Unknown provider '{cfg.provider}'. Valid: {', '.join(PROVIDERS)}"
        )
    if cfg.confirm_mode not in CONFIRM_MODES:
        raise ValueError(
            f"confirm_mode must be one of {CONFIRM_MODES}, got '{cfg.confirm_mode}'"
        )
    cfg.provider = cfg.provider.lower()
    return cfg


def save_example_config(project_root: Path) -> Path:
    """Write an annotated example config the user can rename/edit."""
    example = AgentConfig()
    path = project_root / ".vibe" / "config.example.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(example.to_dict(), f, indent=2)
        f.write("\n")
    return path
