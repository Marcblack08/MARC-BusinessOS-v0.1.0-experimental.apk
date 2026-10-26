"""Automatic dependency detection and installation for MARC Video Studio AI.

Safe components (FFmpeg, Ollama, text/vision models) are installed when missing.
Large local video models are installed only when the detected hardware and free
disk space meet the conservative profile needed by the bundled LTX-Video workflow.
No administrator elevation is requested and user projects are never deleted.
"""
from __future__ import annotations

import ctypes
import json
import os
import platform
import queue
import threading
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

APP_NAME = "MARC Video Studio AI Desktop"
DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP_NAME
ENGINE_ROOT = DATA_ROOT / "engines"
WORKFLOW_ROOT = DATA_ROOT / "workflows"
REPORT_PATH = DATA_ROOT / "setup_report.json"
DEFAULT_COMFY_URL = os.environ.get("MARC_COMFYUI_URL", "http://127.0.0.1:8188").strip().rstrip("/")
OLLAMA_URL = os.environ.get("MARC_OLLAMA_URL", "http://127.0.0.1:11434").strip().rstrip("/")
LTX_WORKFLOW_URL = "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/ltxv_image_to_video.json"
LTX_CHECKPOINT_URL = "https://huggingface.co/Lightricks/LTX-Video/resolve/main/ltx-video-2b-v0.9.5.safetensors"
LTX_TEXT_ENCODER_URL = "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"
COMFY_NVIDIA_URL = "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia.7z"
COMFY_NVIDIA_OLD_URL = "https://github.com/comfyanonymous/ComfyUI/releases/latest/download/ComfyUI_windows_portable_nvidia_cu126.7z"
OLLAMA_TEXT_MODEL = "qwen2.5:3b"
OLLAMA_VISION_MODEL = "moondream"


def _notify(callback: Callable[[str], None] | None, message: str) -> None:
    if callback:
        try:
            callback(message)
        except Exception:
            pass
    try:
        print("[MARC setup] " + message, flush=True)
    except Exception:
        # Windowed PyInstaller builds may not have a console/stdout attached.
        pass


def _request_bytes(url: str, timeout: float = 8.0) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "MARC-Video-Studio/0.4"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def _request_json(url: str, timeout: float = 5.0) -> dict | list | None:
    try:
        raw = _request_bytes(url, timeout=timeout)
        return json.loads(raw.decode("utf-8"))
    except (OSError, urllib.error.URLError, TimeoutError, ValueError, UnicodeError):
        return None


