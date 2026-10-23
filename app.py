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
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from scene_engine import (
    allocate_scene_durations, build_audio_filter_graph, build_srt_subtitles,
    ffmpeg_filter_path, parse_script_scenes, scene_motion_filter
)

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

COMFYUI_URL = "http://127.0.0.1:8188"

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
            animation_style TEXT NOT NULL DEFAULT '2D fluida'
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
        self.geometry("1540x960")
        self.minsize(1160, 700)
        self.state("zoomed")
        self.conn = db_connect()
        self.current_id = None
        self.ai_available = False
        self.generation_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.generation_running = False
        self.render_running = False
        self.render_cancel_event = threading.Event()
        self.scene_data = []
        self.scene_assets = {}
        self.scene_duration_overrides = {}
        self.last_export_path = ""
        self.audio_track_path = ""
        self.music_track_path = ""
        self.loop_music_var = None
        self.voice_generation_running = False
        self.voice_cancel_event = threading.Event()
        self.available_voice_names = []
        self.comfy_available = False
        self.image_generation_running = False
        self._style()
        self._build()
        self.refresh_projects()
        self.timeline_playhead_seconds = 0
        self.timeline_selected_scene = 1
        self.after(700, self.detect_pc_async)
        self.check_tools()
        self.after(180, self._poll_generation_events)
        self.after(1100, lambda: self.detect_image_models(quiet=True))
        self.after(1300, lambda: self.detect_local_voices(quiet=True))

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
        self.colors = {
            "bg": "#070d18", "panel": "#0e192a", "panel2": "#15243a",
            "input": "#091321", "accent": "#168bff", "accent_hover": "#45a5ff",
            "text": "#f2f7ff", "muted": "#9aadc6", "border": "#203651",
            "success": "#62e6b4", "warning": "#ffd166", "danger": "#ff7f91",
            "glow": "#173f70", "surface": "#111f33"
        }
        self.configure(bg=self.colors["bg"])
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background=self.colors["bg"])
        style.configure("Panel.TFrame", background=self.colors["panel"])
        style.configure("TLabel", background=self.colors["bg"], foreground=self.colors["text"], font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background=self.colors["bg"], foreground=self.colors["muted"], font=("Segoe UI", 9))
        style.configure("Title.TLabel", background=self.colors["bg"], foreground="#62b7ff", font=("Segoe UI", 23, "bold"))
        style.configure("Section.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 11, "bold"))
        style.configure("TButton", padding=(12, 9), font=("Segoe UI Semibold", 9), background=self.colors["panel2"], foreground=self.colors["text"], borderwidth=1, relief="flat")
        style.map("TButton",
                  background=[("active", "#203b5d"), ("pressed", self.colors["accent"])],
                  foreground=[("disabled", "#60738b")],
                  bordercolor=[("active", self.colors["accent"])])
        style.configure("Accent.TButton", padding=(15, 10), font=("Segoe UI", 9, "bold"),
                        background=self.colors["accent"], foreground="#ffffff", borderwidth=0, relief="flat")
        style.map("Accent.TButton", background=[("active", self.colors["accent_hover"]), ("pressed", "#0875df")])
        style.configure("TEntry", padding=(10, 9), fieldbackground=self.colors["input"],
                        foreground=self.colors["text"], insertcolor=self.colors["text"],
                        bordercolor=self.colors["border"], lightcolor=self.colors["border"],
                        darkcolor=self.colors["border"], relief="flat")
        style.map("TEntry", bordercolor=[("focus", self.colors["accent"])],
                  lightcolor=[("focus", self.colors["accent"])])
        style.configure("TCombobox", padding=(9, 8), fieldbackground=self.colors["input"],
                        foreground=self.colors["text"], background=self.colors["panel2"],
                        arrowcolor=self.colors["accent"], bordercolor=self.colors["border"],
                        lightcolor=self.colors["border"], darkcolor=self.colors["border"], relief="flat")
        style.map("TCombobox",
                  fieldbackground=[("readonly", self.colors["input"]), ("focus", "#0d1d31")],
                  foreground=[("readonly", self.colors["text"])],
                  bordercolor=[("focus", self.colors["accent"])],
                  lightcolor=[("focus", self.colors["accent"])])
        style.configure("Horizontal.TProgressbar", troughcolor=self.colors["input"],
                        background=self.colors["accent"], bordercolor=self.colors["border"],
                        lightcolor=self.colors["accent"], darkcolor=self.colors["accent"], thickness=8)
        style.configure("Vertical.TScrollbar", background=self.colors["panel2"],
                        troughcolor=self.colors["input"], arrowcolor=self.colors["muted"],
                        bordercolor=self.colors["input"], relief="flat")
        style.map("Vertical.TScrollbar", background=[("active", self.colors["accent"])])
        style.configure("TNotebook", background=self.colors["bg"], borderwidth=0, tabmargins=(2, 5, 2, 0))
        style.configure("TNotebook.Tab", background=self.colors["panel2"], foreground=self.colors["muted"],
                        padding=(15, 9), font=("Segoe UI", 9, "bold"), borderwidth=0)
        style.map("TNotebook.Tab",
                  background=[("selected", self.colors["accent"]), ("active", "#1b3553")],
                  foreground=[("selected", "#ffffff"), ("active", self.colors["text"])])
        style.configure("Treeview", background=self.colors["input"], fieldbackground=self.colors["input"],
                        foreground=self.colors["text"], rowheight=28, borderwidth=0,
                        font=("Segoe UI", 9))
        style.configure("Treeview.Heading", background=self.colors["panel2"],
                        foreground="#69b8ff", font=("Segoe UI", 8, "bold"), relief="flat")
        style.map("Treeview", background=[("selected", self.colors["accent"])],
                  foreground=[("selected", "#ffffff")])

    def _build(self):
        self.grid_rowconfigure(0, weight=1)
        self.grid_columnconfigure(0, weight=1)

        shell = tk.Frame(self, bg=self.colors["bg"])
        shell.grid(row=0, column=0, sticky="nsew")
        shell.grid_rowconfigure(1, weight=1)
        shell.grid_columnconfigure(0, weight=1)

        top = tk.Frame(shell, bg="#09101d", padx=22, pady=16,
                       highlightthickness=1, highlightbackground=self.colors["border"])
        top.grid(row=0, column=0, sticky="ew")
        top.grid_columnconfigure(0, weight=1)
        brand = tk.Frame(top, bg="#09101d")
        brand.grid(row=0, column=0, sticky="w")
        tk.Label(brand, text="MARC", bg="#09101d", fg="#edf4ff",
                 font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(brand, text=" / VIDEO STUDIO", bg="#09101d", fg="#2da8ff",
                 font=("Segoe UI", 20, "bold")).pack(side="left")
        tk.Label(brand, text="   AI CREATIVE WORKSPACE", bg="#09101d", fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(12, 0), pady=(7, 0))
        head_right = tk.Frame(top, bg="#09101d")
        head_right.grid(row=0, column=1, sticky="e")
        self.ai_badge = tk.Label(head_right, text="● IA LOCAL · COMPROBANDO",
                                 bg="#09101d", fg=self.colors["warning"], font=("Segoe UI", 9, "bold"))
        self.ai_badge.pack(side="left", padx=(0, 14))
        self.ffmpeg_badge = tk.Label(head_right, text="● FFMPEG · COMPROBANDO",
                                     bg="#09101d", fg=self.colors["muted"], font=("Segoe UI", 9, "bold"))
        self.ffmpeg_badge.pack(side="left", padx=(0, 12))
        ttk.Button(head_right, text="Diagnóstico PC", command=self.detect_pc_async).pack(side="left", padx=(0, 6))
        ttk.Button(head_right, text="Herramientas", command=self.check_tools).pack(side="left")

        workspace = tk.PanedWindow(shell, orient="horizontal", sashwidth=7, sashrelief="flat",
                                   bg=self.colors["bg"], bd=0, opaqueresize=True, showhandle=False)
        workspace.grid(row=1, column=0, sticky="nsew", padx=14, pady=14)
        self.workspace_panes = workspace

        library = tk.Frame(workspace, bg=self.colors["panel"], width=250,
                           highlightthickness=1, highlightbackground=self.colors["border"])
        library.grid_rowconfigure(2, weight=1)
        library.grid_columnconfigure(0, weight=1)
        workspace.add(library, minsize=205, width=250)
        tk.Label(library, text="BIBLIOTECA", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 10, "bold"), anchor="w").grid(row=0, column=0, sticky="ew", padx=13, pady=(14, 2))
        tk.Label(library, text="Proyectos y guiones", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w").grid(row=1, column=0, sticky="ew", padx=13, pady=(0, 9))
        self.project_list = tk.Listbox(library, bg=self.colors["input"], fg=self.colors["text"],
                                       selectbackground=self.colors["accent"], selectforeground="#fff",
                                       borderwidth=0, highlightthickness=0, font=("Segoe UI", 9),
                                       activestyle="none")
        self.project_list.grid(row=2, column=0, sticky="nsew", padx=8)
        self.project_list.bind("<<ListboxSelect>>", self.load_selected)
        lib_buttons = tk.Frame(library, bg=self.colors["panel"], padx=8, pady=8)
        lib_buttons.grid(row=3, column=0, sticky="ew")
        self.new_project_button = ttk.Button(lib_buttons, text="+ Nuevo proyecto", style="Accent.TButton",
                                              command=self.new_project)
        self.new_project_button.pack(fill="x", pady=(0, 6))
        self.delete_button = ttk.Button(lib_buttons, text="Eliminar proyecto", command=self.delete_project)
        self.delete_button.pack(fill="x")

        editor = tk.Frame(workspace, bg=self.colors["bg"])
        workspace.add(editor, minsize=620, stretch="always")
        editor.grid_rowconfigure(0, weight=1)
        editor.grid_columnconfigure(0, weight=1)

        vertical = tk.PanedWindow(editor, orient="horizontal", sashwidth=7, sashrelief="flat",
                                  bg=self.colors["bg"], bd=0, opaqueresize=True, showhandle=False)
        vertical.grid(row=0, column=0, sticky="nsew")
        self.vertical_panes = vertical

        controls_area = tk.Frame(vertical, bg=self.colors["bg"])
        self.controls_area = controls_area
        vertical.add(controls_area, minsize=285, width=325, stretch="never")
        card = tk.Frame(controls_area, bg=self.colors["panel"], padx=10, pady=10,
                        highlightthickness=1, highlightbackground=self.colors["border"])
        card.pack(fill="both", expand=True)
        tk.Label(card, text="CONFIGURACIÓN DE HISTORIA", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 13, "bold")).pack(anchor="w")
        tk.Label(card, text="Define narrativa, formato y dirección visual. Los paneles se pueden redimensionar.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 10)).pack(anchor="w", pady=(5, 12))

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

        form = tk.Frame(card, bg=self.colors["panel"])
        form.pack(fill="x", expand=True)
        self.form_widgets = []
        form.columnconfigure(0, weight=1, uniform="fields")
        form.columnconfigure(1, weight=1, uniform="fields")
        self._field(form, "Nombre del proyecto", self.title_var, 0, 0, span=2)
        self._field(form, "Género", self.style_var, 1, 0,
                    values=["Novela dramática", "Reencarnación y venganza", "Superación personal", "Romance",
                            "Fantasía", "Misterio y suspenso", "Terror", "Acción y aventura", "Ciencia ficción",
                            "Drama familiar", "Educativo y directo", "Documental", "Promocional"])
        self._field(form, "Plataforma", self.platform_var, 1, 1, values=list(PLATFORMS))
        self._field(form, "Duración (min)", self.duration_var, 2, 0,
                    values=[str(i) for i in (1, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120)])
        self._field(form, "Tono", self.tone_var, 2, 1,
                    values=["Dramático e intenso", "Oscuro y misterioso", "Emotivo", "Inspirador",
                            "Épico", "Ligero y humorístico", "Realista"])
        self._field(form, "Narrador", self.narrator_var, 3, 0,
                    values=["Tercera persona", "Primera persona protagonista", "Primera persona retrospectiva",
                            "Narrador omnisciente"])
        self._field(form, "Desenlace", self.ending_var, 3, 1,
                    values=["Justicia y superación", "Final feliz", "Final trágico", "Giro inesperado",
                            "Abierto para continuación", "Agridulce"])
        self._field(form, "Protagonista", self.protagonist_var, 4, 0)
        self._field(form, "Conflicto central", self.conflict_var, 4, 1)
        self._field(form, "Estilo de dibujo", self.drawing_style_var, 5, 0,
                    values=["Anime cinematográfico", "Manga en blanco y negro", "Cartoon occidental",
                            "Cómic realista", "Acuarela ilustrada", "Pixel art", "3D estilizado",
                            "Realismo cinematográfico"])
        self._field(form, "Estilo de animación", self.animation_style_var, 5, 1,
                    values=["2D fluida", "Anime con movimientos dinámicos", "Motion comic",
                            "Cut-out / recortes", "3D cinematográfica", "Stop motion",
                            "Pixel animation", "Presentación animada"])
        self._field(form, "Premisa / idea", self.topic_var, 6, 0, span=2)
        tk.Label(form, text="Los estilos guían la generación; las ilustraciones se asignan en ESCENAS.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 8),
                 justify="left", wraplength=280).grid(row=7, column=0, columnspan=2,
                                                        sticky="w", padx=5, pady=(5, 2))

        lower = tk.Frame(vertical, bg=self.colors["bg"])
        self.lower_panel = lower
        vertical.add(lower, minsize=620, stretch="always")
        lower.grid_rowconfigure(3, weight=1)
        lower.grid_columnconfigure(0, weight=1)

        toolrow = tk.Frame(lower, bg=self.colors["bg"])
        toolrow.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        self.generate_button = ttk.Button(toolrow, text="✦ Generar guion", style="Accent.TButton",
                                          command=self.generate_script)
        self.generate_button.pack(side="left")
        self.cancel_button = ttk.Button(toolrow, text="Cancelar", command=self.cancel_generation, state="disabled")
        self.cancel_button.pack(side="left", padx=(6, 0))
        self.save_button = ttk.Button(toolrow, text="Guardar", command=self.save_project)
        self.save_button.pack(side="left", padx=(6, 0))
        self.approve_button = ttk.Button(toolrow, text="Aprobar", command=self.approve_script)
        self.approve_button.pack(side="left", padx=(6, 0))
        self.export_button = ttk.Button(toolrow, text="Exportar MP4", command=self.export_video)
        self.export_button.pack(side="left", padx=(6, 0))
        self.cancel_render_button = ttk.Button(toolrow, text="Cancelar render",
                                               command=self.cancel_export, state="disabled")
        self.cancel_render_button.pack(side="left", padx=(6, 0))
        self.configuration_visible = True
        self.config_toggle_button = ttk.Button(
            toolrow, text="Ocultar configuración", command=self.toggle_configuration)
        self.config_toggle_button.pack(side="right")

        statuscard = tk.Frame(lower, bg=self.colors["panel"], padx=10, pady=6,
                              highlightthickness=1, highlightbackground=self.colors["border"])
        statuscard.grid(row=1, column=0, sticky="ew", pady=(0, 7))
        status_head = tk.Frame(statuscard, bg=self.colors["panel"])
        status_head.pack(fill="x")
        self.progress_label_var = tk.StringVar(value="Listo para crear el guion")
        tk.Label(status_head, textvariable=self.progress_label_var, bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(side="left", anchor="w")
        self.details_visible = False
        self.details_button = ttk.Button(status_head, text="＋ Diagnóstico y estimaciones",
                                         command=self.toggle_status_details)
        self.details_button.pack(side="right")
        self.progressbar = ttk.Progressbar(statuscard, mode="determinate", maximum=100, value=0)
        self.progressbar.pack(fill="x", pady=(4, 2))
        self.progress_detail_var = tk.StringVar(value="0% · En espera")
        tk.Label(statuscard, textvariable=self.progress_detail_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 8)).pack(anchor="w")
        self.details_frame = tk.Frame(statuscard, bg=self.colors["panel"])
        self.pc_summary_var = tk.StringVar(value="Detectando equipo…")
        tk.Label(self.details_frame, textvariable=self.pc_summary_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 9), justify="left",
                 wraplength=1250).pack(anchor="w", pady=(8, 0))
        self.estimate_var = tk.StringVar(value="Calculando estimación de producción…")
        tk.Label(self.details_frame, textvariable=self.estimate_var, bg=self.colors["panel"],
                 fg=self.colors["success"], font=("Segoe UI", 9, "bold"), justify="left",
                 wraplength=1250).pack(anchor="w", pady=(4, 0))

        # Persistent monitor in the main workspace; it stays visible while switching tabs.
        preview_dock = tk.Frame(lower, bg=self.colors["panel"], padx=9, pady=7,
                                highlightthickness=1, highlightbackground=self.colors["border"])
        preview_dock.grid(row=2, column=0, sticky="ew", pady=(0, 7))
        preview_dock.grid_columnconfigure(0, weight=3, uniform="monitor")
        preview_dock.grid_columnconfigure(1, weight=2, uniform="monitor")
        monitor_header = tk.Frame(preview_dock, bg=self.colors["panel"])
        monitor_header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 5))
        tk.Label(monitor_header, text="MONITOR / STORYBOARD", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 10, "bold")).pack(side="left")
        self.preview_scene_var = tk.StringVar(value="SIN ESCENAS")
        tk.Label(monitor_header, textvariable=self.preview_scene_var, bg=self.colors["panel"],
                 fg="#69b8ff", font=("Segoe UI", 8, "bold")).pack(side="right")
        monitor = tk.Frame(preview_dock, bg="#03070d", highlightthickness=1,
                           highlightbackground=self.colors["border"])
        monitor.grid(row=1, column=0, sticky="nsew", padx=(0, 6))
        monitor.grid_columnconfigure(0, weight=1)
        monitor.grid_rowconfigure(0, weight=1)
        self.preview_canvas = tk.Canvas(monitor, bg="#03070d", highlightthickness=0,
                                        height=196, width=520)
        self.preview_canvas.grid(row=0, column=0, sticky="nsew")
        self.preview_canvas.bind("<Configure>", lambda _event: self._render_preview_frame())
        scene_inspector = tk.Frame(preview_dock, bg=self.colors["input"], padx=10, pady=8,
                                   highlightthickness=1, highlightbackground=self.colors["border"])
        scene_inspector.grid(row=1, column=1, sticky="nsew")
        tk.Label(scene_inspector, text="ESCENA ACTUAL", bg=self.colors["input"],
                 fg="#69b8ff", font=("Segoe UI", 8, "bold")).pack(anchor="w")
        self.preview_scene_title_var = tk.StringVar(value="Genera un guion")
        tk.Label(scene_inspector, textvariable=self.preview_scene_title_var, bg=self.colors["input"],
                 fg=self.colors["text"], font=("Segoe UI", 11, "bold"),
                 wraplength=260, justify="left").pack(anchor="w", pady=(7, 5))
        self.preview_scene_text_var = tk.StringVar(value="Al seleccionar una escena aparecerán aquí su resumen y referencia visual.")
        tk.Label(scene_inspector, textvariable=self.preview_scene_text_var, bg=self.colors["input"],
                 fg=self.colors["muted"], font=("Segoe UI", 9), wraplength=260,
                 justify="left", anchor="nw").pack(fill="both", expand=True)
        monitor_actions = tk.Frame(preview_dock, bg=self.colors["panel"])
        monitor_actions.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        ttk.Button(monitor_actions, text="◀ Escena", command=lambda: self._step_preview_scene(-1)).pack(side="left")
        ttk.Button(monitor_actions, text="Escena ▶", command=lambda: self._step_preview_scene(1)).pack(side="left", padx=(5, 0))
        ttk.Button(monitor_actions, text="Abrir MP4", style="Accent.TButton",
                   command=self.open_last_video).pack(side="right")
        ttk.Button(monitor_actions, text="Elegir MP4",
                   command=self.choose_preview_video).pack(side="right", padx=(0, 5))

        script_card = tk.Frame(lower, bg=self.colors["panel"], padx=10, pady=9,
                               highlightthickness=1, highlightbackground=self.colors["border"])
        script_card.grid(row=3, column=0, sticky="nsew")
        script_card.grid_rowconfigure(0, weight=1)
        script_card.grid_columnconfigure(0, weight=1)
        studio_tabs = ttk.Notebook(script_card)
        studio_tabs.grid(row=0, column=0, sticky="nsew")
        self.studio_tabs = studio_tabs

        script_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=8, pady=8)
        studio_tabs.add(script_tab, text="  ✎  GUION  ")
        script_tab.grid_rowconfigure(1, weight=1)
        script_tab.grid_columnconfigure(0, weight=1)
        script_head = tk.Frame(script_tab, bg=self.colors["panel"])
        script_head.grid(row=0, column=0, sticky="ew", pady=(0, 7))
        tk.Label(script_head, text="EDITOR DE GUION", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(script_head, text="Revisa el texto antes de aprobar y exportar", bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 9)).pack(side="right")
        textframe = tk.Frame(script_tab, bg=self.colors["input"])
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
        studio_tabs.add(scenes_tab, text="  ▤  ESCENAS  ")
        scenes_tab.grid_columnconfigure(0, weight=1)
        scenes_tab.grid_rowconfigure(6, weight=1)
        tk.Label(scenes_tab, text="PLAN DE MONTAJE", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 12, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(scenes_tab, text="Organiza el guion como escenas, asigna ilustraciones propias o genera imágenes con un motor local opcional.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1000, justify="left").grid(row=1, column=0, sticky="w", pady=(4, 6))
        self.scene_summary_var = tk.StringVar(value="0 escenas · 0 palabras")
        tk.Label(scenes_tab, textvariable=self.scene_summary_var, bg=self.colors["panel"],
                 fg="#69b8ff", font=("Segoe UI", 9, "bold")).grid(row=2, column=0, sticky="w", pady=(0, 8))

        scene_actions = tk.Frame(scenes_tab, bg=self.colors["panel"])
        scene_actions.grid(row=3, column=0, sticky="ew", pady=(0, 7))
        self.assign_image_button = ttk.Button(scene_actions, text="Añadir imagen propia", style="Accent.TButton",
                                              command=self.assign_scene_image)
        self.assign_image_button.pack(side="left")
        self.clear_image_button = ttk.Button(scene_actions, text="Quitar imagen", command=self.clear_scene_image)
        self.clear_image_button.pack(side="left", padx=(6, 0))
        self.refresh_scenes_button = ttk.Button(scene_actions, text="Actualizar escenas",
                                                command=lambda: self._refresh_scene_outline(self.script_text.get("1.0", "end-1c")))
        self.refresh_scenes_button.pack(side="left", padx=(6, 0))
        image_ai_bar = tk.Frame(scenes_tab, bg=self.colors["panel"])
        image_ai_bar.grid(row=4, column=0, sticky="ew", pady=(0, 8))
        tk.Label(image_ai_bar, text="MODELO LOCAL", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 7))
        self.image_model_var = tk.StringVar(value="")
        self.image_model_combo = ttk.Combobox(image_ai_bar, textvariable=self.image_model_var,
                                              values=[], state="readonly", width=27, font=("Segoe UI", 9))
        self.image_model_combo.pack(side="left")
        self.detect_models_button = ttk.Button(image_ai_bar, text="Detectar ComfyUI",
                                                command=self.detect_image_models)
        self.detect_models_button.pack(side="left", padx=(6, 0))
        self.generate_image_button = ttk.Button(image_ai_bar, text="Generar ilustración IA",
                                                style="Accent.TButton", command=self.generate_scene_image)
        self.generate_image_button.pack(side="left", padx=(6, 0))
        self.image_ai_status_var = tk.StringVar(value="ComfyUI local opcional · comprobando modelos…")
        tk.Label(scenes_tab, textvariable=self.image_ai_status_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 8), anchor="w",
                 wraplength=1000, justify="left").grid(row=5, column=0, sticky="ew", pady=(0, 7))

        scene_body = tk.Frame(scenes_tab, bg=self.colors["input"], padx=8, pady=8)
        scene_body.grid(row=6, column=0, sticky="nsew")
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
        tk.Label(scenes_tab, text="La generación de ilustraciones se ejecuta en ComfyUI en tu PC. Requiere instalarlo y descargar al menos un checkpoint compatible. No usa claves API ni servicios en la nube.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1000, justify="left").grid(row=7, column=0, sticky="w", pady=(8, 0))

        visual_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=18, pady=16)
        studio_tabs.add(visual_tab, text="  ✧  DIRECCIÓN VISUAL  ")
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
        self._field(visual_form, "Formato de salida", self.platform_var, 1, 0,
                    values=list(PLATFORMS))
        self._field(visual_form, "Género / dirección", self.style_var, 1, 1,
                    values=["Novela dramática", "Reencarnación y venganza", "Superación personal", "Romance",
                            "Fantasía", "Misterio y suspenso", "Terror", "Acción y aventura", "Ciencia ficción",
                            "Drama familiar", "Educativo y directo", "Documental", "Promocional"])
        self._field(visual_form, "Tono", self.tone_var, 2, 0,
                    values=["Dramático e intenso", "Oscuro y misterioso", "Emotivo", "Inspirador",
                            "Épico", "Ligero y humorístico", "Realista"])
        tk.Label(visual_tab, text="Nota: elegir un estilo define las instrucciones visuales; no crea ilustraciones por sí solo. Para generar imágenes, abre ESCENAS y configura ComfyUI.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").grid(row=3, column=0, sticky="w", pady=(16, 0))

        timeline_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=12, pady=10)
        studio_tabs.add(timeline_tab, text="  ▰  MONTAJE  ")
        timeline_tab.grid_columnconfigure(0, weight=1)
        timeline_tab.grid_rowconfigure(2, weight=1)
        timeline_head = tk.Frame(timeline_tab, bg=self.colors["panel"])
        timeline_head.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        tk.Label(timeline_head, text="LÍNEA DE TIEMPO", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 12, "bold")).pack(side="left")
        self.timeline_time_var = tk.StringVar(value="00:00 / 10:00")
        tk.Label(timeline_head, textvariable=self.timeline_time_var, bg=self.colors["panel"],
                 fg="#69b8ff", font=("Consolas", 10, "bold")).pack(side="right")
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
        timeline_shell = tk.Frame(timeline_tab, bg="#080e18",
                                  highlightthickness=1, highlightbackground=self.colors["border"])
        timeline_shell.grid(row=2, column=0, sticky="nsew")
        timeline_shell.grid_rowconfigure(0, weight=1)
        timeline_shell.grid_columnconfigure(0, weight=1)
        self.timeline_canvas = tk.Canvas(timeline_shell, bg="#080e18", height=245,
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
        studio_tabs.add(preview_tab, text="  ▣  VISTA PREVIA  ")
        preview_tab.grid_columnconfigure(0, weight=1)
        preview_tab.grid_rowconfigure(1, weight=1)
        preview_head = tk.Frame(preview_tab, bg=self.colors["panel"])
        preview_head.grid(row=0, column=0, sticky="ew", pady=(0, 12))
        tk.Label(preview_head, text="MONITOR DE VÍDEO", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 14, "bold")).pack(side="left")
        tk.Label(preview_head, textvariable=self.preview_scene_var, bg=self.colors["panel"],
                 fg="#69b8ff", font=("Segoe UI", 9, "bold")).pack(side="right")
        monitor = tk.Frame(preview_tab, bg="#03070d", highlightthickness=1,
                           highlightbackground=self.colors["border"])
        monitor.grid(row=1, column=0, sticky="nsew")
        monitor.grid_columnconfigure(0, weight=1)
        monitor.grid_rowconfigure(0, weight=1)
        self.preview_tab_canvas = tk.Canvas(monitor, bg="#03070d", highlightthickness=0,
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
        self.preview_status_var = tk.StringVar(value="El monitor muestra el storyboard de la escena seleccionada. Exporta para crear el MP4 final.")
        tk.Label(preview_tab, textvariable=self.preview_status_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1100, justify="left").grid(row=3, column=0, sticky="ew", pady=(10, 0))
        audio_tab = tk.Frame(studio_tabs, bg=self.colors["panel"], padx=16, pady=14)
        studio_tabs.add(audio_tab, text="  ♪  AUDIO  ")
        audio_tab.grid_columnconfigure(0, weight=1)
        audio_tab.grid_rowconfigure(6, weight=1)
        tk.Label(audio_tab, text="NARRACIÓN Y SONIDO", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 13, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(audio_tab, text="Importa una pista de voz/música o genera narración sin conexión usando las voces de Windows que ya estén instaladas.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").grid(row=1, column=0, sticky="w", pady=(4, 14))

        track_card = tk.Frame(audio_tab, bg=self.colors["input"], padx=13, pady=12,
                              highlightthickness=1, highlightbackground=self.colors["border"])
        track_card.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        tk.Label(track_card, text="NARRACIÓN / VOZ", bg=self.colors["input"], fg="#69b8ff",
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
        tk.Label(track_card, text="MÚSICA DE FONDO", bg=self.colors["input"], fg="#69b8ff",
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

        voice_card = tk.Frame(audio_tab, bg=self.colors["panel"], padx=13, pady=12,
                              highlightthickness=1, highlightbackground=self.colors["border"])
        voice_card.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        tk.Label(voice_card, text="GENERAR NARRACIÓN LOCAL", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(voice_card, text="Usa Windows System.Speech y las voces instaladas en el equipo. No requiere token, API ni envío de texto a la nube.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").pack(anchor="w", pady=(3, 10))
        voice_controls = tk.Frame(voice_card, bg=self.colors["panel"])
        voice_controls.pack(fill="x")
        tk.Label(voice_controls, text="VOZ", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 8, "bold")).pack(side="left", padx=(0, 7))
        self.voice_var = tk.StringVar(value="(Automática)")
        self.voice_combo = ttk.Combobox(voice_controls, textvariable=self.voice_var,
                                        values=["(Automática)"], state="readonly", width=35, font=("Segoe UI", 9))
        self.voice_combo.pack(side="left")
        self.detect_voice_button = ttk.Button(voice_controls, text="Detectar voces", command=self.detect_local_voices)
        self.detect_voice_button.pack(side="left", padx=(7, 0))
        self.generate_voice_button = ttk.Button(voice_controls, text="Generar narración", style="Accent.TButton",
                                                command=self.generate_local_voice)
        self.generate_voice_button.pack(side="left", padx=(7, 0))
        self.cancel_voice_button = ttk.Button(voice_controls, text="Cancelar voz", command=self.cancel_local_voice, state="disabled")
        self.cancel_voice_button.pack(side="left", padx=(7, 0))
        self.voice_status_var = tk.StringVar(value="Detectando voces locales de Windows…")
        tk.Label(audio_tab, textvariable=self.voice_status_var, bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w", wraplength=1050, justify="left").grid(row=4, column=0, sticky="ew", pady=(0, 10))
        subtitle_actions = tk.Frame(audio_tab, bg=self.colors["panel"])
        subtitle_actions.grid(row=5, column=0, sticky="ew", pady=(4, 9))
        self.export_srt_button = ttk.Button(
            subtitle_actions, text="Exportar subtítulos SRT", style="Accent.TButton",
            command=self.export_subtitles
        )
        self.export_srt_button.pack(side="left")
        tk.Label(subtitle_actions, text="Crea un archivo de subtítulos con tiempos aproximados por escena.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)).pack(side="left", padx=(10, 0))
        tk.Label(audio_tab, text="Para voces en español, instala un paquete de voz en Configuración de Windows → Hora e idioma → Voz. La voz disponible depende de Windows y del idioma instalado.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9),
                 wraplength=1050, justify="left").grid(row=6, column=0, sticky="nw", pady=(2, 0))

        mux_actions = tk.Frame(audio_tab, bg=self.colors["panel"])
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

        # Compact overview timeline, always visible below the script/scene workspace.
        mini_timeline = tk.Frame(lower, bg=self.colors["panel"], padx=8, pady=5,
                                 highlightthickness=1, highlightbackground=self.colors["border"])
        mini_timeline.grid(row=4, column=0, sticky="ew", pady=(5, 0))
        mini_timeline.grid_columnconfigure(0, weight=1)
        mini_head = tk.Frame(mini_timeline, bg=self.colors["panel"])
        mini_head.grid(row=0, column=0, sticky="ew", pady=(0, 3))
        tk.Label(mini_head, text="SECUENCIA / TIMELINE", bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 8, "bold")).pack(side="left")
        self.mini_time_var = tk.StringVar(value="00:00 / 10:00")
        tk.Label(mini_head, textvariable=self.mini_time_var, bg=self.colors["panel"],
                 fg="#69b8ff", font=("Consolas", 8, "bold")).pack(side="right")
        mini_shell = tk.Frame(mini_timeline, bg="#080e18")
        mini_shell.grid(row=1, column=0, sticky="ew")
        mini_shell.grid_columnconfigure(0, weight=1)
        self.mini_timeline_canvas = tk.Canvas(mini_shell, bg="#080e18", height=76,
                                             highlightthickness=0, borderwidth=0)
        self.mini_timeline_canvas.grid(row=0, column=0, sticky="ew")
        mini_xscroll = ttk.Scrollbar(mini_shell, orient="horizontal",
                                    command=self.mini_timeline_canvas.xview)
        mini_xscroll.grid(row=1, column=0, sticky="ew")
        self.mini_timeline_canvas.configure(xscrollcommand=mini_xscroll.set)
        self.mini_timeline_canvas.bind("<Button-1>", self._mini_timeline_click)
        self.mini_timeline_canvas.bind("<Configure>", lambda _event: self._draw_mini_timeline())

        self.status_var = tk.StringVar(value="Listo. Define una historia o abre un proyecto de la biblioteca.")
        self.after(250, lambda: studio_tabs.select(script_tab))
        self.after(300, self._draw_timeline)
        tk.Label(lower, textvariable=self.status_var, bg=self.colors["bg"], fg=self.colors["muted"],
                 font=("Segoe UI", 8), anchor="w").grid(row=5, column=0, sticky="ew", pady=(3, 0))

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
        bg = "#080e18"
        muted = self.colors["muted"]
        border = "#203651"
        canvas.create_rectangle(0, 0, width, height, fill=bg, outline=bg)
        canvas.create_rectangle(0, 0, left - 1, height, fill="#0d1726", outline="#0d1726")
        # Time ruler
        canvas.create_text(12, 16, text="TIEMPO", anchor="w", fill=muted,
                           font=("Segoe UI", 8, "bold"))
        tick = 30 if total <= 600 else 60
        for seconds in range(0, total + 1, tick):
            x = left + seconds * scale
            canvas.create_line(x, 28, x, height, fill="#18283b", width=1)
            canvas.create_line(x, 24, x, 32, fill="#5d7591", width=1)
            canvas.create_text(x + 3, 15, text=f"{seconds // 60:02d}:{seconds % 60:02d}",
                               anchor="w", fill="#9aadc6", font=("Consolas", 8))
        lanes = [
            ("VÍDEO", 36, 82, "#2678b9"),
            ("NARRACIÓN", 91, 125, "#159d8a"),
            ("MÚSICA", 134, 168, "#8060c7"),
            ("SUBTÍTULOS", 177, 211, "#b7791f"),
        ]
        for label, y1, y2, color in lanes:
            canvas.create_rectangle(0, y1, width, y2, fill="#0b1421", outline="#142338")
            canvas.create_text(12, (y1 + y2) / 2, text=label, anchor="w",
                               fill=color, font=("Segoe UI", 8, "bold"))
        durations = allocate_scene_durations(self.scene_data, total) if self.scene_data else []
        durations = [self.scene_duration_overrides.get(str(i + 1), value) for i, value in enumerate(durations)]
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
            color = "#245f91" if has_image else "#36475d"
            selected = getattr(self, "timeline_selected_scene", 1) == index + 1
            canvas.create_rectangle(x1 + 1, 39, max(x1 + 5, x2 - 2), 79,
                                    fill=color, outline="#55c5ff" if selected else "#42617f",
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
                                   anchor="w", fill="#62758b", font=("Segoe UI", 8))
        playhead = max(0, min(total, int(getattr(self, "timeline_playhead_seconds", 0))))
        px = left + playhead * scale
        canvas.create_line(px, 25, px, 215, fill="#ffcf5a", width=2, tags=("playhead",))
        canvas.create_polygon(px - 5, 25, px + 5, 25, px, 32, fill="#ffcf5a", outline="#ffcf5a")
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
            durations = [self.scene_duration_overrides.get(str(i + 1), value)
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
            canvas.create_rectangle(0, 0, full_width, height, fill="#080e18", outline="#080e18")
            canvas.create_rectangle(0, 0, left - 1, height, fill="#0d1726", outline="#0d1726")
            canvas.create_text(8, 13, text="TIEMPO", anchor="w", fill="#9aadc6", font=("Segoe UI", 7, "bold"))
            canvas.create_text(8, 35, text="VÍDEO", anchor="w", fill="#55b5ff", font=("Segoe UI", 7, "bold"))
            canvas.create_text(8, 57, text="VOZ", anchor="w", fill="#42d5ba", font=("Segoe UI", 7, "bold"))
            canvas.create_text(8, 75, text="MÚSICA", anchor="w", fill="#b29bff", font=("Segoe UI", 7, "bold"))
            tick = 60 if total <= 1800 else 300
            for seconds in range(0, total + 1, tick):
                pos = left + seconds * scale
                canvas.create_line(pos, 20, pos, height - 1, fill="#1c2b3e")
                canvas.create_text(pos + 3, 13, text=f"{seconds//60:02d}:{seconds%60:02d}",
                                   anchor="w", fill="#7489a3", font=("Consolas", 7))
            for x1, x2, number in positions:
                scene = self.scene_data[number - 1]
                asset = self.scene_assets.get(str(number), "")
                has_image = bool(asset and Path(asset).is_file())
                selected = number == getattr(self, "timeline_selected_scene", 1)
                fill = "#176e9d" if has_image else "#29384b"
                canvas.create_rectangle(x1, 24, x2 - 2, 45, fill=fill,
                                        outline="#68d3ff" if selected else "#46617d",
                                        width=2 if selected else 1, tags=(f"mini_scene_{number}",))
                clip_label = f"{number:02d} · {scene.get('title', f'Escena {number}')}"
                max_chars = max(4, int((x2 - x1 - 7) / 6))
                if len(clip_label) > max_chars:
                    clip_label = clip_label[:max(3, max_chars - 1)] + "…"
                if x2 - x1 > 26:
                    canvas.create_text(x1 + 4, 34, text=clip_label, anchor="w",
                                       fill="#f4f8ff", font=("Segoe UI", 7, "bold"),
                                       tags=(f"mini_scene_{number}",))
            voice_color = "#159d8a" if self.audio_track_path and Path(self.audio_track_path).is_file() else "#1a2935"
            music_color = "#6a4eab" if self.music_track_path and Path(self.music_track_path).is_file() else "#1a2935"
            canvas.create_rectangle(left, 49, full_width - 6, 64, fill=voice_color, outline=voice_color)
            voice_label = Path(self.audio_track_path).name if voice_color != "#1a2935" else "Sin narración"
            canvas.create_text(left + 5, 56, text=voice_label, anchor="w",
                               fill="#d9fff5" if voice_color != "#1a2935" else "#61748b",
                               font=("Segoe UI", 7, "bold"))
            canvas.create_rectangle(left, 68, full_width - 6, 82, fill=music_color, outline=music_color)
            music_label = Path(self.music_track_path).name if music_color != "#1a2935" else "Sin música"
            canvas.create_text(left + 5, 75, text=music_label, anchor="w",
                               fill="#e8ddff" if music_color != "#1a2935" else "#61748b",
                               font=("Segoe UI", 7, "bold"))
            playhead = max(0, int(getattr(self, "timeline_playhead_seconds", 0)))
            px = left + playhead * scale
            canvas.create_line(px, 19, px, height, fill="#ffcf5a", width=2, tags=("mini_playhead",))
            canvas.create_polygon(px - 4, 19, px + 4, 19, px, 25, fill="#ffcf5a", outline="#ffcf5a")
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
        durations = [self.scene_duration_overrides.get(str(i + 1), value)
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

    def _timeline_scene_selected(self, _event=None):
        number = self._scene_selection_number()
        if number is not None:
            self.timeline_selected_scene = number
            if hasattr(self, "scene_data") and number <= len(self.scene_data):
                durations = allocate_scene_durations(self.scene_data, self._timeline_duration_seconds())
                self.timeline_playhead_seconds = sum(durations[:number - 1])
            self._draw_timeline()
            self._render_preview_frame()

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
            durations = [self.scene_duration_overrides.get(str(i + 1), value) for i, value in enumerate(durations)]
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
            "Duración del clip", f"Duración de la escena {number} en segundos (5–3600):",
            initialvalue=current, minvalue=5, maxvalue=3600, parent=self
        )
        if value is None:
            return
        self.scene_duration_overrides[str(number)] = int(value)
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
        self.last_export_path = ""
        self.audio_track_path = ""
        self.music_track_path = ""
        if project_id is None:
            project_id = self.current_id
        if project_id is None:
            return
        project_dir = PROJECTS_DIR / str(project_id)
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
        try:
            loaded_durations = json.loads(duration_manifest.read_text(encoding="utf-8")) if duration_manifest.is_file() else {}
            self.scene_duration_overrides = {str(k): max(5, min(3600, int(v))) for k, v in loaded_durations.items() if str(k).isdigit()}
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
        self.scene_data = parse_script_scenes(script)
        try:
            target_seconds = max(60, int(self.duration_var.get() or "10") * 60)
        except (ValueError, tk.TclError):
            target_seconds = 600
        durations = allocate_scene_durations(self.scene_data, target_seconds)
        durations = [self.scene_duration_overrides.get(str(i + 1), value) for i, value in enumerate(durations)]
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
            self.scene_summary_var.set(f"{len(self.scene_data)} escenas · {total_words} palabras · objetivo {self.duration_var.get()} min · {voice_label} · {music_label}")
        self._draw_timeline()
        self._render_preview_frame()

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

    def detect_local_voices(self, quiet=False):
        if self.voice_generation_running:
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

    def generate_local_voice(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
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
            text_path.write_text(narration, encoding="utf-8")
            script_path.write_text(
                r"""param(
    [Parameter(Mandatory=$true)][string]$TextFile,
    [Parameter(Mandatory=$true)][string]$OutputFile,
    [Parameter(Mandatory=$false)][string]$VoiceName
)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    if ($VoiceName -and $VoiceName -ne '(Automática)') { $synth.SelectVoice($VoiceName) }
    $synth.Rate = 0
    $synth.Volume = 100
    $text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($text)) { throw 'El texto de narración está vacío.' }
    $synth.SetOutputToWaveFile($OutputFile)
    $synth.Speak($text)
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
        self.voice_generation_running = True
        self.voice_cancel_event.clear()
        self._set_voice_state(True)
        self.progressbar.configure(mode="indeterminate")
        self.progressbar.start(12)
        self.progress_label_var.set("Narración local en proceso")
        self.progress_detail_var.set("0% · Windows está sintetizando voz desde el guion")
        self.voice_status_var.set("Generando WAV sin conexión. La duración depende de la longitud del guion y la voz instalada.")
        self.status_var.set("La narración se genera localmente; puedes cancelar este proceso.")
        args = (int(self.current_id), str(text_path), str(script_path), str(output_path), chosen_voice)
        threading.Thread(target=self._local_voice_worker, args=args, daemon=True).start()

    def _set_voice_state(self, active):
        state = "disabled" if active else "normal"
        for button in (
            self.generate_button, self.new_project_button, self.save_button, self.approve_button,
            self.export_button, self.delete_button, self.assign_image_button, self.clear_image_button,
            self.refresh_scenes_button, self.select_audio_button, self.clear_audio_button,
            self.detect_models_button, self.generate_image_button, self.detect_voice_button,
            self.generate_voice_button, self.export_srt_button, self.select_music_button, self.clear_music_button
        ):
            button.configure(state=state)
        self.cancel_button.configure(state="disabled")
        self.cancel_render_button.configure(state="disabled")
        self.cancel_voice_button.configure(state="normal" if active else "disabled")
        self.project_list.configure(state=state)
        self._set_scene_list_state(active)
        self.image_model_combo.configure(state="disabled" if active else "readonly")
        self.voice_combo.configure(state="disabled" if active else "readonly")
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
            self.voice_status_var.set("Cancelación solicitada; deteniendo la síntesis de voz…")

    def _local_voice_worker(self, project_id, text_path, script_path, output_path, voice_name):
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
                     "-OutputFile", output_path, "-VoiceName", voice_name],
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
        scenes = parse_script_scenes(script)
        if not scenes:
            messagebox.showwarning("Sin guion", "Genera o escribe un guion antes de exportar subtítulos.")
            return
        try:
            target_seconds = max(60, int(self.duration_var.get() or "10") * 60)
        except ValueError:
            target_seconds = 600
        durations = allocate_scene_durations(scenes, target_seconds)
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
                                       fill="#55b5ff", font=("Segoe UI", 9, "bold"))
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

    def choose_preview_video(self):
        path = filedialog.askopenfilename(
            title="Selecciona un vídeo para previsualizar",
            filetypes=[("Vídeos", "*.mp4 *.mov *.mkv *.webm"), ("Todos los archivos", "*.*")]
        )
        if path:
            self.last_export_path = str(Path(path).resolve())
            self.preview_status_var.set(f"Vídeo seleccionado: {self.last_export_path}")

    def open_last_video(self):
        path = self.last_export_path
        if not path or not Path(path).is_file():
            self.choose_preview_video()
            path = self.last_export_path
        if not path or not Path(path).is_file():
            return
        try:
            if os.name == "nt":
                os.startfile(path)
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
            self.status_var.set(f"Abriendo vídeo en el reproductor del sistema: {Path(path).name}")
        except (OSError, AttributeError) as exc:
            messagebox.showerror("No se pudo abrir el vídeo", str(exc))

    def detect_image_models(self, quiet=False):
        if self.image_generation_running:
            return
        self.image_ai_status_var.set("Conectando con ComfyUI local…")
        threading.Thread(target=self._detect_image_models_worker, args=(quiet,), daemon=True).start()

    def _detect_image_models_worker(self, quiet=False):
        try:
            request = urllib.request.Request(
                COMFYUI_URL + "/object_info/CheckpointLoaderSimple",
                headers={"Accept": "application/json"}
            )
            with urllib.request.urlopen(request, timeout=4) as response:
                payload = json.loads(response.read().decode("utf-8"))
            node = payload.get("CheckpointLoaderSimple", payload)
            required = node.get("input", {}).get("required", {})
            option = required.get("ckpt_name", [])
            models = option[0] if option and isinstance(option[0], list) else []
            models = [str(model) for model in models]
            self.generation_queue.put(("image_models", models, quiet))
        except Exception as exc:
            self.generation_queue.put(("image_models_error", str(exc), quiet))

    def generate_scene_image(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            self.save_project(quiet=True)
        if self.current_id is None:
            messagebox.showwarning("Guarda el proyecto", "Completa el título y la premisa antes de generar imágenes.")
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
        self.progress_detail_var.set("IA de imágenes local · ComfyUI")
        self.status_var.set("Generando una ilustración local. En la GTX 750 puede tardar varios minutos.")
        args = (
            int(self.current_id), idx + 1, scene, model_name,
            self.drawing_style_var.get(), project["platform"], project["topic"]
        )
        threading.Thread(target=self._generate_scene_image_worker, args=args, daemon=True).start()

    def _set_image_state(self, active):
        state = "disabled" if active else "normal"
        self.cancel_button.configure(state="normal" if self.generation_running else "disabled")
        self.cancel_render_button.configure(state="normal" if self.render_running else "disabled")
        for button in (self.generate_button, self.new_project_button, self.save_button, self.approve_button,
                       self.export_button, self.delete_button, self.assign_image_button,
                       self.clear_image_button, self.refresh_scenes_button,
                       self.select_audio_button, self.clear_audio_button,
                       self.detect_models_button, self.generate_image_button,
                       self.detect_voice_button, self.generate_voice_button, self.export_srt_button, self.select_music_button, self.clear_music_button):
            button.configure(state=state)
        self.cancel_voice_button.configure(state="disabled")
        self.voice_combo.configure(state="disabled" if active else "readonly")
        self.project_list.configure(state=state)
        self._set_scene_list_state(active)
        self.cancel_button.configure(state="normal" if self.generation_running else "disabled")
        self.cancel_render_button.configure(state="normal" if self.render_running else "disabled")
        self.image_model_combo.configure(state="disabled" if active else "readonly")
        for widget, idle_state in self.form_widgets:
            widget.configure(state="disabled" if active else idle_state)
        self.script_text.configure(state="disabled" if active else "normal")
        if not active:
            self.progressbar.stop()
            self.progressbar.configure(mode="determinate")

    def _generate_scene_image_worker(self, project_id, scene_number, scene, checkpoint, drawing_style, platform_name, project_topic):
        try:
            self.generation_queue.put(("image_progress", scene_number, "Preparando el prompt visual local…"))
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
            story_excerpt = " ".join(str(scene.get("text", "")).split())[:650]
            visual_description = ""
            # Qwen optionally converts the prose to a compact English visual description; ComfyUI remains the local image engine.
            try:
                visual_description = self._ollama_request(
                    "Convert this Spanish story excerpt into one concise English image-generation prompt. "
                    "Describe only visible people, clothing, expression, action, setting, time of day, camera and lighting. "
                    "Do not add events not in the excerpt. Return only the prompt, no explanations. "
                    f"Story context: {project_topic}. Scene title: {scene.get('title', '')}. Excerpt: {story_excerpt}",
                    max_tokens=180
                )
            except Exception:
                visual_description = story_excerpt
            prompt = (
                f"{style_prompt}. Story moment: {visual_description}. "
                "single coherent frame, clear focal subject, strong composition, consistent character design, "
                "high quality, readable silhouettes, no captions, no writing, no logos, no watermark."
            )
            negative = (
                "text, subtitles, letters, watermark, logo, blurry, low resolution, malformed hands, "
                "extra fingers, extra limbs, duplicate people, distorted face, bad anatomy, compression artifacts"
            )
            if "TikTok" in platform_name or "9:16" in platform_name:
                width, height = 288, 512
            elif "1:1" in platform_name:
                width, height = 512, 512
            else:
                width, height = 512, 288
            client_id = os.urandom(12).hex()
            workflow = {
                "1": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": checkpoint}},
                "2": {"class_type": "CLIPTextEncode", "inputs": {"text": prompt, "clip": ["1", 1]}},
                "3": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["1", 1]}},
                "4": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
                "5": {"class_type": "KSampler", "inputs": {
                    "seed": random.randint(1, 2**31 - 1), "steps": 18, "cfg": 6.5,
                    "sampler_name": "euler", "scheduler": "normal", "denoise": 1.0,
                    "model": ["1", 0], "positive": ["2", 0], "negative": ["3", 0], "latent_image": ["4", 0]
                }},
                "6": {"class_type": "VAEDecode", "inputs": {"samples": ["5", 0], "vae": ["1", 2]}},
                "7": {"class_type": "SaveImage", "inputs": {
                    "filename_prefix": f"MARC_Studio/scene_{scene_number:03d}", "images": ["6", 0]
                }},
            }
            body = json.dumps({"prompt": workflow, "client_id": client_id}).encode("utf-8")
            request = urllib.request.Request(
                COMFYUI_URL + "/prompt", data=body,
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
                    COMFYUI_URL + "/history/" + str(prompt_id),
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
            request = urllib.request.Request(COMFYUI_URL + "/view?" + query)
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
                f"Checkpoint: {checkpoint}\nEstilo: {drawing_style}\nPrompt: {prompt}\nNegative: {negative}\n",
                encoding="utf-8"
            )
            self.generation_queue.put(("image_done", project_id, scene_number, str(destination.resolve()), prompt))
        except Exception as exc:
            self.generation_queue.put(("image_error", scene_number, str(exc)))

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
                minsize=285, width=325, stretch="never"
            )
            self.configuration_visible = True
        elif not visible and is_visible:
            self.vertical_panes.forget(self.controls_area)
            self.configuration_visible = False
        else:
            self.configuration_visible = is_visible
        if hasattr(self, "config_toggle_button"):
            self.config_toggle_button.configure(
                text="Ocultar configuración" if self.configuration_visible else "Mostrar configuración"
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

    def _field(self, parent, label, variable, row, col, values=None, span=1):
        cell = tk.Frame(parent, bg=self.colors["panel"])
        cell.grid(row=row, column=col, columnspan=span, sticky="ew", padx=4, pady=3)
        tk.Label(cell, text=label.upper(), bg=self.colors["panel"], fg="#8fa8c8",
                 font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(0, 3))
        if values is not None:
            widget = ttk.Combobox(cell, textvariable=variable, values=values,
                                  state="readonly", font=("Segoe UI", 9))
        else:
            widget = ttk.Entry(cell, textvariable=variable, font=("Segoe UI", 9))
        widget.pack(fill="x", ipady=1)
        self.form_widgets.append((widget, "readonly" if values is not None else "normal"))
        return widget

    def new_project(self):
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual antes de crear otro proyecto.")
            return
        self.current_id = None
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
        self.progressbar.configure(value=0)
        self.progress_label_var.set("Listo para planificar el guion.")
        self.progress_detail_var.set("0% · Esperando inicio")
        self.script_text.delete("1.0", "end")
        self.scene_assets = {}
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

    def get_form(self):
        title = self.title_var.get().strip()
        topic = self.topic_var.get().strip()
        try:
            duration = int(self.duration_var.get())
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
            "animation_style": self.animation_style_var.get()
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

    def generate_script(self):
        data = self.get_form()
        if not data:
            return
        if self.generation_running or self.render_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        minutes = data["duration"]
        preflight = messagebox.askyesno(
            "Antes de generar el guion",
            "Esta etapa genera el GUION con Ollama; no crea imágenes ni exporta el MP4.\n\n"
            "Después tendrás que ir a ESCENAS para asignar imágenes propias o generar ilustraciones con ComfyUI "
            "(si está instalado y tienes un modelo compatible). Sin imágenes, el vídeo será de tarjetas de texto.\n\n"
            f"Duración solicitada: {minutes} min. El proceso puede tardar bastante en este equipo.\n\n"
            "¿Deseas iniciar la generación del guion ahora?"
        )
        if not preflight:
            return
        self.estimate_var.set(self._estimate_time(minutes))
        # Genera capítulos de aproximadamente 5 minutos para evitar una sola petición enorme.
        chapter_count = max(1, math.ceil(minutes / 5))
        self.planned_chapters = chapter_count
        self.completed_chapters = 0
        self.planned_words = minutes * 135
        self.progressbar.configure(maximum=chapter_count, value=0)
        self.progress_label_var.set(f"Plan: {chapter_count} capítulos · objetivo ~{self.planned_words:,} palabras")
        self.progress_detail_var.set("0% · Preparando la estructura")
        if minutes >= 45:
            confirm = messagebox.askyesno(
                "Guion largo",
                f"Un guion de {minutes} minutos puede necesitar {chapter_count} capítulos generados por separado "
                "y tardar bastante con Qwen 2.5 3B en tu equipo.\n\n¿Deseas continuar?"
            )
            if not confirm:
                return
        # El foco pasa al editor; la configuración completa queda disponible con un botón.
        self.set_configuration_visible(False)
        self.save_project(reset_approval=True, quiet=True)
        self.cancel_event.clear()
        self.generation_running = True
        self._set_generation_state(True)
        self.script_text.configure(state="normal")
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0",
            f"TÍTULO: {data['title']}\nGÉNERO: {data['genre']}\nDURACIÓN OBJETIVO: {minutes} minuto(s)\n"
            "MODELO: Qwen 2.5 3B · ejecución local\n\n")
        self.script_text.configure(state="disabled")
        self.status_var.set(f"Preparando estructura de historia y {chapter_count} capítulo(s)…")
        self.progress_detail_var.set("0% · Consultando modelo local")
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
        for widget, idle_state in self.form_widgets:
            widget.configure(state="disabled" if active else idle_state)
        self.script_text.configure(state="disabled" if active else "normal")
        for button in (self.new_project_button, self.assign_image_button, self.clear_image_button,
                       self.refresh_scenes_button, self.select_audio_button, self.clear_audio_button,
                       self.detect_models_button, self.generate_image_button, self.detect_voice_button,
                       self.generate_voice_button, self.export_srt_button, self.select_music_button, self.clear_music_button):
            button.configure(state=state)
        self.cancel_voice_button.configure(state="disabled")
        self.image_model_combo.configure(state="disabled" if active else "readonly")
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
            self.generation_queue.put(("status", "Qwen está diseñando la biblia de personajes y la trama…"))
            protagonist = data["protagonist"] or "crea un protagonista original con nombre memorable"
            conflict = data["conflict"] or "crea un conflicto personal y externo con consecuencias claras"
            plan_prompt = (
                "Eres director de guion de una novela serializada para videos. Escribe en español. "
                "Crea una biblia breve de continuidad y una escaleta por capítulos. Incluye: premisa, "
                "protagonistas y antagonistas con nombres, objetivos, defectos, relaciones y secretos; "
                "reglas del mundo; conflicto central; evolución emocional; giros y consecuencias; y "
                "desenlace acorde a lo pedido. No escribas consejos genéricos: diseña una ficción concreta. "
                f"Género: {data['genre']}. Premisa: {data['topic']}. Protagonista: {protagonist}. "
                f"Conflicto: {conflict}. Tono: {data['tone']}. Narrador: {data['narrator']}. "
                f"Desenlace: {data['ending']}. Dirección visual: dibujo {data['drawing_style']}; animación {data['animation_style']}. "
                f"Audiencia general de YouTube. Duración: {data['duration']} min. "
                f"Propón exactamente {chapter_count} capítulos y resume cada uno en 1-2 frases. "
                "No afirmes que esta escaleta es el guion final."
            )
            plan = self._ollama_request(plan_prompt, max_tokens=min(1000, 350 + chapter_count * 24))
            self.generation_queue.put(("status", "Estructura preparada. Escribiendo los capítulos en orden…"))
            previous_excerpt = ""
            completed = 0
            words_per_chapter = max(150, round(data["duration"] * 135 / chapter_count))
            for index in range(1, chapter_count + 1):
                if self.cancel_event.is_set():
                    self.generation_queue.put(("cancelled",))
                    return
                self.generation_queue.put(("status", f"Escribiendo capítulo {index} de {chapter_count}…"))
                prompt = (
                    "Eres novelista y guionista. Continúa la historia indicada y escribe SOLO el capítulo solicitado, "
                    "en español natural, con escenas concretas, acción, diálogo y emociones mostradas mediante "
                    "acciones. Evita resúmenes, consejos al público, frases repetidas y relleno. Conserva nombres, "
                    "motivaciones, relaciones, heridas, secretos, cronología y reglas de la historia. No vuelvas a "
                    "presentar personajes ya conocidos como si fueran nuevos. Termina este capítulo con un cambio "
                    "o una pregunta dramática que impulse el siguiente, salvo que sea el desenlace final. "
                    f"Género: {data['genre']}. Premisa: {data['topic']}. Tono: {data['tone']}. "
                    f"Voz narrativa: {data['narrator']}. Protagonista: {protagonist}. Conflicto: {conflict}. "
                    f"Desenlace planificado: {data['ending']}. Plataforma: {data['platform']}. "
                    f"Dirección visual para futuras escenas: {data['drawing_style']}; animación: {data['animation_style']}. "
                    f"Duración objetivo total: {data['duration']} minutos. Capítulo {index} de {chapter_count}. "
                    f"Objetivo: aproximadamente {words_per_chapter} palabras de narración y diálogos; desarrolla "
                    "la escena completa, no la resumas.\n\nBIBLIA Y ESCALETA DE CONTINUIDAD:\n" + plan +
                    (("\n\nFINAL DEL CAPÍTULO ANTERIOR (para continuidad):\n" + previous_excerpt)
                     if previous_excerpt else "\n\nEste es el inicio de la historia; presenta el gancho y al protagonista.")
                )
                token_budget = max(420, min(1300, int(words_per_chapter * 1.8) + 120))
                chapter = self._ollama_request(prompt, max_tokens=token_budget)
                heading = f"\n\n[CAPÍTULO {index:02d} DE {chapter_count:02d}]\n"
                self.generation_queue.put(("chapter", heading + chapter.strip() + "\n", index, chapter_count))
                previous_excerpt = chapter[-2200:]
                completed += 1
            self.generation_queue.put(("done", completed))
        except Exception as exc:
            self.generation_queue.put(("error", str(exc)))

    def save_project(self, reset_approval=False, quiet=False):
        data = self.get_form()
        if not data:
            return
        script = self.script_text.get("1.0", "end-1c")
        now = datetime.now().isoformat(timespec="seconds")
        record = {
            "title": data["title"], "topic": data["topic"], "platform": data["platform"],
            "duration_minutes": data["duration"], "style": data["genre"], "script": script,
            "protagonist": data["protagonist"], "conflict": data["conflict"], "tone": data["tone"],
            "narrator": data["narrator"], "ending": data["ending"],
            "drawing_style": data["drawing_style"], "animation_style": data["animation_style"]
        }
        previous = None
        if self.current_id is not None:
            previous = self.conn.execute("SELECT * FROM projects WHERE id=?", (self.current_id,)).fetchone()
        changed = previous is None or any(str(previous[key] or "") != str(value or "")
                                          for key, value in record.items())
        approved = 0 if reset_approval or changed else int(previous["approved"])
        if self.current_id is None:
            cur = self.conn.execute(
                "INSERT INTO projects(title,topic,platform,duration_minutes,style,script,approved,created_at,"
                "protagonist,conflict,tone,narrator,ending,drawing_style,animation_style) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (record["title"], record["topic"], record["platform"], record["duration_minutes"],
                 record["style"], record["script"], approved, now, record["protagonist"],
                 record["conflict"], record["tone"], record["narrator"], record["ending"],
                 record["drawing_style"], record["animation_style"]))
            self.current_id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE projects SET title=?,topic=?,platform=?,duration_minutes=?,style=?,script=?,approved=?,created_at=?,"
                "protagonist=?,conflict=?,tone=?,narrator=?,ending=?,drawing_style=?,animation_style=? WHERE id=?",
                (record["title"], record["topic"], record["platform"], record["duration_minutes"],
                 record["style"], record["script"], approved, now, record["protagonist"],
                 record["conflict"], record["tone"], record["narrator"], record["ending"],
                 record["drawing_style"], record["animation_style"], self.current_id))
        self.conn.commit()
        self.refresh_projects()
        if not quiet:
            self.status_var.set("Proyecto guardado. " + ("Guion aprobado." if approved else "Pendiente de revisión y aprobación."))

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
                elif kind == "voice_cancelled":
                    self.voice_generation_running = False
                    self._set_voice_state(False)
                    self.progress_label_var.set("Generación de voz cancelada")
                    self.progress_detail_var.set("La narración no se cambió.")
                    self.voice_status_var.set("Cancelado.")
                    self.status_var.set("Se canceló la síntesis de voz local.")
                elif kind == "voice_error":
                    self.voice_generation_running = False
                    self._set_voice_state(False)
                    self.progress_label_var.set("Error al generar la voz")
                    self.progress_detail_var.set("Comprueba que Windows tenga System.Speech y una voz instalada.")
                    self.voice_status_var.set("Falló la generación de voz.")
                    self.status_var.set("No se pudo completar la narración local.")
                    messagebox.showerror(
                        "Error de narración local",
                        "Windows no pudo generar la narración. Revisa que haya una voz instalada y prueba otra vez.\n\n" + event[1]
                    )
                elif kind == "image_models":
                    models, quiet = event[1], event[2]
                    self.comfy_available = True
                    self.image_model_combo.configure(values=models)
                    current_model = self.image_model_var.get()
                    if current_model in models:
                        self.image_model_var.set(current_model)
                    elif models:
                        self.image_model_var.set(models[0])
                    self.image_ai_status_var.set(
                        f"ComfyUI conectado · {len(models)} modelo(s) local(es) disponibles"
                        if models else
                        "ComfyUI conectado, pero falta un checkpoint en models/checkpoints"
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
                    self.image_ai_status_var.set("ComfyUI local no detectado · las imágenes propias siguen disponibles")
                    if not quiet:
                        messagebox.showinfo(
                            "Generador local de imágenes no detectado",
                            "MARC puede renderizar imágenes que importes sin ComfyUI. Para generar ilustraciones localmente, instala/abre ComfyUI en http://127.0.0.1:8188 y coloca un checkpoint compatible.\n\nDetalle: " + detail
                        )
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
                    messagebox.showinfo("Ilustración lista", f"Se generó la imagen local para la escena {scene_number}.\n\nPuedes exportar el MP4 cuando el guion esté aprobado.")
                elif kind == "image_error":
                    scene_number, detail = event[1], event[2]
                    self.image_generation_running = False
                    self._set_image_state(False)
                    self.progress_label_var.set(f"Ilustración fallida · escena {scene_number}")
                    self.progress_detail_var.set("Comprueba ComfyUI, el checkpoint y su consola.")
                    self.status_var.set("No se pudo generar la ilustración local.")
                    messagebox.showerror("Error de ilustración IA", detail)
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
                    self.progressbar.configure(value=100)
                    self.progress_label_var.set(f"Guion completado · {event[1]} capítulos")
                    self.progress_detail_var.set("100% · Revisión y aprobación humana pendientes")
                    self.script_text.configure(state="normal")
                    self.script_text.insert("end", "\n\n[REVISIÓN HUMANA PENDIENTE]\nRevisa continuidad, nombres, ritmo y duración. El guion no está aprobado.")
                    self.script_text.configure(state="disabled")
                    self.save_project(reset_approval=True, quiet=True)
                    self.generation_running = False
                    self._set_generation_state(False)
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
                    self.generation_running = False
                    self._set_generation_state(False)
                    self.status_var.set("Generación cancelada. El borrador parcial se conservó sin aprobar.")
                elif kind == "error":
                    percent = round((getattr(self, "completed_chapters", 0) / max(1, getattr(self, "planned_chapters", 1))) * 100)
                    self.progressbar.configure(value=percent)
                    self.progress_label_var.set("La generación se detuvo · borrador parcial conservado")
                    self.progress_detail_var.set(f"{percent}% · Revisa el mensaje de error y la conexión de Ollama")
                    self.script_text.configure(state="normal")
                    self.save_project(reset_approval=True, quiet=True)
                    self.generation_running = False
                    self._set_generation_state(False)
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
                    self.last_export_path = event[1]
                    if hasattr(self, "preview_status_var"):
                        self.preview_status_var.set(f"Último vídeo exportado: {self.last_export_path}")
                    self.progressbar.configure(maximum=100, value=100)
                    self.progress_label_var.set("Vídeo exportado correctamente")
                    self.progress_detail_var.set(f"100% · {event[2]} escenas · duración aproximada {self._format_eta(event[3])}")
                    self.status_var.set(f"MP4 creado: {self.last_export_path}")
                    messagebox.showinfo("Exportación terminada", f"Vídeo MP4 creado en:\n{self.last_export_path}\n\nPuedes abrirlo desde la pestaña VISTA PREVIA.")
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
                    self.render_running = False
                    self._set_render_state(False)
                    self.progress_label_var.set("Exportación cancelada")
                    self.progress_detail_var.set("El render se detuvo por petición del usuario. El MP4 parcial puede no reproducirse.")
                    self.status_var.set("Exportación cancelada.")
                elif kind == "render_error":
                    self.render_running = False
                    self._set_render_state(False)
                    self.progress_label_var.set("Error durante la exportación")
                    self.progress_detail_var.set("Revisa el mensaje de FFmpeg y la disponibilidad de recursos.")
                    self.status_var.set("No se pudo completar el MP4.")
                    messagebox.showerror("Error de exportación", event[1])
        except queue.Empty:
            pass
        self.after(180, self._poll_generation_events)

    def _existing_approval(self):
        if self.current_id is None:
            return 0
        row = self.conn.execute("SELECT approved FROM projects WHERE id=?", (self.current_id,)).fetchone()
        return int(row["approved"]) if row else 0

    def approve_script(self):
        if not self.script_text.get("1.0", "end-1c").strip():
            messagebox.showwarning("Sin guion", "Genera o escribe un guion antes de aprobarlo.")
            return
        if not messagebox.askyesno("Confirmar aprobación", "¿Has revisado el guion y confirmas que está listo para renderizar?"):
            return
        self.save_project(quiet=True)
        if self.current_id is not None:
            self.conn.execute("UPDATE projects SET approved=1 WHERE id=?", (self.current_id,))
            self.conn.commit()
            self.refresh_projects()
        self.status_var.set("Guion aprobado por el usuario. Ya puedes exportar el MP4.")

    def refresh_projects(self):
        rows = self.conn.execute("SELECT id,title,approved FROM projects ORDER BY id DESC").fetchall()
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
        row = self.project_rows[selection[0]]
        project = self.conn.execute("SELECT * FROM projects WHERE id=?", (row["id"],)).fetchone()
        if not project:
            return
        self.current_id = project["id"]
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

    def export_video(self):
        if self.render_running or self.generation_running or self.image_generation_running or self.voice_generation_running:
            messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.")
            return
        if self.current_id is None:
            messagebox.showwarning("Guarda primero", "Guarda el proyecto antes de exportar.")
            return
        self.save_project(quiet=True)
        row = self.conn.execute("SELECT * FROM projects WHERE id=?", (self.current_id,)).fetchone()
        if not row or not row["approved"]:
            messagebox.showerror("Aprobación obligatoria", "No se puede exportar: primero debes aprobar el guion.")
            return
        scenes = parse_script_scenes(row["script"] or "")
        if not scenes:
            messagebox.showerror("Guion vacío", "El guion no contiene escenas exportables. Genera o escribe el guion primero.")
            return
        asset_map = dict(self.scene_assets)
        for key, value in list(asset_map.items()):
            if not Path(value).is_file():
                asset_map.pop(key, None)
        has_scene_images = any(asset_map.get(str(i + 1)) for i in range(len(scenes)))
        if not has_scene_images:
            continue_text_only = messagebox.askyesno(
                "Faltan imágenes para el vídeo",
                "El guion está listo, pero ninguna escena tiene una imagen asignada.\n\n"
                "Si continúas, el MP4 tendrá tarjetas de texto sobre fondos oscuros; "
                "MARC NO generará ilustraciones automáticamente durante la exportación.\n\n"
                "Pulsa «No» para volver a ESCENAS y asignar imágenes, o «Sí» para continuar con vídeo de texto."
            )
            if not continue_text_only:
                return
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            selected = filedialog.askopenfilename(
                title="Selecciona ffmpeg.exe",
                filetypes=[("FFmpeg ejecutable", "ffmpeg.exe"), ("Ejecutables", "*.exe")]
            )
            if not selected:
                messagebox.showerror("FFmpeg no encontrado", "Selecciona ffmpeg.exe de la carpeta bin para exportar.")
                return
            if Path(selected).name.lower() != "ffmpeg.exe":
                messagebox.showerror("Archivo incorrecto", "Selecciona el archivo ffmpeg.exe.")
                return
            ffmpeg = selected
        output = filedialog.asksaveasfilename(
            title="Guardar vídeo MP4", defaultextension=".mp4",
            filetypes=[("Vídeo MP4", "*.mp4")],
            initialfile=f"{row['title'][:40]}.mp4"
        )
        if not output:
            return
        width, height = PLATFORMS.get(row["platform"], (1280, 720))
        # Perfil ligero para CPU con pocos hilos o equipos con poca RAM: conserva la proporción.
        pc_info = getattr(self, "pc_info", {})
        try:
            logical_cores = int(pc_info.get("cores") or os.cpu_count() or 2)
            ram_gb = float(pc_info.get("ram_gb") or 8)
        except (TypeError, ValueError):
            logical_cores, ram_gb = (os.cpu_count() or 2), 8.0
        if logical_cores <= 4 or ram_gb < 8:
            max_side = 854
            scale = min(1.0, max_side / max(width, height))
            width = max(2, int(width * scale) // 2 * 2)
            height = max(2, int(height * scale) // 2 * 2)
            self.status_var.set(
                f"Perfil ligero activado ({logical_cores} hilos, {ram_gb:g} GB RAM): "
                f"render a {width}×{height} para reducir la carga del equipo."
            )
        target_seconds = max(60, int(row["duration_minutes"]) * 60)
        durations = allocate_scene_durations(scenes, target_seconds)
        durations = [self.scene_duration_overrides.get(str(i + 1), value) for i, value in enumerate(durations)]
        audio_path = self.audio_track_path if self.audio_track_path and Path(self.audio_track_path).is_file() else ""
        music_path = self.music_track_path if self.music_track_path and Path(self.music_track_path).is_file() else ""
        loop_music = bool(self.loop_music_var.get()) if self.loop_music_var is not None else True
        # En Windows, la narración se crea automáticamente si no se importó una pista de voz.
        has_any_audio = bool(audio_path or music_path or os.name == "nt")
        render_steps = len(scenes) + 1 + (1 if has_any_audio else 0)
        self.render_cancel_event.clear()
        self.render_running = True
        self._set_render_state(True)
        self.progressbar.configure(maximum=render_steps, value=0)
        self.progress_label_var.set(f"Preparando render · {len(scenes)} escenas")
        self.progress_detail_var.set(f"0% · Duración objetivo: {self._format_eta(sum(durations))}")
        self.status_var.set("Render iniciado en segundo plano. Puedes seguir viendo el progreso aquí.")
        # Si no hay pista de voz importada, la narración se generará automáticamente durante la exportación.
        narration_text = "\\n\\n".join(
            str(scene.get("text", "")).strip() for scene in scenes if str(scene.get("text", "")).strip()
        ).strip() if not audio_path and os.name == "nt" else ""
        chosen_voice = self.voice_var.get().strip() if hasattr(self, "voice_var") else "(Automática)"
        args = (
            ffmpeg, str(Path(output).resolve()), int(row["id"]), width, height,
            scenes, durations, asset_map, row["animation_style"] or "2D fluida",
            audio_path, music_path, loop_music, narration_text, chosen_voice
        )
        threading.Thread(target=self._render_video_worker, args=args, daemon=True).start()

    def _set_render_state(self, active):
        state = "disabled" if active else "normal"
        self.generate_button.configure(state=state)
        self.cancel_button.configure(state="disabled" if not active else "disabled")
        self.cancel_render_button.configure(state="normal" if active else "disabled")
        for button in (self.new_project_button, self.save_button, self.approve_button,
                       self.export_button, self.delete_button, self.assign_image_button,
                       self.clear_image_button, self.refresh_scenes_button,
                       self.select_audio_button, self.clear_audio_button,
                       self.select_music_button, self.clear_music_button,
                       self.detect_models_button, self.generate_image_button,
                       self.detect_voice_button, self.generate_voice_button, self.export_srt_button):
            button.configure(state=state)
        self.cancel_voice_button.configure(state="disabled")
        self.voice_combo.configure(state="disabled" if active else "readonly")
        self.project_list.configure(state=state)
        self.cancel_button.configure(state="disabled")
        for widget, idle_state in self.form_widgets:
            widget.configure(state="disabled" if active else idle_state)
        self.script_text.configure(state="disabled" if active else "normal")
        self.image_model_combo.configure(state="disabled" if active else "readonly")
        self._set_scene_list_state(active)

    def cancel_export(self):
        if self.render_running:
            self.render_cancel_event.set()
            self.cancel_render_button.configure(state="disabled")
            self.status_var.set("Cancelación solicitada. Se detendrá el proceso FFmpeg actual.")

    def _render_video_worker(self, ffmpeg, output, project_id, width, height,
                             scenes, durations, asset_map, animation_style,
                             audio_path="", music_path="", loop_music=True,
                             narration_text="", chosen_voice="(Automática)"):
        scene_dir = PROJECTS_DIR / str(project_id) / "render_work"
        scene_dir.mkdir(parents=True, exist_ok=True)
        output_path = Path(output)
        temp_output_path = output_path.with_name(output_path.stem + ".marc_rendering.mp4")

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
                narration_text_path.write_text(narration_text, encoding="utf-8")
                narration_script_path.write_text(r"""param([string]$TextFile,[string]$OutputFile,[string]$VoiceName)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Speech
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
  if ($VoiceName -and $VoiceName -ne '(Automática)') { $synth.SelectVoice($VoiceName) }
  $synth.Rate = 0
  $synth.Volume = 100
  $text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
  if ([string]::IsNullOrWhiteSpace($text)) { throw 'El texto de narración está vacío.' }
  $synth.SetOutputToWaveFile($OutputFile)
  $synth.Speak($text)
  $synth.SetOutputToNull()
} finally { $synth.Dispose() }
if (!(Test-Path -LiteralPath $OutputFile) -or (Get-Item -LiteralPath $OutputFile).Length -lt 44) {
  throw 'Windows no generó un archivo WAV válido.'
}
""", encoding="utf-8")
                self.generation_queue.put(("render_progress", 0, len(scenes) + 3, "Generando narración automática con la voz local de Windows…"))
                ps_args = [
                    "powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                    str(narration_script_path), str(narration_text_path), str(generated_voice_path),
                    chosen_voice or "(Automática)"
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
            elapsed_before_scene = 0
            chunk_seconds = 5 * 60
            for index, scene in enumerate(scenes):
                if self.render_cancel_event.is_set():
                    raise RuntimeError("__MARC_RENDER_CANCELLED__")
                seconds = int(durations[index])
                source_text = " ".join(scene["text"].split()).strip()
                asset = asset_map.get(str(index + 1), "")
                asset_signature = None
                if asset and Path(asset).is_file():
                    asset_path = Path(asset)
                    stat = asset_path.stat()
                    asset_signature = {
                        "path": str(asset_path.resolve()), "size": stat.st_size,
                        "mtime_ns": stat.st_mtime_ns
                    }
                cache_payload = {
                    "scene": scene, "duration": seconds, "asset": asset_signature,
                    "animation": animation_style, "width": width, "height": height,
                    "fps": 24, "preset": "ultrafast", "crf": 25, "version": 2
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
                if asset and Path(asset).is_file():
                    motion = scene_motion_filter(animation_style, width, height, seconds)
                    video_filter = f"{motion},{draw_filter}"
                    cmd = [
                        ffmpeg, "-y", "-loop", "1", "-framerate", "24", "-i", str(Path(asset).resolve()),
                        "-t", str(seconds), "-vf", video_filter, "-an", "-r", "24",
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
                        f"color=c=0x0b1320:s={width}x{height}:r=24",
                        "-t", str(seconds), "-vf", video_filter, "-an", "-r", "24",
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

            concat_path = scene_dir / "concat.txt"
            concat_path.write_text(
                "".join(f"file 'scene_{i + 1:03d}.mp4'\n" for i in range(total)),
                encoding="utf-8"
            )
            if self.render_cancel_event.is_set():
                raise RuntimeError("__MARC_RENDER_CANCELLED__")
            self.generation_queue.put(("render_progress", total + 1, final_steps, "Uniendo escenas y finalizando MP4…"))
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
                    has_voice, has_music, voice_input_index, music_input_index
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
            project_dir = PROJECTS_DIR / str(project_id)
            (project_dir / "last_export.txt").write_text(str(output_path), encoding="utf-8")
            self.generation_queue.put(("render_done", str(output_path), total, sum(durations)))
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
