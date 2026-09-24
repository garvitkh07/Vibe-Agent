"""Backend factory — the single place where a provider is instantiated.

Providers:
    ollama        local Ollama (default; no API key)
    openai        OpenAI API                (OPENAI_API_KEY)
    anthropic     Anthropic Claude          (ANTHROPIC_API_KEY)
    gemini        Google Gemini via its OpenAI-compatible endpoint (GEMINI_API_KEY)
    openai-compat any OpenAI-compatible URL (set openai_base_url; key optional)
    fake          scripted offline brain for demos/tests

Keys are read from the environment only — never stored in config files.
"""

from __future__ import annotations

import os
from typing import Optional

from .adapter import JsonToolAdapter
from .anthropic import AnthropicBackend
from .base import LLMError, Message  # noqa: F401  (Message re-exported)
from .fake import FakeBackend
from .ollama import OllamaBackend
from .openai_compat import OpenAICompatBackend


def create_backend(config, wrap_json: Optional[bool] = None):
    """Instantiate the configured backend; wrap with the JSON protocol
    adapter when native tool calling is disabled."""
    p = config.provider
    model = config.effective_model()

    if p == "ollama":
        host = (
            config.ollama_host
            or os.environ.get("OLLAMA_HOST")
            or "http://127.0.0.1:11434"
        )
        backend = OllamaBackend(host=host, model=model, stream=config.stream)

    elif p == "openai":
        key = os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise LLMError("OPENAI_API_KEY is not set.\n  export OPENAI_API_KEY=sk-...")
        base = (
            config.openai_base_url
            or os.environ.get("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        )
        backend = OpenAICompatBackend(base, model, api_key=key, label="openai")

    elif p == "gemini":
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        if not key:
            raise LLMError(
                "GEMINI_API_KEY is not set.\n  export GEMINI_API_KEY=...  "
                "(get one at https://aistudio.google.com/apikey)"
            )
        base = config.gemini_base_url or (
            "https://generativelanguage.googleapis.com/v1beta/openai"
        )
        backend = OpenAICompatBackend(base, model, api_key=key, label="gemini")

    elif p == "openai-compat":
        base = config.openai_base_url or os.environ.get("OPENAI_BASE_URL", "")
        if not base:
            raise LLMError(
                "provider 'openai-compat' needs openai_base_url in .vibe/config.json "
                '(e.g. "http://localhost:1234/v1" for LM Studio)'
            )
        key = os.environ.get("OPENAI_API_KEY", "") or None
        backend = OpenAICompatBackend(base, model, api_key=key, label="openai-compat")

    elif p == "anthropic":
        backend = AnthropicBackend(model=model)

    elif p == "fake":
        backend = FakeBackend()

    else:  # pragma: no cover — load_config validates providers already
        raise LLMError(f"Unknown provider '{p}'")

    use_wrap = config.use_native_tools is False if wrap_json is None else wrap_json
    if use_wrap and not isinstance(backend, FakeBackend):
        return JsonToolAdapter(backend)
    return backend
