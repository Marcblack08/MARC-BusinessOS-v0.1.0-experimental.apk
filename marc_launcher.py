"""MARC desktop launcher: automatic setup and one-flow image-to-video production."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

import app as marc_app
import setup_engine
from production_package import discover_production_package, parse_scene_directions
from video_generation_engine import (
    VideoGenerationError,
    analyze_image_with_ollama,
    generate_video,
)

_original_build = marc_app.App._build
_original_init = marc_app.App.__init__


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


def _set_status(self, message: str):
    try:
        self.after(0, lambda text=message: self.status_var.set(text))
    except (tk.TclError, RuntimeError, AttributeError):
        pass


def _setup_summary(report: dict) -> str:
    hw = report.get("hardware", {})
    ffmpeg = report.get("ffmpeg", {})
    ollama = report.get("ollama", {})
    comfy = report.get("comfyui", {})
    status = "LISTO" if report.get("video_generation_ready") else "NO DISPONIBLE EN ESTE EQUIPO"
    lines = [
        f"CPU: {hw.get('cpu', 'No detectada')}",
        f"RAM: {hw.get('ram_gb', '?')} GB",
        f"GPU: {hw.get('gpu_name', 'No detectada')} ({hw.get('gpu_vram_gb', 0)} GB VRAM)",
        f"Espacio libre: {hw.get('free_disk_gb', '?')} GB",
        f"FFmpeg: {'disponible' if ffmpeg.get('available') else 'no disponible'}",
        f"Ollama: {'disponible' if ollama.get('api_available') else 'no disponible'}",
        f"Modelo visual: {'listo' if ollama.get('vision_model_ready') else 'no disponible'}",
        f"ComfyUI: {'conectado' if comfy.get('available') else 'no conectado'}",
        f"Movimiento corporal por IA: {status}",
    ]
    notes = report.get("notes") or hw.get("notes") or []
    if notes:
        lines.extend(["", "Observaciones:"] + [f"• {note}" for note in notes[:4]])
    return "\n".join(lines)


def _setup_finished(self, report: dict, show_dialog: bool, continuation=None):
    self._setup_running = False
    for button_name in ("prepare_ai_button", "full_production_button"):
        button = getattr(self, button_name, None)
        if button is not None:
            try:
                button.configure(state="normal")
            except tk.TclError:
                pass
    self._setup_report = report
    summary = _setup_summary(report)
    self.status_var.set(
        "Preparación de IA terminada: " +
        ("vídeo IA listo." if report.get("video_generation_ready") else "revisa el diagnóstico.")
    )
    if show_dialog:
        if report.get("video_generation_ready"):
            messagebox.showinfo("Diagnóstico y preparación de IA", summary, parent=self)
        else:
            messagebox.showwarning("Diagnóstico y preparación de IA", summary, parent=self)
    if continuation:
        continuation(report)


def _run_setup(self, show_dialog: bool = True, continuation=None):
    if getattr(self, "_setup_running", False):
        if continuation:
            messagebox.showinfo("Preparación en curso", "M.A.R.C. ya está comprobando e instalando los componentes que faltan.", parent=self)
        return
    self._setup_running = True
    for button_name in ("prepare_ai_button", "full_production_button"):
        button = getattr(self, button_name, None)
        if button is not None:
            try:
                button.configure(state="disabled")
            except tk.TclError:
                pass
    self.status_var.set("Analizando hardware e instalando las dependencias que falten…")

    def progress(message: str):
        _set_status(self, "Preparación IA · " + message)

    def worker():
        try:
            report = setup_engine.run_automatic_setup(callback=progress, install_video_models=True)
        except Exception as exc:
            report = {
                "hardware": setup_engine.detect_hardware(),
                "ffmpeg": {"available": bool(setup_engine.find_ffmpeg()), "path": setup_engine.find_ffmpeg() or ""},
                "ollama": {"api_available": False, "vision_model_ready": False},
                "comfyui": {"available": False},
                "video_generation_ready": False,
                "notes": [f"El asistente de instalación no terminó correctamente: {exc}"],
            }
        try:
            self.after(0, lambda result=report: _setup_finished(self, result, show_dialog, continuation))
        except (tk.TclError, RuntimeError):
            pass

    threading.Thread(target=worker, daemon=True, name="MARC-AI-Setup").start()


def _install_setup_button(self):
    _original_build(self)
    toolbar = _find_button_parent(self.scenes_tab, "Añadir imagen propia")
    if toolbar is None:
        print("MARC: no se encontró la barra de herramientas de Escenas.")
        return
    self.prepare_ai_button = ttk.Button(
        toolbar, text="Preparar IA / Diagnóstico", command=lambda: _run_setup(self, show_dialog=True)
    )
    self.prepare_ai_button.pack(side="left", padx=(6, 0))
    self.full_production_button = ttk.Button(
        toolbar, text="Producción automática", style="Accent.TButton",
        command=lambda: _start_full_production(self)
    )
    self.full_production_button.pack(side="left", padx=(6, 0))
    self.animate_image_button = ttk.Button(
        toolbar, text="Animar imagen a vídeo IA", command=lambda: _open_video_generation(self)
    )
    self.animate_image_button.pack(side="left", padx=(6, 0))


def _startup_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self._setup_report = setup_engine.load_setup_report()
    self._setup_running = False
    self.scene_video_assets = {}
    # Setup is normally run by install_windows.bat; only run it on first launch
    # if no diagnostics report exists. Do not reinstall/re-download on every launch.
    if self._setup_report is None:
        self.after(1800, lambda: _run_setup(self, show_dialog=False))


def _run_package_import(self, package, script: str, directions: list[str], report: dict,
                        use_i2v: bool):
    """Import a folder through MARC's existing package copier and optionally intercept export."""
    if not report.get("ffmpeg", {}).get("available"):
        messagebox.showerror(
            "Falta FFmpeg",
            "M.A.R.C. no detectó FFmpeg. La preparación automática no consiguió instalarlo. "
            "Instálalo o selecciona ffmpeg.exe en el editor antes de exportar.",
            parent=self,
        )
        return
    start_hook_called = {"value": False}
    original_start = self._start_video_render
    original_ask = marc_app.messagebox.askyesno

    def ask_with_auto_export(title, message, *args, **kwargs):
        # Keep the project-replacement confirmation, but default the final package
        # question to Yes so the requested one-click flow goes straight to export.
        if title == "Paquete importado":
            return True
        return original_ask(title, message, *args, **kwargs)

    def intercepted_start(preview=False, remote=False):
        start_hook_called["value"] = True
        if use_i2v and report.get("video_generation_ready"):
            _start_i2v_batch(self, original_start, report)
        elif not use_i2v:
            # Explicitly selected CPU fallback: the established pipeline uses still
            # imagery with pan/zoom; it is not mislabelled as bodily AI animation.
            self._auto_export_after_import = True
            try:
                original_start(preview=False, remote=remote)
            finally:
                self._auto_export_after_import = False
        else:
            messagebox.showwarning(
                "Vídeo IA no disponible",
                "Este equipo no tiene un motor de vídeo IA completamente preparado. No se generará una falsa animación corporal.",
                parent=self,
            )

    self._start_video_render = intercepted_start
    marc_app.messagebox.askyesno = ask_with_auto_export
    try:
        self._apply_production_package(
            package.script_path, script, directions, list(package.image_paths),
            narration_path=package.narration_path, music_path=package.music_path,
        )
    except Exception as exc:
        messagebox.showerror("No se pudo iniciar la producción", str(exc), parent=self)
    finally:
        self._start_video_render = original_start
        marc_app.messagebox.askyesno = original_ask
    if not start_hook_called["value"]:
        self.status_var.set("Importación cancelada o pendiente de confirmación.")


