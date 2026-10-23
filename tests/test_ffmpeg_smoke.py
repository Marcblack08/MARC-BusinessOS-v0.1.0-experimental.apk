"""End-to-end FFmpeg smoke tests for MP4 muxing and local audio tracks."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from scene_engine import build_audio_filter_graph


FFMPEG = shutil.which("ffmpeg")
FFPROBE = shutil.which("ffprobe")


@unittest.skipUnless(FFMPEG and FFPROBE, "ffmpeg/ffprobe are needed for media integration tests")
class FFmpegAudioIntegrationTests(unittest.TestCase):
    def _run(self, args: list[str]) -> None:
        result = subprocess.run(args, capture_output=True, text=True, timeout=90)
        if result.returncode:
            raise AssertionError(
                f"Command failed ({result.returncode}): {' '.join(args)}\n"
                f"{(result.stderr or result.stdout)[-4000:]}"
            )

    def _assert_contains_streams(self, media: Path) -> None:
        result = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(media)],
            capture_output=True, text=True, timeout=30, check=True
        )
        streams = set(result.stdout.splitlines())
        self.assertIn("video", streams, f"No video stream in {media}")
        self.assertIn("audio", streams, f"No audio stream in {media}")

    def test_mux_voice_and_looped_background_music_to_mp4(self):
        with tempfile.TemporaryDirectory(prefix="marc_ffmpeg_test_") as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            voice = root / "voice.wav"
            music = root / "music.wav"
            output = root / "mixed.mp4"

            self._run([
                FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=0x102030:s=320x180:r=24",
                "-t", "2", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(video)
            ])
            self._run([
                FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "2", "-c:a", "pcm_s16le", str(voice)
            ])
            self._run([
                FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=44100",
                "-t", "0.5", "-c:a", "pcm_s16le", str(music)
            ])

            graph = build_audio_filter_graph(True, True, voice_input_index=0, music_input_index=1)
            self._run([
                FFMPEG, "-y", "-i", str(voice), "-stream_loop", "-1", "-i", str(music),
                "-i", str(video), "-filter_complex", graph, "-map", "2:v:0", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "128k", "-shortest",
                "-movflags", "+faststart", str(output)
            ])
            self.assertTrue(output.is_file())
            self.assertGreater(output.stat().st_size, 1000)
            self._assert_contains_streams(output)

    def test_mux_single_voice_track_to_mp4(self):
        with tempfile.TemporaryDirectory(prefix="marc_ffmpeg_voice_test_") as tmp:
            root = Path(tmp)
            video = root / "video.mp4"
            voice = root / "voice.wav"
            output = root / "voice_only.mp4"
            self._run([
                FFMPEG, "-y", "-f", "lavfi", "-i", "color=c=0x102030:s=320x180:r=24",
                "-t", "1.5", "-an", "-c:v", "libx264", "-preset", "ultrafast",
                "-pix_fmt", "yuv420p", str(video)
            ])
            self._run([
                FFMPEG, "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100",
                "-t", "1.5", "-c:a", "pcm_s16le", str(voice)
            ])
            graph = build_audio_filter_graph(True, False, voice_input_index=0)
            self._run([
                FFMPEG, "-y", "-i", str(voice), "-i", str(video),
                "-filter_complex", graph, "-map", "1:v:0", "-map", "[aout]",
                "-c:v", "copy", "-c:a", "aac", "-shortest", str(output)
            ])
            self._assert_contains_streams(output)


if __name__ == "__main__":
    unittest.main()
