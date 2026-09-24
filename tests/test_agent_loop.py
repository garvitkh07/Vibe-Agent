"""End-to-end agent loop tests with a scripted FakeBackend — proves the full
pipeline (LLM -> loop -> executor -> tools -> safety -> confirmation) without
any network or model."""

import tempfile
import unittest
from pathlib import Path

from vibe_agent.agent import Agent, AgentUI
from vibe_agent.config import AgentConfig
from vibe_agent.llm.fake import FakeBackend
from vibe_agent.llm.base import Message, ToolCall
from vibe_agent.tools import build_default_registry
from vibe_agent.tools.base import ExecContext


def make_agent(root: Path, script, confirm=lambda c, d: True, mode="ask") -> Agent:
    config = AgentConfig(confirm_mode=mode, stream=False)
    ctx = ExecContext(root=root, config=config, confirm_fn=confirm)
    return Agent(
        backend=FakeBackend(script=script),
        registry=build_default_registry(),
        ctx=ctx,
        config=config,
        ui=AgentUI(on_text=lambda t: None, on_error=lambda m: None),
    )


class TestAgentLoop(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_create_and_run_file(self):
        script = [
            Message(role="assistant", content="creating", tool_calls=[
                ToolCall(id="c1", name="write_file", arguments={
                    "path": "hello.py", "content": "print('ran ok')\n",
                }),
            ]),
            Message(role="assistant", content="running", tool_calls=[
                ToolCall(id="c2", name="run_command", arguments={"command": "python hello.py"}),
            ]),
            Message(role="assistant", content="all done — file created and executed successfully"),
        ]
        agent = make_agent(self.root, script)
        stats = agent.run_turn("make and run hello.py")

        self.assertEqual(stats.tool_calls, 2)
        self.assertFalse(stats.cancelled)
        self.assertTrue((self.root / "hello.py").exists())

        # the tool result fed back into context must contain the REAL output
        tool_msgs = [m for m in agent.history if m.role == "tool"]
        self.assertTrue(any("ran ok" in m.content for m in tool_msgs))
        self.assertTrue(any("exit code: 0" in m.content for m in tool_msgs))

    def test_deny_list_blocked(self):
        script = [
            Message(role="assistant", content="trying bad thing", tool_calls=[
                ToolCall(id="c1", name="run_command", arguments={"command": "rm -rf /"}),
            ]),
            Message(role="assistant", content="understood, I won't do that"),
        ]
        agent = make_agent(self.root, script)
        agent.run_turn("clean the disk")
        blocked = [m for m in agent.history if m.role == "tool" and "BLOCKED" in m.content]
        self.assertEqual(len(blocked), 1)

    def test_cancelled_confirmation(self):
        declined = lambda cat, det: False  # noqa: E731
        script = [
            Message(role="assistant", tool_calls=[
                ToolCall(id="c1", name="write_file", arguments={
                    "path": "f.txt", "content": "original",
                }),
            ]),
            Message(role="assistant", tool_calls=[
                ToolCall(id="c2", name="write_file", arguments={
                    "path": "f.txt", "content": "clobber attempt",
                }),
            ]),
            Message(role="assistant", content="ok, I'll leave it"),
        ]
        agent = make_agent(self.root, script, confirm=declined)
        agent.run_turn("write then overwrite f.txt")

        self.assertEqual((self.root / "f.txt").read_text(), "original")  # preserved
        cancelled = [m for m in agent.history if m.role == "tool" and "Cancelled" in m.content]
        self.assertEqual(len(cancelled), 1)

    def test_unknown_tool_reports_cleanly(self):
        script = [
            Message(role="assistant", tool_calls=[
                ToolCall(id="c1", name="fly_to_moon", arguments={}),
            ]),
            Message(role="assistant", content="sorry, no such tool"),
        ]
        agent = make_agent(self.root, script)
        agent.run_turn("do magic")
        errs = [m for m in agent.history if m.role == "tool" and "unknown tool" in m.content]
        self.assertEqual(len(errs), 1)

    def test_session_transcript_written(self):
        script = [Message(role="assistant", content="final answer, no tools")]
        agent = make_agent(self.root, script)
        agent.run_turn("hi")
        self.assertTrue(agent.session.path.exists())
        content = agent.session.path.read_text()
        self.assertIn('"user"', content)
        self.assertIn('"assistant"', content)

    def test_fake_demo_end_to_end(self):
        """The same pipeline `vibe --provider fake` exercises."""
        agent = make_agent(self.root, None)  # None -> default demo script
        stats = agent.run_turn("run your demo")
        self.assertGreaterEqual(stats.tool_calls, 3)
        self.assertTrue((self.root / "vibe_demo.py").exists())
        tool_msgs = [m for m in agent.history if m.role == "tool"]
        self.assertTrue(any("Hello from Vibe!" in m.content for m in tool_msgs))

    def test_memory_persists_into_system_prompt(self):
        script = [
            Message(role="assistant", tool_calls=[
                ToolCall(id="c1", name="memory_write",
                         arguments={"content": "use ruff for linting", "mode": "append"}),
            ]),
            Message(role="assistant", content="noted"),
        ]
        agent = make_agent(self.root, script)
        agent.run_turn("remember our lint choice")
        memory_file = self.root / ".vibe" / "MEMORY.md"
        self.assertTrue(memory_file.exists())
        self.assertIn("ruff", memory_file.read_text())

        # a NEW agent (next session) must see it in its system prompt
        agent2 = make_agent(self.root, [Message(role="assistant", content="ok")])
        system = agent2._build_system()
        self.assertIn("ruff", system)


if __name__ == "__main__":
    unittest.main()
