"""Narrative continuity and video-profile helpers for MARC Video Studio."""
from __future__ import annotations

import re
from typing import Iterable

RESOLUTION_PROFILES = {
    "720p (HD)": 720,
    "1080p (Full HD)": 1080,
    "2K / 1440p": 1440,
}
FPS_OPTIONS = ("24", "25", "30", "60")
SHORT_VIDEO_MODE = "Corto (2 minutos)"
SERIES_VIDEO_MODE = "Novela / Serie"

_SPEAKER_PATTERN = r"\[([A-ZÁÉÍÓÚÜÑ][A-ZÁÉÍÓÚÜÑ0-9 _.'-]{0,35})\]\s*:\s*"
_SPEAKER_LINE = re.compile(r"^\s*" + _SPEAKER_PATTERN + r"(.+?)\s*$", re.MULTILINE)
_SPEAKER_INLINE = re.compile(
    _SPEAKER_PATTERN + r"(.*?)(?=\s+" + _SPEAKER_PATTERN + r"|$)",
    re.IGNORECASE,
)


def export_dimensions(platform: str, resolution: str) -> tuple[int, int]:
    """Return even output dimensions for the selected resolution and aspect ratio.

    720p/1080p/1440p refer to the landscape frame height. Portrait swaps the
    dimensions; square uses the selected size for both sides.
    """
    base_height = RESOLUTION_PROFILES.get(resolution, 1080)
    normalized = (platform or "").casefold()
    if "9:16" in normalized or "tiktok" in normalized or "reels" in normalized or "shorts" in normalized:
        return base_height, round(base_height * 16 / 9 / 2) * 2
    if "1:1" in normalized or "square" in normalized or "cuadrado" in normalized:
        return base_height, base_height
    width = round(base_height * 16 / 9 / 2) * 2
    return width, base_height


def target_word_count(duration_minutes: int, mode: str = SERIES_VIDEO_MODE,
                      words_per_minute: int = 135) -> int:
    """Estimate dialogue/narration words for a runtime without overfilling it."""
    minutes = 2 if mode == SHORT_VIDEO_MODE else max(1, int(duration_minutes))
    return max(80, round(minutes * words_per_minute))


def extract_speaker_names(script: str) -> list[str]:
    """Find explicit [SPEAKER]: dialogue/narration labels in script order."""
    result: list[str] = []
    seen: set[str] = set()
    for match in _SPEAKER_INLINE.finditer(script or ""):
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        key = name.casefold()
        if key not in seen:
            seen.add(key)
            result.append(name)
    return result


def narration_segments(script: str) -> list[tuple[str, str]]:
    """Return (speaker, line) pairs; unlabelled paragraphs become NARRADOR."""
    segments: list[tuple[str, str]] = []
    for raw_line in (script or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matches = list(_SPEAKER_INLINE.finditer(line))
        if matches:
            for match in matches:
                spoken = match.group(2).strip()
                if spoken:
                    segments.append((re.sub(r"\s+", " ", match.group(1)).strip(), spoken))
        elif not line.startswith("[") and len(line.split()) > 1:
            segments.append(("NARRADOR", line))
    return segments


def build_series_context(story_bible: str, continuity_state: str, previous_excerpt: str = "") -> str:
    """Assemble a compact, explicit canon block for the next episode prompt."""
    sections = []
    if story_bible.strip():
        sections.append("BIBLIA CANÓNICA (no contradigas estos datos):\n" + story_bible.strip())
    if continuity_state.strip():
        sections.append("ESTADO CANÓNICO AL CIERRE DEL EPISODIO ANTERIOR:\n" + continuity_state.strip())
    if previous_excerpt.strip():
        sections.append("ÚLTIMO FRAGMENTO DEL EPISODIO ANTERIOR (continúa desde aquí):\n" + previous_excerpt.strip())
    if not sections:
        return "No existe continuidad previa. Esta es la primera entrega de la historia."
    return "\n\n".join(sections)


def visual_shot_count(duration_seconds: int, max_shot_seconds: int = 5) -> int:
    """Minimum number of shots needed for a duration and maximum shot length."""
    try:
        duration, shot_length = int(duration_seconds), int(max_shot_seconds)
    except (TypeError, ValueError):
        raise ValueError("Durations must be integers.") from None
    if duration <= 0 or shot_length <= 0:
        raise ValueError("Durations must be greater than zero.")
    return (duration + shot_length - 1) // shot_length


def format_short_chapter(chapter: str) -> str:
    """Normalize short-script line breaks and add a stable chapter heading."""
    body = (chapter or "").strip()
    if not body:
        raise ValueError("The short script cannot be empty.")
    body = body.replace("\\n", "\n")
    return "\n\n[CAPÍTULO 01 DE 01]\n" + body + "\n"


def continuity_review_check(script: str, previous_state: str = "") -> list[str]:
    """Cheap deterministic flags to surface likely issues for human review.

    These are warnings, not proof of a contradiction and never block a draft.
    """
    warnings: list[str] = []
    body = (script or "").strip()
    if not body:
        return ["El guion está vacío."]
    if len(body.split()) < 100:
        warnings.append("El borrador es corto; comprueba que tenga desarrollo suficiente para la duración elegida.")
    repetitive_openings = (
        "había una vez", "en un mundo donde", "todo comenzó cuando",
        "desde tiempos inmemoriales", "en una pequeña ciudad",
    )
    if any(body.casefold().startswith(prefix) for prefix in repetitive_openings):
        warnings.append("El inicio puede resultar genérico; valora abrir con una acción, conflicto o revelación.")
    if previous_state.strip():
        old_names = set(extract_speaker_names(previous_state))
        new_names = set(extract_speaker_names(body))
        if old_names and new_names and not (old_names & new_names):
            warnings.append("No se detectan etiquetas de personajes compartidas con el episodio anterior; revisa la continuidad.")
    return warnings
