import unittest

from story_engine import (
    SHORT_VIDEO_MODE,
    build_series_context,
    continuity_review_check,
    export_dimensions,
    format_short_chapter,
    extract_speaker_names,
    narration_segments,
    target_word_count,
    visual_shot_count,
)


class StoryEngineTests(unittest.TestCase):
    def test_resolution_and_aspect_ratio_profiles(self):
        self.assertEqual(export_dimensions("YouTube 16:9", "720p (HD)"), (1280, 720))
        self.assertEqual(export_dimensions("YouTube 16:9", "1080p (Full HD)"), (1920, 1080))
        self.assertEqual(export_dimensions("YouTube 16:9", "2K / 1440p"), (2560, 1440))
        self.assertEqual(export_dimensions("TikTok / Reels / Shorts 9:16", "1080p (Full HD)"), (1080, 1920))
        self.assertEqual(export_dimensions("Facebook 1:1", "2K / 1440p"), (1440, 1440))

    def test_two_minute_mode_targets_two_minutes(self):
        self.assertEqual(target_word_count(60, SHORT_VIDEO_MODE), 270)

    def test_visual_shot_count_respects_five_second_cap(self):
        self.assertEqual(visual_shot_count(120), 24)
        self.assertEqual(visual_shot_count(300), 60)
        self.assertEqual(visual_shot_count(301), 61)
        with self.assertRaises(ValueError):
            visual_shot_count(0)
        with self.assertRaises(ValueError):
            visual_shot_count(10, 0)

    def test_short_chapter_uses_real_line_breaks(self):
        formatted = format_short_chapter("[GANCHO]\\nUna puerta se cierra.")
        self.assertIn("\n[CAPÍTULO 01 DE 01]\n", formatted)
        self.assertIn("[GANCHO]\nUna puerta", formatted)
        self.assertNotIn("\\n", formatted)

    def test_speaker_labels_are_unique_and_ordered(self):
        script = "[NARRADOR]: La puerta se abrió.\n\n[JUAN]: ¿Quién anda ahí?\n\n[JUAN]: ¡Contesta!"
        self.assertEqual(extract_speaker_names(script), ["NARRADOR", "JUAN"])

    def test_narration_segments_preserve_speakers(self):
        script = "[NARRADOR]: La puerta se abrió.\n\n[JUAN]: ¿Quién anda ahí?"
        self.assertEqual(
            narration_segments(script),
            [("NARRADOR", "La puerta se abrió."), ("JUAN", "¿Quién anda ahí?")],
        )

    def test_narration_segments_parse_several_speakers_inside_one_scene(self):
        script = "[NARRADOR]: La puerta se abrió. [JUAN]: ¿Quién anda ahí? [LUCIA]: Soy yo."
        self.assertEqual(extract_speaker_names(script), ["NARRADOR", "JUAN", "LUCIA"])
        self.assertEqual(
            narration_segments(script),
            [
                ("NARRADOR", "La puerta se abrió."),
                ("JUAN", "¿Quién anda ahí?"),
                ("LUCIA", "Soy yo."),
            ],
        )

    def test_series_context_includes_bible_and_previous_state(self):
        context = build_series_context("Juan busca la carta.", "La carta sigue en su poder.", "La puerta se abrió.")
        self.assertIn("BIBLIA CANÓNICA", context)
        self.assertIn("ESTADO CANÓNICO", context)
        self.assertIn("continúa desde aquí", context)

    def test_continuity_review_flags_generic_opening(self):
        warnings = continuity_review_check("Había una vez un reino muy lejano " + "palabra " * 110)
        self.assertTrue(any("genérico" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()
