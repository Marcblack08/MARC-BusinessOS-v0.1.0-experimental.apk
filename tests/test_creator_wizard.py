import unittest

from creator_wizard import animation_preset, mode_uses_ai, normalize_script_for_images


class CreatorWizardTests(unittest.TestCase):
    def test_preserves_explicit_scene_boundaries_when_scene_count_matches_images(self):
        script = "ESCENA 1 — Inicio\n[NARRADOR]: Ana entra.\n\nESCENA 2 — Final\n[ANA]: ¿Quién está ahí?"
        result = normalize_script_for_images(script, 2)
        self.assertEqual(result, script)

    def test_aligns_pasted_script_to_selected_image_count(self):
        script = (
            "[NARRADOR]: La puerta se abrió lentamente. Nadie respondió.\n\n"
            "[ANA]: ¿Hay alguien aquí? La luz parpadeó.\n\n"
            "[NARRADOR]: Ana retrocedió y salió corriendo."
        )
        result = normalize_script_for_images(script, 3)
        self.assertEqual(result.count("ESCENA "), 3)
        self.assertIn("[ANA]:", result)
        self.assertIn("La puerta se abrió lentamente.", result)

    def test_repartitions_when_existing_scene_count_does_not_match_images(self):
        script = "ESCENA 1 — Inicio\nUna noche oscura.\n\nESCENA 2 — Pasillo\nLa puerta se cerró."
        result = normalize_script_for_images(script, 4)
        self.assertEqual(result.count("ESCENA "), 4)
        self.assertIn("Una noche oscura.", result)
        self.assertIn("La puerta se cerró.", result)

    def test_rejects_empty_script_and_missing_images(self):
        with self.assertRaises(ValueError):
            normalize_script_for_images("", 1)
        with self.assertRaises(ValueError):
            normalize_script_for_images("Una historia.", 0)

    def test_animation_modes_distinguish_camera_motion_from_real_ai_motion(self):
        self.assertFalse(mode_uses_ai("Básico"))
        self.assertTrue(mode_uses_ai("Movimiento IA"))
        self.assertTrue(mode_uses_ai("Cinemático IA"))
        self.assertEqual(animation_preset("Básico")["animation_intensity"], "Normal")
        self.assertEqual(animation_preset("Movimiento IA")["animation_intensity"], "Muy animado")
        self.assertEqual(animation_preset("Cinemático IA")["transition_style"], "Zoom cinematográfico")


if __name__ == "__main__":
    unittest.main()
