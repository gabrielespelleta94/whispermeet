"""Mide la salida de haiku en el análisis periódico: prompt antiguo frente al compacto, con y sin MAX_THINKING_TOKENS=0.

    .venv\\Scripts\\python.exe pruebas\\medir_salida_haiku.py [--tramos 3] [--antiguo RUTA_prompts_antiguo.py]

Usa el contexto de la copia de TR2 (pruebas/_real, fuera de git) y 3 tramos de 5 min de la transcripción real: el usuario
autorizó enviarlos a `claude -p` para estas pruebas. Cada caso: salida total, tokens de razonamiento (los que informa el CLI)
y caracteres del JSON. Resultado en pruebas/_real/resultado_salida_haiku.json.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
APP = AQUI.parent
sys.path.insert(0, str(APP))
from apuntes import planes as PL  # noqa: E402
from apuntes.analisis import claude_cli as C, prompts as P  # noqa: E402
from apuntes.config import CLAUDE_CWD  # noqa: E402
from apuntes.simulador import cargar  # noqa: E402
from apuntes.texto import formatear_lineas, limpiar_transcripcion  # noqa: E402

REAL = AQUI / "_real"


def cargar_antiguo(ruta: Path):
    import apuntes.analisis  # noqa: F401  (el paquete debe estar importado para los imports relativos)
    spec = importlib.util.spec_from_file_location("apuntes.analisis.prompts_antiguo", ruta)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def digest_de_cache() -> str:
    mejor = ""
    for f in sorted((APP / "cache").glob("digest-*tr2*.json"), key=lambda p: p.stat().st_mtime):
        try:
            mejor = json.loads(f.read_text(encoding="utf-8"))["digest"]
        except (OSError, ValueError, KeyError):
            pass
    return mejor


def llamar(sistema: str, usuario: str, sin_razonamiento: bool) -> dict:
    cmd = C.construir_comando(C.ClaudeCLI().exe, sistema, "haiku", "low")
    p = subprocess.run(cmd, input=usuario, capture_output=True, text=True, encoding="utf-8", cwd=str(CLAUDE_CWD),
                       env=C.entorno_limpio(sin_razonamiento=sin_razonamiento), timeout=300)
    d = json.loads(p.stdout)
    u = d["usage"]
    return {"salida": u["output_tokens"], "razonamiento": (u.get("output_tokens_details") or {}).get("thinking_tokens"),
            "chars": len(d["result"]), "ms": d["duration_ms"], "ok_json": P.extraer_json(d["result"]) is not None,
            "resultado": d["result"]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tramos", type=int, default=3)
    ap.add_argument("--antiguo", default=str(REAL / "prompts_antes.py"))
    a = ap.parse_args()
    CLAUDE_CWD.mkdir(parents=True, exist_ok=True)
    antiguo = cargar_antiguo(Path(a.antiguo))
    lineas = cargar(REAL / "tr2.txt")
    digest = digest_de_cache()
    assert digest, "falta el digest de TR2 en cache/ (haz antes una pasada o genera el digest)"
    objetivos = PL.objetivos_iniciales({"objetivos": ["Recorrer los bloques de cálculo y los cuatro estados", "Matrices mes por día de semana, cupos, MLOS, comisión e IVA",
                                                       "Tipología con suplementos o tarifario propio", "Estrategia inicial por hotel", "Inventario fuera de alcance"]})
    tramos = []
    for ini in (600, 1800, 3000, 3900)[: a.tramos]:
        tramos.append(formatear_lineas(limpiar_transcripcion([l for l in lineas if ini <= l.t < ini + 300])))
    casos = {"antiguo + MAX_THINKING_TOKENS=0": (antiguo, True), "antiguo sin la variable": (antiguo, False),
             "compacto + MAX_THINKING_TOKENS=0": (P, True), "compacto sin la variable": (P, False)}
    res: dict = {}
    for nombre, (mod, sin) in casos.items():
        filas = []
        for tr in tramos:
            sistema = mod.sistema_periodico(2500, True)
            usuario = mod.usuario_periodico(digest, "", [], "", tr, PL.bloque_prompt(objetivos))
            r = llamar(sistema, usuario, sin)
            filas.append({k: v for k, v in r.items() if k != "resultado"})
            filas[-1]["resultado"] = r["resultado"][:1500]
            print(f"{nombre:36} salida={r['salida']:>5} razonamiento={r['razonamiento']} chars={r['chars']:>5} json_ok={r['ok_json']}", flush=True)
        res[nombre] = filas
        medias = {k: round(sum(f[k] or 0 for f in filas) / len(filas)) for k in ("salida", "razonamiento", "chars")}
        print("  MEDIA", nombre, medias, flush=True)
    (REAL / "resultado_salida_haiku.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
