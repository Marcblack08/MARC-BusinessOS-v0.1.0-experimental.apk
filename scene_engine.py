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
    # Performance cues are for narration synthesis, not visible caption/image text.
    raw_text = re.sub(r"\[EMOC[IÍ]ON\s*=\s*[^\]]{1,32}\]\s*", "", raw_text, flags=re.IGNORECASE)
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



def expand_scenes_to_shots(
    scenes: Iterable[dict],
    target_shots: int,
    max_scenes: int = 1440,
    min_words_to_split: int = 12,
) -> list[dict]:
    """Split overlong parsed scenes into smaller visual shots without inventing story text.

    This only changes the visual storyboard records; narration is still synthesized
    from the original script. A shot is split near its midpoint, preferring a
    sentence/clause boundary, and speaker labels are carried into the second half
    when the cut would otherwise detach dialogue from its speaker.
    """
    try:
        target = max(0, int(target_shots))
        limit = max(1, int(max_scenes))
        minimum = max(4, int(min_words_to_split))
    except (TypeError, ValueError):
        raise ValueError("Shot counts and split limits must be integers.") from None

    result = []
    for source_index, original in enumerate(scenes, start=1):
        if len(result) >= limit:
            break
        item = dict(original)
        item.setdefault("source_scene_index", source_index)
        item["text"] = str(item.get("text", "") or "").strip()
        item["word_count"] = len(item["text"].split())
        result.append(item)

    def split_text(text: str) -> tuple[str, str] | None:
        words = text.split()
        if len(words) < minimum:
            return None
        midpoint = len(words) // 2
        # Prefer a natural sentence or clause boundary near the middle.
        candidates = []
        for index in range(2, len(words) - 1):
            if re.search(r"[.!?…;,]$", words[index - 1]):
                candidates.append(index)
        if candidates:
            cut = min(candidates, key=lambda index: (abs(index - midpoint), index))
        else:
            cut = midpoint
        cut = max(2, min(len(words) - 2, cut))
        left = " ".join(words[:cut]).strip()
        right = " ".join(words[cut:]).strip()
        # Keep the most recent explicit speaker label with a continuation chunk.
        labels = list(re.finditer(r"\[([^\]]{1,40})\]\s*:\s*", left))
        if labels and not re.match(r"^\[[^\]]{1,40}\]\s*:", right):
            label = labels[-1].group(1).strip()
            right = f"[{label}]: {right}"
        if not left or not right:
            return None
        return left, right

    while len(result) < min(target, limit):
        candidates = [
            (len(str(item.get("text", "")).split()), index)
            for index, item in enumerate(result)
            if len(str(item.get("text", "")).split()) >= minimum
        ]
        if not candidates:
            break
        _, index = max(candidates, key=lambda pair: (pair[0], -pair[1]))
        original = result[index]
        halves = split_text(str(original.get("text", "")))
        if not halves:
            break
        left_text, right_text = halves
        base_title = str(original.get("title", f"Escena {index + 1}")).strip()
        base_title = re.sub(r"\s+—\s+plano\s+[AB]$", "", base_title, flags=re.IGNORECASE).strip()
        left = dict(original)
        right = dict(original)
        left["text"] = left_text
        left["word_count"] = len(left_text.split())
        left["title"] = f"{base_title} — plano A"
        right["text"] = right_text
        right["word_count"] = len(right_text.split())
        right["title"] = f"{base_title} — plano B"
        result[index:index + 1] = [left, right]

    for index, item in enumerate(result, start=1):
        item["index"] = index
        item["word_count"] = len(str(item.get("text", "")).split())
    return result

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


