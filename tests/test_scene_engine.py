import re
import tempfile
import unittest
from pathlib import Path

from scene_engine import (
    allocate_scene_durations, build_audio_filter_graph, build_scene_visual_brief,
    build_cinematic_image_prompt, build_comfy_image_workflow, build_video_transition_filter_graph, camera_direction_for_shot,
    expand_scenes_to_shots, build_srt_subtitles, build_srt_from_timed_segments,
    build_subtitle_drawtext_filter, ffmpeg_filter_path, parse_script_scenes, scene_motion_filter
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
        self.assertTrue(all(item.get("source_scene_index") == 1 for item in expanded))
        self.assertTrue(all(not re.search(r"— plano [AB] — plano [AB]$", item["title"]) for item in expanded))

    def test_expand_supports_twenty_minute_storyboards_and_keeps_source_scene(self):
        text = " ".join(["palabra."] * 4000)
        expanded = expand_scenes_to_shots(
            [{"title": "Escena de prueba", "text": text, "word_count": len(text.split())}],
            target_shots=240,
        )
        self.assertEqual(len(expanded), 240)
        self.assertTrue(all(item.get("source_scene_index") == 1 for item in expanded))
        self.assertEqual([item["index"] for item in expanded], list(range(1, 241)))

    def test_expand_scenes_keeps_short_scenes_and_respects_limit(self):
        scenes = [{"title": "Corto", "text": "[JUAN]: Corre.", "word_count": 2}]
        short_result = expand_scenes_to_shots(scenes, target_shots=20)
        self.assertEqual(len(short_result), 1)
        self.assertEqual(short_result[0]["text"], scenes[0]["text"])
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

    def test_srt_long_scene_is_split_into_readable_cues(self):
        text = (
            "[NARRADOR]: La puerta se abre lentamente y Marta entra en la habitación. "
            "Una fotografía cae al suelo. Desde el pasillo, alguien susurra su nombre."
        )
        srt = build_srt_subtitles([{"text": text}], [5], chars_per_line=34)
        cues = srt.strip().split("\n\n")
        self.assertGreater(len(cues), 1)
        self.assertTrue(all(len("\\n".join(cue.splitlines()[2:])) <= 34 for cue in cues))
        self.assertNotIn("[NARRADOR]", srt)
        self.assertIn("00:00:05,000", cues[-1])

    def test_srt_cues_remain_contiguous_across_scenes(self):
        srt = build_srt_subtitles(
            [{"text": "Primera escena con bastante texto para dividir."}, {"text": "[MARTA]: Ya llegué."}],
            [3, 2],
            chars_per_line=20,
        )
        cues = [cue.splitlines() for cue in srt.strip().split("\n\n")]
        self.assertTrue(cues[0][1].startswith("00:00:00,000 -->"))
        self.assertTrue(cues[-1][1].endswith("00:00:05,000"))
        self.assertEqual(cues[-1][2], "Ya llegué.")

    def test_srt_scales_scene_cues_to_actual_media_duration(self):
        scenes = [{"text": "[NARRADOR]: Primera escena."}, {"text": "[MARTA]: Segunda escena."}]
        srt = build_srt_subtitles(scenes, [5, 5], total_duration_seconds=14.25)
        cues = [item.splitlines() for item in srt.strip().split("\n\n")]
        self.assertEqual(cues[0][1], "00:00:00,000 --> 00:00:07,125")
        self.assertEqual(cues[1][1], "00:00:07,125 --> 00:00:14,250")
        self.assertNotIn("[NARRADOR]", srt)
        self.assertNotIn("[MARTA]", srt)

    def test_srt_duration_scaling_preserves_empty_scenes(self):
        srt = build_srt_subtitles(
            [{"text": "Primera."}, {"text": ""}, {"text": "Tercera."}],
            [2, 2, 2], total_duration_seconds=9,
        )
        cues = [item.splitlines() for item in srt.strip().split("\n\n")]
        self.assertEqual(cues[0][1], "00:00:00,000 --> 00:00:03,000")
        self.assertEqual(cues[1][1], "00:00:06,000 --> 00:00:09,000")

    def test_srt_rejects_non_positive_or_non_finite_timing(self):
        for durations in ([0], [-1], [float("nan")], [float("inf")]):
            with self.subTest(durations=durations):
                with self.assertRaises(ValueError):
                    build_srt_subtitles([{"text": "Texto"}], durations)
        for total in (0, -1, float("nan"), float("inf")):
            with self.subTest(total=total):
                with self.assertRaises(ValueError):
                    build_srt_subtitles([{"text": "Texto"}], [1], total_duration_seconds=total)

    def test_timed_srt_uses_measured_phrase_boundaries(self):
        srt = build_srt_from_timed_segments([
            {"text": "[NARRADOR]: No abras esa puerta.", "start_seconds": 0.42, "end_seconds": 1.68},
            {"text": "[MARTA]: ¿Quién está ahí?", "start_seconds": 1.92, "end_seconds": 3.14},
        ], total_duration_seconds=4.0)
        cues = [item.splitlines() for item in srt.strip().split("\n\n")]
        self.assertEqual(cues[0][1], "00:00:00,420 --> 00:00:01,680")
        self.assertEqual(cues[1][1], "00:00:01,920 --> 00:00:03,140")
        self.assertNotIn("[NARRADOR]", srt)
        self.assertNotIn("[MARTA]", srt)

    def test_timed_srt_rejects_unordered_or_invalid_segments(self):
        with self.assertRaises(ValueError):
            build_srt_from_timed_segments([
                {"text": "Uno", "start_seconds": 2, "end_seconds": 3},
                {"text": "Dos", "start_seconds": 1, "end_seconds": 2},
            ])
        with self.assertRaises(ValueError):
            build_srt_from_timed_segments([
                {"text": "Inválido", "start_seconds": 1, "end_seconds": 1}
            ])

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

    def test_adjacent_shots_use_different_camera_moves(self):
        moves = [
            scene_motion_filter("2D fluida", 720, 1280, 5, "Normal", shot_index=index)
            for index in range(5)
        ]
        self.assertEqual(len(set(moves)), 5)
        self.assertIn("zoompan", moves[0])
        self.assertNotIn("0.0015*on", moves[0])
        self.assertIn("if(eq(on,0)", moves[1])
        self.assertIn("on/", moves[2])

    def test_cinematic_image_prompts_change_camera_and_keep_emotion_specific(self):
        first = camera_direction_for_shot(1)
        second = camera_direction_for_shot(2)
        self.assertNotEqual(first, second)
        prompt = build_cinematic_image_prompt(
            "cinematic anime frame", "Mateo sees a figure inside the elevator",
            3, title="El ascensor", canon_reference="Mateo has short black hair and a navy uniform",
        )
        self.assertIn("tight emotional close-up", prompt)
        self.assertIn("Mateo sees a figure", prompt)
        self.assertIn("short black hair", prompt)
        self.assertIn("one coherent moment", prompt)

    def test_transition_graph_contains_real_crossfades_and_exact_timeline_trim(self):
        graph = build_video_transition_filter_graph([5, 4, 3], transition_seconds=0.4)
        self.assertIn("xfade=transition=fade:duration=0.400:offset=5.000", graph)
        self.assertIn("xfade=transition=fade:duration=0.400:offset=9.000", graph)
        self.assertIn("trim=duration=12.000", graph)
        self.assertTrue(graph.endswith("[vout]"))

    def test_transition_graph_supports_multiple_real_effects(self):
        cases = {
            "Fundido suave": "transition=fade",
            "Deslizar izquierda": "transition=slideleft",
            "Deslizar derecha": "transition=slideright",
            "Barrido izquierda": "transition=wipeleft",
            "Barrido derecha": "transition=wiperight",
            "Zoom cinematográfico": "transition=zoomin",
        }
        for style, expected in cases.items():
            with self.subTest(style=style):
                graph = build_video_transition_filter_graph([5, 4], transition_style=style)
                self.assertIn(expected, graph)

    def test_transition_graph_rejects_invalid_durations(self):
        with self.assertRaises(ValueError):
            build_video_transition_filter_graph([])
        with self.assertRaises(ValueError):
            build_video_transition_filter_graph([5, 0])
        with self.assertRaises(ValueError):
            build_video_transition_filter_graph([5], transition_seconds=2)

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
        self.assertIn("1.035", subtle)
        self.assertIn("1.19", energetic)
        self.assertNotEqual(subtle, energetic)

    def test_visual_brief_does_not_pass_emotion_tags_to_image_prompt(self):
        brief = build_scene_visual_brief({
            "title": "La advertencia",
            "text": "[MATEO]: [EMOCION=miedo] ¡No abras el ascensor!"
        })
        self.assertNotIn("EMOCION", brief["excerpt"])
        self.assertNotIn("EMOCION", " ".join(brief["dialogue"]))


    def test_comfy_image_workflow_uses_normal_save_path_without_upscaler(self):
        workflow = build_comfy_image_workflow(
            "DreamShaper8_pruned.safetensors", "cinematic portrait", "blurry",
            384, 672, 2, seed=123, steps=22
        )
        self.assertEqual(workflow["4"]["inputs"]["width"], 384)
        self.assertEqual(workflow["4"]["inputs"]["height"], 672)
        self.assertNotIn("UpscaleModelLoader", {node["class_type"] for node in workflow.values()})
        self.assertEqual(workflow["7"]["inputs"]["images"], ["6", 0])

    def test_comfy_image_workflow_can_apply_optional_ai_upscaler(self):
        workflow = build_comfy_image_workflow(
            "DreamShaper8_pruned.safetensors", "cinematic portrait", "blurry",
            384, 672, 3, upscale_model="4x-UltraSharp.pth", seed=456
        )
        self.assertEqual(workflow["8"]["class_type"], "UpscaleModelLoader")
        self.assertEqual(workflow["8"]["inputs"]["model_name"], "4x-UltraSharp.pth")
        self.assertEqual(workflow["9"]["class_type"], "ImageUpscaleWithModel")
        self.assertEqual(workflow["9"]["inputs"]["image"], ["6", 0])
        self.assertEqual(workflow["7"]["inputs"]["images"], ["9", 0])

    def test_comfy_image_workflow_validates_dimensions_and_checkpoint(self):
        with self.assertRaises(ValueError):
            build_comfy_image_workflow("", "prompt", "negative", 512, 512, 1)
        with self.assertRaises(ValueError):
            build_comfy_image_workflow("model.safetensors", "prompt", "negative", 513, 512, 1)
        with self.assertRaises(ValueError):
            build_comfy_image_workflow("model.safetensors", "prompt", "negative", 512, 512, 1, steps=0)


    def test_scene_motion_direction_overrides_default_camera_move(self):
        default_move = scene_motion_filter("2D fluida", 1280, 720, 5, "Normal", shot_index=0)
        zoom_out = scene_motion_filter("2D fluida", 1280, 720, 5, "Normal", shot_index=0, direction="La cámara se aleja lentamente")
        pan_left = scene_motion_filter("2D fluida", 1280, 720, 5, "Normal", shot_index=0, direction="Paneo de derecha a izquierda")
        pan_right = scene_motion_filter("2D fluida", 1280, 720, 5, "Normal", shot_index=0, direction="Paneo de izquierda a derecha")
        self.assertNotEqual(default_move, zoom_out)
        self.assertNotEqual(zoom_out, pan_left)
        self.assertNotEqual(pan_left, pan_right)
        self.assertIn("if(eq(on,0)", zoom_out)
        self.assertIn("min(on/", pan_left)
        self.assertIn("min(on/", pan_right)

if __name__ == "__main__":
    unittest.main()
