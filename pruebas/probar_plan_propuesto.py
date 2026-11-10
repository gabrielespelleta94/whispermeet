r"""Prueba real de «Proponer plan» (ola C): UNA llamada a `claude -p` (sonnet) sobre un proyecto FICTICIO creado en una carpeta temporal.

    .venv\Scripts\python.exe pruebas\probar_plan_propuesto.py [--salida RUTA.json]

Crea un proyecto con un documento de arranque y uno de alcance pequeños (con una sección «Contactos» y correos y teléfonos INVENTADOS, una línea con pinta de secreto y
UNA fecha escrita) y lanza la app con una configuración temporal (sin Knowledge ni proyectos extra reales; planes, sesiones, checks, tipos, caché, bandeja, backlog, datos y
consumo, todo en la carpeta temporal: no toca `datos\`, `cache\`, `planes\` ni OneDrive). Antes de llamar al modelo comprueba, con el mismo código que usa la app, que el prompt
que saldría no lleva ningún dato personal ni línea con pinta de secreto; después lanza «Proponer plan» y comprueba que la propuesta tampoco, que no inventa fechas y que NO
escribe nada en la carpeta de planes. Imprime la lista de lo que se leería, la propuesta y el consumo. Gasta UNA llamada a sonnet. Si `claude` no responde o no hay licencia lo dice
tal cual y no lo fuerza. Sin `--salida` no se escribe ningún fichero fuera de la carpeta temporal.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
APP = AQUI.parent
sys.path.insert(0, str(APP))

PROYECTO = "Proyecto Ficticio Gamma"
CORREOS = ["ana.prueba@ejemplo.test", "luis.demo@ejemplo.test"]
TELEFONOS = ["600 123 456", "+34 91 123 45 67"]
PERSONAS = ["Ana Prueba", "Luis Demo"]          # solo aparecen en secciones «Contactos»: no pueden salir de la máquina
SECRETOS = ["hunter2hunter2"]
FECHA_ESCRITA = "2026-12-03"                     # la única fecha de los documentos: cualquier otra que salga en la propuesta es inventada


def texto(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8", newline="\n")


def crear_proyecto(raiz: Path) -> Path:
    p = raiz / PROYECTO
    texto(p / "Kickoff Gamma.md",
          "# Reunión de arranque\n\nProyecto: portal web para que los comerciales de una cadena hotelera cotizen reservas de grupos.\n\n"
          f"Primera sesión de trabajo: {FECHA_ESCRITA} (alcance y cupos). El resto de sesiones se fijarán después.\n\n"
          "Objetivo del proyecto: cotizar un grupo en minutos, sin correos cruzados entre Comercial, Revenue y Administración.\n\n"
          "## Contactos\n- Ana Prueba, ana.prueba@ejemplo.test, 600 123 456\n- Luis Demo, luis.demo@ejemplo.test, +34 91 123 45 67\n\n"
          "Acceso de pruebas\npassword: hunter2hunter2\n")
    texto(p / "Oferta y alcance.md",
          "# Oferta y alcance\n\n## Alcance\n- Catálogo de hoteles y salas.\n- Cotizador de grupos con reglas de cupo.\n- Panel de seguimiento para Revenue.\n\n"
          "## Fuera de alcance\n- Integración con el PMS (fase 2).\n\n## Entregables\n1. Catálogo.\n2. Cotizador.\n3. Panel de Revenue.\n\n"
          "## Hitos\n- Piloto con dos hoteles al terminar el cotizador.\n- Aceptación final tras el piloto.\n")
    return raiz


def prompt_local(raiz: Path) -> tuple[str, dict]:
    """El prompt que saldría, calculado con el mismo código que usa la app (sin llamar a nadie), y la lista previa."""
    from apuntes import archivero as AR
    from apuntes import inventario as INV
    from apuntes import plan_propuesto as PP
    from apuntes.config import Config
    from apuntes.rutas import Guardian
    cfg = Config(Path(tempfile.mkdtemp(prefix="apuntes_plan_cfg_")) / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    g = Guardian(raiz, raiz.parent / "bandeja", raiz.parent / "cache")
    t = PP.topes(cfg)
    sel = PP.seleccionar(INV.mapa(g, PROYECTO, max_por_tipo=1_000_000), t)
    docs, _fuera = AR.leer_documentos(g, PROYECTO, sel, t)
    return PP.usuario(docs, []), PP.publico(sel, t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default=None, help="ruta donde guardar el resultado en JSON (por defecto, no se guarda)")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="apuntes_plan_"))
    raiz = crear_proyecto(tmp / "proyectos")
    for d in ("planes", "sesiones", "checks", "tipos", "cache", "bandeja", "backlog", "datos"):
        (tmp / d).mkdir()
    (tmp / "config.json").write_text(json.dumps({"knowledge": "", "proyectos_extra": []}), encoding="utf-8")
    res: dict = {"proyecto": PROYECTO}
    prompt, plan_local = prompt_local(raiz)
    fugas = [x for x in CORREOS + TELEFONOS + PERSONAS + SECRETOS if x in prompt]
    res["prompt_chars"], res["fugas_en_el_prompt"] = len(prompt), fugas
    print(f"PROMPT {len(prompt)} caracteres; datos personales o secretos que se cuelan: {fugas or 'ninguno'}", flush=True)
    if fugas:
        print("ABORTO: el prompt lleva datos que no deberían salir; no se llama al modelo.")
        shutil.rmtree(tmp, ignore_errors=True)
        return 1
    consumo_log = tmp / "consumo.jsonl"
    proc = subprocess.Popen([sys.executable, str(APP / "app.py"), "--sin-ventana", "--raiz", str(raiz), "--planes", str(tmp / "planes"), "--sesiones", str(tmp / "sesiones"),
                             "--checks", str(tmp / "checks"), "--tipos", str(tmp / "tipos"), "--cache", str(tmp / "cache"), "--bandeja", str(tmp / "bandeja"),
                             "--backlog", str(tmp / "backlog"), "--datos", str(tmp / "datos"), "--consumo", str(consumo_log), "--config", str(tmp / "config.json")],
                            cwd=APP, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    url = None
    for linea in proc.stdout:
        if linea.startswith("APUNTES_URL="):
            url = linea.strip().split("=", 1)[1]
            break
    assert url, "el servidor no arrancó"
    base, token = url.split("/?t=")
    cli = httpx.Client(base_url=base, headers={"X-Token": token}, timeout=600)
    try:
        e = cli.get(f"/api/proyectos/{PROYECTO}/plan/proponer").json()
        res["lista_previa"] = e["plan"]
        print("SE LEERÍA:", [f["nombre"] for f in e["plan"]["leer"]], "| NO:", [(o["nombre"], o["motivo"]) for o in e["plan"]["omitidos"]], "| modelo", e["plan"]["modelo"], flush=True)
        p0 = cli.get(f"/api/proyectos/{PROYECTO}/plan").json()
        print("PLAN antes:", p0["plan"], "| versión", p0["version"], flush=True)
        r = cli.post(f"/api/proyectos/{PROYECTO}/plan/proponer")
        print("POST plan/proponer ->", r.status_code, flush=True)
        d = r.json()
        res["propuesta"] = d
        if r.status_code != 200:
            print("ERROR:", d)
        else:
            print("ORIGEN", d["origen"], "| MODELO", d.get("modelo"), "| LEIDOS", d.get("leidos"), "| TOKENS", d.get("tokens"), "| DESCARTADAS", d.get("descartadas"), "| AVISO", d.get("aviso") or "-", d.get("aviso_detalle") or "")
            for i, s in enumerate(d["sesiones"], 1):
                print(f"  {i}. {s['nombre']} | fecha {s['fecha_iso'] or '-'} {s['hora'] or ''} | tras {s['depende_de'] or '-'} | fuente {s['fuente']['nombre'] if s['fuente'] else '-'}")
                print("     objetivos:", " / ".join(s["objetivos"]))
                print("     checks:", " / ".join(s["checks"]) or "-")
            salida_texto = json.dumps(d, ensure_ascii=False)
            fugas_salida = [x for x in CORREOS + TELEFONOS + PERSONAS + SECRETOS if x in salida_texto]
            fechas = sorted({s["fecha_iso"] for s in d["sesiones"] if s["fecha_iso"]})
            inventadas = [f for f in fechas if f != FECHA_ESCRITA]
            res["fugas_en_la_propuesta"], res["fechas"], res["fechas_inventadas"] = fugas_salida, fechas, inventadas
            print("FUGAS en la propuesta:", fugas_salida or "ninguna", "| FECHAS:", fechas or "ninguna", "| inventadas:", inventadas or "ninguna")
        escrito = sorted(x.name for x in (tmp / "planes").iterdir())
        res["planes_escritos"] = escrito
        print("CARPETA DE PLANES después de proponer:", escrito or "vacía (la propuesta no guarda nada)")
        p1 = cli.get(f"/api/proyectos/{PROYECTO}/plan").json()
        print("PLAN después: ", p1["plan"], "| versión", p1["version"])
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    registros = [json.loads(x) for x in consumo_log.read_text(encoding="utf-8").splitlines()] if consumo_log.exists() else []
    por_tarea: dict = {}
    for reg in registros:
        t = por_tarea.setdefault(reg["tarea"], {"llamadas": 0, "ok": 0, "entrada_con_cache": 0, "salida": 0, "modelos": set()})
        t["llamadas"] += 1
        t["ok"] += bool(reg["ok"])
        for u in reg["uso"]:
            t["entrada_con_cache"] += u["entrada"] + u["cache_creacion"] + u["cache_lectura"]
            t["salida"] += u["salida"]
            t["modelos"].add(u["modelo"])
    res["consumo_por_tarea"] = {k: {**v, "modelos": sorted(v["modelos"])} for k, v in por_tarea.items()}
    print("CONSUMO", json.dumps(res["consumo_por_tarea"], ensure_ascii=False))
    if a.salida:
        Path(a.salida).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print("GUARDADO", a.salida)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
