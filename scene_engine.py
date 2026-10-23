"""Pure helpers for turning an approved script into renderable scenes."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

_METADATA_PREFIXES = (
    "TÍTULO:", "ESTILO:", "GÉNERO:", "DURACIÓN", "MODELO:", "GENERADO POR:",
    "NOTA:", "NOTA DE", "REVISIÓN HUMANA", "REVISIÓN:", "AUDIENCIA:",
)
_HEADING = re.compile(
    r"^\s*(?:\[([^\]]{1,100})\]|(#{1,3}\s+.{1,100})|(ESCENA|SECUENCIA|CAP[IÍ]TULO)\s+.{1,100})\s*$",
    re.IGNORECASE,
)
_SKIP_HEADINGS = {"REVISIÓN HUMANA PENDIENTE", "NOTA DE PRODUCCIÓN"}


def parse_script_scenes(script: str, max_scenes: int = 120) -> list[dict]:
    """Parse script headings/paragraphs into stable, displayable scene records."""
    if not script or not script.strip():
        return []

    scenes: list[dict] = []
    current_title: str | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_title, current_lines
        text = " ".join(line.strip() for line in current_lines if line.strip()).strip()
        current_lines = []
        if not text:
            return
        if len(text.split()) > 180:
            # Split long continuous paragraphs into manageable screen/storyboard units.
            sentences = re.split(r"(?<=[.!?…])\s+", text)
            chunk: list[str] = []
            words = 0
            for sentence in sentences:
                count = len(sentence.split())
                if chunk and words + count > 110:
                    add_scene(" ".join(chunk), current_title)
                    current_title = None
                    chunk, words = [], 0
                chunk.append(sentence)
                words += count
            if chunk:
                add_scene(" ".join(chunk), current_title)
                current_title = None
        else:
            add_scene(text, current_title)
            current_title = None

    def add_scene(text: str, title: str | None) -> None:
        if not text.strip() or len(scenes) >= max_scenes:
            return
        number = len(scenes) + 1
        cleaned_title = re.sub(r"\s+", " ", (title or f"Escena {number}").strip(" []#:-"))
        scenes.append({
            "index": number,
            "title": cleaned_title[:100] or f"Escena {number}",
            "text": text.strip(),
            "word_count": len(text.split()),
        })

    for raw in script.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if not line:
            flush()
            continue
        upper_line = line.upper()
        if upper_line.startswith(_METADATA_PREFIXES) or upper_line.startswith((
            "REVISA CONTINUIDAD", "REVISA LOS DATOS", "VERIFICA LOS HECHOS",
            "REVISA LOS HECHOS", "VERIFICA DATOS", "REVISIÓN HUMANA PENDIENTE",
        )):
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            title = (m.group(1) or m.group(2) or line).strip()
            title = title.strip(" []#:-")
            if title.upper().startswith(tuple(_SKIP_HEADINGS)):
                current_title = None
            else:
                current_title = title
            continue
        if line.startswith("[") and line.endswith("]") and len(line) < 120:
            # Section labels such as [GANCHO], [INTRODUCCIÓN], [CIERRE].
            flush()
            current_title = line.strip(" []")
            continue
        current_lines.append(line)
    flush()

    if not scenes:
        # A line-only/no-paragraph script still gets useful scene blocks.
        words = script.split()
        for start in range(0, len(words), 100):
            add_scene(" ".join(words[start:start + 100]), None)
            if len(scenes) >= max_scenes:
                break
    return scenes


def allocate_scene_durations(scenes: Iterable[dict], total_seconds: int) -> list[int]:
    """Allocate integer scene lengths proportional to word count, with a 5 s minimum."""
    items = list(scenes)
    if not items:
        return []
    target = max(int(total_seconds), 5 * len(items))
    weights = [max(1, int(item.get("word_count", len(str(item.get("text", "")).split())))) for item in items]
    total_weight = sum(weights)
    durations = [max(5, int(target * weight / total_weight)) for weight in weights]
    # Bring the sum back to the target without violating a 5-second per-scene minimum.
    delta = target - sum(durations)
    if delta > 0:
        durations[-1] += delta
    elif delta < 0:
        for i in sorted(range(len(durations)), key=lambda j: durations[j], reverse=True):
            take = min(durations[i] - 5, -delta)
            durations[i] -= take
            delta += take
            if delta == 0:
                break
    return durations


def ffmpeg_filter_path(path: str | Path) -> str:
    """Escape a path inside an FFmpeg filter option (e.g. drawtext=textfile=...)."""
    value = Path(path).resolve().as_posix()
    # Filtergraph option values use ':' as a separator; escape it and filter metacharacters.
    value = value.replace("\\", "\\\\")
    for char in (":", "'", ",", "[", "]"):
        value = value.replace(char, "\\" + char)
    return value


def scene_motion_filter(animation_style: str, width: int, height: int, seconds: int) -> str:
    """Return a conservative motion filter for still artwork; no animation is claimed for text cards."""
    style = (animation_style or "").lower()
    if "pixel" in style:
        low_w, low_h = max(160, width // 5), max(90, height // 5)
        return f"scale={low_w}:{low_h}:flags=neighbor,scale={width}:{height}:flags=neighbor,fps=24"
    if "stop motion" in style:
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=12, fps=24"
    zoom = "1.10" if ("3d" in style or "cinematográfica" in style or "dinámicos" in style) else "1.06"
    # Input must be looped; zoompan makes gentle Ken Burns-style motion from still art.
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},zoompan=z='min(zoom+0.0012,{zoom})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps=24"
    )
