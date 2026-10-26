"""ComfyUI image-to-video adapter for MARC Video Studio AI.

Uses a user-exported ComfyUI API workflow so the engine remains compatible with
different local video models (for example Wan, LTX-Video, or other installed
image-to-video workflows) without silently assuming a model's node layout.
"""
from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Callable


class VideoGenerationError(RuntimeError):
    """A recoverable image-to-video configuration or generation error."""


def _request(url: str, data: bytes | None = None, headers: dict | None = None,
             timeout: float = 30.0) -> bytes:
    req = urllib.request.Request(url, data=data, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(1200).decode("utf-8", "replace")
        raise VideoGenerationError(f"ComfyUI respondió HTTP {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise VideoGenerationError(
            f"No se pudo conectar con ComfyUI en {url}. Comprueba que esté abierto. Detalle: {exc}"
        ) from exc


def check_comfyui(base_url: str = "http://127.0.0.1:8188", timeout: float = 3.0) -> dict:
    """Return basic ComfyUI health and queue status; never downloads models."""
    base = base_url.rstrip("/")
    raw = _request(base + "/system_stats", timeout=timeout)
    try:
        stats = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise VideoGenerationError("ComfyUI respondió, pero /system_stats no devolvió JSON válido.") from exc
    queue_raw = _request(base + "/queue", timeout=timeout)
    queue_data = json.loads(queue_raw.decode("utf-8"))
    return {"url": base, "system": stats, "queue": queue_data}


def upload_image(image_path: str | Path, base_url: str = "http://127.0.0.1:8188") -> str:
    """Upload a still image to ComfyUI and return its server-side filename."""
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise VideoGenerationError(f"No se encontró la imagen: {path}")
    if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
        raise VideoGenerationError("Formato de imagen no compatible. Usa PNG, JPG, JPEG, WebP o BMP.")
    boundary = "----MARC" + uuid.uuid4().hex
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    payload = path.read_bytes()
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{path.name}\"\r\n"
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8") + payload + f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{boundary}--\r\n".encode("utf-8")
    raw = _request(base_url.rstrip("/") + "/upload/image", body,
                   {"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=60)
    try:
        result = json.loads(raw.decode("utf-8"))
        name = result.get("name")
    except (ValueError, UnicodeDecodeError) as exc:
        raise VideoGenerationError("ComfyUI no confirmó la carga de la imagen.") from exc
    if not name:
        raise VideoGenerationError(f"Respuesta de carga inesperada: {raw[:500]!r}")
    return str(name)


def prepare_workflow(workflow: dict, image_filename: str, motion_prompt: str,
                     negative_prompt: str = "") -> dict:
    """Fill obvious image/prompt inputs in a ComfyUI API workflow.

    It intentionally refuses to guess ambiguous workflows. Users can mark node
    inputs with MARC_IMAGE_INPUT / MARC_PROMPT_INPUT / MARC_NEGATIVE_INPUT
    keys in a copied workflow, or use the guided heuristic for common node names.
    """
    if not isinstance(workflow, dict) or not workflow:
        raise VideoGenerationError("El workflow de ComfyUI está vacío o no es válido.")
    prepared = json.loads(json.dumps(workflow))
    image_nodes = []
    prompt_nodes = []
    negative_nodes = []
    for node_id, node in prepared.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        class_type = str(node.get("class_type", "")).lower()
        for key in list(inputs):
            marker = key.upper()
            if marker == "MARC_IMAGE_INPUT" or (
                key in {"image", "image_name"} and any(x in class_type for x in ("loadimage", "imageonly", "wan", "video")))
            :
                image_nodes.append((node_id, key))
            if marker == "MARC_PROMPT_INPUT" or (
                key in {"text", "prompt", "positive"} and any(x in class_type for x in ("text", "clip", "prompt", "conditioning", "wan", "ltx", "video")))
            :
                prompt_nodes.append((node_id, key))
            if marker == "MARC_NEGATIVE_INPUT" or key in {"negative_prompt", "negative"}:
                negative_nodes.append((node_id, key))
    # Explicit markers take priority, then common ComfyUI node patterns.
    explicit_image = [(n, k) for n, node in prepared.items() if isinstance(node, dict)
                      for k in (node.get("inputs") or {}) if k.upper() == "MARC_IMAGE_INPUT"]
    explicit_prompt = [(n, k) for n, node in prepared.items() if isinstance(node, dict)
                       for k in (node.get("inputs") or {}) if k.upper() == "MARC_PROMPT_INPUT"]
    explicit_negative = [(n, k) for n, node in prepared.items() if isinstance(node, dict)
                         for k in (node.get("inputs") or {}) if k.upper() == "MARC_NEGATIVE_INPUT"]
    image_nodes = explicit_image or image_nodes
    prompt_nodes = explicit_prompt or prompt_nodes
    negative_nodes = explicit_negative or negative_nodes
    if len(image_nodes) != 1:
        raise VideoGenerationError(
            "No pude identificar una única entrada de imagen en el workflow. "
            "Edita una copia del JSON API y marca la entrada con la clave MARC_IMAGE_INPUT."
        )
    if not prompt_nodes:
        raise VideoGenerationError(
            "No pude identificar el campo de prompt. Marca el campo de texto positivo como MARC_PROMPT_INPUT."
        )
    for node_id, key in image_nodes:
        prepared[node_id]["inputs"][key] = image_filename
    for node_id, key in prompt_nodes:
        prepared[node_id]["inputs"][key] = motion_prompt
    for node_id, key in negative_nodes:
        prepared[node_id]["inputs"][key] = negative_prompt
    # MARC marker names are metadata only and are not valid inputs to ComfyUI.
    for node in prepared.values():
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
            for key in list(node["inputs"]):
                if key.upper().startswith("MARC_"):
                    node["inputs"].pop(key, None)
    return prepared


def generate_video(image_path: str | Path, motion_prompt: str, workflow_path: str | Path,
                   output_dir: str | Path, base_url: str = "http://127.0.0.1:8188",
                   negative_prompt: str = "", timeout_seconds: int = 1800,
                   poll_interval: float = 2.0,
                   progress: Callable[[str], None] | None = None,
                   cancel_check: Callable[[], bool] | None = None) -> Path:
    """Run an exported ComfyUI API workflow and copy its first video output locally."""
    prompt = str(motion_prompt or "").strip()
    if not prompt:
        raise VideoGenerationError("Describe el movimiento que debe realizar el personaje.")
    workflow_file = Path(workflow_path).expanduser().resolve()
    if not workflow_file.is_file():
        raise VideoGenerationError("Selecciona un workflow API JSON de imagen a vídeo.")
    try:
        workflow = json.loads(workflow_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VideoGenerationError(f"No se pudo leer el workflow JSON: {exc}") from exc
    if "nodes" in workflow and "links" in workflow:
        raise VideoGenerationError(
            "Este parece un workflow visual de ComfyUI. Exporta el workflow en formato API JSON "
            "(menú Save/Export API format) y vuelve a seleccionarlo."
        )
    if progress:
        progress("Comprobando ComfyUI…")
    check_comfyui(base_url)
    if progress:
        progress("Subiendo imagen de referencia…")
    uploaded_name = upload_image(image_path, base_url)
    api_workflow = prepare_workflow(workflow, uploaded_name, prompt, negative_prompt)
    client_id = str(uuid.uuid4())
    payload = json.dumps({"prompt": api_workflow, "client_id": client_id}).encode("utf-8")
    response = json.loads(_request(base_url.rstrip("/") + "/prompt", payload,
                                   {"Content-Type": "application/json"}, timeout=30).decode("utf-8"))
    prompt_id = response.get("prompt_id")
    if not prompt_id:
        raise VideoGenerationError(f"ComfyUI no devolvió prompt_id: {response}")
    if progress:
        progress("Generando vídeo con el modelo local…")
    deadline = time.monotonic() + max(30, int(timeout_seconds))
    while time.monotonic() < deadline:
        if cancel_check and cancel_check():
            raise VideoGenerationError("Generación cancelada. La tarea puede seguir en la cola de ComfyUI.")
        time.sleep(max(0.5, float(poll_interval)))
        history_raw = _request(base_url.rstrip("/") + "/history/" + urllib.parse.quote(str(prompt_id)), timeout=20)
        history = json.loads(history_raw.decode("utf-8"))
        item = history.get(prompt_id) or {}
        if item.get("status", {}).get("status_str") == "error":
            raise VideoGenerationError("ComfyUI reportó un error durante la generación. Revisa su consola.")
        outputs = item.get("outputs") or {}
        video_ref = None
        for node_output in outputs.values():
            if not isinstance(node_output, dict):
                continue
            for key in ("videos", "gifs", "images"):
                entries = node_output.get(key) or []
                for entry in entries:
                    if not isinstance(entry, dict) or not entry.get("filename"):
                        continue
                    filename = str(entry["filename"])
                    if key in {"videos", "gifs"} or Path(filename).suffix.lower() in {".mp4", ".webm", ".mov", ".gif"}:
                        video_ref = entry
                        break
                if video_ref:
                    break
            if video_ref:
                break
        if video_ref:
            if progress:
                progress("Descargando vídeo generado…")
            params = urllib.parse.urlencode({
                "filename": video_ref["filename"],
                "subfolder": video_ref.get("subfolder", ""),
                "type": video_ref.get("type", "output"),
            })
            data = _request(base_url.rstrip("/") + "/view?" + params, timeout=120)
            extension = Path(str(video_ref["filename"])).suffix.lower() or ".mp4"
            if extension not in {".mp4", ".webm", ".mov", ".gif"}:
                extension = ".mp4"
            destination_dir = Path(output_dir).expanduser().resolve()
            destination_dir.mkdir(parents=True, exist_ok=True)
            destination = destination_dir / f"marc_i2v_{time.strftime('%Y%m%d_%H%M%S')}{extension}"
            destination.write_bytes(data)
            if not data:
                raise VideoGenerationError("ComfyUI devolvió un archivo de vídeo vacío.")
            if progress:
                progress(f"Vídeo listo: {destination}")
            return destination
    raise VideoGenerationError(
        f"La generación superó {timeout_seconds} segundos. Comprueba la consola y la cola de ComfyUI."
    )
