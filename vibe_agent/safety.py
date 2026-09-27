"""Command safety classifier.

Three verdicts:
    ALLOW — safe dev commands, run without asking (pytest, ls, git diff, ...)
    ASK   — potentially destructive / system-affecting; requires human approval
    DENY  — clearly catastrophic or integrity-destroying; refused outright

Policy order: DENY patterns win over everything, then ALLOW list, then
anything unrecognised defaults to ASK. Tune the lists freely — they are
plain regexes at the top of this file.

The classifier is a guardrail for an agent YOU run on YOUR machine — it
reduces accidents, it is not a security sandbox against a hostile model.
Review what the agent does; use --yes only for tasks you understand.
"""

from __future__ import annotations

import re
from typing import List, Tuple

ALLOW, ASK, DENY = "ALLOW", "ASK", "DENY"

# (regex, human-readable reason) — catastrophic: refuse, never run.
DENY_PATTERNS: List[Tuple[str, str]] = [
    (r"\brm\s+(?:-{1,2}[\w-]+\s+)*(?:/\s*$|/\*|~(?:\s|$)|\$HOME)", "recursive delete of root/home"),
    (r"--no-preserve-root", "rm --no-preserve-root"),
    (r"\bmkfs(\.\w+)?\b", "filesystem format"),
    (r"\bdd\b[^|;&]*\bof=/dev/(?:sd|nvme|hd|disk|mapper)", "raw disk write via dd"),
    (r">\s*/dev/(?:sd|nvme|hd)", "raw disk overwrite"),
    (r":\(\)\s*\{.*\};\s*:", "fork bomb"),
    (r"\b(?:shutdown|reboot|halt|poweroff)\b", "shutdown/reboot"),
    (r"\b(?:init|telinit)\s+[06]\b", "change runlevel"),
    (r"(?:curl|wget)\b[^|;&]*\|\s*(?:sudo\s+)?(?:ba|z|da|k)?sh\b", "pipe-to-shell download"),
    (r"\bchmod\s+-R\s+\d{3,4}\s+/(?:\s|$)", "chmod -R on filesystem root"),
    (r"\bchown\s+-R\s+\S+\s+/(?:\s|$)", "chown -R on filesystem root"),
    (r"[a-zA-Z]:\\(?:Windows|Program Files)", "targeting Windows system dirs"),
]

# Potentially destructive: run only after explicit human approval.
ASK_PATTERNS: List[Tuple[str, str]] = [
    (r"\brm\s+-(?:\w*r\w*|\w*f\w*)", "rm with -r/-f"),
    (r"\brmdir\b", "remove directory"),
    (r"\bsudo\b", "superuser command"),
    (r"\bkill\b", "kill process"),
    (r"\bpkill\b", "pkill process"),
    (r"\bgit\s+push\b[^;&|]*--(?:force|f)\b", "force-push"),
    (r"\bgit\s+push\b.*(?:--delete|-d)\b", "delete remote branch"),
    (r"\bgit\s+reset\s+--hard\b", "git reset --hard (discards changes)"),
    (r"\bgit\s+clean\s+-(?:\w*f)", "git clean -f (deletes untracked files)"),
    (r"\bgit\s+checkout\s+--\s", "discard working-tree changes"),
    (r"\bgit\s+restore\b", "git restore (may discard changes)"),
    (r"\bgit\s+branch\s+-(?:\w*D\w*)", "force-delete branch"),
    (r"\bgit\s+rebase\b", "rebase rewrites history"),
    (r"\bgit\s+filter-branch\b", "rewrite history"),
    (r"\bgit\s+stash\s+(?:drop|clear)\b", "drop stashes"),
    (r"\bdocker\s+(?:system\s+prune|rm|rmi|volume\s+rm|down)\b", "destructive docker op"),
    (r"\bkubectl\s+delete\b", "kubectl delete"),
    (r"\bdrop\s+(?:database|table)\b", "DROP DATABASE/TABLE"),
    (r"\btruncate\s+table\b", "TRUNCATE TABLE"),
    (r"\bsed\b[^|;&]*\s-i\b", "sed -i edits files in place"),
    (r"\bmv\b", "move/rename (may overwrite)"),
    (r"\bapt(?:-get)?\s+(?:install|remove|purge|upgrade|autoremove)\b", "system package change"),
    (r"\bdnf\s+(?:install|remove|upgrade)\b", "system package change"),
    (r"\bbrew\s+(?:install|uninstall|upgrade)\b", "system package change"),
    (r"\bpip(?:3)?\s+install\s+[^;&|]*(?:--user|--break-system-packages|-U|--upgrade)\b",
     "global/user pip upgrade or override"),
    (r"\bnpx\b", "npx executes arbitrary packages"),
    (r"\bpython(?:3)?\s+-c\b", "inline Python code execution"),
    (r"\bchmod\s+-R\b", "recursive permission change"),
    (r"\bchown\s+-R\b", "recursive ownership change"),
    (r"\bcurl\b|\bwget\b", "network request (data leaves the machine)"),
    (r"\bssh\b|\bscp\b", "remote machine access"),
    (r"\bcrontab\b", "cron modification"),
    (r"\bkillall\b", "killall processes"),
    (r"\b>\s*/etc/", "write to /etc"),
    (r"\bhistory\s+-c\b", "clear shell history"),
]

