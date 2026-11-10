"""Implementación por `claude -p` (Claude Code con la licencia del usuario).

Cada llamada arranca limpia: sin herramientas, MCP, hooks, plugins, CLAUDE.md ni memoria, sin slash
commands, sin persistir sesión, con system prompt propio y cwd neutro. No se usa `--bare` porque
exige ANTHROPIC_API_KEY e ignora el login (se comprobó: devuelve «Not logged in»).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time

from . import ErrorAnalisis, ModeloLLM, Respuesta, Uso
from ..config import CLAUDE_CWD

# Variables que harían facturar por API (o cambiarían de proveedor): se quitan SIEMPRE del subproceso.
ENV_PROHIBIDAS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK",
                  "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY")

_RE_SESION = re.compile(r"not logged in|/login|please log ?in|invalid (api key|authentication)|authentication[_ ]error|oauth token", re.I)
_RE_LIMITE = re.compile(r"(usage|rate|plan|session|weekly|5-hour|daily|monthly) limit|limit (reached|exceeded)|reached your|out of (extra )?usage|quota|limit will reset|resets? (at|in)", re.I)


def entorno_limpio(base: dict | None = None, sin_razonamiento: bool = False) -> dict:
    env = dict(os.environ if base is None else base)
    if sin_razonamiento:  # medido: quita ~500 tokens de salida por llamada en haiku
        env["MAX_THINKING_TOKENS"] = "0"
    for k in list(env):
        if k.upper() in ENV_PROHIBIDAS:
            env.pop(k, None)
    return env


def localizar_claude(buscar=None) -> str | None:
    """Ruta del ejecutable `claude` en el PATH (o None). Un solo sitio: lo usan las llamadas y la comprobación de requisitos. No ejecuta nada."""
    return (buscar or shutil.which)("claude")


def construir_comando(exe: str, sistema: str, modelo: str, esfuerzo: str = "", web: bool = False) -> list[str]:
    herramientas = ["--tools", "WebSearch", "--allowedTools", "WebSearch"] if web else ["--tools", ""]   # web: SOLO la búsqueda, y solo si el usuario la pidió
    cmd = [exe, "-p", "--output-format", "json", "--model", modelo,
           *herramientas,                 # ninguna herramienta (salvo la búsqueda web de «Profundizar», marcada por el usuario)
           "--strict-mcp-config",         # sin MCP (no se pasa --mcp-config)
           "--setting-sources", "",       # sin settings de usuario/proyecto: ni hooks, ni plugins, ni CLAUDE.md
           "--disable-slash-commands",    # sin skills
           "--no-session-persistence",    # no deja sesión en disco
           "--system-prompt", sistema]
    if esfuerzo:
        cmd += ["--effort", esfuerzo]
    return cmd


_CAPACIDAD_WEB: dict = {}


def capacidad_web(exe: str | None = None, forzar: bool = False) -> tuple[bool, str]:
    """¿Admite esta versión de `claude -p` habilitar SOLO la búsqueda web? Se mira en `claude --help` (sin gastar tokens): hacen falta `--tools` (elegir
    herramientas del conjunto interno) y `--allowedTools` (permitirla sin preguntar en modo no interactivo). Se calcula una vez y se recuerda.
    -> (disponible, motivo)."""
    if _CAPACIDAD_WEB and not forzar:
        return _CAPACIDAD_WEB["r"]
    exe = exe or localizar_claude() or "claude"
    try:
        p = subprocess.run([exe, "--help"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=20,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        ayuda = (p.stdout or "") + (p.stderr or "")
    except (OSError, subprocess.TimeoutExpired):
        r = (False, "No se pudo consultar `claude --help`: la búsqueda web no se ofrece.")
    else:
        ok = "--tools" in ayuda and ("--allowedTools" in ayuda or "--allowed-tools" in ayuda)
        r = (True, "") if ok else (False, "Esta versión de `claude -p` no permite habilitar solo la búsqueda web (faltan --tools o --allowedTools).")
    _CAPACIDAD_WEB["r"] = r
    return r


def clasificar_error(texto: str, stderr: str = "") -> ErrorAnalisis:
    t = f"{texto or ''}\n{stderr or ''}"
    if _RE_SESION.search(t):
        return ErrorAnalisis("sesion", "Claude Code no tiene la sesión iniciada. Abre una terminal, ejecuta «claude» "
                             "y usa /login con tu licencia. La grabación y la transcripción continúan.")
    if _RE_LIMITE.search(t):
        return ErrorAnalisis("limite", "Has alcanzado el límite de uso de tu plan de Claude. Los análisis se pausan "
                             "hasta que se restablezca; pulsa «Analizar ahora» para reintentar. "
                             "La grabación y la transcripción continúan.")
    resumen = re.sub(r"\s+", " ", (texto or stderr or "error desconocido")).strip()[:200]
    return ErrorAnalisis("otro", f"El análisis falló: {resumen}", transitorio=True)


def extraer_uso(d: dict, modelo_pedido: str) -> list[Uso]:
    out = []
    mu = d.get("modelUsage")
    if isinstance(mu, dict) and mu:
        for nombre, u in mu.items():
            out.append(Uso(nombre, int(u.get("inputTokens", 0)), int(u.get("outputTokens", 0)),
                           int(u.get("cacheCreationInputTokens", 0)), int(u.get("cacheReadInputTokens", 0)),
                           float(u.get("costUSD", 0) or 0)))
    if not out and isinstance(d.get("usage"), dict):
        u = d["usage"]
        out.append(Uso(modelo_pedido, int(u.get("input_tokens", 0)), int(u.get("output_tokens", 0)),
                       int(u.get("cache_creation_input_tokens", 0)), int(u.get("cache_read_input_tokens", 0)),
                       float(d.get("total_cost_usd", 0) or 0)))
    det = (d.get("usage") or {}).get("output_tokens_details") if isinstance(d.get("usage"), dict) else None
    if out and len(out) == 1 and isinstance(det, dict):
        out[0].razonamiento = int(det.get("thinking_tokens") or 0)
    return out


def interpretar_salida(stdout: str, stderr: str, codigo: int, modelo: str) -> Respuesta:
    try:
        d = json.loads(stdout)
    except ValueError:
        raise clasificar_error(stdout[:300], stderr) if (stdout or stderr) else ErrorAnalisis(
            "salida", "Claude Code no devolvió nada.", transitorio=True)
    if not isinstance(d, dict):
        raise ErrorAnalisis("salida", "Respuesta de Claude Code inesperada.", transitorio=True)
    resultado = d.get("result") if isinstance(d.get("result"), str) else ""
    if d.get("is_error") or codigo != 0:
        raise clasificar_error(resultado, stderr)
    return Respuesta(texto=resultado, uso=extraer_uso(d, modelo), ms=int(d.get("duration_ms") or 0))


def _flags_creacion() -> int:
    """Sin ventana y, en Windows, con prioridad por debajo de lo normal: `claude -p` cede CPU a Whisper (fuera de Windows, 0)."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "BELOW_NORMAL_PRIORITY_CLASS", 0)


