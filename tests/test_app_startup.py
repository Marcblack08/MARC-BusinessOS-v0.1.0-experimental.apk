from __future__ import annotations

import os
import tempfile
import unittest

# The desktop UI smoke test runs on Windows CI, where Tk has a native windowing
# environment. Keep its SQLite/data files out of the checkout and user profile.
_TEST_DATA = None
if os.name == "nt":
    _TEST_DATA = tempfile.TemporaryDirectory(prefix="marc-startup-test-")
    os.environ["MARC_USE_USER_DATA"] = "1"
    os.environ["LOCALAPPDATA"] = _TEST_DATA.name
    from app import App
else:
    App = None


class AppStartupSmokeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Tkinter startup smoke test requires Windows")
    def test_app_constructs_and_compact_toolbar_uses_correct_parents(self):
        root = App()
        try:
            # Forces pending geometry calculations so parent/manager conflicts
            # fail in CI rather than only when a user opens the executable.
            root.update_idletasks()
            self.assertTrue(hasattr(root, "primary_actions"))
            self.assertTrue(hasattr(root, "secondary_actions"))
            self.assertEqual(root.generate_button.winfo_parent(), str(root.compact_toolbar))
            self.assertEqual(root.export_button.winfo_parent(), str(root.compact_toolbar))
            self.assertEqual(root.preview_render_button.winfo_parent(), str(root.secondary_actions))
            self.assertFalse(root.secondary_actions.winfo_ismapped())
            self.assertTrue(root.preview_dock.winfo_manager())
            self.assertTrue(root.configuration_visible)
            self.assertTrue(root.project_library_visible)
            self.assertEqual(root.studio_tabs.winfo_parent(), str(root.lower_panel))
            self.assertEqual(root.script_tab.winfo_parent(), str(root.studio_tabs))
            self.assertEqual(root.preview_dock.winfo_parent(), str(root.script_tab))
            self.assertEqual(root.mini_timeline_panel.winfo_parent(), str(root.script_tab))
            self.assertEqual(root.script_text.winfo_parent(), str(root.script_text_frame))
            self.assertTrue(root.brand_gradient_canvas.winfo_manager())
            root._draw_brand_gradient()
            self.assertGreater(len(root.brand_gradient_canvas.find_all()), 0)
            self.assertEqual(root.project_search_var.get(), "Buscar proyectos...")
            root.project_search_var.set("zz-no-such-project")
            self.assertEqual(root.project_list.size(), 0)
            root.project_search_var.set("Buscar proyectos...")
        finally:
            root._on_close()


if __name__ == "__main__":
    unittest.main()
