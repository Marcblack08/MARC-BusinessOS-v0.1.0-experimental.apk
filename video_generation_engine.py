"""ComfyUI image-to-video adapter for MARC Video Studio AI.

Uses a user-exported ComfyUI API workflow so the engine remains compatible with
different local video models (for example Wan, LTX-Video, or other installed
image-to-video workflows) without silently assuming a model's node layout.
"""
from __future__ import annotations

import base64
import json
import mimetypes
import os
import secrets
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


def _linked_source(value, workflow: dict) -> str | None:
    """Return a ComfyUI API node ID for a standard [node_id, output_slot] link."""
    if isinstance(value, list) and len(value) == 2:
        source = str(value[0])
        if source in workflow and isinstance(value[1], int):
            return source
    return None


def _linked_source(value, workflow: dict) -> str | None:
    """Return a ComfyUI API node ID for a standard [node_id, output_slot] link."""
    if isinstance(value, list) and len(value) == 2:
        source = str(value[0])
        if source in workflow and isinstance(value[1], int):
            return source
    return None


def _find_text_encoder(source_id: str, workflow: dict, polarity: str) -> list[tuple[str, str]]:
    """Walk upstream along only the requested positive/negative conditioning branch."""
    found: list[tuple[str, str]] = []
    pending = [str(source_id)]
    seen: set[str] = set()
    wanted_input = "positive" if polarity == "positive" else "negative"
    while pending:
        node_id = pending.pop(0)
        if node_id in seen or node_id not in workflow:
            continue
        seen.add(node_id)
        node = workflow[node_id]
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        class_type = str(node.get("class_type", "")).lower()
        if "text" in inputs and any(token in class_type for token in ("clip", "text", "prompt", "encode")):
            found.append((node_id, "text"))
            continue
        # LTXV/Wan conditioning nodes expose both branches on the same node.
        # Following every input would incorrectly collect both encoders as positive.
        if wanted_input in inputs:
            source = _linked_source(inputs.get(wanted_input), workflow)
            if source:
                pending.append(source)
            continue
        for value in inputs.values():
            source = _linked_source(value, workflow)
            if source:
                pending.append(source)
    return found