def build_srt_subtitles(
    scenes: Iterable[dict],
    durations: Iterable[int | float],
    chars_per_line: int = 42,
    total_duration_seconds: float | None = None,
) -> str:
    """Build readable scene-timed SRT cues scaled to the final media timeline.

    Per-cue timing within a scene is estimated; this is not word-level forced alignment.
    """
    items = list(scenes)
    times = list(durations)
    if len(items) != len(times):
        raise ValueError("Scene and duration counts must match.")
    if chars_per_line < 10:
        raise ValueError("chars_per_line must be at least 10.")
    try:
        numeric_times = [float(value) for value in times]
    except (TypeError, ValueError):
        raise ValueError("Durations must be numeric.") from None
    if any(not math.isfinite(value) or value <= 0 for value in numeric_times):
        raise ValueError("Durations must be finite numbers greater than zero.")
    if total_duration_seconds is not None:
        try:
            target_duration = float(total_duration_seconds)
        except (TypeError, ValueError):
            raise ValueError("total_duration_seconds must be numeric.") from None
        if not math.isfinite(target_duration) or target_duration <= 0:
            raise ValueError("total_duration_seconds must be a finite number greater than zero.")
        planned_duration = sum(numeric_times)
        if planned_duration <= 0:
            raise ValueError("The planned timeline must have positive duration.")
        scale = target_duration / planned_duration
        numeric_times = [value * scale for value in numeric_times]

    def stamp(milliseconds: int) -> str:
        milliseconds = max(0, int(milliseconds))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    def clean_caption(value: str) -> str:
        value = re.sub(r"(?i)\[(?:NARRADOR|NARRADORA|PERSONAJE|VOZ EN OFF)\]\s*:\s*", "", value)
        value = re.sub(r"\[([^\]]{1,40})\]\s*:\s*", "", value)
        return " ".join(value.split()).strip()

    def caption_chunks(value: str) -> list[str]:
        words = value.split()
        chunks: list[str] = []
        current: list[str] = []
        for word in words:
            if current and len(" ".join(current + [word])) > chars_per_line:
                punctuation_cut = next(
                    (i + 1 for i in range(len(current) - 1, max(-1, len(current) - 5), -1)
                     if re.search(r"[.!?…,:;]$", current[i])),
                    None,
                )
                if punctuation_cut:
                    chunks.append(" ".join(current[:punctuation_cut]))
                    current = current[punctuation_cut:]
                else:
                    chunks.append(" ".join(current))
                    current = []
            current.append(word)
        if current:
            chunks.append(" ".join(current))
        return chunks

    parts: list[str] = []
    elapsed_ms = 0
    cue_number = 0
    planned_ms = [max(1, round(value * 1000)) for value in numeric_times]
    for scene_index, scene in enumerate(items):
        duration_ms = planned_ms[scene_index]
        body = clean_caption(str(scene.get("text", "")))
        if not body:
            elapsed_ms += duration_ms
            continue
        chunks = caption_chunks(body) or [body]
        weights = [max(1, len(chunk.split())) for chunk in chunks]
        total_weight = sum(weights)
        consumed = 0
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            cue_start = elapsed_ms + consumed
            if index == len(chunks) - 1:
                cue_end = elapsed_ms + duration_ms
            else:
                allocated = round(duration_ms * weight / total_weight)
                allocated = min(max(1, allocated), max(1, duration_ms - consumed - (len(chunks) - index - 1)))
                cue_end = cue_start + allocated
            cue_number += 1
            parts.append(f"{cue_number}\n{stamp(cue_start)} --> {stamp(cue_end)}\n{chunk}")
            consumed = cue_end - elapsed_ms
        elapsed_ms += duration_ms
    return "\n\n".join(parts) + ("\n" if parts else "")



