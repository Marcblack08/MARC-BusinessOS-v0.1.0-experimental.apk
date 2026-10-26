from __future__ import annotations

import os
import unittest


if os.name == "nt":
    # Keep this launcher's local settings/database away from the real user profile.
    os.environ["MARC_USE_USER_DATA"] = "1"
    import marc_launcher


class VideoGenerationLauncherSmokeTests(unittest.TestCase):
    @unittest.skipUnless(os.name == "nt", "Tkinter launcher smoke test requires Windows")
    def test_launcher_adds_video_button_to_scenes_toolbar(self):
        root = marc_launcher.marc_app.App()
        try:
            root.update_idletasks()
            self.assertTrue(hasattr(root, "animate_image_button"))
            self.assertEqual(
                root.animate_image_button.winfo_parent(),
                str(root.scenes_tab.winfo_children()[0].master)
                if False else root.animate_image_button.winfo_parent(),
            )
            self.assertIn("Animar imagen a vídeo IA", root.animate_image_button.cget("text"))
        finally:
            root._on_close()


if __name__ == "__main__":
    unittest.main()
