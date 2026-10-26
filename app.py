from __future__ import annotations

import json
import math
import hashlib
import os
import random
import queue
import shutil
import sqlite3
import subprocess
import textwrap
import re
import threading
import platform
import ctypes
import time
import uuid
import urllib.request
import urllib.error
import webbrowser
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from scene_engine import (
    allocate_scene_durations, build_audio_filter_graph, build_scene_visual_brief,
    build_cinematic_image_prompt, build_comfy_image_workflow, build_video_transition_filter_graph, camera_direction_for_shot,
    build_srt_subtitles, build_srt_from_timed_segments, build_subtitle_drawtext_filter, expand_scenes_to_shots, ffmpeg_filter_path,
    parse_script_scenes, scene_motion_filter
)
from voice_engine import build_kokoro_ssml, parse_kokoro_voice_ids
from story_engine import (
    FPS_OPTIONS, RESOLUTION_PROFILES, SERIES_VIDEO_MODE, SHORT_VIDEO_MODE,
    build_series_context, continuity_review_check, export_dimensions,
    extract_speaker_names, target_word_count, format_short_chapter, visual_shot_count,
    creative_direction, dialogue_quality_warnings
)
from production_pipeline import ProductionPipeline, STAGE_LABELS
from production_package import discover_production_package, map_production_resources, parse_scene_directions
from media_quality import inspect_media_file
from remote_server import RemoteControlServer

APP_NAME = "MARC Video Studio AI Desktop"
ROOT = Path(__file__).resolve().parent
# En una instalación normal, los datos se guardan en el perfil del usuario, no en Program Files.
if os.name == "nt" and (getattr(__import__("sys"), "frozen", False) or os.environ.get("MARC_USE_USER_DATA") == "1"):
    APP_DATA_ROOT = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MARC Video Studio AI Desktop"
else:
    APP_DATA_ROOT = ROOT
DATA_DIR = APP_DATA_ROOT / "data"
PROJECTS_DIR = APP_DATA_ROOT / "projects"
DB_PATH = DATA_DIR / "marc_video_studio.db"

COMFYUI_URL = os.environ.get("MARC_COMFYUI_URL", "http://127.0.0.1:8188").strip().rstrip("/")
KOKORO_URL = os.environ.get("MARC_KOKORO_URL", "http://127.0.0.1:7860").strip().rstrip("/")
# Probe common local ports; accept only a valid ComfyUI API endpoint.
COMFYUI_FALLBACK_PORTS = (8188, 8189, 8190, 8180, 7860, 8000)

PLATFORMS = {
    "YouTube 16:9": (1280, 720),
    "TikTok / Reels / Shorts 9:16": (720, 1280),
    "Facebook 1:1": (900, 900),
}

def db_connect():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            topic TEXT NOT NULL,
            platform TEXT NOT NULL,
            duration_minutes INTEGER NOT NULL,
            style TEXT NOT NULL,
            script TEXT NOT NULL DEFAULT '',
            approved INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            protagonist TEXT NOT NULL DEFAULT '',
            conflict TEXT NOT NULL DEFAULT '',
            tone TEXT NOT NULL DEFAULT 'Dramático e intenso',
            narrator TEXT NOT NULL DEFAULT 'Tercera persona',
            ending TEXT NOT NULL DEFAULT 'Justicia y superación',
            drawing_style TEXT NOT NULL DEFAULT 'Anime cinematográfico',
            animation_style TEXT NOT NULL DEFAULT '2D fluida',
            animation_intensity TEXT NOT NULL DEFAULT 'Muy animado',
            overlay_mode TEXT NOT NULL DEFAULT 'Título de escena',
            transition_style TEXT NOT NULL DEFAULT 'Fundido suave',
            subtitle_font TEXT NOT NULL DEFAULT 'Arial',
            subtitle_size TEXT NOT NULL DEFAULT 'Mediano',
            subtitle_color TEXT NOT NULL DEFAULT 'Blanco',
            subtitle_position TEXT NOT NULL DEFAULT 'Inferior',
            subtitle_outline INTEGER NOT NULL DEFAULT 1,
            resolution TEXT NOT NULL DEFAULT '1080p (Full HD)',
            fps INTEGER NOT NULL DEFAULT 30,
            video_mode TEXT NOT NULL DEFAULT 'Novela / Serie',
            series_key TEXT NOT NULL DEFAULT '',
            episode_number INTEGER NOT NULL DEFAULT 1,
            story_bible TEXT NOT NULL DEFAULT '',
            continuity_state TEXT NOT NULL DEFAULT '',
            voice_assignments TEXT NOT NULL DEFAULT '{}'
        )
    """)
    # Migra bases de datos antiguas sin eliminar los proyectos ya guardados.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(projects)").fetchall()}
    migrations = {
        "protagonist": "TEXT NOT NULL DEFAULT ''",
        "conflict": "TEXT NOT NULL DEFAULT ''",
        "tone": "TEXT NOT NULL DEFAULT 'Dramático e intenso'",
        "narrator": "TEXT NOT NULL DEFAULT 'Tercera persona'",
        "ending": "TEXT NOT NULL DEFAULT 'Justicia y superación'",
        "drawing_style": "TEXT NOT NULL DEFAULT 'Anime cinematográfico'",
        "animation_style": "TEXT NOT NULL DEFAULT '2D fluida'",
        "animation_intensity": "TEXT NOT NULL DEFAULT 'Muy animado'",
        "overlay_mode": "TEXT NOT NULL DEFAULT 'Título de escena'",
        "transition_style": "TEXT NOT NULL DEFAULT 'Fundido suave'",
        "subtitle_font": "TEXT NOT NULL DEFAULT 'Arial'",
        "subtitle_size": "TEXT NOT NULL DEFAULT 'Mediano'",
        "subtitle_color": "TEXT NOT NULL DEFAULT 'Blanco'",
        "subtitle_position": "TEXT NOT NULL DEFAULT 'Inferior'",
        "subtitle_outline": "INTEGER NOT NULL DEFAULT 1",
        "resolution": "TEXT NOT NULL DEFAULT '1080p (Full HD)'",
        "fps": "INTEGER NOT NULL DEFAULT 30",
        "video_mode": "TEXT NOT NULL DEFAULT 'Novela / Serie'",
        "series_key": "TEXT NOT NULL DEFAULT ''",
        "episode_number": "INTEGER NOT NULL DEFAULT 1",
        "story_bible": "TEXT NOT NULL DEFAULT ''",
        "continuity_state": "TEXT NOT NULL DEFAULT ''",
        "voice_assignments": "TEXT NOT NULL DEFAULT '{}'",
    }
    for column, declaration in migrations.items():
        if column not in existing:
            conn.execute(f"ALTER TABLE projects ADD COLUMN {column} {declaration}")
    conn.commit()
    return conn

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1536x864")
        self.minsize(1040, 680)
        self.state("zoomed")
        self.conn = db_connect()
        self.current_id = None
        self._creator_narration_override = ""
        self._creator_auto_narration_active = False
        self.series_key = ""
        self.episode_number = 1
        self.story_bible = ""
        self.continuity_state = ""
        self.voice_assignments = {}
        self._vlc_instance = None
        self._vlc_module = None
        self._vlc_player = None
        self._vlc_dll_dir_handle = None
        self.preview_player_active = False
        self._preview_poll_pending = False
        self._updating_preview_seek = False
        self.preview_render_path = ""
        self.preview_render_signature = ""
        self.manual_preview_path = ""
        self.preview_after_image_batch = False
        self.batch_image_active = False
        self.batch_image_queue = []
        self.batch_image_total = 0
        self.ai_available = False
        self.generation_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.generation_running = False
        self.render_running = False
        self.render_cancel_event = threading.Event()
        self.scene_data = []
        self.scene_assets = {}
        self.scene_directions = {}
        self.scene_duration_overrides = {}
        self.auto_expand_storyboard = True
        self.last_export_path = ""
        self.audio_track_path = ""
        self.music_track_path = ""
        self.loop_music_var = None
        self.voice_generation_running = False
        self.voice_cancel_event = threading.Event()
        self.available_voice_names = []
        self.kokoro_voice_names = []
        self.kokoro_url = KOKORO_URL
        self.comfy_url = COMFYUI_URL
        self.comfy_available = False
        self.image_generation_running = False
        self.image_prompt_cache = {}
        self._style()
        self._build()
        self.refresh_projects()
        self.remote_command_queue = queue.Queue(maxsize=64)
        self.remote_snapshot = {}
        self.remote_server = None
        self.remote_server_error = ""
        self.remote_last_command = {}
        self.remote_render_active = False
        try:
            self.remote_server = RemoteControlServer(
                data_dir=DATA_DIR, db_path=DB_PATH, projects_dir=PROJECTS_DIR,
                command_queue=self.remote_command_queue,
                snapshot_provider=lambda: self.remote_snapshot,
                host="127.0.0.1", port=8765,
            )
            self.remote_server.start()
        except OSError as exc:
            self.remote_server_error = str(exc)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.timeline_playhead_seconds = 0
        self.timeline_selected_scene = 1
        self.after(700, self.detect_pc_async)
        self.check_tools()
        self.after(180, self._poll_generation_events)
        self.after(250, self._poll_remote_commands)
        self.after(500, self._publish_remote_snapshot)
        self.after(1100, lambda: self.detect_image_models(quiet=True))
        self.after(1300, lambda: self.detect_local_voices(quiet=True))

    def show_remote_access(self):
        """Display the private access token and Tailscale Serve instructions."""
        if not self.remote_server:
            messagebox.showerror("Panel remoto no iniciado",
                                 "El servidor no pudo abrir el puerto 8765. Cierra otra instancia de MARC y vuelve a intentarlo.")
            return
        window = tk.Toplevel(self)
        window.title("Acceso remoto a MARC")
        window.transient(self)
        window.resizable(False, False)
        window.configure(bg=self.colors["panel"])
        body = tk.Frame(window, bg=self.colors["panel"], padx=18, pady=16)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="MARC · ACCESO REMOTO", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 14, "bold")).pack(anchor="w")
        tk.Label(body, text="Código privado para iniciar sesión desde el teléfono.",
                 bg=self.colors["panel"], fg=self.colors["muted"]).pack(anchor="w", pady=(6, 10))
        tk.Label(body, text="Código de acceso", bg=self.colors["panel"], fg=self.colors["text"]).pack(anchor="w")
        token_var = tk.StringVar(value=self.remote_server.token)
        token_entry = ttk.Entry(body, textvariable=token_var, width=58)
        token_entry.pack(fill="x", pady=(4, 7))
        token_entry.configure(state="readonly")
        actions = tk.Frame(body, bg=self.colors["panel"])
        actions.pack(fill="x", pady=(0, 10))
        def copy_token():
            self.clipboard_clear()
            self.clipboard_append(self.remote_server.token)
            self.update()
            messagebox.showinfo("Código copiado", "Código copiado al portapapeles.", parent=window)
        ttk.Button(actions, text="Copiar código", command=copy_token).pack(side="left")
        ttk.Button(actions, text="Abrir panel local",
                   command=lambda: webbrowser.open(self.remote_server.local_url)).pack(side="left", padx=(8, 0))
        instructions = (
            "Para acceder desde fuera de casa, ejecuta en CMD o PowerShell de esta computadora:\n\n"
            "   tailscale serve --bg 8765\n\n"
            "Abre en el teléfono la URL HTTPS que Tailscale muestre y pega el código de arriba.\n\n"
            "Usa Serve, no Funnel. No compartas el código. Mantén MARC abierto."
        )
        tk.Label(body, text=instructions, bg=self.colors["panel"], fg=self.colors["text"],
                 justify="left", wraplength=420).pack(anchor="w")
        ttk.Button(body, text="Cerrar", command=window.destroy).pack(anchor="e", pady=(12, 0))
        window.update_idletasks()
        window.geometry(f"+{self.winfo_rootx()+80}+{self.winfo_rooty()+80}")

    def _on_close(self):
        try:
            if self.remote_server:
                self.remote_server.stop()
        except Exception:
            pass
        try:
            self.conn.close()
        except Exception:
            pass
        self.destroy()

    def _publish_remote_snapshot(self):
        try:
            running = bool(self.generation_running or self.render_running or
                           self.image_generation_running or self.voice_generation_running or
                           getattr(self, "audio_mux_running", False))
            maximum = max(1.0, float(self.progressbar.cget("maximum")))
            value = max(0.0, float(self.progressbar.cget("value")))
            self.remote_snapshot = {
                "label": "MARC trabajando" if running else "MARC listo",
                "detail": self.status_var.get(),
                "running": running,
                "progress": max(0, min(100, round(value / maximum * 100))),
                "current_id": self.current_id,
                "current_title": self.title_var.get(),
                "ollama": bool(self.ai_available),
                "comfyui": bool(self.comfy_available),
                "server_error": self.remote_server_error,
                "last_command": self.remote_last_command,
            }
        except (tk.TclError, AttributeError, ValueError):
            pass
        self.after(800, self._publish_remote_snapshot)

    def _remote_load_project(self, project_id):
        try:
            project_id = int(project_id)
        except (TypeError, ValueError):
            raise ValueError("ID de proyecto no válido.")
        self.refresh_projects()
        for index, row in enumerate(self.project_rows):
            if int(row["id"]) == project_id:
                self.project_list.selection_clear(0, "end")
                self.project_list.selection_set(index)
                self.project_list.activate(index)
                self.load_selected()
                return
        raise ValueError("No se encontró el proyecto.")

    def _poll_remote_commands(self):
        try:
            while True:
                command = self.remote_command_queue.get_nowait()
                action = command.get("action", "")
                payload = command.get("payload") or {}
                try:
                    if action == "generate_script":
                        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
                            raise RuntimeError("MARC ya tiene un trabajo en curso.")
                        title = str(payload.get("title", "")).strip()[:100]
                        topic = str(payload.get("topic", "")).strip()
                        if not title or not topic:
                            raise ValueError("Completa el nombre del proyecto y la premisa.")
                        if len(topic) > 3000:
                            raise ValueError("La premisa no puede superar 3000 caracteres.")
                        duration = int(payload.get("duration", 2))
                        if duration < 1 or duration > 30:
                            raise ValueError("La duración remota permitida inicialmente es de 1 a 30 minutos.")
                        platform_name = str(payload.get("platform", "YouTube 16:9"))
                        if platform_name not in PLATFORMS:
                            platform_name = "YouTube 16:9"
                        genres = {"Novela dramática", "Reencarnación y venganza", "Superación personal", "Romance",
                                  "Fantasía", "Misterio y suspenso", "Terror", "Acción y aventura", "Ciencia ficción",
                                  "Drama familiar", "Educativo y directo", "Documental", "Promocional"}
                        genre = str(payload.get("genre", "Misterio y suspenso"))
                        if genre not in genres:
                            genre = "Misterio y suspenso"
                        mode = str(payload.get("video_mode", SHORT_VIDEO_MODE))
                        if mode not in (SHORT_VIDEO_MODE, SERIES_VIDEO_MODE):
                            mode = SHORT_VIDEO_MODE
                        if self.current_id is not None:
                            self.save_project(quiet=True)
                        self.current_id = None
                        self.series_key = ""
                        self.episode_number = 1
                        self.story_bible = ""
                        self.continuity_state = ""
                        self.voice_assignments = {}
                        self.title_var.set(title)
                        self.topic_var.set(topic)
                        self.platform_var.set(platform_name)
                        self.duration_var.set(str(duration))
                        self.style_var.set(genre)
                        self.video_mode_var.set(mode)
                        self.protagonist_var.set(str(payload.get("protagonist", ""))[:160])
                        self.conflict_var.set(str(payload.get("conflict", ""))[:300])
                        self._load_scene_assets(None)
                        self.script_text.configure(state="normal")
                        self.script_text.delete("1.0", "end")
                        self.script_text.configure(state="disabled")
                        self._refresh_scene_outline("")
                        self.set_configuration_visible(True)
                        self.generate_script(remote=True)
                    elif action == "open_project":
                        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
                            raise RuntimeError("Espera a que termine el trabajo actual antes de cambiar de proyecto.")
                        self._remote_load_project(payload.get("project_id"))
                    elif action == "save_script":
                        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
                            raise RuntimeError("No se puede editar el guion mientras hay un trabajo en curso.")
                        self._remote_load_project(payload.get("project_id"))
                        script = str(payload.get("script", ""))
                        if len(script) > 200000:
                            raise ValueError("El guion excede 200 000 caracteres.")
                        self.script_text.configure(state="normal")
                        self.script_text.delete("1.0", "end")
                        self.script_text.insert("1.0", script)
                        self._refresh_scene_outline(script)
                        self.save_project(reset_approval=True, quiet=True)
                        self.status_var.set("Guion guardado desde el teléfono; vuelve a aprobarlo antes de exportar.")
                    elif action == "approve_script":
                        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
                            raise RuntimeError("Espera a que termine el trabajo actual antes de aprobar el guion.")
                        self._remote_load_project(payload.get("project_id"))
                        self.approve_script(remote=True)
                    elif action == "generate_images":
                        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
                            raise RuntimeError("MARC ya tiene un trabajo en curso.")
                        self._remote_load_project(payload.get("project_id"))
                        if not self._existing_approval():
                            raise RuntimeError("Revisa y aprueba el guion antes de generar imágenes.")
                        if not self.comfy_available or not self.image_model_var.get().strip():
                            self.detect_image_models(quiet=True)
                            raise RuntimeError("ComfyUI o el checkpoint no están listos. Abre ComfyUI, selecciona/detecta un modelo y vuelve a intentarlo.")
                        self.remote_image_batch_active = True
                        self.generate_missing_scene_images(preconfirmed=True, preview_after=False)
                        if not self.batch_image_active and not self.image_generation_running:
                            self.remote_image_batch_active = False
                    elif action == "render_video":
                        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
                            raise RuntimeError("MARC ya tiene un trabajo en curso.")
                        self._remote_load_project(payload.get("project_id"))
                        self._start_video_render(preview=False, remote=True)
                    elif action in ("cancel", "cancel_generation", "cancel_render"):
                        if action in ("cancel", "cancel_generation") and self.generation_running:
                            self.cancel_event.set()
                        if action in ("cancel", "cancel_render") and self.render_running:
                            self.render_cancel_event.set()
                        if not self.generation_running and not self.render_running:
                            raise RuntimeError("No hay un guion ni un render que cancelar.")
                        self.status_var.set("Cancelación remota solicitada.")
                    else:
                        raise ValueError("Acción no reconocida.")
                    self.remote_last_command = {"id": command.get("id"), "ok": True, "message": "Solicitud procesada: " + action}
                except Exception as exc:
                    self.remote_last_command = {"id": command.get("id"), "ok": False, "message": str(exc)[:500]}
                    self.status_var.set("Error en la solicitud remota: " + str(exc)[:220])
        except queue.Empty:
            pass
        self.after(250, self._poll_remote_commands)

    def detect_pc_async(self):
        self.pc_summary_var.set("Detectando procesador, memoria, gráficos y herramientas…")
        self.estimate_var.set("Calculando un rango aproximado; la primera generación puede tardar más.")
        threading.Thread(target=self._detect_pc_worker, daemon=True).start()

    def _detect_pc_worker(self):
        info = {"os": platform.platform(), "cpu": platform.processor() or "CPU no identificada",
                "cores": os.cpu_count() or 2, "ram_gb": None, "gpu": "No identificada",
                "ollama": shutil.which("ollama") is not None, "ffmpeg": self._find_ffmpeg() is not None}
        if os.name == "nt":
            try:
                class MEMORYSTATUSEX(ctypes.Structure):
                    _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                                ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                                ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                                ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                                ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
                mem = MEMORYSTATUSEX(); mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
                if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem)):
                    info["ram_gb"] = round(mem.ullTotalPhys / (1024 ** 3), 1)
            except Exception:
                pass
            ps = "$cpu=(Get-CimInstance Win32_Processor | Select-Object -First 1 -ExpandProperty Name); $gpu=(Get-CimInstance Win32_VideoController | Select-Object -ExpandProperty Name) -join ', '; Write-Output ('CPU=' + $cpu); Write-Output ('GPU=' + $gpu)"
            try:
                out = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True,
                                     text=True, timeout=8, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                for line in out.stdout.splitlines():
                    if line.startswith("CPU=") and line[4:].strip(): info["cpu"] = line[4:].strip()
                    if line.startswith("GPU=") and line[4:].strip(): info["gpu"] = line[4:].strip()
            except Exception:
                pass
        else:
            try:
                with open("/proc/meminfo", encoding="utf-8") as f:
                    total = next((line for line in f if line.startswith("MemTotal:")), "")
                    if total: info["ram_gb"] = round(int(total.split()[1]) / 1024 / 1024, 1)
            except Exception:
                pass
        info["ram_gb"] = info["ram_gb"] or 8
        info["summary"] = f"PC detectada: {info['cpu']} · {info['cores']} hilos lógicos · RAM {info['ram_gb']} GB · GPU: {info['gpu']} · Ollama: {'sí' if info['ollama'] else 'no detectado'} · FFmpeg: {'sí' if info['ffmpeg'] else 'no detectado'}"
        self.generation_queue.put(("pc_info", info))

    def _estimate_time(self, minutes, info=None):
        info = info or getattr(self, "pc_info", {})
        cores = max(2, int(info.get("cores") or os.cpu_count() or 2))
        ram = float(info.get("ram_gb") or 8)
        cpu = (info.get("cpu") or "").lower()
        gpu = (info.get("gpu") or "").lower()
        # Conservative heuristic, not a benchmark. Qwen latency varies with prompt/context and model offload.
        speed_factor = 1.0
        if cores <= 4: speed_factor *= 1.55
        elif cores <= 6: speed_factor *= 1.2
        elif cores >= 12: speed_factor *= 0.72
        if ram < 8: speed_factor *= 1.6
        elif ram < 16: speed_factor *= 1.2
        if any(x in cpu for x in ("i5-4", "i5-3", "4th gen", "haswell")): speed_factor *= 1.2
        if any(x in gpu for x in ("gtx 750", "gt 7", "intel(r) hd graphics")): speed_factor *= 1.15
        if any(x in gpu for x in ("rtx", "radeon rx 7", "radeon rx 6")): speed_factor *= 0.75
        script_low = max(1, minutes * 0.7 * speed_factor)
        script_high = max(script_low + 1, minutes * 2.2 * speed_factor)
        scenes = max(1, math.ceil(minutes * 60 / 5))
        render_low = max(5, scenes * 0.35)
        render_high = max(render_low + 30, scenes * 1.5)
        # A first local model load can add substantial overhead.
        first_run = " La primera ejecución puede tardar más mientras carga el modelo." if not getattr(self, "ai_available", False) else ""
        return f"Estimado para {minutes} min de vídeo: guion {self._format_eta(script_low*60)}–{self._format_eta(script_high*60)}; render de escenas de texto {self._format_eta(render_low*60)}–{self._format_eta(render_high*60)}. Total base orientativo {self._format_eta(script_low*60+render_low*60)}–{self._format_eta(script_high*60+render_high*60)}.{first_run} La generación de ilustraciones con ComfyUI y la narración de Windows se estiman por separado, porque dependen del checkpoint, la voz y el hardware; esos tiempos no están incluidos en el total base."

    @staticmethod
    def _format_eta(seconds):
        seconds = max(0, int(seconds))
        if seconds < 60: return f"{seconds} s"
        minutes, sec = divmod(seconds, 60)
        if minutes < 60: return f"{minutes} min" if sec < 15 else f"{minutes} min {sec} s"
        hours, minutes = divmod(minutes, 60)
        return f"{hours} h {minutes} min"

    def _style(self):
        """Apply the unified MARC dark-cinematic design system to native Tk/ttk widgets."""
        self.colors = {
            # Premium midnight palette: ink background, layered navy surfaces,
            # electric-blue primary actions and restrained cyan highlights.
            "bg": "#080d18", "panel": "#101a2b", "panel2": "#1a2a42",
            "input": "#0a1220", "accent": "#397dff", "accent_hover": "#6096ff",
            "text": "#f4f7ff", "muted": "#aab8ce", "border": "#293b56",
            "success": "#70dfb4", "warning": "#f3ca79", "danger": "#ff8298",
            "glow": "#19365f", "surface": "#142239",
        }
        self.configure(bg=self.colors["bg"])
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", font=("Segoe UI", 10), foreground=self.colors["text"])
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("Surface.TFrame", background=self.colors["surface"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=self.colors["bg"], foreground="#70a7ff", font=("Segoe UI", 26, "bold"))
        style.configure("Section.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 11, "bold"))
        style.configure("KPI.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 18, "bold"))
        style.configure("TLabelFrame", background=self.colors["panel"], foreground=self.colors["text"], bordercolor=self.colors["border"], relief="solid", borderwidth=1)
        style.configure("TLabelFrame.Label", background=self.colors["panel"], foreground=self.colors["muted"], font=("Segoe UI", 9, "bold"))
        style.configure("TButton", padding=(11, 8), font=("Segoe UI", 9, "bold"), background=self.colors["panel2"], foreground=self.colors["text"], borderwidth=1, bordercolor=self.colors["border"], focusthickness=2, focuscolor=self.colors["accent"], relief="flat")
        style.map("TButton", background=[("disabled", self.colors["panel"]), ("pressed", self.colors["accent"]), ("active", "#243a5c")], foreground=[("disabled", "#64758e"), ("active", self.colors["text"])], bordercolor=[("focus", self.colors["accent"]), ("active", "#35547d")])
        style.configure("Accent.TButton", padding=(13, 9), font=("Segoe UI", 9, "bold"), background=self.colors["accent"], foreground="#ffffff", borderwidth=0, bordercolor=self.colors["accent"], focusthickness=2, focuscolor=self.colors["accent"], relief="flat")
        style.map("Accent.TButton", background=[("disabled", "#263a5c"), ("pressed", "#255edb"), ("active", self.colors["accent_hover"])], foreground=[("disabled", "#93a4bd"), ("active", "#ffffff")])
        style.configure("Quiet.TButton", padding=(10, 7), background=self.colors["panel"], foreground=self.colors["muted"], borderwidth=0, relief="flat")
        style.map("Quiet.TButton", background=[("active", self.colors["panel2"])], foreground=[("active", self.colors["text"])])
        style.configure("TEntry", padding=(10, 9), fieldbackground=self.colors["input"], foreground=self.colors["text"], insertcolor=self.colors["text"], bordercolor=self.colors["border"], lightcolor=self.colors["border"], darkcolor=self.colors["border"], relief="flat")
        style.map("TEntry", bordercolor=[("focus", self.colors["accent"])], lightcolor=[("focus", self.colors["accent"])], fieldbackground=[("disabled", self.colors["panel"])])
        style.configure("TCombobox", padding=(10, 8), fieldbackground=self.colors["input"], foreground=self.colors["text"], background=self.colors["panel2"], arrowcolor=self.colors["muted"], bordercolor=self.colors["border"], lightcolor=self.colors["border"], darkcolor=self.colors["border"], relief="flat")
        style.map("TCombobox", fieldbackground=[("readonly", self.colors["input"]), ("focus", "#14233b")], foreground=[("readonly", self.colors["text"]), ("disabled", "#64758e")], background=[("readonly", self.colors["panel2"]), ("active", self.colors["surface"])], arrowcolor=[("active", self.colors["accent"]), ("disabled", "#64758e")], bordercolor=[("focus", self.colors["accent"])], lightcolor=[("focus", self.colors["accent"])])
        self.option_add("*TCombobox*Listbox.background", self.colors["input"])
        self.option_add("*TCombobox*Listbox.foreground", self.colors["text"])
        self.option_add("*TCombobox*Listbox.selectBackground", self.colors["accent"])
        self.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
        style.configure("Horizontal.TProgressbar", troughcolor=self.colors["input"], background=self.colors["accent"], bordercolor=self.colors["border"], lightcolor=self.colors["accent"], darkcolor=self.colors["accent"], thickness=9)
        style.configure("Vertical.TScrollbar", background=self.colors["panel2"], troughcolor=self.colors["bg"], arrowcolor=self.colors["muted"], bordercolor=self.colors["bg"], relief="flat", arrowsize=12)
        style.map("Vertical.TScrollbar", background=[("active", self.colors["accent"])])
        style.configure("Horizontal.TScrollbar", background=self.colors["panel2"], troughcolor=self.colors["bg"], arrowcolor=self.colors["muted"], bordercolor=self.colors["bg"], relief="flat", arrowsize=12)
        style.map("Horizontal.TScrollbar", background=[("active", self.colors["accent"])])
        style.configure("TMenubutton", padding=(10, 8), font=("Segoe UI", 9, "bold"),
                        background=self.colors["panel2"], foreground=self.colors["text"],
                        borderwidth=1, bordercolor=self.colors["border"], relief="flat")
        style.map("TMenubutton",
                  background=[("active", self.colors["accent"]), ("disabled", self.colors["panel"])],
                  foreground=[("active", "#ffffff"), ("disabled", "#64758e")],
                  bordercolor=[("active", self.colors["accent"])])
        style.configure("TNotebook", background=self.colors["bg"], borderwidth=0, tabmargins=(3, 5, 3, 0))
        style.configure("TNotebook.Tab", background=self.colors["panel"], foreground=self.colors["muted"], padding=(14, 9), font=("Segoe UI", 9, "bold"), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", self.colors["accent"]), ("active", self.colors["panel2"])], foreground=[("selected", "#ffffff"), ("active", self.colors["text"])])
        style.configure("Treeview", background=self.colors["input"], fieldbackground=self.colors["input"], foreground=self.colors["text"], rowheight=36, borderwidth=0, font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=self.colors["panel2"], foreground="#a9caff", font=("Segoe UI", 9, "bold"), relief="flat", padding=(10, 9))
        style.map("Treeview", background=[("selected", self.colors["accent"])], foreground=[("selected", "#ffffff")])
        style.configure("TCheckbutton", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 9), padding=(2, 4))
        style.map("TCheckbutton", background=[("active", self.colors["panel"])], foreground=[("disabled", "#64758e")])
        style.configure("TRadiobutton", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 9), padding=(2, 4))
        style.map("TRadiobutton", background=[("active", self.colors["panel"])], foreground=[("disabled", "#64758e")])
        style.configure("TSeparator", background=self.colors["border"])
        style.configure("Status.TLabel", background=self.colors["surface"], foreground=self.colors["muted"], padding=(10, 6), font=("Segoe UI", 9))
    def _draw_brand_gradient(self, _event=None):
        """Draw a lightweight electric-blue gradient rail using native Tk Canvas."""
        canvas = getattr(self, "brand_gradient_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        width = max(1, canvas.winfo_width())
        height = max(2, canvas.winfo_height())
        canvas.delete("brand-gradient")
        # Periodic cyan → blue → violet → cyan gradient.
        stops = ((0.0, (20, 205, 255)), (0.38, (40, 117, 255)),
                 (0.72, (111, 66, 255)), (1.0, (20, 205, 255)))
        segments = max(60, min(240, width // 5))
        phase = float(getattr(self, "_brand_gradient_phase", 0.0))
        for index in range(segments):
            t = ((index / max(1, segments - 1)) + phase) % 1.0
            left_stop, right_stop = stops[0], stops[-1]
            for j in range(len(stops) - 1):
                if stops[j][0] <= t <= stops[j + 1][0]:
                    left_stop, right_stop = stops[j], stops[j + 1]
                    break
            span = right_stop[0] - left_stop[0] or 1.0
            ratio = (t - left_stop[0]) / span
            rgb = tuple(round(left_stop[1][k] + (right_stop[1][k] - left_stop[1][k]) * ratio)
                        for k in range(3))
            color = "#%02x%02x%02x" % rgb
            x0 = int(index * width / segments)
            x1 = int((index + 1) * width / segments) + 1
            canvas.create_rectangle(x0, 0, x1, height, fill=color, outline="", tags="brand-gradient")

    def _animate_brand_gradient(self, step=0):
        """Run a brief startup shimmer; keep the interface still during normal work."""
        if not self.winfo_exists():
            return
        self._brand_gradient_phase = (step / 18.0) % 1.0
        self._draw_brand_gradient()
        if step < 18:
            self.after(75, lambda: self._animate_brand_gradient(step + 1))

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        shell = tk.Frame(self, bg=self.colors["bg"])
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_rowconfigure(2, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        top = tk.Frame(shell, bg="#0b1424", padx=18, pady=10,
                       highlightthickness=1, highlightbackground=self.colors["border"])
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        brand = tk.Frame(top, bg="#0b1424")
        brand.grid(row=0, column=0, sticky="w")
        tk.Label(brand, text="MARC", bg="#0b1424", fg="#eaf1fc",
                 font=("Segoe UI", 22, "bold")).pack(side="left")
        tk.Label(brand, text=" / VIDEO STUDIO", bg="#0b1424", fg="#3478f6",
                 font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(brand, text="   ESTUDIO CREATIVO IA", bg="#0b1424", fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(12, 0), pady=(7, 0))
        head_right = tk.Frame(top, bg="#0b1424")
        head_right.grid(row=0, column=1, sticky="e")
        self.ai_badge = tk.Label(head_right, text="● IA LOCAL · COMPROBANDO",
                                 bg="#0b1424", fg=self.colors["warning"], font=("Segoe UI", 9, "bold"))
        self.ai_badge.pack(side="left", padx=(0, 14))
        self.ffmpeg_badge = tk.Label(head_right, text="● FFMPEG · COMPROBANDO",
                                     bg="#0b1424", fg=self.colors["muted"], font=("Segoe UI", 9, "bold"))
        self.ffmpeg_badge.pack(side="left", padx=(0, 12))
        self.header_diagnose_button = ttk.Button(head_right, text="Diagnóstico PC", command=self.detect_pc_async)
        self.header_diagnose_button.pack(side="left", padx=(0, 6))
        self.header_tools_button = ttk.Menubutton(head_right, text="Ayuda y herramientas  ▾")
        self.header_tools_menu = tk.Menu(
            self.header_tools_button, tearoff=0,
            bg=self.colors["panel"], fg=self.colors["text"],
            activebackground=self.colors["accent"], activeforeground="#ffffff",
            bd=0, relief="flat",
        )
        self.header_tools_menu.add_command(label="Diagnóstico del equipo", command=self.detect_pc_async)
        self.header_tools_menu.add_command(label="Herramientas instaladas", command=self.check_tools)
        self.header_tools_menu.add_command(label="Acceso remoto", command=self.show_remote_access)
        self.header_tools_menu.add_command(label="Estado de producción", command=self.show_pipeline_status)
        self.header_tools_button.configure(menu=self.header_tools_menu)
        self.header_tools_button.pack(side="left")

        self.brand_gradient_canvas = tk.Canvas(
            shell, height=3, bg=self.colors["bg"], highlightthickness=0, bd=0
        )
        self.brand_gradient_canvas.grid(row=1, column=0, sticky="ew")
        self.brand_gradient_canvas.bind("<Configure>", self._draw_brand_gradient)
        self._brand_gradient_phase = 0.0

        workspace = tk.PanedWindow(shell, orient="horizontal", sashwidth=10, sashrelief="raised",
                                   bg=self.colors["bg"], bd=0, opaqueresize=True, showhandle=False)
        workspace.grid(row=2, column=0, sticky="nsew", padx=12, pady=12)
        self.workspace_panes = workspace

        library = tk.Frame(workspace, bg=self.colors["panel"], width=165,
                           highlightthickness=1, highlightbackground=self.colors["border"])
        library.grid_rowconfigure(3, weight=1)
        library.grid_columnconfigure(0, weight=1)
        workspace.add(library, minsize=125, width=165, stretch="never")
        self.project_library_pane = library
        self.project_library_visible = True
        tk.Label(library, text="▣  BIBLIOTECA", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=13, pady=(14, 2))
        tk.Label(library, text="Proyectos y guiones", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w").grid(row=1, column=0, sticky="ew", padx=13, pady=(0, 8))
        self.project_search_var = tk.StringVar(value="Buscar proyectos...")
        search_entry = ttk.Entry(library, textvariable=self.project_search_var, style="TEntry")
        search_entry.grid(row=2, column=0, sticky="ew", padx=9, pady=(0, 8))
        self.project_list = tk.Listbox(library, bg=self.colors["input"], fg=self.colors["text"],
                                       selectbackground=self.colors["accent"], selectforeground="#fff",
                                       borderwidth=0, highlightthickness=1,
                                       highlightbackground=self.colors["border"],
                                       font=("Segoe UI", 9), activestyle="none")
        self.project_list.grid(row=3, column=0, sticky="nsew", padx=8)
        self.project_list.bind("<<ListboxSelect>>", self.load_selected)
        self.project_search_var.trace_add("write", lambda *_args: self.refresh_projects())
        def clear_project_search(_event=None):
            if self.project_search_var.get() == "Buscar proyectos...":
                self.project_search_var.set("")
        def restore_project_search(_event=None):
            if not self.project_search_var.get().strip():
                self.project_search_var.set("Buscar proyectos...")
        search_entry.bind("<FocusIn>", clear_project_search)
        search_entry.bind("<FocusOut>", restore_project_search)
        lib_buttons = tk.Frame(library, bg=self.colors["panel"], padx=8, pady=8)
        lib_buttons.grid(row=4, column=0, sticky="ew")
        self.new_project_button = ttk.Button(lib_buttons, text="+ Nuevo proyecto", style="Accent.TButton",
                                              command=self.new_project)
        self.new_project_button.pack(fill="x", pady=(0, 6))
        self.delete_button = ttk.Button(lib_buttons, text="Eliminar proyecto", command=self.delete_project)
        self.delete_button.pack(fill="x")
        self.continue_series_button = ttk.Button(lib_buttons, text="↗ Continuar historia", command=self.create_continuation)
        self.continue_series_button.pack(fill="x", pady=(6, 0))

        editor = tk.Frame(workspace, bg=self.colors["bg"])
        workspace.add(editor, minsize=650, stretch="always")
        self.editor_pane = editor
        editor.grid_rowconfigure(0, weight=1)
        editor.grid_columnconfigure(0, weight=1)

        vertical = tk.PanedWindow(editor, orient="horizontal", sashwidth=10, sashrelief="raised",
                                  bg=self.colors["bg"], bd=0, opaqueresize=True, showhandle=False)
        vertical.grid(row=0, column=0, sticky="nsew")
        self.vertical_panes = vertical

        controls_area = tk.Frame(vertical, bg=self.colors["bg"])
        self.controls_area = controls_area
        vertical.add(controls_area, minsize=235, width=280, stretch="never")
        controls_area.grid_rowconfigure(0, weight=1)
        controls_area.grid_columnconfigure(0, weight=1)
        self.config_canvas = tk.Canvas(controls_area, bg=self.colors["bg"], highlightthickness=0, borderwidth=0)
        self.config_canvas.grid(row=0, column=0, sticky="nsew")
        config_scroll = ttk.Scrollbar(controls_area, orient="vertical", command=self.config_canvas.yview)
        config_scroll.grid(row=0, column=1, sticky="ns")
        self.config_canvas.configure(yscrollcommand=config_scroll.set)
        # Scroll the compact configuration rail with the mouse wheel.
        def _scroll_config(event):
            # Route wheel movement only to the panel beneath the pointer.
            try:
                direction = -1 if getattr(event, "delta", 0) > 0 or getattr(event, "num", None) == 4 else 1
                x, y = event.x_root, event.y_root
                config = self.config_canvas
                cx, cy = config.winfo_rootx(), config.winfo_rooty()
                if config.winfo_ismapped() and cx <= x < cx + config.winfo_width() and cy <= y < cy + config.winfo_height():
                    config.yview_scroll(direction, "units")
                    return "break"
                audio = getattr(self, "audio_canvas", None)
                if audio is not None and audio.winfo_ismapped():
                    ax, ay = audio.winfo_rootx(), audio.winfo_rooty()
                    if ax <= x < ax + audio.winfo_width() and ay <= y < ay + audio.winfo_height():
                        audio.yview_scroll(direction, "units")
                        return "break"
            except (tk.TclError, AttributeError, TypeError):
                pass
            return None
        self.config_canvas.bind_all("<MouseWheel>", _scroll_config, add="+")
        self.config_canvas.bind_all("<Button-4>", _scroll_config, add="+")
        self.config_canvas.bind_all("<Button-5>", _scroll_config, add="+")
        card = tk.Frame(self.config_canvas, bg=self.colors["panel"], padx=12, pady=12,
                        highlightthickness=1, highlightbackground=self.colors["border"])
        self.config_canvas_window = self.config_canvas.create_window((0, 0), window=card, anchor="nw")
        card.bind("<Configure>", lambda _event: self.config_canvas.configure(scrollregion=self.config_canvas.bbox("all")))
        self.config_canvas.bind("<Configure>", lambda event: self.config_canvas.itemconfigure(self.config_canvas_window, width=event.width))
        tk.Label(card, text="Crea tu historia", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 15, "bold")).pack(anchor="w")
        tk.Label(
            card,
            text="Empieza con un nombre y una idea sencilla. Ej.: «Una familia descubre un secreto». MARC te guiará paso a paso.",
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
            justify="left", wraplength=260,
        ).pack(anchor="w", pady=(5, 10))

        self.title_var = tk.StringVar()
        self.topic_var = tk.StringVar()
        self.platform_var = tk.StringVar(value=list(PLATFORMS)[0])
        self.duration_var = tk.StringVar(value="10")
        self.style_var = tk.StringVar(value="Reencarnación y venganza")
        self.protagonist_var = tk.StringVar()
        self.conflict_var = tk.StringVar()
        self.tone_var = tk.StringVar(value="Dramático e intenso")
        self.narrator_var = tk.StringVar(value="Tercera persona")
        self.ending_var = tk.StringVar(value="Justicia y superación")
        self.drawing_style_var = tk.StringVar(value="Anime cinematográfico")
        self.animation_style_var = tk.StringVar(value="2D fluida")
        self.animation_intensity_var = tk.StringVar(value="Muy animado")
        self.overlay_mode_var = tk.StringVar(value="Título de escena")
        self.transition_style_var = tk.StringVar(value="Fundido suave")
        self.subtitle_font_var = tk.StringVar(value="Arial")
        self.subtitle_size_var = tk.StringVar(value="Mediano")
        self.subtitle_color_var = tk.StringVar(value="Blanco")
        self.subtitle_position_var = tk.StringVar(value="Inferior")
        self.subtitle_outline_var = tk.BooleanVar(value=True)
        self.video_mode_var = tk.StringVar(value=SERIES_VIDEO_MODE)
        self.resolution_var = tk.StringVar(value="1080p (Full HD)")
        self.fps_var = tk.StringVar(value="30")

        form = tk.Frame(card, bg=self.colors["panel"])
        form.pack(fill="x", expand=True)
        self.form_widgets = []
        self.field_cells = {}
        form.columnconfigure(0, weight=1)

        self.title_var = tk.StringVar()
        self.topic_var = tk.StringVar()
        self.platform_var = tk.StringVar(value=list(PLATFORMS)[0])
        self.duration_var = tk.StringVar(value="10")
        self.style_var = tk.StringVar(value="Reencarnación y venganza")
        self.protagonist_var = tk.StringVar()
        self.conflict_var = tk.StringVar()
        self.tone_var = tk.StringVar(value="Dramático e intenso")
        self.narrator_var = tk.StringVar(value="Tercera persona")
        self.ending_var = tk.StringVar(value="Justicia y superación")
        self.drawing_style_var = tk.StringVar(value="Anime cinematográfico")
        self.animation_style_var = tk.StringVar(value="2D fluida")
        self.animation_intensity_var = tk.StringVar(value="Muy animado")
        self.overlay_mode_var = tk.StringVar(value="Título de escena")
        self.transition_style_var = tk.StringVar(value="Fundido suave")
        self.subtitle_font_var = tk.StringVar(value="Arial")
        self.subtitle_size_var = tk.StringVar(value="Mediano")
        self.subtitle_color_var = tk.StringVar(value="Blanco")
        self.subtitle_position_var = tk.StringVar(value="Inferior")
        self.subtitle_outline_var = tk.BooleanVar(value=True)
        self.video_mode_var = tk.StringVar(value=SERIES_VIDEO_MODE)
        self.resolution_var = tk.StringVar(value="1080p (Full HD)")
        self.fps_var = tk.StringVar(value="30")

        # Basic fields are full-width so their labels and selected values stay readable.
        self._field(form, "Nombre del proyecto", self.title_var, 0, 0)
        self._field(form, "Género", self.style_var, 1, 0,
                    values=["Novela dramática", "Reencarnación y venganza", "Superación personal", "Romance",
                            "Fantasía", "Misterio y suspenso", "Terror", "Acción y aventura", "Ciencia ficción",
                            "Drama familiar", "Educativo y directo", "Documental", "Promocional"])
        self._field(form, "Plataforma", self.platform_var, 2, 0, values=list(PLATFORMS))
        self.duration_field = self._field(form, "Duración (min)", self.duration_var, 3, 0,
                    values=[str(i) for i in (1, 2, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120)])
        self._field(form, "Premisa / idea", self.topic_var, 4, 0)

        advanced_form = tk.Frame(card, bg=self.colors["panel"])
        advanced_form.pack(fill="x", expand=True, pady=(2, 0))
        advanced_form.columnconfigure(0, weight=1)
        self._field(advanced_form, "Tono", self.tone_var, 0, 0,
                    values=["Dramático e intenso", "Oscuro y misterioso", "Emotivo", "Inspirador",
                            "Épico", "Ligero y humorístico", "Realista"])
        self._field(advanced_form, "Narrador", self.narrator_var, 1, 0,
                    values=["Tercera persona", "Primera persona protagonista", "Primera persona retrospectiva",
                            "Narrador omnisciente"])
        self._field(advanced_form, "Desenlace", self.ending_var, 2, 0,
                    values=["Justicia y superación", "Final feliz", "Final trágico", "Giro inesperado",
                            "Abierto para continuación", "Agridulce"])
        self._field(advanced_form, "Protagonista", self.protagonist_var, 3, 0)
        self._field(advanced_form, "Conflicto central", self.conflict_var, 4, 0)
        self.video_mode_field = self._field(advanced_form, "Modo de producción", self.video_mode_var, 5, 0,
                    values=[SHORT_VIDEO_MODE, SERIES_VIDEO_MODE])
        self.video_mode_field.bind("<<ComboboxSelected>>", lambda _event: self._on_video_mode_changed())
        self.advanced_help_label = tk.Label(
            advanced_form, text="Las opciones avanzadas permiten afinar el tono, el narrador y la estructura.",
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 8),
            justify="left", wraplength=250,
        )
        self.advanced_help_label.grid(row=6, column=0, sticky="w", padx=5, pady=(5, 2))
        self.story_options_expanded = False
        self.story_options_button = ttk.Button(
            card, text="＋ Más opciones (opcional)", command=self.toggle_story_options
        )
        self.story_options_button.pack(fill="x", padx=4, pady=(8, 2))
        self._set_story_options_expanded(False)

        lower = tk.Frame(vertical, bg=self.colors["bg"])
        self.lower_panel = lower
        vertical.add(lower, minsize=520, stretch="always")
        lower.grid_rowconfigure(2, weight=1)
        lower.grid_columnconfigure(0, weight=1)

        # Actions are intentionally split into two compact rows so they remain
        # reachable on 1024px-wide screens instead of disappearing off-screen.
        toolrow = tk.Frame(lower, bg=self.colors["bg"])
        toolrow.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        toolrow.grid_columnconfigure(0, weight=1)
        self.toolrow = toolrow

        primary_actions = tk.Frame(
            toolrow, bg=self.colors["panel"], padx=8, pady=6,
            highlightthickness=1, highlightbackground=self.colors["border"]
        )
        primary_actions.grid(row=0, column=0, sticky="ew")
        self.primary_actions = primary_actions
        primary_actions.grid_columnconfigure(4, weight=1)
        self.generate_button = ttk.Button(primary_actions, text="✦ Generar guion", style="Accent.TButton",
                                          command=self.generate_script)
        self.generate_button.grid(row=0, column=0, sticky="w")
        self.save_button = ttk.Button(primary_actions, text="Guardar", command=self.save_project)
        self.save_button.grid(row=0, column=1, sticky="w", padx=(6, 0))
        self.approve_button = ttk.Button(primary_actions, text="Aprobar", command=self.approve_script)
        self.approve_button.grid(row=0, column=2, sticky="w", padx=(6, 0))
        self.export_button = ttk.Button(primary_actions, text="Exportar MP4", command=self.export_video)
        self.export_button.grid(row=0, column=3, sticky="w", padx=(6, 0))
        self.import_package_top_button = ttk.Button(
            primary_actions, text="Importar guion + imágenes", style="Accent.TButton",
            command=self.import_production_package
        )
        self.import_package_top_button.grid(row=0, column=4, sticky="e", padx=(8, 0))
        self.configuration_visible = True
        self.config_toggle_button = ttk.Button(
            primary_actions, text="⚙ Ajustes −", command=self.toggle_configuration)
        self.config_toggle_button.grid(row=0, column=5, sticky="e", padx=(8, 0))

        self.secondary_actions = tk.Frame(toolrow, bg=self.colors["bg"])
        self.secondary_actions.grid(row=1, column=0, sticky="ew", pady=(5, 0))
        secondary_actions = self.secondary_actions
        self.cancel_button = ttk.Button(
            secondary_actions, text="Cancelar guion", command=self.cancel_generation, state="disabled"
        )
        self.cancel_button.pack(side="left")
        self.preview_render_button = ttk.Button(
            secondary_actions, text="Vista previa MP4", command=self.preview_video_render
        )
        self.preview_render_button.pack(side="left", padx=(6, 0))
        self.image_setup_button = ttk.Button(
            secondary_actions, text="✦ Configurar imágenes IA", style="Accent.TButton",
            command=self.open_image_setup
        )
        self.image_setup_button.pack(side="left", padx=(6, 0))
        self.cancel_render_button = ttk.Button(
            secondary_actions, text="Cancelar render", command=self.cancel_export, state="disabled"
        )
        self.cancel_render_button.pack(side="left", padx=(6, 0))

        statuscard = tk.Frame(lower, bg=self.colors["panel"], padx=10, pady=6,
                              highlightthickness=1, highlightbackground=self.colors["border"])
        statuscard.grid(row=1, column=0, sticky="ew", pady=(0, 7))
        status_head = tk.Frame(statuscard, bg=self.colors["panel"])
        status_head.pack(fill="x")
        self.progress_label_var = tk.StringVar(value="Listo para crear el guion")
        tk.Label(status_head, textvariable=self.progress_label_var, bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 9, "bold")).pack(side="left", anchor="w")
        tk.Label(statuscard, text="Configura tu historia y genera un guion con IA.",
                 bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8)).pack(anchor="w", pady=(0, 2))
        self.details_visible = False
        self.details_button = ttk.Button(status_head, text="＋ Diagnóstico y estimaciones",
                                         command=self.toggle_status_details)
        self.details_button.pack(side="right")
        self.remote_access_button = ttk.Button(
            status_head, text="Acceso remoto", command=self.show_remote_access
        )
        self.remote_access_button.pack(side="right", padx=(0, 6))
        self.progressbar = ttk.Progressbar(statuscard, mode="determinate", maximum=100, value=0)
        self.progressbar.pack(fill="x", pady=(2, 1))
        self.progress_detail_var = tk.StringVar(value="0% · En espera")
        tk.Label(statuscard, textvariable=self.progress_detail_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 8)).pack(anchor="w")
        workflow_row = tk.Frame(statuscard, bg=self.colors["panel"])
        workflow_row.pack(fill="x", pady=(4, 0))
        self.workflow_hint_var = tk.StringVar(
            value="Paso 1 de 6 · Crea el guion y revísalo antes de continuar."
        )
        tk.Label(
            workflow_row, textvariable=self.workflow_hint_var, bg=self.colors["panel"],
            fg="#a9caff", font=("Segoe UI", 9, "bold"), anchor="w"
        ).pack(side="left", fill="x", expand=True)
        self.workflow_next_button = ttk.Button(
            workflow_row, text="Ir al siguiente paso  →",
            style="Accent.TButton", command=self.go_to_next_step
        )
        self.workflow_next_button.pack(side="right", padx=(8, 0))
        self.details_frame = tk.Frame(statuscard, bg=self.colors["panel"])
        self.pc_summary_var = tk.StringVar(value="Detectando equipo…")
        tk.Label(self.details_frame, textvariable=self.pc_summary_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 9), justify="left",
                 wraplength=1250).pack(anchor="w", pady=(8, 0))
        self.estimate_var = tk.StringVar(value="Calculando estimación de producción…")
        tk.Label(self.details_frame, textvariable=self.estimate_var, bg=self.colors["panel"],
                 fg=self.colors["success"], font=("Segoe UI", 9, "bold"), justify="left",
                 wraplength=1250).pack(anchor="w", pady=(4, 0))

        # Full-width studio tabs: the GUION tab is a two-column workspace,
        # with the editor on the left and preview/timeline on the right.
        studio_tabs = ttk.Notebook(lower)
        studio_tabs.grid(row=2, column=0, sticky="nsew")
        self.studio_tabs = studio_tabs
        self.workflow_steps = [
            ("Guion", "Importa tu guion ya escrito o revísalo antes del montaje."),
            ("Escenas", "Comprueba el texto y las indicaciones por escena."),
            ("Imágenes", "Importa todas tus imágenes en un solo lote y revisa sus miniaturas."),
            ("Montaje", "MARC enlaza las escenas, movimiento de cámara, voces, audio y transiciones."),
            ("Vista previa", "Reproduce el resultado y revísalo antes de exportar."),
            ("Audio", "Comprueba la voz local, la música importada y los niveles."),
        ]
        self.studio_tabs.bind("<<NotebookTabChanged>>", self.update_workflow_guide)

        script_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=8, pady=8)
        self.script_tab = script_tab
        studio_tabs.add(script_tab, text="1. Guion")
        script_tab.grid_columnconfigure(0, weight=4, uniform="scriptworkspace")
        script_tab.grid_columnconfigure(1, weight=3, uniform="scriptworkspace")
        script_tab.grid_rowconfigure(0, weight=3)
        script_tab.grid_rowconfigure(1, weight=2)

        script_editor_frame = tk.Frame(
            script_tab, bg=self.colors["panel"], padx=8, pady=8,
            highlightthickness=1, highlightbackground=self.colors["border"]
        )
        script_editor_frame.grid(row=0, column=0, rowspan=2, sticky="nsew", padx=(0, 6))
        script_editor_frame.grid_rowconfigure(1, weight=1)
        script_editor_frame.grid_columnconfigure(0, weight=1)
        self.script_editor_frame = script_editor_frame

        # Persistent monitor in the main workspace; it stays visible while switching tabs.
        preview_dock = tk.Frame(script_tab, bg=self.colors["panel"], padx=9, pady=7,
                                highlightthickness=1, highlightbackground=self.colors["border"])
        preview_dock.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        self.preview_dock = preview_dock
        preview_dock.grid_columnconfigure(0, weight=3, uniform="monitor")
        preview_dock.grid_rowconfigure(1, weight=1)
        preview_dock.grid_columnconfigure(1, weight=2, uniform="monitor")
        monitor_header = tk.Frame(preview_dock, bg=self.colors["panel"])
        monitor_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        tk.Label(monitor_header, text="MONITOR / STORYBOARD", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(side="left")
        self.preview_scene_var = tk.StringVar(value="SIN ESCENAS")
        tk.Label(monitor_header, textvariable=self.preview_scene_var, bg=self.colors["panel"],
                 fg="#70a7ff", font=("Segoe UI", 8, "bold")).pack(side="right")
        monitor = tk.Frame(preview_dock, bg="#070c16", highlightthickness=1,
                           highlightbackground=self.colors["border"])
        monitor.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        monitor.grid_columnconfigure(0, weight=1)
        monitor.grid_rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(monitor, bg="#070c16", highlightthickness=0,
                                        height=178, width=460)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self._render_preview_frame())
        self.preview_video_host = tk.Frame(monitor, bg="#070c16", borderwidth=0, highlightthickness=0)
        self.preview_video_host.grid(row=0, column=0, sticky="nsew")
        self.preview_video_host.grid_remove()
        scene_inspector = tk.Frame(preview_dock, bg=self.colors["input"], padx=10, pady=8,
                                   highlightthickness=1, highlightbackground=self.colors["border"])
        scene_inspector.grid(row=1, column=1, sticky="nsew")
        tk.Label(scene_inspector, text="ESCENA ACTUAL", bg=self.colors["input"],
                 fg="#70a7ff", font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.preview_scene_title_var = tk.StringVar(value="Genera un guion")
        tk.Label(scene_inspector, textvariable=self.preview_scene_title_var, bg=self.colors["input"],
                 fg=self.colors["text"], font=("Segoe UI", 11, "bold"),
                 wraplength=260, justify="left").pack(anchor="w", pady=(7, 5))
        self.preview_scene_text_var = tk.StringVar(value="Al seleccionar una escena aparecerán aquí su resumen y referencia visual.")
        tk.Label(scene_inspector, textvariable=self.preview_scene_text_var, bg=self.colors["input"],
                 fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=260,
                 justify="left", anchor="nw").pack(fill="both", expand=True)
        inspector_actions = tk.Frame(scene_inspector, bg=self.colors["input"])
        inspector_actions.pack(fill="x", pady=(8, 0))
        self.inspector_assign_image_button = ttk.Button(
            inspector_actions, text="＋ Imagen", command=self.assign_scene_image)
        self.inspector_assign_image_button.pack(side="left", fill="x", expand=True)
        self.inspector_generate_image_button = ttk.Button(
            inspector_actions, text="✦ IA", command=self.generate_scene_image)
        self.inspector_generate_image_button.pack(side="left", fill="x", expand=True, padx=(4, 0))
        self.inspector_duration_button = ttk.Button(
            scene_inspector, text="Editar duración…", command=self._edit_timeline_duration)
        self.inspector_duration_button.pack(fill="x", pady=(5, 0))
        monitor_actions = tk.Frame(preview_dock, bg=self.colors["panel"])
        monitor_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Button(monitor_actions, text="◀ Escena", command=lambda: self._step_preview_scene(-1)).pack(side="left")
        ttk.Button(monitor_actions, text="Escena ▶", command=lambda: self._step_preview_scene(1)).pack(side="left", padx=(5, 8))
        self.preview_play_button = ttk.Button(monitor_actions, text="▶ Reproducir", style="Accent.TButton",
                                              command=self.play_preview_video)
        self.preview_play_button.pack(side="left")
        self.preview_pause_button = ttk.Button(monitor_actions, text="Ⅱ Pausar",
                                               command=self.pause_preview_video)
        self.preview_pause_button.pack(side="left", padx=(4, 0))
        self.preview_stop_button = ttk.Button(monitor_actions, text="■ Detener",
                                              command=self.stop_preview_video)
        self.preview_stop_button.pack(side="left", padx=(4, 0))
        ttk.Button(monitor_actions, text="Abrir externo",
                   command=self.open_last_video).pack(side="right")
        ttk.Button(monitor_actions, text="Elegir MP4",
                   command=self.choose_preview_video).pack(side="right", padx=(0, 5))
        self.preview_seek_var = tk.DoubleVar(value=0)
        seek_row = tk.Frame(preview_dock, bg=self.colors["panel"])
        seek_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        self.preview_seek_scale = ttk.Scale(seek_row, from_=0, to=1000, variable=self.preview_seek_var,
                                           command=self._seek_preview_video)
        self.preview_seek_scale.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.preview_seek_scale.bind("<ButtonPress-1>", lambda _event: setattr(self, "_seeking_preview", True))
        self.preview_seek_scale.bind("<ButtonRelease-1>", lambda _event: setattr(self, "_seeking_preview", False))
        self.preview_time_var = tk.StringVar(value="00:00 / 00:00")
        tk.Label(seek_row, textvariable=self.preview_time_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Consolas", 8)).pack(side="right")
        self.preview_playback_status_var = tk.StringVar(value="Storyboard listo · selecciona una escena o elige un MP4")
        tk.Label(preview_dock, textvariable=self.preview_playback_status_var,
                 bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8), anchor="w").grid(row=4, column=0, columnspan=2, sticky="ew", pady=(3, 0))

        script_tab.grid_rowconfigure(1, weight=1)
        script_tab.grid_columnconfigure(0, weight=1)
        script_head = tk.Frame(script_editor_frame, bg=self.colors["panel"])
        script_head.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        tk.Label(script_head, text="EDITOR DE GUION", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        self.script_approve_button = ttk.Button(
            script_head, text="Aprobar guion", style="Accent.TButton", command=self.approve_script
        )
        self.script_approve_button.pack(side="right", padx=(8, 0))
        tk.Label(script_head, text="Revisa el texto antes de continuar", bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 9)).pack(side="right")
        textframe = tk.Frame(script_editor_frame, bg=self.colors["input"])
        self.script_text_frame = textframe
        textframe.grid(row=1, column=0, sticky="nsew")
        textframe.grid_rowconfigure(0, weight=1)
        textframe.grid_columnconfigure(0, weight=1)
        self.script_text = tk.Text(textframe, wrap="word", undo=True, bg=self.colors["input"],
                                   fg=self.colors["text"], insertbackground="#ffffff",
                                   selectbackground=self.colors["accent"], font=("Segoe UI", 10),
                                   relief="flat", padx=14, pady=12, highlightthickness=0,
                                   spacing1=2, spacing3=5)
        self.script_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(textframe, orient="vertical", command=self.script_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.script_text.configure(yscrollcommand=scrollbar.set)

        scenes_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=14, pady=12)
        self.scenes_tab = scenes_tab
        studio_tabs.add(scenes_tab, text="2. Escenas")
        scenes_tab.grid_columnconfigure(0, weight=3, uniform="scene_visual_workspace")
        scenes_tab.grid_columnconfigure(1, weight=2, uniform="scene_visual_workspace", minsize=280)
        scenes_tab.grid_rowconfigure(6, weight=1)
        tk.Label(scenes_tab, text="PLAN DE MONTAJE", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 12, "bold")).grid(row=0, column=0, columnspan=2, sticky="w")
        tk.Label(scenes_tab, text="Tu flujo: guion por escenas + indicaciones de movimiento + lote de imágenes ya creadas. MARC se encarga del movimiento de cámara, voz local, audio disponible, transiciones y MP4.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1200, justify="left").grid(row=1, column=0, columnspan=2, sticky="w", pady=(4, 6))
        self.scene_summary_var = tk.StringVar(value="0 planos · 0 palabras · planos ≤5 s")
        scene_summary_card = tk.Frame(
            scenes_tab, bg=self.colors["surface"], padx=12, pady=9,
            highlightbackground=self.colors["border"], highlightthickness=1
        )
        scene_summary_card.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(0, 10))
        tk.Frame(scene_summary_card, bg=self.colors["accent"], width=3).pack(side="left", fill="y", padx=(0, 10))
        tk.Label(
            scene_summary_card, textvariable=self.scene_summary_var, bg=self.colors["surface"],
            fg="#a9caff", font=("Segoe UI Semibold", 9), anchor="w", justify="left", wraplength=1000
        ).pack(side="left", fill="x", expand=True)

        scene_actions = tk.Frame(scenes_tab, bg=self.colors["panel"])
        scene_actions.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        self.import_package_button = ttk.Button(
            scene_actions, text="Importar paquete (guion + dirección + imágenes)",
            style="Accent.TButton", command=self.import_production_package
        )
        self.import_package_button.pack(side="left")
        self.assign_image_button = ttk.Button(scene_actions, text="Añadir imagen propia", command=self.assign_scene_image)
        self.assign_image_button.pack(side="left", padx=(6, 0))
        self.clear_image_button = ttk.Button(scene_actions, text="Quitar imagen", command=self.clear_scene_image)
        self.clear_image_button.pack(side="left", padx=(6, 0))
        self.refresh_scenes_button = ttk.Button(scene_actions, text="Actualizar escenas",
                                                command=lambda: self._refresh_scene_outline(self.script_text.get("1.0", "end-1c")))
        self.refresh_scenes_button.pack(side="left", padx=(6, 0))
        self.toggle_image_ai_button = ttk.Button(
            scene_actions, text="Generación IA opcional ▸", command=self.toggle_image_ai_tools
        )
        self.toggle_image_ai_button.pack(side="right", padx=(8, 0))
        image_ai_bar = tk.Frame(scenes_tab, bg=self.colors["panel"])
        image_ai_bar.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 8))
        self.image_ai_bar = image_ai_bar
        model_row = tk.Frame(image_ai_bar, bg=self.colors["panel"])
        model_row.pack(fill="x", pady=(0, 6))
        tk.Label(model_row, text="MODELO LOCAL", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 7))
        self.image_model_var = tk.StringVar(value="")
        self.image_model_combo = ttk.Combobox(model_row, textvariable=self.image_model_var,
                                              values=[], state="readonly", width=32, font=("Segoe UI", 9))
        self.image_model_combo.pack(side="left")
        self.image_model_combo.bind("<<ComboboxSelected>>", lambda _event: self.update_image_model_guidance())
        self.detect_models_button = ttk.Button(model_row, text="Detectar motor",
                                                command=self.detect_image_models)
        self.detect_models_button.pack(side="left", padx=(6, 0))
        self.start_comfyui_button = ttk.Button(
            model_row, text="Iniciar / instalar", command=self.start_comfyui
        )
        self.start_comfyui_button.pack(side="left", padx=(6, 0))
        upscale_row = tk.Frame(image_ai_bar, bg=self.colors["panel"])
        upscale_row.pack(fill="x", pady=(0, 6))
        tk.Label(upscale_row, text="MEJORA IA (OPCIONAL)", bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 7))
        self.image_upscale_var = tk.StringVar(value="(Sin mejora)")
        self.image_upscale_combo = ttk.Combobox(
            upscale_row, textvariable=self.image_upscale_var,
            values=["(Sin mejora)"], state="readonly", width=30, font=("Segoe UI", 9)
        )
        self.image_upscale_combo.pack(side="left")
        tk.Label(upscale_row, text="Aumenta resolución; puede tardar más.",
                 bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8)).pack(side="left", padx=(8, 0))
        tk.Label(
            image_ai_bar,
            text="Para activarlo: instala un modelo ESRGAN gratuito en ComfyUI/models/upscale_models y pulsa «Detectar motor».",
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 8),
            anchor="w", justify="left", wraplength=1000
        ).pack(fill="x", anchor="w", pady=(0, 6))
        image_action_row = tk.Frame(image_ai_bar, bg=self.colors["panel"])
        image_action_row.pack(fill="x")
        self.generate_image_button = ttk.Button(image_action_row, text="Generar imagen de esta escena",
                                                style="Accent.TButton", command=self.generate_scene_image)
        self.generate_image_button.pack(side="left")
        self.generate_missing_images_button = ttk.Button(
            image_action_row, text="Generar imágenes que faltan", command=self.generate_missing_scene_images)
        self.generate_missing_images_button.pack(side="left", padx=(6, 0))
        self.image_ai_status_var = tk.StringVar(value="Motor visual local · comprobando ComfyUI y checkpoints…")
        self.image_ai_status_label = tk.Label(
            scenes_tab, textvariable=self.image_ai_status_var, bg=self.colors["panel"],
            fg=self.colors["muted"], font=("Segoe UI", 8), anchor="w",
            wraplength=1000, justify="left"
        )
        self.image_ai_status_label.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(0, 7))
        self.image_ai_tools_visible = False
        image_ai_bar.grid_remove()
        self.image_ai_status_label.grid_remove()

        scene_body = tk.Frame(scenes_tab, bg=self.colors["input"], padx=8, pady=8)
        scene_body.grid(row=6, column=0, sticky="nsew", padx=(0, 6))
        scene_body.grid_columnconfigure(0, weight=1)
        scene_body.grid_rowconfigure(0, weight=1)
        columns = ("number", "title", "words", "duration", "visual")
        self.scene_outline = ttk.Treeview(scene_body, columns=columns, show="headings",
                                          selectmode="browse", height=8)
        for key, heading in (("number", "#"), ("title", "ESCENA"), ("words", "PALABRAS"),
                             ("duration", "DURACIÓN"), ("visual", "RECURSO VISUAL")):
            self.scene_outline.heading(key, text=heading)
        self.scene_outline.column("number", width=42, minwidth=38, anchor="center", stretch=False)
        self.scene_outline.column("title", width=260, minwidth=130, anchor="w", stretch=True)
        self.scene_outline.column("words", width=82, minwidth=70, anchor="e", stretch=False)
        self.scene_outline.column("duration", width=84, minwidth=70, anchor="center", stretch=False)
        self.scene_outline.column("visual", width=190, minwidth=120, anchor="w", stretch=True)
        self.scene_outline.grid(row=0, column=0, sticky="nsew")
        scene_scroll = ttk.Scrollbar(scene_body, orient="vertical", command=self.scene_outline.yview)
        scene_scroll.grid(row=0, column=1, sticky="ns")
        self.scene_outline.configure(yscrollcommand=scene_scroll.set)
        self.scene_outline.bind("<Double-1>", lambda _event: self.assign_scene_image())
        self.scene_outline.bind("<<TreeviewSelect>>", self._timeline_scene_selected)

        scene_visual_panel = tk.Frame(
            scenes_tab, bg=self.colors["panel"], padx=12, pady=12,
            highlightthickness=1, highlightbackground=self.colors["border"]
        )
        scene_visual_panel.grid(row=6, column=1, sticky="nsew", padx=(6, 0))
        scene_visual_panel.grid_columnconfigure(0, weight=1)
        tk.Label(scene_visual_panel, text="IMAGEN DE LA ESCENA",
                 bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).grid(row=0, column=0, sticky="w")
        self.scene_artwork_canvas = tk.Canvas(
            scene_visual_panel, bg="#070c16", height=210, width=320,
            highlightthickness=1, highlightbackground=self.colors["border"]
        )
        self.scene_artwork_canvas.grid(row=1, column=0, sticky="ew", pady=(8, 6))
        self.scene_visual_caption_var = tk.StringVar(value="Importa tu lote para visualizar las imágenes.")
        tk.Label(scene_visual_panel, textvariable=self.scene_visual_caption_var,
                 bg=self.colors["panel"], fg="#a9caff", font=("Segoe UI", 9, "bold"),
                 wraplength=330, justify="left").grid(row=2, column=0, sticky="ew", pady=(0, 8))
        tk.Label(scene_visual_panel, text="MOVIMIENTO / DIRECCIÓN",
                 bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).grid(row=3, column=0, sticky="w")
        self.scene_visual_direction_var = tk.StringVar(value="Automático: movimiento de cámara y transición.")
        tk.Label(scene_visual_panel, textvariable=self.scene_visual_direction_var,
                 bg=self.colors["input"], fg=self.colors["text"], padx=8, pady=8,
                 wraplength=330, justify="left", anchor="nw").grid(row=4, column=0, sticky="ew", pady=(4, 8))
        tk.Label(scene_visual_panel, text="DIÁLOGO / TEXTO DE LA ESCENA",
                 bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).grid(row=5, column=0, sticky="w")
        self.scene_visual_dialogue_var = tk.StringVar(value="Al seleccionar una escena aparecerá aquí su texto.")
        tk.Label(scene_visual_panel, textvariable=self.scene_visual_dialogue_var,
                 bg=self.colors["panel"], fg=self.colors["muted"], padx=8, pady=8,
                 wraplength=330, justify="left", anchor="nw").grid(row=6, column=0, sticky="ew", pady=(4, 8))
        scene_visual_actions = tk.Frame(scene_visual_panel, bg=self.colors["panel"])
        scene_visual_actions.grid(row=7, column=0, sticky="ew")
        ttk.Button(scene_visual_actions, text="＋ Asignar / reemplazar",
                   command=self.assign_scene_image).pack(side="left", fill="x", expand=True)
        ttk.Button(scene_visual_actions, text="Ver monitor",
                   command=self.show_selected_scene_in_monitor).pack(side="left", fill="x", expand=True, padx=(6, 0))
        tk.Label(scenes_tab, text="Importa el guion por escenas, las indicaciones de movimiento y todas tus imágenes. MARC genera la voz local si falta una narración y monta el MP4. La animación de personajes mediante IA es opcional y requiere un modelo de vídeo compatible.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1200, justify="left").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 0))

        visual_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=18, pady=16)
        studio_tabs.add(visual_tab, text="3. Imágenes")
        visual_tab.grid_columnconfigure(0, weight=1)
        tk.Label(visual_tab, text="DIRECCIÓN VISUAL DEL PROYECTO",
                 bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 14, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(visual_tab,
                 text="Ajusta el lenguaje visual aquí sin tener que volver al formulario completo.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 10),
                 wraplength=1050, justify="left").grid(row=1, column=0, sticky="w", pady=(5, 14))
        visual_form = tk.Frame(visual_tab, bg=self.colors["panel"])
        visual_form.grid(row=2, column=0, sticky="new")
        visual_form.columnconfigure(0, weight=1, uniform="visual")
        visual_form.columnconfigure(1, weight=1, uniform="visual")
        self._field(visual_form, "Estilo de dibujo", self.drawing_style_var, 0, 0,
                    values=["Anime cinematográfico", "Manga en blanco y negro", "Cartoon occidental",
                            "Cómic realista", "Acuarela ilustrada", "Pixel art", "3D estilizado",
                            "Realismo cinematográfico"])
        self._field(visual_form, "Estilo de animación", self.animation_style_var, 0, 1,
                    values=["2D fluida", "Anime con movimientos dinámicos", "Motion comic",
                            "Cut-out / recortes", "3D cinematográfica", "Stop motion",
                            "Pixel animation", "Presentación animada"])
        self._field(visual_form, "Resolución de salida", self.resolution_var, 1, 0,
                    values=list(RESOLUTION_PROFILES))
        self._field(visual_form, "Fotogramas por segundo", self.fps_var, 1, 1,
                    values=list(FPS_OPTIONS))
        self._field(visual_form, "Intensidad de movimiento", self.animation_intensity_var, 2, 0,
                    values=["Suave", "Normal", "Muy animado"])
        self._field(visual_form, "Texto sobre las imágenes", self.overlay_mode_var, 2, 1,
                    values=["Título de escena", "Subtítulo narrativo", "Sin texto"])
        self._field(visual_form, "Transición entre escenas", self.transition_style_var, 3, 0,
                    values=["Corte directo", "Fundido suave", "Deslizar izquierda",
                            "Deslizar derecha", "Barrido izquierda", "Barrido derecha",
                            "Zoom cinematográfico"])
        self._field(visual_form, "Fuente de subtítulos", self.subtitle_font_var, 4, 0,
                    values=["Arial", "Segoe UI", "Verdana", "Georgia", "Impact"])
        self._field(visual_form, "Tamaño de subtítulos", self.subtitle_size_var, 4, 1,
                    values=["Pequeño", "Mediano", "Grande"])
        self._field(visual_form, "Color de subtítulos", self.subtitle_color_var, 5, 0,
                    values=["Blanco", "Amarillo", "Cian"])
        self._field(visual_form, "Posición de subtítulos", self.subtitle_position_var, 5, 1,
                    values=["Inferior", "Centro"])
        self.subtitle_outline_checkbutton = tk.Checkbutton(
            visual_form, text="Contorno negro y sombra para mejorar la lectura",
            variable=self.subtitle_outline_var, bg=self.colors["panel"], fg=self.colors["text"],
            activebackground=self.colors["panel"], activeforeground=self.colors["text"],
            selectcolor=self.colors["input"], font=("Segoe UI", 9)
        )
        self.subtitle_outline_checkbutton.grid(row=6, column=0, columnspan=2, sticky="w", pady=(7, 0))
        self.visual_advanced_labels = (
            "Estilo de animación", "Fotogramas por segundo", "Intensidad de movimiento",
            "Texto sobre las imágenes", "Transición entre escenas", "Fuente de subtítulos",
            "Tamaño de subtítulos", "Color de subtítulos", "Posición de subtítulos",
        )
        self.visual_advanced_expanded = False
        for field_label in self.visual_advanced_labels:
            self.field_cells[field_label].grid_remove()
        self.subtitle_outline_checkbutton.grid_remove()
        self.visual_advanced_button = ttk.Button(
            visual_tab, text="＋ Mostrar ajustes visuales avanzados",
            command=self.toggle_visual_options
        )
        self.visual_advanced_button.grid(row=3, column=0, sticky="w", pady=(8, 2))
        tk.Label(visual_tab, text="Los valores predeterminados sirven para empezar. Abre los ajustes avanzados cuando necesites personalizar la animación o los subtítulos.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").grid(row=7, column=0, sticky="w", pady=(12, 0))
        canon_actions = tk.Frame(visual_tab, bg=self.colors["panel"])
        canon_actions.grid(row=8, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(canon_actions, text="📖 Biblia de la historia y continuidad",
                   style="Accent.TButton", command=self.edit_story_bible).pack(side="left")
        tk.Label(canon_actions,
                 text="Revisa y corrige personajes, relaciones, escenarios y el punto exacto desde donde debe continuar la serie.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=760, justify="left").pack(side="left", padx=(12, 0))

        timeline_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=12, pady=10)
        studio_tabs.add(timeline_tab, text="4. Montaje")
        timeline_tab.grid_columnconfigure(0, weight=1)
        timeline_tab.grid_rowconfigure(2, weight=1)
        timeline_head = tk.Frame(timeline_tab, bg=self.colors["panel"])
        timeline_head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(timeline_head, text="LÍNEA DE TIEMPO", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 12, "bold")).pack(side="left")
        self.timeline_time_var = tk.StringVar(value="00:00 / 10:00")
        tk.Label(timeline_head, textvariable=self.timeline_time_var, bg=self.colors["panel"],
                 fg="#70a7ff", font=("Consolas", 10, "bold")).pack(side="right")
        timeline_tools = tk.Frame(timeline_tab, bg=self.colors["panel"])
        timeline_tools.grid(row=1, column=0, sticky="ew", pady=(0, 8))
        ttk.Button(timeline_tools, text="◀ Escena", command=lambda: self._step_timeline_scene(-1)).pack(side="left")
        ttk.Button(timeline_tools, text="Escena ▶", command=lambda: self._step_timeline_scene(1)).pack(side="left", padx=(5, 8))
        ttk.Button(timeline_tools, text="Mover clip ◀", command=lambda: self._move_timeline_scene(-1)).pack(side="left", padx=(0, 4))
        ttk.Button(timeline_tools, text="Mover clip ▶", command=lambda: self._move_timeline_scene(1)).pack(side="left", padx=(0, 8))
        ttk.Button(timeline_tools, text="Duración…", command=self._edit_timeline_duration).pack(side="left", padx=(0, 8))
        ttk.Button(timeline_tools, text="＋ Imagen", command=self.assign_scene_image).pack(side="left")
        ttk.Button(timeline_tools, text="＋ Voz", command=self.select_audio_track).pack(side="left", padx=(5, 0))
        ttk.Button(timeline_tools, text="＋ Música", command=self.select_music_track).pack(side="left", padx=(5, 0))
        tk.Label(timeline_tools, text="Zoom", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(side="left", padx=(18, 5))
        self.timeline_zoom_var = tk.DoubleVar(value=2.0)
        self.timeline_zoom_scale = ttk.Scale(timeline_tools, from_=1.0, to=4.0,
                                             variable=self.timeline_zoom_var,
                                             command=lambda _value: self._draw_timeline())
        self.timeline_zoom_scale.pack(side="left", fill="x", expand=True, padx=(0, 10))
        timeline_shell = tk.Frame(timeline_tab, bg="#0b1120",
                                  highlightthickness=1, highlightbackground=self.colors["border"])
        timeline_shell.grid(row=2, column=0, sticky="nsew")
        timeline_shell.grid_rowconfigure(0, weight=1)
        timeline_shell.grid_columnconfigure(0, weight=1)
        self.timeline_canvas = tk.Canvas(timeline_shell, bg="#0b1120", height=245,
                                        highlightthickness=0, borderwidth=0)
        self.timeline_canvas.grid(row=0, column=0, sticky="nsew")
        timeline_xscroll = ttk.Scrollbar(timeline_shell, orient="horizontal",
                                         command=self.timeline_canvas.xview)
        timeline_xscroll.grid(row=1, column=0, sticky="ew")
        self.timeline_canvas.configure(xscrollcommand=timeline_xscroll.set)
        self.timeline_canvas.bind("<Button-1>", self._timeline_click)
        self.timeline_canvas.bind("<B1-Motion>", self._timeline_drag)
        self.timeline_canvas.bind("<Double-Button-1>", self._timeline_double_click)
        tk.Label(timeline_tab,
                 text="Selecciona un clip para sincronizarlo con la escena. Haz clic o arrastra en la regla para mover el cabezal; usa los botones para asignar imágenes y pistas. El cabezal es de navegación visual, no una reproducción de vídeo en tiempo real.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 8),
                 wraplength=1100, justify="left").grid(row=3, column=0, sticky="ew", pady=(7, 0))

        preview_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=18, pady=16)
        self.preview_tab = preview_tab
        studio_tabs.add(preview_tab, text="5. Vista previa")
        preview_tab.grid_columnconfigure(0, weight=1)
        preview_tab.grid_rowconfigure(1, weight=1)
        preview_head = tk.Frame(preview_tab, bg=self.colors["panel"])
        preview_head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(preview_head, text="MONITOR DE VÍDEO", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(preview_head, textvariable=self.preview_scene_var, bg=self.colors["panel"],
                 fg="#70a7ff", font=("Segoe UI", 9, "bold")).pack(side="right")
        monitor = tk.Frame(preview_tab, bg="#070c16", highlightthickness=1,
                           highlightbackground=self.colors["border"])
        monitor.grid(row=1, column=0, sticky="nsew")
        monitor.grid_columnconfigure(0, weight=1)
        monitor.grid_rowconfigure(0, weight=1)
        self.preview_tab_canvas = tk.Canvas(monitor, bg="#070c16", highlightthickness=0,
                                            height=300, width=800)
        self.preview_tab_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_tab_canvas.bind("<Configure>", lambda _event: self._render_preview_frame())
        preview_transport = tk.Frame(preview_tab, bg=self.colors["panel"])
        preview_transport.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        ttk.Button(preview_transport, text="◀ Escena anterior",
                   command=lambda: self._step_preview_scene(-1)).pack(side="left")
        ttk.Button(preview_transport, text="Siguiente escena ▶",
                   command=lambda: self._step_preview_scene(1)).pack(side="left", padx=(6, 0))
        ttk.Button(preview_transport, text="Abrir último MP4", style="Accent.TButton",
                   command=self.open_last_video).pack(side="right")
        ttk.Button(preview_transport, text="Elegir MP4",
                   command=self.choose_preview_video).pack(side="right", padx=(0, 6))
        ttk.Button(preview_transport, text="Exportar MP4", style="Accent.TButton",
                   command=self.export_video).pack(side="right", padx=(0, 6))
        self.preview_status_var = tk.StringVar(value="El monitor muestra el storyboard de la escena seleccionada. Exporta para crear el MP4 final.")
        tk.Label(preview_tab, textvariable=self.preview_status_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1100, justify="left").grid(row=3, column=0, sticky="ew", pady=(10, 0))
        audio_tab = tk.Frame(studio_tabs, bg=self.colors["panel"])
        studio_tabs.add(audio_tab, text="6. Audio")
        audio_tab.grid_rowconfigure(0, weight=1)
        audio_tab.grid_columnconfigure(0, weight=1)
        self.audio_canvas = tk.Canvas(audio_tab, bg=self.colors["panel"], highlightthickness=0, bd=0)
        self.audio_canvas.grid(row=0, column=0, sticky="nsew")
        self.audio_scrollbar = ttk.Scrollbar(audio_tab, orient="vertical", command=self.audio_canvas.yview)
        self.audio_scrollbar.grid(row=0, column=1, sticky="ns")
        self.audio_canvas.configure(yscrollcommand=self.audio_scrollbar.set)
        audio_content = tk.Frame(self.audio_canvas, bg=self.colors["panel"], padx=16, pady=14)
        self.audio_content = audio_content
        audio_window = self.audio_canvas.create_window((0, 0), window=audio_content, anchor="nw")
        audio_content.bind(
            "<Configure>", lambda _event: self.audio_canvas.configure(scrollregion=self.audio_canvas.bbox("all"))
        )
        self.audio_canvas.bind(
            "<Configure>", lambda event: self.audio_canvas.itemconfigure(audio_window, width=event.width)
        )
        self.audio_canvas.bind(
            "<MouseWheel>",
            lambda event: (self.audio_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"), "break")[1]
        )
        audio_content.grid_columnconfigure(0, weight=1)
        audio_content.grid_rowconfigure(6, weight=1)
        tk.Label(audio_content, text="NARRACIÓN Y SONIDO", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(audio_content, text="Importa una pista de voz/música o genera narración sin conexión usando las voces de Windows que ya estén instaladas.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").grid(row=1, column=0, sticky="w", pady=(4, 14))

        track_card = tk.Frame(audio_content, bg=self.colors["input"], padx=13, pady=12,
                              highlightthickness=1, highlightbackground=self.colors["border"])
        track_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        tk.Label(track_card, text="NARRACIÓN / VOZ", bg=self.colors["input"], fg="#70a7ff",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.audio_track_label_var = tk.StringVar(value="Sin pista de narración")
        tk.Label(track_card, textvariable=self.audio_track_label_var, bg=self.colors["input"],
                 fg=self.colors["text"], font=("Segoe UI", 9), anchor="w",
                 wraplength=1000, justify="left").pack(fill="x", pady=(4, 7))
        track_actions = tk.Frame(track_card, bg=self.colors["input"])
        track_actions.pack(fill="x", pady=(0, 10))
        self.select_audio_button = ttk.Button(track_actions, text="Importar narración", style="Accent.TButton",
                                              command=self.select_audio_track)
        self.select_audio_button.pack(side="left")
        self.clear_audio_button = ttk.Button(track_actions, text="Quitar narración", command=self.clear_audio_track)
        self.clear_audio_button.pack(side="left", padx=(8, 0))
        tk.Frame(track_card, bg=self.colors["border"], height=1).pack(fill="x", pady=(0, 10))
        tk.Label(track_card, text="MÚSICA DE FONDO", bg=self.colors["input"], fg="#70a7ff",
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.music_track_label_var = tk.StringVar(value="Sin música de fondo")
        tk.Label(track_card, textvariable=self.music_track_label_var, bg=self.colors["input"],
                 fg=self.colors["text"], font=("Segoe UI", 9), anchor="w",
                 wraplength=1000, justify="left").pack(fill="x", pady=(4, 7))
        music_actions = tk.Frame(track_card, bg=self.colors["input"])
        music_actions.pack(fill="x")
        self.select_music_button = ttk.Button(music_actions, text="Importar música", command=self.select_music_track)
        self.select_music_button.pack(side="left")
        self.clear_music_button = ttk.Button(music_actions, text="Quitar música", command=self.clear_music_track)
        self.clear_music_button.pack(side="left", padx=(8, 0))
        self.loop_music_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            music_actions, text="Repetir música si es más corta que el vídeo",
            variable=self.loop_music_var, bg=self.colors["input"], fg=self.colors["text"],
            activebackground=self.colors["input"], activeforeground=self.colors["text"],
            selectcolor=self.colors["panel"], font=("Segoe UI", 9)
        ).pack(side="left", padx=(16, 0))

        voice_card = tk.Frame(audio_content, bg=self.colors["panel"], padx=13, pady=12,
                              highlightthickness=1, highlightbackground=self.colors["border"])
        voice_card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        tk.Label(voice_card, text="GENERAR NARRACIÓN LOCAL", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(voice_card, text="La opción Windows usa voces instaladas. Kokoro es un motor neuronal local opcional: permite más voces, diálogo por personaje y prosodia emocional si el servidor está conectado.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").pack(anchor="w", pady=(3, 10))
        voice_engine_row = tk.Frame(voice_card, bg=self.colors["panel"])
        voice_engine_row.pack(fill="x", pady=(0, 7))
        tk.Label(voice_engine_row, text="MOTOR", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 7))
        self.voice_engine_var = tk.StringVar(value="Windows (básica)")
        self.voice_engine_combo = ttk.Combobox(
            voice_engine_row, textvariable=self.voice_engine_var,
            values=["Windows (básica)", "Kokoro (neuronal local)"],
            state="readonly", width=25, font=("Segoe UI", 9)
        )
        self.voice_engine_combo.pack(side="left")
        self.voice_engine_combo.bind("<<ComboboxSelected>>", self.on_voice_engine_changed)
        self.voice_select_row = tk.Frame(voice_card, bg=self.colors["panel"])
        voice_select_row = self.voice_select_row
        voice_select_row.pack(fill="x", pady=(0, 7))
        tk.Label(voice_select_row, text="VOZ", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 7))
        self.voice_var = tk.StringVar(value="(Automática)")
        self.voice_combo = ttk.Combobox(voice_select_row, textvariable=self.voice_var,
                                        values=["(Automática)"], state="readonly", width=35, font=("Segoe UI", 9))
        self.voice_combo.pack(side="left")
        self.detect_voice_button = ttk.Button(voice_select_row, text="Detectar voces", command=self.detect_local_voices)
        self.detect_voice_button.pack(side="left", padx=(7, 0))
        self.add_voices_button = ttk.Button(voice_select_row, text="Añadir voces de Windows", command=self.configure_voice_engine)
        self.add_voices_button.pack(side="left", padx=(7, 0))
        voice_action_row = tk.Frame(voice_card, bg=self.colors["panel"])
        voice_action_row.pack(fill="x")
        self.assign_character_voices_button = ttk.Button(
            voice_action_row, text="Voces por personaje", command=self.edit_character_voices)
        self.assign_character_voices_button.pack(side="left")
        self.generate_voice_button = ttk.Button(voice_action_row, text="Generar narración", style="Accent.TButton",
                                                command=self.generate_local_voice)
        self.generate_voice_button.pack(side="left", padx=(7, 0))
        self.cancel_voice_button = ttk.Button(voice_action_row, text="Cancelar voz", command=self.cancel_local_voice, state="disabled")
        self.cancel_voice_button.pack(side="left", padx=(7, 0))
        self.voice_status_var = tk.StringVar(value="Detectando voces locales de Windows…")
        tk.Label(audio_content, textvariable=self.voice_status_var, bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w", wraplength=1050, justify="left").grid(row=4, column=0, sticky="ew", pady=(0, 10))
        subtitle_actions = tk.Frame(audio_content, bg=self.colors["panel"])
        subtitle_actions.grid(row=5, column=0, sticky="ew", pady=(4, 9))
        self.export_srt_button = ttk.Button(
            subtitle_actions, text="Exportar subtítulos SRT", style="Accent.TButton",
            command=self.export_subtitles
        )
        self.export_srt_button.pack(side="left")
        tk.Label(subtitle_actions, text="Ajusta los tiempos al MP4 final; la sincronía por palabra sigue siendo aproximada.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        tk.Label(audio_content, text="Para voces en español, instala un paquete de voz en Configuración de Windows → Hora e idioma → Voz. La voz disponible depende de Windows y del idioma instalado.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").grid(row=6, column=0, sticky="nw", pady=(2, 0))

        mux_actions = tk.Frame(audio_content, bg=self.colors["panel"])
        mux_actions.grid(row=7, column=0, sticky="ew", pady=(12, 0))
        ttk.Button(
            mux_actions, text="Añadir audio al último vídeo",
            style="Accent.TButton", command=self.add_audio_to_last_video
        ).pack(side="left")
        tk.Label(
            mux_actions,
            text="Aplica la voz y/o música al MP4 ya exportado sin volver a renderizar las escenas.",
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
            wraplength=800, justify="left"
        ).pack(side="left", padx=(10, 0))

        # Secondary overview timeline kept available in code; the full editor lives in Montage.
        mini_timeline = tk.Frame(script_tab, bg=self.colors["panel"], padx=8, pady=5,
                                 highlightthickness=1, highlightbackground=self.colors["border"])
        mini_timeline.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(5, 0))
        self.mini_timeline_panel = mini_timeline
        mini_timeline.grid_columnconfigure(0, weight=1)
        mini_head = tk.Frame(mini_timeline, bg=self.colors["panel"])
        mini_head.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        tk.Label(mini_head, text="SECUENCIA / TIMELINE", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 8, "bold")).pack(side="left")
        self.mini_time_var = tk.StringVar(value="00:00 / 10:00")
        tk.Label(mini_head, textvariable=self.mini_time_var, bg=self.colors["panel"],
                 fg="#70a7ff", font=("Consolas", 8, "bold")).pack(side="right")
        mini_shell = tk.Frame(mini_timeline, bg="#0b1120")
        mini_shell.grid(row=1, column=0, sticky="ew")
        mini_shell.grid_columnconfigure(0, weight=1)
        self.mini_timeline_canvas = tk.Canvas(mini_shell, bg="#0b1120", height=76,
                                             highlightthickness=0, borderwidth=0)
        self.mini_timeline_canvas.grid(row=0, column=0, sticky="ew")
        mini_xscroll = ttk.Scrollbar(mini_shell, orient="horizontal",
                                    command=self.mini_timeline_canvas.xview)
        mini_xscroll.grid(row=1, column=0, sticky="ew")
        self.mini_timeline_canvas.configure(xscrollcommand=mini_xscroll.set)
        self.mini_timeline_canvas.bind("<Button-1>", self._mini_timeline_click)
        self.mini_timeline_canvas.bind("<Configure>", lambda _event: self._draw_mini_timeline())

        self.status_var = tk.StringVar(value="Listo. Configura la historia, genera el guion y revisa las escenas.")
        self.after(250, lambda: studio_tabs.select(script_tab))
        self.after(280, self.update_workflow_guide)
        self.after(300, self._draw_timeline)
        tk.Label(lower, textvariable=self.status_var, bg=self.colors["bg"], fg=self.colors["muted"],
                 font=("Segoe UI", 8), anchor="w").grid(row=3, column=0, sticky="ew", pady=(3, 0))
        self._apply_compact_workspace()
        self.after(120, self._set_responsive_initial_sashes)
        self.after(90, lambda: self._animate_brand_gradient(0))

    def update_workflow_guide(self, _event=None):
        """Keep the guidance strip aligned with the currently selected production step."""
        tabs = getattr(self, "studio_tabs", None)
        steps = getattr(self, "workflow_steps", ())
        if tabs is None or not steps:
            return
        try:
            index = tabs.index(tabs.select())
        except (tk.TclError, ValueError):
            index = 0
        index = max(0, min(index, len(steps) - 1))
        _name, hint = steps[index]
        self.workflow_hint_var.set(f"Paso {index + 1} de {len(steps)} · {hint}")
        if index == len(steps) - 1:
            label = "Volver al guion  ↶"
        else:
            next_name = steps[index + 1][0]
            label = f"Siguiente: {next_name}  →"
        self.workflow_next_button.configure(text=label)

    def go_to_next_step(self):
        """Guide novices through the workflow without silently launching expensive jobs."""
        tabs = getattr(self, "studio_tabs", None)
        if tabs is None:
            return
        try:
            current = tabs.index(tabs.select())
        except (tk.TclError, ValueError):
            current = 0

        # Do not send a beginner to an empty scenes page or let them skip approval.
        if current == 0:
            script = self.script_text.get("1.0", "end-1c").strip()
            if not script:
                messagebox.showinfo(
                    "Primero crea el guion",
                    "Completa el nombre del proyecto y la premisa, pulsa «Crear guion» y espera a que aparezca el texto."
                )
                return
            if not self._existing_approval():
                messagebox.showinfo(
                    "Revisa y aprueba el guion",
                    "Lee el guion y pulsa «Aprobar guion» en el encabezado del editor antes de continuar a Escenas."
                )
                return

        last = len(getattr(self, "workflow_steps", ())) - 1
        if current < last:
            tabs.select(current + 1)
        else:
            # The final guide button promises to return to the beginning.
            tabs.select(0)
        self.update_workflow_guide()

    def _set_responsive_initial_sashes(self):
        """Set useful initial panel proportions while keeping both dividers draggable."""
        try:
            self.update_idletasks()
            if str(self.project_library_pane) in tuple(self.workspace_panes.panes()):
                self.workspace_panes.sash_place(0, 165, 0)
            editor_width = max(650, self.editor_pane.winfo_width())
            config_width = min(max(285, int(editor_width * 0.24)), max(285, editor_width - 700))
            self.vertical_panes.sash_place(0, config_width, 0)
        except (tk.TclError, AttributeError):
            return

    def _apply_compact_workspace(self):
        """Start with a focused two-panel workspace; reveal project library on demand."""
        # Restore the core panels in the intended order.
        if str(self.project_library_pane) not in tuple(self.workspace_panes.panes()):
            self.workspace_panes.add(
                self.project_library_pane, before=self.editor_pane,
                minsize=180, width=225, stretch="never"
            )
        self.workspace_panes.forget(self.project_library_pane)
        self.project_library_visible = False
        self.set_configuration_visible(True)
        # The full monitor and timeline already have dedicated tabs. Hide their
        # duplicates here so the script editor gets the entire workspace.
        self.preview_dock.grid_remove()
        if hasattr(self, "mini_timeline_panel"):
            self.mini_timeline_panel.grid_remove()
        self.script_tab.grid_columnconfigure(0, weight=1, uniform="scriptworkspace")
        self.script_tab.grid_columnconfigure(1, weight=0, uniform="scriptworkspace")
        self.script_tab.grid_rowconfigure(0, weight=1)
        self.script_tab.grid_rowconfigure(1, weight=0)
        self.script_editor_frame.grid_configure(row=0, column=0, rowspan=1, padx=0)

        # Keep the existing widgets and callbacks, but replace the crowded
        # legacy toolbar with a responsive container whose children all use pack.
        for widget in (
            self.generate_button, self.save_button, self.approve_button,
            self.export_button, self.config_toggle_button,
        ):
            widget.grid_remove()
        for widget in (
            self.cancel_button, self.preview_render_button, self.image_setup_button,
            self.cancel_render_button,
        ):
            widget.pack_forget()
        self.header_diagnose_button.pack_forget()
        self.ai_badge.pack_forget()
        self.ffmpeg_badge.pack_forget()
        self.header_tools_button.pack(side="left")

        if hasattr(self, "compact_toolbar"):
            self.compact_toolbar.destroy()
        self.compact_toolbar = tk.Frame(
            self.primary_actions, bg=self.colors["panel"], padx=3, pady=2
        )
        self.compact_toolbar.grid(row=0, column=0, columnspan=8, sticky="ew")
        self.primary_actions.grid_columnconfigure(0, weight=1)
        self.compact_toolbar.grid_columnconfigure(2, weight=1)

        self.toolbar_new_button = ttk.Button(
            self.compact_toolbar, text="＋ Nuevo", command=self.new_project
        )
        self.toolbar_new_button.pack(side="left", padx=(0, 6))
        self.toolbar_config_button = ttk.Button(
            self.compact_toolbar, text="Ocultar formulario", command=self.toggle_configuration
        )
        self.toolbar_config_button.pack(side="left", padx=(0, 6))
        self.toolbar_generate_button = ttk.Button(
            self.compact_toolbar, text="1 · Crear guion", style="Accent.TButton",
            command=self.generate_script
        )
        self.toolbar_generate_button.pack(side="left", padx=(0, 6))
        self.toolbar_save_button = ttk.Button(
            self.compact_toolbar, text="Guardar", command=self.save_project
        )
        self.toolbar_save_button.pack(side="left", padx=(0, 6))
        self.toolbar_approve_button = ttk.Button(
            self.compact_toolbar, text="2 · Aprobar guion", command=self.approve_script
        )
        self.toolbar_approve_button.pack(side="left", padx=(0, 6))
        self.toolbar_export_button = ttk.Button(
            self.compact_toolbar, text="5 · Crear vídeo", command=self.export_video
        )
        self.toolbar_export_button.pack(side="left", padx=(0, 6))

        # Keep the form toggle visible alongside the primary action.
        self.toolbar_config_button.pack(side="left", padx=(0, 6))
        for button in (self.toolbar_save_button, self.toolbar_approve_button, self.toolbar_export_button):
            button.pack_forget()

        # Redirect state updates to the visible controls. The original widgets
        # remain hidden in their legacy frame, but progress callbacks must affect
        # the buttons the user can actually click.
        self.config_toggle_button = self.toolbar_config_button
        self.generate_button = self.toolbar_generate_button
        self.save_button = self.toolbar_save_button
        self.approve_button = self.toolbar_approve_button
        self.export_button = self.toolbar_export_button

        self.more_button = ttk.Menubutton(self.compact_toolbar, text="Más opciones  ▾")
        self.more_menu = tk.Menu(
            self.more_button, tearoff=0,
            bg=self.colors["panel"], fg=self.colors["text"],
            activebackground=self.colors["accent"], activeforeground="#ffffff",
            bd=0, relief="flat",
        )
        self.more_menu.add_command(label="Guardar proyecto", command=self.save_project)
        self.more_menu.add_command(label="Aprobar guion", command=self.approve_script)
        self.more_menu.add_command(label="Crear vídeo final", command=self.export_video)
        self.more_menu.add_command(label="Mostrar / ocultar ajustes", command=self.toggle_configuration)
        self.more_menu.add_command(label="Mostrar / ocultar proyectos guardados", command=self.toggle_project_library)
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Vista previa MP4", command=self.preview_video_render)
        self.more_menu.add_command(label="Configurar imágenes IA", command=self.open_image_setup)
        self.more_menu.add_command(label="Abrir menú Herramientas", command=lambda: self.header_tools_button.event_generate("<Button-1>"))
        self.more_menu.add_command(label="Continuar historia", command=self.create_continuation)
        self.more_menu.add_command(label="Estado / reanudar producción", command=self.show_pipeline_status)
        self.more_menu.add_separator()
        self.more_menu.add_command(label="Cancelar generación", command=self.cancel_generation)
        self.more_menu.add_command(label="Cancelar render", command=self.cancel_export)
        self.more_button.configure(menu=self.more_menu)
        self.more_button.pack(side="right")

        # Slightly increase visual hierarchy and keep the timeline attached to
        # the preview rather than leaving a large empty gap under the editor.
        self.preview_dock.configure(padx=10, pady=9)
        self.mini_timeline_panel.configure(padx=9, pady=7)
        self.script_tab.grid_columnconfigure(0, weight=1, uniform="scriptworkspace")
        self.script_tab.grid_columnconfigure(1, weight=0, uniform="scriptworkspace")

    def toggle_project_library(self):
        """Show or hide the saved-project library without shrinking the editor all day."""
        if not hasattr(self, "workspace_panes") or not hasattr(self, "project_library_pane"):
            return
        panes = tuple(self.workspace_panes.panes())
        pane_name = str(self.project_library_pane)
        # Use explicit state as the source of truth when panes are briefly stale.
        if bool(self.project_library_visible):
            if pane_name in panes:
                self.workspace_panes.forget(self.project_library_pane)
            self.project_library_visible = False
        else:
            if pane_name not in panes:
                self.workspace_panes.add(
                    self.project_library_pane, before=self.editor_pane,
                    minsize=205, width=250, stretch="never"
                )
            self.project_library_visible = True

    def _timeline_duration_seconds(self):
        try:
            return max(60, int(self.duration_var.get() or "10") * 60)
        except (ValueError, tk.TclError):
            return 600

    def _draw_timeline(self):
        """Render a lightweight, selectable multi-track edit timeline."""
        canvas = getattr(self, "timeline_canvas", None)
        if canvas is None or not canvas.winfo_exists():
            return
        canvas.delete("all")
        zoom = max(1.0, min(4.0, float(self.timeline_zoom_var.get() if hasattr(self, "timeline_zoom_var") else 2.0)))
        total = self._timeline_duration_seconds()
        scale = zoom
        left = 116
        width = left + total * scale + 32
        height = 236
        self.timeline_scale_px = scale
        self.timeline_left_px = left
        self.timeline_canvas.configure(scrollregion=(0, 0, width, height))
        bg = "#0b1120"
        muted = self.colors["muted"]
        border = "#203651"
        canvas.create_rectangle(0, 0, width, height, fill=bg, outline=bg)
        canvas.create_rectangle(0, 0, left - 1, height, fill="#111b2e", outline="#111b2e")
        # Time ruler
        canvas.create_text(12, 16, text="TIEMPO", anchor="w", fill=muted,
                           font=("Segoe UI", 8, "bold"))
        tick = 30 if total <= 600 else 60
        for seconds in range(0, total + 1, tick):
            x = left + seconds * scale
            canvas.create_line(x, 28, x, height, fill="#263650", width=1)
            canvas.create_line(x, 24, x, 32, fill="#7f91ac", width=1)
            canvas.create_text(x + 3, 15, text=f"{seconds // 60:02d}:{seconds % 60:02d}",
                               anchor="w", fill="#a2b1c7", font=("Consolas", 8))
        lanes = [
            ("VÍDEO", 36, 82, "#3478f6"),
            ("NARRACIÓN", 91, 125, "#159d8a"),
            ("MÚSICA", 134, 168, "#8060c7"),
            ("SUBTÍTULOS", 177, 211, "#b7791f"),
        ]
        for label, y1, y2, color in lanes:
            canvas.create_rectangle(0, y1, width, y2, fill="#0c1526", outline="#263650")
            canvas.create_text(12, (y1 + y2) / 2, text=label, anchor="w",
                               fill=color, font=("Segoe UI", 8, "bold"))
        durations = allocate_scene_durations(self.scene_data, total) if self.scene_data else []
        durations = [min(5, max(1, int(self.scene_duration_overrides.get(str(i + 1), value)))) for i, value in enumerate(durations)]
        timeline_total = max(total, sum(durations)) if durations else total
        width = left + timeline_total * scale + 32
        self.timeline_canvas.configure(scrollregion=(0, 0, width, height))
        elapsed = 0
        for index, scene in enumerate(self.scene_data):
            seconds = durations[index] if index < len(durations) else 5
            x1 = left + elapsed * scale
            x2 = left + (elapsed + seconds) * scale
            asset = self.scene_assets.get(str(index + 1), "")
            has_image = bool(asset and Path(asset).is_file())
            color = "#245f91" if has_image else "#263650"
            selected = getattr(self, "timeline_selected_scene", 1) == index + 1
            canvas.create_rectangle(x1 + 1, 39, max(x1 + 5, x2 - 2), 79,
                                    fill=color, outline="#55c5ff" if selected else "#35547d",
                                    width=2 if selected else 1, tags=(f"timeline_scene_{index + 1}",))
            max_chars = max(5, int((x2 - x1 - 8) / 7))
            title = scene.get("title", f"Escena {index + 1}")
            if len(title) > max_chars:
                title = title[:max(3, max_chars - 1)] + "…"
            canvas.create_text(x1 + 6, 48, text=f"{index + 1:02d} · {title}",
                               anchor="nw", fill="#ffffff", font=("Segoe UI", 8, "bold"),
                               tags=(f"timeline_scene_{index + 1}",))
            canvas.create_text(x1 + 6, 66, text="Imagen" if has_image else "Tarjeta",
                               anchor="nw", fill="#d7e7f8", font=("Segoe UI", 7),
                               tags=(f"timeline_scene_{index + 1}",))
            # Caption blocks align to the scene cuts.
            canvas.create_rectangle(x1 + 1, 181, max(x1 + 5, x2 - 2), 207,
                                    fill="#60451d", outline="#b7791f")
            elapsed += seconds
        # Audio clips are represented by their actual imported assets; they span the
        # project target because FFmpeg mixes them against the final sequence.
        for path, y1, y2, color, label in (
            (self.audio_track_path, 96, 120, "#159d8a", "Narración local"),
            (self.music_track_path, 139, 163, "#8060c7", "Música de fondo"),
        ):
            if path and Path(path).is_file():
                canvas.create_rectangle(left + 1, y1, left + total * scale - 2, y2,
                                        fill=color, outline=color)
                canvas.create_text(left + 8, (y1 + y2) / 2, text=Path(path).name,
                                   anchor="w", fill="#ffffff", font=("Segoe UI", 8, "bold"))
            else:
                canvas.create_text(left + 8, (y1 + y2) / 2, text=f"Sin pista · {label}",
                                   anchor="w", fill="#8e9fb8", font=("Segoe UI", 8))
        playhead = max(0, min(total, int(getattr(self, "timeline_playhead_seconds", 0))))
        px = left + playhead * scale
        canvas.create_line(px, 25, px, 215, fill="#f5c451", width=2, tags=("playhead",))
        canvas.create_polygon(px - 5, 25, px + 5, 25, px, 32, fill="#f5c451", outline="#f5c451")
        canvas.xview_moveto(max(0.0, min(1.0, (px - 180) / max(1, width))))
        if hasattr(self, "timeline_time_var"):
            self.timeline_time_var.set(f"{playhead // 60:02d}:{playhead % 60:02d} / {total // 60:02d}:{total % 60:02d}")
        self._draw_mini_timeline()

    def _draw_mini_timeline(self):
        """Draw a compact scene/audio overview outside the Montage tab."""
        canvas = getattr(self, "mini_timeline_canvas", None)
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists():
                return
            canvas.delete("all")
            viewport = max(520, canvas.winfo_width())
            left = 88
            height = 86
            target_seconds = self._timeline_duration_seconds()
            durations = allocate_scene_durations(self.scene_data, target_seconds) if self.scene_data else []
            durations = [min(5, max(1, int(self.scene_duration_overrides.get(str(i + 1), value))))
                         for i, value in enumerate(durations)]
            total = max(1, sum(durations) if durations else target_seconds)
            scale = max(0.22, min(1.6, (viewport - left - 12) / total))
            positions = []
            x = left
            for i, scene in enumerate(self.scene_data):
                duration = durations[i] if i < len(durations) else 5
                clip_width = max(30, duration * scale)
                positions.append((x, x + clip_width, i + 1))
                x += clip_width
            full_width = max(viewport, x + 12)
            canvas.configure(scrollregion=(0, 0, full_width, height))
            canvas.create_rectangle(0, 0, full_width, height, fill="#0b1120", outline="#0b1120")
            canvas.create_rectangle(0, 0, left - 1, height, fill="#111b2e", outline="#111b2e")
            canvas.create_text(8, 13, text="TIEMPO", anchor="w", fill="#a2b1c7", font=("Segoe UI", 7, "bold"))
            canvas.create_text(8, 35, text="VÍDEO", anchor="w", fill="#70a7ff", font=("Segoe UI", 7, "bold"))
            canvas.create_text(8, 57, text="VOZ", anchor="w", fill="#42d5ba", font=("Segoe UI", 7, "bold"))
            canvas.create_text(8, 75, text="MÚSICA", anchor="w", fill="#b29bff", font=("Segoe UI", 7, "bold"))
            tick = 60 if total <= 1800 else 300
            for seconds in range(0, total + 1, tick):
                pos = left + seconds * scale
                canvas.create_line(pos, 20, pos, height - 1, fill="#263650")
                canvas.create_text(pos + 3, 13, text=f"{seconds//60:02d}:{seconds%60:02d}",
                                   anchor="w", fill="#8e9fb8", font=("Consolas", 7))
            if not hasattr(self, "_mini_thumb_cache"):
                self._mini_thumb_cache = {}
            try:
                from PIL import Image, ImageTk
                pillow_available = True
            except ImportError:
                pillow_available = False
            for x1, x2, number in positions:
                scene = self.scene_data[number - 1]
                asset = self.scene_assets.get(str(number), "")
                has_image = bool(asset and Path(asset).is_file())
                selected = number == getattr(self, "timeline_selected_scene", 1)
                fill = "#176e9d" if has_image else "#29384b"
                canvas.create_rectangle(x1, 24, x2 - 2, 45, fill=fill,
                                        outline="#68d3ff" if selected else "#35547d",
                                        width=2 if selected else 1, tags=(f"mini_scene_{number}",))
                label_x = x1 + 4
                if has_image and pillow_available and x2 - x1 >= 42:
                    try:
                        thumb_width = min(34, max(20, int(x2 - x1 - 8)))
                        stat = Path(asset).stat()
                        cache_key = (str(Path(asset).resolve()), stat.st_mtime_ns, thumb_width)
                        photo = self._mini_thumb_cache.get(cache_key)
                        if photo is None:
                            with Image.open(asset) as source:
                                thumb = source.convert("RGB")
                            thumb.thumbnail((thumb_width, 17), Image.Resampling.LANCZOS)
                            photo = ImageTk.PhotoImage(thumb)
                            self._mini_thumb_cache[cache_key] = photo
                        canvas.create_image(x1 + 3 + thumb_width / 2, 34, image=photo,
                                            anchor="center", tags=(f"mini_scene_{number}",))
                        label_x = x1 + thumb_width + 6
                    except (OSError, ValueError):
                        pass
                clip_label = f"{number:02d} · {scene.get('title', f'Escena {number}')}"
                available = int(x2 - label_x - 4)
                max_chars = max(3, available // 5)
                if len(clip_label) > max_chars:
                    clip_label = clip_label[:max(2, max_chars - 1)] + "…"
                if available >= 18:
                    canvas.create_text(label_x, 34, text=clip_label, anchor="w",
                                       fill="#f4f8ff", font=("Segoe UI", 7, "bold"),
                                       tags=(f"mini_scene_{number}",))
            voice_color = "#159d8a" if self.audio_track_path and Path(self.audio_track_path).is_file() else "#18263d"
            music_color = "#6a4eab" if self.music_track_path and Path(self.music_track_path).is_file() else "#18263d"
            canvas.create_rectangle(left, 49, full_width - 6, 64, fill=voice_color, outline=voice_color)
            voice_label = Path(self.audio_track_path).name if voice_color != "#18263d" else "Sin narración"
            canvas.create_text(left + 5, 56, text=voice_label, anchor="w",
                               fill="#d9fff5" if voice_color != "#18263d" else "#8e9fb8",
                               font=("Segoe UI", 7, "bold"))
            canvas.create_rectangle(left, 68, full_width - 6, 82, fill=music_color, outline=music_color)
            music_label = Path(self.music_track_path).name if music_color != "#18263d" else "Sin música"
            canvas.create_text(left + 5, 75, text=music_label, anchor="w",
                               fill="#e8ddff" if music_color != "#18263d" else "#8e9fb8",
                               font=("Segoe UI", 7, "bold"))
            playhead = max(0, int(getattr(self, "timeline_playhead_seconds", 0)))
            px = left + playhead * scale
            canvas.create_line(px, 19, px, height, fill="#f5c451", width=2, tags=("mini_playhead",))
            canvas.create_polygon(px - 4, 19, px + 4, 19, px, 25, fill="#f5c451", outline="#f5c451")
            if hasattr(self, "mini_time_var"):
                self.mini_time_var.set(
                    f"{playhead//60:02d}:{playhead%60:02d} / {target_seconds//60:02d}:{target_seconds%60:02d}"
                )
        except (tk.TclError, ValueError, OSError):
            return

    def _mini_timeline_click(self, event):
        canvas = getattr(self, "mini_timeline_canvas", None)
        if canvas is None or not self.scene_data:
            return
        x = canvas.canvasx(event.x)
        y = canvas.canvasy(event.y)
        if not (22 <= y <= 47):
            return
        viewport = max(520, canvas.winfo_width())
        left = 88
        target = self._timeline_duration_seconds()
        durations = allocate_scene_durations(self.scene_data, target)
        durations = [min(5, max(1, int(self.scene_duration_overrides.get(str(i + 1), value))))
                     for i, value in enumerate(durations)]
        elapsed = 0
        scale = max(0.22, min(1.6, (viewport - left - 12) / max(1, sum(durations))))
        for index, duration in enumerate(durations):
            clip_width = max(30, duration * scale)
            if left + elapsed <= x <= left + elapsed + clip_width:
                self.timeline_selected_scene = index + 1
                self.timeline_playhead_seconds = sum(durations[:index])
                iid = f"scene_{index + 1}"
                if iid in self.scene_outline.get_children(""):
                    self.scene_outline.selection_set(iid)
                    self.scene_outline.see(iid)
                self._draw_timeline()
                self._render_preview_frame()
                break
            elapsed += clip_width

    def _render_scene_asset_preview(self):
        """Render the selected imported image and its scene direction in the Scenes inspector."""
        canvas = getattr(self, "scene_artwork_canvas", None)
        if canvas is None:
            return
        width, height = 320, 210
        try:
            if not canvas.winfo_exists():
                return
            canvas.delete("all")
            width = max(220, canvas.winfo_width())
            height = max(150, canvas.winfo_height())
            selected = self._scene_selection_number()
            number = selected or max(1, int(getattr(self, "timeline_selected_scene", 1)))
            scenes = getattr(self, "scene_data", [])
            scene = scenes[number - 1] if 1 <= number <= len(scenes) else {}
            asset = str(getattr(self, "scene_assets", {}).get(str(number), "") or "")
            if asset and Path(asset).is_file():
                from PIL import Image, ImageTk
                with Image.open(asset) as source:
                    image = source.convert("RGB")
                image.thumbnail((width - 12, height - 12), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(image)
                self._scene_artwork_photo = photo
                canvas.create_image(width // 2, height // 2, image=photo, anchor="center")
                canvas.create_rectangle(5, 5, width - 5, height - 5, outline="#397dff", width=1)
                self.scene_visual_caption_var.set(f"Escena {number:03d} · {Path(asset).name}")
            else:
                canvas.create_rectangle(5, 5, width - 5, height - 5, fill="#0a1220", outline="#293b56")
                canvas.create_text(
                    width // 2, height // 2,
                    text="SIN IMAGEN ASIGNADA\n\nImporta el lote completo\no asigna una imagen a esta escena.",
                    fill="#aab8ce", font=("Segoe UI", 10, "bold"), justify="center",
                )
                self.scene_visual_caption_var.set(f"Escena {number:03d} · sin imagen asignada")
            direction = getattr(self, "scene_directions", {}).get(str(number), "")
            self.scene_visual_direction_var.set(
                direction or "Movimiento automático: MARC aplicará un movimiento de cámara y una transición adecuados."
            )
            spoken = re.sub(r"\s+", " ", str(scene.get("text", "") or "")).strip()
            self.scene_visual_dialogue_var.set(
                spoken[:480] + ("…" if len(spoken) > 480 else "")
                if spoken else "No hay texto asociado a esta escena."
            )
        except (OSError, ValueError, tk.TclError, ImportError, AttributeError) as exc:
            try:
                canvas.delete("all")
                canvas.create_text(width // 2, height // 2, text=f"No se pudo mostrar la imagen.\n{exc}",
                                   fill="#ff8298", justify="center")
            except tk.TclError:
                pass

    def show_selected_scene_in_monitor(self):
        """Switch to the main monitor and redraw the selected scene."""
        try:
            self.studio_tabs.select(self.script_tab)
            self._render_preview_frame()
        except (AttributeError, tk.TclError):
            pass

    def _timeline_scene_selected(self, _event=None):
        number = self._scene_selection_number()
        if number is not None:
            self.timeline_selected_scene = number
            if hasattr(self, "scene_data") and number <= len(self.scene_data):
                durations = allocate_scene_durations(self.scene_data, self._timeline_duration_seconds())
                self.timeline_playhead_seconds = sum(durations[:number - 1])
            self._draw_timeline()
            self._render_preview_frame()
            self._render_scene_asset_preview()

    def _timeline_seconds_from_event(self, event):
        canvas = self.timeline_canvas
        x = canvas.canvasx(event.x)
        left = getattr(self, "timeline_left_px", 116)
        scale = max(0.1, getattr(self, "timeline_scale_px", 2.0))
        return max(0, min(self._timeline_duration_seconds(), int((x - left) / scale)))

    def _timeline_click(self, event):
        seconds = self._timeline_seconds_from_event(event)
        self.timeline_playhead_seconds = seconds
        canvas_y = self.timeline_canvas.canvasy(event.y)
        if 36 <= canvas_y <= 82 and self.scene_data:
            durations = allocate_scene_durations(self.scene_data, self._timeline_duration_seconds())
            durations = [min(5, max(1, int(self.scene_duration_overrides.get(str(i + 1), value)))) for i, value in enumerate(durations)]
            elapsed = 0
            for index, duration in enumerate(durations):
                if elapsed <= seconds < elapsed + duration or index == len(durations) - 1:
                    self.timeline_selected_scene = index + 1
                    if hasattr(self, "scene_outline") and self.scene_outline.winfo_exists():
                        iid = f"scene_{index + 1}"
                        if iid in self.scene_outline.get_children(""):
                            self.scene_outline.selection_set(iid)
                            self.scene_outline.see(iid)
                    break
                elapsed += duration
        self._draw_timeline()
        self._render_preview_frame()

    def _timeline_drag(self, event):
        self.timeline_playhead_seconds = self._timeline_seconds_from_event(event)
        self._draw_timeline()

    def _timeline_double_click(self, event):
        y = self.timeline_canvas.canvasy(event.y)
        if 36 <= y <= 82:
            self._timeline_click(event)
            self._edit_timeline_duration()

    def _selected_timeline_scene(self):
        number = int(getattr(self, "timeline_selected_scene", 1))
        return number if 1 <= number <= len(self.scene_data) else None

    def _edit_timeline_duration(self):
        number = self._selected_timeline_scene()
        if number is None:
            messagebox.showinfo("Selecciona un clip", "Selecciona una escena en la línea de tiempo primero.")
            return
        durations = allocate_scene_durations(self.scene_data, self._timeline_duration_seconds())
        current = self.scene_duration_overrides.get(str(number), durations[number - 1])
        from tkinter import simpledialog
        value = simpledialog.askinteger(
            "Duración del clip", f"Duración de la escena {number} en segundos (1–5):",
            initialvalue=min(5, max(1, int(current))), minvalue=1, maxvalue=5, parent=self
        )
        if value is None:
            return
        self.scene_duration_overrides[str(number)] = min(5, max(1, int(value)))
        self._save_scene_assets()
        self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
        self.save_project(reset_approval=True, quiet=True)
        self.status_var.set(f"Duración de la escena {number}: {value} s. Revisa y vuelve a aprobar antes de exportar.")

    def _move_timeline_scene(self, step):
        number = self._selected_timeline_scene()
        if number is None:
            messagebox.showinfo("Selecciona un clip", "Selecciona un clip de vídeo antes de moverlo.")
            return
        target = number - 1 + step
        if not 0 <= target < len(self.scene_data):
            return
        scenes = list(self.scene_data)
        scenes[number - 1], scenes[target] = scenes[target], scenes[number - 1]
        old_assets = dict(self.scene_assets)
        old_durations = dict(self.scene_duration_overrides)
        order = list(range(1, len(scenes) + 1))
        order[number - 1], order[target] = order[target], order[number - 1]
        self.scene_assets = {str(new_index): old_assets[str(old_index)]
                             for new_index, old_index in enumerate(order, start=1)
                             if str(old_index) in old_assets}
        self.scene_duration_overrides = {str(new_index): old_durations[str(old_index)]
                                         for new_index, old_index in enumerate(order, start=1)
                                         if str(old_index) in old_durations}
        serialized = "\n\n".join(f"[{scene['title']}]\n{scene['text']}" for scene in scenes)
        self.script_text.configure(state="normal")
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", serialized)
        self._refresh_scene_outline(serialized)
        self.scene_outline.selection_set(f"scene_{target + 1}")
        self.scene_outline.see(f"scene_{target + 1}")
        self.timeline_selected_scene = target + 1
        self._save_scene_assets()
        self.save_project(reset_approval=True, quiet=True)
        self.status_var.set("Clip movido. Sus recursos siguieron a la escena; revisa y vuelve a aprobar el guion.")

    def _step_timeline_scene(self, step):
        if not self.scene_data:
            messagebox.showinfo("Sin escenas", "Genera o abre un guion para poder navegar por escenas.")
            return
        current = max(1, min(len(self.scene_data), int(getattr(self, "timeline_selected_scene", 1))))
        target = max(1, min(len(self.scene_data), current + step))
        self.timeline_selected_scene = target
        durations = allocate_scene_durations(self.scene_data, self._timeline_duration_seconds())
        self.timeline_playhead_seconds = sum(durations[:target - 1])
        iid = f"scene_{target}"
        if iid in self.scene_outline.get_children(""):
            self.scene_outline.selection_set(iid)
            self.scene_outline.see(iid)
        self._draw_timeline()

    def _project_assets_dir(self, project_id=None):
        project_id = project_id if project_id is not None else self.current_id
        if project_id is None:
            return None
        return PROJECTS_DIR / str(project_id) / "assets"

    def _load_scene_assets(self, project_id=None):
        self.scene_assets = {}
        self.scene_duration_overrides = {}
        self._creator_narration_override = ""
        self._creator_auto_narration_active = False
        self.last_export_path = ""
        self.audio_track_path = ""
        self.music_track_path = ""
        if project_id is None:
            project_id = self.current_id
        if project_id is None:
            return
        project_dir = PROJECTS_DIR / str(project_id)
        original_narration_script = project_dir / "assets" / "narration_original.txt"
        try:
            if original_narration_script.is_file():
                self._creator_narration_override = original_narration_script.read_text(encoding="utf-8-sig").strip()
                self._creator_auto_narration_active = bool(self._creator_narration_override)
        except (OSError, UnicodeError):
            self._creator_narration_override = ""
            self._creator_auto_narration_active = False
        manifest = project_dir / "scene_assets.json"
        duration_manifest = project_dir / "scene_durations.json"
        last_video = project_dir / "last_export.txt"
        try:
            if manifest.is_file():
                loaded = json.loads(manifest.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.scene_assets = {str(k): str(v) for k, v in loaded.items()}
        except (OSError, json.JSONDecodeError):
            self.scene_assets = {}
        directions_manifest = project_dir / "scene_directions.json"
        try:
            loaded_directions = json.loads(directions_manifest.read_text(encoding="utf-8")) if directions_manifest.is_file() else {}
            self.scene_directions = {
                str(k): " ".join(str(v or "").split())[:500]
                for k, v in loaded_directions.items()
                if str(k).isdigit() and str(v or "").strip()
            } if isinstance(loaded_directions, dict) else {}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self.scene_directions = {}
        expansion_manifest = project_dir / "auto_expand_storyboard.txt"
        try:
            if expansion_manifest.is_file():
                self.auto_expand_storyboard = expansion_manifest.read_text(encoding="utf-8").strip() == "1"
            else:
                # Existing projects with assigned images retain their original scene indexes.
                self.auto_expand_storyboard = not bool(self.scene_assets)
        except OSError:
            self.auto_expand_storyboard = not bool(self.scene_assets)
        try:
            loaded_durations = json.loads(duration_manifest.read_text(encoding="utf-8")) if duration_manifest.is_file() else {}
            self.scene_duration_overrides = {str(k): max(1, min(5, int(v))) for k, v in loaded_durations.items() if str(k).isdigit()}
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            self.scene_duration_overrides = {}
        try:
            if last_video.is_file():
                candidate = last_video.read_text(encoding="utf-8").strip()
                if candidate and Path(candidate).is_file():
                    self.last_export_path = candidate
        except OSError:
            self.last_export_path = ""
        audio_manifest = project_dir / "audio_track.txt"
        try:
            if audio_manifest.is_file():
                candidate_audio = audio_manifest.read_text(encoding="utf-8").strip()
                if candidate_audio and Path(candidate_audio).is_file():
                    self.audio_track_path = candidate_audio
        except OSError:
            self.audio_track_path = ""
        music_manifest = project_dir / "music_track.txt"
        try:
            if music_manifest.is_file():
                candidate_music = music_manifest.read_text(encoding="utf-8").strip()
                if candidate_music and Path(candidate_music).is_file():
                    self.music_track_path = candidate_music
        except OSError:
            self.music_track_path = ""
        if hasattr(self, "preview_status_var"):
            self.preview_status_var.set(
                f"Último vídeo: {self.last_export_path}" if self.last_export_path
                else "Todavía no hay un MP4 exportado para este proyecto."
            )
        self._refresh_audio_track_label()

    def _save_scene_assets(self):
        assets_dir = self._project_assets_dir()
        if assets_dir is None:
            return
        assets_dir.mkdir(parents=True, exist_ok=True)
        manifest = assets_dir.parent / "scene_assets.json"
        manifest.write_text(json.dumps(self.scene_assets, ensure_ascii=False, indent=2), encoding="utf-8")
        directions_manifest = assets_dir.parent / "scene_directions.json"
        directions_manifest.write_text(json.dumps(self.scene_directions, ensure_ascii=False, indent=2), encoding="utf-8")
        expansion_manifest = assets_dir.parent / "auto_expand_storyboard.txt"
        expansion_manifest.write_text("1" if getattr(self, "auto_expand_storyboard", True) else "0", encoding="utf-8")
        duration_manifest = assets_dir.parent / "scene_durations.json"
        duration_manifest.write_text(json.dumps(self.scene_duration_overrides, ensure_ascii=False, indent=2), encoding="utf-8")
        audio_manifest = assets_dir.parent / "audio_track.txt"
        if self.audio_track_path and Path(self.audio_track_path).is_file():
            audio_manifest.write_text(self.audio_track_path, encoding="utf-8")
        elif audio_manifest.exists():
            audio_manifest.unlink()
        music_manifest = assets_dir.parent / "music_track.txt"
        if self.music_track_path and Path(self.music_track_path).is_file():
            music_manifest.write_text(self.music_track_path, encoding="utf-8")
        elif music_manifest.exists():
            music_manifest.unlink()

    def _set_scene_list_state(self, disabled):
        try:
            self.scene_outline.state(["disabled"] if disabled else ["!disabled"])
        except (AttributeError, tk.TclError):
            pass

    def _scene_selection_number(self):
        selection = self.scene_outline.selection()
        if not selection:
            return None
        item_id = selection[0]
        if not item_id.startswith("scene_"):
            return None
        try:
            return int(item_id.split("_", 1)[1])
        except ValueError:
            return None

    def _refresh_scene_outline(self, script):
        if not hasattr(self, "scene_outline"):
            return
        old_selection = self._scene_selection_number()
        children = self.scene_outline.get_children("")
        if children:
            self.scene_outline.delete(*children)
        parsed_scenes = parse_script_scenes(script)
        try:
            target_seconds = max(60, int(self.duration_var.get() or "10") * 60)
        except (ValueError, tk.TclError):
            target_seconds = 600
        required_shots = min(1440, visual_shot_count(target_seconds))
        self.scene_data = (
            expand_scenes_to_shots(parsed_scenes, required_shots, max_scenes=1440)
            if getattr(self, "auto_expand_storyboard", True) else parsed_scenes
        )
        durations = allocate_scene_durations(self.scene_data, target_seconds)
        durations = [min(5, max(1, int(self.scene_duration_overrides.get(str(i + 1), value)))) for i, value in enumerate(durations)]
        total_words = 0
        for idx, scene in enumerate(self.scene_data):
            asset = self.scene_assets.get(str(idx + 1), "")
            has_asset = bool(asset and Path(asset).is_file())
            visual_status = Path(asset).name if has_asset else "Tarjeta de texto"
            total_words += scene["word_count"]
            self.scene_outline.insert(
                "", "end", iid=f"scene_{idx + 1}",
                values=(f"{idx + 1:02d}", scene["title"][:100], scene["word_count"],
                        self._format_eta(durations[idx]), visual_status)
            )
        if not self.scene_data:
            self.timeline_selected_scene = 1
            self.scene_outline.insert(
                "", "end", iid="scene_empty",
                values=("", "Genera o abre un guion para ver las escenas", "", "", "")
            )
        elif old_selection and 1 <= old_selection <= len(self.scene_data):
            self.scene_outline.selection_set(f"scene_{old_selection}")
            self.scene_outline.see(f"scene_{old_selection}")
            self.timeline_selected_scene = old_selection
        else:
            self.timeline_selected_scene = 1
        if hasattr(self, "scene_summary_var"):
            voice_label = Path(self.audio_track_path).name if self.audio_track_path and Path(self.audio_track_path).is_file() else "sin narración"
            music_label = Path(self.music_track_path).name if self.music_track_path and Path(self.music_track_path).is_file() else "sin música"
            required_shots = visual_shot_count(target_seconds)
            missing_shots = max(0, required_shots - len(self.scene_data))
            visual_note = (
                f" · faltan {missing_shots} planos para cubrir la duración a ≤5 s"
                if missing_shots else " · todos los planos ≤5 s"
            )
            self.scene_summary_var.set(f"{len(self.scene_data)} planos · {total_words} palabras · objetivo {self.duration_var.get()} min{visual_note} · {voice_label} · {music_label}")
        self._draw_timeline()
        self._render_preview_frame()
        self._render_scene_asset_preview()

    def toggle_image_ai_tools(self):
        """Show/hide optional local image-generation controls; batch editing is the default."""
        self.image_ai_tools_visible = not bool(getattr(self, "image_ai_tools_visible", False))
        if self.image_ai_tools_visible:
            self.image_ai_bar.grid()
            self.image_ai_status_label.grid()
            self.toggle_image_ai_button.configure(text="Ocultar generación IA ▾")
        else:
            self.image_ai_bar.grid_remove()
            self.image_ai_status_label.grid_remove()
            self.toggle_image_ai_button.configure(text="Generación IA opcional ▸")

    def import_production_package(self):
        """Import an entire prepared folder; fall back to selecting individual files."""
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        package_dir = filedialog.askdirectory(
            title="Selecciona la carpeta completa del vídeo (guion, direcciones, imagenes y audio opcional)"
        )
        if package_dir:
            try:
                package = discover_production_package(package_dir)
                script = package.script_path.read_text(encoding="utf-8-sig").strip()
                directions = parse_scene_directions(package.direction_path) if package.direction_path else []
            except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
                messagebox.showerror("No se pudo leer el paquete", str(exc))
                return
            self._apply_production_package(
                package.script_path, script, directions, list(package.image_paths),
                narration_path=package.narration_path, music_path=package.music_path,
            )
            return
        if messagebox.askyesno(
            "Importación manual",
            "No seleccionaste una carpeta. ¿Quieres elegir el guion, las direcciones y las imágenes por separado?"
        ):
            self.import_production_package_files()

    def import_production_package_files(self):
        """Legacy/manual import flow for users who keep assets in separate locations."""
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        script_path = filedialog.askopenfilename(
            title="Selecciona el guion completo",
            filetypes=[("Guiones de texto", "*.txt *.md"), ("Todos los archivos", "*.*")]
        )
        if not script_path:
            return
        try:
            script = Path(script_path).read_text(encoding="utf-8-sig").strip()
        except (OSError, UnicodeError) as exc:
            messagebox.showerror("No se pudo leer el guion", str(exc))
            return
        if not script:
            messagebox.showwarning("Guion vacío", "El archivo seleccionado no contiene texto.")
            return
        direction_path = filedialog.askopenfilename(
            title="Selecciona la dirección por escena (opcional; Cancelar para omitir)",
            filetypes=[("Dirección por escena", "*.txt *.md *.json"), ("Todos los archivos", "*.*")]
        )
        try:
            directions = parse_scene_directions(direction_path) if direction_path else []
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            messagebox.showerror("No se pudo leer la dirección", f"Revisa el archivo de dirección por escena.\n\n{exc}")
            return
        image_paths = filedialog.askopenfilenames(
            title="Selecciona todas las imágenes en orden narrativo",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos los archivos", "*.*")]
        )
        if not image_paths:
            messagebox.showwarning("Faltan imágenes", "Selecciona al menos una imagen para importar el paquete.")
            return
        supported = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        images = [Path(item) for item in image_paths if Path(item).suffix.lower() in supported and Path(item).is_file()]
        if not images:
            messagebox.showerror("Sin imágenes compatibles", "No se encontraron imágenes PNG, JPG, JPEG, WEBP o BMP válidas.")
            return
        self._apply_production_package(Path(script_path), script, directions, images)

    def _apply_production_package(self, script_path, script, directions, images, narration_path=None, music_path=None):
        """Copy package assets into a project and connect available audio tracks automatically."""
        images = [Path(item) for item in images if Path(item).is_file()]
        directions = [str(item).strip()[:500] for item in directions if str(item).strip()]
        if not script.strip():
            messagebox.showwarning("Guion vacío", "El paquete no contiene un guion válido.")
            return
        if not images:
            messagebox.showwarning("Faltan imágenes", "El paquete debe incluir al menos una imagen.")
            return
        if self.current_id is not None and (self.script_text.get("1.0", "end-1c").strip() or self.scene_assets):
            if not messagebox.askyesno(
                "Reemplazar el contenido actual",
                "Se reemplazará el guion y la asignación de recursos de este proyecto. Los archivos originales no se borrarán. ¿Continuar?"
            ):
                return
        if not str(self.title_var.get() or "").strip():
            self.title_var.set(Path(script_path).stem.replace("_", " ").replace("-", " ").strip() or "Proyecto importado")
        if not str(self.topic_var.get() or "").strip():
            self.topic_var.set("Producción importada desde guion, dirección e imágenes")
        source_scene_count = len(parse_script_scenes(script))
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", script)
        self.auto_expand_storyboard = True
        self.scene_assets = {}
        self.scene_directions = {}
        self.scene_duration_overrides = {}
        self.audio_track_path = ""
        self.music_track_path = ""
        self._refresh_scene_outline(script)
        if not self.scene_data:
            messagebox.showerror("No se detectaron escenas", "El guion no pudo convertirse en escenas. Añade encabezados como ESCENA 1, ESCENA 2… y vuelve a importarlo.")
            return
        assets_dir = self._project_assets_dir(self.current_id)
        if assets_dir is None:
            self.save_project(reset_approval=True, quiet=True)
            assets_dir = self._project_assets_dir(self.current_id)
        if assets_dir is None:
            messagebox.showerror("No se pudo crear el proyecto", "Completa título y tema, guarda el proyecto y vuelve a importar el paquete.")
            return
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            if getattr(self, "_creator_auto_narration_active", False):
                original_script = str(getattr(self, "_creator_narration_override", "") or "").strip()
                if original_script:
                    (assets_dir / "narration_original.txt").write_text(original_script, encoding="utf-8")
            imported_paths = []
            for image_index, source in enumerate(images, start=1):
                destination = assets_dir / f"imported_image_{image_index:03d}{source.suffix.lower()}"
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                imported_paths.append(str(destination.resolve()))

            scene_count = len(self.scene_data)
            resource_map = map_production_resources(
                self.scene_data, len(imported_paths), len(directions), source_scene_count
            )
            assigned_image_indexes = set()
            for index, (image_index, direction_index) in enumerate(resource_map):
                if image_index is not None and 0 <= image_index < len(imported_paths):
                    self.scene_assets[str(index + 1)] = imported_paths[image_index]
                    assigned_image_indexes.add(image_index)
                if direction_index is not None and 0 <= direction_index < len(directions):
                    self.scene_directions[str(index + 1)] = directions[direction_index]

            if narration_path and Path(narration_path).is_file():
                source = Path(narration_path)
                destination = assets_dir / f"imported_narration{source.suffix.lower()}"
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                self.audio_track_path = str(destination.resolve())
            if music_path and Path(music_path).is_file():
                source = Path(music_path)
                destination = assets_dir / f"imported_music{source.suffix.lower()}"
                if source.resolve() != destination.resolve():
                    shutil.copy2(source, destination)
                self.music_track_path = str(destination.resolve())

            self._save_scene_assets()
            self.save_project(reset_approval=True, quiet=True)
            self._refresh_scene_outline(script)
            if self.scene_data:
                self.scene_outline.selection_set("scene_1")
                self.scene_outline.see("scene_1")
                self._render_scene_asset_preview()
        except (OSError, tk.TclError) as exc:
            messagebox.showerror("Error al importar el paquete", str(exc))
            return
        self.studio_tabs.select(self.scenes_tab)
        direction_note = f" · {len(directions)} indicaciones de movimiento" if directions else " · movimiento de cámara automático"
        audio_note = []
        if self.audio_track_path:
            audio_note.append("narración importada")
        if self.music_track_path:
            audio_note.append("música importada")
        audio_summary = " · " + ", ".join(audio_note) if audio_note else " · voz/música no incluidas en la carpeta"
        unused_images = max(0, len(imported_paths) - len(assigned_image_indexes))
        extra_note = f" · {unused_images} imágenes importadas sin plano asignado (hay menos planos que imágenes)" if unused_images else ""
        self.status_var.set(
            f"Paquete importado: {len(images)} imágenes distribuidas en {scene_count} planos{direction_note}{audio_summary}{extra_note}. "
            "Listo para revisión o montaje automático."
        )
        start_now = messagebox.askyesno(
            "Paquete importado",
            f"Guion: {Path(script_path).name}\nImágenes: {len(images)}\nPlanos detectados: {scene_count}\n"
            f"Direcciones: {len(directions)}\nNarración: {'importada' if self.audio_track_path else 'se sintetizará con la voz local de Windows si está disponible'}\n"
            f"Música: {'importada' if self.music_track_path else 'no incluida'}\n\n"
            "Las imágenes y las indicaciones se copiaron al proyecto. El movimiento será zoom/paneo y transiciones; "
            "esto no genera movimiento corporal neuronal. ¿Deseas aprobar el guion e iniciar ahora el montaje MP4? "
            "El vídeo se guardará automáticamente en la carpeta de exportaciones del proyecto."
        )
        if start_now:
            self.approve_script(remote=True)
            self._auto_export_after_import = True
            try:
                self._start_video_render(preview=False, remote=False)
            finally:
                self._auto_export_after_import = False

    def assign_scene_image(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Completa el título y la premisa antes de asignar imágenes.")
            return
        scene_number = self._scene_selection_number()
        if scene_number is None or not self.scene_data or scene_number > len(self.scene_data):
            messagebox.showinfo("Selecciona una escena", "Primero genera o abre un guion y selecciona una escena.")
            return
        source = filedialog.askopenfilename(
            title="Selecciona la imagen de esta escena",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos los archivos", "*.*")]
        )
        if not source:
            return
        source_path = Path(source)
        if source_path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
            messagebox.showerror("Formato no compatible", "Selecciona una imagen PNG, JPG, WEBP o BMP.")
            return
        assets_dir = self._project_assets_dir()
        if assets_dir is None:
            return
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            destination = assets_dir / f"scene_{scene_number:03d}{source_path.suffix.lower()}"
            shutil.copy2(source_path, destination)
            self.scene_assets[str(scene_number)] = str(destination.resolve())
            self._save_scene_assets()
            self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
            self.scene_outline.selection_set(f"scene_{scene_number}")
            self.scene_outline.see(f"scene_{scene_number}")
            self._render_scene_asset_preview()
            self.status_var.set(f"Imagen asignada a la escena {scene_number}. Se usará durante el render.")
        except OSError as exc:
            messagebox.showerror("No se pudo copiar la imagen", str(exc))

    def clear_scene_image(self):
        scene_number = self._scene_selection_number()
        if scene_number is None:
            messagebox.showinfo("Selecciona una escena", "Selecciona la escena cuya imagen quieres quitar.")
            return
        self.scene_assets.pop(str(scene_number), None)
        try:
            self._save_scene_assets()
        except OSError as exc:
            messagebox.showerror("No se pudo guardar el recurso", str(exc))
            return
        self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
        self.scene_outline.selection_set(f"scene_{scene_number}")
        self.scene_outline.see(f"scene_{scene_number}")
        self._render_scene_asset_preview()
        self.status_var.set(f"Se quitó la imagen de la escena {scene_number}; se usará una tarjeta de texto.")

    def _refresh_audio_track_label(self):
        if hasattr(self, "audio_track_label_var"):
            if self.audio_track_path and Path(self.audio_track_path).is_file():
                voice_path = Path(self.audio_track_path)
                self.audio_track_label_var.set(f"{voice_path.name}\n{voice_path}")
            else:
                self.audio_track_label_var.set("Sin pista de narración. Puedes importar voz o generarla localmente.")
        if hasattr(self, "music_track_label_var"):
            if self.music_track_path and Path(self.music_track_path).is_file():
                music_path = Path(self.music_track_path)
                self.music_track_label_var.set(f"{music_path.name}\n{music_path}")
            else:
                self.music_track_label_var.set("Sin música de fondo.")
        self._draw_timeline()

    def on_voice_engine_changed(self, _event=None):
        """Switch between the built-in SAPI voices and an optional local neural Kokoro server."""
        engine = str(self.voice_engine_var.get() or "Windows (básica)")
        if engine.startswith("Kokoro"):
            self.voice_combo.configure(values=self.kokoro_voice_names)
            if self.voice_var.get() not in self.kokoro_voice_names:
                preferred = next(
                    (name for name in ("ef_dora", "em_alex", "em_santa") if name in self.kokoro_voice_names),
                    self.kokoro_voice_names[0] if self.kokoro_voice_names else ""
                )
                self.voice_var.set(preferred)
            self.add_voices_button.configure(text="Configurar Kokoro")
            self.generate_voice_button.configure(text="Generar voz neural")
            self.voice_status_var.set(
                f"Kokoro local · {len(self.kokoro_voice_names)} voces detectadas"
                if self.kokoro_voice_names else
                "Buscando el motor neural local en http://127.0.0.1:7860…"
            )
            self.detect_kokoro_voices(quiet=True)
        else:
            self.voice_combo.configure(values=self.available_voice_names or ["(Automática)"])
            if self.voice_var.get() not in self.available_voice_names and self.voice_var.get() != "(Automática)":
                self.voice_var.set("(Automática)")
            self.add_voices_button.configure(text="Añadir voces de Windows")
            self.generate_voice_button.configure(text="Generar narración")
            self.voice_status_var.set(
                f"Windows SAPI · {len(self.available_voice_names)} voces detectadas"
                if self.available_voice_names else
                "Detecta o instala voces de Windows, o usa el motor neural Kokoro."
            )
            if os.name == "nt" and not self.available_voice_names:
                self.detect_local_voices(quiet=True)

    def configure_voice_engine(self):
        """Open the setup instructions for the selected local voice engine."""
        engine = str(self.voice_engine_var.get() or "")
        if engine.startswith("Kokoro"):
            messagebox.showinfo(
                "Configurar voces neurales",
                "Kokoro necesita un servidor local. Instala Docker Desktop y abre PowerShell.\n\n"
                "PRIMERA VEZ — descargar e iniciar el motor (CPU):\n"
                "docker run -d --name marc-kokoro -p 7860:7860 -v kokorotts_data:/app/persistent hangrylabs/kokorotts:v1.0\n\n"
                "DESPUÉS — si el contenedor ya existe:\n"
                "docker start marc-kokoro\n\n"
                "Al terminar, vuelve a MARC → Audio → Detectar voces. Dirección local esperada: " + self.kokoro_url +
                "\n\nLa primera instalación descarga el modelo y puede tardar. La narración se procesa localmente."
            )
            webbrowser.open("https://github.com/hangry-labs/kokoroTTS")
            return
        self.open_windows_voice_settings()

    def detect_kokoro_voices(self, quiet=False):
        """Discover voices from an optional local KokoroTTS HTTP service."""
        if self.voice_generation_running:
            return
        self.voice_status_var.set("Buscando voces neurales locales…")
        threading.Thread(target=self._detect_kokoro_voices_worker, args=(quiet,), daemon=True).start()

    def _detect_kokoro_voices_worker(self, quiet=False):
        try:
            request = urllib.request.Request(
                self.kokoro_url + "/tts/voices",
                headers={"Accept": "application/json"},
                method="GET",
            )
            with urllib.request.urlopen(request, timeout=8) as response:
                payload = json.loads(response.read().decode("utf-8"))
            voices = parse_kokoro_voice_ids(payload)
            # Prefer Spanish voice families where available, so Spanish dialogue doesn't accidentally use English voices.
            spanish_voices = [
                voice for voice in voices
                if voice.casefold().startswith(("ef_", "em_", "es_"))
            ]
            if spanish_voices:
                voices = spanish_voices
            if not voices:
                raise RuntimeError(
                    "El servidor respondió, pero no pude leer su lista de voces. "
                    "Comprueba que estás usando la API de KokoroTTS compatible."
                )
            self.generation_queue.put(("kokoro_voices", voices, quiet))
        except Exception as exc:
            self.generation_queue.put(("kokoro_voices_error", str(exc), quiet))

    def open_windows_voice_settings(self):
        """Open Windows speech settings and explain how to refresh the installed voice list."""
        if os.name != "nt":
            self.voice_status_var.set("La gestión de voces locales está disponible en Windows.")
            return
        try:
            os.startfile("ms-settings:speech")
            self.voice_status_var.set(
                "En Configuración de Windows, añade una voz compatible con texto a voz. "
                "Al terminar, vuelve a MARC y pulsa «Detectar voces»."
            )
        except (OSError, AttributeError) as exc:
            messagebox.showinfo(
                "Añadir voces de Windows",
                "Abre Configuración → Hora e idioma → Voz, instala una voz compatible y vuelve a pulsar «Detectar voces».\n\n"
                + str(exc)
            )

    def detect_local_voices(self, quiet=False):
        if self.voice_generation_running:
            return
        engine_var = getattr(self, "voice_engine_var", None)
        if engine_var is not None and str(engine_var.get()).startswith("Kokoro"):
            self.detect_kokoro_voices(quiet=quiet)
            return
        if os.name != "nt":
            self.voice_status_var.set("La narración de Windows solo está disponible en Windows.")
            return
        self.voice_status_var.set("Buscando voces instaladas localmente…")
        threading.Thread(target=self._detect_local_voices_worker, args=(quiet,), daemon=True).start()

    def _detect_local_voices_worker(self, quiet=False):
        try:
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if not powershell:
                raise RuntimeError("No se encontró Windows PowerShell.")
            script = (
                "$ErrorActionPreference='Stop'; "
                "Add-Type -AssemblyName System.Speech; "
                "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }; "
                "$s.Dispose()"
            )
            result = subprocess.run(
                [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script],
                capture_output=True, text=True, timeout=20,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)
            )
            if result.returncode != 0:
                raise RuntimeError((result.stderr or result.stdout or "Windows no pudo enumerar las voces SAPI.").strip()[-1800:])
            voices = list(dict.fromkeys(line.strip() for line in result.stdout.splitlines() if line.strip()))
            self.generation_queue.put(("voice_models", voices, quiet))
        except Exception as exc:
            self.generation_queue.put(("voice_models_error", str(exc), quiet))

    def edit_character_voices(self):
        """Map explicit script speaker labels to installed Windows voices."""
        script = self.script_text.get("1.0", "end-1c")
        speakers = extract_speaker_names(script)
        if not speakers:
            messagebox.showinfo(
                "No hay personajes etiquetados",
                "Para asignar voces, el guion debe identificar las intervenciones como [JUAN]: diálogo y [NARRADOR]: descripción. "
                "Genera un guion con etiquetas de hablante o añádelas al texto."
            )
            return
        is_kokoro = str(self.voice_engine_var.get()).startswith("Kokoro")
        voices = list(self.kokoro_voice_names if is_kokoro else self.available_voice_names)
        if not voices:
            messagebox.showwarning(
                "Primero detecta las voces",
                "Pulsa «Detectar voces» en Audio para cargar las voces del motor seleccionado."
            )
            return
        dialog = tk.Toplevel(self)
        dialog.title("Voces por personaje · Kokoro" if is_kokoro else "Voces por personaje")
        dialog.configure(bg=self.colors["panel"])
        dialog.transient(self)
        dialog.grab_set()
        dialog.geometry("620x520")
        dialog.minsize(520, 360)
        body = tk.Frame(dialog, bg=self.colors["panel"], padx=16, pady=14)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="ASIGNACIÓN DE VOCES", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(body,
                 text=("Elige una voz neural para cada personaje. «Voz principal» usa la voz seleccionada en Audio."
                       if is_kokoro else
                       "Elige una voz local para el narrador y cada personaje. «Voz principal» utiliza la voz general seleccionada en Audio."),
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=560, justify="left").pack(anchor="w", pady=(5, 12))
        scroll = tk.Canvas(body, bg=self.colors["input"], highlightthickness=0)
        scroll.pack(fill="both", expand=True)
        inner = tk.Frame(scroll, bg=self.colors["input"], padx=8, pady=8)
        win = scroll.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _event: scroll.configure(scrollregion=scroll.bbox("all")))
        scroll.bind("<Configure>", lambda event: scroll.itemconfigure(win, width=event.width))
        voice_vars = {}
        options = ["(Voz principal)"] + voices
        for row, speaker in enumerate(speakers):
            tk.Label(inner, text=speaker, bg=self.colors["input"], fg=self.colors["text"],
                     font=("Segoe UI", 10, "bold")).grid(row=row, column=0, sticky="w", padx=(4, 10), pady=5)
            variable = tk.StringVar(value=self.voice_assignments.get(speaker, "(Voz principal)"))
            if variable.get() not in options:
                variable.set("(Voz principal)")
            combo = ttk.Combobox(inner, textvariable=variable, values=options,
                                 state="readonly", font=("Segoe UI", 9))
            combo.grid(row=row, column=1, sticky="ew", padx=4, pady=5)
            voice_vars[speaker] = variable
        inner.columnconfigure(1, weight=1)
        actions = tk.Frame(body, bg=self.colors["panel"])
        actions.pack(fill="x", pady=(12, 0))
        def save_mapping():
            self.voice_assignments = {
                name: var.get() for name, var in voice_vars.items()
                if var.get() and var.get() != "(Voz principal)"
            }
            if self.current_id is not None:
                self.save_project(quiet=True)
            self.voice_status_var.set(f"Voces asignadas a {len(self.voice_assignments)} personaje(s).")
            self.status_var.set("Asignación de voces guardada en el proyecto.")
            dialog.destroy()
        ttk.Button(actions, text="Cancelar", command=dialog.destroy).pack(side="right")
        ttk.Button(actions, text="Guardar asignaciones", style="Accent.TButton",
                   command=save_mapping).pack(side="right", padx=(0, 8))

    def generate_kokoro_voice(self):
        """Generate expressive multi-speaker narration through an optional local KokoroTTS server."""
        if not self.kokoro_voice_names:
            messagebox.showwarning(
                "Primero conecta Kokoro",
                "Pulsa «Detectar voces». Si no encuentra el servidor, pulsa «Configurar Kokoro» para ver cómo instalarlo."
            )
            self.detect_kokoro_voices(quiet=False)
            return
        raw_script = str(getattr(self, "_creator_narration_override", "") or "").strip() or self.script_text.get("1.0", "end-1c")
        if not parse_script_scenes(raw_script):
            messagebox.showwarning("Sin guion", "Genera o escribe un guion antes de crear la narración.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Completa el título y la premisa antes de generar la narración.")
            return
        chosen_voice = self.voice_var.get().strip()
        if chosen_voice not in self.kokoro_voice_names:
            messagebox.showwarning("Selecciona una voz", "Elige una voz Kokoro de la lista detectada.")
            return
        if self.audio_track_path and Path(self.audio_track_path).is_file():
            if not messagebox.askyesno(
                "Reemplazar pista de audio",
                "Este proyecto ya tiene una pista de audio. La nueva narración será la pista actual, "
                "y la pista anterior permanecerá como archivo en los recursos. ¿Continuar?"
            ):
                return
        try:
            ssml, speaker_map = build_kokoro_ssml(
                raw_script, self.kokoro_voice_names, chosen_voice, self.voice_assignments
            )
        except (ValueError, TypeError) as exc:
            messagebox.showwarning("No se pudo preparar el guion de voz", str(exc))
            return
        assets_dir = self._project_assets_dir()
        if assets_dir is None:
            return
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            messagebox.showerror("No se pudo preparar el audio", str(exc))
            return
        output_path = assets_dir / "narration_kokoro.pending.wav"
        self._pipeline_checkpoint(
            "narration", "running",
            f"Kokoro local · voz principal {chosen_voice} · {len(set(speaker_map.values()))} timbres"
        )
        self.voice_generation_running = True
        self.voice_cancel_event.clear()
        self._set_voice_state(True)
        self.progressbar.configure(mode="indeterminate")
        self.progressbar.start(12)
        self.progress_label_var.set("Generando narración neural")
        self.progress_detail_var.set("Preparando diálogo, voces por personaje y prosodia emocional…")
        self.voice_status_var.set(
            "Kokoro está sintetizando la narración localmente. Puede tardar según el equipo y la duración del guion."
        )
        self.status_var.set("Generación de voz neural en curso.")
        threading.Thread(
            target=self._kokoro_voice_worker,
            args=(int(self.current_id), ssml, str(output_path), chosen_voice, self.kokoro_url,
                  len(set(speaker_map.values()))),
            daemon=True,
        ).start()

    def _kokoro_voice_worker(self, project_id, ssml, output_path, voice_name, base_url, voice_count):
        """Call the local Kokoro HTTP API; narration never leaves the local machine."""
        temporary = Path(output_path)
        try:
            body = json.dumps({
                "input_type": "ssml",
                "text": ssml,
                "voice": voice_name,
                "output_format": "wav",
            }, ensure_ascii=False).encode("utf-8")
            request = urllib.request.Request(
                str(base_url).rstrip("/") + "/tts/generate",
                data=body,
                headers={"Content-Type": "application/json", "Accept": "audio/wav"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=900) as response:
                audio = response.read()
                content_type = str(response.headers.get("Content-Type", "")).casefold()
            if self.voice_cancel_event.is_set():
                self.generation_queue.put(("voice_cancelled",))
                return
            if "json" in content_type:
                try:
                    payload = json.loads(audio.decode("utf-8", errors="replace"))
                    detail = str(payload.get("error") or payload.get("detail") or payload)
                except Exception:
                    detail = audio.decode("utf-8", errors="replace")[:600]
                raise RuntimeError("Kokoro devolvió un error de API: " + detail)
            if len(audio) < 44 or not audio.startswith(b"RIFF"):
                detail = audio[:300].decode("utf-8", errors="replace")
                raise RuntimeError("Kokoro no devolvió un WAV válido. " + detail)
            temporary.parent.mkdir(parents=True, exist_ok=True)
            temporary.write_bytes(audio)
            final_path = temporary.with_name("narration_kokoro.wav")
            temporary.replace(final_path)
            label = f"Kokoro neural · {voice_name} · {voice_count} timbres"
            self.generation_queue.put(("voice_done", project_id, str(final_path.resolve()), label))
        except Exception as exc:
            if self.voice_cancel_event.is_set():
                self.generation_queue.put(("voice_cancelled",))
            else:
                self.generation_queue.put(("voice_error", str(exc), "kokoro"))
        finally:
            if self.voice_cancel_event.is_set():
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass

    def generate_local_voice(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if str(self.voice_engine_var.get()).startswith("Kokoro"):
            self.generate_kokoro_voice()
            return
        if os.name != "nt":
            messagebox.showinfo("Solo Windows", "La narración local integrada utiliza las voces instaladas de Windows.")
            return
        raw_script = self.script_text.get("1.0", "end-1c")
        scenes = parse_script_scenes(raw_script)
        narration = "\n\n".join(scene["text"] for scene in scenes if scene.get("text", "").strip()).strip()
        if not narration:
            messagebox.showwarning("Sin guion", "Genera o escribe un guion antes de crear la narración.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Completa el título y la premisa antes de generar la narración.")
            return
        chosen_voice = self.voice_var.get().strip() or "(Automática)"
        if chosen_voice != "(Automática)" and chosen_voice not in self.available_voice_names:
            messagebox.showwarning("Voz no disponible", "Pulsa «Detectar voces» y selecciona una voz instalada.")
            return
        speaker_names = extract_speaker_names(raw_script)
        if len(speaker_names) > 1 and len(self.available_voice_names) > 1:
            if chosen_voice == "(Automática)":
                chosen_voice = self.available_voice_names[0]
                self.voice_var.set(chosen_voice)
            self._prepare_default_character_voice_assignments(raw_script, chosen_voice)
        elif len(speaker_names) > 1:
            self.voice_status_var.set(
                "El guion tiene varios hablantes, pero Windows solo ofrece una voz local. "
                "Instala voces adicionales para distinguir los personajes."
            )
        elif not speaker_names:
            self.voice_status_var.set(
                "No se detectaron etiquetas [PERSONAJE]: en el guion; la narración tendrá una sola voz. "
                "Usa etiquetas por hablante para separar narrador y diálogos."
            )
        if self.audio_track_path and Path(self.audio_track_path).is_file():
            if not messagebox.askyesno(
                "Reemplazar pista de audio",
                "Este proyecto ya tiene una pista de audio. La narración generada pasará a ser la pista actual. "
                "La pista anterior permanecerá como archivo en la carpeta de recursos. ¿Continuar?"
            ):
                return
        assets_dir = self._project_assets_dir()
        if assets_dir is None:
            return
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            text_path = assets_dir / "narration_text.txt"
            script_path = assets_dir / "synthesize_windows_voice.ps1"
            output_path = assets_dir / "narration.pending.wav"
            voice_map_path = assets_dir / "voice_assignments.json"
            text_path.write_text(narration, encoding="utf-8")
            voice_map_path.write_text(json.dumps(self.voice_assignments or {}, ensure_ascii=False), encoding="utf-8")
            script_path.write_text(
                r"""param(
    [Parameter(Mandatory=$true)][string]$TextFile,
    [Parameter(Mandatory=$true)][string]$OutputFile,
    [Parameter(Mandatory=$false)][string]$VoiceName,
    [Parameter(Mandatory=$false)][string]$VoiceMapFile
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voiceMap = @{}
if ($VoiceMapFile -and (Test-Path -LiteralPath $VoiceMapFile)) {
    $parsed = Get-Content -LiteralPath $VoiceMapFile -Raw -Encoding UTF8 | ConvertFrom-Json
    foreach ($property in $parsed.PSObject.Properties) {
        $voiceMap[$property.Name.ToUpperInvariant()] = [string]$property.Value
    }
}
try {
    $systemDefaultVoice = $synth.Voice.Name
    $availableVoices = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
    $defaultVoice = $VoiceName
    if (!$defaultVoice -or $defaultVoice -eq '(Automática)' -or $availableVoices -notcontains $defaultVoice) {
        $defaultVoice = $systemDefaultVoice
    }
    $synth.SelectVoice($defaultVoice)
    $synth.Rate = 0
    $synth.Volume = 100
    function Speak-Expressive {
        param([string]$Line)
        $emotion = 'neutral'
        $spoken = [string]$Line
        if ($spoken -match '^\s*\[EMOCION\s*=\s*([^\]]+)\]\s*') {
            $emotion = $Matches[1].Trim().ToLowerInvariant()
            $spoken = $spoken.Substring($Matches[0].Length).Trim()
        }
        if ([string]::IsNullOrWhiteSpace($spoken)) { return }
        $rate = '+0%'; $pitch = '+0%'; $volume = 'medium'
        switch -Regex ($emotion) {
            '^(miedo|temor|panico|pánico)$' { $rate = '-10%'; $pitch = '+12%'; $volume = 'medium'; break }
            '^(susurro|secreto)$' { $rate = '-18%'; $pitch = '-2%'; $volume = 'soft'; break }
            '^(ira|enojo|rabia)$' { $rate = '+14%'; $pitch = '+8%'; $volume = 'loud'; break }
            '^(tristeza|dolor|duelo)$' { $rate = '-18%'; $pitch = '-8%'; $volume = 'soft'; break }
            '^(alegria|alegría|entusiasmo)$' { $rate = '+10%'; $pitch = '+8%'; $volume = 'loud'; break }
            '^(sorpresa|shock)$' { $rate = '+8%'; $pitch = '+16%'; $volume = 'loud'; break }
            '^(urgencia|panico|pánico)$' { $rate = '+18%'; $pitch = '+10%'; $volume = 'loud'; break }
            '^(suspenso|tension|tensión)$' { $rate = '-16%'; $pitch = '-4%'; $volume = 'soft'; break }
            '^(calma|sereno)$' { $rate = '-7%'; $pitch = '-2%'; $volume = 'medium'; break }
        }
        $safeText = [System.Security.SecurityElement]::Escape($spoken)
        $culture = $synth.Voice.Culture.Name
        if (!$culture) { $culture = 'es-ES' }
        $ssml = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="' + $culture + '"><prosody rate="' + $rate + '" pitch="' + $pitch + '" volume="' + $volume + '">' + $safeText + '</prosody></speak>'
        try { $synth.SpeakSsml($ssml) } catch { $synth.Speak($spoken) }
    }
    $text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($text)) { throw 'El texto de narración está vacío.' }
    $synth.SetOutputToWaveFile($OutputFile)
    foreach ($rawLine in ($text -split '\r?\n')) {
        $line = $rawLine.Trim()
        if ([string]::IsNullOrWhiteSpace($line)) { continue }
        $segments = [regex]::Matches($line, '\[([^\]]+)\]\s*:\s*(.*?)(?=\s+\[[^\]]+\]\s*:\s*|$)')
        if ($segments.Count -gt 0) {
            foreach ($segment in $segments) {
                $speaker = $segment.Groups[1].Value.Trim().ToUpperInvariant()
                $spoken = $segment.Groups[2].Value.Trim()
                if ($voiceMap.ContainsKey($speaker) -and $voiceMap[$speaker] -and
                    $voiceMap[$speaker] -ne '(Voz principal)' -and $availableVoices -contains $voiceMap[$speaker]) {
                    $synth.SelectVoice($voiceMap[$speaker])
                } else {
                    $synth.SelectVoice($defaultVoice)
                }
                if (![string]::IsNullOrWhiteSpace($spoken)) { Speak-Expressive $spoken }
            }
        } else {
            $synth.SelectVoice($defaultVoice)
            Speak-Expressive $line
        }
    }
    $synth.SetOutputToNull()
}
finally {
    $synth.Dispose()
}
if (!(Test-Path -LiteralPath $OutputFile) -or (Get-Item -LiteralPath $OutputFile).Length -lt 44) {
    throw 'Windows no generó un archivo WAV válido.'
}
Write-Output 'NARRATION_OK'
""",
                encoding="utf-8"
            )
        except OSError as exc:
            messagebox.showerror("No se pudo preparar la narración", str(exc))
            return
        self._pipeline_checkpoint("narration", "running", "Sintetizando voz local con Windows")
        self.voice_generation_running = True
        self.voice_cancel_event.clear()
        self._set_voice_state(True)
        self.progressbar.configure(mode="indeterminate")
        self.progressbar.start(12)
        self.progress_label_var.set("Narración local en proceso")
        self.progress_detail_var.set("0% · Windows está sintetizando voz desde el guion")
        self.voice_status_var.set("Generando WAV sin conexión. La duración depende de la longitud del guion y la voz instalada.")
        self.status_var.set("La narración se genera localmente; puedes cancelar este proceso.")
        args = (int(self.current_id), str(text_path), str(script_path), str(output_path), chosen_voice, str(voice_map_path))
        threading.Thread(target=self._local_voice_worker, args=args, daemon=True).start()

    def _set_voice_state(self, active):
        state = "disabled" if active else "normal"
        for button in (
            self.generate_button, self.new_project_button, self.save_button, self.approve_button,
            self.export_button, self.preview_render_button, self.delete_button, self.assign_image_button, self.clear_image_button,
            self.refresh_scenes_button, self.select_audio_button, self.clear_audio_button,
            self.detect_models_button, self.start_comfyui_button, self.generate_image_button, self.generate_missing_images_button, self.detect_voice_button,
            self.generate_voice_button, self.assign_character_voices_button, self.add_voices_button, self.inspector_assign_image_button,
            self.inspector_generate_image_button, self.inspector_duration_button, self.export_srt_button,
            self.select_music_button, self.clear_music_button
        ):
            button.configure(state=state)
        self.cancel_button.configure(state="disabled")
        self.cancel_render_button.configure(state="disabled")
        self.cancel_voice_button.configure(state="normal" if active else "disabled")
        self.project_list.configure(state=state)
        self._set_scene_list_state(active)
        self.image_model_combo.configure(state="disabled" if active else "readonly")
        self.image_upscale_combo.configure(state="disabled" if active else "readonly")
        self.voice_combo.configure(state="disabled" if active else "readonly")
        self.voice_engine_combo.configure(state="disabled" if active else "readonly")
        for widget, idle_state in self.form_widgets:
            widget.configure(state="disabled" if active else idle_state)
        self.script_text.configure(state="disabled" if active else "normal")
        if not active:
            self.progressbar.stop()
            self.progressbar.configure(mode="determinate")

    def cancel_local_voice(self):
        if self.voice_generation_running:
            self.voice_cancel_event.set()
            self.cancel_voice_button.configure(state="disabled")
            if str(self.voice_engine_var.get()).startswith("Kokoro"):
                self.voice_status_var.set(
                    "Cancelación solicitada; Kokoro descartará el audio cuando termine la petición activa."
                )
            else:
                self.voice_status_var.set("Cancelación solicitada; deteniendo la síntesis de voz…")

    def _local_voice_worker(self, project_id, text_path, script_path, output_path, voice_name, voice_map_path=""):
        log_path = Path(text_path).with_name("synthesize_voice.log")
        try:
            powershell = shutil.which("powershell.exe") or shutil.which("powershell")
            if not powershell:
                raise RuntimeError("No se encontró Windows PowerShell.")
            if self.voice_cancel_event.is_set():
                self.generation_queue.put(("voice_cancelled",))
                return
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                process = subprocess.Popen(
                    [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", script_path, "-TextFile", text_path,
                     "-OutputFile", output_path, "-VoiceName", voice_name,
                     "-VoiceMapFile", voice_map_path],
                    stdout=subprocess.DEVNULL, stderr=log, creationflags=creationflags
                )
                last_update = time.monotonic()
                while process.poll() is None:
                    if self.voice_cancel_event.is_set():
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        self.generation_queue.put(("voice_cancelled",))
                        return
                    if time.monotonic() - last_update >= 5:
                        self.generation_queue.put(("voice_progress", "Windows sigue sintetizando la narración local…"))
                        last_update = time.monotonic()
                    time.sleep(0.25)
                if process.returncode != 0:
                    detail = log_path.read_text(encoding="utf-8", errors="replace")[-2200:]
                    raise RuntimeError(detail or f"PowerShell terminó con código {process.returncode}.")
            output = Path(output_path)
            if self.voice_cancel_event.is_set():
                self.generation_queue.put(("voice_cancelled",))
                return
            if not output.is_file() or output.stat().st_size < 44:
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-2200:]
                raise RuntimeError(detail or "Windows no creó un WAV válido.")
            final_output = output.with_name("narration.wav")
            output.replace(final_output)
            self.generation_queue.put(("voice_done", project_id, str(final_output.resolve()), voice_name))
        except Exception as exc:
            self.generation_queue.put(("voice_error", str(exc)))
        finally:
            if self.voice_cancel_event.is_set():
                try:
                    Path(output_path).unlink(missing_ok=True)
                except OSError:
                    pass

    def export_subtitles(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        script = self.script_text.get("1.0", "end-1c")
        parsed_scenes = parse_script_scenes(script)
        if not parsed_scenes:
            messagebox.showwarning("Sin guion", "Genera o escribe un guion antes de exportar subtítulos.")
            return
        try:
            target_seconds = max(60, int(self.duration_var.get() or "10") * 60)
        except ValueError:
            target_seconds = 600
        required_shots = min(1440, visual_shot_count(target_seconds))
        scenes = (
            expand_scenes_to_shots(parsed_scenes, required_shots, max_scenes=1440)
            if getattr(self, "auto_expand_storyboard", True) else parsed_scenes
        )
        durations = allocate_scene_durations(scenes, target_seconds)
        durations = [
            min(5, max(1, int(self.scene_duration_overrides.get(str(i + 1), value))))
            for i, value in enumerate(durations)
        ]
        subtitles = build_srt_subtitles(scenes, durations)
        if not subtitles:
            messagebox.showwarning("Sin subtítulos", "No se encontró texto de escena para exportar.")
            return
        project_title = (self.title_var.get().strip() or "MARC-Subtitulos").replace("/", "-").replace("\\", "-")
        path = filedialog.asksaveasfilename(
            title="Guardar subtítulos SRT",
            defaultextension=".srt",
            filetypes=[("Subtítulos SubRip", "*.srt")],
            initialfile=f"{project_title[:60]}.srt"
        )
        if not path:
            return
        try:
            Path(path).write_text(subtitles, encoding="utf-8-sig")
            self.status_var.set(f"Subtítulos SRT exportados: {path}")
            messagebox.showinfo(
                "Subtítulos exportados",
                f"Se creó el archivo SRT:\n{path}\n\nLos tiempos se reparten por escena según la duración objetivo; revisa la sincronización con la voz antes de publicarlo."
            )
        except OSError as exc:
            messagebox.showerror("No se pudieron guardar los subtítulos", str(exc))

    def select_audio_track(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Completa el título y la premisa antes de asignar audio.")
            return
        source = filedialog.askopenfilename(
            title="Selecciona una pista de narración o voz",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg"), ("Todos los archivos", "*.*")]
        )
        if not source:
            return
        source_path = Path(source)
        if source_path.suffix.lower() not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
            messagebox.showerror("Formato no compatible", "Selecciona un archivo WAV, MP3, M4A, AAC, FLAC u OGG.")
            return
        assets_dir = self._project_assets_dir()
        if assets_dir is None:
            return
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            destination = assets_dir / ("audio_track" + source_path.suffix.lower())
            shutil.copy2(source_path, destination)
            self.audio_track_path = str(destination.resolve())
            self._save_scene_assets()
            self._refresh_audio_track_label()
            self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
            self.status_var.set(f"Pista de narración asignada: {destination.name}")
        except OSError as exc:
            messagebox.showerror("No se pudo copiar el audio", str(exc))

    def clear_audio_track(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        self.audio_track_path = ""
        try:
            self._save_scene_assets()
            self._refresh_audio_track_label()
            self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
            self.status_var.set("Se quitó la pista de audio del proyecto.")
        except OSError as exc:
            messagebox.showerror("No se pudo quitar el audio", str(exc))

    def select_music_track(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Completa el título y la premisa antes de asignar música.")
            return
        source = filedialog.askopenfilename(
            title="Selecciona la música de fondo",
            filetypes=[("Audio", "*.wav *.mp3 *.m4a *.aac *.flac *.ogg"), ("Todos los archivos", "*.*")]
        )
        if not source:
            return
        source_path = Path(source)
        if source_path.suffix.lower() not in {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}:
            messagebox.showerror("Formato no compatible", "Selecciona WAV, MP3, M4A, AAC, FLAC u OGG.")
            return
        assets_dir = self._project_assets_dir()
        if assets_dir is None:
            return
        try:
            assets_dir.mkdir(parents=True, exist_ok=True)
            destination = assets_dir / ("background_music" + source_path.suffix.lower())
            shutil.copy2(source_path, destination)
            self.music_track_path = str(destination.resolve())
            self._save_scene_assets()
            self._refresh_audio_track_label()
            self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
            self.status_var.set(f"Música de fondo asignada: {destination.name}")
        except OSError as exc:
            messagebox.showerror("No se pudo copiar la música", str(exc))

    def clear_music_track(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        self.music_track_path = ""
        try:
            self._save_scene_assets()
            self._refresh_audio_track_label()
            self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
            self.status_var.set("Se quitó la música de fondo del proyecto.")
        except OSError as exc:
            messagebox.showerror("No se pudo quitar la música", str(exc))

    def add_audio_to_last_video(self):
        if self.render_running or getattr(self, "audio_mux_running", False) or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        video = self.last_export_path
        if not video or not Path(video).is_file():
            messagebox.showwarning(
                "No hay vídeo reciente",
                "Este proyecto no tiene un último vídeo disponible. Exporta un MP4 primero o selecciónalo en VISTA PREVIA."
            )
            return
        voice = self.audio_track_path if self.audio_track_path and Path(self.audio_track_path).is_file() else ""
        music = self.music_track_path if self.music_track_path and Path(self.music_track_path).is_file() else ""
        if not voice and not music:
            messagebox.showwarning("No hay audio", "Genera/importa una narración o importa música de fondo primero.")
            return
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            selected = filedialog.askopenfilename(
                title="Selecciona ffmpeg.exe",
                filetypes=[("FFmpeg ejecutable", "ffmpeg.exe"), ("Ejecutables", "*.exe")]
            )
            if not selected or Path(selected).name.lower() != "ffmpeg.exe":
                messagebox.showerror("FFmpeg no encontrado", "Selecciona el archivo ffmpeg.exe para añadir el audio.")
                return
            ffmpeg = selected
        source_path = Path(video).resolve()
        output = filedialog.asksaveasfilename(
            title="Guardar vídeo con audio",
            defaultextension=".mp4",
            filetypes=[("Vídeo MP4", "*.mp4")],
            initialfile=f"{source_path.stem}_con_audio.mp4",
            initialdir=str(source_path.parent)
        )
        if not output:
            return
        output_path = Path(output).resolve()
        if output_path == source_path:
            messagebox.showwarning("Elige otro nombre", "Guarda el vídeo con audio en un archivo nuevo para conservar el original.")
            return
        loop_music = bool(self.loop_music_var.get()) if self.loop_music_var is not None else True
        project_id = self.current_id
        self.audio_mux_running = True
        self.status_var.set("Añadiendo narración y música al último vídeo sin volver a renderizar las imágenes…")
        self.progress_label_var.set("Mezclando audio con el último vídeo")
        self.progress_detail_var.set("FFmpeg está copiando el vídeo y procesando las pistas de sonido.")
        threading.Thread(
            target=self._add_audio_to_video_worker,
            args=(ffmpeg, str(source_path), str(output_path), voice, music, loop_music, project_id),
            daemon=True
        ).start()

    def _add_audio_to_video_worker(self, ffmpeg, source, output, voice, music, loop_music, project_id):
        try:
            cmd = [ffmpeg, "-y", "-i", source]
            voice_index = None
            music_index = None
            next_index = 1
            if voice:
                voice_index = next_index
                cmd.extend(["-i", voice])
                next_index += 1
            if music:
                if loop_music:
                    cmd.extend(["-stream_loop", "-1"])
                music_index = next_index
                cmd.extend(["-i", music])
            graph = build_audio_filter_graph(
                bool(voice), bool(music), voice_index, music_index,
                voice_gain=1.0, music_gain=0.18
            )
            cmd.extend(["-map", "0:v:0", "-filter_complex", graph, "-map", "[aout]",
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                        "-shortest", "-movflags", "+faststart", output])
            log_path = Path(output).with_suffix(".audio-mix.log")
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                result = subprocess.run(
                    cmd, stdout=subprocess.DEVNULL, stderr=log,
                    timeout=60 * 60 * 4, creationflags=creationflags
                )
            if result.returncode != 0 or not Path(output).is_file() or Path(output).stat().st_size == 0:
                detail = log_path.read_text(encoding="utf-8", errors="replace")[-2600:]
                raise RuntimeError(f"FFmpeg no pudo mezclar el audio.\n{detail}")
            self.generation_queue.put(("audio_mux_done", output, project_id))
        except Exception as exc:
            self.generation_queue.put(("audio_mux_error", str(exc)))

    def _step_preview_scene(self, delta):
        total = len(getattr(self, "scene_data", []))
        if not total:
            self.preview_status_var.set("Genera o abre un guion para navegar por las escenas.")
            self._render_preview_frame()
            return
        current = getattr(self, "timeline_selected_scene", 1)
        target = max(1, min(total, current + delta))
        self.timeline_selected_scene = target
        item = f"scene_{target}"
        if hasattr(self, "scene_outline") and item in self.scene_outline.get_children(""):
            self.scene_outline.selection_set(item)
            self.scene_outline.see(item)
        self._render_preview_frame()

    def _render_preview_frame(self):
        """Draw current scene artwork/storyboard into both monitor surfaces."""
        canvases = [getattr(self, "preview_canvas", None),
                    getattr(self, "preview_tab_canvas", None)]
        number = max(1, int(getattr(self, "timeline_selected_scene", 1)))
        scenes = getattr(self, "scene_data", [])
        image_path = getattr(self, "scene_assets", {}).get(str(number), "")
        if not hasattr(self, "_preview_photos"):
            self._preview_photos = {}
        for canvas in canvases:
            if canvas is None:
                continue
            if canvas is getattr(self, "preview_canvas", None) and getattr(self, "preview_player_active", False):
                continue
            try:
                if not canvas.winfo_exists():
                    continue
                canvas.delete("all")
                width = max(320, canvas.winfo_width())
                height = max(150, canvas.winfo_height())
                if image_path and Path(image_path).is_file():
                    try:
                        from PIL import Image, ImageTk
                        with Image.open(image_path) as source:
                            image = source.convert("RGB")
                        image.thumbnail((max(100, width - 24), max(80, height - 24)), Image.Resampling.LANCZOS)
                        photo = ImageTk.PhotoImage(image)
                        self._preview_photos[str(canvas)] = photo
                        canvas.create_image(width // 2, height // 2, image=photo, anchor="center")
                        canvas.create_rectangle(8, 8, width - 8, height - 8, outline="#2b527b", width=1)
                        canvas.create_rectangle(8, height - 27, width - 8, height - 8,
                                                fill="#07111f", outline="#07111f")
                        title = scenes[number - 1].get("title", f"Escena {number}") if number <= len(scenes) else "Imagen de referencia"
                        canvas.create_text(18, height - 17, text=f"ESCENA {number:02d}  ·  {title[:72]}",
                                           anchor="w", fill="#d8eaff", font=("Segoe UI", 8, "bold"))
                    except Exception:
                        canvas.create_text(width // 2, height // 2,
                            text="Imagen asignada\nNo se pudo decodificar la imagen",
                            fill="#a8bdd7", font=("Segoe UI", 11), justify="center")
                elif scenes and number <= len(scenes):
                    scene = scenes[number - 1]
                    canvas.create_rectangle(8, 8, width - 8, height - 8,
                                            fill="#101d30", outline="#24466c", width=2)
                    canvas.create_text(width // 2, height * 0.24,
                                       text=f"STORYBOARD  /  ESCENA {number:02d}",
                                       fill="#70a7ff", font=("Segoe UI", 9, "bold"))
                    title = scene.get("title", f"Escena {number}")
                    canvas.create_text(width // 2, height * 0.45, text=title[:90], width=width - 70,
                                       fill="#f2f7ff", font=("Segoe UI", 15 if height > 200 else 12, "bold"),
                                       justify="center")
                    body = re.sub(r"\s+", " ", scene.get("text", scene.get("content", ""))).strip()
                    if not body:
                        body = "Asigna una ilustración a esta escena para visualizar su composición."
                    canvas.create_text(width // 2, height * 0.69, text=body[:220], width=width - 80,
                                       fill="#a9bad0", font=("Segoe UI", 9), justify="center")
                    canvas.create_text(width // 2, height * 0.89, text="MARC  •  MONITOR DE STORYBOARD",
                                       fill="#47749e", font=("Segoe UI", 8, "bold"))
                else:
                    canvas.create_rectangle(8, 8, width - 8, height - 8,
                                            fill="#101d30", outline="#24466c", width=2)
                    canvas.create_text(width // 2, height * 0.42, text="MARC  /  VIDEO STUDIO",
                                       fill="#168bff", font=("Segoe UI", 18, "bold"))
                    canvas.create_text(width // 2, height * 0.60,
                                       text="Genera un guion para construir el storyboard",
                                       fill="#a9bad0", font=("Segoe UI", 10))
            except tk.TclError:
                continue
        if hasattr(self, "preview_scene_var"):
            self.preview_scene_var.set(
                f"ESCENA {number:02d} / {len(scenes):02d}" if scenes else "STORYBOARD · SIN ESCENAS"
            )
        if hasattr(self, "preview_scene_title_var"):
            if scenes and number <= len(scenes):
                scene = scenes[number - 1]
                self.preview_scene_title_var.set(scene.get("title", f"Escena {number}"))
                summary = re.sub(r"\s+", " ", scene.get("text", "")).strip()
                self.preview_scene_text_var.set(summary[:420] or "Esta escena todavía no tiene texto.")
            else:
                self.preview_scene_title_var.set("Genera un guion")
                self.preview_scene_text_var.set("El resumen de la escena y su referencia visual aparecerán aquí.")

    def _ensure_vlc_player(self):
        """Initialize optional embedded VLC playback; external playback remains the fallback."""
        if self._vlc_player is not None:
            return True
        try:
            if os.name == "nt":
                candidates = []
                for root in (
                    os.environ.get("ProgramFiles", r"C:\Program Files"),
                    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
                    str(Path.home() / "AppData/Local/Programs"),
                ):
                    candidates.extend((Path(root) / "VideoLAN" / "VLC", Path(root) / "VLC"))
                for folder in candidates:
                    if (folder / "libvlc.dll").is_file():
                        os.environ["PATH"] = str(folder) + os.pathsep + os.environ.get("PATH", "")
                        if hasattr(os, "add_dll_directory"):
                            try:
                                self._vlc_dll_dir_handle = os.add_dll_directory(str(folder))
                            except OSError:
                                pass
                        break
            import vlc
            self._vlc_module = vlc
            self._vlc_instance = vlc.Instance("--quiet", "--no-video-title-show")
            if self._vlc_instance is None:
                raise RuntimeError("VLC no pudo inicializar su motor.")
            self._vlc_player = self._vlc_instance.media_player_new()
            return self._vlc_player is not None
        except Exception as exc:
            self._vlc_instance = None
            self._vlc_player = None
            self._vlc_error = str(exc)
            return False

    def play_preview_video(self):
        if self.render_running:
            self.preview_playback_status_var.set("El montaje todavía se está renderizando; podrás reproducirlo al terminar.")
            return
        if self.preview_player_active and self._vlc_player is not None:
            try:
                state = self._vlc_player.get_state()
                if state == self._vlc_module.State.Paused:
                    self._vlc_player.play()
                    self.preview_playback_status_var.set("Reanudando vídeo dentro de MARC")
                    self._schedule_preview_poll()
                    return
                if self._vlc_player.is_playing():
                    return
            except Exception:
                pass

        path = ""
        if self.manual_preview_path and Path(self.manual_preview_path).is_file():
            path = self.manual_preview_path
        elif self.preview_render_path and Path(self.preview_render_path).is_file():
            if self.preview_render_signature == self._current_preview_signature():
                path = self.preview_render_path
            else:
                self.preview_playback_status_var.set("El montaje cambió · generando una vista previa actualizada…")
                self.preview_render_path = ""
                self.preview_render_signature = ""
                self._start_video_render(preview=True)
                return
        if not path:
            # The monitor's play button starts a draft render when there is no current preview.
            # Old final exports and unrelated files remain available via the explicit file-selection controls.
            self.preview_playback_status_var.set("Preparando el vídeo de revisión dentro de MARC…")
            self._start_video_render(preview=True)
            return
        if not self._ensure_vlc_player():
            detail = getattr(self, "_vlc_error", "No se encontró el motor VLC.")
            answer = messagebox.askyesno(
                "Reproducción integrada no disponible",
                "Para reproducir dentro de MARC, instala VLC Media Player de 64 bits y vuelve a intentarlo.\n\n"
                f"Detalle: {detail}\n\n¿Abrir este MP4 en el reproductor externo de Windows?"
            )
            if answer:
                self.open_video_externally(path)
            return
        try:
            self.preview_video_host.grid()
            self.preview_video_host.update_idletasks()
            if os.name == "nt":
                self._vlc_player.set_hwnd(self.preview_video_host.winfo_id())
            elif platform.system() == "Darwin":
                self._vlc_player.set_nsobject(self.preview_video_host.winfo_id())
            else:
                self._vlc_player.set_xwindow(self.preview_video_host.winfo_id())
            media = self._vlc_instance.media_new(str(Path(path).resolve()))
            self._vlc_player.set_media(media)
            self.preview_canvas.delete("all")
            self.preview_player_active = True
            self._vlc_player.play()
            self.preview_playback_status_var.set(f"Reproduciendo dentro de MARC · {Path(path).name}")
            self.preview_status_var.set(f"Monitor integrado: {Path(path).name}")
            self._schedule_preview_poll()
        except Exception as exc:
            self.preview_player_active = False
            self.preview_video_host.grid_remove()
            self._render_preview_frame()
            messagebox.showerror("No se pudo iniciar la reproducción integrada", str(exc))

    def pause_preview_video(self):
        if self._vlc_player is not None and self.preview_player_active:
            try:
                self._vlc_player.pause()
                self.preview_playback_status_var.set("Vídeo en pausa")
            except Exception as exc:
                self.preview_playback_status_var.set(f"No se pudo pausar el vídeo: {exc}")

    def stop_preview_video(self):
        if self._vlc_player is not None:
            try:
                self._vlc_player.stop()
            except Exception:
                pass
        self.preview_player_active = False
        if hasattr(self, "preview_video_host"):
            self.preview_video_host.grid_remove()
        if hasattr(self, "preview_seek_var"):
            self._updating_preview_seek = True
            self.preview_seek_var.set(0)
            self._updating_preview_seek = False
            self.preview_time_var.set("00:00 / 00:00")
        if hasattr(self, "preview_playback_status_var"):
            self.preview_playback_status_var.set("Reproducción detenida · monitor de storyboard")
        self._render_preview_frame()

    def _seek_preview_video(self, value):
        if self._updating_preview_seek or not self.preview_player_active or self._vlc_player is None:
            return
        if getattr(self, "_seeking_preview", False):
            try:
                length = self._vlc_player.get_length()
                if length > 0:
                    self._vlc_player.set_time(int(length * float(value) / 1000))
            except Exception:
                pass

    def _schedule_preview_poll(self):
        if self.preview_player_active and not self._preview_poll_pending:
            self._preview_poll_pending = True
            self.after(150, self._poll_preview_playback)

    def _poll_preview_playback(self):
        self._preview_poll_pending = False
        if not self.preview_player_active or self._vlc_player is None:
            return
        try:
            state = self._vlc_player.get_state()
            length = max(0, int(self._vlc_player.get_length()))
            current = max(0, int(self._vlc_player.get_time()))
            if not getattr(self, "_seeking_preview", False) and length > 0:
                self._updating_preview_seek = True
                self.preview_seek_var.set(min(1000, current * 1000 / length))
                self._updating_preview_seek = False
            if length > 0:
                self.preview_time_var.set(
                    f"{current // 60000:02d}:{(current // 1000) % 60:02d} / "
                    f"{length // 60000:02d}:{(length // 1000) % 60:02d}"
                )
            vlc_state = self._vlc_module.State
            if state == vlc_state.Ended:
                self.stop_preview_video()
                self.preview_playback_status_var.set("Vídeo finalizado")
                return
            if state == vlc_state.Error:
                self.stop_preview_video()
                self.preview_playback_status_var.set("El motor VLC notificó un error de reproducción.")
                return
        except Exception as exc:
            self.preview_playback_status_var.set(f"Error de reproducción: {exc}")
        self._schedule_preview_poll()

    def open_video_externally(self, path):
        try:
            path = str(Path(path).resolve())
            if os.name == "nt":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self.status_var.set(f"Abriendo vídeo en el reproductor del sistema: {Path(path).name}")
        except (OSError, AttributeError) as exc:
            messagebox.showerror("No se pudo abrir el vídeo", str(exc))

    def choose_preview_video(self):
        path = filedialog.askopenfilename(
            title="Selecciona un vídeo para previsualizar",
            filetypes=[("Vídeos", "*.mp4 *.mov *.mkv *.webm"), ("Todos los archivos", "*.*")]
        )
        if path:
            self.manual_preview_path = str(Path(path).resolve())
            self.last_export_path = self.manual_preview_path
            self.preview_status_var.set(f"Vídeo seleccionado: {self.manual_preview_path}")
            self.preview_playback_status_var.set(f"Listo para reproducir · {Path(path).name}")

    def open_last_video(self):
        path = self.last_export_path
        if not path or not Path(path).is_file():
            self.choose_preview_video()
            path = self.last_export_path
        if not path or not Path(path).is_file():
            return
        self.open_video_externally(path)

    def _find_comfyui_launcher(self):
        """Locate the official portable Windows launch scripts without scanning whole drives."""
        home = Path.home()
        roots = []
        configured = os.environ.get("MARC_COMFYUI_DIR", "").strip()
        if configured:
            roots.append(Path(configured).expanduser())
        roots.extend([
            ROOT / "ComfyUI_windows_portable",
            ROOT / "ComfyUI_windows_portable_nvidia",
            home / "ComfyUI_windows_portable",
            home / "ComfyUI_windows_portable_nvidia",
            home / "Downloads" / "ComfyUI_windows_portable",
            home / "Downloads" / "ComfyUI_windows_portable_nvidia",
            home / "Desktop" / "ComfyUI_windows_portable",
            home / "Desktop" / "ComfyUI_windows_portable_nvidia",
        ])
        seen = set()
        for root in roots:
            try:
                root = root.resolve()
            except OSError:
                continue
            candidate_roots = [root]
            if root.name.casefold() == "comfyui":
                candidate_roots.append(root.parent)
            for folder in candidate_roots:
                if str(folder).casefold() in seen:
                    continue
                seen.add(str(folder).casefold())
                for filename in ("run_nvidia_gpu.bat", "run_cpu.bat"):
                    launcher = folder / filename
                    if launcher.is_file():
                        return launcher
        return None

    def _launch_comfyui(self, launcher):
        """Launch a verified portable ComfyUI startup script in its own console."""
        try:
            subprocess.Popen(
                ["cmd.exe", "/c", str(launcher)],
                cwd=str(launcher.parent),
                creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
            )
            self.status_var.set("ComfyUI está iniciando. Mantén abierta su ventana y espera a que indique la dirección local.")
            self.image_ai_status_var.set("ComfyUI iniciándose · buscando el servidor…")
            self.after(12000, lambda: self.detect_image_models(quiet=False))
        except OSError as exc:
            messagebox.showerror(
                "No se pudo iniciar ComfyUI",
                f"No fue posible ejecutar el lanzador encontrado:\n{launcher}\n\n{exc}"
            )

    def start_comfyui(self):
        """Start ComfyUI portable if found, allow folder selection, or open its official installer guide."""
        if self.comfy_available:
            messagebox.showinfo(
                "ComfyUI ya está conectado",
                f"MARC ya detectó el motor visual en {self.comfy_url}. Selecciona un checkpoint y genera la ilustración."
            )
            return

        launcher = self._find_comfyui_launcher() if os.name == "nt" else None
        if launcher:
            self._launch_comfyui(launcher)
            return

        if os.name == "nt" and messagebox.askyesno(
            "Buscar ComfyUI Portable",
            "No encontré automáticamente ComfyUI Portable. Si ya lo descargaste, puedes seleccionar ahora la carpeta donde lo extrajiste. "
            "Responde No para abrir la guía oficial de instalación."
        ):
            selected_dir = filedialog.askdirectory(
                title="Selecciona la carpeta ComfyUI_windows_portable",
                initialdir=str(Path.home()),
                mustexist=True
            )
            if selected_dir:
                os.environ["MARC_COMFYUI_DIR"] = selected_dir
                launcher = self._find_comfyui_launcher()
                if launcher:
                    self._launch_comfyui(launcher)
                    return
                messagebox.showwarning(
                    "No se encontró el lanzador",
                    "La carpeta seleccionada no contiene run_nvidia_gpu.bat ni run_cpu.bat. "
                    "Selecciona la carpeta principal de ComfyUI Portable, no su subcarpeta models."
                )
                return
            return

        message = (
            "Ollama/Qwen genera el guion, pero no crea archivos de imagen. Para ilustrar las escenas necesitas "
            "ComfyUI y un checkpoint compatible. La aplicación no los descarga automáticamente porque pueden ocupar varios GB."
        )
        if messagebox.askyesno(
            "Configurar el motor de imágenes",
            message + "\n\n¿Quieres abrir la guía oficial de instalación de ComfyUI para Windows?"
        ):
            webbrowser.open("https://docs.comfy.org/installation/comfyui_portable_windows")

    def open_image_setup(self):
        """Open the scenes tab and start checking the local image engine."""
        try:
            self.studio_tabs.select(self.scenes_tab)
            self.image_ai_status_var.set("Comprobando el motor de imágenes…")
            self.detect_image_models(quiet=False)
        except Exception as exc:
            messagebox.showerror(
                "No se pudo abrir la configuración de imágenes",
                f"Vuelve a abrir MARC e inténtalo de nuevo.\n\nDetalle: {exc}"
            )

    def _preferred_image_checkpoint(self, models):
        """Prefer a style-tuned checkpoint when several are installed, not an arbitrary first item."""
        names = [str(item).strip() for item in (models or []) if str(item).strip()]
        if not names:
            return ""
        style = str(self.drawing_style_var.get() or "").casefold()
        if "manga" in style:
            preferences = ("manga", "anime", "animagine", "anything", "meina", "counterfeit")
        elif "anime" in style:
            preferences = ("animagine", "illustrious", "noobai", "anything", "meina", "counterfeit", "anime", "pony")
        elif "cartoon" in style:
            preferences = ("cartoon", "illustration", "animagine", "dreamshaper", "comic")
        elif "acuarela" in style:
            preferences = ("watercolor", "storybook", "illustration", "dreamshaper")
        elif "pixel" in style:
            preferences = ("pixel", "game-art", "sprites")
        elif "3d" in style:
            preferences = ("3d", "dreamshaper", "juggernaut", "sdxl")
        elif "realista" in style:
            preferences = ("juggernaut", "realvis", "epicrealism", "photoreal", "realistic", "sdxl")
        elif "cómic" in style:
            preferences = ("comic", "graphic", "illustration", "dreamshaper")
        else:
            preferences = ("illustration", "dreamshaper", "juggernaut")
        for term in preferences:
            candidate = next((name for name in names if term in name.casefold()), None)
            if candidate:
                return candidate
        # If filenames are opaque, prefer a tuned/non-base checkpoint when one
        # exists instead of the generic SD 1.5 base model.
        non_base = next(
            (name for name in names if not any(
                marker in name.casefold()
                for marker in ("v1-5-pruned-emaonly", "sd_v1-5", "base-model")
            )),
            None,
        )
        return non_base or names[0]

    def update_image_model_guidance(self):
        """Explain when a generic base checkpoint is likely to produce generic artwork."""
        selected = str(self.image_model_var.get() or "").strip()
        if not selected:
            return
        model = selected.casefold()
        style = str(self.drawing_style_var.get() or "").casefold()
        if "v1-5-pruned-emaonly" in model or "sd_v1-5" in model or "base" in Path(selected).stem.casefold():
            self.image_ai_status_var.set(
                "Checkpoint base detectado: suele producir imágenes genéricas. "
                "Para mejorar, instala un checkpoint afinado para tu estilo (anime, ilustración o realismo) y selecciónalo aquí."
            )
        elif "anime" in style and not any(term in model for term in ("anime", "animagine", "anything", "meina", "counterfeit")):
            self.image_ai_status_var.set(
                "Para anime, un checkpoint especializado suele dar mejores resultados que un modelo general. "
                "La calidad también depende de memoria y resolución."
            )
        else:
            self.image_ai_status_var.set(
                f"Checkpoint seleccionado: {selected}. MARC aplicará encuadre, continuidad visual y movimiento de cámara."
            )

    def detect_image_models(self, quiet=False):
        if self.image_generation_running:
            return
        self.image_ai_status_var.set("Buscando el motor visual local…")
        threading.Thread(target=self._detect_image_models_worker, args=(quiet,), daemon=True).start()

    def _comfy_candidate_urls(self):
        """Return unique local ComfyUI URLs, honoring an explicit environment override."""
        candidates = [
            os.environ.get("MARC_COMFYUI_URL", "").strip(),
            getattr(self, "comfy_url", ""),
            "http://127.0.0.1:8188",
            "http://localhost:8188",
        ]
        candidates.extend(f"http://127.0.0.1:{port}" for port in COMFYUI_FALLBACK_PORTS)
        normalized = []
        for value in candidates:
            value = str(value or "").strip().rstrip("/")
            if value and value not in normalized:
                normalized.append(value)
        return normalized

    def _detect_image_models_worker(self, quiet=False):
        """Find a working ComfyUI API and distinguish missing checkpoints from connection errors."""
        errors = []
        for base_url in self._comfy_candidate_urls():
            try:
                request = urllib.request.Request(
                    base_url + "/object_info/CheckpointLoaderSimple",
                    headers={"Accept": "application/json"}
                )
                with urllib.request.urlopen(request, timeout=2.5) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                node = payload.get("CheckpointLoaderSimple") if isinstance(payload, dict) else None
                if not isinstance(node, dict):
                    raise RuntimeError("el servidor respondió, pero no expone el nodo de checkpoints de ComfyUI")
                required = node.get("input", {}).get("required", {})
                option = required.get("ckpt_name", [])
                models = option[0] if option and isinstance(option[0], list) else []
                models = [str(model) for model in models]
                upscalers = ["(Sin mejora)"]
                try:
                    upscale_request = urllib.request.Request(
                        base_url + "/object_info/UpscaleModelLoader",
                        headers={"Accept": "application/json"}
                    )
                    with urllib.request.urlopen(upscale_request, timeout=2.5) as response:
                        upscale_payload = json.loads(response.read().decode("utf-8"))
                    upscale_node = upscale_payload.get("UpscaleModelLoader", {})
                    upscale_required = upscale_node.get("input", {}).get("required", {})
                    upscale_options = upscale_required.get("model_name", [])
                    if upscale_options and isinstance(upscale_options[0], list):
                        upscalers.extend(str(name) for name in upscale_options[0] if str(name).strip())
                except Exception:
                    # Older/custom ComfyUI builds may not expose the optional upscaler node.
                    pass
                self.generation_queue.put(("image_models", models, quiet, base_url, upscalers))
                return
            except Exception as exc:
                detail = str(exc).strip().replace("\n", " ")
                errors.append(f"{base_url}: {detail[:180] or type(exc).__name__}")

        # Report the text engine separately to avoid confusing Ollama with image generation.
        ollama_note = "Ollama no responde en 127.0.0.1:11434."
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1.5) as response:
                tags = json.loads(response.read().decode("utf-8"))
            model_names = [
                str(item.get("name", "")) for item in tags.get("models", [])
                if isinstance(item, dict) and item.get("name")
            ]
            ollama_note = "Ollama responde (" + (", ".join(model_names[:4]) or "sin modelos listados") + "); este servicio genera texto, no imágenes."
        except Exception:
            pass
        detail = (
            "No se encontró una API de ComfyUI en los puertos locales habituales. "
            + ollama_note + "\n\n"
            + "Para generar imágenes, inicia ComfyUI y descarga al menos un checkpoint compatible. "
            + "MARC no puede convertir Qwen/Ollama en un generador de imágenes por sí solo. "
            + "Si ComfyUI utiliza otra dirección, define MARC_COMFYUI_URL antes de abrir MARC.\n\n"
            + "Últimos intentos: " + " | ".join(errors[-4:])
        )
        self.generation_queue.put(("image_models_error", detail, quiet))

    def generate_scene_image(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Completa el título y la premisa antes de generar imágenes.")
            return
        self.save_project(quiet=True)
        if not self._existing_approval():
            messagebox.showwarning(
                "Revisa el guion antes de generar imágenes",
                "Primero revisa el guion y el estilo seleccionado en «Dirección visual». "
                "Pulsa «Aprobar» cuando estés conforme; después podrás generar ilustraciones para esta versión."
            )
            return
        scene_number = self._scene_selection_number()
        if scene_number is None or not self.scene_data or scene_number > len(self.scene_data):
            messagebox.showinfo("Selecciona una escena", "Genera o abre un guion y selecciona la escena que quieras ilustrar.")
            return
        model_name = self.image_model_var.get().strip()
        if not model_name:
            messagebox.showinfo(
                "Falta el modelo local",
                "Pulsa «Detectar ComfyUI». Debes abrir ComfyUI localmente y tener al menos un checkpoint instalado."
            )
            self.detect_image_models(quiet=False)
            return
        idx = scene_number - 1
        scene = dict(self.scene_data[idx])
        project = self.conn.execute("SELECT * FROM projects WHERE id=?", (self.current_id,)).fetchone()
        if not project:
            messagebox.showerror("Proyecto no encontrado", "Vuelve a abrir el proyecto e inténtalo otra vez.")
            return
        self.image_generation_running = True
        self._set_image_state(True)
        self.progressbar.configure(mode="indeterminate")
        self.progressbar.start(12)
        self.progress_label_var.set(f"Generando ilustración para la escena {idx + 1}")
        chosen_upscaler = self.image_upscale_var.get().strip()
        if chosen_upscaler == "(Sin mejora)":
            chosen_upscaler = ""
        self.progress_detail_var.set(
            "IA local · ComfyUI" + (f" · mejora IA: {chosen_upscaler}" if chosen_upscaler else "")
        )
        self.status_var.set(
            "Generando una ilustración local. La mejora IA opcional aumenta resolución, pero añade tiempo de procesamiento."
            if chosen_upscaler else
            "Generando una ilustración local. En la GTX 750 puede tardar varios minutos."
        )
        args = (
            int(self.current_id), idx + 1, scene, model_name,
            self.drawing_style_var.get(), project["platform"], project["topic"],
            project["story_bible"] or "", project["continuity_state"] or "", chosen_upscaler
        )
        threading.Thread(target=self._generate_scene_image_worker, args=args, daemon=True).start()

    def _set_image_state(self, active):
        state = "disabled" if active else "normal"
        self.cancel_button.configure(state="normal" if self.generation_running else "disabled")
        self.cancel_render_button.configure(state="normal" if self.render_running else "disabled")
        for button in (self.generate_button, self.new_project_button, self.save_button, self.approve_button,
                       self.export_button, self.preview_render_button, self.delete_button, self.assign_image_button,
                       self.clear_image_button, self.refresh_scenes_button,
                       self.select_audio_button, self.clear_audio_button,
                       self.detect_models_button, self.start_comfyui_button, self.generate_image_button, self.generate_missing_images_button,
                       self.image_setup_button,
                       self.detect_voice_button, self.generate_voice_button, self.inspector_assign_image_button,
                       self.inspector_generate_image_button, self.inspector_duration_button,
                       self.export_srt_button, self.select_music_button, self.clear_music_button):
            button.configure(state=state)
        self.cancel_voice_button.configure(state="disabled")
        self.voice_combo.configure(state="disabled" if active else "readonly")
        self.project_list.configure(state=state)
        self._set_scene_list_state(active)
        self.cancel_button.configure(state="normal" if self.generation_running else "disabled")
        self.cancel_render_button.configure(state="normal" if self.render_running else "disabled")
        self.image_model_combo.configure(state="disabled" if active else "readonly")
        self.image_upscale_combo.configure(state="disabled" if active else "readonly")
        for widget, idle_state in self.form_widgets:
            widget.configure(state="disabled" if active else idle_state)
        self.script_text.configure(state="disabled" if active else "normal")
        if not active:
            self.progressbar.stop()
            self.progressbar.configure(mode="determinate")

    def _generate_scene_image_worker(self, project_id, scene_number, scene, checkpoint, drawing_style, platform_name, project_topic, story_bible="", continuity_state="", upscale_model=""):
        base_url = str(getattr(self, "comfy_url", COMFYUI_URL) or COMFYUI_URL).rstrip("/")
        try:
            self.generation_queue.put(("image_progress", scene_number, f"Preparando el prompt visual · ComfyUI en {base_url}…"))
            style_prompts = {
                "Anime cinematográfico": "cinematic Japanese anime film frame, expressive character acting, dramatic lighting, detailed anime background art",
                "Manga en blanco y negro": "black and white manga illustration, inked line art, screentones, expressive panels, high contrast",
                "Cartoon occidental": "polished western animated series frame, appealing shapes, clear silhouettes, rich colors",
                "Cómic realista": "realistic graphic novel illustration, detailed ink and painterly shading, cinematic composition",
                "Acuarela ilustrada": "hand-painted watercolor storybook illustration, delicate paper texture, expressive brushwork",
                "Pixel art": "high-quality pixel art scene, coherent pixel grid, carefully limited palette, detailed 16-bit game-art composition",
                "3D estilizado": "stylized 3D animated film still, detailed materials, cinematic light, expressive characters",
                "Realismo cinematográfico": "cinematic photorealistic movie still, natural dramatic lighting, carefully composed frame",
            }
            style_prompt = style_prompts.get(drawing_style, "cinematic illustrated story scene")
            # Pixnarr-inspired scene brief: apply only relevant character canon to this shot,
            # rather than forcing the opening of the entire story bible into every image prompt.
            visual_brief = build_scene_visual_brief(
                scene, story_bible=story_bible, continuity_state=continuity_state
            )
            story_excerpt = visual_brief["excerpt"]
            visual_description = ""
            canon_reference = visual_brief["canon_reference"]
            continuity_reference = visual_brief["continuity_reference"]
            scene_narration = visual_brief["narration"]
            scene_dialogue = " | ".join(visual_brief["dialogue"])[:900]
            scene_speakers = ", ".join(visual_brief["speakers"]) or "none explicitly labelled"
            # Batch mode prepares prompts in grouped Ollama calls before image rendering.
            visual_description = str(getattr(self, "image_prompt_cache", {}).pop(str(scene_number), "")).strip()
            if not visual_description:
                try:
                    visual_description = self._ollama_request(
                        "Act as a cinematic storyboard artist and image-prompt director. Convert this one Spanish story scene "
                        "into one concise English prompt for a SINGLE still image, not a sequence or collage. "
                        "Describe the visible subjects and their action, facial expression, body language, wardrobe, setting, time/weather, "
                        "foreground/background, camera framing/angle, lighting and mood. The scene excerpt determines what is happening. "
                        "Treat the canon as a lookup reference: apply only the visual profile of characters relevant to this scene and only "
                        "locations or props that the excerpt calls for. Do not copy unrelated profiles into the image and do not invent a new design. "
                        "Speaker labels are dialogue context, not proof that every speaker must appear on screen. Never render dialogue as written text. "
                        "Preserve established age range, facial features, hairstyle, clothing cues and signature objects when relevant. "
                        "Return only the prompt, without headings, markdown or explanation. "
                        f"Series premise: {project_topic}. Scene title: {visual_brief['title']}. "
                        f"Narration/action: {scene_narration or story_excerpt}. "
                        f"Dialogue context for emotion only: {scene_dialogue or 'No explicit dialogue labels'}. "
                        f"Speaker labels in this scene: {scene_speakers}. "
                        f"Relevant canonical character reference: {canon_reference or 'No character profile was available'}. "
                        f"Previous episode state: {continuity_reference or 'No previous episode state supplied'}.",
                        max_tokens=280
                    )
                except Exception:
                    visual_description = story_excerpt
            prompt = build_cinematic_image_prompt(
                style_prompt=style_prompt,
                visual_description=visual_description or story_excerpt,
                scene_number=scene_number,
                title=visual_brief["title"],
                canon_reference=canon_reference,
                continuity_reference=continuity_reference,
            )
            negative = (
                "text, subtitles, letters, watermark, logo, blurry, low resolution, muddy detail, "
                "flat lighting, washed out colors, malformed hands, extra fingers, extra limbs, "
                "duplicate people, duplicated face, deformed face, bad anatomy, plastic skin, "
                "cropped head, cut-off subject, random accessories, incorrect costume, compression artifacts"
            )
            # More usable source pixels than the previous 288x512 preset, while staying
            # below typical SDXL memory demands for older GPUs such as the GTX 750.
            if "TikTok" in platform_name or "9:16" in platform_name:
                width, height = 384, 672
            elif "1:1" in platform_name:
                width, height = 512, 512
            else:
                width, height = 672, 384
            client_id = os.urandom(12).hex()
            workflow = build_comfy_image_workflow(
                checkpoint=checkpoint,
                prompt=prompt,
                negative_prompt=negative,
                width=width,
                height=height,
                scene_number=scene_number,
                upscale_model=upscale_model,
                seed=random.randint(1, 2**31 - 1),
                steps=22,
                cfg=6.5,
            )
            body = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")
            request = urllib.request.Request(
                base_url + "/prompt", data=body,
                headers={"Content-Type": "application/json"}, method="POST"
            )
            with urllib.request.urlopen(request, timeout=15) as response:
                queued = json.loads(response.read().decode("utf-8"))
            prompt_id = queued.get("prompt_id")
            if not prompt_id:
                raise RuntimeError("ComfyUI no aceptó el flujo de imagen: " + json.dumps(queued, ensure_ascii=False)[:1600])
            self.generation_queue.put(("image_progress", scene_number, "ComfyUI está renderizando la ilustración…"))
            deadline = time.monotonic() + 2700
            outputs = None
            last_status_update = time.monotonic()
            while time.monotonic() < deadline:
                request = urllib.request.Request(
                    base_url + "/history/" + str(prompt_id),
                    headers={"Accept": "application/json"}
                )
                with urllib.request.urlopen(request, timeout=15) as response:
                    history = json.loads(response.read().decode("utf-8"))
                entry = history.get(prompt_id, history if "outputs" in history else {})
                if entry:
                    candidate_outputs = entry.get("outputs", {})
                    images = [
                        image_data for node_output in candidate_outputs.values()
                        for image_data in node_output.get("images", [])
                    ]
                    if images:
                        outputs = images
                        break
                    state = entry.get("status", {})
                    status_text = str(state.get("status_str", "")).lower() if isinstance(state, dict) else ""
                    if status_text in {"error", "failed"}:
                        raise RuntimeError("ComfyUI indicó un error al generar la ilustración.")
                if time.monotonic() - last_status_update >= 8:
                    self.generation_queue.put(("image_progress", scene_number, "ComfyUI sigue generando… el tiempo depende del modelo y del equipo."))
                    last_status_update = time.monotonic()
                time.sleep(1.5)
            if not outputs:
                raise TimeoutError("ComfyUI no entregó una imagen en 45 minutos. Revisa su consola y la memoria de la GPU.")
            image_info = outputs[0]
            query = urlencode({
                "filename": image_info.get("filename", ""),
                "subfolder": image_info.get("subfolder", ""),
                "type": image_info.get("type", "output")
            })
            request = urllib.request.Request(base_url + "/view?" + query)
            with urllib.request.urlopen(request, timeout=60) as response:
                image_bytes = response.read()
            if not image_bytes:
                raise RuntimeError("ComfyUI devolvió una imagen vacía.")
            assets_dir = PROJECTS_DIR / str(project_id) / "assets"
            assets_dir.mkdir(parents=True, exist_ok=True)
            destination = assets_dir / f"scene_{scene_number:03d}_ai.png"
            destination.write_bytes(image_bytes)
            prompt_record = assets_dir / f"scene_{scene_number:03d}_ai_prompt.txt"
            prompt_record.write_text(
                f"Checkpoint: {checkpoint}\nEstilo: {drawing_style}\nPlataforma: {platform_name}\n"
                f"Canon aplicado: {canon_reference}\nEstado previo: {continuity_reference}\n"
                f"Prompt: {prompt}\nNegative: {negative}\n",
                encoding="utf-8"
            )
            self.generation_queue.put(("image_done", project_id, scene_number, str(destination.resolve()), prompt))
        except Exception as exc:
            self.generation_queue.put(("image_error", scene_number, str(exc)))

    def _prepare_batch_image_prompts_worker(
        self, scenes_to_plan, drawing_style, project_topic, story_bible, continuity_state
    ):
        """Prepare scene prompts in groups, falling back to scene text on model errors."""
        styles = {
            "Anime cinematográfico": "cinematic Japanese anime film frame, expressive character acting, dramatic lighting",
            "Manga en blanco y negro": "black and white manga illustration, inked line art, screentones, high contrast",
            "Cartoon occidental": "polished western animated series frame, appealing shapes, clear silhouettes",
            "Cómic realista": "realistic graphic novel illustration, detailed ink and painterly shading",
            "Acuarela ilustrada": "hand-painted watercolor storybook illustration, delicate paper texture",
            "Pixel art": "high-quality pixel art scene, coherent pixel grid, limited palette",
            "3D estilizado": "stylized 3D animated film still, detailed materials, cinematic light",
            "Realismo cinematográfico": "cinematic photorealistic movie still, natural dramatic lighting",
        }
        style_prompt = styles.get(drawing_style, "cinematic illustrated story scene")
        results = {}
        total = len(scenes_to_plan)
        chunk_size = 12
        for start in range(0, total, chunk_size):
            group = scenes_to_plan[start:start + chunk_size]
            briefs, records = {}, []
            for scene_number, scene in group:
                brief = build_scene_visual_brief(scene, story_bible, continuity_state)
                briefs[str(scene_number)] = brief
                records.append({
                    "id": str(scene_number), "title": brief["title"],
                    "action": brief["narration"] or brief["excerpt"],
                    "dialogue_emotion_only": " | ".join(brief["dialogue"])[:180],
                    "characters": brief["speakers"], "canon": brief["canon_reference"][:420],
                    "camera_direction": camera_direction_for_shot(scene_number),
                })
            self.generation_queue.put(("image_prompt_plan_progress", start, total,
                f"Preparando storyboard visual · {start}/{total} escenas"))
            generated = {}
            prompt = (
                "You are a cinematic storyboard artist. Return only a valid JSON object. "
                "Keys must be supplied scene ids; values are concise English prompts for one still image each. "
                "No markdown, collage, panels, captions, logos or watermarks. One coherent moment per image. "
                "Describe visible action, specific facial emotion, expressive body language, wardrobe, environment and lighting. "
                "Follow each record's camera_direction so successive frames use different shot sizes and angles. "
                "Use relevant character canon and preserve hair, face, clothing and recurring props across scenes. "
                "Avoid generic posed portraits; the image must show the exact story beat, not merely a character standing. "
                f"Visual style: {style_prompt}. Premise: {project_topic[:600]}. "
                "Scene records: " + json.dumps(records, ensure_ascii=False)
            )
            try:
                raw = self._ollama_request(prompt, max_tokens=min(1100, max(320, len(group) * 75)))
                left, right = raw.find("{"), raw.rfind("}")
                if left >= 0 and right > left:
                    parsed = json.loads(raw[left:right + 1])
                    if isinstance(parsed, dict):
                        generated = {str(k): str(v).strip() for k,v in parsed.items()
                                     if str(k) in briefs and isinstance(v, str) and v.strip()}
            except Exception:
                generated = {}
            for scene_number, _scene in group:
                key = str(scene_number)
                brief = briefs[key]
                results[key] = generated.get(key,
                    f"{brief['title']}. {brief['narration'] or brief['excerpt']}. "
                    f"Camera: {camera_direction_for_shot(scene_number)}. "
                    f"Characters: {', '.join(brief['speakers']) or 'only the subjects described in the action'}. "
                    "One emotionally readable cinematic frame, active body language, a clear focal point, dramatic lighting, "
                    "and consistent face, hair, costume and props.")
            done = min(total, start + len(group))
            self.generation_queue.put(("image_prompt_plan_progress", done, total,
                f"Storyboard preparado · {done}/{total} escenas"))
        self.generation_queue.put(("image_prompts_ready", results))

    def generate_missing_scene_images(self, preconfirmed=False, preview_after=False):
        """Generate missing scene illustrations sequentially through the existing ComfyUI worker."""
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Guarda el proyecto antes de generar imágenes.")
            return
        self.save_project(quiet=True)
        if not self._existing_approval():
            messagebox.showwarning(
                "Revisa el guion antes de generar imágenes",
                "Primero revisa el guion y la dirección visual y pulsa «Aprobar». "
                "La generación por lotes comenzará después de aprobar esta versión del proyecto."
            )
            return
        self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
        missing = [
            index + 1 for index in range(len(self.scene_data))
            if not (self.scene_assets.get(str(index + 1)) and Path(self.scene_assets[str(index + 1)]).is_file())
        ]
        if not missing:
            if preview_after:
                self.after(150, lambda: self._start_video_render(preview=True))
            elif not preconfirmed:
                messagebox.showinfo("Todo ilustrado", "Todas las escenas ya tienen una imagen asignada.")
            return
        if not self.image_model_var.get().strip():
            messagebox.showwarning(
                "Falta un modelo de imagen",
                "Abre ComfyUI, pulsa «Detectar ComfyUI» y selecciona un checkpoint compatible antes de generar las imágenes."
            )
            self.detect_image_models(quiet=False)
            return
        if not preconfirmed and not messagebox.askyesno(
            "Generar ilustraciones faltantes",
            f"Se generarán {len(missing)} imagen(es), una por escena sin recurso visual. "
            "En una GPU antigua el proceso puede tardar bastante. ¿Continuar?"
        ):
            return
        self._pipeline_checkpoint("storyboard", "running", "Preparando prompts para las escenas pendientes")
        self._pipeline_checkpoint("images", "running", f"Pendientes {len(missing)} ilustraciones")
        self.batch_image_queue = list(missing)
        self.batch_image_total = len(missing)
        self.batch_image_active = True
        self.preview_after_image_batch = bool(preview_after)
        self.studio_tabs.select(self.scenes_tab)
        self.image_prompt_cache = {}
        self.image_generation_running = True
        self._set_image_state(True)
        self.progressbar.configure(mode="indeterminate")
        self.progressbar.start(12)
        self.progress_label_var.set("Preparando storyboard visual")
        self.progress_detail_var.set(f"0/{len(missing)} escenas · agrupando prompts antes de crear imágenes")
        self.status_var.set(f"Preparando prompts para {len(missing)} ilustraciones; después se generarán en secuencia.")
        row = self.conn.execute("SELECT topic, story_bible, continuity_state FROM projects WHERE id=?", (self.current_id,)).fetchone()
        project_topic = str(row["topic"] or "") if row else str(self.topic_var.get() or "")
        story_bible = str(row["story_bible"] or "") if row else str(self.story_bible or "")
        continuity_state = str(row["continuity_state"] or "") if row else str(self.continuity_state or "")
        scenes_to_plan = [(number, dict(self.scene_data[number - 1])) for number in missing]
        threading.Thread(target=self._prepare_batch_image_prompts_worker,
            args=(scenes_to_plan, self.drawing_style_var.get(), project_topic, story_bible, continuity_state),
            daemon=True).start()

    def _start_next_missing_scene_image(self):
        if not self.batch_image_active:
            return
        if not self.batch_image_queue:
            self.batch_image_active = False
            self._pipeline_checkpoint("images", "completed", "Todas las ilustraciones pendientes fueron procesadas")
            total = self.batch_image_total
            self.batch_image_total = 0
            if self.preview_after_image_batch:
                self.preview_after_image_batch = False
                self.status_var.set(f"Ilustraciones listas ({total}). Iniciando vista previa del vídeo…")
                self.after(250, lambda: self._start_video_render(preview=True))
            else:
                self.image_prompt_cache = {}
                self.status_var.set(f"Generación por lotes completada: {total} ilustraciones.")
                if not getattr(self, "remote_image_batch_active", False):
                    messagebox.showinfo("Ilustraciones listas", f"Se generaron {total} ilustraciones y se asignaron a sus escenas.")
                self.remote_image_batch_active = False
            return
        scene_number = self.batch_image_queue.pop(0)
        item = f"scene_{scene_number}"
        if item not in self.scene_outline.get_children(""):
            self.batch_image_active = False
            self.batch_image_queue = []
            self.preview_after_image_batch = False
            messagebox.showerror("Escena no disponible", f"No se encontró la escena {scene_number}. Actualiza la lista e inténtalo otra vez.")
            return
        self.scene_outline.selection_set(item)
        self.scene_outline.see(item)
        self.timeline_selected_scene = scene_number
        self._render_preview_frame()
        self.status_var.set(
            f"Generando ilustración {self.batch_image_total - len(self.batch_image_queue)}/{self.batch_image_total} · escena {scene_number}"
        )
        self.generate_scene_image()

    def set_configuration_visible(self, visible):
        """Expand/collapse the story setup area to give the editor more workspace."""
        if not hasattr(self, "vertical_panes") or not hasattr(self, "controls_area"):
            return
        panes = tuple(self.vertical_panes.panes())
        pane_name = str(self.controls_area)
        is_visible = pane_name in panes
        if visible and not is_visible:
            self.vertical_panes.add(
                self.controls_area, before=self.lower_panel,
                minsize=285, width=320, stretch="never"
            )
            self.configuration_visible = True
        elif not visible and is_visible:
            self.vertical_panes.forget(self.controls_area)
            self.configuration_visible = False
        else:
            self.configuration_visible = is_visible
        if hasattr(self, "config_toggle_button"):
            self.config_toggle_button.configure(
                text="Ocultar formulario" if self.configuration_visible else "Mostrar formulario"
            )

    def toggle_configuration(self):
        self.set_configuration_visible(not getattr(self, "configuration_visible", True))

    def toggle_status_details(self):
        """Show/hide hardware diagnostics and long production estimates."""
        if not hasattr(self, "details_frame"):
            return
        if self.details_visible:
            self.details_frame.pack_forget()
            self.details_button.configure(text="＋ Diagnóstico y estimaciones")
            self.details_visible = False
        else:
            self.details_frame.pack(fill="x", pady=(2, 0))
            self.details_button.configure(text="− Ocultar detalles")
            self.details_visible = True

    def _set_story_options_expanded(self, expanded):
        """Show only essential fields by default; expose optional controls on request."""
        self.story_options_expanded = bool(expanded)
        advanced_labels = ("Tono", "Narrador", "Desenlace", "Protagonista",
                           "Conflicto central", "Modo de producción")
        for label in advanced_labels:
            cell = self.field_cells.get(label)
            if cell is not None:
                cell.grid() if self.story_options_expanded else cell.grid_remove()
        if hasattr(self, "advanced_help_label"):
            self.advanced_help_label.grid() if self.story_options_expanded else self.advanced_help_label.grid_remove()
        if hasattr(self, "story_options_button"):
            self.story_options_button.configure(
                text="− Ocultar opciones avanzadas" if self.story_options_expanded
                else "＋ Más opciones (opcional)"
            )

    def toggle_story_options(self):
        self._set_story_options_expanded(not self.story_options_expanded)

    def toggle_visual_options(self):
        """Reveal optional animation/subtitle controls only when requested."""
        self.visual_advanced_expanded = not getattr(self, "visual_advanced_expanded", False)
        for field_label in getattr(self, "visual_advanced_labels", ()):
            cell = self.field_cells.get(field_label)
            if cell is not None:
                cell.grid() if self.visual_advanced_expanded else cell.grid_remove()
        checkbutton = getattr(self, "subtitle_outline_checkbutton", None)
        if checkbutton is not None:
            checkbutton.grid() if self.visual_advanced_expanded else checkbutton.grid_remove()
        button = getattr(self, "visual_advanced_button", None)
        if button is not None:
            button.configure(
                text="− Ocultar ajustes visuales avanzados" if self.visual_advanced_expanded
                else "＋ Mostrar ajustes visuales avanzados"
            )

    def _field(self, parent, label, variable, row, col, values=None, span=1):
        cell = tk.Frame(parent, bg=self.colors["panel"])
        self.field_cells[label] = cell
        cell.grid(row=row, column=col, columnspan=span, sticky="ew", padx=4, pady=4)
        tk.Label(cell, text=label.upper(), bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(0, 4))
        if values is not None:
            widget = ttk.Combobox(cell, textvariable=variable, values=values,
                                  state="readonly", font=("Segoe UI", 9))
        else:
            widget = ttk.Entry(cell, textvariable=variable, font=("Segoe UI", 9))
        widget.pack(fill="x", ipady=2)
        self.form_widgets.append((widget, "readonly" if values is not None else "normal"))
        return widget

    def new_project(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual antes de crear otro proyecto.")
            return
        if getattr(self, "preview_player_active", False):
            self.stop_preview_video()
        self.preview_render_path = ""
        self.preview_render_signature = ""
        self.manual_preview_path = ""
        self.current_id = None
        self._creator_narration_override = ""
        self._creator_auto_narration_active = False
        self.series_key = ""
        self.episode_number = 1
        self.story_bible = ""
        self.continuity_state = ""
        self.voice_assignments = {}
        self.set_configuration_visible(True)
        self.title_var.set("")
        self.topic_var.set("")
        self.platform_var.set(list(PLATFORMS)[0])
        self.duration_var.set("10")
        self.style_var.set("Reencarnación y venganza")
        self.protagonist_var.set("")
        self.conflict_var.set("")
        self.tone_var.set("Dramático e intenso")
        self.narrator_var.set("Tercera persona")
        self.ending_var.set("Justicia y superación")
        self.drawing_style_var.set("Anime cinematográfico")
        self.animation_style_var.set("2D fluida")
        self.animation_intensity_var.set("Muy animado")
        self.overlay_mode_var.set("Título de escena")
        self.transition_style_var.set("Fundido suave")
        self.subtitle_font_var.set("Arial")
        self.subtitle_size_var.set("Mediano")
        self.subtitle_color_var.set("Blanco")
        self.subtitle_position_var.set("Inferior")
        self.subtitle_outline_var.set(True)
        self.video_mode_var.set(SERIES_VIDEO_MODE)
        self.resolution_var.set("1080p (Full HD)")
        self.fps_var.set("30")
        self._on_video_mode_changed()
        self.progressbar.configure(value=0)
        self.progress_label_var.set("Listo para planificar el guion.")
        self.progress_detail_var.set("0% · Esperando inicio")
        self.script_text.delete("1.0", "end")
        self.scene_assets = {}
        self.scene_video_assets = {}
        self.auto_expand_storyboard = True
        self.scene_duration_overrides = {}
        self.last_export_path = ""
        self.audio_track_path = ""
        self.music_track_path = ""
        self._refresh_audio_track_label()
        if self.loop_music_var is not None:
            self.loop_music_var.set(True)
        if hasattr(self, "preview_status_var"):
            self.preview_status_var.set("Todavía no hay un MP4 exportado para este proyecto.")
        self._refresh_scene_outline("")
        self.status_var.set("Proyecto nuevo. Define la premisa y los parámetros narrativos.")

    def _on_video_mode_changed(self):
        mode = self.video_mode_var.get() if hasattr(self, "video_mode_var") else SERIES_VIDEO_MODE
        is_short = mode == SHORT_VIDEO_MODE
        if is_short:
            self.duration_var.set("2")
        if hasattr(self, "duration_field"):
            self.duration_field.configure(state="disabled" if is_short else "readonly")

    def get_form(self):
        title = self.title_var.get().strip()
        topic = self.topic_var.get().strip()
        try:
            mode = self.video_mode_var.get() if hasattr(self, "video_mode_var") else SERIES_VIDEO_MODE
            duration = 2 if mode == SHORT_VIDEO_MODE else int(self.duration_var.get())
        except ValueError:
            duration = 0
        if not title or not topic:
            messagebox.showwarning("Faltan datos", "Completa el nombre del proyecto y la idea o premisa.")
            return None
        if duration < 1 or duration > 120:
            messagebox.showwarning("Duración no válida", "MARC permite vídeos de entre 1 y 120 minutos por proyecto, procesados en bloques de unos 5 minutos.")
            return None
        if len(topic) > 3000:
            messagebox.showwarning("Premisa demasiado larga", "Resume la premisa en un máximo de 3000 caracteres.")
            return None
        return {
            "title": title, "topic": topic, "platform": self.platform_var.get(),
            "duration": duration, "genre": self.style_var.get(),
            "protagonist": self.protagonist_var.get().strip(),
            "conflict": self.conflict_var.get().strip(),
            "tone": self.tone_var.get(), "narrator": self.narrator_var.get(),
            "ending": self.ending_var.get(),
            "drawing_style": self.drawing_style_var.get(),
            "animation_style": self.animation_style_var.get(),
            "animation_intensity": self.animation_intensity_var.get(),
            "overlay_mode": self.overlay_mode_var.get(),
            "transition_style": self.transition_style_var.get(),
            "subtitle_font": self.subtitle_font_var.get(),
            "subtitle_size": self.subtitle_size_var.get(),
            "subtitle_color": self.subtitle_color_var.get(),
            "subtitle_position": self.subtitle_position_var.get(),
            "subtitle_outline": bool(self.subtitle_outline_var.get()),
            "video_mode": mode,
            "resolution": self.resolution_var.get() if hasattr(self, "resolution_var") else "1080p (Full HD)",
            "fps": int(self.fps_var.get()) if hasattr(self, "fps_var") else 30,
        }

    def _ollama_request(self, prompt, max_tokens=700):
        payload = json.dumps({
            "model": "qwen2.5:3b",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.82,
                "top_p": 0.92,
                "repeat_penalty": 1.10,
                "num_ctx": 8192,
                "num_predict": max_tokens
            }
        }).encode("utf-8")
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(request, timeout=900) as response:
            result = json.loads(response.read().decode("utf-8"))
        answer = result.get("response", "").strip()
        if not answer:
            raise RuntimeError("Ollama respondió sin texto. Comprueba que Qwen esté instalado.")
        return answer

    def generate_script(self, remote=False):
        data = self.get_form()
        if not data:
            return
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        minutes = data["duration"]
        is_short = data["video_mode"] == SHORT_VIDEO_MODE
        preflight_text = (
            "MARC generará un corto de aproximadamente 2 minutos, con gancho inmediato, conflicto compacto y cierre con impacto. "
            "La duración final dependerá de la voz y las pausas. Después podrás revisar las escenas, asignar imágenes y exportar el MP4.\n\n"
            if is_short else
            "MARC generará una novela/serie por capítulos, conservando los personajes y los acontecimientos establecidos. "
            "La generación del guion no crea imágenes ni exporta el MP4 automáticamente.\n\n"
        )
        if not remote and not messagebox.askyesno(
            "Antes de generar el guion",
            preflight_text + f"Duración objetivo: {minutes} minuto(s). Modo: {data['video_mode']}. "
            "El proceso puede tardar con Qwen 2.5 3B local. ¿Comenzar?"
        ):
            return
        self.estimate_var.set(self._estimate_time(minutes))
        chapter_count = max(1, math.ceil(minutes / 5))
        self.planned_chapters = chapter_count
        self.completed_chapters = 0
        self.planned_words = target_word_count(minutes, data["video_mode"])
        self.progressbar.configure(maximum=chapter_count, value=0)
        label = "corto de 2 minutos" if is_short else f"{chapter_count} capítulo(s)"
        self.progress_label_var.set(f"Plan: {label} · objetivo ~{self.planned_words:,} palabras")
        self.progress_detail_var.set("0% · Preparando la estructura narrativa")
        if not remote and not is_short and minutes >= 45:
            confirm = messagebox.askyesno(
                "Novela larga",
                f"El proyecto tendrá {chapter_count} capítulos, generados uno por uno en tu equipo. ¿Deseas continuar?"
            )
            if not confirm:
                return
        self.save_project(reset_approval=True, quiet=True)
        self._pipeline_checkpoint("script", "running", "Generación de guion iniciada")
        data.update({
            "series_key": self.series_key,
            "episode_number": self.episode_number,
            "story_bible": self.story_bible or "",
            "continuity_state": self.continuity_state or "",
            "voice_assignments": dict(self.voice_assignments or {}),
        })
        self.cancel_event.clear()
        self.generation_running = True
        self.remote_generate_active = bool(remote)
        self._set_generation_state(True)
        self.set_configuration_visible(False)
        self.script_text.configure(state="normal")
        self.script_text.delete("1.0", "end")
        self.script_text.insert(
            "1.0",
            f"TÍTULO: {data['title']}\nGÉNERO: {data['genre']}\nDURACIÓN OBJETIVO: {minutes} minuto(s)\n"
            f"MODELO: Qwen 2.5 3B · MODO: {data['video_mode']}\n"
            f"SERIE: {data['series_key']} · EPISODIO: {data['episode_number']}\n\n"
        )
        self.script_text.configure(state="disabled")
        self.status_var.set(f"Preparando la historia · episodio {data['episode_number']}…")
        self.progress_detail_var.set("0% · Consultando el modelo local")
        worker = threading.Thread(target=self._generation_worker, args=(data, chapter_count), daemon=True)
        worker.start()

    def _set_generation_state(self, active):
        state = "disabled" if active else "normal"
        self.generate_button.configure(state=state)
        self.cancel_button.configure(state="normal" if active else "disabled")
        self.project_list.configure(state=state)
        self.delete_button.configure(state=state)
        self.save_button.configure(state=state)
        self.approve_button.configure(state=state)
        self.export_button.configure(state=state)
        self.preview_render_button.configure(state=state)
        for widget, idle_state in self.form_widgets:
            widget.configure(state="disabled" if active else idle_state)
        self.script_text.configure(state="disabled" if active else "normal")
        for button in (self.new_project_button, self.assign_image_button, self.clear_image_button,
                       self.refresh_scenes_button, self.select_audio_button, self.clear_audio_button,
                       self.detect_models_button, self.start_comfyui_button, self.generate_image_button, self.generate_missing_images_button, self.detect_voice_button,
                       self.generate_voice_button, self.inspector_assign_image_button,
                       self.inspector_generate_image_button, self.inspector_duration_button,
                       self.export_srt_button, self.select_music_button, self.clear_music_button):
            button.configure(state=state)
        self.cancel_voice_button.configure(state="disabled")
        self.image_model_combo.configure(state="disabled" if active else "readonly")
        self.image_upscale_combo.configure(state="disabled" if active else "readonly")
        self.voice_combo.configure(state="disabled" if active else "readonly")
        self._set_scene_list_state(active)
        # La barra es determinista: solo avanza cuando un capítulo termina realmente.
        if not active:
            self.progressbar.stop()

    def cancel_generation(self):
        if self.generation_running:
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled")
            self.status_var.set("Cancelación solicitada. Se guardará el borrador parcial sin aprobar.")

    def _generation_worker(self, data, chapter_count):
        try:
            if self.cancel_event.is_set():
                self.generation_queue.put(("cancelled",))
                return
            is_continuation = bool(data.get("story_bible"))
            # Fast path for standalone short videos: one Ollama call instead of
            # separate planning, screenplay, and continuity-summary calls.
            if data.get("video_mode") == SHORT_VIDEO_MODE and not is_continuation:
                self.generation_queue.put(("status", "Escribiendo el guion corto en una sola pasada…"))
                protagonist = data["protagonist"] or "inventa un protagonista distintivo con un deseo urgente"
                conflict = data["conflict"] or "inventa un conflicto concreto con consecuencias"
                fast_prompt = (
                    "Eres guionista jefe de una serie audiovisual en español y escribes para retener audiencia, no para resumir una idea. "
                    "Empieza EN MEDIO de un problema concreto en la primera frase; nada de saludos, contexto largo ni 'había una vez'. "
                    "Cada escena debe cambiar el poder, revelar una pista, elevar el riesgo o forzar una decisión. Usa detalles visuales filmables, "
                    "diálogos breves con intención oculta, interrupciones y reacciones; cada personaje debe tener una voz distinta. "
                    "En ficción dramática, crea al menos dos personajes con objetivos enfrentados y reparte la historia entre sus intervenciones; "
                    "el narrador solo describe acciones y detalles que no puedan mostrarse, nunca cuenta toda la historia por encima de los personajes. "
                    "Evita moralejas explicadas, frases genéricas, repeticiones y relleno.\n"
                    "Devuelve exactamente dos secciones: [BIBLIA CANONICA] con 3-5 líneas de rasgos visuales estables, deseos y relaciones; "
                    "y [GUION] con escenas breves encabezadas [ESCENA 01 — título visual concreto]. Dentro de cada escena, usa [NARRADOR]: "
                    "solo para acción visible y [PERSONAJE]: para cada intervención, una por línea. No pongas dos hablantes en una línea. "
                    "En al menos 4 intervenciones clave, marca una intención vocal concreta al inicio con [EMOCION=miedo], "
                    "[EMOCION=susurro], [EMOCION=ira], [EMOCION=tristeza], [EMOCION=alegria], [EMOCION=sorpresa], "
                    "[EMOCION=urgencia], [EMOCION=suspenso] o [EMOCION=calma]; ejemplo: "
                    "[MATEO]: [EMOCION=miedo] ¡No abras esa puerta! Elige la emoción según el subtexto, no por decoración. "
                    "La etiqueta es técnica: no se pronuncia ni debe aparecer como texto dibujado. No etiquetes cada frase por costumbre. "
                    "Cada escena representa UN instante visual, una acción dominante y un encuadre; máximo 5 segundos por plano. "
                    "Incluye un cambio visual concreto en cada escena y evita describir varias acciones consecutivas en el mismo plano.\n"
                    f"Título: {data['title']}. Género: {data['genre']}. Premisa: {data['topic']}. Tono: {data['tone']}. "
                    f"Protagonista: {protagonist}. Conflicto: {conflict}. Narrador: {data['narrator']}. Desenlace: {data['ending']}. "
                    f"Estilo visual: {data['drawing_style']}. Animación: {data['animation_style']}. Plataforma: {data['platform']}. "
                    f"Dirección creativa: {creative_direction(data['genre'], data['platform'], data['video_mode'])}\n"
                    "Duración aproximada: 2 minutos. Objetivo 240-300 palabras; prioriza una historia completa, ritmo y claridad. "
                    "En ficción, procura que los personajes dialoguen entre sí en varias escenas y que el giro final nazca de una decisión o pista previa.\n"
                    f"STORYBOARD OBLIGATORIO: crea al menos {visual_shot_count(120)} escenas/planos numerados para cubrir los 120 segundos con imágenes de máximo 5 segundos. "
                    "Cada plano debe ser breve, autónomo y fácil de ilustrar; describe un único instante, una acción dominante y un título que indique qué se ve. "
                    "No juntes varias acciones ni saltos temporales. Mantén continuidad de ropa, aspecto, ubicación y objetos. "
                    "No sacrifiques el final para alargar escenas: deben existir gancho, escalada, giro y consecuencia/cierre.\n"
                    f"Biblia previa si existe: {str(data.get('continuity_state', ''))[:900]}"
                )
                fast_result = self._ollama_request(fast_prompt, max_tokens=1150)
                bible_match = re.search(r"(?is)\[BIBLIA CANONICA\](.*?)(?=\[GUION\]|$)", fast_result)
                script_match = re.search(r"(?is)\[GUION\](.*)$", fast_result)
                story_bible = bible_match.group(1).strip() if bible_match else "Canon breve derivado del guion; conservar nombres, apariencia y escenario."
                chapter = script_match.group(1).strip() if script_match else fast_result.strip()
                if not chapter:
                    raise RuntimeError("Qwen no devolvió un guion. Vuelve a intentarlo.")
                self.generation_queue.put(("story_bible", story_bible))
                self.generation_queue.put(("chapter", format_short_chapter(chapter), 1, 1))
                new_state = ("Final del corto: " + chapter[-1800:]).strip()
                self.generation_queue.put(("done", 1, story_bible, new_state))
                return
            episode_number = max(1, int(data.get("episode_number", 1) or 1))

            episode_number = max(1, int(data.get("episode_number", 1) or 1))
            if is_continuation:
                story_bible = data["story_bible"]
                continuity_context = build_series_context(story_bible, data.get("continuity_state", ""))
                self.generation_queue.put(("status", f"Diseñando el episodio {episode_number} respetando la biblia de la serie…"))
                plan_prompt = (
                    "Eres showrunner de una novela serializada en español. No reescribas la biblia ni reinicies la trama. "
                    "Diseña la escaleta SOLO de este nuevo episodio usando el canon y el estado previo. Cada secuencia debe causar la siguiente; "
                    "revela información gradualmente, da consecuencias a decisiones anteriores y no resuelvas misterios abiertos sin preparación. "
                    "No cambies apariencia, parentesco, muertes, ubicación ni objetos canónicos. "
                    f"Serie: {data['title']}. Episodio nuevo: {episode_number}. Modo: {data['video_mode']}. "
                    f"Dirección creativa: {creative_direction(data['genre'], data['platform'], data['video_mode'])}. "
                    f"Duración: {data['duration']} minutos. Escribe 3-6 beats concretos.\n\n" + continuity_context
                )
                plan = self._ollama_request(plan_prompt, max_tokens=550)
            else:
                protagonist = data["protagonist"] or "crea un protagonista original con nombre distintivo y deseo urgente"
                conflict = data["conflict"] or "crea un conflicto personal y externo con consecuencias graves"
                self.generation_queue.put(("status", "Diseñando la biblia canónica de personajes, escenarios y trama…"))
                plan_prompt = (
                    "Eres showrunner y novelista profesional de ficción seriada en español. Diseña una historia específica, no una plantilla genérica. "
                    "Entrega dos secciones con estos encabezados exactos: [BIBLIA CANONICA] y [ESCALETA DE CAPITULOS]. "
                    "En la BIBLIA CANONICA incluye premisa distintiva; reglas del mundo; perfiles de protagonistas, antagonistas y secundarios "
                    "(objetivos, contradicciones, secretos, relaciones, voz verbal, rasgos físicos estables); escenarios reutilizables con detalles visuales; "
                    "cronología; hechos que no pueden cambiar; arcos de personajes; misterios abiertos y consecuencias. En la ESCALETA DE CAPITULOS resume "
                    f"{chapter_count} capítulo(s) concretos. No escribas todavía el guion final.\nGénero: {data['genre']}. Premisa: {data['topic']}. "
                    f"Protagonista: {protagonist}. Conflicto: {conflict}. Tono: {data['tone']}. Narrador: {data['narrator']}. "
                    f"Desenlace: {data['ending']}. Dirección visual: {data['drawing_style']}; animación: {data['animation_style']}. "
                    f"Dirección creativa: {creative_direction(data['genre'], data['platform'], data['video_mode'])}. "
                    f"Duración: {data['duration']} min. Modo: {data['video_mode']}. Evita aperturas cliché, coincidencias gratuitas y personajes expositivos."
                )
                plan = self._ollama_request(plan_prompt, max_tokens=min(1500, 550 + chapter_count * 28))
                canon_match = re.search(
                    r"(?is)\[BIBLIA CANONICA\](.*?)(?=\[ESCALETA DE CAPITULOS\]|$)", plan
                )
                outline_match = re.search(r"(?is)\[ESCALETA DE CAPITULOS\](.*)$", plan)
                if canon_match:
                    story_bible = canon_match.group(1).strip()
                else:
                    story_bible = plan.strip()
                if outline_match:
                    plan = outline_match.group(1).strip()
            self.generation_queue.put(("story_bible", story_bible))
            self.generation_queue.put(("status", "Estructura preparada. Escribiendo con gancho, escenas y diálogos…"))
            previous_excerpt = data.get("continuity_state", "") if is_continuation else ""
            completed = 0
            total_words = target_word_count(data["duration"], data["video_mode"])
            words_per_chapter = max(150, round(total_words / chapter_count))
            seconds_per_chapter = max(60, round(data["duration"] * 60 / chapter_count))
            visual_shots_per_chapter = visual_shot_count(seconds_per_chapter)
            for index in range(1, chapter_count + 1):
                if self.cancel_event.is_set():
                    self.generation_queue.put(("cancelled",))
                    return
                self.generation_queue.put(("status", f"Escribiendo capítulo {index} de {chapter_count}…"))
                previous_label = "episodio de una serie existente" if is_continuation else "primera entrega de una serie nueva"
                prompt = (
                    "Actúa como novelista y guionista profesional de una serie audiovisual en español. Escribe SOLO el capítulo solicitado. "
                    "No describas el proceso ni agregues consejos.\n"
                    "RETENCIÓN: abre en las primeras 1-2 frases con amenaza, decisión irreversible, contradicción inquietante o revelación concreta. "
                    "Prohíbe 'Había una vez', 'En un mundo donde' y presentaciones biográficas lentas. Cada escena debe cambiar lo que se sabe, se desea o se arriesga. "
                    "Usa detalles sensoriales selectivos, subtexto, silencios y diálogos con voz propia. Evita repeticiones, relleno y resolver conflictos sin coste. "
                    "Termina con una consecuencia emocional o una pregunta dramática que impulse la continuación, salvo que se haya pedido un final definitivo.\n"
                    "FORMATO DE ESCENAS Y VOCES: divide el capítulo en escenas visuales con encabezados como [ESCENA 01 — Título breve]. "
                    "Dentro de cada escena, coloca cada intervención en su propia línea usando etiquetas como [NARRADOR]: prosa "
                    "y [JUAN]: diálogo. No pongas dos hablantes en una línea, pero no dejes líneas vacías entre voces de la misma escena; "
                    "deja una línea vacía solo entre escenas. Usa nombres canónicos en mayúsculas y entre corchetes. "
                    "Usa [NARRADOR] para acciones y descripción, y deja que cada personaje hable por sí mismo. "
                    "En al menos 8 intervenciones clave del capítulo, marca una intención vocal concreta al inicio con [EMOCION=miedo], "
                    "[EMOCION=susurro], [EMOCION=ira], [EMOCION=tristeza], [EMOCION=alegria], [EMOCION=sorpresa], [EMOCION=urgencia], "
                    "[EMOCION=suspenso] o [EMOCION=calma]. Ejemplo: [LUCIA]: [EMOCION=susurro] No mires detrás de ti. "
                    "Selecciona la emoción por el subtexto y la evolución del personaje; no repitas siempre la misma etiqueta. "
                    "Estas etiquetas son técnicas: no se pronuncian ni se dibujan. No etiquetes cada frase por costumbre. "
                    "No leas indicaciones técnicas como diálogo.\n"
                    "CONTINUIDAD: no presentes de nuevo a personajes conocidos. Conserva nombres, voces, relaciones, heridas, objetos, escenarios, tiempo y secretos. "
                    "En una continuación, empieza después del estado más reciente; no reinicies ni contradigas el canon.\n"
                    f"Modo: {data['video_mode']}. Género: {data['genre']}. Premisa: {data['topic']}. Tono: {data['tone']}. "
                    f"Narrador: {data['narrator']}. Protagonista: {data['protagonist'] or 'según la biblia'}. Conflicto: {data['conflict'] or 'según la biblia'}. "
                    f"Desenlace: {data['ending']}. Dirección visual: {data['drawing_style']}; animación: {data['animation_style']}. Plataforma: {data['platform']}. "
                    f"Dirección creativa: {creative_direction(data['genre'], data['platform'], data['video_mode'])}. "
                    f"Duración: {data['duration']} minutos. Tipo: {previous_label}. Episodio {episode_number}; capítulo {index}/{chapter_count}. "
                    f"Objetivo aproximado: {words_per_chapter} palabras; si el ritmo pide menos, prioriza calidad sobre relleno.\n"
                    f"STORYBOARD: crea al menos {visual_shots_per_chapter} planos numerados para este capítulo, con máximo de 5 segundos por plano. "
                    "Usa [ESCENA 01 — título concreto] y describe un momento visual único, no una secuencia de acciones agrupadas.\n\n"
                    "BIBLIA / ESCALETA CANÓNICA:\n" + story_bible + "\n\nESCALETA DEL EPISODIO ACTUAL:\n" + plan +
                    ("\n\nESTADO AL FINAL DEL EPISODIO ANTERIOR (continúa después de estos hechos):\n" + previous_excerpt
                     if previous_excerpt else "\n\nINICIO: introduce al público directamente en el conflicto.")
                )
                token_budget = max(430, min(1500, int(words_per_chapter * 2.15) + 150))
                chapter = self._ollama_request(prompt, max_tokens=token_budget)
                heading = f"\n\n[CAPÍTULO {index:02d} DE {chapter_count:02d}]\n"
                self.generation_queue.put(("chapter", heading + chapter.strip() + "\n", index, chapter_count))
                previous_excerpt = chapter[-4200:]
                completed += 1
            self.generation_queue.put(("status", "Actualizando la memoria canónica para el siguiente vídeo…"))
            state_prompt = (
                "Actualiza el ESTADO CANÓNICO para el siguiente episodio de una ficción serial en español. "
                "Responde con hechos concretos y concisos (máximo 1800 caracteres): personajes presentes/ausentes, ubicación, cronología, "
                "estado emocional, heridas, objetos importantes, relaciones modificadas, decisiones, secretos revelados y conflictos abiertos. "
                "No inventes hechos. Indica exactamente desde qué situación debe continuar la próxima entrega.\n\nBIBLIA:\n" + story_bible +
                "\n\nESTADO ANTERIOR:\n" + data.get("continuity_state", "") +
                "\n\nFRAGMENTO FINAL DEL EPISODIO NUEVO:\n" + previous_excerpt
            )
            try:
                new_state = self._ollama_request(state_prompt, max_tokens=500)
            except Exception:
                new_state = "Fragmento de cierre del episodio anterior; continúa sin contradecirlo:\n" + previous_excerpt[-2500:]
            self.generation_queue.put(("done", completed, story_bible, new_state))
        except Exception as exc:
            self.generation_queue.put(("error", str(exc)))

    def _pipeline_checkpoint(self, stage, status, details="", error="", artifacts=None):
        """Persist production progress independently of the project database."""
        if self.current_id is None:
            return
        try:
            journal = ProductionPipeline(PROJECTS_DIR / str(self.current_id) / "production_pipeline.json")
            journal.mark(stage, status, details=details, error=error, artifacts=artifacts)
        except (OSError, ValueError, TypeError) as exc:
            # A journal failure must not interrupt the user's actual video work.
            self.status_var.set("Aviso: no se pudo guardar el punto de recuperación: " + str(exc)[:180])

    def _pipeline_checkpoint_summary(self):
        if self.current_id is None:
            return ""
        try:
            journal = ProductionPipeline(PROJECTS_DIR / str(self.current_id) / "production_pipeline.json")
            snapshot = journal.snapshot()
            current = snapshot.get("current_stage")
            failed = [STAGE_LABELS[name] for name, item in snapshot["stages"].items() if item.get("status") == "failed"]
            if current:
                return f"Producción en curso: {STAGE_LABELS.get(current, current)}."
            if failed:
                return "Etapa pendiente de reintento: " + ", ".join(failed) + "."
            return ""
        except (OSError, ValueError, TypeError):
            return ""

    def show_pipeline_status(self):
        """Show persisted production checkpoints and resume the failed stage on request."""
        if self.current_id is None:
            messagebox.showinfo("Producción MARC", "Guarda o abre un proyecto para consultar su estado de producción.")
            return
        try:
            journal = ProductionPipeline(PROJECTS_DIR / str(self.current_id) / "production_pipeline.json")
            snapshot = journal.snapshot()
        except (OSError, ValueError, TypeError) as exc:
            messagebox.showerror("Estado de producción", "No se pudo leer el registro de recuperación.\n\n" + str(exc))
            return

        stages = snapshot["stages"]
        lines = []
        symbols = {"completed": "✓", "running": "…", "failed": "!", "pending": "·", "skipped": "—"}
        for name, label in STAGE_LABELS.items():
            item = stages.get(name, {})
            status = item.get("status", "pending")
            line = f"{symbols.get(status, '·')} {label}: {status}"
            if status == "failed" and item.get("error"):
                line += " — " + str(item["error"]).replace("\n", " ")[:110]
            lines.append(line)
        failed = next((name for name in STAGE_LABELS if stages.get(name, {}).get("status") == "failed"), None)
        header = "Estado guardado en el equipo. Los recursos y la caché no se borran.\n\n"
        if not failed:
            messagebox.showinfo("Estado de producción", header + "\n".join(lines))
            return
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Producción en curso", header + "\n".join(lines))
            return
        prompt = header + "\n".join(lines) + "\n\n¿Reanudar desde la etapa fallida: " + STAGE_LABELS[failed] + "?"
        if not messagebox.askyesno("Reanudar producción", prompt):
            return
        retry_stage = journal.retry_failed()
        if not retry_stage:
            messagebox.showinfo("Producción MARC", "No hay ninguna etapa fallida que reanudar.")
            return
        self.status_var.set("Reanudando producción desde: " + STAGE_LABELS.get(retry_stage, retry_stage))
        if retry_stage == "script":
            self.generate_script()
        elif retry_stage == "review":
            self.approve_script()
        elif retry_stage in {"storyboard", "images"}:
            self.generate_missing_scene_images(preconfirmed=True, preview_after=True)
        elif retry_stage in {"montage", "quality_check", "export"}:
            self._start_video_render(preview=False)
        else:
            messagebox.showinfo(
                "Reanudación manual",
                "Esta etapa tiene un punto de recuperación guardado, pero necesita una acción manual desde la pestaña correspondiente: "
                + STAGE_LABELS.get(retry_stage, retry_stage)
            )

    def save_project(self, reset_approval=False, quiet=False):
        data = self.get_form()
        if not data:
            return
        script = self.script_text.get("1.0", "end-1c")
        now = datetime.now().isoformat(timespec="seconds")
        if not self.series_key:
            self.series_key = "series-" + uuid.uuid4().hex
        self.episode_number = max(1, int(getattr(self, "episode_number", 1) or 1))
        record = {
            "title": data["title"], "topic": data["topic"], "platform": data["platform"],
            "duration_minutes": data["duration"], "style": data["genre"], "script": script,
            "protagonist": data["protagonist"], "conflict": data["conflict"], "tone": data["tone"],
            "narrator": data["narrator"], "ending": data["ending"],
            "drawing_style": data["drawing_style"], "animation_style": data["animation_style"],
            "animation_intensity": data["animation_intensity"], "overlay_mode": data["overlay_mode"],
            "transition_style": data["transition_style"],
            "subtitle_font": data["subtitle_font"], "subtitle_size": data["subtitle_size"],
            "subtitle_color": data["subtitle_color"], "subtitle_position": data["subtitle_position"],
            "subtitle_outline": int(data["subtitle_outline"]),
            "resolution": data["resolution"], "fps": data["fps"], "video_mode": data["video_mode"],
            "series_key": self.series_key, "episode_number": self.episode_number,
            "story_bible": self.story_bible or "", "continuity_state": self.continuity_state or "",
            "voice_assignments": json.dumps(self.voice_assignments or {}, ensure_ascii=False),
        }
        previous = None
        if self.current_id is not None:
            previous = self.conn.execute("SELECT * FROM projects WHERE id=?", (self.current_id,)).fetchone()
        changed = previous is None or any(str(previous[key] or "") != str(value or "")
                                          for key, value in record.items())
        approved = 0 if reset_approval or changed else int(previous["approved"])
        columns = (
            "title,topic,platform,duration_minutes,style,script,approved,created_at,"
            "protagonist,conflict,tone,narrator,ending,drawing_style,animation_style,"
            "animation_intensity,overlay_mode,transition_style,subtitle_font,subtitle_size,subtitle_color,"
            "subtitle_position,subtitle_outline,resolution,fps,video_mode,series_key,episode_number,story_bible,continuity_state,voice_assignments"
        )
        values = (
            record["title"], record["topic"], record["platform"], record["duration_minutes"],
            record["style"], record["script"], approved, now, record["protagonist"],
            record["conflict"], record["tone"], record["narrator"], record["ending"],
            record["drawing_style"], record["animation_style"], record["animation_intensity"],
            record["overlay_mode"], record["transition_style"], record["subtitle_font"],
            record["subtitle_size"], record["subtitle_color"], record["subtitle_position"],
            record["subtitle_outline"], record["resolution"], record["fps"], record["video_mode"],
            record["series_key"], record["episode_number"],
            record["story_bible"], record["continuity_state"], record["voice_assignments"]
        )
        if self.current_id is None:
            placeholders = ",".join("?" for _ in values)
            cur = self.conn.execute(f"INSERT INTO projects({columns}) VALUES({placeholders})", values)
            self.current_id = cur.lastrowid
        else:
            assignments = ",".join(f"{column}=?" for column in columns.split(","))
            self.conn.execute(f"UPDATE projects SET {assignments} WHERE id=?", values + (self.current_id,))
        self.conn.commit()
        self.refresh_projects()
        if not quiet:
            self.status_var.set("Proyecto guardado. " + ("Guion aprobado." if approved else "Pendiente de revisión y aprobación."))

    def create_continuation(self):
        """Create a new episode linked to the selected project's narrative canon."""
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            messagebox.showwarning("Selecciona una historia", "Abre el proyecto que quieres continuar y vuelve a intentarlo.")
            return
        self.save_project(quiet=True)
        source = self.conn.execute("SELECT * FROM projects WHERE id=?", (self.current_id,)).fetchone()
        if not source:
            messagebox.showerror("Proyecto no encontrado", "No se pudo leer el proyecto que quieres continuar.")
            return
        series_key = source["series_key"] or ("series-" + uuid.uuid4().hex)
        source_script = source["script"] or ""
        bible = source["story_bible"] or (
            f"TÍTULO CANÓNICO: {source['title']}\nGÉNERO: {source['style']}\n"
            f"PREMISA: {source['topic']}\nPROTAGONISTA: {source['protagonist']}\n"
            f"CONFLICTO CENTRAL: {source['conflict']}\nTONO: {source['tone']}\n"
            "Mantén estos datos estables; no cambies nombres, motivaciones ni reglas sin una causa en la historia."
        )
        state = source["continuity_state"] or (
            "Continuidad derivada del episodio anterior. Conserva sus hechos y continúa desde su final.\n\n"
            + source_script[-3500:]
        )
        self.conn.execute(
            "UPDATE projects SET series_key=?,story_bible=?,continuity_state=? WHERE id=?",
            (series_key, bible, state, source["id"])
        )
        self.conn.commit()
        base_title = re.sub(r"\s+[—-]\s+Episodio\s+\d+$", "", source["title"], flags=re.IGNORECASE)
        self.current_id = None
        self.series_key = series_key
        self.episode_number = int(source["episode_number"] or 1) + 1
        self.story_bible = bible
        self.continuity_state = state
        try:
            self.voice_assignments = json.loads(source["voice_assignments"] or "{}")
        except (TypeError, json.JSONDecodeError):
            self.voice_assignments = {}
        self.set_configuration_visible(True)
        self.title_var.set(f"{base_title} — Episodio {self.episode_number}")
        self.topic_var.set(source["topic"])
        self.platform_var.set(source["platform"])
        self.duration_var.set(str(source["duration_minutes"]))
        self.style_var.set(source["style"])
        self.protagonist_var.set(source["protagonist"] or "")
        self.conflict_var.set(source["conflict"] or "")
        self.tone_var.set(source["tone"] or "Dramático e intenso")
        self.narrator_var.set(source["narrator"] or "Tercera persona")
        self.ending_var.set(source["ending"] or "Abierto para continuación")
        self.drawing_style_var.set(source["drawing_style"] or "Anime cinematográfico")
        self.animation_style_var.set(source["animation_style"] or "2D fluida")
        self.video_mode_var.set(source["video_mode"] or SERIES_VIDEO_MODE)
        self.resolution_var.set(source["resolution"] or "1080p (Full HD)")
        self.fps_var.set(str(source["fps"] or 30))
        self._on_video_mode_changed()
        self.script_text.configure(state="normal")
        self.script_text.delete("1.0", "end")
        self.scene_assets = {}
        self.audio_track_path = ""
        self.music_track_path = ""
        self.last_export_path = ""
        self._refresh_audio_track_label()
        self._refresh_scene_outline("")
        self.save_project(reset_approval=True, quiet=True)
        self.status_var.set(
            f"Nueva continuación creada: episodio {self.episode_number}. "
            "El siguiente guion consultará la biblia y el estado de la historia anterior."
        )

    def edit_story_bible(self):
        """Open the saved canon and episode-end state so the user can review or correct continuity."""
        if self.current_id is None:
            messagebox.showinfo(
                "Guarda el proyecto",
                "Guarda el proyecto o genera su primer guion antes de editar la biblia narrativa."
            )
            return
        dialog = tk.Toplevel(self)
        dialog.title("Biblia narrativa y continuidad")
        dialog.configure(bg=self.colors["bg"])
        dialog.transient(self)
        dialog.geometry("1120x760")
        dialog.minsize(820, 560)
        dialog.grid_rowconfigure(1, weight=1)
        dialog.grid_columnconfigure(0, weight=1)
        head = tk.Frame(dialog, bg=self.colors["panel"], padx=16, pady=12)
        head.grid(row=0, column=0, sticky="ew", padx=12, pady=(12, 8))
        tk.Label(head, text="BIBLIA CANÓNICA DE LA HISTORIA",
                 bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(
            head,
            text=f"Proyecto: {self.title_var.get().strip()} · Episodio {self.episode_number}. "
                 "Lo que guardes aquí se usará como referencia en las siguientes continuaciones.",
            bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
            wraplength=1000, justify="left"
        ).pack(anchor="w", pady=(4, 0))
        editors = tk.Frame(dialog, bg=self.colors["bg"])
        editors.grid(row=1, column=0, sticky="nsew", padx=12)
        editors.grid_columnconfigure(0, weight=1, uniform="canon")
        editors.grid_columnconfigure(1, weight=1, uniform="canon")
        editors.grid_rowconfigure(1, weight=1)
        tk.Label(editors, text="PERSONAJES, REGLAS Y ESCENARIOS",
                 bg=self.colors["bg"], fg="#70a7ff",
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(2, 6))
        tk.Label(editors, text="ESTADO AL CIERRE DEL EPISODIO",
                 bg=self.colors["bg"], fg="#70a7ff",
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=1, sticky="w", padx=(8, 0), pady=(2, 6))
        bible_frame = tk.Frame(editors, bg=self.colors["input"])
        bible_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        bible_frame.grid_rowconfigure(0, weight=1)
        bible_frame.grid_columnconfigure(0, weight=1)
        bible_text = tk.Text(bible_frame, wrap="word", undo=True, bg=self.colors["input"],
                             fg=self.colors["text"], insertbackground="#ffffff",
                             selectbackground=self.colors["accent"], font=("Segoe UI", 10),
                             relief="flat", padx=12, pady=10, highlightthickness=0)
        bible_text.grid(row=0, column=0, sticky="nsew")
        bible_scroll = ttk.Scrollbar(bible_frame, orient="vertical", command=bible_text.yview)
        bible_scroll.grid(row=0, column=1, sticky="ns")
        bible_text.configure(yscrollcommand=bible_scroll.set)
        state_frame = tk.Frame(editors, bg=self.colors["input"])
        state_frame.grid(row=1, column=1, sticky="nsew", padx=(6, 0))
        state_frame.grid_rowconfigure(0, weight=1)
        state_frame.grid_columnconfigure(0, weight=1)
        state_text = tk.Text(state_frame, wrap="word", undo=True, bg=self.colors["input"],
                             fg=self.colors["text"], insertbackground="#ffffff",
                             selectbackground=self.colors["accent"], font=("Segoe UI", 10),
                             relief="flat", padx=12, pady=10, highlightthickness=0)
        state_text.grid(row=0, column=0, sticky="nsew")
        state_scroll = ttk.Scrollbar(state_frame, orient="vertical", command=state_text.yview)
        state_scroll.grid(row=0, column=1, sticky="ns")
        state_text.configure(yscrollcommand=state_scroll.set)
        bible_text.insert("1.0", self.story_bible or "")
        state_text.insert("1.0", self.continuity_state or "")
        foot = tk.Frame(dialog, bg=self.colors["bg"], padx=12, pady=12)
        foot.grid(row=2, column=0, sticky="ew")
        tk.Label(foot,
                 text="Consejo: conserva nombres, apariencia, reglas del mundo, ubicaciones y hechos ya establecidos. "
                      "El estado debe explicar qué ocurrió al final, dónde está cada personaje y qué queda pendiente.",
                 bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 8),
                 wraplength=760, justify="left").pack(side="left")
        def save_canon():
            self.story_bible = bible_text.get("1.0", "end-1c").strip()
            self.continuity_state = state_text.get("1.0", "end-1c").strip()
            self.save_project(reset_approval=True, quiet=True)
            self.status_var.set("Biblia narrativa y estado de continuidad guardados. Revisa el guion antes de aprobarlo.")
            dialog.destroy()
        actions = tk.Frame(foot, bg=self.colors["bg"])
        actions.pack(side="right")
        ttk.Button(actions, text="Cancelar", command=dialog.destroy).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="Guardar canon", style="Accent.TButton",
                   command=save_canon).pack(side="left")

    def _refresh_ai_status(self):
        try:
            request = urllib.request.Request("http://127.0.0.1:11434/api/tags", headers={"Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=2) as response:
                result = json.loads(response.read().decode("utf-8"))
            model_names = [item.get("name", "") for item in result.get("models", [])]
            self.ai_available = any(name.startswith("qwen2.5:3b") for name in model_names)
            if self.ai_available:
                self.ai_badge.configure(text="● IA LOCAL · QWEN 2.5 3B LISTA", fg=self.colors["success"])
            elif model_names:
                self.ai_badge.configure(text="● OLLAMA ACTIVO · QWEN NO ENCONTRADO", fg=self.colors["warning"])
            else:
                self.ai_badge.configure(text="● OLLAMA ACTIVO · SIN MODELOS", fg=self.colors["warning"])
        except Exception:
            self.ai_available = False
            self.ai_badge.configure(text="● IA LOCAL DESCONECTADA", fg=self.colors["danger"])

    def _find_ffmpeg(self):
        found = shutil.which("ffmpeg") or os.environ.get("MARC_FFMPEG", "")
        if found and Path(found).is_file():
            return str(Path(found))
        candidates = [
            ROOT / "ffmpeg" / "bin" / "ffmpeg.exe",
            ROOT / "tools" / "ffmpeg" / "bin" / "ffmpeg.exe",
        ]
        for drive in ("C:", "D:", "E:", "F:", "G:"):
            for pattern in ("ffmpeg-*/bin/ffmpeg.exe", "ffmpeg*/bin/ffmpeg.exe"):
                try:
                    candidates.extend(Path(drive + "/").glob(pattern))
                except OSError:
                    pass
        for candidate in candidates:
            try:
                if candidate.is_file():
                    os.environ["PATH"] = str(candidate.parent) + os.pathsep + os.environ.get("PATH", "")
                    return str(candidate)
            except OSError:
                continue
        return ""

    def check_tools(self):
        self._refresh_ai_status()
        ffmpeg = self._find_ffmpeg()
        if ffmpeg:
            self.ffmpeg_badge.configure(text="● FFMPEG · DISPONIBLE", fg=self.colors["success"])
        else:
            self.ffmpeg_badge.configure(text="● FFMPEG · NO ENCONTRADO", fg=self.colors["danger"])
        self.status_var.set("Comprobación completada. " +
                            ("Qwen y FFmpeg están disponibles." if self.ai_available and ffmpeg else
                             "Revisa los indicadores de IA y FFmpeg en la parte superior."))

    def _poll_generation_events(self):
        try:
            while True:
                event = self.generation_queue.get_nowait()
                kind = event[0]
                if kind == "pc_info":
                    self.pc_info = event[1]
                    self.pc_summary_var.set(event[1]["summary"])
                    self.estimate_var.set(self._estimate_time(int(self.duration_var.get() or "10"), event[1]))
                elif kind == "story_bible":
                    self.story_bible = event[1] or self.story_bible
                    if self.current_id is not None:
                        self.save_project(reset_approval=True, quiet=True)
                    self.status_var.set("Biblia narrativa guardada; se conservará aunque canceles el borrador.")
                elif kind == "status":
                    self.status_var.set(event[1])
                elif kind == "voice_models":
                    voices, quiet = event[1], event[2]
                    self.available_voice_names = list(voices)
                    options = ["(Automática)"] + voices
                    self.voice_combo.configure(values=options)
                    if self.voice_var.get() not in options:
                        self.voice_var.set("(Automática)")
                    if voices:
                        self.voice_status_var.set(
                            f"{len(voices)} voz(es) local(es) disponible(s). Selecciona una voz y genera narración."
                        )
                    else:
                        self.voice_status_var.set(
                            "Windows no devolvió voces instaladas. Instala una voz de idioma en Configuración → Hora e idioma → Voz."
                        )
                        if not quiet:
                            messagebox.showwarning(
                                "No hay voces instaladas",
                                "Windows no devolvió voces SAPI. Instala una voz desde la configuración de idioma/voz de Windows y pulsa Detectar voces."
                            )
                elif kind == "voice_models_error":
                    detail, quiet = event[1], event[2]
                    self.voice_status_var.set("No se pudieron detectar las voces locales de Windows.")
                    if not quiet:
                        messagebox.showerror("Voces locales no disponibles", detail)
                elif kind == "voice_progress":
                    self.voice_status_var.set(event[1])
                    self.progress_detail_var.set(event[1])
                    self.status_var.set(event[1])
                elif kind == "voice_done":
                    project_id, audio_path, voice_name = event[1], event[2], event[3]
                    self._pipeline_checkpoint("narration", "completed", f"Narración WAV generada con {voice_name}", artifacts=[audio_path])
                    self.voice_generation_running = False
                    self._set_voice_state(False)
                    if self.current_id == project_id:
                        self.audio_track_path = audio_path
                        self._save_scene_assets()
                        self._refresh_audio_track_label()
                        self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
                    self.progressbar.configure(value=100)
                    self.progress_label_var.set("Narración local generada")
                    self.progress_detail_var.set("WAV guardado en los recursos del proyecto")
                    self.voice_status_var.set(f"Narración lista con la voz: {voice_name}")
                    self.status_var.set("Narración WAV creada localmente y asignada a la pista del proyecto.")
                    messagebox.showinfo(
                        "Narración generada",
                        f"Se generó la narración local en:\n{audio_path}\n\nPuedes aprobar el guion y exportar el MP4 para combinar el audio."
                    )
                    if getattr(self, "_auto_export_after_voice", False):
                        def resume_auto_export():
                            try:
                                self._start_video_render(preview=False, remote=False)
                            finally:
                                self._auto_export_after_voice = False
                                self._auto_export_after_import = False
                        self.after(250, resume_auto_export)
                elif kind == "voice_cancelled":
                    self._pipeline_checkpoint("narration", "pending", "Síntesis de voz cancelada")
                    self.voice_generation_running = False
                    self._set_voice_state(False)
                    self.progress_label_var.set("Generación de voz cancelada")
                    self.progress_detail_var.set("La narración no se cambió.")
                    self.voice_status_var.set("Cancelado.")
                    self.status_var.set("Se canceló la síntesis de voz local.")
                elif kind == "voice_error":
                    engine_label = "Kokoro" if len(event) > 2 and event[2] == "kokoro" else "Windows"
                    self._pipeline_checkpoint("narration", "failed", f"No se pudo generar la narración ({engine_label})", error=str(event[1]))
                    self.voice_generation_running = False
                    self._set_voice_state(False)
                    self.progress_label_var.set("Error al generar la voz")
                    if engine_label == "Kokoro":
                        self.progress_detail_var.set("Comprueba que el servidor Kokoro esté activo y la voz seleccionada siga disponible.")
                        self.voice_status_var.set("Falló la generación de voz neural.")
                        self.status_var.set("No se pudo completar la narración neural.")
                        message = "Kokoro no pudo generar la narración. Revisa el servidor local y la voz seleccionada.\n\n" + event[1]
                    else:
                        self.progress_detail_var.set("Comprueba que Windows tenga System.Speech y una voz instalada.")
                        self.voice_status_var.set("Falló la generación de voz.")
                        self.status_var.set("No se pudo completar la narración local.")
                        message = "Windows no pudo generar la narración. Revisa que haya una voz instalada y prueba otra vez.\n\n" + event[1]
                    messagebox.showerror("Error de narración local", message)
                elif kind == "kokoro_voices":
                    voices, quiet = event[1], event[2]
                    self.kokoro_voice_names = list(voices)
                    if str(self.voice_engine_var.get()).startswith("Kokoro"):
                        self.voice_combo.configure(values=self.kokoro_voice_names)
                        current = self.voice_var.get()
                        if current not in self.kokoro_voice_names:
                            preferred = next(
                                (name for name in ("ef_dora", "em_alex", "em_santa")
                                 if name in self.kokoro_voice_names),
                                self.kokoro_voice_names[0] if self.kokoro_voice_names else ""
                            )
                            self.voice_var.set(preferred)
                        self.voice_status_var.set(
                            f"Kokoro conectado · {len(self.kokoro_voice_names)} voces disponibles. "
                            "Las etiquetas emocionales ajustan la prosodia y los personajes pueden usar timbres distintos."
                        )
                        if not quiet:
                            messagebox.showinfo(
                                "Voces neurales detectadas",
                                f"Kokoro está conectado y expone {len(self.kokoro_voice_names)} voces. "
                                "MARC asignará voces diferentes por personaje cuando haya más de una disponible."
                            )
                elif kind == "kokoro_voices_error":
                    detail, quiet = event[1], event[2]
                    if str(self.voice_engine_var.get()).startswith("Kokoro"):
                        self.voice_combo.configure(values=[])
                        self.voice_var.set("")
                        self.voice_status_var.set(
                            "Kokoro no está conectado. Pulsa «Configurar Kokoro» para instalarlo o iniciar el servidor."
                        )
                        if not quiet:
                            messagebox.showwarning(
                                "Motor neural no disponible",
                                f"No se encontró el servidor Kokoro en {self.kokoro_url}. "
                                "Inicia el servidor local y vuelve a pulsar «Detectar voces».\n\n" + detail
                            )
                elif kind == "image_models":
                    models, quiet = event[1], event[2]
                    base_url = event[3] if len(event) > 3 else COMFYUI_URL
                    upscalers = event[4] if len(event) > 4 and event[4] else ["(Sin mejora)"]
                    self.comfy_url = base_url
                    self.comfy_available = True
                    self.image_model_combo.configure(values=models)
                    self.image_upscale_combo.configure(values=upscalers)
                    if self.image_upscale_var.get() not in upscalers:
                        self.image_upscale_var.set("(Sin mejora)")
                    current_model = self.image_model_var.get()
                    if models:
                        preferred_model = self._preferred_image_checkpoint(models)
                        generic_model = any(
                            marker in str(current_model).casefold()
                            for marker in ("v1-5-pruned-emaonly", "sd_v1-5", "base-model")
                        )
                        if current_model in models and not (generic_model and preferred_model != current_model):
                            self.image_model_var.set(current_model)
                        else:
                            self.image_model_var.set(preferred_model)
                    if models:
                        self.update_image_model_guidance()
                    else:
                        self.image_ai_status_var.set(
                            f"ComfyUI conectado en {base_url}, pero falta un checkpoint en models/checkpoints"
                        )
                    if not models and not quiet:
                        messagebox.showwarning(
                            "No hay modelos de imagen",
                            "ComfyUI responde, pero no tiene checkpoints detectados. Instala un modelo compatible en ComfyUI/models/checkpoints y pulsa Detectar ComfyUI."
                        )
                elif kind == "image_models_error":
                    detail, quiet = event[1], event[2]
                    self.comfy_available = False
                    self.image_model_combo.configure(values=[])
                    self.image_model_var.set("")
                    self.image_ai_status_var.set("Motor visual sin conexión · revisar ComfyUI y checkpoint")
                    if not quiet:
                        messagebox.showwarning(
                            "Generador de imágenes no disponible",
                            "La IA de texto y el motor visual son componentes distintos. MARC necesita ComfyUI activo y al menos un checkpoint de imagen para generar ilustraciones.\n\n" + detail
                        )
                elif kind == "image_prompt_plan_progress":
                    completed, total, detail = event[1], event[2], event[3]
                    self.progress_label_var.set(f"Preparando storyboard · {completed}/{total}")
                    self.progress_detail_var.set(detail)
                    self.status_var.set(detail)
                elif kind == "image_prompts_ready":
                    self._pipeline_checkpoint("storyboard", "completed", f"Preparados {len(event[1] or {})} prompts visuales")
                    self._pipeline_checkpoint("images", "running", "Generando ilustraciones en secuencia")
                    self.image_prompt_cache = dict(event[1] or {})
                    self.image_generation_running = False
                    self.progressbar.stop()
                    self.progressbar.configure(mode="determinate", maximum=max(1, len(self.image_prompt_cache)), value=0)
                    self._set_image_state(False)
                    self.progress_label_var.set(f"Storyboard listo · {len(self.image_prompt_cache)} prompts")
                    self.progress_detail_var.set("Prompts agrupados con IA; iniciando generación local de imágenes.")
                    self.status_var.set("Prompts visuales preparados. ComfyUI generará las ilustraciones una por una.")
                    self.after(180, self._start_next_missing_scene_image)
                elif kind == "image_progress":
                    self.progress_label_var.set(f"Ilustración IA · escena {event[1]}")
                    self.progress_detail_var.set(event[2])
                    self.status_var.set(event[2])
                elif kind == "image_done":
                    project_id, scene_number, image_path, prompt = event[1], event[2], event[3], event[4]
                    self.image_generation_running = False
                    self._set_image_state(False)
                    if self.current_id == project_id:
                        self.scene_assets[str(scene_number)] = image_path
                        self._save_scene_assets()
                        self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
                        self.scene_outline.selection_set(f"scene_{scene_number}")
                        self.scene_outline.see(f"scene_{scene_number}")
                    self.progress_label_var.set(f"Ilustración generada · escena {scene_number}")
                    self.progress_detail_var.set("Imagen guardada localmente en los recursos del proyecto.")
                    self.status_var.set("Ilustración IA generada y asignada a la escena.")
                    if self.batch_image_active:
                        completed_count = self.batch_image_total - len(self.batch_image_queue)
                        self.progress_label_var.set(f"Imágenes IA · {completed_count}/{self.batch_image_total}")
                        self.progress_detail_var.set(f"Escena {scene_number} ilustrada · preparando la siguiente")
                        self.after(250, self._start_next_missing_scene_image)
                    else:
                        messagebox.showinfo(
                            "Ilustración lista",
                            f"Se generó la imagen local para la escena {scene_number}. "
                            "Puedes previsualizar el montaje antes de exportarlo."
                        )
                elif kind == "image_error":
                    scene_number, detail = event[1], event[2]
                    self._pipeline_checkpoint("images", "failed", f"Falló la ilustración de la escena {scene_number}", error=str(detail))
                    self.image_generation_running = False
                    self.batch_image_active = False
                    self.batch_image_queue = []
                    self.batch_image_total = 0
                    self.image_prompt_cache = {}
                    self.progressbar.stop()
                    self.progressbar.configure(mode="determinate")
                    self.preview_after_image_batch = False
                    self._set_image_state(False)
                    self.progress_label_var.set(f"Ilustración fallida · escena {scene_number}")
                    self.progress_detail_var.set("Comprueba ComfyUI, el checkpoint y su consola.")
                    self.status_var.set("No se pudo generar la ilustración local.")
                    if not getattr(self, "remote_image_batch_active", False):
                        messagebox.showerror("Error de ilustración IA", detail)
                    self.remote_image_batch_active = False
                elif kind == "chapter":
                    self.completed_chapters = event[2]
                    percent = round((self.completed_chapters / max(1, event[3])) * 100)
                    self.progressbar.configure(value=percent)
                    self.progress_label_var.set(f"Guion: {self.completed_chapters} de {event[3]} capítulos completados")
                    self.progress_detail_var.set(f"{percent}% · {self.completed_chapters}/{event[3]} capítulos · borrador guardado")
                    self.script_text.configure(state="normal")
                    self.script_text.insert("end", event[1])
                    self.script_text.see("end")
                    self.script_text.configure(state="disabled")
                    self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
                    self.update_idletasks()
                    self.status_var.set(f"Capítulo {event[2]} de {event[3]} terminado. Guardando borrador…")
                    self.save_project(reset_approval=True, quiet=True)
                elif kind == "done":
                    if len(event) >= 4:
                        self.story_bible = event[2] or self.story_bible
                        self.continuity_state = event[3] or self.continuity_state
                    self.progressbar.configure(value=100)
                    self.progress_label_var.set(f"Guion completado · {event[1]} capítulos")
                    self.progress_detail_var.set("100% · Revisión y aprobación humana pendientes")
                    self.script_text.configure(state="normal")
                    self.script_text.insert("end", "\n\n[REVISIÓN HUMANA PENDIENTE]\nRevisa continuidad, nombres, ritmo y duración. El guion no está aprobado.")
                    self.script_text.configure(state="disabled")
                    self.save_project(reset_approval=True, quiet=True)
                    self._pipeline_checkpoint("script", "completed", f"Guion generado: {event[1]} capítulo(s)")
                    self.generation_running = False
                    self.remote_generate_active = False
                    self._set_generation_state(False)
                    self._refresh_scene_outline(self.script_text.get("1.0", "end-1c"))
                    words = len(self.script_text.get("1.0", "end-1c").split())
                    approx_minutes = words / 135
                    target_minutes = int(self.duration_var.get() or "1")
                    self.status_var.set(
                        f"Generación terminada: {event[1]} capítulo(s), {words} palabras "
                        f"(aprox. {approx_minutes:.1f} min a 135 palabras/min; objetivo {target_minutes} min). "
                        "Revisa el borrador antes de aprobarlo."
                    )
                elif kind == "cancelled":
                    percent = round((getattr(self, "completed_chapters", 0) / max(1, getattr(self, "planned_chapters", 1))) * 100)
                    self.progressbar.configure(value=percent)
                    self.progress_label_var.set("Generación cancelada · borrador parcial conservado")
                    self.progress_detail_var.set(f"{percent}% · Reanuda generando un nuevo borrador cuando quieras")
                    self.script_text.configure(state="normal")
                    self.save_project(reset_approval=True, quiet=True)
                    self._pipeline_checkpoint("script", "pending", "Generación cancelada; borrador parcial conservado")
                    self.generation_running = False
                    self.remote_generate_active = False
                    self._set_generation_state(False)
                    self.status_var.set("Generación cancelada. El borrador parcial se conservó sin aprobar.")
                elif kind == "error":
                    percent = round((getattr(self, "completed_chapters", 0) / max(1, getattr(self, "planned_chapters", 1))) * 100)
                    self.progressbar.configure(value=percent)
                    self.progress_label_var.set("La generación se detuvo · borrador parcial conservado")
                    self.progress_detail_var.set(f"{percent}% · Revisa el mensaje de error y la conexión de Ollama")
                    self.script_text.configure(state="normal")
                    self.save_project(reset_approval=True, quiet=True)
                    self._pipeline_checkpoint("script", "failed", "La generación no terminó", error=str(event[1]))
                    self.generation_running = False
                    was_remote_generation = bool(getattr(self, "remote_generate_active", False))
                    self.remote_generate_active = False
                    self._set_generation_state(False)
                    if not was_remote_generation:
                        messagebox.showerror("Error de generación", "La IA local no pudo completar el guion.\n\n" + event[1])
                    self.status_var.set("La generación se detuvo. El borrador parcial se conserva sin aprobar.")
                elif kind == "render_progress":
                    current, total, detail = event[1], event[2], event[3]
                    self.progressbar.configure(maximum=total, value=current)
                    percent = round((current / max(1, total)) * 100)
                    self.progress_label_var.set(f"Exportación MP4 · {current} de {total} pasos")
                    self.progress_detail_var.set(f"{percent}% · {detail}")
                    self.status_var.set(detail)
                elif kind == "render_done":
                    self.render_running = False
                    self._set_render_state(False)
                    is_preview = bool(event[4]) if len(event) > 4 else False
                    self.progressbar.configure(maximum=100, value=100)
                    if is_preview:
                        self._pipeline_checkpoint("montage", "completed", "Vista previa MP4 renderizada", artifacts=[event[1]])
                        self.preview_render_path = event[1]
                        self.preview_render_signature = self._current_preview_signature()
                        self.manual_preview_path = ""
                        self.progress_label_var.set("Vista previa lista")
                        self.progress_detail_var.set(
                            f"100% · borrador 720p · {event[2]} escenas · duración aproximada {self._format_eta(event[3])}"
                        )
                        self.preview_playback_status_var.set("Vista previa terminada · abriendo reproductor integrado…")
                        self.preview_status_var.set(
                            f"Vista previa de revisión creada: {self.preview_render_path} · exporta solo después de revisarla."
                        )
                        self.status_var.set("Vista previa lista. Reproduce el montaje y ajusta escenas, voz o duración antes de exportar.")
                        self.studio_tabs.select(self.preview_tab)
                        self.after(300, self.play_preview_video)
                    else:
                        output_file = Path(event[1])
                        report = event[5] if len(event) > 5 and isinstance(event[5], dict) else {
                            "passed": output_file.is_file() and output_file.stat().st_size > 1024,
                            "errors": ["No se recibió el informe detallado de calidad del MP4."],
                            "duration": None, "width": None, "height": None, "fps": None,
                            "audio_streams": 0, "subtitle_streams": 0,
                        }
                        self._pipeline_checkpoint("montage", "completed", "Montaje final renderizado", artifacts=[event[1]])
                        self._pipeline_checkpoint("quality_check", "running", "Validando metadatos y pistas del MP4")
                        quality_errors = list(report.get("errors") or [])
                        subtitle_report = report.get("subtitle_check") or {}
                        subtitle_artifacts = [report["subtitle_path"]] if report.get("subtitle_path") else []
                        quality_summary = (
                            f"Resolución {report.get('width') or '?'}x{report.get('height') or '?'} · "
                            f"{(report.get('fps') or 0):.2f} FPS · "
                            f"duración {self._format_eta(report.get('duration') or event[3])} · "
                            f"audio: {report.get('audio_streams', 0)} pista(s) · "
                            f"SRT: {subtitle_report.get('cue_count', 0)} subtítulo(s)"
                        )
                        if report.get("passed") and output_file.is_file() and output_file.stat().st_size > 1024:
                            self._pipeline_checkpoint(
                                "quality_check", "completed",
                                "Validación MP4 superada. " + quality_summary,
                                artifacts=[event[1]] + subtitle_artifacts,
                            )
                            self._pipeline_checkpoint(
                                "export", "completed", "MP4 y subtítulos SRT guardados y validados",
                                artifacts=[event[1]] + subtitle_artifacts,
                            )
                            self.progress_label_var.set("Vídeo exportado y validado")
                            self.status_var.set("MP4 creado y validado. " + event[1])
                        else:
                            detail = " ".join(str(item) for item in quality_errors) or "El archivo no superó las comprobaciones básicas."
                            self._pipeline_checkpoint("quality_check", "failed", "La validación de calidad no se superó", error=detail)
                            self._pipeline_checkpoint("export", "failed", "MP4 creado, pero pendiente de corregir las alertas de calidad", error=detail, artifacts=[event[1]])
                            self.progress_label_var.set("MP4 creado con alertas de calidad")
                            self.status_var.set("MP4 creado, pero no se considera validado.")
                        self.last_export_path = event[1]
                        self.manual_preview_path = ""
                        if hasattr(self, "preview_status_var"):
                            self.preview_status_var.set(f"Último vídeo exportado: {self.last_export_path}")
                        self.progress_detail_var.set(
                            f"100% · {event[2]} escenas · {quality_summary}"
                        )
                        if not getattr(self, "remote_render_active", False):
                            if report.get("passed") and output_file.is_file() and output_file.stat().st_size > 1024:
                                messagebox.showinfo(
                                    "Exportación validada",
                                    f"Vídeo MP4 creado y validado:\n{self.last_export_path}\nSubtítulos SRT:\n{report.get('subtitle_path') or 'No disponibles'}\n\n{quality_summary}\n\nPuedes abrirlo desde la pestaña VISTA PREVIA."
                                )
                            else:
                                messagebox.showwarning(
                                    "MP4 con alertas de calidad",
                                    f"El archivo se generó, pero MARC detectó problemas:\n\n{chr(10).join(quality_errors) or 'No se pudo confirmar la integridad completa.'}\n\n{quality_summary}\n\nRevisa el archivo antes de publicarlo."
                                )
                        self.remote_render_active = False
                elif kind == "audio_mux_done":
                    self.audio_mux_running = False
                    self.last_export_path = event[1]
                    project_id = event[2]
                    if project_id is not None:
                        try:
                            manifest = PROJECTS_DIR / str(project_id) / "last_export.txt"
                            manifest.parent.mkdir(parents=True, exist_ok=True)
                            manifest.write_text(self.last_export_path, encoding="utf-8")
                        except OSError:
                            pass
                    if hasattr(self, "preview_status_var"):
                        self.preview_status_var.set(f"Último vídeo con audio: {self.last_export_path}")
                    self.progressbar.configure(maximum=100, value=100)
                    self.progress_label_var.set("Vídeo con audio listo")
                    self.progress_detail_var.set("Las imágenes se copiaron sin volver a renderizarlas; se aplicaron las pistas seleccionadas.")
                    self.status_var.set(f"Vídeo con audio creado: {self.last_export_path}")
                    messagebox.showinfo("Audio añadido", f"Se creó el vídeo con audio:\n{self.last_export_path}")
                elif kind == "audio_mux_error":
                    self.audio_mux_running = False
                    self.progress_label_var.set("No se pudo añadir el audio")
                    self.progress_detail_var.set("Revisa el registro de FFmpeg junto al archivo de salida.")
                    self.status_var.set("Falló la mezcla de audio.")
                    messagebox.showerror("Error al mezclar audio", event[1])
                elif kind == "render_cancelled":
                    self._pipeline_checkpoint("montage", "pending", "Render cancelado; los recursos y caché se conservan")
                    self._pipeline_checkpoint("export", "pending", "Exportación cancelada; se puede volver a intentar")
                    self.render_running = False
                    self.remote_render_active = False
                    self._set_render_state(False)
                    self.progress_label_var.set("Exportación cancelada")
                    self.progress_detail_var.set("El render se detuvo por petición del usuario. El MP4 parcial puede no reproducirse.")
                    self.status_var.set("Exportación cancelada.")
                elif kind == "render_error":
                    self._pipeline_checkpoint("montage", "failed", "No se pudo completar el montaje", error=str(event[1]))
                    self._pipeline_checkpoint("export", "failed", "No se pudo completar el MP4", error=str(event[1]))
                    self.render_running = False
                    was_remote_render = bool(getattr(self, "remote_render_active", False))
                    self.remote_render_active = False
                    self._set_render_state(False)
                    self.progress_label_var.set("Error durante la exportación")
                    self.progress_detail_var.set("Revisa el mensaje de FFmpeg y la disponibilidad de recursos.")
                    self.status_var.set("No se pudo completar el MP4: " + str(event[1])[-240:])
                    if not was_remote_render:
                        messagebox.showerror("Error de exportación", event[1])
        except queue.Empty:
            pass
        self.after(180, self._poll_generation_events)

    def _existing_approval(self):
        if self.current_id is None:
            return 0
        row = self.conn.execute("SELECT approved FROM projects WHERE id=?", (self.current_id,)).fetchone()
        return int(row["approved"]) if row else 0

    def approve_script(self, remote=False):
        script = self.script_text.get("1.0", "end-1c").strip()
        if not script:
            if remote:
                self.status_var.set("No hay guion para aprobar. Espera a que termine o genera uno primero.")
            else:
                messagebox.showwarning("Sin guion", "Genera o escribe un guion antes de aprobarlo.")
            return
        mode = self.video_mode_var.get() if hasattr(self, "video_mode_var") else SERIES_VIDEO_MODE
        target_seconds = 120 if mode == SHORT_VIDEO_MODE else max(60, int(self.duration_var.get()) * 60)
        expected_scenes = visual_shot_count(target_seconds)
        warnings = continuity_review_check(
            script,
            self.continuity_state if self.episode_number > 1 else "",
            expected_scenes=expected_scenes,
        )
        warnings.extend(dialogue_quality_warnings(script, self.style_var.get()))
        review_text = "¿Has revisado el guion y confirmas que está listo para renderizar?"
        if warnings:
            review_text = (
                "Antes de aprobar, revisa estos avisos automáticos (son indicios, no conclusiones):\n\n"
                + "\n".join("• " + warning for warning in warnings)
                + "\n\n¿Has revisado el guion y deseas aprobarlo de todas formas?"
            )
        if not remote and not messagebox.askyesno("Revisión narrativa", review_text):
            return
        self.save_project(quiet=True)
        self._pipeline_checkpoint("script", "completed", "Guion guardado para producción")
        self._pipeline_checkpoint("review", "completed", "Guion aprobado por el usuario")
        if self.current_id is not None:
            self.conn.execute("UPDATE projects SET approved=1 WHERE id=?", (self.current_id,))
            self.conn.commit()
            self.refresh_projects()
        self.status_var.set("Guion aprobado por el usuario. Ya puedes generar ilustraciones y preparar el MP4.")

    def refresh_projects(self):
        rows = self.conn.execute("SELECT id,title,approved FROM projects ORDER BY id DESC").fetchall()
        search_var = getattr(self, "project_search_var", None)
        query = search_var.get().strip().casefold() if search_var is not None else ""
        if query == "buscar proyectos...":
            query = ""
        if query:
            rows = [
                row for row in rows
                if query in str(row["title"]).casefold() or query in str(row["id"])
            ]
        self.project_rows = rows
        self.project_list.delete(0, "end")
        selected_index = None
        for index, row in enumerate(rows):
            mark = "✓" if row["approved"] else "•"
            self.project_list.insert("end", f"{mark}  {row['title']}  · #{row['id']}")
            if row["id"] == self.current_id:
                selected_index = index
        if selected_index is not None:
            self.project_list.selection_set(selected_index)

    def load_selected(self, _event=None):
        self.set_configuration_visible(True)
        selection = self.project_list.curselection()
        if not selection:
            return
        if getattr(self, "preview_player_active", False):
            self.stop_preview_video()
        self.preview_render_path = ""
        self.preview_render_signature = ""
        self.manual_preview_path = ""
        row = self.project_rows[selection[0]]
        project = self.conn.execute("SELECT * FROM projects WHERE id=?", (row["id"],)).fetchone()
        if not project:
            return
        self.current_id = project["id"]
        self._creator_narration_override = ""
        self.title_var.set(project["title"])
        self.topic_var.set(project["topic"])
        self.platform_var.set(project["platform"])
        self.duration_var.set(str(project["duration_minutes"]))
        self.style_var.set(project["style"])
        self.protagonist_var.set(project["protagonist"] or "")
        self.conflict_var.set(project["conflict"] or "")
        self.tone_var.set(project["tone"] or "Dramático e intenso")
        self.narrator_var.set(project["narrator"] or "Tercera persona")
        self.ending_var.set(project["ending"] or "Justicia y superación")
        self.drawing_style_var.set(project["drawing_style"] or "Anime cinematográfico")
        self.animation_style_var.set(project["animation_style"] or "2D fluida")
        self.animation_intensity_var.set(project["animation_intensity"] or "Muy animado")
        self.overlay_mode_var.set(project["overlay_mode"] or "Título de escena")
        self.transition_style_var.set(project["transition_style"] or "Fundido suave")
        self.subtitle_font_var.set(project["subtitle_font"] or "Arial")
        self.subtitle_size_var.set(project["subtitle_size"] or "Mediano")
        self.subtitle_color_var.set(project["subtitle_color"] or "Blanco")
        self.subtitle_position_var.set(project["subtitle_position"] or "Inferior")
        self.subtitle_outline_var.set(bool(project["subtitle_outline"]))
        self.video_mode_var.set(project["video_mode"] or SERIES_VIDEO_MODE)
        self.resolution_var.set(project["resolution"] or "1080p (Full HD)")
        self.fps_var.set(str(project["fps"] or 30))
        self.series_key = project["series_key"] or ""
        self.episode_number = int(project["episode_number"] or 1)
        self.story_bible = project["story_bible"] or ""
        self.continuity_state = project["continuity_state"] or ""
        try:
            self.voice_assignments = json.loads(project["voice_assignments"] or "{}")
        except (TypeError, json.JSONDecodeError):
            self.voice_assignments = {}
        self._on_video_mode_changed()
        self.scene_video_assets = {}
        self._load_scene_assets(project["id"])
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", project["script"])
        self._refresh_scene_outline(project["script"] or "")
        self.status_var.set("Este proyecto está aprobado." if project["approved"] else "Proyecto cargado. Guion pendiente de aprobación.")

    def delete_project(self):
        if self.current_id is None:
            messagebox.showinfo("Selecciona proyecto", "Selecciona un proyecto guardado primero.")
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar este proyecto y su guion local?"):
            return
        self.conn.execute("DELETE FROM projects WHERE id=?", (self.current_id,))
        self.conn.commit()
        self.new_project()
        self.refresh_projects()
        self.status_var.set("Proyecto eliminado.")

    def preview_video_render(self):
        """Render a 720p draft into the project and open it inside MARC for review."""
        self._start_video_render(preview=True)

    def export_video(self, remote=False):
        """Render the approved project at its selected delivery settings."""
        self._start_video_render(preview=False, remote=remote)

    def _current_preview_signature(self):
        """Fingerprint the editable timeline so stale previews are never mistaken for current work."""
        def file_state(value):
            if not value:
                return {"path": "", "exists": False}
            try:
                path = Path(value)
                if not path.is_file():
                    return {"path": str(value), "exists": False}
                stat = path.stat()
                return {"path": str(path.resolve()), "exists": True,
                        "size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
            except (OSError, TypeError, ValueError):
                return {"path": str(value), "exists": False}

        try:
            script = self.script_text.get("1.0", "end-1c")
        except (AttributeError, tk.TclError):
            script = ""
        payload = {
            "project_id": self.current_id,
            "script": script,
            "title": self.title_var.get(),
            "topic": self.topic_var.get(),
            "platform": self.platform_var.get(),
            "duration": self.duration_var.get(),
            "animation": self.animation_style_var.get(),
            "drawing": self.drawing_style_var.get(),
            "resolution": self.resolution_var.get(),
            "fps": self.fps_var.get(),
            "durations": self.scene_duration_overrides,
            "voice_assignments": self.voice_assignments,
            "selected_voice": self.voice_var.get() if hasattr(self, "voice_var") else "(Automática)",
            "scene_assets": {
                str(number): file_state(path)
                for number, path in sorted(self.scene_assets.items(), key=lambda item: str(item[0]))
            },
            "scene_directions": self.scene_directions,
            "narration": file_state(self.audio_track_path),
            "music": file_state(self.music_track_path),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()

    def _prepare_default_character_voice_assignments(self, script, primary_voice="(Automática)"):
        """Preserve manual voice choices and assign alternate installed voices to unlabeled characters."""
        speakers = extract_speaker_names(script)
        voices = list(dict.fromkeys(str(voice).strip() for voice in self.available_voice_names if str(voice).strip()))
        if len(speakers) < 2 or len(voices) < 2:
            return 0

        old_mapping = dict(self.voice_assignments or {})
        by_speaker = {str(name).strip().upper(): value for name, value in old_mapping.items()}
        default_voice = primary_voice if primary_voice in voices else voices[0]
        alternatives = [voice for voice in voices if voice.casefold() != default_voice.casefold()]
        if not alternatives:
            return 0

        mapping = dict(old_mapping)
        assigned = 0
        for speaker in speakers:
            key = str(speaker).strip().upper()
            if any(token in key for token in ("NARRADOR", "NARRADORA", "NARRATOR", "VOZ EN OFF")):
                continue
            current = by_speaker.get(key)
            if current in voices:
                mapping[speaker] = current
                continue
            mapping[speaker] = alternatives[assigned % len(alternatives)]
            assigned += 1

        if mapping != old_mapping:
            self.voice_assignments = mapping
            if self.current_id is not None:
                self.save_project(quiet=True)
        return assigned

    def _start_video_render(self, preview=False, remote=False):
        if self.render_running or self.generation_running or self.image_generation_running or self.voice_generation_running:
            if remote:
                self.status_var.set("No se pudo iniciar el render remoto: ya hay otro trabajo en curso.")
            else:
                messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            if remote:
                self.status_var.set("Selecciona y guarda un proyecto antes de renderizar.")
            else:
                messagebox.showwarning("Guarda primero", "Completa el título y la premisa y guarda el proyecto antes de renderizar.")
            return
        self.save_project(quiet=True)
        row = self.conn.execute("SELECT * FROM projects WHERE id=?", (self.current_id,)).fetchone()
        if not row:
            if remote:
                self.status_var.set("Proyecto no encontrado al iniciar el render remoto.")
            else:
                messagebox.showerror("Proyecto no encontrado", "Vuelve a abrir o guardar el proyecto e inténtalo otra vez.")
            return
        if not preview and not row["approved"]:
            if remote:
                self.status_var.set("No se puede exportar: primero revisa y aprueba el guion desde el teléfono.")
            else:
                messagebox.showerror("Aprobación obligatoria", "No se puede exportar: primero debes aprobar el guion.")
            return
        original_scenes = parse_script_scenes(row["script"] or "")
        if not original_scenes:
            if remote:
                self.status_var.set("El proyecto no contiene escenas; genera o guarda un guion antes de exportar.")
            else:
                messagebox.showerror("Guion vacío", "El guion no contiene escenas renderizables. Genera o escribe el guion primero.")
            return

        target_seconds = max(60, int(row["duration_minutes"]) * 60)
        required_shots = min(1440, visual_shot_count(target_seconds))
        scenes = (
            expand_scenes_to_shots(original_scenes, required_shots, max_scenes=1440)
            if getattr(self, "auto_expand_storyboard", True) else original_scenes
        )
        asset_map = dict(self.scene_assets)
        for key, value in list(asset_map.items()):
            if not Path(value).is_file():
                asset_map.pop(key, None)
        missing_images = [
            index + 1 for index in range(len(scenes))
            if not asset_map.get(str(index + 1))
        ]
        self._pipeline_checkpoint("storyboard", "completed", f"Storyboard preparado: {len(scenes)} planos")
        if not missing_images:
            self._pipeline_checkpoint("images", "completed", f"Todas las escenas tienen imagen ({len(scenes)})")
        if missing_images and not remote:
            model_ready = bool(self.image_model_var.get().strip())
            if preview and model_ready:
                generate_images = messagebox.askyesno(
                    "Preparar la vista previa",
                    f"{len(missing_images)} escena(s) no tienen ilustración. Sin imágenes se verán tarjetas de texto, no escenas visuales. "
                    "¿Generar ahora las ilustraciones faltantes con ComfyUI antes de previsualizar?"
                )
                if generate_images:
                    self.generate_missing_scene_images(preconfirmed=True, preview_after=True)
                    return
                if not messagebox.askyesno(
                    "Vista previa sin imágenes",
                    "La vista previa tendrá tarjetas de texto en las escenas sin ilustración. No representará una animación visual completa. ¿Continuar?"
                ):
                    return
            else:
                if preview:
                    warning = (
                        f"{len(missing_images)} escena(s) no tienen imagen. La vista previa mostrará tarjetas de texto en esas escenas. "
                        "Para un vídeo visual, configura ComfyUI y genera las imágenes faltantes. ¿Continuar de todos modos?"
                    )
                else:
                    warning = (
                        f"{len(missing_images)} escena(s) no tienen imagen. El MP4 usará tarjetas de texto para esas escenas. "
                        "MARC anima las imágenes asignadas mediante movimiento de cámara, pero no genera movimiento neuronal de personajes. ¿Continuar?"
                    )
                if not messagebox.askyesno("Escenas sin ilustración", warning):
                    return
        if missing_images:
            self._pipeline_checkpoint(
                "images", "skipped",
                f"Se continúa con tarjetas de texto en {len(missing_images)} plano(s) sin ilustración"
            )

        preview_audio_path = self.audio_track_path if self.audio_track_path and Path(self.audio_track_path).is_file() else ""
        chosen_voice = self.voice_var.get().strip() if hasattr(self, "voice_var") else "(Automática)"
        if not preview_audio_path and str(self.voice_engine_var.get()).startswith("Kokoro"):
            # Do not silently fall back to the flat Windows system voice when the user
            # explicitly selected the neural engine. Generate it first; a second click
            # starts rendering with the now-assigned WAV track.
            self.studio_tabs.select(self.audio_tab)
            self.voice_status_var.set(
                "Kokoro seleccionado: primero genera la narración neural. Cuando termine, vuelve a Vista previa o Exportar MP4."
            )
            self.generate_kokoro_voice()
            return
        if not preview_audio_path and os.name == "nt":
            voice_count = len(self.available_voice_names)
            speaker_count = len(extract_speaker_names(row["script"] or ""))
            if speaker_count > 1 and voice_count > 1:
                if chosen_voice == "(Automática)":
                    chosen_voice = self.available_voice_names[0]
                    self.voice_var.set(chosen_voice)
                self._prepare_default_character_voice_assignments(row["script"] or "", chosen_voice)
            elif speaker_count > 1 and voice_count <= 1:
                self.voice_status_var.set(
                    "El guion contiene varios hablantes, pero Windows solo tiene una voz local detectada; "
                    "instala más voces para distinguirlos."
                )

        signature = self._current_preview_signature()
        if preview:
            preview_dir = PROJECTS_DIR / str(row["id"]) / "previews"
            preview_path = preview_dir / f"preview_{signature[:16]}.mp4"
            if preview_path.is_file() and preview_path.stat().st_size > 0:
                self.preview_render_path = str(preview_path.resolve())
                self.preview_render_signature = signature
                self.manual_preview_path = ""
                self.preview_playback_status_var.set("Vista previa encontrada · abriendo en el monitor integrado…")
                self.studio_tabs.select(self.preview_tab)
                self.play_preview_video()
                return
        else:
            preview_path = None

        ffmpeg = self._find_ffmpeg()
        if not ffmpeg and remote:
            self.status_var.set("No se encontró FFmpeg. Instálalo o configúralo antes de exportar remotamente.")
            return
        if not ffmpeg:
            selected = filedialog.askopenfilename(
                title="Selecciona ffmpeg.exe",
                filetypes=[("FFmpeg ejecutable", "ffmpeg.exe"), ("Ejecutables", "*.exe")]
            )
            if not selected:
                messagebox.showerror("FFmpeg no encontrado", "Selecciona ffmpeg.exe de la carpeta bin para renderizar.")
                return
            if Path(selected).name.lower() != "ffmpeg.exe":
                messagebox.showerror("Archivo incorrecto", "Selecciona el archivo ffmpeg.exe.")
                return
            ffmpeg = selected

        final_resolution = row["resolution"] or "1080p (Full HD)"
        final_fps = max(1, int(row["fps"] or 30))
        if preview:
            resolution = "720p (HD)"
            fps = min(final_fps, 24)
        else:
            resolution = final_resolution
            fps = final_fps
        width, height = export_dimensions(row["platform"], resolution)
        pc_info = getattr(self, "pc_info", {})
        try:
            logical_cores = int(pc_info.get("cores") or os.cpu_count() or 2)
            ram_gb = float(pc_info.get("ram_gb") or 8)
        except (TypeError, ValueError):
            logical_cores, ram_gb = os.cpu_count() or 2, 8.0
        if not remote and not preview and (resolution == "2K / 1440p" or fps >= 60) and (logical_cores <= 4 or ram_gb < 12):
            warning = (
                f"Has elegido {resolution}, {width}×{height} a {fps} FPS. "
                "Este perfil puede tardar considerablemente en este equipo. MARC conservará la resolución seleccionada; "
                "no la reducirá silenciosamente. ¿Continuar con esta calidad?"
            )
            if not messagebox.askyesno("Render de alta calidad", warning):
                return
        if preview:
            preview_path.parent.mkdir(parents=True, exist_ok=True)
            output = str(preview_path.resolve())
            self.manual_preview_path = ""
            self.preview_playback_status_var.set("Preparando vista previa 720p dentro de MARC…")
            self.preview_status_var.set("Render de revisión · 720p / 24 FPS máximo · no es la exportación final.")
            self.studio_tabs.select(self.preview_tab)
        else:
            self.status_var.set(f"Salida configurada: {width}×{height} · {fps} FPS · {resolution}.")
            if remote:
                safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", str(row["title"])).strip("._")[:60]
                safe_title = safe_title or f"proyecto-{row['id']}"
                export_dir = PROJECTS_DIR / str(row["id"]) / "exports"
                export_dir.mkdir(parents=True, exist_ok=True)
                output = str((export_dir / f"{safe_title}.mp4").resolve())
            elif getattr(self, "_auto_export_after_import", False):
                safe_title = re.sub(r"[^A-Za-z0-9._-]+", "_", str(row["title"])).strip("._")[:60]
                safe_title = safe_title or f"proyecto-{row['id']}"
                export_dir = PROJECTS_DIR / str(row["id"]) / "exports"
                export_dir.mkdir(parents=True, exist_ok=True)
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                output = str((export_dir / f"{safe_title}_{timestamp}.mp4").resolve())
            else:
                output = filedialog.asksaveasfilename(
                    title="Guardar vídeo MP4", defaultextension=".mp4",
                    filetypes=[("Vídeo MP4", "*.mp4")],
                    initialfile=f"{row['title'][:36]}-{resolution.split()[0]}.mp4"
                )
                if not output:
                    return
        durations = allocate_scene_durations(scenes, target_seconds)
        durations = [min(5, max(1, int(self.scene_duration_overrides.get(str(i + 1), value)))) for i, value in enumerate(durations)]
        audio_path = preview_audio_path
        music_path = self.music_track_path if self.music_track_path and Path(self.music_track_path).is_file() else ""
        loop_music = bool(self.loop_music_var.get()) if self.loop_music_var is not None else True
        has_any_audio = bool(audio_path or music_path or (os.name == "nt" and not audio_path))
        render_steps = len(scenes) + 1 + (1 if has_any_audio else 0)
        self.render_cancel_event.clear()
        if audio_path or narration_text:
            self._pipeline_checkpoint("narration", "completed", "Pista de voz disponible para el render", artifacts=[audio_path] if audio_path else [])
        else:
            self._pipeline_checkpoint("narration", "skipped", "No se seleccionó narración ni síntesis local")
        if music_path or audio_path:
            self._pipeline_checkpoint("audio", "completed", "Pistas de audio disponibles para la mezcla", artifacts=[path for path in (audio_path, music_path) if path])
        else:
            self._pipeline_checkpoint("audio", "skipped", "El vídeo se renderizará sin pistas de audio externas")
        if preview:
            self._pipeline_checkpoint("montage", "running", "Generando vista previa del montaje")
        else:
            self._pipeline_checkpoint("montage", "running", "Renderizando montaje final")
            self._pipeline_checkpoint("export", "running", "Exportación MP4 iniciada")
        self.render_running = True
        self._set_render_state(True)
        if getattr(self, "preview_player_active", False):
            self.stop_preview_video()
        self.progressbar.configure(maximum=render_steps, value=0)
        label = f"Preparando vista previa · {len(scenes)} escenas" if preview else f"Preparando render · {len(scenes)} escenas"
        self.progress_label_var.set(label)
        if preview:
            self.progress_detail_var.set(f"0% · borrador 720p · {width}×{height} · {fps} FPS")
        else:
            self.progress_detail_var.set(
                f"0% · {width}×{height} · {fps} FPS · duración objetivo {self._format_eta(sum(durations))}"
            )
        voice_assignments_json = json.dumps(self.voice_assignments or {}, ensure_ascii=False)
        # Keep spoken narration tied to the original script; visual shot splitting must not
        # change narration wording or add artificial pauses between split storyboard shots.
        narration_override = str(getattr(self, "_creator_narration_override", "") or "").strip()
        narration_text = (
            narration_override or "\n\n".join(
                str(scene.get("text", "")).strip()
                for scene in original_scenes if str(scene.get("text", "")).strip()
            ).strip()
        ) if not audio_path and os.name == "nt" else ""
        self.remote_render_active = bool(remote)
        args = (
            ffmpeg, str(Path(output).resolve()), int(row["id"]), width, height,
            scenes, durations, asset_map, row["animation_style"] or "2D fluida",
            row["animation_intensity"] or "Muy animado", row["overlay_mode"] or "Título de escena",
            row["transition_style"] or "Fundido suave",
            audio_path, music_path, loop_music, narration_text, chosen_voice, fps,
            voice_assignments_json, bool(preview),
            row["subtitle_font"] or "Arial", row["subtitle_size"] or "Mediano",
            row["subtitle_color"] or "Blanco", row["subtitle_position"] or "Inferior",
            bool(row["subtitle_outline"]), dict(getattr(self, "scene_video_assets", {}) or {})
        )
        threading.Thread(target=self._render_video_worker, args=args, daemon=True).start()

    def _set_render_state(self, active):
        state = "disabled" if active else "normal"
        self.generate_button.configure(state=state)
        self.cancel_button.configure(state="disabled" if not active else "disabled")
        self.cancel_render_button.configure(state="normal" if active else "disabled")
        for button in (self.new_project_button, self.save_button, self.approve_button,
                       self.export_button, self.preview_render_button, self.delete_button, self.assign_image_button,
                       self.clear_image_button, self.refresh_scenes_button,
                       self.select_audio_button, self.clear_audio_button,
                       self.select_music_button, self.clear_music_button,
                       self.detect_models_button, self.start_comfyui_button, self.generate_image_button, self.generate_missing_images_button,
                       self.detect_voice_button, self.generate_voice_button, self.assign_character_voices_button, self.add_voices_button,
                       self.inspector_assign_image_button, self.inspector_generate_image_button,
                       self.inspector_duration_button, self.export_srt_button):
            button.configure(state=state)
        self.cancel_voice_button.configure(state="disabled")
        self.voice_combo.configure(state="disabled" if active else "readonly")
        self.voice_engine_combo.configure(state="disabled" if active else "readonly")
        self.project_list.configure(state=state)
        self.cancel_button.configure(state="disabled")
        for widget, idle_state in self.form_widgets:
            widget.configure(state="disabled" if active else idle_state)
        self.script_text.configure(state="disabled" if active else "normal")
        self.image_model_combo.configure(state="disabled" if active else "readonly")
        self.image_upscale_combo.configure(state="disabled" if active else "readonly")
        self._set_scene_list_state(active)

    def cancel_export(self):
        if self.render_running:
            self.render_cancel_event.set()
            self.cancel_render_button.configure(state="disabled")
            self.status_var.set("Cancelación solicitada. Se detendrá el proceso FFmpeg actual.")

    def _render_video_worker(self, ffmpeg, output, project_id, width, height,
                             scenes, durations, asset_map, animation_style,
                             animation_intensity="Muy animado", overlay_mode="Título de escena",
                             transition_style="Fundido suave", audio_path="", music_path="", loop_music=True,
                             narration_text="", chosen_voice="(Automática)", fps=30,
                             voice_assignments_json="{}", is_preview=False,
                              subtitle_font="Arial", subtitle_size="Mediano",
                              subtitle_color="Blanco", subtitle_position="Inferior",
                              subtitle_outline=True, video_asset_map=None):
        scene_dir = PROJECTS_DIR / str(project_id) / "render_work"
        scene_dir.mkdir(parents=True, exist_ok=True)
        output_path = Path(output)
        temp_output_path = output_path.with_name(output_path.stem + ".marc_rendering.mp4")
        # Each source clip carries a small tail so the next shot can cross-dissolve over it.
        crossfade_seconds = 0.4 if transition_style != "Corte directo" else 0.0

        def run_ffmpeg(cmd, log_name, cwd=None):
            log_path = scene_dir / log_name
            creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
            with log_path.open("w", encoding="utf-8", errors="replace") as log:
                process = subprocess.Popen(
                    cmd, cwd=str(cwd) if cwd else None,
                    stdout=subprocess.DEVNULL, stderr=log,
                    creationflags=creationflags
                )
                while process.poll() is None:
                    if self.render_cancel_event.is_set():
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise RuntimeError("__MARC_RENDER_CANCELLED__")
                    time.sleep(0.2)
                if process.returncode:
                    detail = log_path.read_text(encoding="utf-8", errors="replace")[-2600:]
                    raise RuntimeError(f"FFmpeg falló (código {process.returncode}).\n{detail}")

        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            # Crea voz local de Windows automáticamente si el usuario no importó una narración.
            if narration_text and not (audio_path and Path(audio_path).is_file()):
                narration_text_path = scene_dir / "auto_narration.txt"
                narration_script_path = scene_dir / "auto_narration.ps1"
                generated_voice_path = scene_dir / "auto_narration.wav"
                voice_map_path = scene_dir / "voice_assignments.json"
                narration_timing_path = scene_dir / "auto_narration.timing.json"
                if narration_timing_path.exists():
                    narration_timing_path.unlink()
                narration_text_path.write_text(narration_text, encoding="utf-8")
                try:
                    voice_map = json.loads(voice_assignments_json or "{}")
                except (TypeError, json.JSONDecodeError):
                    voice_map = {}
                voice_map_path.write_text(json.dumps(voice_map, ensure_ascii=False), encoding="utf-8")
                narration_script_path.write_text(r"""param([string]$TextFile,[string]$OutputFile,[string]$VoiceName,[string]$VoiceMapFile,[string]$TimingFile)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voiceMap = @{}
if (Test-Path -LiteralPath $VoiceMapFile) {
  $parsed = Get-Content -LiteralPath $VoiceMapFile -Raw -Encoding UTF8 | ConvertFrom-Json
  foreach ($property in $parsed.PSObject.Properties) { $voiceMap[$property.Name.ToUpperInvariant()] = [string]$property.Value }
}
try {
  $systemDefaultVoice = $synth.Voice.Name
  $availableVoices = @($synth.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name })
  $defaultVoice = $VoiceName
  if (!$defaultVoice -or $defaultVoice -eq '(Automática)' -or $availableVoices -notcontains $defaultVoice) {
    $defaultVoice = $systemDefaultVoice
  }
  $synth.SelectVoice($defaultVoice)
  $synth.Rate = 0
  $synth.Volume = 100
  function Speak-Expressive {
      param([string]$Line)
      $emotion = 'neutral'
      $spoken = [string]$Line
      if ($spoken -match '^\s*\[EMOCION\s*=\s*([^\]]+)\]\s*') {
          $emotion = $Matches[1].Trim().ToLowerInvariant()
          $spoken = $spoken.Substring($Matches[0].Length).Trim()
      }
      if ([string]::IsNullOrWhiteSpace($spoken)) { return }
      $rate = '+0%'; $pitch = '+0%'; $volume = 'medium'
      switch -Regex ($emotion) {
          '^(miedo|temor|panico|pánico)$' { $rate = '-10%'; $pitch = '+12%'; $volume = 'medium'; break }
          '^(susurro|secreto)$' { $rate = '-18%'; $pitch = '-2%'; $volume = 'soft'; break }
          '^(ira|enojo|rabia)$' { $rate = '+14%'; $pitch = '+8%'; $volume = 'loud'; break }
          '^(tristeza|dolor|duelo)$' { $rate = '-18%'; $pitch = '-8%'; $volume = 'soft'; break }
          '^(alegria|alegría|entusiasmo)$' { $rate = '+10%'; $pitch = '+8%'; $volume = 'loud'; break }
          '^(sorpresa|shock)$' { $rate = '+8%'; $pitch = '+16%'; $volume = 'loud'; break }
          '^(urgencia|panico|pánico)$' { $rate = '+18%'; $pitch = '+10%'; $volume = 'loud'; break }
          '^(suspenso|tension|tensión)$' { $rate = '-16%'; $pitch = '-4%'; $volume = 'soft'; break }
          '^(calma|sereno)$' { $rate = '-7%'; $pitch = '-2%'; $volume = 'medium'; break }
      }
      $safeText = [System.Security.SecurityElement]::Escape($spoken)
      $culture = $synth.Voice.Culture.Name
      if (!$culture) { $culture = 'es-ES' }
      $ssml = '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="' + $culture + '"><prosody rate="' + $rate + '" pitch="' + $pitch + '" volume="' + $volume + '">' + $safeText + '</prosody></speak>'
      try { $synth.SpeakSsml($ssml) } catch { $synth.Speak($spoken) }
  }
  $text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
  if ([string]::IsNullOrWhiteSpace($text)) { throw 'El texto de narración está vacío.' }
  $synth.SetOutputToWaveFile($OutputFile)
  $timedSegments = New-Object System.Collections.Generic.List[object]
  foreach ($rawLine in ($text -split '\r?\n')) {
    $line = $rawLine.Trim()
    if ([string]::IsNullOrWhiteSpace($line)) { continue }
    $segments = [regex]::Matches($line, '\[([^\]]+)\]\s*:\s*(.*?)(?=\s+\[[^\]]+\]\s*:\s*|$)')
    if ($segments.Count -gt 0) {
      foreach ($segment in $segments) {
        $speaker = $segment.Groups[1].Value.Trim().ToUpperInvariant()
        $spoken = $segment.Groups[2].Value.Trim()
        if ($voiceMap.ContainsKey($speaker) -and $voiceMap[$speaker] -and
            $voiceMap[$speaker] -ne '(Voz principal)' -and $availableVoices -contains $voiceMap[$speaker]) {
          $synth.SelectVoice($voiceMap[$speaker])
        } else {
          $synth.SelectVoice($defaultVoice)
        }
        if (![string]::IsNullOrWhiteSpace($spoken)) {
          $spokenText = $spoken -replace '^\s*\[EMOCION\s*=\s*[^\]]+\]\s*', ''
          $startSeconds = $synth.AudioPosition.TotalSeconds
          Speak-Expressive $spoken
          $endSeconds = $synth.AudioPosition.TotalSeconds
          if ($endSeconds -gt $startSeconds) {
            $timedSegments.Add([ordered]@{ text = $spokenText; start_seconds = [double]$startSeconds; end_seconds = [double]$endSeconds })
          }
        }
      }
    } else {
      if ($defaultVoice -and $defaultVoice -ne '(Automática)') { $synth.SelectVoice($defaultVoice) }
      $lineText = $line -replace '^\s*\[EMOCION\s*=\s*[^\]]+\]\s*', ''
      $startSeconds = $synth.AudioPosition.TotalSeconds
      Speak-Expressive $line
      $endSeconds = $synth.AudioPosition.TotalSeconds
      if ($endSeconds -gt $startSeconds) {
        $timedSegments.Add([ordered]@{ text = $lineText; start_seconds = [double]$startSeconds; end_seconds = [double]$endSeconds })
      }
    }
  }
  $synth.SetOutputToNull()
  ConvertTo-Json -InputObject @($timedSegments) -Depth 4 | Set-Content -LiteralPath $TimingFile -Encoding UTF8
} finally { $synth.Dispose() }
if (!(Test-Path -LiteralPath $OutputFile) -or (Get-Item -LiteralPath $OutputFile).Length -lt 44) {
  throw 'Windows no generó un archivo WAV válido.'
}""", encoding="utf-8")
                self.generation_queue.put(("render_progress", 0, len(scenes) + 3, "Generando narración automática con la voz local de Windows…"))
                ps_args = [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(narration_script_path), str(narration_text_path), str(generated_voice_path),
                    chosen_voice or "(Automática)", str(voice_map_path), str(narration_timing_path)
                ]
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                try:
                    result = subprocess.run(ps_args, capture_output=True, text=True, timeout=60 * 60,
                                            creationflags=creationflags)
                except subprocess.TimeoutExpired:
                    raise RuntimeError("La generación automática de voz superó una hora y se detuvo.")
                if result.returncode != 0 or not generated_voice_path.is_file() or generated_voice_path.stat().st_size < 44:
                    raise RuntimeError("No se pudo generar la narración automática. Comprueba que Windows tenga una voz instalada. " +
                                       (result.stderr or result.stdout or "").strip()[-1800:])
                audio_path = str(generated_voice_path.resolve())
            total = len(scenes)
            has_voice = bool(audio_path and Path(audio_path).is_file())
            has_music = bool(music_path and Path(music_path).is_file())
            has_audio = has_voice or has_music
            final_steps = total + 1 + (1 if has_audio else 0)
            font_size = max(20, min(44, width // 28))
            subtitle_size_px = {"Pequeño": max(18, round(width * 0.022)),
                                "Mediano": max(22, round(width * 0.030)),
                                "Grande": max(28, round(width * 0.040))}.get(
                                    subtitle_size, max(22, round(width * 0.030)))
            font_files = {"Arial": "arial.ttf", "Segoe UI": "segoeui.ttf",
                          "Verdana": "verdana.ttf", "Georgia": "georgia.ttf", "Impact": "impact.ttf"}
            windows_fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
            font_candidate = windows_fonts / font_files.get(subtitle_font, "arial.ttf")
            subtitle_fontfile = str(font_candidate) if font_candidate.is_file() else ""
            subtitle_color_value = {"Blanco": "white", "Amarillo": "yellow", "Cian": "cyan"}.get(
                subtitle_color, "white")
            elapsed_before_scene = 0
            chunk_seconds = 5 * 60
            for index, scene in enumerate(scenes):
                if self.render_cancel_event.is_set():
                    raise RuntimeError("__MARC_RENDER_CANCELLED__")
                seconds = int(durations[index])
                clip_seconds = seconds + crossfade_seconds
                source_text = re.sub(r"\[EMOC[IÍ]ON\s*=\s*[^\]]{1,32}\]\s*", "", " ".join(scene["text"].split()), flags=re.IGNORECASE)
                source_text = re.sub(r"\[([^\]]+)\]\s*:\s*", "", source_text).strip()
                asset = asset_map.get(str(index + 1), "")
                video_asset_map = video_asset_map or {}
                video_asset = str(video_asset_map.get(str(index + 1), "") or "")
                asset_signature = None
                if asset and Path(asset).is_file():
                    asset_path = Path(asset)
                    stat = asset_path.stat()
                    asset_signature = {
                        "path": str(asset_path.resolve()), "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns
                    }
                video_asset_signature = None
                if video_asset and Path(video_asset).is_file():
                    video_path = Path(video_asset)
                    video_stat = video_path.stat()
                    video_asset_signature = {
                        "path": str(video_path.resolve()), "size": video_stat.st_size,
                        "mtime_ns": video_stat.st_mtime_ns
                    }
                cache_payload = {
                    "scene": scene, "duration": seconds, "clip_duration": clip_seconds,
                    "asset": asset_signature, "video_asset": video_asset_signature,
                    "animation": animation_style, "intensity": animation_intensity,
                    "overlay": overlay_mode, "transition": transition_style,
                    "subtitle_font": subtitle_font, "subtitle_size": subtitle_size,
                    "subtitle_color": subtitle_color_value, "subtitle_position": subtitle_position,
                    "subtitle_outline": bool(subtitle_outline), "subtitle_fontfile": subtitle_fontfile,
                    "width": width, "height": height,
                    "fps": int(fps), "preset": "ultrafast", "crf": 25, "version": 7
                }
                cache_fingerprint = hashlib.sha256(
                    json.dumps(cache_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
                ).hexdigest()
                scene_file = scene_dir / f"scene_{index + 1:03d}.mp4"
                cache_file = scene_dir / f"scene_{index + 1:03d}.cache.json"
                try:
                    cached = json.loads(cache_file.read_text(encoding="utf-8")) if cache_file.is_file() else {}
                except (OSError, json.JSONDecodeError):
                    cached = {}
                if (scene_file.is_file() and scene_file.stat().st_size > 0
                        and cached.get("fingerprint") == cache_fingerprint):
                    elapsed_before_scene += seconds
                    chunk_number = max(1, math.ceil(elapsed_before_scene / chunk_seconds))
                    chunk_total = max(1, math.ceil(sum(durations) / chunk_seconds))
                    self.generation_queue.put((
                        "render_progress", index + 1, final_steps,
                        f"Bloque {chunk_number}/{chunk_total} · escena {index + 1}/{total}: reutilizada"
                    ))
                    continue
                sentences = re.split(r"(?<=[.!?…])\s+", source_text)
                caption = " ".join(sentences[:2]).strip()
                if len(caption) > 190:
                    caption = caption[:187].rsplit(" ", 1)[0] + "…"
                title = scene.get("title", "")
                if title and not title.lower().startswith("escena "):
                    body = title + "\n\n" + caption
                else:
                    body = caption or title or f"Escena {index + 1}"
                wrap_width = 27 if height > width else 48
                wrapped = []
                for paragraph in body.splitlines():
                    wrapped.extend(textwrap.wrap(paragraph, width=wrap_width, break_long_words=False) or [""])
                text_file = scene_dir / f"scene_text_{index + 1:03d}.txt"
                text_file.write_text("\n".join(wrapped), encoding="utf-8")
                draw_path = ffmpeg_filter_path(text_file)
                draw_filter = (
                    f"drawtext=textfile='{draw_path}':expansion=none:fontcolor=white:"
                    f"fontsize={font_size}:line_spacing=12:x=(w-text_w)/2:y=(h-text_h)/2:"
                    "box=1:boxcolor=0x06101d@0.80:boxborderw=28"
                )
                if video_asset and Path(video_asset).is_file():
                    # A generated I2V clip takes precedence over a still image. Loop/trim it to
                    # the shot duration, then scale/crop and overlay the scene label if requested.
                    label_filter = ""
                    if overlay_mode != "Sin texto":
                        label_file = scene_dir / f"scene_label_{index + 1:03d}.txt"
                        scene_label = (" ".join(source_text.split())[:150]
                                       if overlay_mode == "Subtítulo narrativo"
                                       else str(title or f"Escena {index + 1}"))
                        scene_label = re.sub(r"\s+", " ", scene_label).strip()[:160]
                        label_file.write_text(scene_label, encoding="utf-8")
                        label_filter = build_subtitle_drawtext_filter(
                            label_file, subtitle_fontfile or None, subtitle_size_px,
                            color=subtitle_color_value, position=subtitle_position, outline=subtitle_outline
                        )
                    filters = [
                        f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos",
                        f"crop={width}:{height}", f"fps={fps}", "setsar=1",
                    ]
                    if label_filter:
                        filters.append(label_filter)
                    video_filter = ",".join(filters)
                    cmd = [
                        ffmpeg, "-y", "-stream_loop", "-1", "-i", str(Path(video_asset).resolve()),
                        "-t", str(clip_seconds), "-vf", video_filter, "-an", "-r", str(fps),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                        "-crf", "25", "-movflags", "+faststart", str(scene_file)
                    ]
                elif asset and Path(asset).is_file():
                    # Keep the generated illustration dominant. Spoken prose is carried by the audio track;
                    # only a small lower-third scene label is drawn over artwork.
                    label_filter = ""
                    if overlay_mode != "Sin texto":
                        label_file = scene_dir / f"scene_label_{index + 1:03d}.txt"
                        scene_label = (" ".join(source_text.split())[:150]
                                       if overlay_mode == "Subtítulo narrativo"
                                       else str(title or f"Escena {index + 1}"))
                        scene_label = re.sub(r"\s+", " ", scene_label).strip()[:160]
                        label_file.write_text(scene_label, encoding="utf-8")
                        label_path = ffmpeg_filter_path(label_file)
                        label_size = max(16, min(30, width // (58 if overlay_mode == "Subtítulo narrativo" else 52)))
                        label_filter = build_subtitle_drawtext_filter(
                            label_file, subtitle_fontfile or None, subtitle_size_px,
                            color=subtitle_color_value, position=subtitle_position, outline=subtitle_outline
                        )
                    motion = scene_motion_filter(
                        animation_style, width, height, max(1, math.ceil(clip_seconds)),
                        animation_intensity, shot_index=index,
                        direction=self.scene_directions.get(str(index + 1), "")
                    )
                    filters = [motion]
                    if label_filter:
                        filters.append(label_filter)
                    video_filter = ",".join(filters)
                    cmd = [
                        ffmpeg, "-y", "-loop", "1", "-framerate", str(fps), "-i", str(Path(asset).resolve()),
                        "-t", str(clip_seconds), "-vf", video_filter, "-an", "-r", str(fps),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                        "-crf", "25", "-movflags", "+faststart", str(scene_file)
                    ]
                else:
                    video_filter = (
                        "drawbox=x=0:y=0:w=iw:h=8:color=0x168bff@0.90:t=fill,"
                        + draw_filter
                    )
                    cmd = [
                        ffmpeg, "-y", "-f", "lavfi", "-i",
                        f"color=c=0x0b1320:s={width}x{height}:r={fps}",
                        "-t", str(clip_seconds), "-vf", video_filter, "-an", "-r", str(fps),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                        "-crf", "25", "-movflags", "+faststart", str(scene_file)
                    ]
                run_ffmpeg(cmd, f"scene_{index + 1:03d}.log")
                cache_file.write_text(
                    json.dumps({"fingerprint": cache_fingerprint}, ensure_ascii=False),
                    encoding="utf-8"
                )
                elapsed_before_scene += seconds
                chunk_number = max(1, math.ceil(elapsed_before_scene / chunk_seconds))
                chunk_total = max(1, math.ceil(sum(durations) / chunk_seconds))
                self.generation_queue.put((
                    "render_progress", index + 1, final_steps,
                    f"Bloque {chunk_number}/{chunk_total} · escena {index + 1}/{total}: {scene.get('title', 'Escena')}"
                ))

            # Never silently cut a narration that is longer than the planned montage.
            # Reuse existing <=5-second shots in sequence until the video can cover the full voice track.
            final_durations = list(durations)
            concat_scene_indexes = list(range(total))
            if has_voice:
                ffprobe = shutil.which("ffprobe")
                if not ffprobe:
                    ffprobe_name = "ffprobe.exe" if os.name == "nt" else "ffprobe"
                    sibling_probe = Path(ffmpeg).resolve().with_name(ffprobe_name)
                    if sibling_probe.is_file():
                        ffprobe = str(sibling_probe)
                voice_seconds = 0.0
                creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
                if ffprobe:
                    try:
                        probe = subprocess.run(
                            [ffprobe, "-v", "error", "-show_entries", "format=duration",
                             "-of", "default=noprint_wrappers=1:nokey=1", str(Path(audio_path).resolve())],
                            capture_output=True, text=True, timeout=30, creationflags=creationflags,
                        )
                        voice_seconds = float((probe.stdout or "").strip()) if probe.returncode == 0 else 0.0
                    except (OSError, ValueError, subprocess.TimeoutExpired):
                        voice_seconds = 0.0
                # Some portable FFmpeg bundles omit ffprobe; FFmpeg still reports duration on input.
                if not voice_seconds:
                    try:
                        probe = subprocess.run(
                            [ffmpeg, "-hide_banner", "-i", str(Path(audio_path).resolve())],
                            capture_output=True, text=True, timeout=30, creationflags=creationflags,
                        )
                        duration_match = re.search(
                            r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)",
                            (probe.stderr or "") + "\n" + (probe.stdout or ""),
                        )
                        if duration_match:
                            hours, minutes, seconds = duration_match.groups()
                            voice_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
                    except (OSError, subprocess.TimeoutExpired):
                        voice_seconds = 0.0
                if math.isfinite(voice_seconds) and voice_seconds > sum(final_durations) + 0.25:
                        original_video_seconds = sum(final_durations)
                        while sum(final_durations) < math.ceil(voice_seconds):
                            concat_scene_indexes.extend(range(total))
                            final_durations.extend(durations)
                        self.generation_queue.put((
                            "render_progress", total + 1, final_steps,
                            f"Narración de {voice_seconds:.0f} s: ampliando el montaje de "
                            f"{original_video_seconds} s a {sum(final_durations)} s para conservar toda la voz."
                        ))

            if self.render_cancel_event.is_set():
                raise RuntimeError("__MARC_RENDER_CANCELLED__")
            self.generation_queue.put(("render_progress", total + 1, final_steps, "Uniendo escenas y aplicando transiciones…"))
            if transition_style != "Corte directo":
                # Keep long timelines compatible with Windows command-line length limits.
                # Render small transition chunks with a tail handle, then xfade the chunks in
                # a compact final graph. The filter graph is stored in a file, not argv.
                transition = max(0.08, min(0.4, crossfade_seconds or 0.4))
                chunk_size = 30
                rendered_chunks = []
                rendered_chunk_durations = []
                if len(concat_scene_indexes) <= chunk_size:
                    # Short projects render in one pass to avoid an unnecessary encode generation.
                    rendered_chunks = [
                        scene_dir / f"scene_{scene_index + 1:03d}.mp4"
                        for scene_index in concat_scene_indexes
                    ]
                    rendered_chunk_durations = list(final_durations)
                    group_count = 1
                else:
                    group_count = max(1, math.ceil(len(concat_scene_indexes) / chunk_size))
                    for chunk_number, start in enumerate(range(0, len(concat_scene_indexes), chunk_size), start=1):
                        if self.render_cancel_event.is_set():
                            raise RuntimeError("__MARC_RENDER_CANCELLED__")
                        chunk_indexes = concat_scene_indexes[start:start + chunk_size]
                        chunk_durations = final_durations[start:start + chunk_size]
                        chunk_path = scene_dir / f"transition_chunk_{chunk_number:03d}.mp4"
                        chunk_filter_path = scene_dir / f"transition_chunk_{chunk_number:03d}.filter"
                        chunk_filter_path.write_text(
                            build_video_transition_filter_graph(
                                chunk_durations,
                                transition_seconds=transition,
                                transition_style=transition_style,
                                fade_edges=False,
                                preserve_tail=True,
                            ),
                            encoding="utf-8",
                        )
                        chunk_cmd = [ffmpeg, "-y", "-filter_complex_threads", "1"]
                        for scene_index in chunk_indexes:
                            chunk_cmd.extend(["-i", str(scene_dir / f"scene_{scene_index + 1:03d}.mp4")])
                        chunk_cmd.extend([
                            "-filter_complex_script", str(chunk_filter_path),
                            "-map", "[vout]", "-an", "-r", str(fps),
                            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                            "-crf", "25", "-movflags", "+faststart", str(chunk_path),
                        ])
                        run_ffmpeg(chunk_cmd, f"crossfade_chunk_{chunk_number:03d}.log", cwd=scene_dir)
                        if not chunk_path.is_file() or chunk_path.stat().st_size == 0:
                            raise RuntimeError(f"FFmpeg no produjo el bloque de transición {chunk_number}.")
                        rendered_chunks.append(chunk_path)
                        rendered_chunk_durations.append(sum(chunk_durations))
                        self.generation_queue.put((
                            "render_progress", total + 1, final_steps,
                            f"Transiciones · bloque {chunk_number}/{group_count} ensamblado"
                        ))

                final_filter_path = scene_dir / "crossfade_final.filter"
                final_filter_path.write_text(
                    build_video_transition_filter_graph(
                        rendered_chunk_durations,
                        transition_seconds=transition,
                        transition_style=transition_style,
                    ),
                    encoding="utf-8",
                )
                concat_cmd = [ffmpeg, "-y", "-filter_complex_threads", "1"]
                for chunk_path in rendered_chunks:
                    concat_cmd.extend(["-i", str(chunk_path)])
                concat_cmd.extend([
                    "-filter_complex_script", str(final_filter_path),
                    "-map", "[vout]", "-an",
                    "-t", f"{sum(final_durations):.3f}", "-r", str(fps),
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast",
                    "-crf", "25", "-movflags", "+faststart", str(temp_output_path)
                ])
                run_ffmpeg(concat_cmd, "crossfade.log", cwd=scene_dir)
            else:
                concat_path = scene_dir / "concat.txt"
                concat_path.write_text(
                    "".join(f"file 'scene_{i + 1:03d}.mp4'\n" for i in concat_scene_indexes),
                    encoding="utf-8"
                )
                concat_cmd = [
                    ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", "concat.txt",
                    "-c", "copy", "-movflags", "+faststart", str(temp_output_path)
                ]
                run_ffmpeg(concat_cmd, "concat.log", cwd=scene_dir)
            if not temp_output_path.is_file() or temp_output_path.stat().st_size == 0:
                raise RuntimeError("FFmpeg terminó, pero no se encontró un archivo MP4 válido.")
            if has_audio:
                if self.render_cancel_event.is_set():
                    raise RuntimeError("__MARC_RENDER_CANCELLED__")
                audio_video_path = scene_dir / "with_audio.mp4"
                if audio_video_path.exists():
                    audio_video_path.unlink()
                self.generation_queue.put(("render_progress", total + 2, final_steps, "Mezclando narración y música de fondo…"))
                mux_cmd = [ffmpeg, "-y"]
                input_index = 0
                voice_input_index = None
                music_input_index = None
                if has_voice:
                    voice_input_index = input_index
                    mux_cmd.extend(["-i", str(Path(audio_path).resolve())])
                    input_index += 1
                if has_music:
                    if loop_music:
                        mux_cmd.extend(["-stream_loop", "-1"])
                    music_input_index = input_index
                    mux_cmd.extend(["-i", str(Path(music_path).resolve())])
                    input_index += 1
                video_input_index = input_index
                mux_cmd.extend(["-i", str(temp_output_path)])
                filter_graph = build_audio_filter_graph(
                    has_voice, has_music, voice_input_index, music_input_index,
                    duration_seconds=float(sum(final_durations)),
                )
                mux_cmd.extend([
                    "-filter_complex", filter_graph,
                    "-map", f"{video_input_index}:v:0", "-map", "[aout]",
                    "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest",
                    "-movflags", "+faststart", str(audio_video_path)
                ])
                run_ffmpeg(mux_cmd, "mux_audio.log", cwd=scene_dir)
                if not audio_video_path.is_file() or audio_video_path.stat().st_size == 0:
                    raise RuntimeError("FFmpeg no pudo combinar la narración/música con el vídeo.")
                temp_output_path.unlink()
                audio_video_path.replace(temp_output_path)
            temp_output_path.replace(output_path)
            self.generation_queue.put(("render_progress", final_steps, final_steps, "Generando subtítulos SRT y verificando integridad del MP4…"))
            subtitle_path = output_path.with_suffix(".srt")
            try:
                subtitle_scenes = [scenes[index] for index in concat_scene_indexes]
                # Probe final muxed MP4: -shortest can make it shorter than the
                # planned repeated-shot timeline when narration ends earlier.
                timing_probe = inspect_media_file(str(temp_output_path), ffmpeg_path=ffmpeg)
                actual_media_duration = timing_probe.get("duration") if timing_probe.get("passed") else None
                subtitle_duration = (
                    float(actual_media_duration)
                    if actual_media_duration and actual_media_duration > 0
                    else float(sum(final_durations))
                )
                timed_segments = []
                if narration_text and has_voice:
                    timing_sidecar = scene_dir / "auto_narration.timing.json"
                    if timing_sidecar.is_file():
                        try:
                            loaded_segments = json.loads(timing_sidecar.read_text(encoding="utf-8-sig"))
                            if isinstance(loaded_segments, list) and loaded_segments:
                                timed_segments = loaded_segments
                        except (OSError, json.JSONDecodeError):
                            timed_segments = []
                if timed_segments:
                    try:
                        subtitle_text = build_srt_from_timed_segments(
                            timed_segments, total_duration_seconds=subtitle_duration
                        )
                    except (KeyError, TypeError, ValueError):
                        # If Windows returns unusable timing metadata, preserve export
                        # by falling back to scene-based SRT rather than failing the MP4.
                        subtitle_text = build_srt_subtitles(
                            subtitle_scenes,
                            final_durations,
                            total_duration_seconds=subtitle_duration,
                        )
                else:
                    subtitle_text = build_srt_subtitles(
                        subtitle_scenes,
                        final_durations,
                        total_duration_seconds=subtitle_duration,
                    )
                subtitle_path.write_text(subtitle_text, encoding="utf-8-sig")
            except (OSError, ValueError, IndexError) as subtitle_exc:
                try:
                    if subtitle_path.exists():
                        subtitle_path.unlink()
                except OSError:
                    pass
                self.generation_queue.put((
                    "render_progress", final_steps, final_steps,
                    f"Aviso: no se pudo crear el archivo SRT: {subtitle_exc}"
                ))
            quality_report = inspect_media_file(
                str(output_path),
                ffmpeg_path=ffmpeg,
                expected_width=width,
                expected_height=height,
                expected_fps=fps,
                minimum_duration=sum(final_durations),
                require_audio=bool(has_audio),
                subtitle_path=str(subtitle_path),
            )
            quality_report["subtitle_path"] = str(subtitle_path) if subtitle_path.is_file() else None
            project_dir = PROJECTS_DIR / str(project_id)
            (project_dir / "last_export.txt").write_text(str(output_path), encoding="utf-8")
            self.generation_queue.put((
                "render_done", str(output_path), len(concat_scene_indexes),
                sum(final_durations), bool(is_preview), quality_report
            ))
        except RuntimeError as exc:
            if "__MARC_RENDER_CANCELLED__" in str(exc):
                self.generation_queue.put(("render_cancelled",))
            else:
                self.generation_queue.put(("render_error", str(exc)))
        except Exception as exc:
            self.generation_queue.put(("render_error", str(exc)))
        finally:
            try:
                if temp_output_path.exists():
                    temp_output_path.unlink()
            except OSError:
                pass


if __name__ == "__main__":
    App().mainloop()
