"""Pure helpers for turning an approved script into renderable scenes."""
from __future__ import annotations

import math
import re
import textwrap
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



_SCENE_SPEAKER_INLINE = re.compile(
    r"\[([^\]]{1,40})\]\s*:\s*(.*?)(?=\s+\[[^\]]{1,40}\]\s*:|$)",
    re.IGNORECASE | re.DOTALL,
)
_NARRATOR_LABELS = {"narrador", "narrator", "voz en off", "voiceover"}


def build_scene_visual_brief(
    scene: dict,
    story_bible: str = "",
    continuity_state: str = "",
    max_excerpt_chars: int = 650,
    max_canon_chars: int = 1200,
    max_continuity_chars: int = 450,
) -> dict:
    """Build a scene-specific visual brief that applies only relevant story canon.

    Speaker labels are treated as dialogue context, not as a guarantee that the
    speaker must be visible. If character names are available, prefer canon
    paragraphs mentioning those names instead of sending the full story bible
    prefix to every image-generation request.
    """
    scene = scene if isinstance(scene, dict) else {}
    title = " ".join(str(scene.get("title", "")).split())[:100]
    raw_text = str(scene.get("text", "") or "").strip()
    normalized_text = " ".join(raw_text.split())
    excerpt_limit = max(0, int(max_excerpt_chars))
    canon_limit = max(0, int(max_canon_chars))
    continuity_limit = max(0, int(max_continuity_chars))
    excerpt = normalized_text[:excerpt_limit]

    speakers: list[str] = []
    dialogue: list[str] = []
    narrator_parts: list[str] = []
    for match in _SCENE_SPEAKER_INLINE.finditer(raw_text):
        name = " ".join(match.group(1).split()).strip()
        spoken = " ".join(match.group(2).split()).strip()
        if not name or not spoken:
            continue
        if name.casefold() in _NARRATOR_LABELS:
            narrator_parts.append(spoken)
            continue
        if name.casefold() not in {item.casefold() for item in speakers}:
            speakers.append(name)
        dialogue.append(f"{name}: {spoken}")

    unlabelled_text = " ".join(_SCENE_SPEAKER_INLINE.sub(" ", raw_text).split()).strip()
    narration_parts = ([unlabelled_text] if unlabelled_text else []) + narrator_parts
    narration = " ".join(narration_parts)
    if not _SCENE_SPEAKER_INLINE.search(raw_text):
        narration = normalized_text
    narration = narration[:excerpt_limit]

    bible = str(story_bible or "").strip()
    relevant_paragraphs: list[str] = []
    if speakers and bible:
        for paragraph in re.split(r"\n\s*\n", bible):
            cleaned = " ".join(paragraph.split()).strip()
            if not cleaned:
                continue
            if any(
                re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", cleaned, re.IGNORECASE)
                for name in speakers
            ):
                relevant_paragraphs.append(cleaned)
                if len(relevant_paragraphs) >= 5:
                    break
    if relevant_paragraphs:
        canon_reference = "\n".join(relevant_paragraphs)
    else:
        canon_reference = " ".join(bible.split())
    canon_reference = canon_reference[:canon_limit]

    continuity_reference = " ".join(str(continuity_state or "").split())[:continuity_limit]
    return {
        "title": title,
        "excerpt": excerpt,
        "speakers": speakers,
        "narration": narration,
        "dialogue": dialogue[:8],
        "canon_reference": canon_reference,
        "continuity_reference": continuity_reference,
    }


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


