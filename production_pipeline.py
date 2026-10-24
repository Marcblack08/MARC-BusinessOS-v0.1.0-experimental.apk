"""Persistent checkpoints for resumable MARC video-production workflows."""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PIPELINE_VERSION = 1
STAGES = (
    "script",
    "review",
    "storyboard",
    "images",
    "narration",
    "audio",
    "montage",
    "quality_check",
    "export",
)
STAGE_LABELS = {
    "script": "Guion",
    "review": "Revisión y aprobación",
    "storyboard": "Storyboard",
    "images": "Imágenes",
    "narration": "Narración",
    "audio": "Música y efectos",
    "montage": "Montaje",
    "quality_check": "Control de calidad",
    "export": "Exportación MP4",
}
STATUSES = {"pending", "running", "completed", "failed", "skipped"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ProductionPipeline:
    """Small atomic JSON journal; it records progress but never stores media itself."""

    def __init__(self, manifest_path: str | Path):
        self.path = Path(manifest_path)
        self.data = self._read()

    def _blank(self) -> dict[str, Any]:
        return {
            "version": PIPELINE_VERSION,
            "updated_at": _now(),
            "current_stage": None,
            "cancelled": False,
            "stages": {
                stage: {
                    "status": "pending",
                    "attempts": 0,
                    "started_at": None,
                    "completed_at": None,
                    "updated_at": None,
                    "details": "",
                    "error": "",
                    "artifacts": [],
                }
                for stage in STAGES
            },
        }

    def _read(self) -> dict[str, Any]:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            if payload.get("version") != PIPELINE_VERSION or not isinstance(payload.get("stages"), dict):
                return self._blank()
            base = self._blank()
            for stage in STAGES:
                saved = payload["stages"].get(stage, {})
                if isinstance(saved, dict):
                    base["stages"][stage].update(saved)
                    if base["stages"][stage].get("status") not in STATUSES:
                        base["stages"][stage]["status"] = "pending"
            base["current_stage"] = payload.get("current_stage") if payload.get("current_stage") in STAGES else None
            base["cancelled"] = bool(payload.get("cancelled", False))
            base["updated_at"] = str(payload.get("updated_at") or _now())
            return base
        except (OSError, ValueError, TypeError):
            return self._blank()

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.data["updated_at"] = _now()
        fd, temporary = tempfile.mkstemp(prefix=self.path.name + ".", suffix=".tmp", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self.data, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            try:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            except OSError:
                pass

    def mark(
        self,
        stage: str,
        status: str,
        details: str = "",
        error: str = "",
        artifacts: list[str] | None = None,
    ) -> dict[str, Any]:
        if stage not in STAGES:
            raise ValueError(f"Unknown production stage: {stage}")
        if status not in STATUSES:
            raise ValueError(f"Unknown stage status: {status}")
        item = self.data["stages"][stage]
        now = _now()
        if status == "running":
            item["attempts"] = int(item.get("attempts", 0)) + 1
            item["started_at"] = now
            self.data["current_stage"] = stage
            self.data["cancelled"] = False
        elif status in {"completed", "failed", "skipped"}:
            item["completed_at"] = now if status == "completed" else None
            if self.data.get("current_stage") == stage:
                self.data["current_stage"] = None
        item["status"] = status
        item["updated_at"] = now
        item["details"] = str(details or "")[:2000]
        item["error"] = str(error or "")[:4000]
        if artifacts is not None:
            item["artifacts"] = [str(path) for path in artifacts if str(path).strip()]
        self.save()
        return dict(item)

    def cancel(self, details: str = "Cancelado por el usuario") -> None:
        current = self.data.get("current_stage")
        if current and self.data["stages"][current]["status"] == "running":
            self.data["stages"][current]["status"] = "pending"
            self.data["stages"][current]["details"] = str(details)[:2000]
            self.data["stages"][current]["updated_at"] = _now()
        self.data["current_stage"] = None
        self.data["cancelled"] = True
        self.save()

    def retry_failed(self) -> str | None:
        """Reset the first failed stage and dependent later stages, preserving earlier work."""
        failed = next((stage for stage in STAGES if self.data["stages"][stage]["status"] == "failed"), None)
        if failed is None:
            return None
        start = STAGES.index(failed)
        for stage in STAGES[start:]:
            item = self.data["stages"][stage]
            if item["status"] != "pending":
                item["status"] = "pending"
                item["completed_at"] = None
                item["error"] = ""
                item["updated_at"] = _now()
        self.data["current_stage"] = None
        self.data["cancelled"] = False
        self.save()
        return failed

    def next_pending(self) -> str | None:
        return next((stage for stage in STAGES if self.data["stages"][stage]["status"] in {"pending", "failed"}), None)

    def snapshot(self) -> dict[str, Any]:
        return json.loads(json.dumps(self.data, ensure_ascii=False))

    def summary(self) -> dict[str, int]:
        return {status: sum(1 for stage in self.data["stages"].values() if stage["status"] == status) for status in STATUSES}
