from __future__ import annotations

import json
import shutil
import sqlite3
import subprocess
import textwrap
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
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    return conn

def draft_script(title: str, topic: str, minutes: int, style: str) -> str:
    # Generador local determinista para el MVP. No usa red ni API.
    sections = [
        ("GANCHO", f"¿Sabías esto sobre {topic}? En este video vamos a descubrirlo de forma clara y práctica."),
        ("INTRODUCCIÓN", f"Bienvenido. Hoy hablaremos de {topic}. La idea es explicar lo esencial y dejarte recomendaciones que puedas aplicar."),
        ("PUNTO 1", f"Primero, entiende el contexto de {topic}. Antes de tomar decisiones, identifica el objetivo, los recursos disponibles y los errores más comunes."),
        ("PUNTO 2", f"Segundo, ve paso a paso. Divide {topic} en acciones pequeñas, comprueba cada resultado y evita dar por hecho información que todavía no has verificado."),
        ("PUNTO 3", f"Tercero, revisa la calidad. Compara alternativas, verifica los datos importantes y adapta las recomendaciones a tu situación."),
        ("RESUMEN", f"En resumen: comprende el objetivo de {topic}, avanza por etapas y valida el resultado antes de darlo por terminado."),
        ("CIERRE", "Si este contenido te resultó útil, comenta qué tema te gustaría ver después y comparte el video con quien pueda necesitarlo.")
    ]
    lines = [f"TÍTULO: {title}", f"ESTILO: {style}", f"DURACIÓN OBJETIVO: {minutes} minuto(s)", ""]
    for heading, body in sections:
        lines.extend([f"[{heading}]", body, ""])
    lines.append("NOTA DE PRODUCCIÓN: Este guion es un borrador generado mediante plantillas locales. Revisa hechos, cifras, derechos de autor y adecuación al público antes de aprobarlo.")
    return "\n".join(lines)

