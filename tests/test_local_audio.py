import tempfile
import unittest
import wave
from pathlib import Path

from local_audio import generate_ambient_bed, infer_mood


class LocalAudioTests(unittest.TestCase):
    def test_generates_stereo_pcm_bed_with_non_silent_audio(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_ambient_bed(Path(tmp) / "bed.wav", mood="misterio", seconds=8, sample_rate=8000)
            self.assertTrue(path.is_file())
            with wave.open(str(path), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 2)
                self.assertEqual(audio.getsampwidth(), 2)
                self.assertEqual(audio.getframerate(), 8000)
                self.assertEqual(audio.getnframes(), 8 * 8000)
                data = audio.readframes(200)
            self.assertTrue(any(byte != 0 for byte in data))

    def test_selects_mood_from_story_context(self):
        self.assertEqual(infer_mood("Terror: una sombra persigue a la familia en la casa"), "terror")
        self.assertEqual(infer_mood("La protagonista descubre un secreto"), "misterio")
        self.assertEqual(infer_mood("Un gran viaje y una batalla épica"), "aventura")
        self.assertEqual(infer_mood("Una historia familiar"), "drama")

    def test_rejects_invalid_duration(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                generate_ambient_bed(Path(tmp) / "bad.wav", seconds=1)


if __name__ == "__main__":
    unittest.main()
