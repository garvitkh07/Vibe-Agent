"""Vibe — a local-first AI developer agent with a swappable LLM brain.

Architecture:
    LLM backends (ollama / openai / anthropic / gemini / openai-compatible / fake)
        -> Agent orchestration loop (ReAct-style reasoning + tool calling)
        -> Tool layer (filesystem, search, terminal, git, testing, project, memory, web)
        -> Safety layer (deny / ask / allow classification + human confirmation)
        -> Context management (trimming, project memory, session transcripts)
"""

__version__ = "0.1.0"

__all__ = ["__version__"]