def _run_capture(command: list[str], timeout: float = 8.0) -> str:
    try:
        result = subprocess.run(
            command, check=False, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        return result.stdout or ""
    except (OSError, subprocess.TimeoutExpired, ValueError):
        return ""


def supports_local_i2v(hardware: dict) -> bool:
    """Conservative gate for installing local video models on supported hardware."""
    gpu_name = str(hardware.get("gpu_name", "")).casefold()
    return bool(
        os.name == "nt"
        and float(hardware.get("gpu_vram_gb") or 0) >= 8.0
        and float(hardware.get("ram_gb") or 0) >= 24.0
        and float(hardware.get("free_disk_gb") or 0) >= 30.0
        and any(token in gpu_name for token in ("rtx", "geforce rtx", "gtx 10"))
    )


def _windows_memory_gb() -> float:
    if os.name == "nt":
        try:
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            status = MEMORYSTATUSEX()
            status.dwLength = ctypes.sizeof(status)
            if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return round(status.ullTotalPhys / (1024 ** 3), 1)
        except Exception:
            pass
    try:
        import psutil  # type: ignore
        return round(psutil.virtual_memory().total / (1024 ** 3), 1)
    except Exception:
        return 0.0


def detect_hardware(data_root: str | Path | None = None) -> dict:
    """Inspect local CPU, RAM, disk and NVIDIA VRAM without installing anything."""
    root = Path(data_root or DATA_ROOT).expanduser()
    try:
        root.mkdir(parents=True, exist_ok=True)
        free_gb = round(shutil.disk_usage(root).free / (1024 ** 3), 1)
    except OSError:
        free_gb = 0.0
    ram_gb = _windows_memory_gb()
    gpu_name = ""
    vram_gb = 0.0
    nvidia_smi = shutil.which("nvidia-smi")
    if nvidia_smi:
        output = _run_capture([
            nvidia_smi, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"
        ], timeout=10)
        first = next((line.strip() for line in output.splitlines() if line.strip()), "")
        if first:
            name, _, memory = first.partition(",")
            gpu_name = name.strip()
            try:
                vram_gb = round(float(memory.strip()) / 1024, 1)
            except ValueError:
                vram_gb = 0.0
    if not gpu_name and os.name == "nt":
        output = _run_capture([
            "powershell", "-NoProfile", "-Command",
            "Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name",
        ], timeout=10)
        gpu_name = next((line.strip() for line in output.splitlines() if line.strip()), "")
    # Local LTX image-to-video is considered installable only when there is a
    # supported NVIDIA accelerator, enough system memory and room for ~15 GB of
    # weights plus the runtime. This is a conservative installation gate, not a
    # promise of performance.
    has_nvidia_vram = bool(vram_gb > 0 and gpu_name)
    can_install_i2v = supports_local_i2v({
        "gpu_name": gpu_name, "gpu_vram_gb": vram_gb,
        "ram_gb": ram_gb, "free_disk_gb": free_gb,
    })
    return {
        "os": platform.platform(),
        "os_name": platform.system(),
        "os_release": platform.release(),
        "cpu": platform.processor() or platform.machine(),
        "cpu_cores": os.cpu_count() or 1,
        "ram_gb": ram_gb,
        "gpu_name": gpu_name or "No se detectó una GPU NVIDIA compatible",
        "gpu_vram_gb": vram_gb,
        "free_disk_gb": free_gb,
        "can_install_local_i2v": bool(can_install_i2v),
        "i2v_requirement": "Windows + NVIDIA con ≥8 GB VRAM + ≥24 GB RAM + ≥30 GB libres",
    }


def find_ollama_exe() -> str | None:
    candidates = [
        shutil.which("ollama"),
        os.environ.get("OLLAMA_EXE", ""),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe"),
        r"C:\Program Files\Ollama\ollama.exe",
    ]
    for item in candidates:
        if item and Path(item).is_file():
            return str(Path(item).resolve())
    return None


def find_ffmpeg() -> str | None:
    candidates = [
        shutil.which("ffmpeg"),
        os.environ.get("MARC_FFMPEG", ""),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "FFmpeg" / "bin" / "ffmpeg.exe"),
        r"C:\Program Files\FFmpeg\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for item in candidates:
        if item and Path(item).is_file():
            return str(Path(item).resolve())
    for base in (Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages",
                 Path(r"C:\Program Files")):
        try:
            matches = list(base.glob("**/ffmpeg.exe"))
            if matches:
                return str(matches[0].resolve())
        except (OSError, PermissionError):
            pass
    return None


def _comfy_urls() -> list[str]:
    values = [DEFAULT_COMFY_URL, "http://127.0.0.1:8189", "http://127.0.0.1:8190"]
    result = []
    for value in values:
        value = str(value or "").strip().rstrip("/")
        if value and value not in result:
            result.append(value)
    return result


def probe_comfyui() -> dict | None:
    """Return ComfyUI URL, object info and model options if an instance is online."""
    for base in _comfy_urls():
        system = _request_json(base + "/system_stats", timeout=3.0)
        info = _request_json(base + "/object_info", timeout=8.0)
        if isinstance(system, dict) and isinstance(info, dict) and "CheckpointLoaderSimple" in info:
            checkpoint_options = []
            clip_options = []
            try:
                checkpoint_options = list(
                    info["CheckpointLoaderSimple"]["input"]["required"]["ckpt_name"][0]
                )
            except (KeyError, IndexError, TypeError):
                pass
            try:
                clip_options = list(info["CLIPLoader"]["input"]["required"]["clip_name"][0])
            except (KeyError, IndexError, TypeError):
                pass
            return {
                "url": base, "system": system, "object_info": info,
                "checkpoints": [str(v) for v in checkpoint_options],
                "text_encoders": [str(v) for v in clip_options],
                "supports_ltx_i2v": "LTXVImgToVideo" in info and "SaveVideo" in info,
            }
    return None


def _winget_install(package_id: str, callback: Callable[[str], None] | None = None) -> bool:
    winget = shutil.which("winget")
    if not winget or os.name != "nt":
        _notify(callback, f"Winget no está disponible; no se pudo instalar automáticamente {package_id}.")
        return False
    _notify(callback, f"Instalando {package_id} con Winget…")
    command = [
        winget, "install", "--id", package_id, "--exact", "--silent",
        "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity",
    ]
    success = _stream_process(command, callback, f"Instalación {package_id}", timeout=1200)
    if success:
        _refresh_path()
        _notify(callback, f"{package_id} instalado.")
        return True
    _notify(callback, f"Winget no pudo confirmar la instalación de {package_id}.")
    return False


def _refresh_path() -> None:
    path = os.environ.get("PATH", "")
    additions = [
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Links"),
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama"),
        r"C:\Program Files\FFmpeg\bin",
        r"C:\ffmpeg\bin",
    ]
    os.environ["PATH"] = os.pathsep.join([p for p in additions if p and Path(p).is_dir()] + [path])


def _ensure_ollama_server(callback: Callable[[str], None] | None = None) -> tuple[str | None, list[str]]:
    api = _request_json(OLLAMA_URL + "/api/tags", timeout=2.5)
    if isinstance(api, dict):
        models = [
            str(item.get("name", "")) for item in api.get("models", [])
            if isinstance(item, dict) and item.get("name")
        ]
        return OLLAMA_URL, models
    exe = find_ollama_exe()
    if not exe:
        _notify(callback, "Ollama no está instalado; intentaré instalarlo.")
        _winget_install("Ollama.Ollama", callback)
        exe = find_ollama_exe()
    if exe:
        _notify(callback, "Iniciando el servicio local Ollama…")
        try:
            subprocess.Popen(
                [exe, "serve"], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
        except OSError:
            pass
        for _ in range(30):
            time.sleep(2)
            api = _request_json(OLLAMA_URL + "/api/tags", timeout=2.0)
            if isinstance(api, dict):
                models = [
                    str(item.get("name", "")) for item in api.get("models", [])
                    if isinstance(item, dict) and item.get("name")
                ]
                return OLLAMA_URL, models
    return None, []


def _model_installed(models: list[str], required: str) -> bool:
    base = required.split(":", 1)[0].casefold()
    return any(item.casefold() == required.casefold() or item.split(":", 1)[0].casefold() == base
               for item in models)


def _stream_process(command: list[str], callback: Callable[[str], None] | None,
                    label: str, timeout: int = 3600) -> bool:
    """Drain child output on a reader thread so a quiet process cannot block setup."""
    try:
        proc = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
    except OSError as exc:
        _notify(callback, f"{label}: {exc}")
        return False
    messages: queue.Queue[str | None] = queue.Queue()
    def reader():
        try:
            if proc.stdout:
                for line in proc.stdout:
                    messages.put(line.rstrip())
        finally:
            messages.put(None)
    threading.Thread(target=reader, daemon=True, name="MARC-Setup-Log").start()
    start = time.monotonic()
    last_update = start
    stream_closed = False
    while proc.poll() is None or not stream_closed or not messages.empty():
        if time.monotonic() - start > timeout:
            proc.kill()
            _notify(callback, f"{label} superó el tiempo límite.")
            return False
        try:
            line = messages.get(timeout=1.0)
            if line is None:
                stream_closed = True
            elif line.strip():
                _notify(callback, f"{label}: {line.strip()[:180]}")
                last_update = time.monotonic()
        except queue.Empty:
            pass
        if time.monotonic() - last_update > 20:
            _notify(callback, f"{label} sigue trabajando…")
            last_update = time.monotonic()
    return proc.returncode == 0


def _ollama_pull(model: str, callback: Callable[[str], None] | None = None) -> bool:
    exe = find_ollama_exe()
    if not exe:
        return False
    _notify(callback, f"Descargando modelo local {model}; puede ocupar varios GB…")
    return _stream_process([exe, "pull", model], callback, f"Ollama {model}", timeout=7200)


def _run_with_progress(command: list[str], callback: Callable[[str], None] | None,
                       label: str, timeout: int = 3600) -> bool:
    return _stream_process(command, callback, label, timeout=timeout)


def _download_file(url: str, destination: Path,
                   callback: Callable[[str], None] | None = None,
                   min_bytes: int = 1_000_000) -> bool:
    """Stream large weights to disk and remove incomplete downloads on failure."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and destination.stat().st_size >= max(1, int(min_bytes)):
        return True
    partial = destination.with_suffix(destination.suffix + ".download")
    try:
        request = urllib.request.Request(url, headers={"User-Agent": "MARC-Video-Studio/0.4"})
        with urllib.request.urlopen(request, timeout=90) as response, partial.open("wb") as output:
            total = int(response.headers.get("Content-Length") or 0)
            done = 0
            last = 0.0
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                output.write(chunk)
                done += len(chunk)
                now = time.monotonic()
                if now - last >= 3:
                    if total:
                        _notify(callback, f"Descargando {destination.name}: {done/1024**3:.1f}/{total/1024**3:.1f} GB")
                    else:
                        _notify(callback, f"Descargando {destination.name}: {done/1024**3:.1f} GB")
                    last = now
        if partial.stat().st_size < max(1, int(min_bytes)):
            raise OSError("El archivo descargado es demasiado pequeño o está incompleto.")
        partial.replace(destination)
        _notify(callback, f"Descarga terminada: {destination.name}")
        return True
    except (OSError, urllib.error.URLError, TimeoutError) as exc:
        try:
            partial.unlink(missing_ok=True)
        except OSError:
            pass
        _notify(callback, f"No se pudo descargar {destination.name}: {exc}")
        return False


def _find_comfy_launcher() -> Path | None:
    explicit = os.environ.get("MARC_COMFYUI_DIR", "").strip()
    roots = [Path(explicit)] if explicit else []
    roots += [
        ENGINE_ROOT / "ComfyUI_windows_portable",
        ENGINE_ROOT / "ComfyUI",
        Path(os.environ.get("USERPROFILE", str(Path.home()))) / "ComfyUI_windows_portable",
        Path("C:/AI/ComfyUI_windows_portable"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        for name in ("run_nvidia_gpu.bat", "run_nvidia_gpu_fast_fp8_accumulation.bat"):
            candidate = root / name
            if candidate.is_file():
                return candidate
        try:
            for candidate in root.glob("**/run_nvidia_gpu.bat"):
                return candidate
        except (OSError, PermissionError):
            pass
    return None


def _seven_zip_exe() -> str | None:
    candidates = [
        shutil.which("7z"), shutil.which("7za"),
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe",
        str(Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "7-Zip" / "7z.exe"),
    ]
    return next((str(Path(x).resolve()) for x in candidates if x and Path(x).is_file()), None)


def _install_comfy_portable(hardware: dict, callback: Callable[[str], None] | None) -> Path | None:
    if os.name != "nt" or not hardware.get("can_install_local_i2v"):
        return None
    gpu_name = str(hardware.get("gpu_name", "")).casefold()
    if not any(token in gpu_name for token in ("rtx", "geforce rtx", "gtx 10")):
        _notify(callback, "No se descargará ComfyUI automáticamente: la GPU detectada no coincide con una compilación NVIDIA compatible conocida.")
        return None
    _winget_install("7zip.7zip", callback)
    seven_zip = _seven_zip_exe()
    if not seven_zip:
        _notify(callback, "Falta 7-Zip para extraer ComfyUI Portable; instala 7-Zip y vuelve a pulsar Preparar IA.")
        return None
    ENGINE_ROOT.mkdir(parents=True, exist_ok=True)
    archive = ENGINE_ROOT / "ComfyUI_windows_portable.7z"
    url = COMFY_NVIDIA_OLD_URL if "gtx 10" in gpu_name else COMFY_NVIDIA_URL
    if not _download_file(url, archive, callback):
        return None
    _notify(callback, "Extrayendo ComfyUI Portable en la carpeta local de MARC…")
    if not _run_with_progress(
        [seven_zip, "x", str(archive), "-o" + str(ENGINE_ROOT), "-y"],
        callback, "Extracción de ComfyUI", timeout=2400,
    ):
        return None
    launcher = _find_comfy_launcher()
    if launcher:
        return launcher
    _notify(callback, "ComfyUI se extrajo, pero no se encontró el lanzador NVIDIA esperado.")
    return None


def _managed_comfy_model_dirs(launcher: Path | None) -> tuple[Path, Path] | None:
    if launcher:
        root = launcher.parent
        candidates = [
            root / "ComfyUI" / "models",
            root / "ComfyUI" / "models" / "checkpoints",
        ]
        for models in candidates:
            if models.is_dir() and (models / "checkpoints").is_dir():
                return models / "checkpoints", models / "text_encoders"
    custom = os.environ.get("MARC_COMFYUI_MODELS", "").strip()
    if custom:
        models = Path(custom)
        if (models / "checkpoints").is_dir():
            return models / "checkpoints", models / "text_encoders"
    return None


def _ensure_ltx_weights(launcher: Path | None,
                        callback: Callable[[str], None] | None = None) -> bool:
    dirs = _managed_comfy_model_dirs(launcher)
    if not dirs:
        _notify(callback, "No se pudo localizar una carpeta de modelos de ComfyUI para LTX-Video.")
        return False
    checkpoints, text_encoders = dirs
    checkpoint = checkpoints / "ltx-video-2b-v0.9.5.safetensors"
    encoder = text_encoders / "t5xxl_fp16.safetensors"
    # The two model files total roughly 15 GB. The caller has already checked
    # free space and local hardware before reaching this function.
    return (
        _download_file(LTX_CHECKPOINT_URL, checkpoint, callback)
        and _download_file(LTX_TEXT_ENCODER_URL, encoder, callback)
    )


def ensure_official_workflow(callback: Callable[[str], None] | None = None) -> Path | None:
    WORKFLOW_ROOT.mkdir(parents=True, exist_ok=True)
    destination = WORKFLOW_ROOT / "ltxv_image_to_video.json"
    if destination.is_file():
        try:
            payload = json.loads(destination.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("nodes") and payload.get("links"):
                return destination
        except (OSError, ValueError):
            pass
    _notify(callback, "Descargando la plantilla oficial de imagen a vídeo LTX desde Comfy-Org…")
    if _download_file(LTX_WORKFLOW_URL, destination, callback, min_bytes=100):
        try:
            payload = json.loads(destination.read_text(encoding="utf-8"))
            if isinstance(payload, dict) and payload.get("nodes") and payload.get("links"):
                return destination
        except (OSError, ValueError):
            pass
        destination.unlink(missing_ok=True)
    return None


def _launch_comfy(launcher: Path, callback: Callable[[str], None] | None = None) -> None:
    if probe_comfyui():
        return
    _notify(callback, "Iniciando ComfyUI local…")
    try:
        subprocess.Popen(
            ["cmd.exe", "/c", str(launcher)], cwd=str(launcher.parent),
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=0,
        )
    except OSError as exc:
        _notify(callback, f"No se pudo iniciar ComfyUI: {exc}")
        return
    for _ in range(90):
        time.sleep(2)
        if probe_comfyui():
            _notify(callback, "ComfyUI está listo.")
            return
    _notify(callback, "ComfyUI no respondió a tiempo. Revisa la consola del motor y vuelve a intentarlo.")


def build_report(callback: Callable[[str], None] | None = None,
                 data_root: str | Path | None = None) -> dict:
    hardware = detect_hardware(data_root)
    ffmpeg = find_ffmpeg()
    ollama_tags = _request_json(OLLAMA_URL + "/api/tags", timeout=2.5)
    ollama_models = [
        str(item.get("name", "")) for item in (ollama_tags or {}).get("models", [])
        if isinstance(item, dict) and item.get("name")
    ] if isinstance(ollama_tags, dict) else []
    comfy = probe_comfyui()
    workflow = ensure_official_workflow(None) if comfy and comfy.get("supports_ltx_i2v") else None
    checkpoint_present = bool(comfy and any("ltx-video-2b" in name.casefold() for name in comfy.get("checkpoints", [])))
    encoder_present = bool(comfy and any("t5xxl_fp16" in name.casefold() for name in comfy.get("text_encoders", [])))
    local_ready = bool(comfy and comfy.get("supports_ltx_i2v") and checkpoint_present and encoder_present and workflow)
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware": hardware,
        "ffmpeg": {"available": bool(ffmpeg), "path": ffmpeg or ""},
        "ollama": {
            "available": bool(ollama_models or find_ollama_exe()),
            "api_available": isinstance(ollama_tags, dict),
            "models": ollama_models,
            "script_model_ready": _model_installed(ollama_models, OLLAMA_TEXT_MODEL),
            "vision_model_ready": any(_model_installed(ollama_models, model) for model in
                                      (OLLAMA_VISION_MODEL, "qwen2.5vl", "gemma3", "llava", "llama3.2-vision", "gemma4")),
        },
        "comfyui": {
            "available": bool(comfy), "url": comfy.get("url", "") if comfy else "",
            "supports_ltx_i2v": bool(comfy and comfy.get("supports_ltx_i2v")),
            "checkpoint_ready": checkpoint_present, "text_encoder_ready": encoder_present,
            "workflow_path": str(workflow) if workflow else "",
        },
        "video_generation_ready": local_ready,
        "video_setup_recommended": bool(hardware.get("can_install_local_i2v")),
        "notes": [],
    }
    if not hardware.get("can_install_local_i2v") and not local_ready:
        report["notes"].append(
            "Este equipo no cumple el perfil conservador para instalar LTX local (NVIDIA ≥8 GB VRAM, "
            "RAM ≥24 GB y espacio libre ≥30 GB). Se omite la descarga de unos 15 GB de modelos de vídeo."
        )
    if not local_ready:
        report["notes"].append("No hay un motor local LTX imagen-a-vídeo completamente preparado.")
    try:
        Path(data_root or REPORT_PATH.parent).mkdir(parents=True, exist_ok=True)
        report_path = Path(data_root) / "setup_report.json" if data_root else REPORT_PATH
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return report


def run_automatic_setup(callback: Callable[[str], None] | None = None,
                        install_video_models: bool = True,
                        data_root: str | Path | None = None) -> dict:
    """Install missing safe prerequisites, and install local I2V only on suitable hardware."""
    root = Path(data_root or DATA_ROOT).expanduser()
    root.mkdir(parents=True, exist_ok=True)
    _notify(callback, "Analizando Windows, memoria, GPU, disco y motores de IA instalados…")
    hardware = detect_hardware(root)
    ffmpeg = find_ffmpeg()
    if not ffmpeg:
        _winget_install("Gyan.FFmpeg.Shared", callback)
        ffmpeg = find_ffmpeg()
    comfy = probe_comfyui()
    free_disk_gb = shutil.disk_usage(root).free / (1024 ** 3)
    model_downloads_allowed = free_disk_gb >= 8.0
    ollama_url, models = _ensure_ollama_server(callback)
    if ollama_url:
        if not _model_installed(models, OLLAMA_TEXT_MODEL):
            if model_downloads_allowed:
                _ollama_pull(OLLAMA_TEXT_MODEL, callback)
            else:
                _notify(callback, "Quedan menos de 8 GB libres; no descargaré modelos de texto/visión para evitar llenar el disco.")
        tags = _request_json(OLLAMA_URL + "/api/tags", timeout=3.0)
        models = [
            str(item.get("name", "")) for item in (tags or {}).get("models", [])
            if isinstance(item, dict) and item.get("name")
        ] if isinstance(tags, dict) else models
        vision_ready = any(_model_installed(models, model) for model in
                           (OLLAMA_VISION_MODEL, "qwen2.5vl", "gemma3", "llava", "llama3.2-vision", "gemma4"))
        if not vision_ready:
            if model_downloads_allowed:
                _ollama_pull(OLLAMA_VISION_MODEL, callback)
            else:
                _notify(callback, "Se omitió el modelo visual porque no hay espacio libre suficiente.")
    else:
        _notify(callback, "Ollama no está disponible. Se conserva el editor; la instalación local de IA necesita Winget o el instalador oficial de Ollama.")
    workflow_path = ensure_official_workflow(callback)
    if not comfy:
        launcher = _find_comfy_launcher()
        if launcher:
            _launch_comfy(launcher, callback)
            comfy = probe_comfyui()
    else:
        launcher = _find_comfy_launcher()
    if not comfy and install_video_models and hardware.get("can_install_local_i2v"):
        if shutil.disk_usage(root).free / (1024 ** 3) < 30:
            _notify(callback, "No hay 30 GB libres. No se descargará ComfyUI ni el modelo de vídeo para evitar llenar el disco.")
        else:
            launcher = _install_comfy_portable(hardware, callback)
            if launcher and _ensure_ltx_weights(launcher, callback):
                _launch_comfy(launcher, callback)
                comfy = probe_comfyui()
    elif comfy and install_video_models and hardware.get("can_install_local_i2v"):
        launcher = _find_comfy_launcher()
        dirs = _managed_comfy_model_dirs(launcher)
        if dirs:
            checkpoints, encoders = dirs
            has_checkpoint = (checkpoints / "ltx-video-2b-v0.9.5.safetensors").is_file()
            has_encoder = (encoders / "t5xxl_fp16.safetensors").is_file()
            if not (has_checkpoint and has_encoder):
                if shutil.disk_usage(root).free / (1024 ** 3) >= 20:
                    _ensure_ltx_weights(launcher, callback)
                    _launch_comfy(launcher, callback)
                    comfy = probe_comfyui()
                else:
                    _notify(callback, "No hay espacio libre suficiente para instalar el modelo LTX.")
    if workflow_path is None:
        workflow_path = ensure_official_workflow(callback)
    report = build_report(callback, data_root=root)
    report["ffmpeg"]["path"] = find_ffmpeg() or ""
    report["comfyui"]["workflow_path"] = str(workflow_path) if workflow_path else ""
    if not report["ffmpeg"]["available"]:
        report["notes"].append("FFmpeg sigue ausente: instala FFmpeg y vuelve a pulsar Preparar IA.")
    if not report["ollama"]["script_model_ready"]:
        report["notes"].append("El modelo de guion Qwen no está disponible.")
    if not report["ollama"]["vision_model_ready"]:
        report["notes"].append("No se detectó un modelo visual en Ollama; AUTO no analizará imágenes hasta instalar uno.")
    if not report["video_generation_ready"] and not report["hardware"].get("can_install_local_i2v"):
        report["notes"].append(
            "En este equipo se pueden preparar guion, voz, audio y montaje ligero, pero no se promete movimiento corporal neuronal local. "
            "Para esa etapa se necesita un PC con GPU compatible o un motor de vídeo externo."
        )
    try:
        (root / "setup_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass
    return report


def load_setup_report(data_root: str | Path | None = None) -> dict | None:
    path = Path(data_root) / "setup_report.json" if data_root else REPORT_PATH
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    import argparse
    parser = argparse.ArgumentParser(description="Detectar y preparar dependencias locales de MARC.")
    parser.add_argument("--bootstrap", action="store_true", help="Instalar dependencias que falten y preparar motores compatibles.")
    parser.add_argument("--check", action="store_true", help="Solo detectar lo instalado, sin descargar paquetes.")
    args = parser.parse_args(argv)
    if args.check:
        report = build_report()
    else:
        report = run_automatic_setup()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("ffmpeg", {}).get("available") else 1


if __name__ == "__main__":
    raise SystemExit(main())
