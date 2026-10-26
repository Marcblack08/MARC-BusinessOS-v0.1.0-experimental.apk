"""Lightweight offline ambient soundtrack generator (standard library only).

Creates an instrumental loop for narration-led videos when the package does not
include a music track. It is deliberately low complexity and runs on CPU; it is
not marketed as neural/AI composition.
"""
from __future__ import annotations

import math
import wave
from array import array
from pathlib import Path

TAU = 2.0 * math.pi

# (root MIDI pitch, minor triad). Chord progression repeats every complete loop.
PROGRESSIONS = {
    "misterio": ((50, True), (46, False), (53, False), (57, True)),
    "terror": ((38, True), (41, True), (45, False), (40, True)),
    "drama": ((57, True), (53, False), (60, False), (55, False)),
    "romance": ((60, False), (57, True), (53, False), (55, False)),
    "aventura": ((55, False), (62, False), (52, True), (60, False)),
    "inspirador": ((60, False), (67, False), (57, True), (65, False)),
    "neutral": ((57, True), (53, False), (60, False), (55, False)),
}


def infer_mood(text: str) -> str:
    value = str(text or "").casefold()
    if any(term in value for term in ("terror", "horror", "asesino", "sangre", "miedo", "oscuro")):
        return "terror"
    if any(term in value for term in ("suspenso", "misterio", "secreto", "desaparec", "amenaza", "revancha")):
        return "misterio"
    if any(term in value for term in ("aventura", "batalla", "viaje", "misión", "mision", "épico", "epico")):
        return "aventura"
    if any(term in value for term in ("romance", "amor", "pareja", "corazón", "corazon")):
        return "romance"
    if any(term in value for term in ("motivación", "motivacion", "superación", "superacion", "victoria", "inspirador")):
        return "inspirador"
    return "drama"


def _frequency(midi_note: int, loop_seconds: int) -> float:
    exact = 440.0 * (2.0 ** ((midi_note - 69) / 12.0))
    # Quantize imperceptibly so all oscillators return to their phase at loop end.
    return max(1.0 / loop_seconds, round(exact * loop_seconds) / loop_seconds)


def _chord_frequencies(root: int, minor: bool, loop_seconds: int) -> tuple[float, ...]:
    third = 3 if minor else 4
    notes = (root - 12, root, root + third, root + 7, root + 12)
    return tuple(_frequency(note, loop_seconds) for note in notes)


def generate_ambient_bed(output_path: str | Path, mood: str = "drama",
                          seconds: int = 48, sample_rate: int = 22050) -> Path:
    """Write a quiet stereo WAV loop suitable for use under dialogue."""
    try:
        seconds = int(seconds)
        sample_rate = int(sample_rate)
    except (TypeError, ValueError):
        raise ValueError("La duración y la frecuencia de muestreo deben ser enteros.") from None
    if seconds < 8 or seconds > 180 or sample_rate < 8000 or sample_rate > 48000:
        raise ValueError("Duración permitida: 8–180 segundos; frecuencia: 8000–48000 Hz.")
    mood_key = str(mood or "drama").casefold()
    progression = PROGRESSIONS.get(mood_key, PROGRESSIONS["neutral"])
    chords = [_chord_frequencies(root, minor, seconds) for root, minor in progression]
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    frame_count = seconds * sample_rate
    chord_seconds = seconds / len(chords)
    crossfade_seconds = min(0.65, chord_seconds / 8.0)
    block_frames = 4096

    with wave.open(str(destination), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(sample_rate)
        start = 0
        while start < frame_count:
            count = min(block_frames, frame_count - start)
            samples = array("h")
            for offset in range(count):
                frame = start + offset
                t = frame / sample_rate
                position = t / chord_seconds
                chord_index = int(position) % len(chords)
                within = t - math.floor(position) * chord_seconds
                next_weight = 0.0
                if within >= chord_seconds - crossfade_seconds:
                    next_weight = min(1.0, (within - (chord_seconds - crossfade_seconds)) / crossfade_seconds)
                current = chords[chord_index]
                following = chords[(chord_index + 1) % len(chords)]
                swell = 0.80 + 0.12 * math.sin(TAU * t / 11.0)
                tone_current = (
                    math.sin(TAU * current[0] * t) * 0.20
                    + math.sin(TAU * current[1] * t) * 0.15
                    + math.sin(TAU * current[2] * t) * 0.12
                    + math.sin(TAU * current[3] * t) * 0.13
                    + math.sin(TAU * current[4] * t) * 0.05
                )
                if next_weight:
                    tone_next = (
                        math.sin(TAU * following[0] * t) * 0.20
                        + math.sin(TAU * following[1] * t) * 0.15
                        + math.sin(TAU * following[2] * t) * 0.12
                        + math.sin(TAU * following[3] * t) * 0.13
                        + math.sin(TAU * following[4] * t) * 0.05
                    )
                    tone = tone_current * (1.0 - next_weight) + tone_next * next_weight
                else:
                    tone = tone_current
                # Quiet master level leaves headroom for the voice track.
                sample = int(max(-1.0, min(1.0, tone * swell * 0.72)) * 32767)
                samples.append(sample)
                samples.append(sample)
            if samples.itemsize != 2:
                raise RuntimeError("La plataforma no admite muestras PCM de 16 bits.")
            if __import__("sys").byteorder != "little":
                samples.byteswap()
            output.writeframesraw(samples.tobytes())
            start += count
    return destination