def visual_workflow_to_api(workflow: dict) -> dict:
    """Convert the official LTX image-to-video visual template to ComfyUI API format.

    The converter deliberately supports the node types used by the official
    Comfy-Org LTX-Video 0.9.5 image-to-video template. It omits canvas notes,
    groups and editor-only widget values, and fails if the workflow is incompatible.
    """
    if not isinstance(workflow, dict) or not isinstance(workflow.get("nodes"), list):
        raise VideoGenerationError("El workflow visual de ComfyUI no contiene una lista de nodos válida.")
    nodes = {str(node.get("id")): node for node in workflow["nodes"] if isinstance(node, dict)}
    links = {}
    for link in workflow.get("links", []):
        if isinstance(link, list) and len(link) >= 6:
            links[str(link[0])] = (str(link[1]), int(link[2]))
    api: dict[str, dict] = {}

    def link_value(node: dict, input_name: str):
        for item in node.get("inputs", []) or []:
            if item.get("name") == input_name and item.get("link") is not None:
                ref = links.get(str(item["link"]))
                if ref:
                    return [ref[0], ref[1]]
        return None

    for node_id, node in nodes.items():
        class_type = str(node.get("type", ""))
        values = list(node.get("widgets_values") or [])
        inputs: dict = {}
        if class_type == "CheckpointLoaderSimple":
            if values:
                inputs["ckpt_name"] = values[0]
        elif class_type == "CLIPLoader":
            if len(values) >= 3:
                inputs.update({"clip_name": values[0], "type": values[1], "device": values[2]})
        elif class_type == "CLIPTextEncode":
            clip = link_value(node, "clip")
            if values and clip:
                inputs.update({"text": values[0], "clip": clip})
        elif class_type == "LoadImage":
            if values:
                inputs["image"] = values[0]
        elif class_type == "LTXVImgToVideo":
            names = ("width", "height", "length", "batch_size", "strength")
            for index, name in enumerate(names):
                if index < len(values):
                    inputs[name] = values[index]
            for name in ("positive", "negative", "vae", "image"):
                value = link_value(node, name)
                if value:
                    inputs[name] = value
        elif class_type == "LTXVConditioning":
            for name in ("positive", "negative"):
                value = link_value(node, name)
                if value:
                    inputs[name] = value
            if values:
                inputs["frame_rate"] = values[0]
        elif class_type == "LTXVScheduler":
            names = ("steps", "max_shift", "base_shift", "stretch", "terminal")
            for index, name in enumerate(names):
                if index < len(values):
                    inputs[name] = values[index]
            latent = link_value(node, "latent")
            if latent:
                inputs["latent"] = latent
        elif class_type == "KSamplerSelect":
            if values:
                inputs["sampler_name"] = values[0]
        elif class_type == "SamplerCustom":
            # The visual editor includes an extra control-after-generate choice;
            # this is UI state, not an API input, so it must not shift cfg.
            if len(values) >= 4:
                seed_mode = str(values[2]).casefold() if len(values) > 2 else ""
                seed = secrets.randbits(53) if seed_mode in {"randomize", "randomise"} else int(values[1])
                inputs.update({
                    "add_noise": values[0], "noise_seed": seed,
                    "cfg": float(values[3]),
                })
            for name in ("model", "positive", "negative", "sampler", "sigmas", "latent_image"):
                value = link_value(node, name)
                if value:
                    inputs[name] = value
        elif class_type == "VAEDecode":
            for name in ("samples", "vae"):
                value = link_value(node, name)
                if value:
                    inputs[name] = value
        elif class_type == "CreateVideo":
            images = link_value(node, "images")
            if images:
                inputs["images"] = images
            if values:
                inputs["fps"] = values[0]
            audio = link_value(node, "audio")
            if audio:
                inputs["audio"] = audio
        elif class_type == "SaveVideo":
            video = link_value(node, "video")
            if video:
                inputs["video"] = video
            if len(values) >= 3:
                inputs.update({
                    "filename_prefix": values[0], "format": {"format": values[1], "codec": values[2]}
                })
        else:
            # Ignore canvas notes, reroutes and any unsupported nodes.
            continue
        api[node_id] = {"class_type": class_type, "inputs": inputs}

    required = {
        "CheckpointLoaderSimple", "CLIPLoader", "CLIPTextEncode", "LoadImage",
        "LTXVImgToVideo", "LTXVConditioning", "LTXVScheduler", "KSamplerSelect",
        "SamplerCustom", "VAEDecode", "CreateVideo", "SaveVideo",
    }
    present = {str(item.get("class_type")) for item in api.values()}
    missing = sorted(required - present)
    if missing:
        raise VideoGenerationError(
            "La plantilla LTX no contiene los nodos requeridos: " + ", ".join(missing)
        )
    return api


