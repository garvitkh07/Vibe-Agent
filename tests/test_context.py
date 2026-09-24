import unittest

from vibe_agent.context import trim_messages
from vibe_agent.llm.base import Message, ToolCall


def block_of_tool_calls(i: int, size: int = 100) -> list:
    return [
        Message(role="assistant", content="", tool_calls=[
            ToolCall(id=f"c{i}", name="read_file", arguments={"path": "x"}),
        ]),
        Message(role="tool", content="x" * size, name="read_file", tool_call_id=f"c{i}"),
    ]


class TestTrim(unittest.TestCase):
    def test_recent_messages_kept(self):
        msgs = [Message(role="user", content="u1" * 500)]
        for i in range(5):
            msgs.append(Message(role="user", content="u" * 400))
            msgs.extend(block_of_tool_calls(i))
        msgs.append(Message(role="user", content="latest question"))
        trimmed = trim_messages(msgs, max_tokens=50)  # 50 tokens = 200 chars
        self.assertEqual(trimmed[-1].content, "latest question")
        # system-less trimming never orphans tool results:
        for m in trimmed:
            if m.role == "tool":
                self.assertTrue(any(
                    p.role == "assistant" and p.tool_calls for p in trimmed
                ))

    def test_never_orphans_tool_results(self):
        msgs = []
        for i in range(10):
            msgs.extend(block_of_tool_calls(i, size=300))
        trimmed = trim_messages(msgs, max_tokens=60)
        # every kept tool result must have its assistant request kept too
        for m in trimmed:
            if m.role == "tool":
                parent = any(
                    p.role == "assistant" and p.tool_calls
                    and p.tool_calls[0].id == m.tool_call_id
                    for p in trimmed
                )
                self.assertTrue(parent, "orphaned tool result in trimmed history")

    def test_budget_respected_roughly(self):
        msgs = [Message(role="user", content="a" * 4000) for _ in range(10)]
        trimmed = trim_messages(msgs, max_tokens=250)  # 1000 chars
        total = sum(len(m.content) for m in trimmed)
        self.assertLessEqual(total, 1000 + 4000)  # at least the last block kept


if __name__ == "__main__":
    unittest.main()