def escape_drawtext(value: str) -> str:
    return value.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%").replace(",", "\\,")

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_NAME)
        self.geometry("1050x760")
        self.minsize(850, 620)
        self.configure(bg="#0b1220")
        self.conn = db_connect()
        self.current_id = None
        self._style()
        self._build()
        self.refresh_projects()

    def _style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TFrame", background="#0b1220")
        style.configure("TLabel", background="#0b1220", foreground="#e5edf8", font=("Segoe UI", 10))
        style.configure("Title.TLabel", font=("Segoe UI", 19, "bold"), foreground="#60a5fa")
        style.configure("TButton", padding=7)
        style.configure("TEntry", padding=5)
        style.configure("TCombobox", padding=5)

    def _build(self):
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_NAME, style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Producción local · Sin claves API · Aprobación humana obligatoria").pack(anchor="w", pady=(2, 12))

        body = ttk.Frame(outer)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body, padding=(0, 0, 14, 0))
        left.pack(side="left", fill="y")
        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True)

        ttk.Label(left, text="PROYECTOS").pack(anchor="w")
        self.project_list = tk.Listbox(left, width=30, height=25, bg="#111c2f", fg="#e5edf8",
                                       selectbackground="#2563eb", borderwidth=0, highlightthickness=0)
        self.project_list.pack(fill="y", expand=True, pady=(6, 8))
        self.project_list.bind("<<ListboxSelect>>", self.load_selected)
        ttk.Button(left, text="Nuevo proyecto", command=self.new_project).pack(fill="x")
        ttk.Button(left, text="Eliminar proyecto", command=self.delete_project).pack(fill="x", pady=(5, 0))

        form = ttk.Frame(right)
        form.pack(fill="x")
        self.title_var = tk.StringVar()
        self.topic_var = tk.StringVar()
        self.platform_var = tk.StringVar(value=list(PLATFORMS)[0])
        self.duration_var = tk.StringVar(value="3")
        self.style_var = tk.StringVar(value="Educativo y directo")

        self._field(form, "Nombre del proyecto", self.title_var, 0)
        self._field(form, "Tema del video", self.topic_var, 1)
        ttk.Label(form, text="Plataforma / formato").grid(row=2, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.platform_var, values=list(PLATFORMS), state="readonly").grid(row=2, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="Duración objetivo (minutos, máx. 10)").grid(row=3, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.duration_var, values=[str(i) for i in range(1, 11)], state="readonly").grid(row=3, column=1, sticky="ew", pady=4)
        ttk.Label(form, text="Estilo").grid(row=4, column=0, sticky="w", pady=4)
        ttk.Combobox(form, textvariable=self.style_var, values=["Educativo y directo", "Narrativo", "Promocional", "Documental", "Motivacional"], state="readonly").grid(row=4, column=1, sticky="ew", pady=4)
        form.columnconfigure(1, weight=1)

        controls = ttk.Frame(right)
        controls.pack(fill="x", pady=8)
        ttk.Button(controls, text="Generar borrador", command=self.generate_script).pack(side="left")
        ttk.Button(controls, text="Guardar cambios", command=self.save_project).pack(side="left", padx=6)
        ttk.Button(controls, text="Aprobar guion", command=self.approve_script).pack(side="left")
        ttk.Button(controls, text="Exportar MP4", command=self.export_video).pack(side="left", padx=6)

        ttk.Label(right, text="EDITOR DEL GUION").pack(anchor="w", pady=(4, 4))
        self.script_text = tk.Text(right, wrap="word", undo=True, bg="#111c2f", fg="#e5edf8",
                                   insertbackground="white", selectbackground="#1d4ed8",
                                   font=("Consolas", 10), relief="flat", padx=10, pady=10)
        self.script_text.pack(fill="both", expand=True)
        self.status_var = tk.StringVar(value="Crea un proyecto para comenzar.")
        ttk.Label(right, textvariable=self.status_var).pack(anchor="w", pady=(8, 0))
        ttk.Label(right, text="La exportación está bloqueada hasta que apruebes el guion. No se publica automáticamente.").pack(anchor="w", pady=(3, 0))

    def _field(self, parent, label, variable, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        ttk.Entry(parent, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=4)

    def new_project(self):
        self.current_id = None
        self.title_var.set("")
        self.topic_var.set("")
        self.platform_var.set(list(PLATFORMS)[0])
        self.duration_var.set("3")
        self.style_var.set("Educativo y directo")
        self.script_text.delete("1.0", "end")
        self.status_var.set("Proyecto nuevo sin guardar. Completa el nombre y el tema.")

    def get_form(self):
        title = self.title_var.get().strip()
        topic = self.topic_var.get().strip()
        try:
            duration = int(self.duration_var.get())
        except ValueError:
            duration = 0
        if not title or not topic:
            messagebox.showwarning("Faltan datos", "Completa el nombre del proyecto y el tema.")
            return None
        if duration < 1 or duration > 10:
            messagebox.showwarning("Duración no válida", "La duración debe estar entre 1 y 10 minutos.")
            return None
        return title, topic, self.platform_var.get(), duration, self.style_var.get()

    def generate_script(self):
        data = self.get_form()
        if not data:
            return
        title, topic, _, minutes, style = data
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", draft_script(title, topic, minutes, style))
        self.status_var.set("Borrador generado localmente. Revísalo y guárdalo; aún no está aprobado.")
        self.save_project(reset_approval=True, quiet=True)

    def save_project(self, reset_approval=False, quiet=False):
        data = self.get_form()
        if not data:
            return
        title, topic, platform, duration, style = data
        script = self.script_text.get("1.0", "end-1c")
        approved = 0 if reset_approval else self._existing_approval()
        now = datetime.now().isoformat(timespec="seconds")
        if self.current_id is None:
            cur = self.conn.execute(
                "INSERT INTO projects(title,topic,platform,duration_minutes,style,script,approved,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (title, topic, platform, duration, style, script, approved, now))
            self.current_id = cur.lastrowid
        else:
            self.conn.execute(
                "UPDATE projects SET title=?,topic=?,platform=?,duration_minutes=?,style=?,script=?,approved=?,created_at=? WHERE id=?",
                (title, topic, platform, duration, style, script, approved, now, self.current_id))
        self.conn.commit()
        self.refresh_projects()
        if not quiet:
            self.status_var.set("Proyecto guardado. " + ("Guion aprobado." if approved else "Guion pendiente de aprobación."))

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
        self.status_var.set("Guion aprobado por el usuario. Ya puedes exportar el MP4.")

    def refresh_projects(self):
        rows = self.conn.execute("SELECT id,title,approved FROM projects ORDER BY id DESC").fetchall()
        self.project_rows = rows
        self.project_list.delete(0, "end")
        for row in rows:
            mark = "✓" if row["approved"] else "•"
            self.project_list.insert("end", f"{mark} {row['title']}  [#{row['id']}]")

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
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", project["script"])
        self.status_var.set("Guion aprobado." if project["approved"] else "Guion pendiente de aprobación.")

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
        ffmpeg = shutil.which("ffmpeg")
        if not ffmpeg:
            messagebox.showerror("FFmpeg no encontrado", "Instala FFmpeg y añádelo al PATH. Después reinicia la aplicación.")
            return
        output = filedialog.asksaveasfilename(title="Guardar video MP4", defaultextension=".mp4",
                                               filetypes=[("Video MP4", "*.mp4")],
                                               initialfile=f"{row['title'][:40]}.mp4")
        if not output:
            return
        width, height = PLATFORMS.get(row["platform"], (1280, 720))
        lines = [x.strip() for x in row["script"].splitlines() if x.strip() and not x.startswith("[") and not x.startswith("TÍTULO:") and not x.startswith("ESTILO:") and not x.startswith("DURACIÓN") and not x.startswith("NOTA DE PRODUCCIÓN")]
        if not lines:
            messagebox.showerror("Guion vacío", "El guion no contiene escenas exportables.")
            return
        scene_dir = PROJECTS_DIR / str(row["id"])
        scene_dir.mkdir(parents=True, exist_ok=True)
        seconds = max(5, int(row["duration_minutes"]) * 60 // len(lines))
        try:
            for i, line in enumerate(lines):
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
            concat = scene_dir / "concat.txt"
            concat.write_text("".join(f"file '{(scene_dir / f'scene_{i:03d}.mp4').as_posix()}'\n" for i in range(len(lines))), encoding="utf-8")
            cmd = [ffmpeg, "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", output]
            subprocess.run(cmd, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or str(exc))[-1800:]
            messagebox.showerror("Error de exportación", f"FFmpeg no pudo renderizar el video.\n\n{detail}")
            return
        self.status_var.set(f"Video exportado: {output}")
        messagebox.showinfo("Exportación terminada", f"Video MP4 creado en:\n{output}")

if __name__ == "__main__":
    App().mainloop()