def _start_full_production(self):
    if any(bool(getattr(self, name, False)) for name in (
        "generation_running", "render_running", "image_generation_running", "voice_generation_running",
        "getattr_placeholder",
    )):
        messagebox.showinfo("Proceso en curso", "Espera a que termine el proceso actual.", parent=self)
        return
    folder = filedialog.askdirectory(
        parent=self, title="Elige la carpeta con guion e imágenes (el audio es opcional)"
    )
    if not folder:
        return
    try:
        package = discover_production_package(folder)
        script = package.script_path.read_text(encoding="utf-8-sig").strip()
        directions = parse_scene_directions(package.direction_path) if package.direction_path else []
    except Exception as exc:
        messagebox.showerror("Paquete incompleto", str(exc), parent=self)
        return

    def after_setup(report: dict):
        if not report.get("ffmpeg", {}).get("available"):
            _run_package_import(self, package, script, directions, report, use_i2v=False)
            return
        if report.get("video_generation_ready"):
            _run_package_import(self, package, script, directions, report, use_i2v=True)
            return
        summary = _setup_summary(report)
        continue_basic = messagebox.askyesno(
            "Vídeo IA no disponible en este equipo",
            "M.A.R.C. detectó que no puede ejecutar movimiento corporal por IA con la configuración actual.\n\n"
            + summary + "\n\n"
            "¿Deseas continuar y crear el MP4 con las imágenes, las voces y el montaje convencional? "
            "Este modo usa movimiento de cámara y NO equivale a animación corporal real.",
            parent=self,
        )
        if continue_basic:
            _run_package_import(self, package, script, directions, report, use_i2v=False)

    _run_setup(self, show_dialog=False, continuation=after_setup)


