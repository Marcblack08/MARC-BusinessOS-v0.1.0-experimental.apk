from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from xml.sax.saxutils import escape, quoteattr

VOICE_ID_RE = re.compile(r"^[A-Za-z]{2,4}_[A-Za-z0-9_]+$")
SPEAKER_RE = re.compile(r"\[([^\]]{1,48})\]\s*:\s*(.*?)(?=\s+\[[^\]]{1,48}\]\s*:\s*|$)")
EMOTION_RE = re.compile(r"^\s*\[EMOC[IÍ]ON\s*=\s*([^\]]{1,32})\]\s*", re.IGNORECASE)

_NARRATOR_LABELS = {"NARRADOR", "NARRADORA", "NARRATOR", "VOICEOVER", "VOZ EN OFF"}
_EMOTION_PROSODY = {
    "miedo": ("0.90", "+2st", "0.90"),
    "temor": ("0.90", "+2st", "0.90"),
    "panico": ("1.18", "+3st", "1.08"),
    "pánico": ("1.18", "+3st", "1.08"),
    "susurro": ("0.78", "-1st", "0.62"),
    "secreto": ("0.82", "-1st", "0.68"),
    "ira": ("1.16", "+3st", "1.08"),
    "enojo": ("1.16", "+3st", "1.08"),
    "rabia": ("1.20", "+3st", "1.10"),
    "tristeza": ("0.82", "-3st", "0.80"),
    "dolor": ("0.82", "-3st", "0.82"),
    "duelo": ("0.78", "-3st", "0.78"),
    "alegria": ("1.08", "+2st", "1.00"),
    "alegría": ("1.08", "+2st", "1.00"),
    "entusiasmo": ("1.12", "+3st", "1.05"),
    "sorpresa": ("1.12", "+4st", "1.05"),
    "shock": ("1.12", "+4st", "1.05"),
    "urgencia": ("1.22", "+2st", "1.10"),
    "suspenso": ("0.82", "-1st", "0.75"),
    "tension": ("0.82", "-1st", "0.75"),
    "tensión": ("0.82", "-1st", "0.75"),
    "calma": ("0.92", "-1st", "0.92"),
    "sereno": ("0.92", "-1st", "0.92"),
}


def parse_kokoro_voice_ids(payload: object) -> list[str]:
    """Extract stable Kokoro voice IDs from the JSON shapes used by local voice APIs."""
    found: list[str] = []
    seen: set[str] = set()

    def add(value: object) -> None:
        candidate = str(value or "").strip()
        if VOICE_ID_RE.fullmatch(candidate) and candidate not in seen:
            seen.add(candidate)
            found.append(candidate)

    def visit(node: object) -> None:
        if isinstance(node, str):
            add(node)
            return
        if isinstance(node, Mapping):
            # Some versions expose an array; others expose an object keyed by voice ID.
            for key in ("voice_id", "voiceId", "id", "slug", "voice", "name"):
                value = node.get(key)
                if isinstance(value, str):
                    add(value)
            for key, value in node.items():
                add(key)
                if isinstance(value, (Mapping, list, tuple)):
                    visit(value)
                elif isinstance(value, str) and key.casefold() in {
                    "voices", "items", "data", "results", "speakers"
                }:
                    add(value)
            return
        if isinstance(node, Sequence) and not isinstance(node, (bytes, bytearray)):
            for item in node:
                visit(item)

    visit(payload)
    return found


def _parse_script_segments(script: str) -> list[tuple[str, str, str]]:
    """Return (speaker, spoken_text, emotion) tuples; skip scene/chapter headings."""
    segments: list[tuple[str, str, str]] = []
    for raw_line in str(script or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        matches = list(SPEAKER_RE.finditer(line))
        if matches:
            for match in matches:
                speaker = match.group(1).strip().upper()
                spoken = match.group(2).strip()
                emotion = ""
                emotion_match = EMOTION_RE.match(spoken)
                if emotion_match:
                    emotion = emotion_match.group(1).strip().casefold()
                    spoken = spoken[emotion_match.end():].strip()
                if spoken and not speaker.startswith(("ESCENA", "CAPITULO", "CAPÍTULO", "BIBLIA")):
                    segments.append((speaker, spoken, emotion))
            continue
        # Lines wrapped in brackets without a colon are headings or metadata.
        if line.startswith("[") and line.endswith("]"):
            continue
        emotion = ""
        emotion_match = EMOTION_RE.match(line)
        if emotion_match:
            emotion = emotion_match.group(1).strip().casefold()
            line = line[emotion_match.end():].strip()
        if line:
            segments.append(("NARRADOR", line, emotion))
    return segments


def build_kokoro_ssml(
    script: str,
    voice_ids: Sequence[str],
    default_voice: str,
    speaker_assignments: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, str]]:
    """Create safe SSML with emotion-aware prosody and automatic multi-voice dialogue."""
    valid_voices = []
    seen = set()
    for value in voice_ids:
        name = str(value or "").strip()
        if VOICE_ID_RE.fullmatch(name) and name not in seen:
            valid_voices.append(name)
            seen.add(name)
    default_voice = str(default_voice or "").strip()
    if default_voice not in valid_voices:
        raise ValueError("Selecciona una voz Kokoro que aparezca en la lista detectada.")
    segments = _parse_script_segments(script)
    if not segments:
        raise ValueError("No hay texto de guion que se pueda convertir en narración.")

    narrator_present = any(speaker in _NARRATOR_LABELS for speaker, _, _ in segments)
    speaker_order: list[str] = []
    for speaker, _, _ in segments:
        if speaker not in speaker_order:
            speaker_order.append(speaker)

    supplied = {
        str(key).strip().upper(): str(value).strip()
        for key, value in (speaker_assignments or {}).items()
        if str(value).strip() in seen
    }
    auto_assignments: dict[str, str] = {}
    alternate_voices = [voice for voice in valid_voices if voice != default_voice]
    dialogue_index = 0
    first_dialogue_assigned = False
    for speaker in speaker_order:
        if speaker in _NARRATOR_LABELS:
            auto_assignments[speaker] = default_voice
        elif speaker in supplied:
            auto_assignments[speaker] = supplied[speaker]
        elif not narrator_present and not first_dialogue_assigned:
            auto_assignments[speaker] = default_voice
            first_dialogue_assigned = True
        elif alternate_voices:
            auto_assignments[speaker] = alternate_voices[dialogue_index % len(alternate_voices)]
            dialogue_index += 1
        else:
            auto_assignments[speaker] = default_voice

    chunks = ["<speak>"]
    previous_speaker = None
    for speaker, spoken, emotion in segments:
        voice = auto_assignments.get(speaker, default_voice)
        safe_voice = quoteattr(voice)
        profile = _EMOTION_PROSODY.get(emotion)
        text_xml = escape(spoken)
        if profile:
            speed, pitch, volume = profile
            body = (
                f'<prosody speed="{speed}" pitch="{pitch}" volume="{volume}">'
                f"{text_xml}</prosody>"
            )
        else:
            body = text_xml
        chunks.append(f"<voice name={safe_voice}>{body}</voice>")
        pause = "180ms" if speaker != previous_speaker else "90ms"
        chunks.append(f'<break time="{pause}"/>')
        previous_speaker = speaker
    chunks.append("</speak>")
    return "".join(chunks), auto_assignments
