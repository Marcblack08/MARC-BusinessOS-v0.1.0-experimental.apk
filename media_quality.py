"""Small, dependency-free media-output checks for MARC exports."""
from __future__ import annotations

import math
import re
from fractions import Fraction
from typing import Any


def _number(value: Any) -> float | None:
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def _rate(value: Any) -> float | None:
    if value in (None, "", "0/0", "N/A"):
        return None
    try:
        result = float(Fraction(str(value)))
        return result if math.isfinite(result) and result > 0 else None
    except (ValueError, ZeroDivisionError, TypeError, OverflowError):
        return None


def validate_media_info(
    info: dict[str, Any],
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
    minimum_duration: float | None = None,
    require_audio: bool = False,
) -> dict[str, Any]:
    """Return a structured pass/warning report from ffprobe-like metadata."""
    streams = info.get("streams", []) if isinstance(info, dict) else []
    streams = streams if isinstance(streams, list) else []
    video = next((s for s in streams if isinstance(s, dict) and s.get("codec_type") == "video"), None)
    audio_streams = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "audio"]
    subtitle_streams = [s for s in streams if isinstance(s, dict) and s.get("codec_type") == "subtitle"]
    fmt = info.get("format", {}) if isinstance(info, dict) else {}
    fmt = fmt if isinstance(fmt, dict) else {}
    duration = _number(fmt.get("duration"))
    if duration is None and video:
        duration = _number(video.get("duration"))

    checks: list[dict[str, Any]] = []
    errors: list[str] = []
    warnings: list[str] = []

    def add(name: str, passed: bool, detail: str, severity: str = "error") -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            (errors if severity == "error" else warnings).append(detail)

    add("video_stream", video is not None, "No se encontró una pista de vídeo." if video is None else "Pista de vídeo detectada.")
    width = int(video.get("width") or 0) if video else 0
    height = int(video.get("height") or 0) if video else 0
    if video:
        add("dimensions", width > 0 and height > 0, f"Resolución detectada: {width}x{height}." if width > 0 and height > 0 else "La resolución del vídeo no es válida.")
        if expected_width and expected_height:
            add(
                "expected_dimensions", width == int(expected_width) and height == int(expected_height),
                f"Resolución {width}x{height}; se esperaba {int(expected_width)}x{int(expected_height)}."
            )
        fps = _rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))
        if expected_fps:
            valid_fps = fps is not None and abs(fps - float(expected_fps)) <= max(0.75, float(expected_fps) * 0.03)
            add(
                "fps", valid_fps,
                f"FPS detectados: {fps:.3f}; objetivo: {float(expected_fps):g}." if fps is not None else "No se pudo determinar el FPS del vídeo."
            )
    if duration is None or duration <= 0:
        add("duration", False, "No se pudo verificar una duración positiva.")
    else:
        add("duration", True, f"Duración detectada: {duration:.2f} s.")
        if minimum_duration is not None:
            min_seconds = max(0.0, float(minimum_duration))
            # A small tolerance accommodates MP4 time-base and encoder rounding.
            add(
                "minimum_duration", duration + 0.75 >= min_seconds,
                f"Duración {duration:.2f} s; mínimo esperado {min_seconds:.2f} s."
            )
    add("audio", bool(audio_streams) or not require_audio,
        "Pista de audio detectada." if audio_streams else (
            "Se esperaba audio, pero el MP4 no contiene una pista de audio." if require_audio
            else "Sin pista de audio externa; permitido para este proyecto."
        ))
    return {
        "passed": not errors,
        "checks": checks,
        "errors": errors,
        "warnings": warnings,
        "duration": duration,
        "width": width or None,
        "height": height or None,
        "fps": (_rate(video.get("avg_frame_rate")) or _rate(video.get("r_frame_rate"))) if video else None,
        "audio_streams": len(audio_streams),
        "subtitle_streams": len(subtitle_streams),
    }


def parse_ffmpeg_probe_text(text: str) -> dict[str, Any]:
    """Extract conservative stream facts from FFmpeg stderr when ffprobe is unavailable."""
    source = str(text or "")
    duration_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", source)
    duration = None
    if duration_match:
        hours, minutes, seconds = duration_match.groups()
        duration = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    video_match = re.search(
        r"Stream #\d+:\d+.*?Video:.*?(?:,\s*(\d{2,5})x(\d{2,5})(?:\[[^]]+\])?)",
        source, re.IGNORECASE
    )
    fps_match = re.search(r"(?:,\s*|\s)(\d+(?:\.\d+)?)\s*fps", source, re.IGNORECASE)
    has_audio = bool(re.search(r"Stream #\d+:\d+.*?Audio:", source, re.IGNORECASE))
    streams = []
    if video_match:
        stream = {"codec_type": "video", "width": int(video_match.group(1)), "height": int(video_match.group(2))}
        if fps_match:
            stream["avg_frame_rate"] = fps_match.group(1)
        streams.append(stream)
    if has_audio:
        streams.append({"codec_type": "audio"})
    return {"format": {"duration": duration} if duration is not None else {}, "streams": streams}


