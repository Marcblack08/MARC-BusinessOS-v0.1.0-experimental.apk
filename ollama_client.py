"""Cliente local para Ollama. No usa servicios externos ni claves API."""
import json
import urllib.request
import urllib.error

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODEL_NAME = "qwen2.5:3b"

def generate_script(title, topic, platform, minutes, style):
    prompt = (
        "Eres un guionista profesional de videos. Escribe en español natural un guion original "
        "con secciones [GANCHO], [INTRODUCCION], [ESCENA 1], [ESCENA 2], [CIERRE]. "
        "Incluye narración completa y sugerencias visuales breves. No inventes datos como hechos; "
        "señala lo que deba verificarse. "
        f"Proyecto: {title}. Tema: {topic}. Plataforma: {platform}. "
        f"Duración aproximada: {minutes} minutos. Estilo: {style}. "
    )
    body = json.dumps({
        "model": MODEL_NAME,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.7, "num_ctx": 4096}
    }).encode("utf-8")
    request = urllib.request.Request(
        OLLAMA_URL, data=body,
        headers={"Content-Type": "application/json"},
        method="POST"
    )
    with urllib.request.urlopen(request, timeout=600) as response:
        result = json.loads(response.read().decode("utf-8"))
    text = result.get("response", "").strip()
    if not text:
        raise RuntimeError("Ollama respondió sin contenido.")
    return (
        f"TÍTULO: {title}\nESTILO: {style}\nDURACIÓN OBJETIVO: {minutes} minuto(s)\n"
        f"MODELO: {MODEL_NAME} (local)\n\n{text}\n\n"
        "NOTA: Revisa hechos, derechos de autor y adecuación al público antes de aprobar."
    )
