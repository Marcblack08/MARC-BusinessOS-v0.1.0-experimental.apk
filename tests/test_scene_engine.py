import unittest

from scene_engine import (
    allocate_scene_durations, build_srt_subtitles, ffmpeg_filter_path,
    parse_script_scenes, scene_motion_filter
)


class SceneEngineTests(unittest.TestCase):
    def test_empty_script_has_no_scenes(self):
        self.assertEqual(parse_script_scenes("   "), [])

    def test_metadata_not_rendered_as_scene(self):
        script = (
            "TÍTULO: El regreso\n"
            "GÉNERO: Novela dramática\n"
            "DURACIÓN OBJETIVO: 5 minutos\n\n"
            "[CAPÍTULO 01 DE 01]\n"
            "Lucía abrió la puerta y vio a su hermano. No podía creer que hubiera regresado.\n\n"
            "[REVISIÓN HUMANA PENDIENTE]\n"
            "Revisa continuidad, nombres, ritmo y duración."
        )
        scenes = parse_script_scenes(script)
        self.assertTrue(scenes)
        self.assertTrue(all("TÍTULO:" not in s["text"] for s in scenes))
        self.assertTrue(all("Revisa continuidad" not in s["text"] for s in scenes))
        self.assertIn("Lucía abrió la puerta", " ".join(s["text"] for s in scenes))

    def test_scene_duration_sum_matches_target_when_feasible(self):
        scenes = [
            {"word_count": 100, "text": "one"},
            {"word_count": 200, "text": "two"},
            {"word_count": 100, "text": "three"},
        ]
        durations = allocate_scene_durations(scenes, 120)
        self.assertEqual(sum(durations), 120)
        self.assertTrue(all(x >= 5 for x in durations))
        self.assertGreater(durations[1], durations[0])

    def test_duration_respects_minimum_for_many_scenes(self):
        scenes = [{"word_count": 1, "text": "scene"} for _ in range(30)]
        durations = allocate_scene_durations(scenes, 60)
        self.assertEqual(len(durations), 30)
        self.assertTrue(all(x >= 5 for x in durations))
        self.assertEqual(sum(durations), 150)

    def test_srt_cues_are_numbered_and_time_uses_comma_milliseconds(self):
        scenes = [
            {"text": "La noche cayó. Lucía cerró la puerta."},
            {"text": "Alguien llamó desde el pasillo."},
        ]
        srt = build_srt_subtitles(scenes, [7, 5])
        self.assertIn("1\n00:00:00,000 --> 00:00:07,000", srt)
        self.assertIn("2\n00:00:07,000 --> 00:00:12,000", srt)
        self.assertIn("Lucía cerró la puerta.", srt)

    def test_srt_rejects_mismatched_scene_durations(self):
        with self.assertRaises(ValueError):
            build_srt_subtitles([{"text": "Texto"}], [])

    def test_filter_path_escapes_windows_colon_and_apostrophe(self):
        escaped = ffmpeg_filter_path(r"C:\Users\Marc's files\scene:01.txt")
        self.assertIn(r"C\:", escaped)
        self.assertIn(r"Marc\'s files", escaped)

    def test_motion_filter_uses_requested_output_size(self):
        result = scene_motion_filter("2D fluida", 1280, 720, 10)
        self.assertIn("s=1280x720", result)
        pixel = scene_motion_filter("Pixel animation", 720, 1280, 5)
        self.assertIn("flags=neighbor", pixel)


if __name__ == "__main__":
    unittest.main()
