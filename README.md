# ◆ Vibe — your personal AI Developer Agent

A local-first **AI software-engineering agent** ("vibe coding agent") that runs in
your terminal, works inside your real projects, and behaves like a senior
developer pair-programming with you — not a code generator.

**Zero dependencies.** Pure Python 3.9+ standard library. The LLM brain is
swappable; the default is a **local Ollama model — no API key, no cloud**.

```
LLM (Ollama / OpenAI / Anthropic / Gemini / OpenAI-compatible / fake)
        │            ← swappable brain: one interface, one factory
        ▼
Agent loop (ReAct orchestration, max-steps guard, context budgeting)
        │            ← understands the task, decides tools, verifies results
        ▼
Tool layer — 19 tools
 ├─ project inspection   project_summary · project_tree · list_dir
 ├─ files                read_file · write_file · edit_file (targeted) · delete_path
 ├─ search               search_files (regex, respects ignore dirs) · find_files
 ├─ terminal             run_command (safety-classified, timeout, output capped)
 ├─ testing              run_tests (pytest / unittest / npm / cargo / go)
 ├─ git                  git_status · git_diff · git_log · git_branches · git_commit
 ├─ memory               memory_read · memory_write (.vibe/MEMORY.md, persists)
 └─ web                  fetch_url (docs/API specs, human-approved)
        │
        ▼
Safety layer — every command/operation classified ALLOW / ASK / DENY
        + human confirmation prompts + JSONL session transcripts
```

---

## Quickstart

### 1. Get a brain (local, free, no API key)

Install [Ollama](https://ollama.com), then:

```bash
ollama pull qwen2.5-coder:7b     # strong coding model with tool calling
```

Other good tool-capable models: `qwen2.5-coder:14b`, `llama3.1:8b`,
`mistral-nemo`, `deepseek-coder-v2:16b`.

### 2. Run Vibe

```bash
cd your-project                 # any project folder
python vibe.py                  # interactive REPL
```

That's it. No `pip install` needed (stdlib only). Optional installer:

```bash
pip install -e .                # gives you a global `vibe` command
```

### 3. Verify your setup

```bash
python vibe.py --check          # python, git, each provider, Ollama models
python vibe.py --provider fake --yes "run your demo"
                                # scripted offline demo of the whole pipeline
```

---

## Using the agent

```bash
python vibe.py                              # REPL in current folder
python vibe.py --project ~/my-app           # work on a specific project
python vibe.py --model llama3.1:8b          # override model
python vibe.py "fix the failing tests"      # one-shot task, then exit
python vibe.py --yes "..."                  # auto-approve risky ops (careful)
```

**REPL commands:** `/help` `/model` `/provider` `/tools` `/memory` `/tree`
`/context` `/clear` `/resume` `/init` `/quit`

Example session:

```
you › why does pytest fail after your last change?
◆ Vibe  ⚙ run_command {"command": "python -m pytest -q"}
         ✓ 1 failed, 3 passed ...
  The failure is in `cart.py:42` — `total` is reset inside the loop, so
  discounts apply only to the last item. Root cause: variable shadowing.
  Smallest fix: ... [applies targeted edit_file, re-runs tests]
  ✓ 4 passed
  Fixed. Verify with: pytest -q. Note: test_discount_bulk only covered the
  happy path — want me to add a regression test?
```

### How it behaves (your standing instructions, built in)

The system prompt (`vibe_agent/prompts.py`) encodes your spec:

- **Workflow:** `WHY → REQUIREMENTS → ARCHITECTURE → TECHNOLOGY → IMPLEMENTATION → TESTING → DEBUGGING → OPTIMIZATION → DEPLOYMENT`
- Understand before modifying; inspect real files, never guess
- Targeted `edit_file` edits, not wholesale rewrites; preserve working code
- Debugging protocol: reproduce → root cause → explain → smallest fix → test → regressions
- Never invent APIs/files/schemas; never hardcode secrets (env vars only)
- Git: explains operations, never force-push/reset/branch-delete without explicit confirmation
- AI/ML: precise vocabulary, no "it works" claims without evaluation evidence
- Teaching-first communication; honest about facts vs assumptions vs recommendations

Edit `prompts.py` to tune the personality — it's plain text, rebuilt every turn.

---

## Swapping the brain

The LLM is isolated behind one interface (`vibe_agent/llm/`). Switch with a
flag or config — the tools, loop, and safety layer are untouched:

| Provider        | Command                                   | Key (env var only)    |
|-----------------|-------------------------------------------|-----------------------|
| Ollama (default)| `--provider ollama`                       | none                  |
| OpenAI          | `--provider openai --model gpt-4o-mini`   | `OPENAI_API_KEY`      |
| Anthropic       | `--provider anthropic`                    | `ANTHROPIC_API_KEY`   |
| Gemini          | `--provider gemini`                       | `GEMINI_API_KEY`      |
| LM Studio/vLLM/Groq/any OpenAI-compatible | `--provider openai-compat` + `openai_base_url` in config | optional |

Config layers (later wins): built-ins ← `~/.vibe/config.json` ←
`<project>/.vibe/config.json` ← CLI flags. `python vibe.py --init` writes an
annotated example.

```json
{
  "provider": "ollama",
  "model": "qwen2.5-coder:7b",
  "temperature": 0.2,
  "max_steps": 30,
  "max_context_tokens": 32000,
  "confirm_mode": "ask",
  "use_native_tools": true
}
```

For models **without** native tool calling, set `"use_native_tools": false` —
a JSON-protocol adapter (`llm/adapter.py`) teaches any plain chat model to
drive the same tools.

**API keys are read from environment variables only** — never stored in
config files, never hardcoded, never logged.

---

## Safety & control

Every terminal command is classified by `safety.py`:

| Verdict  | Behaviour                                   | Examples                                    |
|----------|---------------------------------------------|---------------------------------------------|
| `ALLOW`  | runs immediately                             | `pytest`, `git diff`, `npm test`, `ls`      |
| `ASK`    | requires your `[y/N]` in the terminal        | `rm -rf build/`, `git reset --hard`, `sudo`, `curl` |
| `DENY`   | refused outright, agent must pick another way| `rm -rf /`, `mkfs`, `dd of=/dev/…`, `curl … \| sh`, `shutdown` |

Plus: unknown commands default to **ASK**; `write_file` confirms overwrites;
`delete_path` always confirms; destructive git ops aren't given tools (they
must pass the classifier); `--yes` auto-approves but **never** un-blocks
DENY-listed commands; `confirm_mode: "strict"` confirms everything.

