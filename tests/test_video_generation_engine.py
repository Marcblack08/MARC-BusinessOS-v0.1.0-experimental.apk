import unittest

from video_generation_engine import prepare_workflow, VideoGenerationError


class VideoGenerationEngineTests(unittest.TestCase):
    def test_maps_reference_image_and_positive_prompt_without_touching_negative(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "old positive", "clip": ["9", 0]}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad anatomy, blurry", "clip": ["9", 0]}},
            "4": {"class_type": "KSampler", "inputs": {
                "positive": ["2", 0], "negative": ["3", 0], "model": ["9", 0]
            }},
            "5": {"class_type": "VideoCombine", "inputs": {"images": ["6", 0]}},
        }
        result = prepare_workflow(workflow, "reference.png", "La mujer camina con movimientos naturales")
        self.assertEqual(result["1"]["inputs"]["image"], "reference.png")
        self.assertEqual(result["2"]["inputs"]["text"], "La mujer camina con movimientos naturales")
        self.assertEqual(result["3"]["inputs"]["text"], "bad anatomy, blurry")
        self.assertEqual(workflow["1"]["inputs"]["image"], "old.png")

    def test_custom_negative_prompt_replaces_only_negative_encoder(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "positive text"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "bad quality"}},
            "4": {"class_type": "KSampler", "inputs": {"positive": ["2", 0], "negative": ["3", 0]}},
        }
        result = prepare_workflow(
            workflow, "reference.png", "Personaje corre hacia la puerta", "sin desenfoque"
        )
        self.assertEqual(result["2"]["inputs"]["text"], "Personaje corre hacia la puerta")
        self.assertEqual(result["3"]["inputs"]["text"], "sin desenfoque")

    def test_rejects_workflow_with_multiple_reference_images(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "one.png"}},
            "2": {"class_type": "LoadImage", "inputs": {"image": "two.png"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "move"}},
        }
        with self.assertRaises(VideoGenerationError):
            prepare_workflow(workflow, "reference.png", "walk")

    def test_rejects_ambiguous_positive_text_inputs(self):
        workflow = {
            "1": {"class_type": "LoadImage", "inputs": {"image": "one.png"}},
            "2": {"class_type": "CLIPTextEncode", "inputs": {"text": "first"}},
            "3": {"class_type": "CLIPTextEncode", "inputs": {"text": "second"}},
        }
        with self.assertRaises(VideoGenerationError):
            prepare_workflow(workflow, "reference.png", "walk")


if __name__ == "__main__":
    unittest.main()
