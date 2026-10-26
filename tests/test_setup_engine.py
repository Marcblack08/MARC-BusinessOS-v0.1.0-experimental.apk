import unittest
from unittest.mock import patch

import setup_engine


class SetupEngineTests(unittest.TestCase):
    def test_local_i2v_gate_rejects_old_cpu_only_computer(self):
        with patch("setup_engine.os.name", "nt"):
            self.assertFalse(setup_engine.supports_local_i2v({
                "gpu_name": "No GPU",
                "gpu_vram_gb": 0,
                "ram_gb": 12,
                "free_disk_gb": 100,
            }))
            self.assertFalse(setup_engine.supports_local_i2v({
                "gpu_name": "NVIDIA GTX 750",
                "gpu_vram_gb": 2,
                "ram_gb": 16,
                "free_disk_gb": 100,
            }))

    def test_local_i2v_gate_requires_memory_vram_and_disk(self):
        capable = {
            "gpu_name": "NVIDIA GeForce RTX 4070",
            "gpu_vram_gb": 12,
            "ram_gb": 32,
            "free_disk_gb": 80,
        }
        with patch("setup_engine.os.name", "nt"):
            self.assertTrue(setup_engine.supports_local_i2v(capable))
            for field, value in (("gpu_vram_gb", 7.9), ("ram_gb", 23.9), ("free_disk_gb", 29.9)):
                weaker = dict(capable)
                weaker[field] = value
                with self.subTest(field=field):
                    self.assertFalse(setup_engine.supports_local_i2v(weaker))

    def test_ollama_model_match_accepts_a_tagged_model_name(self):
        self.assertTrue(setup_engine._model_installed(["moondream:latest"], "moondream"))
        self.assertTrue(setup_engine._model_installed(["qwen2.5:3b"], "qwen2.5:3b"))
        self.assertFalse(setup_engine._model_installed(["qwen2.5:3b"], "moondream"))

    def test_report_summary_data_keeps_video_gate_explicit(self):
        hardware = {
            "gpu_name": "No GPU", "gpu_vram_gb": 0, "ram_gb": 12,
            "free_disk_gb": 40,
        }
        with patch("setup_engine.os.name", "nt"):
            self.assertFalse(setup_engine.supports_local_i2v(hardware))


if __name__ == "__main__":
    unittest.main()
