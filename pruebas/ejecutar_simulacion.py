"""Recorre toda la app en modo --simular contra un proyecto ficticio (copia en pruebas/salida/).

    .venv\\Scripts\\python.exe pruebas\\ejecutar_simulacion.py [transcripcion.txt] [--cadencia 5|10|equipo] [--velocidad N] [--no-aplicar]
    .venv\\Scripts\\python.exe pruebas\\ejecutar_simulacion.py --compartido --sesion-plan S1     # proyecto compartido + plan
    .venv\\Scripts\\python.exe pruebas\\ejecutar_simulacion.py --compartido --sesion-plan otra   # mismo, sin objetivos

Usa `claude -p` de verdad (con la transcripción ficticia). No toca ningún proyecto real: el «compartido» es una
copia ficticia dentro de pruebas/salida/ y su transcripción va a pruebas/salida/sesiones/.
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
SALIDA = AQUI / "salida"
PROYECTO = "Proyecto Ficticio Alfa"
PROYECTO_COMPARTIDO = "Proyecto Compartido Beta"
CONSUMO_LOG = APP / "datos" / "consumo.jsonl"


def tabla_consumo(desde: int) -> dict:
    """Agrupa por tarea las llamadas registradas en consumo.jsonl desde el desplazamiento `desde`."""
    out: dict[str, dict] = {}
    if not CONSUMO_LOG.exists():
        return out
    with open(CONSUMO_LOG, "rb") as f:
        f.seek(desde)
        lineas = f.read().decode("utf-8").splitlines()
    for l in lineas:
        r = json.loads(l)
        t = out.setdefault(r["tarea"], {"llamadas": 0, "entrada": 0, "salida": 0})
        t["llamadas"] += 1
        for u in r["uso"]:
            t["entrada"] += u["entrada"] + u["cache_creacion"] + u["cache_lectura"]
            t["salida"] += u["salida"]
    out["TOTAL"] = {k: sum(v[k] for t, v in out.items()) for k in ("llamadas", "entrada", "salida")}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcripcion", nargs="?")
    ap.add_argument("--cadencia", default="5", help="5 | 10 | equipo | manual")
    ap.add_argument("--velocidad", type=float, default=30.0)
    ap.add_argument("--no-aplicar", action="store_true")
    ap.add_argument("--compartido", action="store_true", help="usa el proyecto compartido ficticio y su plan de sesiones")
    ap.add_argument("--sesion-plan", default=None, help="id de la sesión del plan (con --compartido)")
    ap.add_argument("--pulir", action="store_true", help="pulsa «Pulir con Opus» en la revisión (UNA llamada a opus; mide su consumo)")
    ap.add_argument("--no-publicar", action="store_true", help="con --compartido: elige «No publicar» en la revisión (02. Sesiones no debe crearse)")
    a = ap.parse_args()
    if a.compartido and not a.sesion_plan:
        a.sesion_plan = "S1"
    transcripcion = a.transcripcion or str(AQUI / ("reunion-datos-beta.txt" if a.compartido else "reunion-ficticia.txt"))
    fallos: list[str] = []

    def chequeo(nombre: str, ok: bool, detalle: str = "") -> None:
        print("CHEQUEO", "OK " if ok else "FALLA", nombre, detalle)
        if not ok:
            fallos.append(nombre)

    if SALIDA.exists():
        shutil.rmtree(SALIDA)
    shutil.copytree(AQUI / "proyectos", SALIDA / "proyectos")
    raiz = SALIDA / "proyectos"
    argumentos = []
    if a.compartido:
        shutil.copytree(AQUI / "compartidos", SALIDA / "compartidos")
        shutil.copytree(AQUI / "planes-beta", SALIDA / "planes")
        proyecto = PROYECTO_COMPARTIDO
        carpeta_proyecto = SALIDA / "compartidos" / PROYECTO_COMPARTIDO
        argumentos = ["--extra", f"{PROYECTO_COMPARTIDO}={carpeta_proyecto}", "--planes", str(SALIDA / "planes"),
                      "--sesiones", str(SALIDA / "sesiones"), "--checks", str(SALIDA / "checks")]
    else:
        proyecto = PROYECTO
        carpeta_proyecto = raiz / PROYECTO
    (SALIDA / "config.json").write_text(json.dumps({"knowledge": ""}), encoding="utf-8")     # nunca el Knowledge de OneDrive en una prueba
    (SALIDA / "extra_vacio").mkdir(exist_ok=True)
    argumentos += ["--config", str(SALIDA / "config.json"), "--cache", str(SALIDA / "cache")]
    if not a.compartido:
        argumentos += ["--extra", f"Carpeta de prueba vacía={SALIDA / 'extra_vacio'}"]     # sustituye a los proyectos extra (OneDrive) de la configuración
    ctx = carpeta_proyecto / "00. CONTEXTO (IA)"
    alcance_antes = (ctx / "02-alcance.md").read_text(encoding="utf-8")
    consumo_desde = CONSUMO_LOG.stat().st_size if CONSUMO_LOG.exists() else 0

    proc = subprocess.Popen([sys.executable, str(APP / "app.py"), "--simular", transcripcion, "--velocidad", str(a.velocidad),
                             "--raiz", str(raiz), "--sin-ventana", *argumentos], cwd=APP, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8")
    url = None
    for linea in proc.stdout:
        if linea.startswith("APUNTES_URL="):
            url = linea.strip().split("=", 1)[1]
            break
    assert url, "el servidor no arrancó"
    base, token = url.split("/?t=")
    cli = httpx.Client(base_url=base, headers={"X-Token": token}, timeout=300)

    def esperar(cond, t=900, paso=1.0):
        fin = time.time() + t
        while time.time() < fin:
            s = cli.get("/api/sesion").json()
            if cond(s):
                return s
            time.sleep(paso)
        raise TimeoutError("tiempo agotado")

    try:
        print("INFO", {k: v for k, v in cli.get("/api/info").json().items() if k in ("version", "simulacion")})
        lista = cli.get("/api/proyectos").json()["proyectos"]
        print("PROYECTOS", [(p["nombre"], "compartida" if p["compartido"] else "", "plan" if p["plan"] else "") for p in lista])
        cuerpo = {"proyecto": proyecto, "tema": "Seguimiento portal Alfa", "cadencia": a.cadencia}
        if a.compartido:
            p = next(p for p in lista if p["nombre"] == proyecto)
            chequeo("el proyecto compartido sale marcado y con plan", p["compartido"] and p["plan"] is not None)
            ses = next(s for s in p["plan"]["sesiones"] if s["id"] == a.sesion_plan)
            print("ELEGIR_SESION", ses["id"], ses["nombre"], "| objetivos:", len(ses["objetivos"]), "| prioritario:", ses["fichero_prioritario"])
            cuerpo.update(tema=ses["nombre"], sesion_plan=ses["id"])  # la interfaz rellena el tema con el de la sesión
        usar_checks = a.compartido and a.sesion_plan not in (None, "otra")
        cb = {"proyecto": proyecto, "sesion": a.sesion_plan}
        if usar_checks:
            lista = cli.get("/api/checks", params=cb).json()["checks"]
            print("CHECKS_BASE", [(c["origen"], c["texto"]) for c in lista])
            chequeo("hay checks base del plan antes de empezar", sum(c["origen"] == "plan" for c in lista) >= 4)
            # el usuario bloquea a mano ANTES de la reunión: marca y desmarca «Las cuatro tablas» (el modelo debería marcarlo, pero no puede)
            bloqueado = next(c for c in lista if c["texto"].startswith("Las cuatro tablas"))
            cli.put(f"/api/checks/{bloqueado['id']}", json={**cb, "hecho": True})
            cli.put(f"/api/checks/{bloqueado['id']}", json={**cb, "hecho": False})
            # y marca a mano otro que el modelo no debe tocar
            manual = next(c for c in lista if c["texto"].startswith("Precios por tipolog"))
            cli.put(f"/api/checks/{manual['id']}", json={**cb, "hecho": True})
        r = cli.post("/api/sesion/iniciar", json=cuerpo)
        print("INICIAR", r.status_code, r.json().get("sesion"))
        if a.compartido:
            print("OBJETIVOS_INICIALES", [(o["n"], o["estado"]) for o in r.json()["objetivos"]])
        if usar_checks:
            esperar(lambda s: s["digest"]["origen"] in ("generado", "cache", "error", "vacio"))
            lista = cli.get("/api/checks", params=cb).json()["checks"]
            sug = [c for c in lista if c["origen"] == "sugerido"]
            print("CHECKS_SUGERIDOS", [c["texto"] for c in sug])
            chequeo("el digest ha traído checks sugeridos (máx. 8)", 0 < len(sug) <= 8, f"{len(sug)} sugeridos")
        total = sum(1 for l in Path(transcripcion).read_text(encoding="utf-8").splitlines() if "]" in l and ":" in l and not l.startswith("#"))
        s = esperar(lambda s: len(s["segmentos"]) >= total)
        print("SEGMENTOS", len(s["segmentos"]), "t=", s["t"], "analisis_hechos=", s["analisis"]["n"], "digest=", s["digest"])
        print("OBJETIVOS_TRAS_PERIODICOS", [(o["n"], o["estado"], o["minuto"]) for o in s["objetivos"]])
        s = esperar(lambda s: not s["analisis"]["en_curso"])
        print("ANALISIS_MANUAL", cli.post("/api/sesion/analizar").json())
        s = esperar(lambda s: not s["analisis"]["en_curso"])
        print("TARJETAS", len(s["tarjetas"]))
        for t in s["tarjetas"]:
            print("   ", t["categoria"], t["minuto"], "|", t["texto"], "|", t.get("responsable", ""), "|", t.get("referencia", ""))
        print("RESUMEN_ACUM", s["resumen_acumulado"][:300])
        for o in s["objetivos"]:
            print("   OBJETIVO", o["n"], o["estado"], o["minuto"] or "--:--", "|", o["texto"])
        if a.compartido and a.sesion_plan != "otra":
            chequeo("hay objetivos con estado actualizado y minuto citado",
                    any(o["estado"] != "sin_tratar" and o["minuto"] for o in s["objetivos"]))
        if a.compartido and a.sesion_plan == "otra":
            chequeo("sin plan no hay objetivos", s["objetivos"] == [])
        if usar_checks:
            lista = cli.get("/api/checks", params=cb).json()["checks"]
            for c in lista:
                print("   CHECK", c["origen"], c["estado"], "auto" if c["auto"] else ("bloqueado" if c["bloqueado"] else ""), c["minuto"] or "--:--", "|", c["texto"], "|", c["cita"])
            autos = [c for c in lista if c["auto"]]
            chequeo("el modelo marcó al menos un check automático con minuto y cita", bool(autos) and all(c["minuto"] and c["cita"] for c in autos),
                    f"{len(autos)} automáticos")
            chequeo("las citas tienen como máximo 15 palabras", all(len(c["cita"].rstrip("…").split()) <= 15 for c in autos))
            b = next(c for c in lista if c["id"] == bloqueado["id"])
            chequeo("el check bloqueado a mano sigue abierto y no automático", b["estado"] == "abierto" and b["bloqueado"] and not b["auto"])
            m = next(c for c in lista if c["id"] == manual["id"])
            chequeo("el check marcado a mano sigue hecho y no automático", m["estado"] == "hecho" and m["bloqueado"] and not m["auto"])
        print("TERMINAR", cli.post("/api/sesion/terminar").json())
        s = esperar(lambda s: s["revision"] and s["revision"]["estado"] in ("lista", "error"))
        rev = s["revision"]
        print("REVISION", rev["estado"], rev.get("error"), "| compartido:", rev["compartido"], "|", rev["destino_contexto"])
        print("RESUMEN_FINAL", rev["resumen"][:1500])
        if a.pulir:
            r = cli.post("/api/revision/pulir").json()
            pu = cli.get("/api/sesion").json()["revision"]["pulido"]
            print("PULIDO", r, "| estado:", pu["estado"], "|", pu["error"])
            print("PULIDO_TEXTO", pu["resumen"][:1500])
            chequeo("el pulido con Opus devolvió una versión y no sustituyó a la de Sonnet", pu["estado"] == "listo" and pu["elegida"] == "sonnet"
                    and cli.get("/api/sesion").json()["revision"]["resumen"] == rev["resumen"])
        if a.compartido and a.sesion_plan != "otra":
            chequeo("el resumen final incluye los objetivos cumplidos y pendientes", "Objetivos de la sesión" in rev["resumen"]
                    and "pendientes" in rev["resumen"].lower())
        if usar_checks:
            chequeo("el resumen final lista los checks (hechos y pendientes)", "Checks de la sesión" in rev["resumen"] and "**Hechos**" in rev["resumen"]
                    and "**Pendientes**" in rev["resumen"])
            chequeo("el resumen final refleja el automático y el bloqueado", "(automático, minuto" in rev["resumen"] and "Las cuatro tablas" in rev["resumen"]
                    and "(desmarcado a mano)" in rev["resumen"] and "(a mano)" in rev["resumen"])
        if a.compartido:
            pub = rev["publicacion"]
            print("PUBLICACION_PREVISTA", pub)
            chequeo("la revisión avisa del destino en la carpeta compartida", pub["aplica"] and pub["publicar"] and "02. Sesiones" in pub["destino"])
            chequeo("antes de cerrar, 02. Sesiones aún NO existe", not (carpeta_proyecto / "02. Sesiones (transcripciones)").exists())
            chequeo("la revisión avisa de carpeta compartida", rev["compartido"] is True and "Compartido Beta" in rev["destino_contexto"])
        for c in rev["cambios"]:
            print("CAMBIO", c["id"], c["fichero"], c["tipo"], "valido=", c["valido"], c["error"])
            print("\n".join("     " + l for l in c["diff"].splitlines()))
        if not a.no_aplicar:
            validos = [c["id"] for c in rev["cambios"] if c["valido"]]
            if validos:
                res = cli.post("/api/revision/aplicar", json={"aceptados": validos[:1]}).json()
                print("APLICAR", res)
                cambiado = (ctx / "02-alcance.md").read_text(encoding="utf-8") != alcance_antes
                print("ALCANCE_CAMBIADO", cambiado, "| ficheros:", res.get("ficheros"))
                chequeo("se aplicó un cambio aceptado", bool(res.get("aplicados")))
                print("REGISTRO_TOP", (ctx / "10-registro-de-cambios.md").read_text(encoding="utf-8").split("---", 1)[1][:600])
            else:
                chequeo("hay algún cambio válido que aceptar", False, "(el modelo no propuso cambios aplicables)")
        if a.compartido:
            locales = list((SALIDA / "sesiones").rglob("*.md"))
            print("SESION_ARCHIVO_LOCAL", [str(p.relative_to(SALIDA)) for p in locales])
            chequeo("la copia local de la sesión existe", len(locales) == 1)
            if locales:
                texto = locales[0].read_text(encoding="utf-8")
                chequeo("la sesión guardada lista los objetivos" if a.sesion_plan != "otra" else "la sesión guardada no lista objetivos",
                        ("Objetivos de la sesión" in texto) == (a.sesion_plan != "otra"))
        else:
            sesiones = list((raiz / PROYECTO / "02. Sesiones (transcripciones)").glob("*.md"))
            print("SESION_ARCHIVO", [p.name for p in sesiones])
        print("CONSUMO", json.dumps(cli.get("/api/consumo").json(), ensure_ascii=False))
        if a.compartido:
            if a.no_publicar:
                cli.post("/api/revision/publicacion", json={"publicar": False})
            cierre = cli.post("/api/revision/cerrar", json={}).json()
            print("CIERRE", cierre)
            sesiones_c = carpeta_proyecto / "02. Sesiones (transcripciones)"
            if a.no_publicar:
                chequeo("con «No publicar» no se crea 02. Sesiones en la carpeta compartida", not sesiones_c.exists())
                chequeo("con «No publicar» la copia local se conserva", len(list((SALIDA / "sesiones").rglob("*.md"))) == 1)
            else:
                docs = list(sesiones_c.glob("*.md")) if sesiones_c.exists() else []
                chequeo("al cerrar se publicó un único documento en 02. Sesiones", cierre.get("ok") and len(docs) == 1, str([d.name for d in docs]))
                if docs:
                    doc = docs[0].read_text(encoding="utf-8")
                    chequeo("el documento publicado trae resumen, objetivos y checks", "## Resumen" in doc and "## Transcripción" in doc
                            and ("Objetivos de la sesión" in doc) == (a.sesion_plan != "otra") and ("Checks de la sesión" in doc) == usar_checks)
                    print("PUBLICADO", docs[0])
                chequeo("sin nada más nuevo en la carpeta compartida", sorted(p.name for p in carpeta_proyecto.iterdir()) == ["00. CONTEXTO (IA)", "02. Sesiones (transcripciones)"])
        else:
            cli.post("/api/revision/cerrar")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
    print("TOKENS_POR_TAREA", json.dumps(tabla_consumo(consumo_desde), ensure_ascii=False))
    print("RESULTADO", "FALLOS: " + ", ".join(fallos) if fallos else "todos los chequeos OK")
    return 1 if fallos else 0


if __name__ == "__main__":
    sys.exit(main())
