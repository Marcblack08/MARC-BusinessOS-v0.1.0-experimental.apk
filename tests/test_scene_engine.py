import tempfile
import unittest
from pathlib import Path

from scene_engine import (
    allocate_scene_durations, build_audio_filter_graph, build_scene_visual_brief, expand_scenes_to_shots,
    build_srt_subtitles, build_subtitle_drawtext_filter, ffmpeg_filter_path,
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

    def test_visual_brief_extracts_dialogue_and_relevant_character_profiles(self):
        scene = {
            "title": "El ultimátum",
            "text": (
                "[NARRADOR]: La lluvia golpea la ventana. "
                "[MARTA]: No voy a firmar. "
                "[IVÁN]: Entonces perderás todo."
            ),
        }
        bible = (
            "BIBLIA DE PERSONAJES\n\n"
            "MARTA: 32 años, cabello negro recogido, abrigo verde oscuro y una cicatriz fina sobre la ceja.\n\n"
            "IVÁN: 45 años, cabello gris corto, traje azul marino, anillo de plata.\n\n"
            "LUCÍA: 20 años, cabello rojo, chaqueta amarilla y botas de cuero."
        )
        brief = build_scene_visual_brief(
            scene, story_bible=bible, continuity_state="Marta todavía conserva la carta."
        )
        self.assertEqual(brief["speakers"], ["MARTA", "IVÁN"])
        self.assertIn("La lluvia golpea la ventana", brief["narration"])
        self.assertEqual(len(brief["dialogue"]), 2)
        self.assertIn("MARTA: No voy a firmar.", brief["dialogue"][0])
        self.assertIn("MARTA:", brief["canon_reference"])
        self.assertIn("IVÁN:", brief["canon_reference"])
        self.assertNotIn("LUCÍA:", brief["canon_reference"])
        self.assertIn("Marta todavía conserva la carta", brief["continuity_reference"])

    def test_visual_brief_handles_unlabelled_scene_and_empty_context(self):
        brief = build_scene_visual_brief(
            {"title": "Pasillo", "text": "Una puerta se abre lentamente en el pasillo oscuro."}
        )
        self.assertEqual(brief["speakers"], [])
        self.assertEqual(brief["narration"], "Una puerta se abre lentamente en el pasillo oscuro.")
        self.assertEqual(brief["canon_reference"], "")
        self.assertEqual(brief["continuity_reference"], "")

    def test_visual_brief_respects_context_size_limits(self):
        brief = build_scene_visual_brief(
            {"title": " Título   largo ", "text": "texto " * 100},
            story_bible="canon " * 100,
            continuity_state="estado " * 100,
            max_excerpt_chars=25,
            max_canon_chars=35,
            max_continuity_chars=20,
        )
        self.assertLessEqual(len(brief["excerpt"]), 25)
        self.assertLessEqual(len(brief["canon_reference"]), 35)
        self.assertLessEqual(len(brief["continuity_reference"]), 20)
        self.assertEqual(brief["title"], "Título largo")


    def test_expand_scenes_to_target_shot_count_without_losing_text(self):
        original_text = (
            "[NARRADOR]: La puerta se abre lentamente. Marta entra en la habitación y descubre "
            "una fotografía sobre la mesa. Nadie debería estar allí. Una sombra se mueve detrás "
            "de la cortina. Marta retrocede y escucha tres golpes en la pared."
        )
        original = [{"index": 1, "title": "La habitación", "text": original_text, "word_count": len(original_text.split())}]
        expanded = expand_scenes_to_shots(original, target_shots=4)
        self.assertGreaterEqual(len(expanded), 4)
        self.assertEqual([item["index"] for item in expanded], list(range(1, len(expanded) + 1)))
        self.assertTrue(all(item["word_count"] == len(item["text"].split()) for item in expanded))
        self.assertIn("Marta", " ".join(item["text"] for item in expanded))
        self.assertTrue(all(item["text"].strip() for item in expanded))

    def test_expand_scenes_keeps_short_scenes_and_respects_limit(self):
        scenes = [{"title": "Corto", "text": "[JUAN]: Corre.", "word_count": 2}]
        self.assertEqual(expand_scenes_to_shots(scenes, target_shots=20), scenes)
        long_text = " ".join(["palabra"] * 80)
        expanded = expand_scenes_to_shots([{"title": "Largo", "text": long_text}], target_shots=20, max_scenes=5)
        self.assertEqual(len(expanded), 5)

    def test_scene_duration_sum_matches_target_when_feasible(self):
        scenes = [
            {"word_count": 100, "text": "one"},
            {"word_count": 200, "text": "two"},
            {"word_count": 100, "text": "three"},
        ]
        durations = allocate_scene_durations(scenes, 12)
        self.assertEqual(sum(durations), 12)
        self.assertTrue(all(1 <= x <= 5 for x in durations))
        self.assertGreaterEqual(durations[1], durations[0])

    def test_duration_respects_five_second_cap_for_many_scenes(self):
        scenes = [{"word_count": 1, "text": "scene"} for _ in range(30)]
        durations = allocate_scene_durations(scenes, 60)
        self.assertEqual(len(durations), 30)
        self.assertTrue(all(1 <= x <= 5 for x in durations))
        self.assertEqual(sum(durations), 60)

    def test_duration_shortens_if_there_are_too_few_scenes(self):
        scenes = [{"word_count": 100, "text": "scene"} for _ in range(3)]
        durations = allocate_scene_durations(scenes, 120)
        self.assertEqual(durations, [5, 5, 5])
        self.assertEqual(sum(durations), 15)

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

    def test_audio_filter_graph_for_voice_only(self):
        graph = build_audio_filter_graph(True, False, voice_input_index=0)
        self.assertIn("[0:a:0]volume=1.000,apad[aout]", graph)
        self.assertNotIn("amix", graph)

    def test_audio_filter_graph_for_music_only(self):
        graph = build_audio_filter_graph(False, True, music_input_index=0)
        self.assertIn("[0:a:0]volume=0.180,afade=t=in:st=0:d=1.500,apad[aout]", graph)
        self.assertNotIn("amix", graph)
        self.assertNotIn("sidechaincompress", graph)

    def test_audio_filter_graph_mixes_voice_and_background_music(self):
        graph = build_audio_filter_graph(
            True, True, voice_input_index=0, music_input_index=1,
            duration_seconds=12, music_fade_seconds=1.5
        )
        self.assertIn("[0:a:0]volume=1.000,apad[voice]", graph)
        self.assertIn(
            "[1:a:0]atrim=duration=12.000,asetpts=PTS-STARTPTS,"
            "volume=0.180,afade=t=in:st=0:d=1.500,"
            "afade=t=out:st=10.500:d=1.500,apad[music]",
            graph,
        )
        self.assertIn(
            "[music][voice]sidechaincompress=threshold=0.035:ratio=5:attack=20:release=450[ducked]",
            graph,
        )
        self.assertIn("[voice][ducked]amix=inputs=2", graph)
        self.assertTrue(graph.endswith("[aout]"))

    def test_audio_filter_graph_keeps_fades_non_overlapping_for_short_video(self):
        graph = build_audio_filter_graph(
            False, True, music_input_index=0,
            duration_seconds=1, music_fade_seconds=1.5
        )
        self.assertIn("atrim=duration=1.000,asetpts=PTS-STARTPTS", graph)
        self.assertIn("afade=t=in:st=0:d=0.500", graph)
        self.assertIn("afade=t=out:st=0.500:d=0.500", graph)

    def test_audio_filter_graph_can_disable_music_ducking(self):
        graph = build_audio_filter_graph(
            True, True, voice_input_index=0, music_input_index=1, duck_music=False
        )
        self.assertIn("[voice][music]amix=inputs=2", graph)
        self.assertNotIn("sidechaincompress", graph)

    def test_audio_filter_graph_requires_audio_input_indexes(self):
        with self.assertRaises(ValueError):
            build_audio_filter_graph(True, False)
        with self.assertRaises(ValueError):
            build_audio_filter_graph(False, True)

    def test_audio_filter_graph_rejects_invalid_duration_and_fade(self):
        with self.assertRaises(ValueError):
            build_audio_filter_graph(False, True, music_input_index=0, duration_seconds=0)
        with self.assertRaises(ValueError):
            build_audio_filter_graph(False, True, music_input_index=0, duration_seconds=-2)
        with self.assertRaises(ValueError):
            build_audio_filter_graph(False, True, music_input_index=0, music_fade_seconds=-1)

    def test_filter_path_escapes_windows_colon_and_apostrophe(self):
        escaped = ffmpeg_filter_path(r"C:\Users\Marc's files\scene:01.txt")
        self.assertIn(r"C\:", escaped)
        self.assertIn(r"Marc\'s files", escaped)

    def test_motion_filter_uses_requested_output_size(self):
        result = scene_motion_filter("2D fluida", 1280, 720, 10)
        self.assertIn("s=1280x720", result)
        pixel = scene_motion_filter("Pixel animation", 720, 1280, 5)
        self.assertIn("flags=neighbor", pixel)

    def test_subtitle_filter_supports_font_color_position_and_outline(self):
        with tempfile.TemporaryDirectory() as tmp:
            subtitle = Path(tmp) / "Marc's subtitles:01.txt"
            subtitle.write_text("Texto de prueba", encoding="utf-8")
            result = build_subtitle_drawtext_filter(subtitle, None, 42, color="Amarillo", position="Centro", outline=True)
            self.assertIn("fontcolor=yellow", result)
            self.assertIn("fontsize=42", result)
            self.assertIn("y=(h-text_h)/2", result)
            self.assertIn("borderw=3", result)
            self.assertIn("box=1", result)
            self.assertIn(r"Marc\'s subtitles\:01.txt", result)

    def test_subtitle_filter_defaults_to_lower_third_and_validates_size(self):
        result = build_subtitle_drawtext_filter("caption.txt", None, 1000, color="unknown")
        self.assertIn("fontsize=96", result)
        self.assertIn("fontcolor=white", result)
        self.assertIn("y=h-text_h-h*0.06", result)
        self.assertIn("borderw=3", result)

    def test_motion_intensity_changes_zoom_amount(self):
        subtle = scene_motion_filter("2D fluida", 1280, 720, 5, "Suave")
        energetic = scene_motion_filter("2D fluida", 1280, 720, 5, "Muy animado")
        self.assertIn("1.025", subtle)
        self.assertIn("1.16", energetic)
        self.assertNotEqual(subtle, energetic)


if __name__ == "__main__":
    unittest.main()
