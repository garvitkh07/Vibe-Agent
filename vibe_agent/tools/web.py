"""Web fetch tool — lets the agent read a URL (docs, API specs, error pages).

Human approval is required on every fetch (network = data leaves the
machine). HTML is stripped to readable text with a tiny regex pipeline —
good enough for docs, not a browser.
"""

from __future__ import annotations

import html as html_mod
import re
import urllib.request
from typing import Any, Dict

from .base import ExecContext, Tool, ToolResult
from ..utils import truncate_middle

MAX_FETCH_CHARS = 20_000
MAX_FETCH_BYTES = 2_000_000

_TAG_SCRIPT = re.compile(r"<(script|style|noscript|svg|head)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TAG_BR = re.compile(r"<(br|/p|/div|/li|/h[1-6]|/tr)[^>]*>", re.IGNORECASE)
_TAG_ANY = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t]+")
_BLANK = re.compile(r"\n{3,}")


class FetchUrl(Tool):
    name = "fetch_url"
    description = (
        "Fetch a URL and return its text content (HTML stripped). Use for "
        "documentation, API specs, error pages. Requires user approval. "
        "Binary/JS-heavy pages may return little useful text."
    )
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "Must start with http:// or https://."},
            "max_chars": {"type": "integer", "description": "Max returned characters. Default 20000."},
        },
        "required": ["url"],
    }

    def run(self, args: Dict[str, Any], ctx: ExecContext) -> ToolResult:
        url = str(args["url"]).strip()
        if not url.lower().startswith(("http://", "https://")):
            return ToolResult.error("only http:// and https:// URLs are allowed")
        # Block obvious localhost probes from a compromised model.
        if "localhost" in url or "127.0.0.1" in url or "0.0.0.0" in url:
            return ToolResult.error("refusing to fetch localhost — test APIs with run_command/curl instead")

        if not ctx.confirm("network", f"Fetch URL:\n    {url}"):
            return ToolResult("Cancelled by user — fetch not performed.", success=False)

        req = urllib.request.Request(
            url, headers={"User-Agent": "Mozilla/5.0 (compatible; VibeAgent/0.1)"}
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                ctype = resp.headers.get("Content-Type", "")
                raw = resp.read(MAX_FETCH_BYTES)
        except Exception as e:
            return ToolResult.error(f"fetch failed: {e}")

        if "html" in ctype or raw[:256].lstrip().lower().startswith(b"<!doctype html"):
            text = raw.decode("utf-8", errors="replace")
            text = _TAG_SCRIPT.sub(" ", text)
            text = _TAG_BR.sub("\n", text)
            text = _TAG_ANY.sub(" ", text)
            text = html_mod.unescape(text)
            text = _WS.sub(" ", text)
            text = _BLANK.sub("\n\n", text)
        else:
            text = raw.decode("utf-8", errors="replace")

        limit = min(int(args.get("max_chars", MAX_FETCH_CHARS)), MAX_FETCH_CHARS)
        return ToolResult(f"content-type: {ctype}\n{truncate_middle(text.strip(), limit)}")
