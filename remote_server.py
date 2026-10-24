"""Authenticated loopback web control plane for MARC Video Studio AI.

The server intentionally binds to 127.0.0.1. To access it remotely, place it
behind Tailscale Serve rather than exposing this HTTP listener to the LAN.
"""
from __future__ import annotations

import hmac
import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

MAX_JSON_BYTES = 1_000_000
MAX_UPLOAD_BYTES = 512 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp4", ".mov", ".m4v", ".webm", ".mp3", ".wav", ".m4a", ".aac", ".srt"
}
DOWNLOAD_EXTENSIONS = {
    ".mp4", ".mov", ".m4v", ".webm", ".png", ".jpg", ".jpeg", ".webp", ".gif",
    ".mp3", ".wav", ".m4a", ".aac", ".srt", ".txt", ".json"
}

PANEL_HTML = r"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#09101d">
<title>MARC · Control remoto</title>
<style>
:root{color-scheme:dark;--bg:#070c15;--panel:#101a2a;--panel2:#142238;--border:#26364e;--text:#eef5ff;--muted:#a6b6cc;--blue:#249bff;--green:#35d39a;--yellow:#f2c15c;--red:#ff707a}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at 15% -10%,#143158 0,transparent 45%),var(--bg);color:var(--text);font:15px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{position:sticky;top:0;z-index:3;background:#09101df2;border-bottom:1px solid var(--border);padding:14px max(16px,calc((100vw - 900px)/2));backdrop-filter:blur(16px)}
.brand{font-weight:850;font-size:1.18rem;letter-spacing:.04em}.brand span{color:var(--blue)}.sub{color:var(--muted);font-size:.82rem;margin-top:2px}
main{width:min(900px,100%);margin:0 auto;padding:16px 14px 60px;display:grid;gap:14px}
.card{background:linear-gradient(155deg,#111c2d,#0c1421);border:1px solid var(--border);border-radius:17px;padding:16px;box-shadow:0 8px 28px #0002}
h2{font-size:1rem;margin:0 0 12px}h3{font-size:.92rem;margin:0 0 7px}
label{display:block;color:var(--muted);font-size:.84rem;margin:10px 0 5px}
input,select,textarea,button{font:inherit}input,select,textarea{width:100%;border:1px solid #30425e;background:#080f1b;color:var(--text);border-radius:10px;padding:11px 12px;outline:none}textarea{min-height:155px;resize:vertical;line-height:1.5}input:focus,select:focus,textarea:focus{border-color:var(--blue)}
button{border:1px solid #315174;border-radius:11px;padding:11px 13px;background:#152b45;color:var(--text);font-weight:700;cursor:pointer}button.primary{background:linear-gradient(130deg,#0877dc,#229cff);border-color:#269bff;color:white}button.good{background:#123e39;border-color:#217f6e}button.danger{background:#3a1d2a;border-color:#713047}button:disabled{opacity:.45;cursor:not-allowed}.row{display:flex;gap:8px;flex-wrap:wrap}.row>*{flex:1}.grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.muted{color:var(--muted)}.small{font-size:.82rem}.status{border:1px solid var(--border);background:#080f1a;padding:12px;border-radius:12px}.status strong{display:block;margin-bottom:4px}.pill{display:inline-block;border-radius:100px;padding:3px 8px;background:#20314a;color:#cfe7ff;font-size:.76rem}.pill.ok{background:#123e32;color:#8cf0c4}.pill.warn{background:#44371d;color:#ffe1a0}.progress{height:8px;background:#26364a;border-radius:99px;overflow:hidden;margin-top:10px}.progress div{height:100%;width:0;background:linear-gradient(90deg,#1687ef,#35d39a);transition:width .3s}.item{padding:11px 0;border-bottom:1px solid var(--border)}.item:last-child{border:0}.file{display:flex;gap:10px;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #223047}.file span{overflow-wrap:anywhere}.hidden{display:none!important}.notice{padding:10px 12px;border-radius:10px;background:#132b45;color:#c8e7ff;margin-top:8px}.error{background:#421f2b;color:#ffd2d6}.tokenrow{display:flex;gap:8px}.tokenrow input{min-width:0}.foot{color:var(--muted);font-size:.78rem;text-align:center;padding:8px}
@media(max-width:560px){header{padding:12px 15px}main{padding:12px 10px 45px}.card{padding:13px}.grid{grid-template-columns:1fr}.row button{min-width:0}.tokenrow{display:grid;grid-template-columns:1fr}.brand{font-size:1.08rem}}
</style>
</head>
<body>
<header><div class="brand">MARC <span>/ VIDEO STUDIO</span></div><div class="sub">Panel móvil · La computadora procesa los trabajos</div></header>
<main>
<section class="card" id="authCard">
<h2>Conectar con tu MARC</h2><p class="muted small">Introduce el código de acceso mostrado en MARC en tu computadora. No uses este panel en un dispositivo que no sea tuyo.</p>
<label for="token">Código de acceso</label><div class="tokenrow"><input id="token" type="password" autocomplete="current-password" placeholder="Pega aquí el código de MARC"><button class="primary" id="connectBtn">Conectar</button></div><div id="authMsg" class="notice hidden"></div>
</section>
<div id="app" class="hidden">
<section class="card"><h2>Estado de la computadora</h2><div class="status"><strong id="statusTitle">Conectando…</strong><span class="muted small" id="statusDetail">Esperando estado de MARC</span><div class="progress"><div id="progressBar"></div></div></div><div class="row" style="margin-top:10px"><button id="refreshBtn">Actualizar</button><button class="danger" id="logoutBtn">Desconectar</button></div><p class="muted small" id="engineInfo">Ollama y ComfyUI permanecen en la computadora.</p></section>
<section class="card"><h2>Crear una historia</h2><p class="muted small">MARC generará el guion en la computadora con Ollama. El guion queda pendiente de revisión antes de exportar.</p>
<label for="title">Nombre del proyecto</label><input id="title" maxlength="100" placeholder="Ej. La carta que llegó diez años tarde">
<label for="topic">Idea o premisa</label><textarea id="topic" style="min-height:90px" maxlength="5000" placeholder="Cuenta qué sucede, quién es el protagonista y qué conflicto debe resolver."></textarea>
<div class="grid"><div><label for="genre">Género</label><select id="genre"><option>Novela dramática</option><option>Reencarnación y venganza</option><option>Superación personal</option><option>Romance</option><option>Fantasía</option><option>Misterio y suspenso</option><option>Terror</option><option>Acción y aventura</option><option>Ciencia ficción</option><option>Drama familiar</option><option>Documental</option><option>Promocional</option></select></div>
<div><label for="platform">Formato</label><select id="platform"><option>YouTube 16:9</option><option>TikTok / Reels / Shorts 9:16</option><option>Facebook 1:1</option></select></div></div>
<div class="grid"><div><label for="duration">Duración objetivo</label><select id="duration"><option value="1">1 minuto</option><option value="2" selected>2 minutos</option><option value="3">3 minutos</option><option value="5">5 minutos</option><option value="10">10 minutos</option><option value="15">15 minutos</option><option value="20">20 minutos</option><option value="30">30 minutos</option></select></div><div><label for="mode">Producción</label><select id="mode"><option value="Corto (2 minutos)">Corto</option><option value="Novela / Serie">Novela / Serie</option></select></div></div>
<button class="primary" id="generateBtn" style="width:100%;margin-top:14px">✦ Generar guion en mi computadora</button><div id="generateMsg" class="notice hidden"></div>
</section>
<section class="card"><h2>Mis proyectos</h2><div class="row"><button id="listBtn">Actualizar proyectos</button><select id="projectSelect" aria-label="Seleccionar proyecto"><option value="">Selecciona un proyecto</option></select></div>
<div id="projectInfo" class="item muted small">Selecciona un proyecto para revisar el guion y sus archivos.</div>
<label for="script">Guion del proyecto seleccionado</label><textarea id="script" placeholder="El guion aparecerá aquí cuando esté disponible."></textarea>
<div class="row" style="margin-top:8px"><button id="saveScriptBtn">Guardar guion</button><button class="good" id="approveBtn">Aprobar guion</button></div>
<div class="row" style="margin-top:8px"><button id="imageBtn">Generar imágenes</button><button class="primary" id="renderBtn">Exportar MP4 en la computadora</button><button class="danger" id="cancelBtn">Cancelar trabajo</button></div>
<div id="projectMsg" class="notice hidden"></div>
</section>
<section class="card"><h2>Archivos y descargas</h2><p class="muted small">Los MP4 se guardan en la computadora y puedes descargarlos al teléfono desde aquí.</p><div id="files" class="muted small">Selecciona un proyecto.</div>
<label for="upload">Subir archivos desde el teléfono al proyecto</label><input id="upload" type="file" accept="image/*,video/*,audio/*,.srt,.txt">
<button id="uploadBtn" style="width:100%;margin-top:8px">Subir archivo seleccionado</button><div id="uploadMsg" class="notice hidden"></div>
</section>
<div class="foot">MARC Remote · Acceso privado por Tailscale · No compartas tu código de acceso.</div>
</div>
</main>
<script>
(function(){
const $=id=>document.getElementById(id);let token=localStorage.getItem("marc_remote_token")||"";let selectedId="";let lastScript="";let scriptDirty=false;let saveCommandId="";let seenCurrentId="";
if(token)$("token").value=token;
function message(id,text,isError){const e=$(id);e.textContent=text;e.classList.remove("hidden","error");if(isError)e.classList.add("error");}
function clearMessage(id){$(id).classList.add("hidden");}
async function api(path,options={}){const headers=Object.assign({"X-MARC-Token":token},options.headers||{});const response=await fetch(path,Object.assign({},options,{headers}));if(response.status===401)throw new Error("Código de acceso incorrecto. Revisa el código en MARC.");const type=response.headers.get("content-type")||"";const data=type.includes("application/json")?await response.json():null;if(!response.ok)throw new Error(data?.error||("Error HTTP "+response.status));return data;}
function authError(e){message("authMsg",e.message||String(e),true);$("authCard").classList.remove("hidden");$("app").classList.add("hidden");}
async function connect(){token=$("token").value.trim();if(!token){message("authMsg","Pega el código que aparece en MARC.",true);return;}try{const s=await api("/api/status");localStorage.setItem("marc_remote_token",token);$("authCard").classList.add("hidden");$("app").classList.remove("hidden");message("authMsg","Conexión correcta.");renderStatus(s);await refreshProjects();}catch(e){authError(e);}}
function renderStatus(s){$("statusTitle").textContent=s.label||"MARC disponible";$("statusDetail").textContent=(s.detail||"")+" · "+(s.running?"Trabajo en curso":"Sin trabajo activo");$("progressBar").style.width=Math.max(0,Math.min(100,Number(s.progress||0)))+"%";$("engineInfo").textContent="Proyecto activo: "+(s.current_title||"ninguno")+" · Ollama: "+(s.ollama?"detectado":"sin confirmar")+" · ComfyUI: "+(s.comfyui?"conectado":"sin confirmar");if(s.last_command&&s.last_command.ok===false)message("projectMsg",s.last_command.message||"La solicitud no se completó.",true);if(saveCommandId&&s.last_command&&s.last_command.id===saveCommandId&&s.last_command.ok){scriptDirty=false;lastScript=$("script").value;saveCommandId="";}const current=String(s.current_id||"");if(current&&current!==seenCurrentId){seenCurrentId=current;if(!selectedId)refreshProjects();}}
async function refreshStatus(){try{renderStatus(await api("/api/status"));}catch(e){message("projectMsg",e.message,true);}}
async function refreshProjects(){try{const data=await api("/api/projects");const sel=$("projectSelect");const old=selectedId||sel.value;sel.innerHTML='<option value="">Selecciona un proyecto</option>';for(const p of data.projects||[]){const o=document.createElement("option");o.value=String(p.id);o.textContent=(p.approved?"✓ ":"• ")+p.title+" (#"+p.id+")";sel.appendChild(o);}if(old&&[...sel.options].some(o=>o.value===old)){sel.value=old;}else if(sel.options.length>1){sel.selectedIndex=1;}selectedId=sel.value;if(selectedId)await loadProject();}catch(e){message("projectMsg",e.message,true);}}
async function loadProject(){selectedId=$("projectSelect").value;if(!selectedId){$("projectInfo").textContent="Selecciona un proyecto para revisar el guion y sus archivos.";$("script").value="";$("files").textContent="Selecciona un proyecto.";return;}try{const [data,filedata]=await Promise.all([api("/api/projects/"+selectedId),api("/api/projects/"+selectedId+"/files")]);const p=data.project;$("projectInfo").textContent="#"+p.id+" · "+p.title+" · "+(p.approved?"Guion aprobado":"Pendiente de revisión")+" · "+p.duration_minutes+" min";if(!scriptDirty||$("script").value===lastScript){$("script").value=p.script||"";lastScript=$("script").value;scriptDirty=false;}renderFiles(filedata.files||[]);}catch(e){message("projectMsg",e.message,true);}}
function renderFiles(files){const container=$("files");container.innerHTML="";if(!files.length){container.textContent="Todavía no hay archivos descargables. Exporta un MP4 o sube un recurso al proyecto.";return;}for(const f of files){const row=document.createElement("div");row.className="file";const label=document.createElement("span");label.textContent=f.name+" · "+f.size_label;const button=document.createElement("button");button.textContent=f.download?"Descargar":"Archivo";button.disabled=!f.download;button.addEventListener("click",()=>downloadFile(f.path,f.name));row.append(label,button);container.appendChild(row);}}
async function downloadFile(path,name){try{const response=await fetch("/api/download?project_id="+encodeURIComponent(selectedId)+"&path="+encodeURIComponent(path),{headers:{"X-MARC-Token":token}});if(!response.ok){const d=await response.json().catch(()=>({}));throw new Error(d.error||"No se pudo descargar el archivo.");}const blob=await response.blob();const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),30000);}catch(e){message("projectMsg",e.message,true);}}
async function command(action,payload){const data=await api("/api/command",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action,payload:payload||{}})});return data;}
$("script").addEventListener("input",()=>{scriptDirty=$("script").value!==lastScript;});$("connectBtn").addEventListener("click",connect);$("token").addEventListener("keydown",e=>{if(e.key==="Enter")connect();});
$("refreshBtn").addEventListener("click",async()=>{await refreshStatus();await refreshProjects();});$("listBtn").addEventListener("click",refreshProjects);$("projectSelect").addEventListener("change",loadProject);
$("generateBtn").addEventListener("click",async()=>{if(!$("title").value.trim()||!$("topic").value.trim()){message("generateMsg","Escribe el nombre del proyecto y la premisa.",true);return;}try{$("generateBtn").disabled=true;selectedId="";$("projectSelect").value="";await command("generate_script",{title:$("title").value.trim(),topic:$("topic").value.trim(),genre:$("genre").value,platform:$("platform").value,duration:Number($("duration").value),video_mode:$("mode").value});message("generateMsg","Solicitud enviada a la computadora. El guion se generará allí; puedes salir de esta página y volver más tarde.");await refreshProjects();}catch(e){message("generateMsg",e.message,true);}finally{$("generateBtn").disabled=false;}});
$("saveScriptBtn").addEventListener("click",async()=>{if(!selectedId){message("projectMsg","Selecciona un proyecto.",true);return;}try{const reply=await command("save_script",{project_id:Number(selectedId),script:$("script").value});saveCommandId=reply.request_id;message("projectMsg","Solicitud de guardado enviada.");}catch(e){message("projectMsg",e.message,true);}});
$("approveBtn").addEventListener("click",async()=>{if(!selectedId){message("projectMsg","Selecciona un proyecto.",true);return;}if(scriptDirty){message("projectMsg","Guarda los cambios del guion antes de aprobarlo.",true);return;}if(!confirm("Confirmas que has revisado el guion y quieres aprobarlo para exportar?"))return;try{await command("approve_script",{project_id:Number(selectedId)});message("projectMsg","Solicitud de aprobación enviada.");}catch(e){message("projectMsg",e.message,true);}});
$("imageBtn").addEventListener("click",async()=>{if(!selectedId){message("projectMsg","Selecciona un proyecto.",true);return;}if(!confirm("Generar las imágenes que faltan? En tu laptop puede tardar mucho porque ComfyUI usa la CPU."))return;try{await command("generate_images",{project_id:Number(selectedId)});message("projectMsg","Generación de imágenes solicitada. Deja MARC y ComfyUI abiertos.");}catch(e){message("projectMsg",e.message,true);}});$("renderBtn").addEventListener("click",async()=>{if(!selectedId){message("projectMsg","Selecciona un proyecto.",true);return;}if(!confirm("Iniciar exportación MP4 en la computadora? El proceso puede tardar y usar bastante CPU."))return;try{await command("render_video",{project_id:Number(selectedId)});message("projectMsg","Exportación solicitada. Deja la computadora encendida y MARC abierto.");}catch(e){message("projectMsg",e.message,true);}});
$("cancelBtn").addEventListener("click",async()=>{try{await command("cancel");message("projectMsg","Cancelación solicitada.");}catch(e){message("projectMsg",e.message,true);}});
$("uploadBtn").addEventListener("click",async()=>{const file=$("upload").files[0];if(!selectedId){message("uploadMsg","Selecciona el proyecto antes de subir un archivo.",true);return;}if(!file){message("uploadMsg","Selecciona primero una imagen, vídeo o audio.",true);return;}if(file.size>512*1024*1024){message("uploadMsg","El archivo supera el límite de 512 MB.",true);return;}try{$("uploadBtn").disabled=true;const response=await fetch("/api/upload?project_id="+encodeURIComponent(selectedId)+"&filename="+encodeURIComponent(file.name),{method:"POST",headers:{"X-MARC-Token":token,"Content-Type":"application/octet-stream"},body:file});const data=await response.json();if(!response.ok)throw new Error(data.error||"Falló la carga.");message("uploadMsg","Archivo guardado en el proyecto. Puedes asignarlo desde MARC en la computadora.");$("upload").value="";await loadProject();}catch(e){message("uploadMsg",e.message,true);}finally{$("uploadBtn").disabled=false;}});
$("logoutBtn").addEventListener("click",()=>{localStorage.removeItem("marc_remote_token");token="";$("app").classList.add("hidden");$("authCard").classList.remove("hidden");$("token").value="";});
if(token){connect();}
setInterval(async()=>{if(token&&!$("app").classList.contains("hidden")){await refreshStatus();if(selectedId)await loadProject();}},3500);
})();
</script>
</body>
</html>"""


def _safe_filename(filename: str) -> str:
    name = Path(unquote(str(filename or "upload"))).name
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name).strip(" .")
    return name[:120] or "upload"


def _size_label(size: int) -> str:
    value = float(max(0, size))
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{value:.1f} GB"


class RemoteControlServer:
    """Loopback-only HTTP server used by the MARC desktop app and Tailscale Serve."""

    def __init__(self, *, data_dir, db_path, projects_dir, command_queue, snapshot_provider,
                 host="127.0.0.1", port=8765):
        self.data_dir = Path(data_dir)
        self.db_path = Path(db_path)
        self.projects_dir = Path(projects_dir)
        self.command_queue = command_queue
        self.snapshot_provider = snapshot_provider
        self.host = host
        self.port = int(port)
        self._httpd = None
        self._thread = None
        self.token = self._load_or_create_token()

    def _load_or_create_token(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / "remote_access.json"
        try:
            content = json.loads(path.read_text(encoding="utf-8"))
            token = content.get("token", "")
            if isinstance(token, str) and len(token) >= 32:
                return token
        except (OSError, json.JSONDecodeError, AttributeError):
            pass
        token = secrets.token_urlsafe(32)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"token": token, "created_at": time.time()}, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        return token

    @property
    def local_url(self):
        return f"http://127.0.0.1:{self.port}"

    def start(self):
        if self._httpd:
            return
        owner = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "MARCRemote/1.0"
            sys_version = ""

            def log_message(self, fmt, *args):
                # Do not log request headers or authentication material.
                return

            def _send(self, status, body, content_type="application/json; charset=utf-8", headers=None):
                if isinstance(body, str):
                    body = body.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("Referrer-Policy", "no-referrer")
                self.send_header("X-Frame-Options", "DENY")
                self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
                if headers:
                    for key, value in headers.items():
                        self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def _json(self, status, data):
                self._send(status, json.dumps(data, ensure_ascii=False).encode("utf-8"))

            def _auth_ok(self):
                supplied = self.headers.get("X-MARC-Token", "")
                if not supplied:
                    authorization = self.headers.get("Authorization", "")
                    if authorization.lower().startswith("bearer "):
                        supplied = authorization[7:].strip()
                return bool(supplied) and hmac.compare_digest(supplied, owner.token)

            def _authorized(self):
                if self._auth_ok():
                    return True
                self._json(401, {"error": "Código de acceso no válido."})
                return False

            def _read_json(self):
                try:
                    size = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise ValueError("Longitud de solicitud no válida.")
                if size < 0 or size > MAX_JSON_BYTES:
                    raise ValueError("La solicitud es demasiado grande.")
                raw = self.rfile.read(size)
                payload = json.loads(raw.decode("utf-8") if raw else "{}")
                if not isinstance(payload, dict):
                    raise ValueError("Se esperaba un objeto JSON.")
                return payload

            def do_GET(self):
                parsed = urlparse(self.path)
                path = parsed.path
                if path == "/" or path == "/index.html":
                    self._send(200, PANEL_HTML, "text/html; charset=utf-8")
                    return
                if path == "/favicon.ico":
                    self._send(204, b"", "image/x-icon")
                    return
                if path == "/api/health":
                    self._json(200, {"service": "MARC Remote", "token_required": True})
                    return
                if not path.startswith("/api/") or not self._authorized():
                    if path.startswith("/api/"):
                        return
                    self._json(404, {"error": "Ruta no encontrada."})
                    return
                try:
                    if path == "/api/status":
                        self._json(200, owner.snapshot_provider() or {})
                    elif path == "/api/projects":
                        self._json(200, {"projects": owner._list_projects()})
                    elif path.startswith("/api/projects/") and path.endswith("/files"):
                        project_id = owner._project_id_from_path(path, suffix="/files")
                        if project_id is None:
                            self._json(400, {"error": "ID de proyecto no válido."})
                        else:
                            self._json(200, {"files": owner._list_files(project_id)})
                    elif path.startswith("/api/projects/"):
                        project_id = owner._project_id_from_path(path)
                        project = owner._get_project(project_id) if project_id is not None else None
                        if not project:
                            self._json(404, {"error": "No se encontró el proyecto."})
                        else:
                            self._json(200, {"project": project})
                    elif path == "/api/download":
                        query = parse_qs(parsed.query)
                        try:
                            project_id = int(query.get("project_id", [""])[0])
                        except (TypeError, ValueError):
                            self._json(400, {"error": "ID de proyecto no válido."})
                            return
                        relative = unquote(query.get("path", [""])[0])
                        candidate = owner._resolve_download(project_id, relative)
                        if candidate is None:
                            self._json(404, {"error": "Archivo no encontrado o no permitido."})
                            return
                        size = candidate.stat().st_size
                        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
                        self.send_response(200)
                        self.send_header("Content-Type", content_type)
                        self.send_header("Content-Length", str(size))
                        self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(candidate.name))
                        self.send_header("Cache-Control", "no-store")
                        self.send_header("X-Content-Type-Options", "nosniff")
                        self.end_headers()
                        with candidate.open("rb") as stream:
                            while True:
                                chunk = stream.read(1024 * 1024)
                                if not chunk:
                                    break
                                self.wfile.write(chunk)
                    else:
                        self._json(404, {"error": "Ruta no encontrada."})
                except (OSError, sqlite3.Error, ValueError) as exc:
                    self._json(500, {"error": str(exc)[:500] or "Error interno."})

            def do_POST(self):
                parsed = urlparse(self.path)
                if not parsed.path.startswith("/api/") or not self._authorized():
                    if not parsed.path.startswith("/api/"):
                        self._json(404, {"error": "Ruta no encontrada."})
                    return
                if parsed.path == "/api/upload":
                    self._handle_upload(parsed.query)
                    return
                try:
                    payload = self._read_json()
                except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
                    self._json(400, {"error": str(exc)[:300] or "JSON no válido."})
                    return
                if parsed.path == "/api/command":
                    action = str(payload.get("action", "")).strip()
                    allowed = {"generate_script", "save_script", "approve_script", "render_video", "generate_images",
                               "cancel", "cancel_generation", "cancel_render", "open_project"}
                    if action not in allowed:
                        self._json(400, {"error": "Acción no permitida."})
                        return
                    command_payload = payload.get("payload", {})
                    if not isinstance(command_payload, dict):
                        self._json(400, {"error": "Los parámetros deben ser un objeto."})
                        return
                    request_id = uuid.uuid4().hex
                    owner.command_queue.put({"id": request_id, "action": action, "payload": command_payload})
                    self._json(202, {"accepted": True, "request_id": request_id, "message": "Solicitud encolada en MARC."})
                    return
                self._json(404, {"error": "Ruta no encontrada."})

            def _handle_upload(self, query_string):
                query = parse_qs(query_string)
                try:
                    project_id = int(query.get("project_id", [""])[0])
                    length = int(self.headers.get("Content-Length", "0"))
                except (TypeError, ValueError):
                    self._json(400, {"error": "Proyecto o tamaño no válido."})
                    return
                if length <= 0 or length > MAX_UPLOAD_BYTES:
                    self._json(413, {"error": "El archivo está vacío o supera el límite de 512 MB."})
                    return
                filename = _safe_filename(query.get("filename", ["upload"])[0])
                extension = Path(filename).suffix.lower()
                if extension not in ALLOWED_UPLOAD_EXTENSIONS:
                    self._json(415, {"error": "Tipo de archivo no permitido."})
                    return
                if not owner._get_project(project_id):
                    self._json(404, {"error": "No se encontró el proyecto."})
                    return
                destination_dir = owner.projects_dir / str(project_id) / "uploads"
                destination_dir.mkdir(parents=True, exist_ok=True)
                destination = destination_dir / (uuid.uuid4().hex[:10] + "_" + filename)
                remaining = length
                try:
                    with destination.open("wb") as output:
                        while remaining:
                            chunk = self.rfile.read(min(1024 * 1024, remaining))
                            if not chunk:
                                raise OSError("La carga se interrumpió antes de completarse.")
                            output.write(chunk)
                            remaining -= len(chunk)
                except OSError as exc:
                    try:
                        destination.unlink(missing_ok=True)
                    except OSError:
                        pass
                    self._json(400, {"error": str(exc)[:300]})
                    return
                self._json(201, {"uploaded": True, "path": str(destination.relative_to(owner.projects_dir / str(project_id))).replace("\\", "/"),
                                 "name": destination.name, "size": length})

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._httpd.daemon_threads = True
        self._thread = threading.Thread(target=self._httpd.serve_forever, name="MARCRemoteHTTP", daemon=True)
        self._thread.start()

    def stop(self):
        if self._httpd:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
        self._thread = None

    def _connect_db(self):
        connection = sqlite3.connect(self.db_path, timeout=5)
        connection.row_factory = sqlite3.Row
        return connection

    def _list_projects(self):
        with self._connect_db() as db:
            rows = db.execute(
                "SELECT id,title,topic,platform,duration_minutes,approved,created_at FROM projects ORDER BY id DESC LIMIT 200"
            ).fetchall()
        return [dict(row) for row in rows]

    def _get_project(self, project_id):
        if project_id is None or project_id < 1:
            return None
        with self._connect_db() as db:
            row = db.execute("SELECT id,title,topic,platform,duration_minutes,approved,created_at,script,style,video_mode FROM projects WHERE id=?",
                             (project_id,)).fetchone()
        return dict(row) if row else None

    def _project_id_from_path(self, path, suffix=""):
        candidate = path[len("/api/projects/"):]
        if suffix and candidate.endswith(suffix):
            candidate = candidate[:-len(suffix)]
        candidate = candidate.strip("/")
        if not candidate.isdigit():
            return None
        value = int(candidate)
        return value if value > 0 else None

    def _project_root(self, project_id):
        root = (self.projects_dir / str(int(project_id))).resolve()
        base = self.projects_dir.resolve()
        if not root.is_relative_to(base):
            return None
        if not root.is_dir():
            return None
        return root

    def _list_files(self, project_id):
        root = self._project_root(project_id)
        if root is None:
            return []
        files = []
        try:
            iterator = root.rglob("*")
            for path in iterator:
                if not path.is_file() or path.suffix.lower() not in DOWNLOAD_EXTENSIONS:
                    continue
                resolved = path.resolve()
                if not resolved.is_relative_to(root):
                    continue
                relative = path.relative_to(root).as_posix()
                stat = path.stat()
                is_download = path.suffix.lower() in DOWNLOAD_EXTENSIONS
                files.append({"name": path.name, "path": relative, "size": stat.st_size,
                              "size_label": _size_label(stat.st_size), "download": is_download,
                              "modified": stat.st_mtime})
        except OSError:
            pass
        files.sort(key=lambda item: (0 if item["name"].lower().endswith(".mp4") else 1, -item["modified"]))
        return files[:300]

    def _resolve_download(self, project_id, relative):
        root = self._project_root(project_id)
        if root is None or not relative:
            return None
        try:
            candidate = (root / relative).resolve()
            if not candidate.is_relative_to(root) or not candidate.is_file():
                return None
            if candidate.suffix.lower() not in DOWNLOAD_EXTENSIONS:
                return None
            return candidate
        except (OSError, ValueError):
            return None