# Safe everyday dev commands: prefix-matched (command head).
SAFE_PREFIXES = [
    "ls", "dir", "pwd", "echo", "cat", "head", "tail", "wc", "file", "stat",
    "tree", "which", "whereis", "whoami", "date", "uname", "env", "printenv",
    "grep", "rg", "find", "fd", "diff", "sort", "uniq", "cut", "awk",
    "sed -n", "true", "sleep",
    "python", "python3", "pytest", "py.test", "pip", "pip3",
    "node", "npm install", "npm ci", "npm run", "npm test", "npm start", "npm init",
    "yarn", "pnpm",
    "git status", "git diff", "git log", "git show", "git branch", "git remote",
    "git add", "git commit", "git stash", "git tag", "git switch", "git checkout",
    "git init", "git config --get",
    "go build", "go test", "go vet", "go run", "gofmt",
    "cargo build", "cargo check", "cargo test", "cargo run", "cargo clippy",
    "make", "cmake",
    "mkdir", "touch", "cp",
    "docker ps", "docker images", "docker logs", "docker build",
    "docker compose up", "docker compose build", "docker compose logs", "docker compose config",
]

_COMPOUND_SPLIT = re.compile(r"\s*(?:&&|\|\||;)\s*")

_COMPILED_DENY = [(re.compile(p, re.IGNORECASE), r) for p, r in DENY_PATTERNS]
_COMPILED_ASK = [(re.compile(p, re.IGNORECASE), r) for p, r in ASK_PATTERNS]


def classify(command: str) -> Tuple[str, str]:
    """Return (verdict, reason) for a shell command string."""
    cmd = command.strip()
    if not cmd:
        return DENY, "empty command"

    # 1) Deny-list wins over everything, checked on the FULL command so that
    #    pipes like `curl ... | sh` are caught.
    for rx, reason in _COMPILED_DENY:
        if rx.search(cmd):
            return DENY, reason

    # 2) Evaluate each segment of compound commands separately.
    segments = [s for s in _COMPOUND_SPLIT.split(cmd) if s.strip()]
    ask_reasons: List[str] = []
    for seg in segments:
        verdict, reason = _classify_simple(seg.strip())
        if verdict == DENY:
            return DENY, reason
        if verdict == ASK:
            ask_reasons.append(reason)
    if ask_reasons:
        return ASK, "; ".join(sorted(set(ask_reasons)))
    return ALLOW, "safe command"


def _classify_simple(cmd: str) -> Tuple[str, str]:
    for rx, reason in _COMPILED_ASK:
        if rx.search(cmd):
            return ASK, reason
    head = cmd.split()[0] if cmd.split() else ""
    if any(cmd.startswith(prefix + " ") or cmd == prefix for prefix in SAFE_PREFIXES):
        return ALLOW, "safe command"
    if head in ("ls", "cat", "echo", "git", "grep", "find", "python", "python3"):
        # known-good binaries with unlisted subcommands: still allow common reads
        return ALLOW, "safe command"
    return ASK, "unrecognised command — not on the safe list"