def _start_i2v_batch(self, original_start, report: dict):
    """Animate each distinct imported still once, map clips to shots, then render audio+MP4."""
    workflow_value = str((report.get("comfyui") or {}).get("workflow_path") or "")
    workflow_path = Path(workflow_value) if workflow_value else setup_engine.ensure_official_workflow()
    comfy_url = str((report.get("comfyui") or {}).get("url") or setup_engine.DEFAULT_COMFY_URL)
    if not workflow_path or not workflow_path.is_file():
        messagebox.showerror("Falta el workflow de vídeo", "No se encuentra la plantilla LTX de imagen a vídeo.", parent=self)
        return
    still_map = {
        str(key): str(value) for key, value in (getattr(self, "scene_assets", {}) or {}).items()
        if value and Path(value).is_file()
    }
    if not still_map:
        messagebox.showerror("No hay imágenes", "El paquete no tiene imágenes válidas asignadas a las escenas.", parent=self)
        return
    scenes = list(getattr(self, "scene_data", []) or [])
    scenes_by_key = {str(index + 1): scene for index, scene in enumerate(scenes)}
    # One generation per distinct image. If the imported package has one image for
    # each original scene, the same short clip can be reused for its split timeline
    # shots without paying the generation cost for each storyboard fragment.
    image_targets: dict[str, dict] = {}
    for scene_key, image in still_map.items():
        resolved = str(Path(image).resolve())
        target = image_targets.setdefault(resolved, {"image": resolved, "keys": [], "context": "", "direction": ""})
        target["keys"].append(scene_key)
        if not target["context"]:
            scene = scenes_by_key.get(scene_key, {})
            target["context"] = f"{scene.get('title', '')}\n{scene.get('text', '')}".strip()
            target["direction"] = str((getattr(self, "scene_directions", {}) or {}).get(scene_key, "")).strip()

    output_root = Path(marc_app.PROJECTS_DIR) / str(self.current_id or "importacion") / "generated_video"
    output_root.mkdir(parents=True, exist_ok=True)
    button = getattr(self, "full_production_button", None)
    if button:
        button.configure(state="disabled")
    self.status_var.set(f"Animando {len(image_targets)} imagen(es) mediante IA…")

    def progress(message: str):
        _set_status(self, "Vídeo IA · " + message)

    def worker():
        clips: dict[str, str] = {}
        failures: list[str] = []
        total = len(image_targets)
        for count, target in enumerate(image_targets.values(), start=1):
            image_path = Path(target["image"])
            context = target["context"]
            direction = target["direction"]
            if self.render_cancel_event.is_set():
                failures.append("Generación cancelada por el usuario.")
                break
            signature = hashlib.sha256(
                (str(image_path.resolve()) + context + direction +
                 str(image_path.stat().st_mtime_ns) + str(image_path.stat().st_size)).encode("utf-8")
            ).hexdigest()[:20]
            destination = output_root / f"scene_i2v_{signature}.mp4"
            if destination.is_file() and destination.stat().st_size > 0:
                progress(f"Reutilizando clip {count}/{total}: {image_path.name}")
            else:
                try:
                    progress(f"Analizando y animando imagen {count}/{total}: {image_path.name}")
                    try:
                        prompt = analyze_image_with_ollama(
                            image_path, base_url=setup_engine.OLLAMA_URL,
                            scene_context=context, camera_direction=direction,
                        )
                    except VideoGenerationError:
                        # The narrative still gives the video model grounded direction;
                        # the diagnostic panel will still flag that visual analysis is absent.
                        prompt = (
                            "Animate the people and objects already visible in the reference image. "
                            "Preserve each character's identity, face, outfit, proportions, and the scene composition. "
                            f"Narrative context: {context[:1200]}. Camera/action direction: {direction[:350]}. "
                            "Create natural full-body motion and subtle secondary movement; do not morph identities, "
                            "add characters, or replace the setting."
                        )
                    generated = generate_video(
                        image_path=image_path,
                        motion_prompt=prompt,
                        workflow_path=workflow_path,
                        output_dir=output_root,
                        base_url=comfy_url,
                        negative_prompt="deformed anatomy, identity changes, extra limbs, flicker, severe blur, text, watermark",
                        progress=progress,
                        frame_count=49,
                    )
                    if generated.resolve() != destination.resolve():
                        if destination.exists():
                            destination.unlink()
                        generated.replace(destination)
                except Exception as exc:
                    failures.append(f"{image_path.name}: {exc}")
                    progress(f"Falló la animación de {image_path.name}: {exc}")
                    continue
            for key in target["keys"]:
                clips[key] = str(destination.resolve())

        if not clips:
            message = "\n".join(failures[:8]) or "No se generó ningún clip."
            self.after(0, lambda text=message: _video_batch_failed(self, text, button))
            return
        if failures:
            message = "\n".join(failures[:8])
            def ask_partial():
                ok = messagebox.askyesno(
                    "Algunas imágenes no se pudieron animar",
                    f"Se generaron {len(clips)} clip(s), pero fallaron {len(failures)} imagen(es).\n\n"
                    f"{message[:1800]}\n\n"
                    "¿Exportar el vídeo con los clips de IA que sí se generaron y movimiento de cámara en las escenas restantes?",
                    parent=self,
                )
                if ok:
                    _finish_video_batch(self, clips, original_start, button)
                else:
                    _video_batch_failed(self, "La exportación se canceló. Los clips generados se conservaron.", button)
            self.after(0, ask_partial)
        else:
            self.after(0, lambda: _finish_video_batch(self, clips, original_start, button))

    threading.Thread(target=worker, daemon=True, name="MARC-I2V-Batch").start()


