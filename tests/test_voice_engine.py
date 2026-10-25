import unittest

from voice_engine import build_kokoro_ssml, parse_kokoro_voice_ids


class KokoroVoiceEngineTests(unittest.TestCase):
    def test_parse_voice_ids_from_list_and_nested_api_payload(self):
        payload = {
            "voices": [
                {"voice_id": "ef_dora", "display_name": "Dora"},
                {"id": "em_alex", "language": "Spanish"},
            ],
            "metadata": {"other": "not-a-voice"},
        }
        self.assertEqual(parse_kokoro_voice_ids(payload), ["ef_dora", "em_alex"])

    def test_build_ssml_uses_distinct_character_voices_and_strips_emotion_tags(self):
        script = """[ESCENA 01 — Recepción]
[NARRADOR]: El ascensor se detuvo en el piso imposible.
[MATEO]: [EMOCION=miedo] ¡No abras esa puerta!
[LUCIA]: [EMOCION=susurro] Ya está abierta.
"""
        ssml, assignments = build_kokoro_ssml(
            script,
            ["ef_dora", "em_alex", "em_santa"],
            "ef_dora",
        )
        self.assertTrue(ssml.startswith("<speak>"))
        self.assertTrue(ssml.endswith("</speak>"))
        self.assertIn('<voice name="ef_dora">', ssml)
        self.assertIn('<voice name="em_alex">', ssml)
        self.assertIn('<voice name="em_santa">', ssml)
        self.assertIn('speed="0.90" pitch="+2st"', ssml)
        self.assertIn('speed="0.78" pitch="-1st"', ssml)
        self.assertNotIn("[EMOCION=miedo]", ssml)
        self.assertIn("¡No abras esa puerta!", ssml)
        self.assertEqual(assignments["NARRADOR"], "ef_dora")
        self.assertNotEqual(assignments["MATEO"], assignments["LUCIA"])

    def test_build_ssml_escapes_story_text(self):
        ssml, _ = build_kokoro_ssml(
            "[MATEO]: [EMOCION=ira] A & B < C",
            ["em_alex"],
            "em_alex",
        )
        self.assertIn("A &amp; B &lt; C", ssml)
        self.assertNotIn("A & B < C", ssml)

    def test_build_ssml_rejects_unknown_default_voice_and_empty_story(self):
        with self.assertRaises(ValueError):
            build_kokoro_ssml("[MATEO]: Hola", ["em_alex"], "missing_voice")
        with self.assertRaises(ValueError):
            build_kokoro_ssml("[ESCENA 01 — Nada]", ["em_alex"], "em_alex")


if __name__ == "__main__":
    unittest.main()
