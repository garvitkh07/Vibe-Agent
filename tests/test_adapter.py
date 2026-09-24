import unittest

from vibe_agent.llm.adapter import JsonToolAdapter, extract_json_object
from vibe_agent.llm.base import Message


class _Scripted:
    name = "scripted"

    def __init__(self, reply):
        self.reply = reply

    def chat(self, messages, tools=None, temperature=0.2, on_text=None):
        self.seen = messages
        return Message(role="assistant", content=self.reply)

    def check(self):
        return "ok"


class TestExtractJson(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(extract_json_object('{"tool": "ls", "arguments": {}}')["tool"], "ls")

    def test_fenced(self):
        text = 'Let me look.\n```json\n{"tool": "read_file", "arguments": {"path": "a.py"}}\n```'
        obj = extract_json_object(text)
        self.assertEqual(obj["arguments"]["path"], "a.py")

    def test_embedded(self):
        text = 'Sure! {"tool": "run_command", "arguments": {"command": "ls"}} that works'
        self.assertEqual(extract_json_object(text)["tool"], "run_command")

    def test_none_for_prose(self):
        self.assertIsNone(extract_json_object("Just a normal answer with {braces} only."))


class TestAdapter(unittest.TestCase):
    def test_parses_tool_call(self):
        inner = _Scripted('{"tool": "project_summary", "arguments": {}}')
        adapter = JsonToolAdapter(inner)
        tools = [{"name": "project_summary", "description": "d", "parameters": {"type": "object"}}]
        result = adapter.chat([Message(role="system", content="sys"),
                               Message(role="user", content="inspect")], tools=tools)
        self.assertIsNotNone(result.tool_calls)
        self.assertEqual(result.tool_calls[0].name, "project_summary")

    def test_protocol_injected_into_system(self):
        inner = _Scripted("hello")
        adapter = JsonToolAdapter(inner)
        tools = [{"name": "t", "description": "d", "parameters": {"type": "object"}}]
        adapter.chat([Message(role="system", content="sys"),
                      Message(role="user", content="hi")], tools=tools)
        self.assertIn("Tool use protocol", inner.seen[0].content)

    def test_tool_result_wrapped_as_user_json(self):
        inner = _Scripted("done")
        adapter = JsonToolAdapter(inner)
        adapter.chat([
            Message(role="system", content="s"),
            Message(role="user", content="go"),
            Message(role="tool", content="the result", name="t", tool_call_id="c0"),
        ])
        self.assertIn("tool_result", inner.seen[-1].content)


if __name__ == "__main__":
    unittest.main()
