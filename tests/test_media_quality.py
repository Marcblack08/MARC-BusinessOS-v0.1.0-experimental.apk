import unittest

from media_quality import parse_ffmpeg_probe_text, validate_media_info, validate_srt_text


class MediaQualityTests(unittest.TestCase):
    def sample_info(self):
        return {
            "format": {"duration": "120.02"},
            "streams": [
                {"codec_type": "video", "width": 1280, "height": 720, "avg_frame_rate": "30/1"},
                {"codec_type": "audio", "codec_name": "aac"},
            ],
        }

    def test_accepts_expected_video_audio_duration_resolution_and_fps(self):
        result = validate_media_info(
            self.sample_info(), expected_width=1280, expected_height=720,
            expected_fps=30, minimum_duration=119, require_audio=True,
        )
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["width"], 1280)
        self.assertEqual(result["height"], 720)
        self.assertEqual(result["audio_streams"], 1)
        self.assertAlmostEqual(result["duration"], 120.02)

    def test_rejects_missing_video_and_required_audio(self):
        result = validate_media_info(
            {"format": {"duration": 10}, "streams": []},
            expected_width=1280, expected_height=720, expected_fps=30,
            minimum_duration=9, require_audio=True,
        )
        self.assertFalse(result["passed"])
        self.assertTrue(any("pista de vídeo" in error for error in result["errors"]))
        self.assertTrue(any("pista de audio" in error for error in result["errors"]))

    def test_rejects_wrong_dimensions_fps_and_short_duration(self):
        result = validate_media_info(
            self.sample_info(), expected_width=1920, expected_height=1080,
            expected_fps=60, minimum_duration=150, require_audio=True,
        )
        self.assertFalse(result["passed"])
        failed = {check["name"] for check in result["checks"] if not check["passed"]}
        self.assertIn("expected_dimensions", failed)
        self.assertIn("fps", failed)
        self.assertIn("minimum_duration", failed)

    def test_ffmpeg_text_fallback_extracts_duration_video_and_audio(self):
        output = (
            "Duration: 00:02:00.50, start: 0.000000, bitrate: 1500 kb/s\n"
            "Stream #0:0: Video: h264, yuv420p, 1280x720, 30 fps, 30 tbr\n"
            "Stream #0:1: Audio: aac, 48000 Hz, stereo"
        )
        info = parse_ffmpeg_probe_text(output)
        result = validate_media_info(info, expected_width=1280, expected_height=720, expected_fps=30, require_audio=True)
        self.assertTrue(result["passed"], result["errors"])
        self.assertAlmostEqual(result["duration"], 120.5)
        self.assertEqual(result["audio_streams"], 1)

    def test_srt_validator_accepts_sequential_non_overlapping_cues(self):
        text = (
            "1\n00:00:00,000 --> 00:00:02,000\nLa puerta estaba abierta.\n\n"
            "2\n00:00:02,000 --> 00:00:04,500\nNo debiste venir."
        )
        result = validate_srt_text(text)
        self.assertTrue(result["passed"], result["errors"])
        self.assertEqual(result["cue_count"], 2)

    def test_srt_validator_rejects_bad_timestamps_and_nonconsecutive_numbers(self):
        text = (
            "1\n00:00:03,000 --> 00:00:02,000\nTexto uno.\n\n"
            "3\n00:00:01,000 --> 00:00:04,000\nTexto dos."
        )
        result = validate_srt_text(text)
        self.assertFalse(result["passed"])
        self.assertTrue(any("hora final" in error for error in result["errors"]))
        self.assertTrue(any("numeración" in error for error in result["errors"]))
        self.assertTrue(any("solapan" in error for error in result["errors"]))

    def test_ffmpeg_fallback_does_not_invent_missing_streams(self):
        info = parse_ffmpeg_probe_text("Duration: 00:00:01.00, start: 0.0")
        self.assertEqual(info["streams"], [])
        result = validate_media_info(info)
        self.assertFalse(result["passed"])


if __name__ == "__main__":
    unittest.main()
