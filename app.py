from __future__ import annotations

import json
import math
import os
import queue
import shutil
import sqlite3
import subprocess
import textwrap
import threading
import platform
import ctypes
import urllib.request
import urllib.error
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from pathlib import Path

APP_NAME = "MARC Video Studio AI Desktop"
ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PROJECTS_DIR = ROOT / "projects"
DB_PATH = DATA_DIR / "marc_video_studio.db"

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
        self.geometry("1180x720")
        self.minsize(960, 630)
        self.conn = db_connect()
        self.current_id = None
        self.ai_available = False
        self.generation_queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.generation_running = False
        self._style()
        self._build()
        self.refresh_projects()
        self.after(700, self.detect_pc_async)
        self.check_tools()
        self.after(180, self._poll_generation_events)

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
        render_low = max(0.5, scenes * 0.025)
        render_high = max(render_low + 0.5, scenes * 0.09)
        # A first local model load can add substantial overhead.
        first_run = " La primera ejecución puede tardar más mientras carga el modelo." if not getattr(self, "ai_available", False) else ""
        return f"Estimado para {minutes} min de video: guion {self._format_eta(script_low*60)}–{self._format_eta(script_high*60)}; render de escenas de texto {self._format_eta(render_low*60)}–{self._format_eta(render_high*60)}. Total orientativo {self._format_eta(script_low*60+render_low*60)}–{self._format_eta(script_high*60+render_high*60)}.{first_run} No incluye generación de imágenes, animación real ni voz, todavía no implementadas."

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
            "bg": "#08111f", "panel": "#101d31", "panel2": "#142640",
            "input": "#0b1728", "accent": "#2585ff", "accent_hover": "#4a9bff",
            "text": "#edf4ff", "muted": "#9bb0ca", "border": "#263b57",
            "success": "#70e1b1", "warning": "#ffd166", "danger": "#ff8f8f"
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
        style.configure("Title.TLabel", background=self.colors["bg"], foreground="#69b0ff", font=("Segoe UI", 22, "bold"))
        style.configure("Section.TLabel", background=self.colors["panel"], foreground=self.colors["text"], font=("Segoe UI", 11, "bold"))
        style.configure("TButton", padding=(11, 8), font=("Segoe UI", 9, "bold"), background=self.colors["panel2"], foreground=self.colors["text"], borderwidth=0)
        style.map("TButton", background=[("active", self.colors["accent"]), ("pressed", self.colors["accent"])], foreground=[("disabled", "#60738b")])
        style.configure("Accent.TButton", padding=(13, 10), font=("Segoe UI", 9, "bold"), background=self.colors["accent"], foreground="#ffffff", borderwidth=0)
        style.map("Accent.TButton", background=[("active", self.colors["accent_hover"]), ("pressed", self.colors["accent_hover"])])
        style.configure("TEntry", padding=7, fieldbackground=self.colors["input"], foreground=self.colors["text"], insertcolor=self.colors["text"])
        style.configure("TCombobox", padding=7, fieldbackground=self.colors["input"], foreground=self.colors["text"], background=self.colors["panel2"], arrowcolor=self.colors["text"])
        style.map("TCombobox", fieldbackground=[("readonly", self.colors["input"])], foreground=[("readonly", self.colors["text"])])

    def _build(self):
        outer = ttk.Frame(self, padding=18)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer, bg=self.colors["bg"])
        header.pack(fill="x", pady=(0, 16))
        title_col = tk.Frame(header, bg=self.colors["bg"])
        title_col.pack(side="left", fill="x", expand=True)
        tk.Label(title_col, text="MARC  /  STUDIO", bg=self.colors["bg"], fg="#69b0ff",
                 font=("Segoe UI", 23, "bold")).pack(anchor="w")
        tk.Label(title_col, text="Tu estudio creativo con inteligencia artificial local",
                 bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 10)).pack(anchor="w", pady=(2, 0))
        header_actions = tk.Frame(header, bg=self.colors["bg"])
        header_actions.pack(side="right", anchor="e")
        self.ai_badge = tk.Label(header_actions, text="● IA LOCAL · COMPROBANDO",
                                 bg=self.colors["bg"], fg=self.colors["warning"], font=("Segoe UI", 9, "bold"))
        self.ai_badge.pack(anchor="e", pady=(0, 5))
        self.ffmpeg_badge = tk.Label(header_actions, text="● FFmpeg · COMPROBANDO",
                                     bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 9, "bold"))
        self.ffmpeg_badge.pack(anchor="e", pady=(0, 7))
        ttk.Button(header_actions, text="Comprobar herramientas", command=self.check_tools).pack(anchor="e", pady=(0, 5))
        ttk.Button(header_actions, text="Diagnóstico de PC", command=self.detect_pc_async).pack(anchor="e")

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        sidebar = tk.Frame(body, bg=self.colors["panel"], width=238, padx=13, pady=14,
                           highlightthickness=1, highlightbackground=self.colors["border"])
        sidebar.pack(side="left", fill="y", padx=(0, 15))
        sidebar.pack_propagate(False)
        tk.Label(sidebar, text="BIBLIOTECA", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(sidebar, text="Tus proyectos y guiones", bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 10))
        self.project_list = tk.Listbox(
            sidebar, width=25, height=20, bg=self.colors["input"], fg=self.colors["text"],
            selectbackground=self.colors["accent"], selectforeground="#ffffff",
            borderwidth=0, highlightthickness=1, highlightbackground=self.colors["border"],
            font=("Segoe UI", 9), activestyle="none"
        )
        self.project_list.pack(fill="both", expand=True, pady=(0, 10))
        self.project_list.bind("<<ListboxSelect>>", self.load_selected)
        ttk.Button(sidebar, text="+ Nuevo proyecto", style="Accent.TButton", command=self.new_project).pack(fill="x")
        self.delete_button = ttk.Button(sidebar, text="Eliminar proyecto", command=self.delete_project)
        self.delete_button.pack(fill="x", pady=(7, 0))
        tk.Label(sidebar, text="LOCAL · PRIVADO · SIN API", bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 8, "bold")).pack(anchor="w", pady=(16, 0))

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)
        form_card = tk.Frame(right, bg=self.colors["panel"], padx=15, pady=13,
                             highlightthickness=1, highlightbackground=self.colors["border"])
        form_card.pack(fill="x")
        tk.Label(form_card, text="CONFIGURA TU HISTORIA", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(anchor="w")
        tk.Label(form_card, text="Define la idea, el género y los personajes. La IA desarrollará el guion por capítulos.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 10))

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

        grid = tk.Frame(form_card, bg=self.colors["panel"])
        grid.pack(fill="x")
        self.form_widgets = []
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="story_cols")
        self._field(grid, "Nombre del proyecto", self.title_var, 0, 0)
        self._field(grid, "Género / tipo de contenido", self.style_var, 0, 1,
                    values=["Novela dramática", "Reencarnación y venganza", "Superación personal",
                            "Romance", "Fantasía", "Misterio y suspenso", "Terror", "Acción y aventura",
                            "Ciencia ficción", "Drama familiar", "Educativo y directo", "Documental", "Promocional"])
        self._field(grid, "Plataforma", self.platform_var, 0, 2, values=list(PLATFORMS))
        self._field(grid, "Idea o premisa de la historia", self.topic_var, 1, 0, span=2)
        self._field(grid, "Duración objetivo (minutos)", self.duration_var, 1, 2,
                    values=[str(i) for i in (1, 3, 5, 10, 15, 20, 30, 45, 60, 90, 120)])
        self._field(grid, "Protagonista (opcional)", self.protagonist_var, 2, 0)
        self._field(grid, "Conflicto central (opcional)", self.conflict_var, 2, 1)
        self._field(grid, "Tono narrativo", self.tone_var, 2, 2,
                    values=["Dramático e intenso", "Oscuro y misterioso", "Emotivo", "Inspirador",
                            "Épico", "Ligero y humorístico", "Realista"])
        self._field(grid, "Tipo de narrador", self.narrator_var, 3, 0,
                    values=["Tercera persona", "Primera persona protagonista", "Primera persona retrospectiva",
                            "Narrador omnisciente"])
        self._field(grid, "Tipo de desenlace", self.ending_var, 3, 1,
                    values=["Justicia y superación", "Final feliz", "Final trágico", "Giro inesperado",
                            "Abierto para continuación", "Agridulce"])
        self._field(grid, "Estilo de dibujo", self.drawing_style_var, 4, 0,
                    values=["Anime cinematográfico", "Manga en blanco y negro", "Cartoon occidental",
                            "Cómic realista", "Acuarela ilustrada", "Pixel art", "3D estilizado", "Realismo cinematográfico"])
        self._field(grid, "Estilo de animación", self.animation_style_var, 4, 1,
                    values=["2D fluida", "Anime con movimientos dinámicos", "Motion comic", "Cut-out / recortes",
                            "3D cinematográfica", "Stop motion", "Pixel animation", "Presentación animada"])
        tk.Label(grid, text="La selección guía la dirección visual.\nLa generación automática de dibujos se incorporará después.",
                 bg=self.colors["panel"], fg=self.colors["muted"], font=("Segoe UI", 8), justify="left").grid(
                     row=4, column=2, sticky="w", padx=8, pady=(10, 4))

        actions = tk.Frame(right, bg=self.colors["bg"])
        actions.pack(fill="x", pady=10)
        self.generate_button = ttk.Button(actions, text="✦ Generar guion con IA", style="Accent.TButton",
                                          command=self.generate_script)
        self.generate_button.pack(side="left")
        self.cancel_button = ttk.Button(actions, text="Cancelar generación", command=self.cancel_generation, state="disabled")
        self.cancel_button.pack(side="left", padx=(8, 0))
        self.save_button = ttk.Button(actions, text="Guardar", command=self.save_project)
        self.save_button.pack(side="left", padx=(8, 0))
        self.approve_button = ttk.Button(actions, text="Aprobar guion", command=self.approve_script)
        self.approve_button.pack(side="left", padx=(8, 0))
        self.export_button = ttk.Button(actions, text="Exportar MP4", command=self.export_video)
        self.export_button.pack(side="left", padx=(8, 0))
        progress_card = tk.Frame(right, bg=self.colors["panel"], padx=11, pady=9,
                                  highlightthickness=1, highlightbackground=self.colors["border"])
        progress_card.pack(fill="x", pady=(0, 8))
        self.pc_summary_var = tk.StringVar(value="Analizando el equipo para estimar tiempos…")
        tk.Label(progress_card, textvariable=self.pc_summary_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 8), justify="left", wraplength=850).pack(anchor="w", pady=(0, 5))
        self.estimate_var = tk.StringVar(value="Estimación disponible tras detectar el equipo.")
        tk.Label(progress_card, textvariable=self.estimate_var, bg=self.colors["panel"],
                 fg=self.colors["success"], font=("Segoe UI", 9, "bold"), justify="left", wraplength=850).pack(anchor="w", pady=(0, 5))
        self.progress_label_var = tk.StringVar(value="Listo para planificar el guion.")
        tk.Label(progress_card, textvariable=self.progress_label_var, bg=self.colors["panel"],
                 fg=self.colors["text"], font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self.progressbar = ttk.Progressbar(progress_card, mode="determinate", maximum=100, value=0)
        self.progressbar.pack(fill="x", pady=(6, 4))
        self.progress_detail_var = tk.StringVar(value="0% · Esperando inicio")
        tk.Label(progress_card, textvariable=self.progress_detail_var, bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 8)).pack(anchor="w")

        editor_card = tk.Frame(right, bg=self.colors["panel"], padx=13, pady=11,
                               highlightthickness=1, highlightbackground=self.colors["border"])
        editor_card.pack(fill="both", expand=True)
        editor_header = tk.Frame(editor_card, bg=self.colors["panel"])
        editor_header.pack(fill="x", pady=(0, 7))
        tk.Label(editor_header, text="EDITOR DE GUION", bg=self.colors["panel"], fg=self.colors["text"],
                 font=("Segoe UI", 11, "bold")).pack(side="left")
        tk.Label(editor_header, text="Edita el texto antes de aprobar", bg=self.colors["panel"],
                 fg=self.colors["muted"], font=("Segoe UI", 9)).pack(side="right")
        self.script_text = tk.Text(
            editor_card, wrap="word", undo=True, bg=self.colors["input"], fg=self.colors["text"],
            insertbackground="#ffffff", selectbackground=self.colors["accent"],
            font=("Segoe UI", 10), relief="flat", padx=13, pady=12,
            highlightthickness=1, highlightbackground=self.colors["border"]
        )
        self.script_text.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="Listo. Completa la premisa y pulsa «Generar guion con IA».")
        tk.Label(right, textvariable=self.status_var, bg=self.colors["bg"], fg=self.colors["muted"],
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(8, 2))
        tk.Label(right, text="La exportación requiere aprobación manual. Modificar un guion aprobado anula su aprobación.",
                 bg=self.colors["bg"], fg=self.colors["muted"], font=("Segoe UI", 8), anchor="w").pack(fill="x")

    def _field(self, parent, label, variable, row, col, values=None, span=1):
        cell = tk.Frame(parent, bg=self.colors["panel"])
        cell.grid(row=row, column=col, columnspan=span, sticky="ew", padx=5, pady=4)
        tk.Label(cell, text=label, bg=self.colors["panel"], fg=self.colors["muted"],
                 font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 4))
        if values is not None:
            widget = ttk.Combobox(cell, textvariable=variable, values=values,
                                  state="readonly", font=("Segoe UI", 9))
        else:
            widget = ttk.Entry(cell, textvariable=variable, font=("Segoe UI", 9))
        widget.pack(fill="x")
        self.form_widgets.append((widget, "readonly" if values is not None else "normal"))
        return widget

    def new_project(self):
        if self.generation_running:
            messagebox.showinfo("Generación en curso", "Espera o cancela la generación actual antes de crear otro proyecto.")
            return
        self.current_id = None
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
            messagebox.showwarning("Duración no válida", "La duración debe estar entre 1 y 120 minutos.")
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
        if self.generation_running:
            messagebox.showinfo("Generación en curso", "Ya hay una generación en proceso.")
            return
        minutes = data["duration"]
        self.estimate_var.set(self._estimate_time(minutes))
        chapter_count = max(1, math.ceil((minutes * 135) / 360))
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
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", project["script"])
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
        if self.current_id is None:
            messagebox.showwarning("Guarda primero", "Guarda el proyecto antes de exportar.")
            return
        self.save_project(quiet=True)
        row = self.conn.execute("SELECT * FROM projects WHERE id=?", (self.current_id,)).fetchone()
        if not row or not row["approved"]:
            messagebox.showerror("Aprobación obligatoria", "No se puede exportar: primero debes aprobar el guion.")
            return
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            selected = filedialog.askopenfilename(
                title="Selecciona ffmpeg.exe",
                filetypes=[("FFmpeg ejecutable", "ffmpeg.exe"), ("Ejecutables", "*.exe")]
            )
            if not selected:
                messagebox.showerror("FFmpeg no encontrado", "No se encontró FFmpeg automáticamente. Selecciona ffmpeg.exe de la carpeta bin.")
                return
            if Path(selected).name.lower() != "ffmpeg.exe":
                messagebox.showerror("Archivo incorrecto", "Selecciona el archivo ffmpeg.exe.")
                return
            ffmpeg = selected
        output = filedialog.asksaveasfilename(title="Guardar video MP4", defaultextension=".mp4",
                                               filetypes=[("Video MP4", "*.mp4")],
                                               initialfile=f"{row['title'][:40]}.mp4")
        if not output:
            return
        width, height = PLATFORMS.get(row["platform"], (1280, 720))
        lines = [
            x.strip() for x in row["script"].splitlines()
            if x.strip()
            and not x.strip().startswith("[")
            and not x.strip().startswith(("TÍTULO:", "ESTILO:", "GÉNERO:", "DURACIÓN", "MODELO:", "GENERADO POR:", "NOTA:", "NOTA DE"))
        ]
        if not lines:
            messagebox.showerror("Guion vacío", "El guion no contiene escenas exportables.")
            return
        # Agrupa párrafos para aproximar la duración elegida sin crear miles de escenas de 5 segundos.
        target_seconds = max(5, int(row["duration_minutes"]) * 60)
        max_scenes = max(1, target_seconds // 5)
        group_size = max(1, math.ceil(len(lines) / max_scenes))
        scene_texts = [" ".join(lines[i:i + group_size]) for i in range(0, len(lines), group_size)]
        seconds = max(5, target_seconds // len(scene_texts))
        scene_dir = PROJECTS_DIR / str(row["id"])
        scene_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.progressbar.configure(maximum=len(scene_texts) + 1, value=0)
            self.progress_label_var.set(f"Renderizando video · {len(scene_texts)} escenas")
            self.progress_detail_var.set("0% · Preparando escenas de texto")
            self.update_idletasks()
            for i, line in enumerate(scene_texts):
                # Texto seguro para filtro drawtext; cada escena es un fondo sencillo.
                wrapped = "\\n".join(textwrap.wrap(line, width=32 if height > width else 48))
                textfile = scene_dir / f"scene_{i:03d}.txt"
                textfile.write_text(wrapped, encoding="utf-8")
                scene_path = scene_dir / f"scene_{i:03d}.mp4"
                cmd = [
                    ffmpeg, "-y", "-f", "lavfi", "-i", f"color=c=0x101b30:s={width}x{height}:d={seconds}:r=24",
                    "-vf", f"drawtext=textfile='{textfile.as_posix()}':fontcolor=white:fontsize={max(22, width//28)}:line_spacing=12:x=(w-text_w)/2:y=(h-text_h)/2:box=1:boxcolor=0x2563eb@0.65:boxborderw=26",
                    "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "ultrafast", "-crf", "28",
                    str(scene_path)
                ]
                subprocess.run(cmd, check=True, capture_output=True, text=True)
                done = i + 1
                percent = round(done / (len(scene_texts) + 1) * 100)
                self.progressbar.configure(value=done)
                self.progress_label_var.set(f"Renderizando video · escena {done} de {len(scene_texts)}")
                self.progress_detail_var.set(f"{percent}% · FFmpeg está procesando las escenas")
                self.update_idletasks()
            concat = scene_dir / "concat.txt"
            concat.write_text("".join(f"file '{(scene_dir / f'scene_{i:03d}.mp4').as_posix()}'\n" for i in range(len(scene_texts))), encoding="utf-8")
            cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", output]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            self.progressbar.configure(value=len(scene_texts) + 1)
            self.progress_label_var.set("Video exportado correctamente")
            self.progress_detail_var.set("100% · Render finalizado")
            self.update_idletasks()
        except (subprocess.CalledProcessError, OSError) as exc:
            detail = (getattr(exc, "stderr", None) or str(exc))[-1800:]
            self.progress_label_var.set("La exportación se detuvo")
            self.progress_detail_var.set("Error · Revisa FFmpeg y el mensaje de diagnóstico")
            messagebox.showerror("Error de exportación", f"FFmpeg no pudo renderizar el video.\n\n{detail}")
            return
        self.status_var.set(f"Video exportado: {output}")
        messagebox.showinfo("Exportación terminada", f"Video MP4 creado en:\n{output}")

if __name__ == "__main__":
    App().mainloop()
