r"""Prueba real: la transcripción TR2 (ya convertida en pruebas/_real/tr2.txt) contra la copia local del contexto.

    .venv\Scripts\python.exe pruebas\probar_tr2.py [--velocidad 6] [--cadencia 5] [--tope 30] [--proyecto "Planificador TR2 (sin 09 ni 11)"] [--modo equipo|5|10|manual] [--config FICHERO.json] [--salida resultado_tr2.json]

`--proyecto`: la copia con todo el contexto (por defecto) o la copia SIN 09-peticiones y 11-bitacora (se actualizaron después de la reunión);
cada una necesita su plan en pruebas/_real/planes/.

Todo vive en pruebas/_real/ (fuera de git). NO acepta ningún cambio propuesto: los lista. Si los análisis llegan
al tope, para y lo dice. Resultados completos en pruebas/_real/resultado_tr2.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
APP = AQUI.parent
REAL = AQUI / "_real"
PROYECTO = "Planificador TR2 (copia)"
SESION = "TR2"
CONSUMO_LOG = APP / "datos" / "consumo.jsonl"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--velocidad", type=float, default=6.0)
    ap.add_argument("--cadencia", type=int, default=5)
    ap.add_argument("--modo", choices=["equipo", "adaptativo", "5", "10", "manual"], default=None,
                    help="modo de cadencia (por defecto el de --cadencia, es decir, cada 5 min como siempre)")
    ap.add_argument("--tope", type=int, default=60)
    ap.add_argument("--falso", action="store_true", help="modelo FALSO (sin tokens): ensayo del flujo y de los eventos; no sirve para medir consumo")
    ap.add_argument("--config", default=str(REAL / "config_tr2.json"),
                    help="configuración de la prueba (se crea con knowledge vacío si falta): nunca se toca datos/config.json ni se lee Knowledge de OneDrive")
    ap.add_argument("--proyecto", default=PROYECTO)
    ap.add_argument("--salida", default="resultado_tr2.json")
    a = ap.parse_args()
    transcripcion = REAL / "tr2.txt"
    checks_dir = REAL / "checks_equipo"      # checks de ESTA pasada (se parte de cero: ni sugeridos ni marcas de otras pruebas)
    shutil.rmtree(checks_dir, ignore_errors=True)
    extra_vacio = REAL / "extra_vacio"          # sustituye a los proyectos extra de la configuración (que apuntan a OneDrive)
    extra_vacio.mkdir(exist_ok=True)
    cfg_ruta = Path(a.config)
    if not cfg_ruta.exists():
        cfg_ruta.write_text(json.dumps({"knowledge": ""}), encoding="utf-8")
    consumo_log = REAL / "consumo_falso.jsonl" if a.falso else CONSUMO_LOG
    desde = consumo_log.stat().st_size if consumo_log.exists() else 0
    lanzador = [sys.executable, str(AQUI / "servir_modelo_falso.py"), "--retardo", "0.3", "--"] if a.falso else [sys.executable, str(APP / "app.py")]
    proc = subprocess.Popen([*lanzador, "--simular", str(transcripcion), "--velocidad", str(a.velocidad),
                             "--raiz", str(REAL / "proyectos"), "--planes", str(REAL / "planes"), "--sesiones", str(REAL / "sesiones"),
                             "--checks", str(checks_dir), "--config", str(cfg_ruta), *(["--cache", str(REAL / "cache_falso"), "--consumo", str(REAL / "consumo_falso.jsonl")] if a.falso else []), "--extra", f"Carpeta de prueba vacía={extra_vacio}",
                             "--sin-ventana"], cwd=APP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    url = None
    for linea in proc.stdout:
        if linea.startswith("APUNTES_URL="):
            url = linea.strip().split("=", 1)[1]
            break
    assert url, "el servidor no arrancó"
    base, token = url.split("/?t=")
    cli = httpx.Client(base_url=base, headers={"X-Token": token}, timeout=300)
    res: dict = {"historial": [], "omitidos": [], "parada_por_tope": False}
    try:
        lista = cli.get("/api/proyectos").json()["proyectos"]
        p = next(p for p in lista if p["nombre"] == a.proyecto)
        ses = next(s for s in p["plan"]["sesiones"] if s["id"] == SESION)
        print("PLAN", ses["nombre"], len(ses["objetivos"]), "objetivos")
        r = cli.post("/api/sesion/iniciar", json={"proyecto": a.proyecto, "tema": ses["nombre"], "cadencia": a.modo or a.cadencia, "sesion_plan": SESION})
        print("INICIAR", r.status_code)
        sesion_id = r.json()["sesion"]["id"]      # el consumo se suma SOLO de esta sesión: otra instancia que escriba en consumo.jsonl no puede mezclarse
        total = sum(1 for l in transcripcion.read_text(encoding="utf-8").splitlines() if "]" in l and ":" in l and not l.startswith("#"))
        ultimo_n, ultimo_om = 0, None
        while True:
            s = cli.get("/api/sesion").json()
            n = s["analisis"]["n"]
            om = s["analisis"]["ultimo_omitido"]
            if om and om != ultimo_om:
                res["omitidos"].append({"t": s["t"], **om}); ultimo_om = om
            if n != ultimo_n:
                ultimo_n = n
                res["historial"].append({"n": n, "t": s["t"], "tarjetas": len(s["tarjetas"]),
                                         "objetivos": [(o["n"], o["estado"], o["minuto"]) for o in s["objetivos"]]})
                print("ANALISIS", n, "t=", s["t"], "tarjetas", len(s["tarjetas"]), flush=True)
            if s["analisis"]["ultimo_error"]:
                res.setdefault("errores", []).append(s["analisis"]["ultimo_error"])
            if n >= a.tope:
                res["parada_por_tope"] = True
                print("PARADA: tope de análisis alcanzado", n)
                break
            if len(s["segmentos"]) >= total and not s["analisis"]["en_curso"]:
                break
            time.sleep(1)
        # análisis final de lo que quede (equivale a cerrar la reunión)
        if not res["parada_por_tope"] and (a.modo or a.cadencia) != "equipo":
            while cli.get("/api/sesion").json()["analisis"]["en_curso"]:
                time.sleep(1)
            cli.post("/api/sesion/analizar")
            time.sleep(2)
            while cli.get("/api/sesion").json()["analisis"]["en_curso"]:
                time.sleep(1)
        s = cli.get("/api/sesion").json()
        res["modo"] = a.modo or str(a.cadencia)
        res["traza"] = s.get("traza", [])      # una fila por análisis: tramo, motivo de disparo, modelo, tokens
        res["tareas"] = s.get("tareas", [])    # cada llamada real: agente, modelo, tramo, duración, tokens (con el equipo, un turno por perfil)
        res["equipo"] = s.get("equipo")
        res["definiciones"] = (s.get("monitor") or {}).get("definiciones", [])
        res["monitor"] = {"feed": (s.get("monitor") or {}).get("feed", []), "pasadas": (s.get("monitor") or {}).get("pasadas", [])}
        res.update(duracion_s=s["t"], segmentos=len(s["segmentos"]), palabras=sum(len(x["texto"].split()) for x in s["segmentos"]),
                   analisis=s["analisis"]["n"], tarjetas=s["tarjetas"], resumen_acumulado=s["resumen_acumulado"], objetivos=s["objetivos"])
        cli.post("/api/sesion/terminar")
        fin = time.time() + 600
        while time.time() < fin:
            s = cli.get("/api/sesion").json()
            if s["revision"] and s["revision"]["estado"] in ("lista", "error"):
                break
            time.sleep(1)
        rev = s["revision"] or {}
        res["tarjetas_finales"] = s["tarjetas"]
        res["revision"] = {"estado": rev.get("estado"), "error": rev.get("error"), "resumen": rev.get("resumen"), "sin_cambios": rev.get("sin_cambios"),
                           "cambios": [{k: c.get(k) for k in ("id", "fichero", "tipo", "valido", "error", "diff")} for c in rev.get("cambios", [])]}
        print("REVISION", rev.get("estado"), "cambios propuestos:", len(rev.get("cambios", [])), "(NO se aceptan)")
        cli.post("/api/revision/cerrar")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    salida = Path(a.salida)   # un nombre suelto va a pruebas/_real; una ruta (relativa a la app o absoluta) se respeta
    salida = salida if salida.is_absolute() else (APP / salida if salida.parent != Path(".") else REAL / salida)
    por_modelo: dict = {}
    por_tarea: dict = {}
    if consumo_log.exists():
        with open(consumo_log, "rb") as f:
            f.seek(desde)
            for l in f.read().decode("utf-8").splitlines():
                r = json.loads(l)
                if r.get("sesion") != sesion_id:
                    continue
                t = por_tarea.setdefault(r["tarea"], {"llamadas": 0, "ok": 0, "coste": 0.0})
                t["llamadas"] += 1; t["ok"] += bool(r["ok"])
                for u in r["uso"]:
                    m = por_modelo.setdefault(u["modelo"], {"entrada_con_cache": 0, "cache_lectura": 0, "salida": 0, "coste_ref_usd": 0.0, "llamadas": 0})
                    m["llamadas"] += 1
                    m["entrada_con_cache"] += u["entrada"] + u["cache_creacion"] + u["cache_lectura"]
                    m["cache_lectura"] += u["cache_lectura"]
                    m["salida"] += u["salida"]; m["coste_ref_usd"] += u.get("coste_ref_usd") or 0
                    t["coste"] += u.get("coste_ref_usd") or 0
    res["consumo_por_modelo"], res["consumo_por_tarea"] = por_modelo, por_tarea
    salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("CONSUMO", json.dumps(por_modelo), json.dumps(por_tarea))
    print("GUARDADO", salida)
    return 0


if __name__ == "__main__":
    sys.exit(main())
