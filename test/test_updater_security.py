import ast
import tempfile
import unittest
import zipfile
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "source" / "__init__.py"
WANTED_ASSIGNMENTS = {
    "MAX_UPDATE_EXPANDED_BYTES",
    "MAX_UPDATE_FILE_BYTES",
    "RELEASE_FILE_ALLOWLIST",
    "REQUIRED_UPDATE_FILES",
}
WANTED_FUNCTIONS = {
    "_version_tuple",
    "_normalized_zip_name",
    "_validate_update_archive",
}


def _load_updater_helpers():
    tree = ast.parse(SOURCE.read_text(encoding="utf-8"), filename=str(SOURCE))
    selected = []
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {target.id for target in node.targets
                     if isinstance(target, ast.Name)}
            if names & WANTED_ASSIGNMENTS:
                selected.append(node)
        elif isinstance(node, ast.FunctionDef) and node.name in WANTED_FUNCTIONS:
            selected.append(node)
    module = ast.Module(body=selected, type_ignores=[])
    namespace = {"os": __import__("os"), "re": __import__("re"),
                 "zipfile": zipfile}
    exec(compile(module, str(SOURCE), "exec"), namespace)
    return namespace


HELPERS = _load_updater_helpers()


def _make_archive(entries):
    handle = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    handle.close()
    with zipfile.ZipFile(handle.name, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return Path(handle.name)


class UpdaterSecurityTests(unittest.TestCase):
    def test_version_comparison_normalizes_common_tags(self):
        version_tuple = HELPERS["_version_tuple"]
        self.assertEqual(version_tuple("v1.2"), (1, 2, 0))
        self.assertEqual(version_tuple("1.2.3-rc1"), (1, 2, 3))

    def test_valid_release_is_accepted(self):
        archive = _make_archive({
            "__init__.py": 'PLUGIN_VERSION = "2.0.0"\n',
            "README.md": "readme",
            "native/sp_layer_tools_delegate_qt5.dll": b"qt5",
            "native/sp_layer_tools_delegate_qt6.dll": b"qt6",
        })
        try:
            HELPERS["_validate_update_archive"](str(archive), "2.0.0")
        finally:
            archive.unlink(missing_ok=True)

    def test_path_traversal_is_rejected(self):
        archive = _make_archive({"../outside.txt": "bad"})
        try:
            with self.assertRaisesRegex(RuntimeError, "不安全路径"):
                HELPERS["_validate_update_archive"](str(archive))
        finally:
            archive.unlink(missing_ok=True)

    def test_unexpected_file_is_rejected(self):
        archive = _make_archive({
            "__init__.py": 'PLUGIN_VERSION = "2.0.0"\n',
            "README.md": "readme",
            "native/sp_layer_tools_delegate_qt5.dll": b"qt5",
            "native/sp_layer_tools_delegate_qt6.dll": b"qt6",
            "payload.exe": b"bad",
        })
        try:
            with self.assertRaisesRegex(RuntimeError, "非白名单"):
                HELPERS["_validate_update_archive"](str(archive))
        finally:
            archive.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