def _finish_video_batch(self, clips: dict[str, str], original_start, button):
    try:
        self.scene_video_assets = clips
        try:
            manifest = Path(marc_app.PROJECTS_DIR) / str(self.current_id or "importacion") / "generated_video" / "scene_video_assets.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps(clips, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        self._auto_export_after_import = True
        self.status_var.set("Clips IA listos. Montando voces, música, subtítulos y MP4…")
        original_start(preview=False, remote=False)
    except Exception as exc:
        messagebox.showerror("No se pudo montar el MP4", str(exc), parent=self)
    finally:
        self._auto_export_after_import = False
        if button is not None:
            try:
                button.configure(state="normal")
            except tk.TclError:
                pass


def _video_batch_failed(self, message: str, button=None):
    self.status_var.set("La generación de vídeo IA no se completó.")
    if button is not None:
        try:
            button.configure(state="normal")
        except tk.TclError:
            pass
    messagebox.showerror(
        "No se pudo completar la producción IA",
        message + "\n\nLos archivos ya generados se conservaron en la carpeta de producción.",
        parent=self,
    )


def _open_video_generation(self):
    """Generate one clip from a still image using the configured local video workflow."""
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
    report = getattr(self, "_setup_report", None) or setup_engine.load_setup_report() or {}
    if not report.get("video_generation_ready"):
        _run_setup(
            self, show_dialog=False,
            continuation=lambda result: _continue_single_image(self, image_path, result),
        )
        return
    _continue_single_image(self, image_path, report)


