from __future__ import annotations

import os
import unittest


if os.name == "nt":
    # Keep this launcher's local settings/database away from the real user profile.
    os.environ["MARC_USE_USER_DATA"] = "1"
    import marc_launcher


class VideoGenerationLauncherSmokeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Tkinter launcher smoke test requires Windows")
    def test_launches_minimal_creator_and_keeps_advanced_editor_available(self):
        root = marc_launcher.marc_app.App()
        try:
            root.update_idletasks()
            self.assertTrue(hasattr(root, "_creator_wizard"))
            self.assertTrue(hasattr(root, "_creator_show_page"))
            self.assertTrue(hasattr(root, "easy_creator_button"))
            self.assertEqual(root._creator_page, 1)
            self.assertTrue(root._creator_wizard.winfo_exists())
            self.assertIn("Creador fácil", root.easy_creator_button.cget("text"))
            self.assertTrue(hasattr(root, "studio_tabs"))
            self.assertIsNotNone(root.full_production_button)
            self.assertIsNotNone(root.animate_image_button)
            self.assertIsNotNone(root.prepare_ai_button)
            self.assertEqual(root._creator_mode_var.get(), "Básico")
            self.assertEqual(root._marc_full_editor_shell.winfo_manager(), "grid")
        finally:
            root._on_close()


if __name__ == "__main__":
    unittest.main()