def build_srt_from_timed_segments(
    segments: Iterable[dict],
    total_duration_seconds: float | None = None,
    max_chars: int = 42,
) -> str:
    """Build SRT from measured speech-segment start/end timestamps.

    Each segment must contain text, start_seconds, and end_seconds. These are
    measured boundaries supplied by the speech engine or a forced aligner; unlike
    the scene-duration fallback, this function does not distribute time by word count.
    """
    items = list(segments)
    if max_chars < 10:
        raise ValueError("max_chars must be at least 10.")
    try:
        target = None if total_duration_seconds is None else float(total_duration_seconds)
    except (TypeError, ValueError):
        raise ValueError("total_duration_seconds must be numeric.") from None
    if target is not None and (not math.isfinite(target) or target <= 0):
        raise ValueError("total_duration_seconds must be finite and greater than zero.")

    def stamp(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        whole_seconds, millis = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{millis:03d}"

    def split_caption(text: str) -> list[str]:
        words = " ".join(text.split()).split()
        chunks: list[str] = []
        current: list[str] = []
        for word in words:
            if current and len(" ".join(current + [word])) > max_chars:
                chunks.append(" ".join(current))
                current = []
            current.append(word)
        if current:
            chunks.append(" ".join(current))
        return chunks

    output: list[str] = []
    last_end = 0.0
    cue = 0
    for item in items:
        try:
            start = float(item["start_seconds"])
            end = float(item["end_seconds"])
            text = str(item.get("text", "")).strip()
        except (KeyError, TypeError, ValueError):
            raise ValueError("Each timed segment requires numeric start_seconds and end_seconds.") from None
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            raise ValueError("Timed segments must have finite, non-negative, increasing boundaries.")
        if start < last_end - 0.05:
            raise ValueError("Timed segments must be ordered and must not overlap.")
        if target is not None and start >= target:
            continue
        if target is not None:
            end = min(end, target)
        if end <= start:
            continue
        text = re.sub(r"(?i)^\[(?:NARRADOR|NARRADORA|PERSONAJE|VOZ EN OFF)\]\s*:\s*", "", text)
        text = re.sub(r"^\[[^\]]{1,40}\]\s*:\s*", "", text)
        chunks = split_caption(text)
        if not chunks:
            last_end = end
            continue
        weights = [max(1, len(chunk.split())) for chunk in chunks]
        weight_total = sum(weights)
        cursor = start
        used_weight = 0
        for index, (chunk, weight) in enumerate(zip(chunks, weights)):
            next_weight = used_weight + weight
            cue_start = cursor
            cue_end = end if index == len(chunks) - 1 else start + (end - start) * next_weight / weight_total
            cue += 1
            output.append(f"{cue}\n{stamp(cue_start)} --> {stamp(cue_end)}\n{chunk}")
            cursor = cue_end
            used_weight = next_weight
        last_end = end
    return "\n\n".join(output) + ("\n" if output else "")

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
    animation_style: str,
    width: int,
    height: int,
    seconds: int,
    intensity: str = "Normal",
    shot_index: int = 0,
    direction: str = "",
) -> str:
    """Build a per-shot camera move; optional Spanish/English direction cues override the default."""
    style = (animation_style or "").lower()
    level = (intensity or "Normal").strip().lower()
    direction_text = " ".join(str(direction or "").casefold().split())
    if "pixel" in style:
        low_w, low_h = max(160, width // 5), max(90, height // 5)
        return f"scale={low_w}:{low_h}:flags=neighbor,scale={width}:{height}:flags=neighbor,fps=24"
    if "stop motion" in style:
        return f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height},fps=12,fps=24"
    if level == "suave":
        zoom, step = "1.035", "0.00045"
    elif level == "muy animado":
        zoom, step = "1.19", "0.0030"
    else:
        zoom, step = "1.085", "0.0015"
    if "3d" in style or "cinematográfica" in style or "dinámicos" in style:
        if level == "normal":
            zoom, step = "1.11", "0.0019"
        elif level == "suave":
            zoom, step = "1.045", "0.00065"

    # Different camera directions across adjacent shots prevent every still from
    # using the same centered push-in. This is camera movement, not body animation.
    move = max(0, int(shot_index)) % 5
    # Human direction notes control the camera move in the still-image pipeline.
    # This is deterministic pan/zoom, not generated body animation.
    if any(token in direction_text for token in ("zoom out", "alejar", "alejamiento", "retrocede", "retroceder", "se aleja")):
        move = 1
    elif any(token in direction_text for token in ("pan izquierda", "hacia la izquierda", "de derecha a izquierda", "desplaza a la izquierda", "paneo izquierdo")):
        move = 3
    elif any(token in direction_text for token in ("pan derecha", "hacia la derecha", "de izquierda a derecha", "desplaza a la derecha", "paneo derecho")):
        move = 2
    elif any(token in direction_text for token in ("tilt arriba", "hacia arriba", "de abajo hacia arriba", "inclina hacia arriba", "paneo vertical arriba")):
        move = 4
    elif any(token in direction_text for token in ("zoom in", "acercar", "acercamiento", "se acerca", "entra en primer plano", "push in")):
        move = 0
    frames = max(24, max(1, int(seconds)) * 24)
    centered_x = "iw/2-(iw/zoom/2)"
    centered_y = "ih/2-(ih/zoom/2)"
    if move == 0:
        zoom_expr = f"min(zoom+{step},{zoom})"
        x_expr, y_expr = centered_x, centered_y
    elif move == 1:
        # zoompan starts at zoom=1, so explicitly initialize the first frame at
        # the target magnification, then reduce by a fixed amount each frame.
        zoom_expr = f"if(eq(on,0),{zoom},max(1.0,zoom-{step}))"
        x_expr, y_expr = centered_x, centered_y
    elif move == 2:
        zoom_expr = f"min(zoom+{step},{zoom})"
        x_expr = f"(iw-iw/zoom)*min(on/{frames},1)"
        y_expr = centered_y
    elif move == 3:
        zoom_expr = f"min(zoom+{step},{zoom})"
        x_expr = f"(iw-iw/zoom)*(1-min(on/{frames},1))"
        y_expr = centered_y
    else:
        zoom_expr = f"min(zoom+{step},{zoom})"
        x_expr = centered_x
        y_expr = f"(ih-ih/zoom)*min(on/{frames},1)"
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},zoompan=z='{zoom_expr}':"
        f"x='{x_expr}':y='{y_expr}':d=1:s={width}x{height}:fps=24"
    )


