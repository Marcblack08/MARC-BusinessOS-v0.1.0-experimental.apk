"""Minimal three-step video creator and local voice catalog for MARC.

The full editor stays available behind an explicit Advanced Editor action.
This module owns the compact creation flow and does not replace production engines.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
import threading
import urllib.error
import urllib.request
import uuid
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Iterable

STEP_BG = "#0b1220"
CARD_BG = "#111b2d"
INPUT_BG = "#0a1323"
TEXT = "#edf3ff"
MUTED = "#91a0b8"
ACCENT = "#4c8dff"
BORDER = "#26354c"
VOICE_SAMPLE = "Hola. Esta es una muestra de la voz que narrará tu historia."


def normalize_script_for_images(script: str, image_count: int) -> str:
    """Keep explicit scenes when their count matches images; otherwise align story chunks to images."""
    raw = str(script or "").strip().replace("\r\n", "\n").replace("\r", "\n")
    if not raw:
        raise ValueError("Pega el guion antes de continuar.")
    try:
        image_total = int(image_count)
    except (TypeError, ValueError):
        image_total = 0
    if image_total < 1:
        raise ValueError("Añade al menos una imagen para continuar.")
    heading = re.compile(r"(?im)^\s*(?:ESCENA|SCENE)\s+\d+\b.*$")
    existing_headings = list(heading.finditer(raw))
    if existing_headings and len(existing_headings) == image_total:
        return raw
    # If a script already has scene headers but a different number of images, remove
    # only the headers before splitting its actual content into image-aligned shots.
    cleaned = heading.sub("", raw)
    # Ignore common standalone editorial headings but retain dialogue labels and action.
    cleaned_lines = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if stripped and re.match(r"(?i)^(?:CAP[IÍ]TULO|CHAPTER)\s+\d+\b", stripped):
            continue
        cleaned_lines.append(line)
    text = "\n".join(cleaned_lines).strip()
    sentences = [piece.strip() for piece in re.split(r"(?<=[.!?…])\s+|\n{2,}", text) if piece.strip()]
    if not sentences:
        sentences = [text]
    if image_total == 1:
        chunks = [" ".join(sentences)]
    else:
        chunks = []
        for index in range(image_total):
            start = round(index * len(sentences) / image_total)
            end = round((index + 1) * len(sentences) / image_total)
            chunk = " ".join(sentences[start:end]).strip()
            chunks.append(chunk)
        # If there are fewer sentences than images, distribute words so no scene is empty.
        if any(not chunk for chunk in chunks):
            words = text.split()
            chunks = []
            for index in range(image_total):
                start = round(index * len(words) / image_total)
                end = round((index + 1) * len(words) / image_total)
                chunks.append(" ".join(words[start:end]).strip())
    result = []
    for index, chunk in enumerate(chunks, start=1):
        if not chunk:
            chunk = "Continuación visual de la escena anterior."
        result.append(f"ESCENA {index} — Plano {index}\n{chunk}")
    return "\n\n".join(result)


def mode_uses_ai(mode: str) -> bool:
    return str(mode or "").casefold().strip() in {"movimiento ia", "cinemático ia", "cinematico ia"}


def animation_preset(mode: str) -> dict[str, str]:
    """Map a small set of friendly animation choices onto existing editor options."""
    selected = str(mode or "Básico").casefold()
    if "cinem" in selected:
        return {
            "animation_style": "Anime con movimientos dinámicos",
            "animation_intensity": "Muy animado",
            "transition_style": "Zoom cinematográfico",
            "overlay_mode": "Subtítulo narrativo",
        }
    if "movimiento" in selected and "ia" in selected:
        return {
            "animation_style": "2D fluida",
            "animation_intensity": "Muy animado",
            "transition_style": "Fundido suave",
            "overlay_mode": "Título de escena",
        }
    return {
        "animation_style": "2D fluida",
        "animation_intensity": "Normal",
        "transition_style": "Fundido suave",
        "overlay_mode": "Título de escena",
    }


def set_creator_status(app, message: str, percent: int | None = None) -> None:
    """Update the compact wizard progress label safely from any worker thread."""
    def update():
        label = getattr(app, "_creator_status_var", None)
        if label is not None:
            label.set(str(message))
        progress = getattr(app, "_creator_progress", None)
        if progress is not None and percent is not None:
            progress.configure(value=max(0, min(100, int(percent))))
        try:
            app.status_var.set(str(message))
        except Exception:
            pass
    try:
        app.after(0, update)
    except (tk.TclError, RuntimeError):
        pass


def create_creator_wizard(app, on_start: Callable[..., None],
                          on_advanced: Callable[[], None]) -> tk.Frame:
    """Hide the full editor by default and show a 3-step, beginner-friendly creator."""
    shell = None
    for child in app.winfo_children():
        try:
            if child.winfo_manager() == "grid" and child.grid_info().get("row") == "0":
                shell = child
                break
        except tk.TclError:
            continue
    if shell is not None:
        app._marc_full_editor_shell = shell
        shell.grid_remove()
    app.grid_rowconfigure(0, weight=1)
    app.grid_columnconfigure(0, weight=1)
    try:
        app.geometry("1120x760")
        app.minsize(900, 640)
    except tk.TclError:
        pass

    wizard = tk.Frame(app, bg=STEP_BG)
    wizard.grid(row=0, column=0, sticky="nsew")
    wizard.grid_rowconfigure(1, weight=1)
    wizard.grid_columnconfigure(0, weight=1)
    app._creator_wizard = wizard
    app._creator_images: list[str] = []
    app._creator_mode_var = tk.StringVar(value="Básico")
    app._creator_page = 1
    app._creator_status_var = tk.StringVar(value="Todo listo para empezar.")
    app._creator_voice_label_var = tk.StringVar(value="Voz automática · Windows")
    app._creator_progress = None
    app._creator_selected_voice = None

    header = tk.Frame(wizard, bg=STEP_BG, padx=26, pady=15)
    header.grid(row=0, column=0, sticky="ew")
    tk.Label(header, text="MARC", bg=STEP_BG, fg=TEXT,
             font=("Segoe UI", 20, "bold")).pack(side="left")
    tk.Label(header, text=" VIDEO STUDIO", bg=STEP_BG, fg=ACCENT,
             font=("Segoe UI", 16, "bold")).pack(side="left", padx=(7, 0), pady=(4, 0))
    ttk.Button(header, text="Editor avanzado ↗", command=on_advanced).pack(side="right")
    tk.Frame(wizard, bg=BORDER, height=1).grid(row=0, column=0, sticky="sew")

    content = tk.Frame(wizard, bg=STEP_BG, padx=26, pady=14)
    content.grid(row=1, column=0, sticky="nsew")
    content.grid_rowconfigure(1, weight=1)
    content.grid_columnconfigure(0, weight=1)
    app._creator_content = content

    stepbar = tk.Frame(content, bg=STEP_BG)
    stepbar.grid(row=0, column=0, sticky="ew", pady=(0, 12))
    app._creator_step_labels = []
    for i, label in enumerate(("1  Proyecto", "2  Animación y voz", "3  Crear vídeo")):
        item = tk.Label(stepbar, text=label, bg=STEP_BG, fg=MUTED,
                        font=("Segoe UI", 9, "bold"), padx=10, pady=5)
        item.pack(side="left", padx=(0, 8))
        app._creator_step_labels.append(item)

    page = tk.Frame(content, bg=STEP_BG)
    page.grid(row=1, column=0, sticky="nsew")
    page.grid_rowconfigure(0, weight=1)
    page.grid_columnconfigure(0, weight=1)
    app._creator_page_frame = page

    def base_card(parent, padding=20):
        return tk.Frame(parent, bg=CARD_BG, padx=padding, pady=padding,
                        highlightthickness=1, highlightbackground=BORDER)

    def heading(parent, title, subtitle):
        tk.Label(parent, text=title, bg=CARD_BG, fg=TEXT,
                 font=("Segoe UI", 20, "bold")).pack(anchor="w")
        tk.Label(parent, text=subtitle, bg=CARD_BG, fg=MUTED,
                 font=("Segoe UI", 10), wraplength=850, justify="left").pack(
                     anchor="w", pady=(5, 15))

    def update_steps(number):
        app._creator_page = number
        for index, item in enumerate(app._creator_step_labels, start=1):
            item.configure(
                fg=TEXT if index == number else ACCENT if index < number else MUTED,
                bg=CARD_BG if index == number else STEP_BG,
            )

    def show_page(number):
        update_steps(number)
        for child in page.winfo_children():
            child.destroy()
        if number == 1:
            build_project_page()
        elif number == 2:
            build_animation_page()
        else:
            build_progress_page()

    def images_summary():
        count = len(app._creator_images)
        names = [Path(path).name for path in app._creator_images]
        if not names:
            return "Todavía no has añadido imágenes."
        shown = names[:4]
        extra = f"  ·  +{len(names) - len(shown)} más" if len(names) > len(shown) else ""
        return f"{count} imagen(es): " + ", ".join(shown) + extra

    def choose_images():
        chosen = filedialog.askopenfilenames(
            parent=app, title="Selecciona las imágenes en orden narrativo",
            filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos los archivos", "*.*")],
        )
        if chosen:
            seen = {str(Path(p).resolve()).casefold() for p in app._creator_images}
            for item in chosen:
                path = Path(item)
                if path.is_file() and path.suffix.casefold() in {".png", ".jpg", ".jpeg", ".webp", ".bmp"}:
                    resolved = str(path.resolve())
                    if resolved.casefold() not in seen:
                        app._creator_images.append(resolved)
                        seen.add(resolved)
            app._creator_images.sort(key=lambda path: _natural_sort_key(Path(path).name))
            image_count_var.set(images_summary())

    def choose_image_folder():
        folder = filedialog.askdirectory(parent=app, title="Selecciona una carpeta de imágenes")
        if not folder:
            return
        valid = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
        discovered = sorted(
            (p.resolve() for p in Path(folder).rglob("*") if p.is_file() and p.suffix.casefold() in valid),
            key=lambda path: _natural_sort_key(path.name),
        )
        if not discovered:
            messagebox.showwarning("Sin imágenes", "No encontré PNG, JPG, WEBP o BMP en esa carpeta.", parent=app)
            return
        app._creator_images = [str(path) for path in discovered]
        image_count_var.set(images_summary())

    def remove_images():
        app._creator_images = []
        image_count_var.set(images_summary())

    def build_project_page():
        card = base_card(page)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(3, weight=1)
        heading(card, "Crea tu vídeo", "Ponle un nombre, pega el guion y añade las imágenes. MARC se ocupa del resto.")
        tk.Label(card, text="NOMBRE DEL VÍDEO", bg=CARD_BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).grid(row=1, column=0, sticky="w")
        title_entry = ttk.Entry(card, textvariable=app.title_var, font=("Segoe UI", 12))
        title_entry.grid(row=2, column=0, sticky="ew", pady=(5, 12))
        if not app.title_var.get().strip():
            app.title_var.set("")
        script_head = tk.Frame(card, bg=CARD_BG)
        script_head.grid(row=3, column=0, sticky="new")
        script_head.grid_columnconfigure(0, weight=1)
        tk.Label(script_head, text="PEGA TU GUION", bg=CARD_BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(script_head, text="Respeta tus escenas y diálogos; puedes pegar el texto completo.",
                 bg=CARD_BG, fg=MUTED, font=("Segoe UI", 9)).grid(row=1, column=0, sticky="w", pady=(2, 6))
        script_box = tk.Text(
            script_head, height=11, wrap="word", undo=True,
            bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
            relief="flat", borderwidth=0, padx=12, pady=10,
            font=("Segoe UI", 10), highlightthickness=1, highlightbackground=BORDER,
        )
        script_box.grid(row=2, column=0, sticky="nsew")
        script_head.grid_rowconfigure(2, weight=1)
        app._creator_script_box = script_box
        if getattr(app, "_creator_pending_script", ""):
            script_box.insert("1.0", app._creator_pending_script)
        elif getattr(app, "script_text", None):
            existing = app.script_text.get("1.0", "end-1c").strip()
            if existing:
                script_box.insert("1.0", existing)
        images_area = tk.Frame(card, bg=CARD_BG)
        images_area.grid(row=4, column=0, sticky="ew", pady=(12, 0))
        tk.Label(images_area, text="IMÁGENES", bg=CARD_BG, fg=MUTED,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        image_count_var = tk.StringVar(value=images_summary())
        tk.Label(images_area, textvariable=image_count_var, bg=CARD_BG, fg=TEXT,
                 font=("Segoe UI", 9), anchor="w").pack(fill="x", pady=(4, 8))
        image_buttons = tk.Frame(images_area, bg=CARD_BG)
        image_buttons.pack(fill="x")
        ttk.Button(image_buttons, text="＋ Añadir imágenes", command=choose_images).pack(side="left")
        ttk.Button(image_buttons, text="Importar carpeta", command=choose_image_folder).pack(side="left", padx=(7, 0))
        ttk.Button(image_buttons, text="Quitar todas", command=remove_images).pack(side="left", padx=(7, 0))
        footer = tk.Frame(card, bg=CARD_BG)
        footer.grid(row=5, column=0, sticky="ew", pady=(15, 0))
        tk.Label(footer, text="Tu guion e imágenes se procesan en el equipo cuando usas los motores locales.",
                 bg=CARD_BG, fg=MUTED, font=("Segoe UI", 8)).pack(side="left")
        ttk.Button(footer, text="Siguiente  →", style="Accent.TButton",
                   command=lambda: continue_to_animation(script_box)).pack(side="right")
        title_entry.focus_set()

    def continue_to_animation(script_box):
        title = app.title_var.get().strip()
        script = script_box.get("1.0", "end-1c").strip()
        if not title:
            messagebox.showwarning("Falta el nombre", "Escribe el nombre de tu vídeo.", parent=app)
            return
        if not script:
            messagebox.showwarning("Falta el guion", "Pega el guion completo antes de continuar.", parent=app)
            return
        if not app._creator_images:
            messagebox.showwarning("Faltan imágenes", "Añade al menos una imagen para ilustrar el guion.", parent=app)
            return
        app._creator_pending_script = script
        app._creator_script_box = script_box
        show_page(2)

    def build_animation_page():
        card = base_card(page)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        heading(card, "¿Cómo quieres animarlo?", "Elige un estilo. No tienes que configurar cada herramienta.")
        choices = [
            ("Básico", "Movimiento de cámara",
             "Zoom, paneo y transiciones. La opción más ligera; no mueve el cuerpo de los personajes."),
            ("Movimiento IA", "Animación de personajes",
             "Genera movimiento corporal desde cada imagen. Necesita un motor de vídeo y hardware compatible."),
            ("Cinemático IA", "Movimiento + montaje cinematográfico",
             "Animación IA, transiciones más marcadas y una presentación cinematográfica."),
        ]
        modes_area = tk.Frame(card, bg=CARD_BG)
        modes_area.pack(fill="x", pady=(0, 12))
        for value, subtitle, detail in choices:
            row = tk.Frame(modes_area, bg=INPUT_BG, padx=12, pady=9,
                           highlightthickness=1, highlightbackground=BORDER)
            row.pack(fill="x", pady=4)
            row.columnconfigure(1, weight=1)
            tk.Radiobutton(
                row, variable=app._creator_mode_var, value=value, bg=INPUT_BG, fg=TEXT,
                selectcolor=STEP_BG, activebackground=INPUT_BG, activeforeground=TEXT,
                font=("Segoe UI", 10, "bold"), command=refresh_mode_description,
            ).grid(row=0, column=0, rowspan=2, sticky="w", padx=(0, 12))
            tk.Label(row, text=subtitle, bg=INPUT_BG, fg=TEXT,
                     font=("Segoe UI", 10, "bold")).grid(row=0, column=1, sticky="w")
            tk.Label(row, text=detail, bg=INPUT_BG, fg=MUTED,
                     font=("Segoe UI", 9), wraplength=800, justify="left").grid(
                         row=1, column=1, sticky="w", pady=(2, 0))
        app._creator_mode_description = tk.StringVar()
        tk.Label(card, textvariable=app._creator_mode_description, bg=CARD_BG,
                 fg=ACCENT, font=("Segoe UI", 9, "bold"), wraplength=850,
                 justify="left").pack(anchor="w", pady=(0, 12))
        refresh_mode_description()

        tk.Frame(card, bg=BORDER, height=1).pack(fill="x", pady=(0, 12))
        voice_row = tk.Frame(card, bg=CARD_BG)
        voice_row.pack(fill="x")
        voice_text = tk.Frame(voice_row, bg=CARD_BG)
        voice_text.pack(side="left", fill="x", expand=True)
        tk.Label(voice_text, text="VOCES", bg=CARD_BG, fg=TEXT,
                 font=("Segoe UI", 12, "bold")).pack(anchor="w")
        tk.Label(voice_text, text="Escoge una voz instalada o abre el catálogo para añadir más.",
                 bg=CARD_BG, fg=MUTED, font=("Segoe UI", 9)).pack(anchor="w", pady=(3, 2))
        tk.Label(voice_text, textvariable=app._creator_voice_label_var, bg=CARD_BG,
                 fg=ACCENT, font=("Segoe UI", 9, "bold")).pack(anchor="w", pady=(2, 0))
        ttk.Button(voice_row, text="Catálogo de voces", style="Accent.TButton",
                   command=lambda: open_voice_catalog(app)).pack(side="right", padx=(14, 0))
        footer = tk.Frame(card, bg=CARD_BG)
        footer.pack(fill="x", pady=(18, 0))
        ttk.Button(footer, text="← Volver", command=lambda: show_page(1)).pack(side="left")
        ttk.Button(footer, text="Crear vídeo  →", style="Accent.TButton",
                   command=lambda: start_production()).pack(side="right")

    def refresh_mode_description():
        mode = app._creator_mode_var.get()
        descriptions = {
            "Básico": "Rápido y compatible con más equipos: movimiento 2D de cámara, fundidos y montaje.",
            "Movimiento IA": "Anima realmente personajes/objetos si hay un motor local compatible.",
            "Cinemático IA": "Anima con IA y aplica un acabado de montaje más cinematográfico.",
        }
        if hasattr(app, "_creator_mode_description"):
            app._creator_mode_description.set(descriptions.get(mode, descriptions["Básico"]))

    def start_production():
        title = app.title_var.get().strip()
        script = normalize_script_for_images(
            getattr(app, "_creator_pending_script", ""), len(app._creator_images)
        )
        if not title:
            show_page(1)
            return
        show_page(3)
        set_creator_status(app, "Preparando tu producción…", 5)
        on_start(
            title=title,
            script=script,
            image_paths=list(app._creator_images),
            mode=app._creator_mode_var.get(),
        )

    def build_progress_page():
        card = base_card(page, padding=30)
        card.grid(row=0, column=0, sticky="nsew")
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(2, weight=1)
        tk.Label(card, text="MARC está creando tu vídeo", bg=CARD_BG, fg=TEXT,
                 font=("Segoe UI", 22, "bold")).grid(row=0, column=0, sticky="w")
        tk.Label(card, text="El proceso prepara el motor, anima las imágenes, genera la narración y monta el MP4.",
                 bg=CARD_BG, fg=MUTED, font=("Segoe UI", 10), wraplength=850,
                 justify="left").grid(row=1, column=0, sticky="w", pady=(6, 20))
        app._creator_progress = ttk.Progressbar(card, mode="determinate", maximum=100, value=5)
        app._creator_progress.grid(row=2, column=0, sticky="new", pady=(0, 10))
        tk.Label(card, textvariable=app._creator_status_var, bg=CARD_BG, fg=ACCENT,
                 font=("Segoe UI", 10, "bold"), wraplength=850, justify="left").grid(
                     row=3, column=0, sticky="w", pady=(0, 14))
        tk.Label(card, text="Puedes seguir trabajando en el editor avanzado. El progreso y los archivos se conservan en este proyecto.",
                 bg=CARD_BG, fg=MUTED, font=("Segoe UI", 9), wraplength=850,
                 justify="left").grid(row=4, column=0, sticky="w")
        actions = tk.Frame(card, bg=CARD_BG)
        actions.grid(row=5, column=0, sticky="ew", pady=(22, 0))
        ttk.Button(actions, text="Editor avanzado ↗", command=on_advanced).pack(side="left")
        ttk.Button(actions, text="Crear otro vídeo", command=new_video).pack(side="right")

    def new_video():
        app._creator_images = []
        app._creator_pending_script = ""
        app.title_var.set("")
        app.topic_var.set("")
        show_page(1)

    # Save callbacks on the app instance for progress/automation helpers.
    app._creator_show_page = show_page
    app._creator_refresh_voice_label = refresh_voice_label
    app._creator_new_video = new_video
    show_page(1)
    return wizard


def _natural_sort_key(name: str):
    return tuple(
        (0, int(part)) if part.isdigit() else (1, part.casefold())
        for part in re.split(r"(\d+)", str(name))
    )


def refresh_voice_label(app):
    engine = str(app.voice_engine_var.get() if hasattr(app, "voice_engine_var") else "Windows").casefold()
    voice = str(app.voice_var.get() if hasattr(app, "voice_var") else "(Automática)").strip()
    engine_name = "Kokoro neuronal" if engine.startswith("kokoro") else "Windows"
    shown = "Automática" if not voice or voice == "(Automática)" else voice
    variable = getattr(app, "_creator_voice_label_var", None)
    if variable is not None:
        variable.set(f"{shown} · {engine_name}")


def open_voice_catalog(app):
    """Show installed Windows/Kokoro voices, with preview and install links."""
    dialog = tk.Toplevel(app)
    dialog.title("Catálogo de voces · MARC")
    dialog.configure(bg=STEP_BG)
    dialog.transient(app)
    dialog.geometry("680x570")
    dialog.minsize(590, 460)
    body = tk.Frame(dialog, bg=STEP_BG, padx=20, pady=18)
    body.pack(fill="both", expand=True)
    tk.Label(body, text="Catálogo de voces", bg=STEP_BG, fg=TEXT,
             font=("Segoe UI", 18, "bold")).pack(anchor="w")
    tk.Label(body, text="Selecciona una voz instalada, escúchala y añádela a tu vídeo. Las voces nuevas se instalan en Windows o mediante Kokoro local.",
             bg=STEP_BG, fg=MUTED, font=("Segoe UI", 9), wraplength=620,
             justify="left").pack(anchor="w", pady=(5, 12))

    tree = ttk.Treeview(body, columns=("engine", "voice"), show="headings", height=13, selectmode="browse")
    tree.heading("engine", text="MOTOR")
    tree.heading("voice", text="VOZ DISPONIBLE")
    tree.column("engine", width=155, anchor="w")
    tree.column("voice", width=430, anchor="w")
    tree.pack(fill="both", expand=True)
    status = tk.StringVar(value="Buscando voces instaladas…")
    tk.Label(body, textvariable=status, bg=STEP_BG, fg=ACCENT, font=("Segoe UI", 9),
             anchor="w", wraplength=620, justify="left").pack(fill="x", pady=(8, 6))

    voices: list[tuple[str, str]] = []
    selected_voice = {"engine": "", "name": ""}

    def fill_catalog(items: Iterable[tuple[str, str]], message: str):
        voices.clear()
        voices.extend(items)
        tree.delete(*tree.get_children())
        for engine, name in voices:
            tree.insert("", "end", iid=f"{engine}:{name}", values=(engine, name))
        status.set(message)
        current_engine = "Kokoro" if str(app.voice_engine_var.get()).startswith("Kokoro") else "Windows"
        current_voice = str(app.voice_var.get() or "")
        current_id = f"{current_engine}:{current_voice}"
        if current_id in tree.get_children(""):
            tree.selection_set(current_id)

    def refresh():
        status.set("Buscando voces locales…")
        tree.delete(*tree.get_children())
        def worker():
            found: list[tuple[str, str]] = []
            error_notes = []
            if os.name == "nt":
                powershell = __import__("shutil").which("powershell.exe") or __import__("shutil").which("powershell")
                if powershell:
                    ps = (
                        "$ErrorActionPreference='Stop'; Add-Type -AssemblyName System.Speech; "
                        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        "$s.GetInstalledVoices() | ForEach-Object { $_.VoiceInfo.Name }; $s.Dispose()"
                    )
                    try:
                        result = subprocess.run(
                            [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                            capture_output=True, text=True, timeout=25,
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                        )
                        if result.returncode == 0:
                            found.extend(("Windows", line.strip()) for line in result.stdout.splitlines() if line.strip())
                        else:
                            error_notes.append("Windows no devolvió la lista de voces.")
                    except Exception:
                        error_notes.append("No se pudo consultar el catálogo de voces de Windows.")
            try:
                req = urllib.request.Request(
                    "http://127.0.0.1:7860/tts/voices", headers={"Accept": "application/json"}
                )
                with urllib.request.urlopen(req, timeout=3.0) as response:
                    payload = json.loads(response.read().decode("utf-8"))
                from voice_engine import parse_kokoro_voice_ids
                kokoro = parse_kokoro_voice_ids(payload)
                spanish = [v for v in kokoro if v.casefold().startswith(("ef_", "em_", "es_"))]
                if spanish:
                    kokoro = spanish
                found.extend(("Kokoro", voice) for voice in kokoro)
            except Exception:
                pass
            found = list(dict.fromkeys(found))
            message = (
                f"{len(found)} voz(es) disponible(s)."
                if found else
                "No se encontraron voces. Instala una voz de Windows o configura Kokoro y pulsa Actualizar."
            )
            if error_notes:
                message += " " + " ".join(error_notes)
            try:
                dialog.after(0, lambda rows=found, msg=message: fill_catalog(rows, msg))
            except (tk.TclError, RuntimeError):
                pass
        threading.Thread(target=worker, daemon=True, name="MARC-Voice-Catalog").start()

    def choose_current() -> tuple[str, str] | None:
        selection = tree.selection()
        if not selection:
            return None
        item = tree.item(selection[0], "values")
        return str(item[0]), str(item[1])

    def use_voice():
        pair = choose_current()
        if pair is None:
            messagebox.showinfo("Selecciona una voz", "Elige una voz de la lista.", parent=dialog)
            return
        engine, name = pair
        if engine == "Kokoro":
            app.voice_engine_var.set("Kokoro (neuronal local)")
            app.kokoro_voice_names = [voice for eng, voice in voices if eng == "Kokoro"]
            app.voice_var.set(name)
            try:
                app.voice_combo.configure(values=app.kokoro_voice_names)
            except (tk.TclError, AttributeError):
                pass
            try:
                app.voice_status_var.set(f"Voz Kokoro seleccionada: {name}")
            except Exception:
                pass
        else:
            app.voice_engine_var.set("Windows (básica)")
            app.available_voice_names = [voice for eng, voice in voices if eng == "Windows"]
            app.voice_var.set(name)
            try:
                app.voice_combo.configure(values=["(Automática)"] + app.available_voice_names)
            except (tk.TclError, AttributeError):
                pass
            try:
                app.voice_status_var.set(f"Voz de Windows seleccionada: {name}")
            except Exception:
                pass
        try:
            app.on_voice_engine_changed()
        except Exception:
            pass
        refresh_voice_label(app)
        dialog.destroy()

    def preview_voice():
        pair = choose_current()
        if pair is None:
            messagebox.showinfo("Selecciona una voz", "Elige una voz de la lista para escuchar una muestra.", parent=dialog)
            return
        engine, name = pair
        status.set(f"Preparando muestra: {name}…")
        def worker():
            try:
                if engine == "Windows":
                    powershell = __import__("shutil").which("powershell.exe") or __import__("shutil").which("powershell")
                    if not powershell:
                        raise RuntimeError("PowerShell no está disponible.")
                    ps = (
                        "Add-Type -AssemblyName System.Speech; "
                        "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
                        "$voice=$env:MARC_PREVIEW_VOICE; "
                        "try { $s.SelectVoice($voice) } catch { throw 'Voz no disponible: ' + $voice }; "
                        "$s.Speak($env:MARC_PREVIEW_TEXT); $s.Dispose()"
                    )
                    env = os.environ.copy()
                    env["MARC_PREVIEW_VOICE"] = name
                    env["MARC_PREVIEW_TEXT"] = VOICE_SAMPLE
                    result = subprocess.run(
                        [powershell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                        capture_output=True, text=True, timeout=45, env=env,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    if result.returncode != 0:
                        raise RuntimeError((result.stderr or result.stdout or "No se pudo reproducir la muestra.").strip()[-500:])
                else:
                    payload = json.dumps({
                        "input_type": "text", "text": VOICE_SAMPLE, "voice": name,
                        "output_format": "wav",
                    }).encode("utf-8")
                    request = urllib.request.Request(
                        "http://127.0.0.1:7860/tts/generate", data=payload,
                        headers={"Content-Type": "application/json", "Accept": "audio/wav"}, method="POST",
                    )
                    with urllib.request.urlopen(request, timeout=90) as response:
                        audio = response.read()
                    if len(audio) < 44 or not audio.startswith(b"RIFF"):
                        raise RuntimeError("Kokoro no devolvió un WAV válido para la muestra.")
                    path = Path(tempfile.gettempdir()) / f"marc_voice_preview_{uuid.uuid4().hex}.wav"
                    path.write_bytes(audio)
                    if os.name == "nt":
                        os.startfile(str(path))
                    else:
                        import webbrowser
                        webbrowser.open(path.as_uri())
                try:
                    dialog.after(0, lambda: status.set(f"Muestra reproducida: {name}"))
                except (tk.TclError, RuntimeError):
                    pass
            except Exception as exc:
                try:
                    dialog.after(0, lambda text=str(exc): status.set(f"No se pudo reproducir: {text[:180]}"))
                except (tk.TclError, RuntimeError):
                    pass
        threading.Thread(target=worker, daemon=True, name="MARC-Voice-Preview").start()

    def install_windows():
        if os.name == "nt":
            try:
                os.startfile("ms-settings:speech")
                status.set("En Windows, agrega una voz compatible. Al volver, pulsa Actualizar.")
            except (OSError, AttributeError):
                status.set("Abre Configuración → Hora e idioma → Voz para instalar voces.")
        else:
            messagebox.showinfo("Voces de Windows", "La instalación de voces SAPI solo está disponible en Windows.", parent=dialog)

    def install_kokoro():
        try:
            app.voice_engine_var.set("Kokoro (neuronal local)")
            app.configure_voice_engine()
            status.set("Sigue los pasos de Kokoro. Cuando el servidor esté activo, pulsa Actualizar.")
        except Exception as exc:
            messagebox.showerror("Kokoro", str(exc), parent=dialog)

    actions = tk.Frame(body, bg=STEP_BG)
    actions.pack(fill="x", pady=(10, 0))
    ttk.Button(actions, text="Actualizar", command=refresh).pack(side="left")
    ttk.Button(actions, text="Escuchar muestra", command=preview_voice).pack(side="left", padx=(6, 0))
    ttk.Button(actions, text="Instalar voces Windows", command=install_windows).pack(side="left", padx=(6, 0))
    ttk.Button(actions, text="Voces IA Kokoro", command=install_kokoro).pack(side="left", padx=(6, 0))
    ttk.Button(actions, text="Usar voz", style="Accent.TButton", command=use_voice).pack(side="right")
    ttk.Button(actions, text="Cerrar", command=dialog.destroy).pack(side="right", padx=(0, 6))
    refresh()
    return dialog
