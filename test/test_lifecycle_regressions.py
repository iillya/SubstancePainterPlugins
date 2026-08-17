import ast
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "source" / "__init__.py"
CPP_SOURCE = (Path(__file__).resolve().parents[1] / "source" / "cpp" /
              "sp_tools_delegate.cpp")
TEXT = SOURCE.read_text(encoding="utf-8")
CPP_TEXT = CPP_SOURCE.read_text(encoding="utf-8")
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

    def test_python_only_pushes_alignment_configuration(self):
        push_source = _function_text("_push_align_config")
        self.assertIn("sp_tools_set_align_config", push_source)
        self.assertNotIn("findChildren", push_source)
        for obsolete in ("_align_do_sync", "_align_view_type_at_cursor",
                         "_align_get_current_tool_id", "_on_align_tick",
                         "_on_view_changed"):
            self.assertNotIn(obsolete, FUNCTIONS)

    def test_native_watchdog_uses_two_hundred_milliseconds(self):
        self.assertIn("g_alignTimer->setInterval(200);", CPP_TEXT)

    def test_native_view_trigger_is_bounded_to_sixteen_levels(self):
        self.assertIn("current && depth < 16", CPP_TEXT)

    def test_immediate_tool_and_view_triggers_are_retained(self):
        self.assertIn("&QToolButton::toggled", CPP_TEXT)
        self.assertIn("type == QEvent::Enter || type == QEvent::Leave", CPP_TEXT)
        self.assertIn("alignNow();", CPP_TEXT)

    def test_alignment_logic_is_owned_by_native_module(self):
        self.assertIn("QString currentAlignToolId()", CPP_TEXT)
        self.assertIn("int viewAtCursor()", CPP_TEXT)
        self.assertIn("void alignNow()", CPP_TEXT)
        self.assertIn('name.contains(QStringLiteral("alignment"))', CPP_TEXT)
        self.assertIn('name.contains(QStringLiteral("size_space"))', CPP_TEXT)

    def test_native_module_owns_channel_selector_lookup(self):
        self.assertIn("QComboBox *findLayerChannelCombo()", CPP_TEXT)
        self.assertIn("sp_tools_request_channels", CPP_TEXT)
        self.assertNotIn("def _find_channel_selector_combo", TEXT)
        self.assertNotIn("def _layers_dock", TEXT)

    def test_channel_resolution_callback_uses_native_order(self):
        callback_source = _function_text("_on_resolve_channels")
        self.assertIn("native_labels", callback_source)
        self.assertIn("native_keys", callback_source)
        self.assertNotIn("_push_channels_to_native()", callback_source)


if __name__ == "__main__":
    unittest.main()