File tools are confined to the project root. Session transcripts
(JSONL) are stored in `.vibe/sessions/` for full auditability.

> Honest limits: the classifier is a guardrail for an agent *you* run on
> *your* machine — it prevents accidents, but it is not a sandbox against a
> hostile model. Review what it does; use `--yes` only for tasks you
> understand.

### Memory

`memory_write` stores durable notes (decisions + why, conventions, gotchas)
in `.vibe/MEMORY.md`, injected into every future session — the agent
remembers your project between runs.

---

## Adding your own tool (2 minutes)

```python
# vibe_agent/tools/my_tool.py
from .base import Tool, ToolResult

class DockerLogs(Tool):
    name = "docker_logs"
    description = "Show logs of a docker container in this project."
    parameters = {"type": "object",
                  "properties": {"container": {"type": "string"}},
                  "required": ["container"]}

    def run(self, args, ctx):
        return ToolResult(f"(run docker logs {args['container']} via subprocess here)")
```

```python
# vibe_agent/tools/__init__.py — register it
registry.register(DockerLogs())
```

Every backend (native or JSON protocol) picks it up automatically. That's the
whole extension story.

---

## Tests

36 unit/integration tests, no network needed (the fake brain proves the full
loop end-to-end, including blocked commands and cancelled confirmations):

```bash
python -m unittest discover -s tests -t .
```

## Project layout

```
vibe_agent/
├── agent.py          # orchestration loop (the "reasoning" core)
├── executor.py       # single choke point: lookup → args guard → run → cap output
├── safety.py         # ALLOW / ASK / DENY command classifier
├── context.py        # token budgeting, block-atomic trimming, session store
├── prompts.py        # your standing instructions as the system prompt
├── config.py         # layered config, env-var-only secrets
├── cli.py            # REPL, one-shot mode, --check, confirmations
└── llm/              # swappable brain
    ├── base.py       # Message / ToolCall / backend interface
    ├── factory.py    # provider instantiation (one place)
    ├── ollama.py     # primary: local, streaming, native tools
    ├── openai_compat.py  # OpenAI + LM Studio + Groq + Gemini + vLLM
    ├── anthropic.py  # Claude native API
    ├── adapter.py    # JSON protocol for tool-less models
    └── fake.py       # scripted brain for tests & offline demo
tests/                # 36 tests: safety, files, loop, trimming, adapter
```

## Roadmap ideas

- Streaming for OpenAI/Anthropic backends (Ollama already streams)
- Context summarization (currently: block-atomic trimming + capped tool outputs)
- Web search tool · LSP integration · containerized command execution
- Multi-project workspaces · agentic plan files for long tasks

## Known limits (v0.1, by design)

- OpenAI/Anthropic backends are non-streaming (responses appear at once)
- Long-running servers should be started by *you* — the agent will hand you
  the command instead of blocking (timeouts protect the loop)
- `fetch_url` strips HTML crudely; JS-heavy pages return little text
