"""MARC desktop launcher: automatic setup and one-flow image-to-video production."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
import tkinter as tk
from types import SimpleNamespace
from tkinter import filedialog, messagebox, simpledialog, ttk
from pathlib import Path

import app as marc_app
import setup_engine
from local_audio import generate_ambient_bed, infer_mood
from creator_wizard import (
    animation_preset, create_creator_wizard, mode_uses_ai,
    normalize_script_for_images, refresh_voice_label, set_creator_status,
)
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
    waiters = list(getattr(self, "_setup_waiters", []) or [])
    self._setup_waiters = []
    if continuation:
        waiters.append(continuation)
    for callback in waiters:
        try:
            callback(report)
        except Exception as exc:
            messagebox.showerror("No se pudo continuar la producción", str(exc), parent=self)


def _run_setup(self, show_dialog: bool = True, continuation=None,
               install_video_models: bool = True,
               install_text_model: bool = True,
               install_vision_model: bool = True):
    if getattr(self, "_setup_running", False):
        if continuation:
            self._setup_waiters = list(getattr(self, "_setup_waiters", []) or []) + [continuation]
        self._setup_show_dialog = bool(getattr(self, "_setup_show_dialog", False) or show_dialog)
        # If the user requests a more complete setup while a lighter one is active,
        # queue a full diagnostic after the current pass rather than silently ignoring it.
        requested = (install_video_models, install_text_model, install_vision_model)
        active = getattr(self, "_setup_profile", (False, False, False))
        if any(a and not b for a, b in zip(requested, active)):
            self._setup_waiters.append(
                lambda _report: _run_setup(
                    self, show_dialog=False,
                    install_video_models=install_video_models,
                    install_text_model=install_text_model,
                    install_vision_model=install_vision_model,
                )
            )
        return
    self._setup_running = True
    self._setup_show_dialog = show_dialog
    self._setup_profile = (install_video_models, install_text_model, install_vision_model)
    self._setup_waiters = [continuation] if continuation else []
    for button_name in ("prepare_ai_button", "full_production_button"):
        button = getattr(self, button_name, None)
        if button is not None:
            try:
                button.configure(state="disabled")
            except tk.TclError:
                pass
    set_creator_status(self, "Analizando hardware e instalando solo lo necesario…", 8)

    def progress(message: str):
        _set_status(self, "Preparación IA · " + message)

    def worker():
        try:
            report = setup_engine.run_automatic_setup(
                callback=progress,
                install_video_models=install_video_models,
                install_text_model=install_text_model,
                install_vision_model=install_vision_model,
            )
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
            self.after(0, lambda result=report: _setup_finished(
                self, result, bool(getattr(self, "_setup_show_dialog", show_dialog))
            ))
        except (tk.TclError, RuntimeError):
            pass

    threading.Thread(target=worker, daemon=True, name="MARC-AI-Setup").start()


def _show_advanced_editor(self):
    wizard = getattr(self, "_creator_wizard", None)
    shell = getattr(self, "_marc_full_editor_shell", None)
    if wizard is not None:
        wizard.grid_remove()
    if shell is not None:
        shell.grid()
    try:
        self.studio_tabs.select(self.script_tab)
        self.after(100, self._set_responsive_initial_sashes)
    except Exception:
        pass


def _show_easy_creator(self):
    shell = getattr(self, "_marc_full_editor_shell", None)
    wizard = getattr(self, "_creator_wizard", None)
    if shell is not None:
        shell.grid_remove()
    if wizard is not None:
        wizard.grid()
        try:
            self._creator_show_page(1)
        except Exception:
            pass


def _install_setup_button(self):
    _original_build(self)
    shell = getattr(self, "_marc_full_editor_shell", None)
    if shell is None:
        shell = next((child for child in self.winfo_children() if child.winfo_manager() == "grid"), None)
        self._marc_full_editor_shell = shell

    # Keep all legacy controls and tabs, but start beginners in the three-step creator.
    head_right = getattr(getattr(self, "header_tools_button", None), "master", None)
    if head_right is not None:
        self.easy_creator_button = ttk.Button(
            head_right, text="Creador fácil", command=lambda: _show_easy_creator(self)
        )
        self.easy_creator_button.pack(side="left", padx=(6, 0))

    self.full_production_button = None
    self.prepare_ai_button = None
    self.animate_image_button = None
    self.video_ai_actions = None
    self._creator_package = None
    self._creator_production_mode = "Básico"
    self._creator_status_var = tk.StringVar(value="Listo para empezar.")
    self._creator_advanced_callback = lambda: _show_advanced_editor(self)
    self._creator_easy_callback = lambda: _show_easy_creator(self)
    create_creator_wizard(
        self,
        on_start=lambda **kwargs: _start_wizard_production(self, **kwargs),
        on_advanced=lambda: _show_advanced_editor(self),
    )


def _start_wizard_production(self, title: str, script: str, image_paths: list[str], mode: str):
    """Prepare a new project from the guided creator, then run its chosen production preset."""
    try:
        title = str(title or "").strip()
        images = [str(Path(item).expanduser().resolve()) for item in image_paths
                  if Path(item).expanduser().is_file()]
        if not title:
            raise ValueError("Escribe el nombre del vídeo.")
        if not images:
            raise ValueError("Añade al menos una imagen.")
        script = normalize_script_for_images(str(script or ""), len(images))
        # Preserve a previously open project before opening a fresh production.
        if getattr(self, "current_id", None) is not None:
            try:
                self.save_project(quiet=True)
            except Exception:
                pass
        self.new_project()
        self.title_var.set(title)
        self.topic_var.set(("Producción desde guion: " + " ".join(script.split()))[:2950])
        preset = animation_preset(mode)
        self.animation_style_var.set(preset["animation_style"])
        self.animation_intensity_var.set(preset["animation_intensity"])
        self.transition_style_var.set(preset["transition_style"])
        self.overlay_mode_var.set(preset["overlay_mode"])
        self.scene_video_assets = {}
        refresh_voice_label(self)

        staging = setup_engine.DATA_ROOT / "wizard_imports" / uuid.uuid4().hex
        staging.mkdir(parents=True, exist_ok=True)
        script_path = staging / "guion.md"
        script_path.write_text(script, encoding="utf-8")
        package = SimpleNamespace(
            root=staging,
            script_path=script_path,
            image_paths=tuple(Path(item) for item in images),
        )
        self._creator_package = package
        self._creator_production_mode = str(mode or "Básico")
        set_creator_status(self, "Analizando el equipo y preparando las herramientas necesarias…", 8)
    except Exception as exc:
        set_creator_status(self, f"No se pudo preparar el proyecto: {exc}", 0)
        messagebox.showerror("No se pudo preparar el vídeo", str(exc), parent=self)
        return

    ai_requested = mode_uses_ai(mode)

    def after_setup(report: dict):
        if not report.get("ffmpeg", {}).get("available"):
            set_creator_status(self, "Falta FFmpeg. No se ha iniciado el render.", 0)
            messagebox.showerror(
                "No se pudo preparar el montaje",
                "M.A.R.C. no detectó FFmpeg. Pulsa Editor avanzado → Diagnóstico para revisar la instalación.",
                parent=self,
            )
            return
        if not ai_requested:
            set_creator_status(self, "Importando escenas y preparando voz, música y montaje…", 22)
            _run_package_import(self, package, script, [], report, use_i2v=False)
            return
        if report.get("video_generation_ready"):
            set_creator_status(self, "Motor de vídeo listo. Preparando animación IA por escena…", 25)
            _run_package_import(self, package, script, [], report, use_i2v=True)
            return
        summary = _setup_summary(report)
        continue_basic = messagebox.askyesno(
            "Movimiento IA no disponible en este equipo",
            "Este equipo no ha quedado preparado para movimiento corporal neuronal.\n\n"
            + summary + "\n\n¿Crear el vídeo con movimiento de cámara, voces, música y montaje convencional? "
            "Podrás volver a probar Movimiento IA desde un equipo compatible.",
            parent=self,
        )
        if continue_basic:
            self.animation_style_var.set("2D fluida")
            self.animation_intensity_var.set("Normal")
            self.transition_style_var.set("Fundido suave")
            self.overlay_mode_var.set("Título de escena")
            set_creator_status(self, "Usando el modo básico compatible con este equipo…", 22)
            _run_package_import(self, package, script, [], report, use_i2v=False)
        else:
            set_creator_status(self, "Producción en pausa. Instala un motor de vídeo compatible o cambia a Básico.", 0)

    _run_setup(
        self, show_dialog=False, continuation=after_setup,
        install_video_models=ai_requested,
        install_text_model=False,
        install_vision_model=ai_requested,
    )


def _startup_init(self, *args, **kwargs):
    _original_init(self, *args, **kwargs)
    self._setup_report = setup_engine.load_setup_report()
    self._setup_running = False
    self.scene_video_assets = {}
    # Installation and model downloads are user-triggered from the creator or tools panel.
    # Opening the app never starts a hidden multi-GB download.


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
    self.scene_video_assets = {}
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
            # The CPU-compatible fallback is explicitly labelled as camera motion.
            _start_basic_export(self, original_start, remote=remote)
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


def _watch_export_completion(self, previous_path: str = "", attempt: int = 0):
    """Open the export folder once the final render has produced a new MP4."""
    if getattr(self, "render_running", False):
        if attempt < 7200:
            try:
                self.after(2000, lambda: _watch_export_completion(self, previous_path, attempt + 1))
            except (tk.TclError, RuntimeError):
                pass
        return
    current_path = str(getattr(self, "last_export_path", "") or "")
    if not current_path or current_path == previous_path:
        return
    path = Path(current_path)
    if not path.is_file():
        return
    self.status_var.set("MP4 terminado. Abriendo la carpeta de exportación…")
    try:
        if os.name == "nt":
            os.startfile(str(path.parent))
        else:
            import webbrowser
            webbrowser.open(path.parent.as_uri())
    except (OSError, AttributeError):
        pass


def _start_basic_export(self, original_start, remote=False):
    """Generate a small offline ambient bed when no music was supplied, then export."""
    current_music = str(getattr(self, "music_track_path", "") or "")
    if current_music and Path(current_music).is_file():
        _continue_basic_export(self, original_start, current_music, remote=remote)
        return
    try:
        project_root = Path(marc_app.PROJECTS_DIR) / str(getattr(self, "current_id", None) or "importacion")
        music_root = project_root / "generated_video"
        music_root.mkdir(parents=True, exist_ok=True)
        script = self.script_text.get("1.0", "end-1c")
        mood = infer_mood(script)
        destination = music_root / f"marc_ambient_{mood}.wav"
    except Exception:
        destination = None
        mood = "drama"
    button = getattr(self, "full_production_button", None)
    if button is not None:
        button.configure(state="disabled")

    def worker():
        audio_path = ""
        try:
            if destination is not None:
                if not destination.is_file() or destination.stat().st_size < 100_000:
                    _set_status(self, f"Creando banda sonora ambiental local ({mood})…")
                    generate_ambient_bed(destination, mood=mood)
                if destination.is_file() and destination.stat().st_size > 0:
                    audio_path = str(destination.resolve())
        except Exception as exc:
            _set_status(self, f"No se pudo generar la música automáticamente: {exc}")
        try:
            self.after(0, lambda path=audio_path: _continue_basic_export(
                self, original_start, path, remote=remote, button=button
            ))
        except (tk.TclError, RuntimeError):
            pass

    threading.Thread(target=worker, daemon=True, name="MARC-Ambient-Music").start()


def _continue_basic_export(self, original_start, music_path: str, remote=False, button=None):
    if music_path and (not getattr(self, "music_track_path", "") or not Path(self.music_track_path).is_file()):
        self.music_track_path = music_path
        try:
            self._refresh_audio_track_label()
        except Exception:
            pass
    previous_path = str(getattr(self, "last_export_path", "") or "")
    self._auto_export_after_import = True
    try:
        original_start(preview=False, remote=remote)
        self.after(2000, lambda: _watch_export_completion(self, previous_path))
    finally:
        self._auto_export_after_import = False
        if button is not None:
            try:
                button.configure(state="normal")
            except tk.TclError:
                pass


def _i2v_dimensions(self) -> tuple[int, int]:
    try:
        platform = str(self.platform_var.get())
    except Exception:
        platform = "YouTube 16:9"
    if "9:16" in platform:
        return 512, 768
    if "1:1" in platform:
        return 640, 640
    return 768, 512


def _start_i2v_batch(self, original_start, report: dict):
    """Animate each distinct imported still once, map clips to shots, then render audio+MP4."""
    workflow_value = str((report.get("comfyui") or {}).get("workflow_path") or "")
    workflow_path = Path(workflow_value) if workflow_value else setup_engine.ensure_official_workflow()
    comfy_url = str((report.get("comfyui") or {}).get("url") or setup_engine.DEFAULT_COMFY_URL)
    i2v_width, i2v_height = _i2v_dimensions(self)
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
    try:
        script_for_music = self.script_text.get("1.0", "end-1c")
    except Exception:
        script_for_music = ""
    music_mood = infer_mood(script_for_music)
    existing_music = str(getattr(self, "music_track_path", "") or "")
    music_is_available = bool(existing_music and Path(existing_music).is_file())
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

    try:
        self.render_cancel_event.clear()
    except Exception:
        pass
    output_root = Path(marc_app.PROJECTS_DIR) / str(self.current_id or "importacion") / "generated_video"
    output_root.mkdir(parents=True, exist_ok=True)
    button = getattr(self, "full_production_button", None)
    if button:
        button.configure(state="disabled")
    self.status_var.set(f"Animando {len(image_targets)} imagen(es) mediante IA…")

    def progress(message: str):
        _set_status(self, "Vídeo IA · " + message)

    generated_music = output_root / f"marc_ambient_{music_mood}.wav"

    def worker():
        clips: dict[str, str] = {}
        failures: list[str] = []
        total = len(image_targets)
        music_path = ""
        if not music_is_available:
            try:
                if not generated_music.is_file() or generated_music.stat().st_size < 100_000:
                    progress(f"Creando banda sonora ambiental local ({music_mood})…")
                    generate_ambient_bed(generated_music, mood=music_mood)
                if generated_music.is_file() and generated_music.stat().st_size > 0:
                    music_path = str(generated_music.resolve())
                    progress("Banda sonora ambiental preparada.")
            except Exception as exc:
                progress(f"La banda sonora no se pudo crear; se continuará sin música: {exc}")
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
                        frame_count=49, output_width=i2v_width, output_height=i2v_height,
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
                    _finish_video_batch(self, clips, original_start, button, music_path)
                else:
                    _video_batch_failed(self, "La exportación se canceló. Los clips generados se conservaron.", button)
            self.after(0, ask_partial)
        else:
            self.after(0, lambda: _finish_video_batch(self, clips, original_start, button, music_path))

    threading.Thread(target=worker, daemon=True, name="MARC-I2V-Batch").start()


def _finish_video_batch(self, clips: dict[str, str], original_start, button, generated_music=""):
    try:
        self.scene_video_assets = clips
        if generated_music and (not getattr(self, "music_track_path", "") or not Path(self.music_track_path).is_file()):
            self.music_track_path = generated_music
            try:
                self._refresh_audio_track_label()
            except Exception:
                pass
        try:
            manifest = Path(marc_app.PROJECTS_DIR) / str(self.current_id or "importacion") / "generated_video" / "scene_video_assets.json"
            manifest.parent.mkdir(parents=True, exist_ok=True)
            manifest.write_text(json.dumps(clips, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass
        previous_path = str(getattr(self, "last_export_path", "") or "")
        self._auto_export_after_import = True
        self.status_var.set("Clips IA listos. Montando voces, música, subtítulos y MP4…")
        original_start(preview=False, remote=False)
        self.after(2000, lambda: _watch_export_completion(self, previous_path))
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
    i2v_width, i2v_height = _i2v_dimensions(self)
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
                progress=progress, frame_count=49, output_width=i2v_width, output_height=i2v_height,
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
