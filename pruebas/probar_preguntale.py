r"""Prueba real de «Pregúntale»: 3 preguntas con `claude -p` (haiku) sobre la reunión FICTICIA, con el proyecto ficticio copiado a una
carpeta temporal (no escribe en pruebas\proyectos ni toca OneDrive).

    .venv\Scripts\python.exe pruebas\probar_preguntale.py [--velocidad 40] [--salida resultado_preguntale.json]

Gasta en total: 1 llamada de digest (haiku, ficticio) y 3 de consulta (haiku). La cadencia es «manual»: no hay análisis periódicos
ni resumen final. Resultado (con contenido real del modelo sobre datos ficticios) en pruebas\_real\.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
APP = AQUI.parent
REAL = AQUI / "_real"
PROYECTO = "Proyecto Ficticio Alfa"
PREGUNTAS = [
    ("¿Qué se acordó sobre la fecha del piloto?", "haiku"),                      # no nombra ningún fichero
    ("¿Qué dice el alcance sobre la integración con SAP?", "haiku"),             # nombra 02-alcance.md: viajan extractos
    ("¿Cuál es el presupuesto total del proyecto en euros?", "haiku"),           # no está en los datos: debe decirlo
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--velocidad", type=float, default=40.0)
    ap.add_argument("--salida", default="resultado_preguntale.json")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="apuntes_preg_"))
    shutil.copytree(AQUI / "proyectos", tmp / "proyectos")
    for d in ("planes", "sesiones", "checks"):
        (tmp / d).mkdir()
    (tmp / "config.json").write_text("{}", encoding="utf-8")
    transcripcion = AQUI / "reunion-ficticia.txt"
    proc = subprocess.Popen([sys.executable, str(APP / "app.py"), "--simular", str(transcripcion), "--velocidad", str(a.velocidad), "--sin-ventana",
                             "--raiz", str(tmp / "proyectos"), "--planes", str(tmp / "planes"), "--sesiones", str(tmp / "sesiones"),
                             "--checks", str(tmp / "checks"), "--config", str(tmp / "config.json"), "--extra", f"Nada={tmp}"],
                            cwd=APP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    url = None
    for linea in proc.stdout:
        if linea.startswith("APUNTES_URL="):
            url = linea.strip().split("=", 1)[1]
            break
    assert url, "el servidor no arrancó"
    base, token = url.split("/?t=")
    cli = httpx.Client(base_url=base, headers={"X-Token": token}, timeout=300)
    res: dict = {"proyecto": PROYECTO, "preguntas": []}
    try:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento portal Alfa", "cadencia": "manual"})
        assert r.status_code == 200, r.text
        total = sum(1 for l in transcripcion.read_text(encoding="utf-8").splitlines() if l.startswith("["))
        fin = time.time() + 120
        while time.time() < fin:
            s = cli.get("/api/sesion").json()
            if len(s["segmentos"]) >= total and s["digest"]["origen"] in ("generado", "cache", "error"):
                break
            time.sleep(1)
        res["digest"] = s["digest"]
        res["analisis_automaticos"] = s["analisis"]["n"]            # debe ser 0: la cadencia es «manual»
        for pregunta, modelo in PREGUNTAS:
            t0 = time.time()
            q = cli.post("/api/sesion/consultar", json={"pregunta": pregunta, "modelo": modelo}).json()
            q["segundos"] = round(time.time() - t0, 1)
            res["preguntas"].append(q)
            print("P:", pregunta, "\nR:", q.get("respuesta") or q.get("error"), "| citas", q.get("citas"), "| base", q.get("base"), "| tokens", q.get("tokens"), flush=True)
        s = cli.get("/api/sesion").json()
        res["consumo"] = s["consumo"]
        res["traza_tareas"] = [{k: t.get(k) for k in ("agente", "modelo", "ms", "tokens", "estado")} for t in s["tareas"] if t.get("agente") in ("consultas", "contexto")]
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        shutil.rmtree(tmp, ignore_errors=True)
    (REAL / a.salida).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("GUARDADO", REAL / a.salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
