r"""Prueba real del Agente Archivero: UNA llamada a `claude -p` (sonnet) sobre un proyecto FICTICIO creado en una carpeta temporal.

    .venv\Scripts\python.exe pruebas\probar_archivero.py [--salida resultado_archivero.json]

Crea un proyecto con 6 documentos pequeños (md, docx, pptx, txt, sql) y un fichero sin pistas, dos de ellos con una sección «Contactos» y correos y teléfonos
INVENTADOS, y lanza la app con una configuración temporal (sin Knowledge ni proyectos extra reales; planes, sesiones, checks, tipos, caché, bandeja, backlog,
datos y consumo, todo en la carpeta temporal: no toca `datos\`, `cache\` ni OneDrive). Antes de llamar al modelo comprueba, con el mismo código que usa la
app, que el prompt que saldría no lleva ningún dato personal ni línea con pinta de secreto; después lanza el Archivero y comprueba que el resultado tampoco.
Imprime el plan, el resultado y el consumo. Gasta UNA llamada a sonnet. Si `claude` no responde o no hay licencia lo dice tal cual y no lo fuerza.
Resultado (contenido real del modelo sobre datos ficticios) en pruebas\_real\.
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import httpx

AQUI = Path(__file__).resolve().parent
APP = AQUI.parent
REAL = AQUI / "_real"
sys.path.insert(0, str(APP))

PROYECTO = "Proyecto Ficticio Gamma"
CORREOS = ["ana.prueba@ejemplo.test", "luis.demo@ejemplo.test", "marta.ejemplo@ejemplo.test", "pedro.muestra@ejemplo.test"]
TELEFONOS = ["600 123 456", "611222333", "+34 91 123 45 67"]
PERSONAS = ["Ana Prueba", "Luis Demo", "Marta Ejemplo"]      # solo aparecen en secciones «Contactos»: no pueden salir de la máquina
PERSONA_EN_EL_TEXTO = "Pedro Muestra"                         # aparece fuera de «Contactos»: viaja (no hay forma determinista de quitar un nombre), pero el modelo no debe devolverlo
SECRETOS = ["hunter2hunter2", "abc123456789xyz"]


def docx(ruta: Path, parrafos: list[str]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    cuerpo = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in parrafos)
    with zipfile.ZipFile(ruta, "w") as z:
        z.writestr("word/document.xml", f'<?xml version="1.0"?><w:document xmlns:w="x"><w:body>{cuerpo}</w:body></w:document>')


def pptx(ruta: Path, diapositivas: list[list[str]]) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ruta, "w") as z:
        for n, lineas in enumerate(diapositivas, 1):
            z.writestr(f"ppt/slides/slide{n}.xml", "<p:sld>" + "".join(f"<a:p><a:r><a:t>{x}</a:t></a:r></a:p>" for x in lineas) + "</p:sld>")


def texto(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8", newline="\n")


def crear_proyecto(raiz: Path) -> Path:
    p = raiz / PROYECTO
    texto(p / "Oferta y alcance.md",
          "# Oferta y alcance\n\nPortal web para que los comerciales de una cadena hotelera cotizen reservas de grupos.\n\n## Alcance\n- Catálogo de hoteles y salas.\n- Cotizador de grupos "
          "con reglas de cupo.\n- Panel de seguimiento para Revenue.\n\n## Fuera de alcance\n- Integración con el PMS (fase 2).\n\n## Contactos\n- Ana Prueba, ana.prueba@ejemplo.test, 600 123 456\n"
          "- Luis Demo, luis.demo@ejemplo.test, +34 91 123 45 67\n")
    docx(p / "Diseño funcional.docx", ["Diseño funcional del portal de grupos.", "Proceso de cotización: el comercial elige hotel, fechas y número de personas; el sistema aplica el cupo.",
                                      "Si se supera el cupo, la solicitud pasa a Revenue para su aprobación.", "Contactos", "Marta Ejemplo - marta.ejemplo@ejemplo.test - 611222333",
                                      "", "Notificaciones: se avisa por correo al comercial cuando Revenue responde."])
    texto(p / "Modelo de datos.sql", "-- Modelo de datos del portal\nCREATE TABLE hotel (id INT PRIMARY KEY, nombre TEXT, ciudad TEXT);\nCREATE TABLE cotizacion (id INT PRIMARY KEY, hotel_id INT, "
                                      "fecha_entrada DATE, personas INT, estado TEXT);\nCREATE TABLE cupo (hotel_id INT, fecha DATE, plazas INT);\n")
    texto(p / "Plan de sesiones.txt", "Sesión 1 (semana 1): alcance y cupos.\nSesión 2 (semana 3): modelo de datos y catálogo.\nSesión 3 (semana 5): cotizador.\nPiloto: semana 8 con dos hoteles.\n")
    pptx(p / "Kickoff Gamma.pptx", [["Reunión de arranque", "Objetivo: cotizar grupos en minutos, sin correos cruzados"], ["Equipo", "Comercial, Revenue y Administración"]])
    texto(p / "Usuarios y roles.md", "# Usuarios y roles de la solución\n\n- Comercial: crea y consulta sus cotizaciones.\n- Revenue manager: aprueba las que superan el cupo.\n- Administrador: gestiona el catálogo.\n\n"
                                      "Responsable del acceso: Pedro Muestra (pedro.muestra@ejemplo.test)\npassword: hunter2hunter2\nclave de acceso: abc123456789xyz\n")
    docx(p / "Varios" / "Cosas del cliente.docx", ["Notas sueltas sin pista en el nombre ni en la carpeta."])
    return raiz


def prompt_local(raiz: Path) -> tuple[str, dict]:
    """El prompt que saldría, calculado con el mismo código que usa la app (sin llamar a nadie), y el plan."""
    from apuntes import archivero as AR
    from apuntes import inventario as INV
    from apuntes.config import Config
    from apuntes.rutas import Guardian
    cfg = Config(Path(tempfile.mkdtemp(prefix="apuntes_arch_cfg_")) / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    g = Guardian(raiz, raiz.parent / "bandeja", raiz.parent / "cache")
    t = AR.topes(cfg)
    sel = AR.seleccionar(INV.mapa(g, PROYECTO, max_por_tipo=1_000_000), t)
    docs = []
    for f in sel["leer"]:
        docs.append({"i": len(docs) + 1, "nombre": f["nombre"], "tipo": f["tipo"], "texto": AR.preparar_texto(g.leer_para_archivero(PROYECTO, f["ruta"], tope_chars=t["por_documento"] * 4), t["por_documento"])})
    sin = [{**f, "i": n} for n, f in enumerate(sel["sin_clasificar"], 1)]
    return AR.usuario(docs, sin), AR.publico(sel, t)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--salida", default="resultado_archivero.json")
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix="apuntes_arch_"))
    raiz = crear_proyecto(tmp / "proyectos")
    for d in ("planes", "sesiones", "checks", "tipos", "cache", "bandeja", "backlog", "datos"):
        (tmp / d).mkdir()
    (tmp / "config.json").write_text(json.dumps({"knowledge": "", "proyectos_extra": []}), encoding="utf-8")
    res: dict = {"proyecto": PROYECTO}
    # 1. lo que saldría de la máquina, comprobado ANTES de llamar a nadie
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
        e = cli.get(f"/api/proyectos/{PROYECTO}/archivero").json()
        res["plan"], res["resultado_antes"] = e["plan"], e["resultado"]
        print("PLAN leer:", [f["nombre"] for f in e["plan"]["leer"]], "\n     omitidos:", [(o["nombre"], o["motivo"]) for o in e["plan"]["omitidos"]],
              "\n     sin clasificar:", e["plan"]["sin_clasificar"], "| resultado cacheado:", e["resultado"], flush=True)
        r = cli.post(f"/api/proyectos/{PROYECTO}/archivero")
        print("POST archivero ->", r.status_code, flush=True)
        d = r.json()
        res["resultado"] = d
        if r.status_code != 200:
            print("ERROR:", d)
        else:
            print("ORIGEN", d["origen"], "| MODELO", d.get("modelo"), "| LEIDOS", d.get("leidos"), "| TOKENS", d.get("tokens"), "| AVISO", d.get("aviso") or "-", d.get("aviso_detalle") or "")
            for f in d["facetas"]:
                print(f"  [{f['estado']}] {f['titulo']}: {' / '.join(f['sabemos']) or '-'} | fuentes: {', '.join(x['nombre'] for x in f['fuentes']) or '-'} | falta: {' / '.join(f['falta']) or '-'}")
            for x in d["documentos"]:
                print(f"  {x['nombre']} ({x['tipo_titulo']}): {x['resumen']}")
            print("  PROPUESTAS:", [(p["nombre"], p["tipo_titulo"]) for p in d["propuestas"]])
            salida_texto = json.dumps(d, ensure_ascii=False)
            fugas_salida = [x for x in CORREOS + TELEFONOS + PERSONAS + [PERSONA_EN_EL_TEXTO] + SECRETOS if x in salida_texto]
            res["fugas_en_el_resultado"] = fugas_salida
            print("FUGAS en el resultado:", fugas_salida or "ninguna")
            r2 = cli.post(f"/api/proyectos/{PROYECTO}/archivero").json()
            res["segunda_vez_desde_cache"] = r2.get("desde_cache")
            print("Segunda vez desde la caché (sin tokens):", r2.get("desde_cache"))
            v = cli.post(f"/api/proyectos/{PROYECTO}/archivero/guardar", json={"confirmar": False}).json()
            print("Vista previa de guardar:", v["fichero"], "| actualiza:", v["actualiza"], "| carpeta nueva:", v["carpeta_nueva"], "| (no se escribe nada)")
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
    salida = REAL / a.salida
    REAL.mkdir(exist_ok=True)
    salida.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print("GUARDADO", salida)
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
