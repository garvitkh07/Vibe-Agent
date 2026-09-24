import tempfile
import unittest
from pathlib import Path

from vibe_agent.config import AgentConfig
from vibe_agent.tools.base import ExecContext
from vibe_agent.tools.filesystem import DeletePath, EditFile, WriteFile
from vibe_agent.tools.search import FindFiles, SearchFiles


def _ctx(root: Path, confirm=lambda cat, det: True) -> ExecContext:
    return ExecContext(root=root, config=AgentConfig(), confirm_fn=confirm)


class TestFilesystem(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "src").mkdir()
        (self.root / "src" / "app.py").write_text(
            "def greet(name):\n    return 'hi'\n\n\ndef bye():\n    return 'bye'\n"
        )
        (self.root / "README.md").write_text("# demo\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_write_creates_parents(self):
        r = WriteFile().run({"path": "a/b/c.txt", "content": "hello"}, _ctx(self.root))
        self.assertTrue(r.success)
        self.assertTrue((self.root / "a" / "b" / "c.txt").read_text() == "hello")

    def test_write_overwrite_requires_confirm(self):
        ctx = _ctx(self.root, confirm=lambda c, d: False)
        r = WriteFile().run({"path": "README.md", "content": "clobbered"}, ctx)
        self.assertFalse(r.success)
        self.assertEqual((self.root / "README.md").read_text(), "# demo\n")

    def test_edit_exact_match(self):
        r = EditFile().run(
            {"path": "src/app.py", "old_string": "return 'hi'", "new_string": "return f'hi {name}'"},
            _ctx(self.root),
        )
        self.assertTrue(r.success)
        self.assertIn("f'hi {name}'", (self.root / "src" / "app.py").read_text())

    def test_edit_not_found_is_actionable_error(self):
        r = EditFile().run(
            {"path": "src/app.py", "old_string": "NOPE", "new_string": "x"},
            _ctx(self.root),
        )
        self.assertFalse(r.success)
        self.assertIn("not found", r.output)

    def test_edit_ambiguous(self):
        text = "x = 1\nx = 1\n"
        (self.root / "dup.py").write_text(text)
        r = EditFile().run({"path": "dup.py", "old_string": "x = 1", "new_string": "y = 1"}, _ctx(self.root))
        self.assertFalse(r.success)
        self.assertIn("2 locations", r.output)
        self.assertEqual((self.root / "dup.py").read_text(), text)

    def test_edit_replace_all(self):
        (self.root / "dup.py").write_text("x = 1\nx = 1\n")
        r = EditFile().run(
            {"path": "dup.py", "old_string": "x = 1", "new_string": "y = 1", "replace_all": True},
            _ctx(self.root),
        )
        self.assertTrue(r.success)
        self.assertEqual((self.root / "dup.py").read_text(), "y = 1\ny = 1\n")

    def test_path_confined_to_root(self):
        with self.assertRaises(ValueError):
            _ctx(self.root).resolve("../outside.txt")

    def test_delete_requires_confirm(self):
        ctx = _ctx(self.root, confirm=lambda c, d: False)
        r = DeletePath().run({"path": "README.md"}, ctx)
        self.assertFalse(r.success)
        self.assertTrue((self.root / "README.md").exists())
        r2 = DeletePath().run({"path": "README.md"}, _ctx(self.root))
        self.assertTrue(r2.success)
        self.assertFalse((self.root / "README.md").exists())

    def test_delete_dir_needs_recursive(self):
        r = DeletePath().run({"path": "src"}, _ctx(self.root))
        self.assertFalse(r.success)
        r2 = DeletePath().run({"path": "src", "recursive": True}, _ctx(self.root))
        self.assertTrue(r2.success)
        self.assertFalse((self.root / "src").exists())


class TestSearch(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "app.py").write_text("def train():\n    pass\n")
        (self.root / "node_modules").mkdir(parents=True)
        (self.root / "node_modules" / "x.js").write_text("function train() {}\n")
        (self.root / "tests").mkdir(parents=True)
        (self.root / "tests" / "t.py").write_text("import app\napp.train()\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_search_finds_and_ignores_node_modules(self):
        r = SearchFiles().run({"pattern": "train"}, _ctx(self.root))
        hits = r.output.splitlines()
        self.assertEqual(len(hits), 2)  # app.py def + tests call; node_modules excluded
        self.assertFalse(any("node_modules" in h for h in hits))

    def test_search_glob(self):
        r = SearchFiles().run({"pattern": "train", "glob": "*.py"}, _ctx(self.root))
        self.assertTrue(all(h.endswith(".py") or ":" in h for h in [r.output]))
        self.assertNotIn(".js", r.output)

    def test_search_line_numbers(self):
        r = SearchFiles().run({"pattern": "def train"}, _ctx(self.root))
        self.assertIn("app.py:1:", r.output)

    def test_find_files(self):
        r = FindFiles().run({"pattern": "*.py"}, _ctx(self.root))
        paths = r.output.splitlines()
        self.assertIn("app.py", paths)
        self.assertIn(str(Path("tests") / "t.py"), paths)


if __name__ == "__main__":
    unittest.main()