def inspect_media_file(
    path: str,
    ffmpeg_path: str | None = None,
    ffprobe_path: str | None = None,
    expected_width: int | None = None,
    expected_height: int | None = None,
    expected_fps: float | None = None,
    minimum_duration: float | None = None,
    require_audio: bool = False,
    subtitle_path: str | None = None,
) -> dict[str, Any]:
    """Probe a rendered file, preferring ffprobe and falling back to FFmpeg's input report."""
    import json
    import os
    import shutil
    import subprocess
    from pathlib import Path

    media_path = Path(path)
    if not media_path.is_file() or media_path.stat().st_size <= 1024:
        return {
            "passed": False, "checks": [],
            "errors": ["El archivo de salida no existe o está vacío."],
            "warnings": [], "duration": None, "width": None, "height": None,
            "fps": None, "audio_streams": 0, "subtitle_streams": 0,
        }
    probe = ffprobe_path or shutil.which("ffprobe")
    if not probe and ffmpeg_path:
        sibling_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
        sibling = Path(ffmpeg_path).resolve().with_name(sibling_name)
        if sibling.is_file():
            probe = str(sibling)
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
    info = None
    if probe:
        try:
            completed = subprocess.run(
                [probe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(media_path.resolve())],
                capture_output=True, text=True, timeout=45, creationflags=creationflags,
            )
            if completed.returncode == 0:
                parsed = json.loads(completed.stdout or "{}")
                if isinstance(parsed, dict):
                    info = parsed
        except (OSError, ValueError, subprocess.TimeoutExpired):
            info = None
    if info is None and ffmpeg_path:
        try:
            completed = subprocess.run(
                [ffmpeg_path, "-hide_banner", "-i", str(media_path.resolve())],
                capture_output=True, text=True, timeout=45, creationflags=creationflags,
            )
            info = parse_ffmpeg_probe_text((completed.stderr or "") + "\\n" + (completed.stdout or ""))
        except (OSError, subprocess.TimeoutExpired):
            info = None
    if info is None:
        return {
            "passed": False, "checks": [],
            "errors": ["No se pudo inspeccionar el MP4: no hay ffprobe disponible o la lectura falló."],
            "warnings": [], "duration": None, "width": None, "height": None,
            "fps": None, "audio_streams": 0, "subtitle_streams": 0,
        }
    report = validate_media_info(
        info, expected_width=expected_width, expected_height=expected_height,
        expected_fps=expected_fps, minimum_duration=minimum_duration,
        require_audio=require_audio,
    )
    if subtitle_path:
        try:
            subtitle_file = Path(subtitle_path)
            subtitle_result = validate_srt_text(subtitle_file.read_text(encoding="utf-8-sig")) if subtitle_file.is_file() else {
                "passed": False, "cue_count": 0, "errors": ["No se encontró el archivo de subtítulos SRT."]
            }
        except (OSError, UnicodeError) as exc:
            subtitle_result = {"passed": False, "cue_count": 0, "errors": [f"No se pudo leer el archivo SRT: {exc}"]}
        report["subtitle_check"] = subtitle_result
        report["checks"].append({
            "name": "subtitles", "passed": subtitle_result["passed"],
            "detail": f"SRT válido: {subtitle_result['cue_count']} subtítulo(s)." if subtitle_result["passed"] else "El SRT no superó la validación."
        })
        report["subtitle_streams"] = subtitle_result["cue_count"]
        if not subtitle_result["passed"]:
            report["errors"].extend(subtitle_result["errors"])
            report["passed"] = False
    return report


_SRT_BLOCK = re.compile(
    r"(?m)^([0-9]+)\s*\n"
    r"(\d{2,}:\d{2}:\d{2},\d{3})\s+-->\s+"
    r"(\d{2,}:\d{2}:\d{2},\d{3})\s*\n"
    r"(.+?)(?=\n{2,}|\Z)",
    re.DOTALL,
)


def validate_srt_text(text: str) -> dict[str, Any]:
    """Check SRT cue numbering, timestamps, non-empty text and cue ordering."""
    source = str(text or "").strip()
    if not source:
        return {"passed": False, "cue_count": 0, "errors": ["El archivo SRT está vacío."]}
    blocks = re.split(r"\n\s*\n", source)
    errors: list[str] = []
    valid_count = 0
    previous_end = -1

    def milliseconds(stamp: str) -> int:
        hours, minutes, seconds = stamp.split(":")
        seconds, millis = seconds.split(",")
        return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(millis)

    for index, block in enumerate(blocks, start=1):
        lines = block.splitlines()
        if len(lines) < 3 or not lines[0].strip().isdigit():
            errors.append(f"Bloque {index}: falta número, intervalo o texto.")
            continue
        if int(lines[0].strip()) != index:
            errors.append(f"Bloque {index}: numeración de subtítulos no consecutiva.")
        timing = re.fullmatch(
            r"(\d{2,}:\d{2}:\d{2},\d{3})\s+-->\s+(\d{2,}:\d{2}:\d{2},\d{3})",
            lines[1].strip(),
        )
        if not timing:
            errors.append(f"Bloque {index}: formato de tiempo SRT inválido.")
            continue
        start_ms, end_ms = milliseconds(timing.group(1)), milliseconds(timing.group(2))
        if end_ms <= start_ms:
            errors.append(f"Bloque {index}: la hora final debe ser posterior a la inicial.")
        if start_ms < previous_end:
            errors.append(f"Bloque {index}: los subtítulos se solapan o están desordenados.")
        if not " ".join(lines[2:]).strip():
            errors.append(f"Bloque {index}: el texto está vacío.")
        previous_end = end_ms
        valid_count += 1
    if valid_count == 0:
        errors.append("No se encontraron subtítulos válidos.")
    return {"passed": not errors, "cue_count": valid_count, "errors": errors}