def allocate_scene_durations(
    scenes: Iterable[dict], total_seconds: int, max_scene_seconds: int = 5
) -> list[int]:
    """Allocate durations while ensuring no still-image shot exceeds the configured cap.

    If there are too few scenes for the requested runtime, the resulting montage is
    shorter rather than holding a still for longer than the cap. The scene panel
    reports how many additional shots are needed to reach the requested runtime.
    """
    items = list(scenes)
    if not items:
        return []
    try:
        cap = int(max_scene_seconds)
        requested = int(total_seconds)
    except (TypeError, ValueError):
        raise ValueError("Durations must be integers.") from None
    if cap < 1 or requested < 1:
        raise ValueError("Durations must be greater than zero.")
    weights = [
        max(1, int(item.get("word_count", len(str(item.get("text", "")).split()))))
        for item in items
    ]
    # Every scene needs at least one second, but no still-image clip may exceed cap.
    target = min(max(requested, len(items)), cap * len(items))
    durations = [1] * len(items)
    remaining = target - len(items)
    # Add seconds to the scenes with the highest weighted need, respecting the cap.
    while remaining > 0:
        eligible = [i for i, value in enumerate(durations) if value < cap]
        if not eligible:
            break
        chosen = max(eligible, key=lambda i: (weights[i] / (durations[i] + 1), -i))
        durations[chosen] += 1
        remaining -= 1
    return durations


def build_audio_filter_graph(
    has_voice: bool,
    has_music: bool,
    voice_input_index: int | None = None,
    music_input_index: int | None = None,
    voice_gain: float = 1.0,
    music_gain: float = 0.18,
    duration_seconds: float | None = None,
    music_fade_seconds: float = 1.5,
    duck_music: bool = True,
) -> str:
    """Build an FFmpeg graph with music fades and automatic speech ducking.

    When output duration is known, music is trimmed to the video and receives
    short fades at both ends. If narration is present, sidechain compression
    lowers music while speech is active.
    """
    if not has_voice and not has_music:
        return ""
    if has_voice and voice_input_index is None:
        raise ValueError("voice_input_index is required when narration is enabled.")
    if has_music and music_input_index is None:
        raise ValueError("music_input_index is required when music is enabled.")

    try:
        voice_gain = float(voice_gain)
        music_gain = float(music_gain)
        music_fade_seconds = float(music_fade_seconds)
        duration = None if duration_seconds is None else float(duration_seconds)
    except (TypeError, ValueError):
        raise ValueError("Audio gains, duration and fade length must be numeric.") from None

    if not math.isfinite(voice_gain) or not math.isfinite(music_gain):
        raise ValueError("Audio gain must be finite.")
    if not 0.0 <= voice_gain <= 4.0 or not 0.0 <= music_gain <= 4.0:
        raise ValueError("Audio gain must be between 0 and 4.")
    if not math.isfinite(music_fade_seconds) or not 0.0 <= music_fade_seconds <= 30.0:
        raise ValueError("Music fade length must be between 0 and 30 seconds.")
    if duration is not None and (not math.isfinite(duration) or duration <= 0.0):
        raise ValueError("duration_seconds must be a finite number greater than zero.")

    fade = music_fade_seconds
    if duration is not None and fade > 0.0:
        # Prevent fade-in and fade-out from overlapping on short videos.
        fade = min(fade, duration / 2.0)

    parts: list[str] = []
    if has_voice:
        voice_label = "voice" if has_music else "aout"
        parts.append(
            f"[{voice_input_index}:a:0]volume={voice_gain:.3f},apad[{voice_label}]"
        )

    if has_music:
        music_source = f"[{music_input_index}:a:0]"
        music_chain: list[str] = []
        if duration is not None:
            music_chain.extend([
                f"atrim=duration={duration:.3f}",
                "asetpts=PTS-STARTPTS",
            ])
        music_chain.append(f"volume={music_gain:.3f}")
        if fade > 0.0:
            music_chain.append(f"afade=t=in:st=0:d={fade:.3f}")
            if duration is not None:
                fade_out_start = max(0.0, duration - fade)
                music_chain.append(
                    f"afade=t=out:st={fade_out_start:.3f}:d={fade:.3f}"
                )
        music_label = "music" if has_voice else "aout"
        music_chain.append("apad")
        parts.append(music_source + ",".join(music_chain) + f"[{music_label}]")

    if has_voice and has_music:
        mixed_music = "music"
        if duck_music:
            parts.append(
                "[music][voice]sidechaincompress="
                "threshold=0.035:ratio=5:attack=20:release=450[ducked]"
            )
            mixed_music = "ducked"
        parts.append(
            f"[voice][{mixed_music}]amix=inputs=2:duration=longest:dropout_transition=2[aout]"
        )

    return ";".join(parts)