class ClaudeCLI(ModeloLLM):
    def __init__(self, exe: str | None = None):
        self.exe = exe or localizar_claude() or "claude"

    def completar(self, sistema: str, usuario: str, modelo: str, esfuerzo: str = "", timeout_s: int = 240,
                  sin_razonamiento: bool = False, web: bool = False) -> Respuesta:
        CLAUDE_CWD.mkdir(parents=True, exist_ok=True)
        cmd = construir_comando(self.exe, sistema, modelo, esfuerzo, web)
        t0 = time.time()
        try:
            p = subprocess.run(cmd, input=usuario, capture_output=True, text=True, encoding="utf-8",
                               timeout=timeout_s, cwd=str(CLAUDE_CWD), env=entorno_limpio(sin_razonamiento=sin_razonamiento),
                               creationflags=_flags_creacion())
        except subprocess.TimeoutExpired:
            raise ErrorAnalisis("tiempo", f"Claude Code no respondió en {timeout_s} s.", transitorio=True)
        except FileNotFoundError:
            raise ErrorAnalisis("otro", "No se encuentra el comando «claude» en el PATH.")
        r = interpretar_salida(p.stdout, p.stderr, p.returncode, modelo)
        if not r.ms:
            r.ms = int((time.time() - t0) * 1000)
        return r
