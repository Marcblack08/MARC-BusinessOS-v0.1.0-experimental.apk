from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from production_package import discover_production_package, parse_scene_directions


class ProductionPackageTests(unittest.TestCase):
    def test_discovers_script_directions_sorted_images_and_optional_audio(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "imagenes").mkdir()
            (root / "audio").mkdir()
            (root / "guion.md").write_text(
                "ESCENA 1 — La puerta\n[NARRADOR]: La puerta se abre.\n",
                encoding="utf-8",
            )
            (root / "direcciones.json").write_text(json.dumps({
                "scenes": [
                    {"scene": 1, "camera_motion": "Zoom lento hacia la puerta"},
                    {"scene": 2, "camera_motion": "Paneo de izquierda a derecha"},
                ]
            }), encoding="utf-8")
            (root / "imagenes" / "imagen_10.png").write_bytes(b"test")
            (root / "imagenes" / "imagen_2.png").write_bytes(b"test")
            (root / "audio" / "narracion.wav").write_bytes(b"test")
            (root / "audio" / "musica.mp3").write_bytes(b"test")

            package = discover_production_package(root)
            self.assertEqual(package.script_path.name, "guion.md")
            self.assertEqual([path.name for path in package.image_paths], ["imagen_2.png", "imagen_10.png"])
            self.assertEqual(package.narration_path.name, "narracion.wav")
            self.assertEqual(package.music_path.name, "musica.mp3")
            self.assertEqual(
                parse_scene_directions(package.direction_path),
                ["Zoom lento hacia la puerta", "Paneo de izquierda a derecha"],
            )

    def test_fails_with_clear_error_when_images_are_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "guion.txt").write_text("ESCENA 1: Prueba\n[NARRADOR]: Hola.", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "No encuentro imágenes"):
                discover_production_package(root)

    def test_selects_one_fallback_text_file_as_script(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "historia_final.md").write_text("ESCENA 1: Inicio\n[NARRADOR]: Hola.", encoding="utf-8")
            (root / "images").mkdir()
            (root / "images" / "001.jpg").write_bytes(b"img")
            package = discover_production_package(root)
            self.assertEqual(package.script_path.name, "historia_final.md")

    def test_plain_text_directions_support_one_instruction_per_line(self):
        with tempfile.TemporaryDirectory() as temporary:
            direction_file = Path(temporary) / "direcciones.txt"
            direction_file.write_text("Zoom lento hacia el rostro\nPaneo de izquierda a derecha\n", encoding="utf-8")
            self.assertEqual(
                parse_scene_directions(direction_file),
                ["Zoom lento hacia el rostro", "Paneo de izquierda a derecha"],
            )

    def test_plain_text_directions_support_numbered_blocks(self):
        with tempfile.TemporaryDirectory() as temporary:
            direction_file = Path(temporary) / "direcciones.md"
            direction_file.write_text("ESCENA 1: Acercamiento lento\nMovimiento hacia el rostro\n\nESCENA 2: Paneo\nDe derecha a izquierda", encoding="utf-8")
            self.assertEqual(
                parse_scene_directions(direction_file),
                ["Acercamiento lento Movimiento hacia el rostro", "Paneo De derecha a izquierda"],
            )


if __name__ == "__main__":
    unittest.main()
