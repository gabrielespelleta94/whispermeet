"""Mide cuántos tokens de salida de haiku son razonamiento y qué ajuste los quita de verdad (prompt periódico compacto).

    .venv\\Scripts\\python.exe pruebas\\probar_thinking.py [--real] [--reps 3]

Sin `--real` usa la reunión ficticia (tramo de 10 min). Con `--real` usa un tramo de 5 min de TR2 y su digest (pruebas/_real, fuera de git).
Variantes: la variable MAX_THINKING_TOKENS=0 sola (lo que había), + CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1, + --settings con
alwaysThinkingEnabled=false, todo junto y una directiva «sin razonamiento» en el prompt. Imprime salida total, tokens de razonamiento y caracteres del JSON por llamada.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from apuntes.analisis import claude_cli as C, prompts as P  # noqa: E402
from apuntes.config import CLAUDE_CWD  # noqa: E402
from apuntes.simulador import cargar  # noqa: E402
from apuntes.texto import formatear_lineas, limpiar_transcripcion  # noqa: E402

AQUI = Path(__file__).resolve().parent
ap = argparse.ArgumentParser()
ap.add_argument("--real", action="store_true")
ap.add_argument("--reps", type=int, default=3)
ap.add_argument("--solo", default="", help="solo las variantes cuyo nombre contenga este texto")
a = ap.parse_args()
if a.real:
    lineas = cargar(AQUI / "_real" / "tr2.txt")
    nuevo = formatear_lineas(limpiar_transcripcion([l for l in lineas if 1800 <= l.t < 2100]))
    cache = sorted((AQUI.parent / "cache").glob("digest-*tr2*.json"), key=lambda p: p.stat().st_mtime)
    digest = json.loads(cache[-1].read_text(encoding="utf-8"))["digest"] if cache else "(sin digest)"
else:
    nuevo = formatear_lineas(limpiar_transcripcion([l for l in cargar(AQUI / "reunion-ficticia.txt") if l.t < 600]))
    digest = "[02-alcance.md] No entra: SAP (fase 2). [04] Piloto 20/01."
from apuntes import planes as PL  # noqa: E402
OBJ = PL.objetivos_iniciales({"objetivos": ["Recorrer los bloques de cálculo y los cuatro estados", "Matrices mes por día de semana, cupos, MLOS, comisión e IVA",
                                            "Tipología con suplementos o tarifario propio", "Estrategia inicial por hotel", "Inventario fuera de alcance"]})
# con --real el prompt es el de una reunión con plan (objetivos + títulos ya emitidos), que es donde más razona haiku
sistema = P.sistema_periodico(2500, a.real)
usuario = P.usuario_periodico(digest, "", ["[03:19] decisión: ejemplo de tarjeta ya emitida"] if a.real else [], "", nuevo, PL.bloque_prompt(OBJ) if a.real else "")
exe = C.ClaudeCLI().exe
SIN_ADAPT = {"CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1"}
AJUSTES = ["--settings", json.dumps({"alwaysThinkingEnabled": False})]
DIRECTIVA = "\nResponde directamente con el JSON: sin razonamiento previo, sin borradores ni comprobaciones."
variantes = {
    "MAX_THINKING_TOKENS=0 (lo que había)": ([], {"MAX_THINKING_TOKENS": "0"}),
    "+ DISABLE_ADAPTIVE_THINKING=1": ([], {"MAX_THINKING_TOKENS": "0", **SIN_ADAPT}),
    "+ --settings alwaysThinkingEnabled=false": (AJUSTES, {"MAX_THINKING_TOKENS": "0"}),
    "las tres cosas": (AJUSTES, {"MAX_THINKING_TOKENS": "0", **SIN_ADAPT}),
    "las tres + directiva «sin razonamiento» en el prompt": (AJUSTES, {"MAX_THINKING_TOKENS": "0", **SIN_ADAPT, "_DIRECTIVA": "1"}),
    "solo la directiva (MAX_THINKING_TOKENS=0 + prompt)": ([], {"MAX_THINKING_TOKENS": "0", "_DIRECTIVA": "1"}),
}
CLAUDE_CWD.mkdir(parents=True, exist_ok=True)
for nombre, (extra, env) in variantes.items():
    if a.solo and a.solo not in nombre:
        continue
    medias = []
    for _ in range(a.reps):
        env = dict(env)
        sis = sistema + DIRECTIVA if env.pop("_DIRECTIVA", None) else sistema
        cmd = C.construir_comando(exe, sis, "haiku", "low") + extra
        e = C.entorno_limpio()
        e.update(env)
        p = subprocess.run(cmd, input=usuario, capture_output=True, text=True, encoding="utf-8", cwd=str(CLAUDE_CWD), env=e, timeout=300)
        d = json.loads(p.stdout)
        u = d["usage"]
        raz = (u.get("output_tokens_details") or {}).get("thinking_tokens")
        medias.append((u["output_tokens"], raz or 0))
        print(f"{nombre:44} salida={u['output_tokens']:>5} razonamiento={raz}  json_ok={d['result'].strip().startswith('{')} chars={len(d['result'])} ms={d['duration_ms']}", flush=True)
    print(f"  MEDIA: salida={sum(m[0] for m in medias) / len(medias):.0f} razonamiento={sum(m[1] for m in medias) / len(medias):.0f}", flush=True)