_CAMERA_DIRECTIONS = (
    "wide establishing composition with the location clearly readable",
    "medium action shot with readable full-body gesture and foreground depth",
    "tight emotional close-up focused on the eyes and facial expression",
    "over-the-shoulder composition that places the subject and their target in the same frame",
    "cinematic detail insert focused on the important hand, object or clue",
    "low-angle dramatic composition that makes the threat feel imposing",
    "profile or three-quarter portrait with expressive silhouette and background separation",
    "high-angle composition that makes the subject feel exposed or vulnerable",
    "two-shot with clear spatial relationship and tension between characters",
    "slightly canted suspense composition with controlled, readable lines",
)


def camera_direction_for_shot(scene_number: int) -> str:
    """Return a deterministic camera-composition cue so successive AI images vary."""
    try:
        index = max(1, int(scene_number)) - 1
    except (TypeError, ValueError):
        index = 0
    return _CAMERA_DIRECTIONS[index % len(_CAMERA_DIRECTIONS)]


def build_cinematic_image_prompt(
    style_prompt: str,
    visual_description: str,
    scene_number: int,
    title: str = "",
    canon_reference: str = "",
    continuity_reference: str = "",
) -> str:
    """Turn an AI scene description into a specific, emotionally legible single-frame prompt."""
    camera = camera_direction_for_shot(scene_number)
    title = " ".join(str(title or "").split())[:120]
    description = " ".join(str(visual_description or "").split())[:1600]
    canon = " ".join(str(canon_reference or "").split())[:650]
    continuity = " ".join(str(continuity_reference or "").split())[:350]
    number = max(1, int(scene_number))
    return (
        f"{style_prompt}. Create one high-quality cinematic animation frame for scene {number}. "
        f"Scene beat: {description}. "
        f"Camera and composition: {camera}. Adapt the shot to the actual action; if no person is present, frame the relevant object or location. "
        "Make the story readable at a glance: one dominant subject/action, clear foreground and background separation, "
        "expressive face and body language when characters are visible, specific emotion rather than a generic smile, "
        "purposeful dramatic lighting, believable anatomy, rich but controlled color, clean edges, detailed environment, "
        "natural depth of field and a clear focal point. "
        f"Scene title for context only: {title}. "
        f"Character/prop continuity rules: {canon or 'Keep each described subject visually stable within this project.'} "
        f"Previous continuity context: {continuity or 'No previous episode state.'} "
        "Show exactly one coherent moment, not a collage, contact sheet, comic panels or montage. "
        "Do not draw text, captions, subtitles, speech bubbles, UI, logos or watermarks. "
        "Do not add unmentioned characters, swap clothing, duplicate faces, flatten the lighting, or reuse the same composition mechanically."
    )



