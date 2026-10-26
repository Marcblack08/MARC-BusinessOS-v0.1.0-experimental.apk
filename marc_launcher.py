"""M.A.R.C. desktop launcher with optional real image-to-video integration.

The regular editor stays intact. This launcher adds a focused image-to-video
action to the Scenes toolbar and delegates inference to a user-configured
ComfyUI API workflow; it does not download large models automatically.
"""
from __future__ import annotations

import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

import app as marc_app
from video_generation_engine import (
    VideoGenerationError,
    analyze_image_with_ollama,
    generate_video,
)

_original_build = marc_app.App._build


def _find_button_parent(widget: tk.Misc, caption: str):
    for child in widget.winfo_children():
        if isinstance(child, (ttk.Button, tk.Button)):
            try:
                if child.cget("text") == caption:
                    return child.master
            except tk.TclError:
                pass
        found = _find_button_parent(child, caption)
        if found is not None:
            return found
    return None


def _motion_prompt_dialog(self, image_path: str):
    """Return (prompt, is_auto), or (None, False) when cancelled."""
    prompt = simpledialog.askstring(
        "Animación real con IA",
        "Escribe AUTO para analizar la imagen con un modelo visual local, "
        "o describe el movimiento que quieres (caminar, girar, correr, etc.):",
        initialvalue="AUTO",
        parent=self,
    )
    if prompt is None or not prompt.strip():
        return None, False
    if prompt.strip().casefold() in {"auto", "automático", "automatico"}:
        return "", True
    return prompt.strip(), False


def _open_video_generation(self):
    if any(bool(getattr(self, name, False)) for name in (
        "generation_running", "render_running", "image_generation_running", "voice_generation_running"
    )):
        messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.", parent=self)
        return

    image_path = filedialog.askopenfilename(
        parent=self, title="Selecciona la imagen que quieres animar",
        filetypes=[("Imágenes", "*.png *.jpg *.jpeg *.webp *.bmp"), ("Todos los archivos", "*.*")],
    )
    if not image_path:
        return
    settings_path = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "MARC Video Studio AI Desktop" / "video_generation_settings.json"
    saved_workflow = ""
    try:
        saved_workflow = str(json.loads(settings_path.read_text(encoding="utf-8")).get("workflow_path", ""))
    except (OSError, ValueError, AttributeError):
        pass
    workflow_path = ""
    if saved_workflow and Path(saved_workflow).is_file():
        if messagebox.askyesno(
            "Workflow guardado",
            "¿Usar el workflow de imagen a vídeo que configuraste anteriormente?\n\n"
            f"{saved_workflow}\n\nPulsa No para elegir otro.",
            parent=self,
        ):
            workflow_path = saved_workflow
    if not workflow_path:
        workflow_path = filedialog.askopenfilename(
            parent=self, title="Selecciona el workflow API de imagen a vídeo de ComfyUI",
            initialdir=str(Path(saved_workflow).parent) if saved_workflow else None,
            filetypes=[("Workflow API JSON", "*.json"), ("JSON", "*.json")],
        )
    if not workflow_path:
        return
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps({"workflow_path": workflow_path}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass
    motion_prompt, use_auto_analysis = _motion_prompt_dialog(self, image_path)
    if motion_prompt is None and not use_auto_analysis:
        return
    negative_prompt = simpledialog.askstring(
        "Evitar en la animación",
        "Indicación negativa opcional (déjala vacía si no la necesitas):",
        parent=self,
    )
    output_root = Path(getattr(marc_app, "PROJECTS_DIR", Path.home())) / str(
        getattr(self, "current_id", None) or "importacion"
    ) / "generated_video"
    base_url = str(getattr(self, "comfy_url", "http://127.0.0.1:8188"))
    ollama_url = "http://127.0.0.1:11434"
    button = getattr(self, "animate_image_button", None)
    if button is not None:
        button.configure(state="disabled")
    self.status_var.set("Preparando generación de vídeo IA…")

    def set_status(text: str):
        try:
            self.after(0, lambda message=text: self.status_var.set(message))
        except (tk.TclError, RuntimeError):
            pass

    def worker():
        try:
            prompt = motion_prompt
            if use_auto_analysis:
                set_status("Analizando la imagen con un modelo visual local…")
                prompt = analyze_image_with_ollama(image_path, base_url=ollama_url)
            destination = generate_video(
                image_path=image_path,
                motion_prompt=prompt,
                workflow_path=workflow_path,
                output_dir=output_root,
                base_url=base_url,
                negative_prompt=(negative_prompt or "").strip(),
                progress=set_status,
            )
            self.after(0, lambda path=str(destination): _video_generation_success(self, path))
        except Exception as exc:
            message = str(exc)
            try:
                self.after(0, lambda details=message: _video_generation_error(self, details))
            except (tk.TclError, RuntimeError):
                pass

    threading.Thread(target=worker, daemon=True, name="MARC-ImageToVideo").start()


def _video_generation_success(self, path: str):
    button = getattr(self, "animate_image_button", None)
    if button is not None:
        button.configure(state="normal")
    self.status_var.set("Vídeo generado: " + path)
    messagebox.showinfo(
        "Animación generada",
        "M.A.R.C. recibió un archivo de vídeo del motor de IA. Revisa el resultado antes de publicarlo.\n\n"
        f"Archivo guardado en:\n{path}\n\n"
        "Esta primera integración guarda el clip generado; la sincronización automática con el montaje "
        "se añadirá en una siguiente etapa.",
        parent=self,
    )


def _video_generation_error(self, message: str):
    button = getattr(self, "animate_image_button", None)
    if button is not None:
        button.configure(state="normal")
    self.status_var.set("No se pudo completar la animación IA.")
    messagebox.showerror("Generación de vídeo IA", message, parent=self)


def _build_with_video_button(self):
    _original_build(self)
    parent = _find_button_parent(self.scenes_tab, "Añadir imagen propia")
    if parent is None:
        # Fail visibly in logs without making the whole editor unusable.
        print("MARC I2V: no se encontró la barra de herramientas de Escenas.")
        return
    self.animate_image_button = ttk.Button(
        parent, text="Animar imagen a vídeo IA", command=lambda: _open_video_generation(self)
    )
    self.animate_image_button.pack(side="left", padx=(6, 0))


marc_app.App._build = _build_with_video_button


if __name__ == "__main__":
    marc_app.App().mainloop()
