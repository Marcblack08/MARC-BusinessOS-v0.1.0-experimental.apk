"""Discover a self-contained MARC production package from a user-selected folder.

Expected layout (filenames may vary):
  guion.md
  direcciones.json          # optional
  imagenes/001.png ...      # required
  audio/narracion.wav       # optional
  audio/musica.mp3          # optional

No media is downloaded by this module. It only discovers existing, user-owned assets.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
AUDIO_EXTENSIONS = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
TEXT_EXTENSIONS = {".txt", ".md"}
IGNORED_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules", "cache", "caches",
    "output", "outputs", "export", "exports", "render", "renders", "temp", "tmp",
    "build", "dist", "logs",
}
IMAGE_DIR_NAMES = {"imagenes", "images", "image", "frames", "fotogramas", "ilustraciones", "illustrations", "art"}
SCRIPT_NAMES = {"guion", "script", "historia", "story", "screenplay"}
DIRECTION_NAMES = {
    "direcciones", "direccion", "directions", "direction", "movimientos", "movement",
    "movements", "camera", "camara", "planos", "shots",
}
NARRATION_NAMES = {"narracion", "narration", "voz", "voiceover", "voice_over", "narrator", "dialogos", "dialogue"}
MUSIC_NAMES = {"musica", "music", "soundtrack", "banda_sonora", "background_music", "musica_fondo"}


@dataclass(frozen=True)
class ProductionPackage:
    root: Path
    script_path: Path
    direction_path: Path | None
    image_paths: tuple[Path, ...]
    narration_path: Path | None = None
    music_path: Path | None = None

    @property
    def title(self) -> str:
        return self.script_path.stem.replace("_", " ").replace("-", " ").strip() or "Proyecto importado"


def _normalise(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold().strip()


def _natural_key(path: Path, root: Path) -> tuple:
    relative = path.relative_to(root).as_posix()
    pieces = re.split(r"(\d+)", relative)
    return tuple((0, int(piece)) if piece.isdigit() else (1, piece.casefold()) for piece in pieces)


def _files_in_package(root: Path) -> list[Path]:
    found: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if any(part.casefold() in IGNORED_DIRS or part.startswith(".") for part in relative_parts[:-1]):
            continue
        found.append(path)
    return sorted(found, key=lambda item: _natural_key(item, root))


def _script_file(files: list[Path], root: Path) -> Path:
    text_files = [path for path in files if path.suffix.casefold() in TEXT_EXTENSIONS]
    preferred = [
        path for path in text_files
        if _normalise(path.stem).replace(" ", "_") in SCRIPT_NAMES
    ]
    if preferred:
        preferred.sort(key=lambda path: (len(path.relative_to(root).parts), path.name.casefold()))
        return preferred[0]
    excluded = DIRECTION_NAMES | {"readme", "notas", "notes", "instrucciones", "instructions", "metadata", "manifest"}
    fallback = [
        path for path in text_files
        if _normalise(path.stem).replace(" ", "_") not in excluded
        and not any(term in _normalise(path.stem) for term in ("direc", "movim", "camera", "movements"))
    ]
    if len(fallback) == 1:
        return fallback[0]
    if not fallback:
        raise ValueError("No encuentro el guion. Añade un archivo guion.txt, guion.md, script.txt o script.md.")
    names = ", ".join(path.name for path in fallback[:8])
    raise ValueError(f"Hay varios archivos de texto y no puedo identificar el guion automáticamente: {names}. Renombra el guion a guion.md.")


def _direction_file(files: list[Path], root: Path) -> Path | None:
    candidates = [
        path for path in files
        if path.suffix.casefold() in {".json", ".txt", ".md"}
        and (
            _normalise(path.stem).replace(" ", "_") in DIRECTION_NAMES
            or any(term in _normalise(path.stem) for term in ("direccion", "direction", "movimiento", "movement", "camera", "planos", "shots"))
        )
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: (
        0 if _normalise(path.stem).replace(" ", "_") in {"direcciones", "directions", "direccion", "direction"} else 1,
        0 if path.suffix.casefold() == ".json" else 1,
        len(path.relative_to(root).parts),
        path.name.casefold(),
    ))
    return candidates[0]


def _named_audio(files: list[Path], names: set[str], root: Path) -> Path | None:
    candidates = [
        path for path in files
        if path.suffix.casefold() in AUDIO_EXTENSIONS
        and _normalise(path.stem).replace(" ", "_") in names
    ]
    if not candidates:
        # Accept conventional names with useful suffixes, e.g. musica_fondo_final.mp3.
        terms = {"music", "musica", "soundtrack", "banda_sonora", "background_music", "musica_fondo"} if names == MUSIC_NAMES else {
            "narracion", "narration", "voiceover", "voice_over", "voz", "dialogos", "dialogue"
        }
        candidates = [
            path for path in files
            if path.suffix.casefold() in AUDIO_EXTENSIONS
            and any(term in _normalise(path.stem).replace(" ", "_") for term in terms)
        ]
    if not candidates:
        return None
    candidates.sort(key=lambda path: (len(path.relative_to(root).parts), path.name.casefold()))
    return candidates[0]


def discover_production_package(folder: str | Path) -> ProductionPackage:
    """Validate and discover a package folder; raises a Spanish ValueError if incomplete."""
    root = Path(folder).expanduser().resolve()
    if not root.is_dir():
        raise ValueError("Selecciona una carpeta de paquete que exista.")
    files = _files_in_package(root)
    script_path = _script_file(files, root)
    try:
        script = script_path.read_text(encoding="utf-8-sig").strip()
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"No se pudo leer el guion {script_path.name}: {exc}") from exc
    if not script:
        raise ValueError(f"El archivo de guion {script_path.name} está vacío.")

    direction_path = _direction_file(files, root)
    image_candidates = [path for path in files if path.suffix.casefold() in IMAGE_EXTENSIONS]
    preferred_images = [
        path for path in image_candidates
        if any(_normalise(parent).replace(" ", "_") in IMAGE_DIR_NAMES for parent in path.relative_to(root).parts[:-1])
    ]
    images = preferred_images or image_candidates
    images.sort(key=lambda item: _natural_key(item, root))
    if not images:
        raise ValueError("No encuentro imágenes. Añádelas a una carpeta imagenes o images (PNG, JPG, WEBP o BMP).")

    narration_path = _named_audio(files, NARRATION_NAMES, root)
    music_path = _named_audio(files, MUSIC_NAMES, root)
    return ProductionPackage(
        root=root,
        script_path=script_path,
        direction_path=direction_path,
        image_paths=tuple(images),
        narration_path=narration_path,
        music_path=music_path,
    )


def map_production_resources(
    shots: list[dict[str, Any]],
    image_count: int,
    direction_count: int,
    source_scene_count: int,
) -> list[tuple[int | None, int | None]]:
    """Map imported images/directions to expanded storyboard shots.

    When there is one image/direction per original script scene, keep that pairing
    across all short shots split from the same scene. If the user supplies one
    asset per shot, map one-to-one. Otherwise distribute a smaller batch evenly
    across the timeline so every provided image participates in the edit.
    Returned indexes are zero-based; a missing direction is represented by None.
    """
    shot_items = list(shots)
    try:
        images_total = max(0, int(image_count))
        directions_total = max(0, int(direction_count))
        source_total = max(0, int(source_scene_count))
    except (TypeError, ValueError):
        raise ValueError("Los recuentos de escenas, imágenes y direcciones deben ser enteros.") from None
    if not shot_items:
        return []
    if images_total < 1:
        raise ValueError("Debe haber al menos una imagen para crear el montaje.")

    mappings: list[tuple[int | None, int | None]] = []
    shot_total = len(shot_items)
    for shot_index, shot in enumerate(shot_items):
        try:
            source_index = int(shot.get("source_scene_index", shot_index + 1)) - 1
        except (TypeError, ValueError):
            source_index = shot_index
        source_index = max(0, min(max(0, source_total - 1), source_index))

        if source_total > 0 and images_total == source_total:
            image_index = source_index
        elif images_total >= shot_total:
            image_index = shot_index
        else:
            image_index = min(images_total - 1, (shot_index * images_total) // shot_total)

        direction_index: int | None = None
        if directions_total:
            if directions_total == shot_total:
                direction_index = shot_index
            elif source_total > 0 and directions_total == source_total:
                direction_index = source_index
            elif directions_total == images_total:
                direction_index = min(directions_total - 1, image_index)
            else:
                direction_index = min(
                    directions_total - 1,
                    (shot_index * directions_total) // shot_total,
                )
        mappings.append((image_index, direction_index))
    return mappings


def parse_scene_directions(path: str | Path | None) -> list[str]:
    """Read camera-movement directions from JSON, numbered text, or one-line-per-shot text."""
    if not path:
        return []
    direction_path = Path(path)
    raw = direction_path.read_text(encoding="utf-8-sig").strip()
    if not raw:
        return []
    if direction_path.suffix.casefold() == ".json":
        payload: Any = json.loads(raw)
        if isinstance(payload, dict):
            payload = payload.get("scenes", payload)
        if isinstance(payload, dict):
            items = sorted(payload.items(), key=lambda item: (
                0, int(item[0])
            ) if str(item[0]).isdigit() else (1, str(item[0]).casefold()))
            values = [value for _, value in items]
        elif isinstance(payload, list):
            values = sorted(
                payload,
                key=lambda item: (int(item.get("scene", item.get("index", 0)) or 0),)
                if isinstance(item, dict) and str(item.get("scene", item.get("index", 0))).isdigit()
                else (10**9,),
            )
        else:
            raise ValueError("El JSON de direcciones debe contener una lista o un objeto de escenas.")
        directions = []
        fields = ("camera_motion", "camera_direction", "direction", "movement_instruction", "movement", "camera_movement", "camera")
        for item in values:
            value = item
            if isinstance(item, dict):
                value = next((item.get(key) for key in fields if str(item.get(key, "") or "").strip()), "")
            direction = " ".join(str(value or "").split())[:500]
            if direction:
                directions.append(direction)
        return directions

    heading = re.compile(r"^\s*(?:\[?\s*)?(?:ESCENA|SCENE)\s*(\d+)\s*\]?\s*[:.)\-–—]+\s*(.*)$", re.IGNORECASE)
    numbered: dict[int, list[str]] = {}
    sequential: list[str] = []
    current_number: int | None = None
    current: list[str] = []
    paragraphs: list[list[str]] = []
    paragraph: list[str] = []
    for raw_line in raw.splitlines():
        line = raw_line.strip()
        if not line:
            if paragraph:
                paragraphs.append(paragraph)
                paragraph = []
            continue
        paragraph.append(line)
        match = heading.match(line)
        if match:
            if current_number is not None:
                numbered[current_number] = current
            elif current:
                sequential.extend(current)
            current_number = int(match.group(1))
            current = [match.group(2).strip()] if match.group(2).strip() else []
        elif current_number is not None:
            current.append(line)
        else:
            sequential.append(line)
    if paragraph:
        paragraphs.append(paragraph)
    if current_number is not None:
        numbered[current_number] = current
    if numbered:
        return [" ".join(numbered[key]).strip()[:500] for key in sorted(numbered) if " ".join(numbered[key]).strip()]
    # Blank-line-separated blocks are treated as directions; otherwise use each non-empty line.
    if len(paragraphs) > 1:
        return [" ".join(block).strip()[:500] for block in paragraphs if " ".join(block).strip()]
    return [" ".join(line.split())[:500] for line in paragraphs[0] if line.strip()] if paragraphs else []