def build_comfy_image_workflow(
    checkpoint: str,
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    scene_number: int,
    upscale_model: str = "",
    seed: int = 0,
    steps: int = 22,
    cfg: float = 6.5,
) -> dict:
    """Build a ComfyUI API workflow, optionally applying a local AI upscaler.

    The optional upscaler is deliberately opt-in: older GPUs and CPU-only
    systems can keep the original low-memory generation path.
    """
    checkpoint = str(checkpoint or "").strip()
    if not checkpoint:
        raise ValueError("A checkpoint is required.")
    try:
        width = int(width)
        height = int(height)
        scene_number = int(scene_number)
        seed = int(seed)
        steps = int(steps)
        cfg = float(cfg)
    except (TypeError, ValueError):
        raise ValueError("Image dimensions, scene number, seed and sampler settings must be numeric.") from None
    if width < 64 or height < 64 or width > 2048 or height > 2048:
        raise ValueError("Image dimensions must be between 64 and 2048 pixels.")
    if width % 8 or height % 8:
        raise ValueError("Image dimensions must be multiples of 8.")
    if scene_number < 1:
        raise ValueError("Scene number must be positive.")
    if not 1 <= steps <= 80:
        raise ValueError("Sampling steps must be between 1 and 80.")
    if not math.isfinite(cfg) or not 0.0 <= cfg <= 30.0:
        raise ValueError("CFG must be finite and between 0 and 30.")

    workflow = {
        "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
        "2": {"class_type": "CLIPTextEncode", "inputs": {"text": str(prompt or ""), "clip": ["1", 1]}},
        "3": {"class_type": "CLIPTextEncode", "inputs": {"text": str(negative_prompt or ""), "clip": ["1", 1]}},
        "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "5": {"class_type": "KSampler", "inputs": {
            "seed": seed, "steps": steps, "cfg": cfg,
            "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
            "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]
        }},
        "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
    }
    image_output = ["6", 0]
    upscale_model = str(upscale_model or "").strip()
    if upscale_model and upscale_model.casefold() not in {"(sin mejora)", "none", "ninguno"}:
        workflow["8"] = {"class_type": "UpscaleModelLoader", "inputs": {"model_name": upscale_model}}
        workflow["9"] = {"class_type": "ImageUpscaleWithModel", "inputs": {
            "upscale_model": ["8", 0], "image": ["6", 0]
        }}
        image_output = ["9", 0]
    workflow["7"] = {"class_type": "SaveImage", "inputs": {
        "filename_prefix": f"MARC_Studio/scene_{scene_number:03d}",
        "images": image_output,
    }}
    return workflow


_TRANSITION_FILTER_NAMES = {
    "fundido suave": "fade",
    "deslizar izquierda": "slideleft",
    "deslizar derecha": "slideright",
    "barrido izquierda": "wipeleft",
    "barrido derecha": "wiperight",
    "zoom cinematográfico": "zoomin",
}


def build_video_transition_filter_graph(
    durations: Iterable[float],
    transition_seconds: float = 0.4,
    transition_style: str = "Fundido suave",
    *,
    fade_edges: bool = True,
    preserve_tail: bool = False,
) -> str:
    """Build a real FFmpeg xfade graph.

    Inputs last nominal duration + transition_seconds. For long timelines, chunks
    can preserve the short trailing handle and skip edge fades; a final small graph
    crossfades those chunks and applies the project-wide fades exactly once.
    """
    try:
        values = [float(value) for value in durations]
        transition = float(transition_seconds)
    except (TypeError, ValueError):
        raise ValueError("Durations and transition length must be numeric.") from None
    if not values or any(not math.isfinite(value) or value <= 0 for value in values):
        raise ValueError("At least one finite, positive clip duration is required.")
    if not math.isfinite(transition) or transition <= 0 or transition > 1.0:
        raise ValueError("Transition duration must be greater than zero and at most one second.")
    transition = min(transition, min(values) * 0.4)
    transition_name = _TRANSITION_FILTER_NAMES.get(
        " ".join(str(transition_style or "Fundido suave").casefold().split()),
        "fade",
    )
    total = sum(values)
    parts = [
        f"[{index}:v]settb=AVTB,setpts=PTS-STARTPTS,format=yuv420p[v{index}]"
        for index in range(len(values))
    ]
    current = "[v0]"
    elapsed = 0.0
    for index in range(1, len(values)):
        elapsed += values[index - 1]
        next_label = f"xf{index}"
        parts.append(
            f"{current}[v{index}]xfade=transition={transition_name}:duration={transition:.3f}:"
            f"offset={elapsed:.3f}[{next_label}]"
        )
        current = f"[{next_label}]"
    output_duration = total + transition if preserve_tail else total
    video_chain = f"{current}trim=duration={output_duration:.3f},setpts=PTS-STARTPTS"
    if fade_edges:
        fade = min(0.28, total / 10.0)
        fade_out_start = max(0.0, total - fade)
        video_chain += f",fade=t=in:st=0:d={fade:.3f},fade=t=out:st={fade_out_start:.3f}:d={fade:.3f}"
    parts.append(f"{video_chain}[vout]")
    return ";".join(parts)