def _continue_single_image(self, image_path: str, report: dict):
    if not report.get("video_generation_ready"):
        messagebox.showwarning(
            "No hay motor de vídeo IA compatible",
            _setup_summary(report) + "\n\nNo se generará un clip de cámara/zoom haciéndolo pasar por animación corporal.",
            parent=self,
        )
        return
    workflow_path = Path(str((report.get("comfyui") or {}).get("workflow_path") or ""))
    if not workflow_path.is_file():
        workflow_path = setup_engine.ensure_official_workflow()
    if not workflow_path or not workflow_path.is_file():
        messagebox.showerror("Falta workflow", "M.A.R.C. no pudo obtener la plantilla LTX de imagen a vídeo.", parent=self)
        return
    prompt = simpledialog.askstring(
        "Movimiento real con IA",
        "Escribe AUTO para analizar la imagen o describe la acción (ej.: camina, mira atrás y corre):",
        initialvalue="AUTO", parent=self,
    )
    if prompt is None or not prompt.strip():
        return
    output_root = Path(marc_app.PROJECTS_DIR) / str(getattr(self, "current_id", None) or "importacion") / "generated_video"
    button = getattr(self, "animate_image_button", None)
    if button:
        button.configure(state="disabled")
    def progress(message: str):
        _set_status(self, "Vídeo IA · " + message)
    def worker():
        try:
            if prompt.strip().casefold() in {"auto", "automático", "automatico"}:
                motion = analyze_image_with_ollama(
                    image_path, base_url=setup_engine.OLLAMA_URL
                )
            else:
                motion = prompt.strip()
            destination = generate_video(
                image_path=image_path, motion_prompt=motion,
                workflow_path=workflow_path, output_dir=output_root,
                base_url=str((report.get("comfyui") or {}).get("url") or setup_engine.DEFAULT_COMFY_URL),
                progress=progress, frame_count=49,
            )
            self.after(0, lambda path=str(destination): _single_video_finished(self, path, button))
        except Exception as exc:
            self.after(0, lambda details=str(exc): _video_batch_failed(self, details, button))
    threading.Thread(target=worker, daemon=True, name="MARC-Single-I2V").start()


def _single_video_finished(self, path: str, button=None):
    if button is not None:
        button.configure(state="normal")
    self.status_var.set("Vídeo IA generado: " + path)
    messagebox.showinfo(
        "Clip generado",
        f"El clip con movimiento generado por IA se guardó en:\n{path}\n\n"
        "En Producción automática, MARC también puede conectar estos clips al montaje completo junto con la voz y la música.",
        parent=self,
    )


marc_app.App._build = _install_setup_button
marc_app.App.__init__ = _startup_init


if __name__ == "__main__":
    marc_app.App().mainloop()