def prepare_workflow(workflow: dict, image_filename: str, motion_prompt: str,
                     negative_prompt: str = "", frame_count: int = 49,
                     output_width: int = 768, output_height: int = 512) -> dict:
    """Fill image and positive/negative prompts of an API or official visual workflow."""
    if not isinstance(workflow, dict) or not workflow:
        raise VideoGenerationError("El workflow de ComfyUI está vacío o no es válido.")
    if "nodes" in workflow and "links" in workflow:
        prepared = visual_workflow_to_api(workflow)
    else:
        prepared = json.loads(json.dumps(workflow))
    image_nodes: list[tuple[str, str]] = []
    text_nodes: list[tuple[str, str]] = []
    for node_id, node in prepared.items():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        inputs = node["inputs"]
        class_type = str(node.get("class_type", "")).lower()
        if "image" in inputs and any(token in class_type for token in ("loadimage", "imageonly")):
            image_nodes.append((node_id, "image"))
        if "text" in inputs and any(token in class_type for token in ("clip", "text", "prompt", "encode")):
            text_nodes.append((node_id, "text"))

    positive_nodes: list[tuple[str, str]] = []
    negative_nodes: list[tuple[str, str]] = []
    for node in prepared.values():
        if not isinstance(node, dict) or not isinstance(node.get("inputs"), dict):
            continue
        for key, value in node["inputs"].items():
            if key.lower() not in {"positive", "negative"}:
                continue
            source_id = _linked_source(value, prepared)
            if source_id:
                matches = _find_text_encoder(
                    source_id, prepared, "positive" if key.lower() == "positive" else "negative"
                )
                if key.lower() == "positive":
                    positive_nodes.extend(matches)
                else:
                    negative_nodes.extend(matches)
    positive_nodes = list(dict.fromkeys(positive_nodes))
    negative_nodes = list(dict.fromkeys(negative_nodes))
    if not positive_nodes:
        negative_clues = (
            "low quality", "worst quality", "bad anatomy", "deformed", "blurry",
            "extra fingers", "negative prompt", "watermark, text", "jpeg artifacts",
        )
        negative_by_text = [
            item for item in text_nodes
            if any(clue in str(prepared[item[0]]["inputs"].get(item[1], "")).lower()
                   for clue in negative_clues)
        ]
        candidates = [item for item in text_nodes if item not in negative_by_text]
        if len(candidates) == 1:
            positive_nodes = candidates
        else:
            raise VideoGenerationError(
                "No se pudo distinguir el prompt positivo. Usa el workflow API LTX que se incluye en Preparar IA."
            )
        if not negative_nodes:
            negative_nodes = negative_by_text

    image_nodes = list(dict.fromkeys(image_nodes))
    if len(image_nodes) != 1:
        raise VideoGenerationError(
            "El workflow debe tener una única entrada LoadImage para animar la imagen de referencia."
        )
    if len(positive_nodes) != 1:
        raise VideoGenerationError(
            "El workflow tiene varias entradas de texto positivo. Usa la plantilla oficial LTX de MARC."
        )
    prepared[image_nodes[0][0]]["inputs"][image_nodes[0][1]] = image_filename
    prepared[positive_nodes[0][0]]["inputs"][positive_nodes[0][1]] = motion_prompt
    if negative_prompt.strip():
        if len(negative_nodes) > 1:
            raise VideoGenerationError(
                "El workflow tiene varias entradas negativas. Deja el prompt negativo vacío o usa la plantilla oficial LTX de MARC."
            )
        if len(negative_nodes) == 1:
            prepared[negative_nodes[0][0]]["inputs"][negative_nodes[0][1]] = negative_prompt.strip()
    # Keep dimensions aligned to 32 pixels and the clip short enough for local inference.
    width = max(256, min(1024, int(output_width)))
    height = max(256, min(1024, int(output_height)))
    width = max(256, round(width / 32) * 32)
    height = max(256, round(height / 32) * 32)
    # LTX expects 8n+1 frames.
    length = max(9, int(frame_count))
    length = ((length - 1) // 8) * 8 + 1
    for node in prepared.values():
        if isinstance(node, dict) and isinstance(node.get("inputs"), dict):
            if str(node.get("class_type", "")) == "LTXVImgToVideo":
                node["inputs"]["length"] = length
                node["inputs"]["width"] = width
                node["inputs"]["height"] = height
            if str(node.get("class_type", "")) == "LTXVScheduler":
                node["inputs"]["steps"] = min(30, max(1, int(node["inputs"].get("steps", 20))))
    return prepared


def analyze_image_with_ollama(image_path: str | Path,
                              base_url: str = "http://127.0.0.1:11434",
                              model_override: str | None = None,
                              timeout: float = 180.0,
                              scene_context: str = "",
                              camera_direction: str = "") -> str:
    """Use an installed local vision model to describe a still and suggest motion."""
    path = Path(image_path).expanduser().resolve()
    if not path.is_file():
        raise VideoGenerationError(f"No se encontró la imagen para analizar: {path}")
    try:
        raw = _request(base_url.rstrip("/") + "/api/tags", timeout=10)
        tags = json.loads(raw.decode("utf-8")).get("models", [])
    except (ValueError, UnicodeDecodeError) as exc:
        raise VideoGenerationError("Ollama no devolvió una lista válida de modelos.") from exc
    available = [str(item.get("name", "")) for item in tags if isinstance(item, dict)]
    override = (model_override or os.environ.get("MARC_VISION_MODEL", "")).strip()
    if override:
        model = next((name for name in available if name == override or name.startswith(override)), None)
        if model is None:
            raise VideoGenerationError(
                f"El modelo visual '{override}' no está instalado en Ollama. Modelos disponibles: "
                + (", ".join(available[:12]) or "ninguno")
            )
    else:
        preferred = ("moondream", "qwen2.5vl:3b", "qwen2.5vl", "gemma3:4b",
                     "gemma3", "llava", "minicpm-v", "llama3.2-vision")
        model = None
        for candidate in preferred:
            model = next((name for name in available
                          if name == candidate or name.startswith(candidate)), None)
            if model:
                break
        if model is None:
            raise VideoGenerationError(
                "No se encontró un modelo visual en Ollama. Instala un modelo de visión compatible "
                "(por ejemplo moondream o qwen2.5vl:3b) o escribe manualmente la acción en vez de usar AUTO. "
                "Ollama no puede analizar imágenes con un modelo solo de texto."
            )
    image_data = base64.b64encode(path.read_bytes()).decode("ascii")
    body = json.dumps({
        "model": model,
        "stream": False,
        "messages": [{
            "role": "user",
            "content": (
                "Analyze this image for an image-to-video clip. Describe only what is visible, "
                "and return a concise ENGLISH motion prompt for the video model. "
                "Preserve identity, clothing, setting, and visual style. Propose natural body movement "
                "that fits the visible pose; do not invent additional characters. "
                "Usa el contexto narrativo y la dirección visual siguientes cuando estén presentes. "
                "No cambies la identidad del personaje ni añadas elementos incompatibles. "
                f"Contexto del guion: {str(scene_context or '').strip()[:1200] or 'Sin contexto narrativo adicional'}. "
                f"Dirección del plano: {str(camera_direction or '').strip()[:350] or 'Movimiento natural apropiado para la escena'}. "
                "Do not include explanations, headings, or quotation marks; return only the motion prompt."
            ),
            "images": [image_data],
        }],
        "options": {"temperature": 0.25},
    }).encode("utf-8")
    try:
        response = json.loads(_request(
            base_url.rstrip("/") + "/api/chat", body,
            {"Content-Type": "application/json"}, timeout=timeout
        ).decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise VideoGenerationError("Ollama devolvió una respuesta visual no válida.") from exc
    message = response.get("message") or {}
    result = str(message.get("content", "")).strip()
    if not result:
        raise VideoGenerationError(f"El modelo visual {model} no devolvió una descripción.")
    return result[:4000]


def generate_video(image_path: str | Path, motion_prompt: str, workflow_path: str | Path,
                   output_dir: str | Path, base_url: str = "http://127.0.0.1:8188",
                   negative_prompt: str = "", timeout_seconds: int = 1800,
                   poll_interval: float = 2.0,
                   progress: Callable[[str], None] | None = None,
                   cancel_check: Callable[[], bool] | None = None,
                   frame_count: int = 49,
                   output_width: int = 768, output_height: int = 512) -> Path:
    """Run an API or supported visual ComfyUI I2V workflow and save the resulting video locally."""
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
    if progress:
        progress("Comprobando ComfyUI…")
    check_comfyui(base_url)
    if progress:
        progress("Subiendo imagen de referencia…")
    uploaded_name = upload_image(image_path, base_url)
    api_workflow = prepare_workflow(
        workflow, uploaded_name, prompt, negative_prompt, frame_count=frame_count,
        output_width=output_width, output_height=output_height
    )
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
