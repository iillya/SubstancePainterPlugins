import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "source" / "__init__.py"
TEXT = SOURCE.read_text(encoding="utf-8")
TREE = ast.parse(TEXT, filename=str(SOURCE))
FUNCTIONS = {
    node.name: node for node in TREE.body if isinstance(node, ast.FunctionDef)
}


def _function_text(name):
    return ast.get_source_segment(TEXT, FUNCTIONS[name])


class LifecycleRegressionTests(unittest.TestCase):
    def test_initial_cleanup_does_not_load_native_dll(self):
        close_source = _function_text("close_plugin")
        self.assertIn("dll = _native", close_source)
        self.assertNotIn("dll = _load_native()", close_source)

    def test_project_closing_does_not_load_native_dll(self):
        close_source = _function_text("_on_project_closing")
        self.assertIn("dll = _native", close_source)
        self.assertNotIn("dll = _load_native()", close_source)

    def test_closed_log_is_guarded_by_real_started_state(self):
        stop_source = _function_text("_align_stop")
        self.assertIn("if was_started:", stop_source)
        self.assertIn("映射校准助手已关闭", stop_source)

    def test_start_resets_stale_session_and_debounce_state(self):
        start_source = _function_text("start_plugin")
        self.assertIn("_SESSION_CLOSING = False", start_source)
        self.assertIn("_STACK_PENDING = False", start_source)
        self.assertIn("_LAST_SELECTED_UID = None", start_source)


if __name__ == "__main__":
    unittest.main()
