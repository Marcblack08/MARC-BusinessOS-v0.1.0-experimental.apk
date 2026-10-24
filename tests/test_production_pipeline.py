import tempfile
import unittest
from pathlib import Path

from production_pipeline import ProductionPipeline, STAGES


class ProductionPipelineTests(unittest.TestCase):
    def test_pipeline_starts_pending_and_persists_across_instances(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "production_pipeline.json"
            pipeline = ProductionPipeline(path)
            self.assertEqual(pipeline.next_pending(), "script")
            pipeline.mark("script", "running", "Generando borrador")
            pipeline.mark("script", "completed", "Guion guardado", artifacts=["script.txt"])

            restored = ProductionPipeline(path)
            stage = restored.snapshot()["stages"]["script"]
            self.assertEqual(stage["status"], "completed")
            self.assertEqual(stage["artifacts"], ["script.txt"])
            self.assertEqual(stage["attempts"], 1)
            self.assertEqual(restored.next_pending(), "review")

    def test_failed_stage_can_be_retried_without_losing_completed_prior_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = ProductionPipeline(Path(tmp) / "pipeline.json")
            pipeline.mark("script", "completed")
            pipeline.mark("review", "completed")
            pipeline.mark("storyboard", "completed")
            pipeline.mark("images", "failed", error="ComfyUI desconectado")
            pipeline.mark("montage", "completed")
            self.assertEqual(pipeline.retry_failed(), "images")
            snapshot = pipeline.snapshot()["stages"]
            self.assertEqual(snapshot["script"]["status"], "completed")
            self.assertEqual(snapshot["review"]["status"], "completed")
            self.assertEqual(snapshot["storyboard"]["status"], "completed")
            self.assertEqual(snapshot["images"]["status"], "pending")
            self.assertEqual(snapshot["montage"]["status"], "pending")
            self.assertEqual(pipeline.next_pending(), "images")

    def test_cancel_returns_running_stage_to_pending(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = ProductionPipeline(Path(tmp) / "pipeline.json")
            pipeline.mark("images", "running")
            pipeline.cancel()
            state = pipeline.snapshot()
            self.assertTrue(state["cancelled"])
            self.assertIsNone(state["current_stage"])
            self.assertEqual(state["stages"]["images"]["status"], "pending")

    def test_invalid_stage_or_status_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = ProductionPipeline(Path(tmp) / "pipeline.json")
            with self.assertRaises(ValueError):
                pipeline.mark("unknown", "running")
            with self.assertRaises(ValueError):
                pipeline.mark("script", "unknown")

    def test_summary_counts_stage_states(self):
        with tempfile.TemporaryDirectory() as tmp:
            pipeline = ProductionPipeline(Path(tmp) / "pipeline.json")
            pipeline.mark("script", "completed")
            pipeline.mark("review", "running")
            summary = pipeline.summary()
            self.assertEqual(summary["completed"], 1)
            self.assertEqual(summary["running"], 1)
            self.assertEqual(sum(summary.values()), len(STAGES))


if __name__ == "__main__":
    unittest.main()
