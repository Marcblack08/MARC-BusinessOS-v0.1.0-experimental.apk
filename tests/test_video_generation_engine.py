import unittest

from video_generation_engine import prepare_workflow, visual_workflow_to_api, VideoGenerationError


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


    def test_converts_official_style_ltx_visual_workflow_and_injects_image_prompt(self):
        nodes = [
            {"id": 44, "type": "CheckpointLoaderSimple", "inputs": [], "widgets_values": ["ltx-video-2b-v0.9.5.safetensors"]},
            {"id": 38, "type": "CLIPLoader", "inputs": [], "widgets_values": ["t5xxl_fp16.safetensors", "ltxv", "default"]},
            {"id": 6, "type": "CLIPTextEncode", "inputs": [{"name": "clip", "link": 1}], "widgets_values": ["old positive prompt"]},
            {"id": 7, "type": "CLIPTextEncode", "inputs": [{"name": "clip", "link": 2}], "widgets_values": ["bad anatomy, blurry"]},
            {"id": 78, "type": "LoadImage", "inputs": [], "widgets_values": ["old.png", "image"]},
            {"id": 77, "type": "LTXVImgToVideo", "inputs": [
                {"name": "positive", "link": 3}, {"name": "negative", "link": 4},
                {"name": "vae", "link": 5}, {"name": "image", "link": 6},
            ], "widgets_values": [512, 320, 97, 1, 0.15]},
            {"id": 69, "type": "LTXVConditioning", "inputs": [
                {"name": "positive", "link": 7}, {"name": "negative", "link": 8},
            ], "widgets_values": [24]},
            {"id": 71, "type": "LTXVScheduler", "inputs": [{"name": "latent", "link": 9}],
             "widgets_values": [20, 2.05, 0.95, True, 0.1]},
            {"id": 73, "type": "KSamplerSelect", "inputs": [], "widgets_values": ["euler"]},
            {"id": 72, "type": "SamplerCustom", "inputs": [
                {"name": "model", "link": 10}, {"name": "positive", "link": 11},
                {"name": "negative", "link": 12}, {"name": "sampler", "link": 13},
                {"name": "sigmas", "link": 14}, {"name": "latent_image", "link": 15},
            ], "widgets_values": [True, 12345, "randomize", 3]},
            {"id": 8, "type": "VAEDecode", "inputs": [
                {"name": "samples", "link": 16}, {"name": "vae", "link": 17},
            ], "widgets_values": []},
            {"id": 80, "type": "CreateVideo", "inputs": [
                {"name": "images", "link": 18}, {"name": "audio", "link": None},
            ], "widgets_values": [24]},
            {"id": 81, "type": "SaveVideo", "inputs": [{"name": "video", "link": 19}],
             "widgets_values": ["video/ComfyUI", "auto", "auto"]},
            {"id": 76, "type": "Note", "inputs": [], "widgets_values": ["editor note"]},
        ]
        links = [
            [1, 38, 0, 6, 0, "CLIP"], [2, 38, 0, 7, 0, "CLIP"],
            [3, 6, 0, 77, 0, "CONDITIONING"], [4, 7, 0, 77, 1, "CONDITIONING"],
            [5, 44, 2, 77, 2, "VAE"], [6, 78, 0, 77, 3, "IMAGE"],
            [7, 77, 0, 69, 0, "CONDITIONING"], [8, 77, 1, 69, 1, "CONDITIONING"],
            [9, 77, 2, 71, 0, "LATENT"], [10, 44, 0, 72, 0, "MODEL"],
            [11, 69, 0, 72, 1, "CONDITIONING"], [12, 69, 1, 72, 2, "CONDITIONING"],
            [13, 73, 0, 72, 3, "SAMPLER"], [14, 71, 0, 72, 4, "SIGMAS"],
            [15, 77, 2, 72, 5, "LATENT"], [16, 72, 0, 8, 0, "LATENT"],
            [17, 44, 2, 8, 1, "VAE"], [18, 8, 0, 80, 0, "IMAGE"],
            [19, 80, 0, 81, 0, "VIDEO"],
        ]
        visual = {"nodes": nodes, "links": links}
        api = visual_workflow_to_api(visual)
        self.assertNotIn("76", api)
        self.assertEqual(api["81"]["inputs"]["format"], {"format": "auto", "codec": "auto"})
        prepared = prepare_workflow(
            visual, "reference.png", "La mujer camina hacia la puerta", frame_count=49
        )
        self.assertEqual(prepared["78"]["inputs"]["image"], "reference.png")
        self.assertEqual(prepared["6"]["inputs"]["text"], "La mujer camina hacia la puerta")
        self.assertEqual(prepared["7"]["inputs"]["text"], "bad anatomy, blurry")
        self.assertEqual(prepared["77"]["inputs"]["length"], 49)
        self.assertEqual(prepared["77"]["inputs"]["width"], 768)
        self.assertEqual(prepared["77"]["inputs"]["height"], 512)
        vertical = prepare_workflow(
            visual, "reference.png", "La mujer camina hacia la puerta",
            frame_count=49, output_width=512, output_height=768
        )
        self.assertEqual(vertical["77"]["inputs"]["width"], 512)
        self.assertEqual(vertical["77"]["inputs"]["height"], 768)



if __name__ == "__main__":
    unittest.main()