def build_srt_subtitles(scenes: Iterable[dict], durations: Iterable[int], chars_per_line: int = 42) -> str:
    """Build SRT captions from scene text and approximate scene-level durations."""
    items = list(scenes)
    times = list(durations)
    if len(items) != len(times):
        raise ValueError("Scene and duration counts must match.")
    if chars_per_line < 10:
        raise ValueError("chars_per_line must be at least 10.")

    def stamp(milliseconds: int) -> str:
        milliseconds = max(0, int(milliseconds))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    parts: list[str] = []
    elapsed_ms = 0
    cue_number = 0
    for scene, duration in zip(items, times):
        body = " ".join(str(scene.get("text", "")).split()).strip()
        if not body:
            elapsed_ms += max(1, int(duration)) * 1000
            continue
        duration_ms = max(1, int(duration)) * 1000
        wrapped = textwrap.wrap(body, width=chars_per_line, break_long_words=False) or [body]
        cue_number += 1
        parts.append(
            f"{cue_number}\n{stamp(elapsed_ms)} --> {stamp(elapsed_ms + duration_ms)}\n"
            + "\n".join(wrapped)
        )
        elapsed_ms += duration_ms
    return "\n\n".join(parts) + ("\n" if parts else "")


def ffmpeg_filter_path(path: str | Path) -> str:
    """Escape a path inside an FFmpeg filter option (e.g. drawtext=textfile=...)."""
    value = Path(path).resolve().as_posix()
    # Filtergraph option values use ':' as a separator; escape it and filter metacharacters.
    value = value.replace("\\", "\\\\")
    for char in (":", "'", ",", "[", "]"):
        value = value.replace(char, "\\" + char)
    return value


def build_subtitle_drawtext_filter(textfile: str | Path, fontfile: str | Path | None, font_size: int,
                                   color: str = "white", position: str = "Inferior", outline: bool = True) -> str:
    """Build an escaped FFmpeg drawtext filter for subtitle styling."""
    palette = {"Blanco": "white", "Amarillo": "yellow", "Cian": "cyan",
               "white": "white", "yellow": "yellow", "cyan": "cyan"}
    size = max(12, min(96, int(font_size)))
    options = [f"textfile='{ffmpeg_filter_path(textfile)}'", "expansion=none",
               f"fontcolor={palette.get(str(color), 'white')}", f"fontsize={size}", "x=(w-text_w)/2"]
    if fontfile and Path(fontfile).is_file():
        options.append(f"fontfile='{ffmpeg_filter_path(fontfile)}'")
    options.append("y=(h-text_h)/2" if str(position).casefold() == "centro" else "y=h-text_h-h*0.06")
    if outline:
        options.extend(["borderw=3", "bordercolor=black", "shadowx=2", "shadowy=2"])
    else:
        options.extend(["shadowx=1", "shadowy=1"])
    options.extend(["box=1", "boxcolor=0x06101d@0.68", "boxborderw=14"])
    return "drawtext=" + ":".join(options)


def scene_motion_filter(
    animation_style: str, width: int, height: int, seconds: int, intensity: str = "Normal"
) -> str:
    """Return an FFmpeg motion filter for still artwork, scaled by the user's motion intensity."""
    style = (animation_style or "").lower()
    level = (intensity or "Normal").strip().lower()
    if "pixel" in style:
        low_w, low_h = max(160, width // 5), max(90, height // 5)
        return f"scale={low_w}:{low_h}:flags=neighbor,scale={width}:{height}:flags=neighbor,fps=24"
    if "stop motion" in style:
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=12, fps=24"
    if level == "suave":
        zoom, step = "1.025", "0.00035"
    elif level == "muy animado":
        zoom, step = "1.16", "0.0028"
    else:
        zoom, step = "1.07", "0.0012"
    if "3d" in style or "cinematográfica" in style or "dinámicos" in style:
        if level == "normal":
            zoom, step = "1.10", "0.0018"
        elif level == "suave":
            zoom, step = "1.04", "0.0006"
    # The still image is looped by the caller; zoompan creates camera movement, not character animation.
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},zoompan=z='min(zoom+{step},{zoom})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={width}x{height}:fps=24"
    )
