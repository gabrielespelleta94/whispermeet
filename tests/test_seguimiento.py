"""Ola 3, punto 6: seguimiento de pendientes entre sesiones. Sesiones .md sintéticas en carpeta temporal, sin modelo y sin tocar datos reales."""
import hashlib
import json
from pathlib import Path

from apuntes.seguimiento import cobertura, frases_de_cierre
from apuntes.fuentes import Doc, Indice
from ola3_util import PROYECTO, montaje, sesion_md

S1 = sesion_md("Arranque", "2026-10-20", insights=[
    "- [04:20] **Pendiente:** Enviar la estimación de tarifas del piloto (Ana)",
    "- [05:10] **Pendiente:** Revisar las licencias del cliente",
    "- [06:00] **Decisión:** Se empieza por la fase uno"])
S2 = sesion_md("Seguimiento", "2026-10-27", insights=[
    "- [03:00] **Pendiente:** Revisar las licencias del cliente",
    "- [03:30] **Pendiente:** Definir el calendario del piloto con fechas"],
    resumen="Se envió la estimación de tarifas del piloto al cliente y quedó validada.\n\n### Pendientes\n- Definir el calendario del piloto con fechas\n")
S3 = sesion_md("Cierre de fase", "2026-11-03", resumen="### Decisiones\n- Se aprueba la fase dos sin cambios.\n\n### Próximos pasos\n- Definir el calendario del piloto con fechas\n- Revisar las licencias del cliente\n")
SESIONES = [("2026-10-20-arranque.md", S1), ("2026-10-27-seguimiento.md", S2), ("2026-11-03-cierre-de-fase.md", S3)]


def hashes(carpeta):
    return {str(p): hashlib.sha1(p.read_bytes()).hexdigest() for p in Path(carpeta).rglob("*.md")}


def por_texto(r):
    return {p["texto"]: p for p in r["pendientes"]}


def test_frases_de_cierre_ignoran_lo_que_sigue_abierto():
    resumen = "Se acordó cambiar el formato del informe.\n\n### Decisiones\n- Se mantiene el piloto en enero.\n\n### Pendientes\n- Enviar las tarifas al cliente\n\n**Sin tratar (quedan pendientes)**\n- Cerrar licencias\n\n**Cumplidos**\n- Alcance de la fase uno cerrado\n"
    f = frases_de_cierre(resumen, ["Se aprueba el calendario definitivo"])
    assert "Se acordó cambiar el formato del informe." in f and "Se mantiene el piloto en enero." in f and "Alcance de la fase uno cerrado" in f
    assert "Se aprueba el calendario definitivo" in f
    assert not any("tarifas" in x or "licencias" in x for x in f)


def test_cobertura_exige_umbral_y_palabras_clave():
    idx = Indice([Doc("sesión", "sesion", [("Se envió la estimación de tarifas al cliente", None), ("Hablamos del tiempo y del café en la oficina", None)])])
    hit = cobertura("Enviar la estimación de tarifas", idx, 0.6)
    assert hit and hit[0]["frase"].startswith("Se envió la estimación") and hit[1] >= 0.6
    assert cobertura("Enviar la estimación de tarifas y el calendario del piloto con fechas", idx, 0.6) is None   # solo cubre una parte
    assert cobertura("Licencias del cliente", idx, 0.6) is None


def test_cierre_automatico_con_cita_y_consolidacion(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path, sesiones=SESIONES)
    antes = hashes(tmp_path / "proyectos")
    with cli:
        r = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento").json()
        p = por_texto(r)
        assert set(p) == {"Enviar la estimación de tarifas del piloto", "Revisar las licencias del cliente", "Definir el calendario del piloto con fechas"}
        tarifas = p["Enviar la estimación de tarifas del piloto"]
        assert tarifas["estado"] == "hecho" and tarifas["auto"] is True and tarifas["responsable"] == "Ana"
        assert tarifas["cita"]["sesion_id"] and tarifas["cita"]["fecha"] == "2026-10-27" and "estimación de tarifas" in tarifas["cita"]["texto"]
        # repetido en S1 y S2 (y listado como siguiente paso en S3): UNA vez, la más antigua posterior no lo cubre -> abierto
        lic = p["Revisar las licencias del cliente"]
        assert lic["estado"] == "abierto" and lic["veces"] == 2 and lic["cita"] is None
        # una frase de «Pendientes»/«Próximos pasos» no cuenta como haberlo hecho
        assert p["Definir el calendario del piloto con fechas"]["estado"] == "abierto"
        assert r["abiertos"] == 2 and r["hechos"] == 1 and r["autonomia"] == "hacer"
        # el estado se refleja en el backlog (galería y «Sesiones»)
        items = {i["texto"]: i for i in bl.items(True)["items"] if i["tipo"] == "pendiente"}
        assert items["Enviar la estimación de tarifas del piloto"]["estado"] == "hecho"
    # persistencia local por el Guardian, y los .md no se tocan
    archivo = tmp_path / "seguimiento" / "proyecto-ola-tres.json"
    assert archivo.is_file() and json.loads(archivo.read_text(encoding="utf-8"))["version"] == 1
    assert hashes(tmp_path / "proyectos") == antes
    assert not any(x.name.endswith(".json") for x in (tmp_path / "proyectos").rglob("*"))


def test_reabrir_es_reversible_y_no_se_vuelve_a_cerrar_solo(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path, sesiones=SESIONES)
    with cli:
        r = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento").json()
        iid = por_texto(r)["Enviar la estimación de tarifas del piloto"]["id"]
        ab = cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{iid}/reabrir").json()
        assert ab["estado"] == "abierto" and ab["auto"] is False and ab["cita"] is None
        r2 = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento?refrescar=1").json()
        assert por_texto(r2)["Enviar la estimación de tarifas del piloto"]["estado"] == "abierto" and r2["hechos"] == 0
        h = cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{iid}/hecho", json={"cita": {"sesion": "sesión 2026-10-27 · Seguimiento", "texto": "Se envió la estimación"}}).json()
        assert h["estado"] == "hecho" and h["auto"] is False and h["cita"]["texto"] == "Se envió la estimación"
        assert cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{iid}/hecho").json()["estado"] == "hecho"     # sin cita también vale (lo marca el usuario)
        assert cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{iid}/reabrir").json()["estado"] == "abierto"


def test_con_autonomia_proponer_solo_se_propone_el_cierre(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path, sesiones=SESIONES, config={"autonomia": {"consolidar_pendientes": "proponer"}})
    with cli:
        r = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento").json()
        t = por_texto(r)["Enviar la estimación de tarifas del piloto"]
        assert t["estado"] == "abierto" and t["cierre_propuesto"]["fecha"] == "2026-10-27" and "estimación" in t["cierre_propuesto"]["texto"]
        assert r["hechos"] == 0 and r["autonomia"] == "proponer"
        # el usuario acepta la propuesta
        h = cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{t['id']}/hecho", json={"cita": t["cierre_propuesto"]}).json()
        assert h["estado"] == "hecho" and h["cita"]["fecha"] == "2026-10-27"


def test_umbral_configurable(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path, sesiones=SESIONES, config={"seguimiento_umbral": 1.0})
    with cli:
        r = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento").json()
        # «Enviar» no está en la frase («Se envió…»): con el umbral al máximo ya no cuenta
        assert por_texto(r)["Enviar la estimación de tarifas del piloto"]["estado"] == "abierto" and r["umbral"] == 1.0


def test_errores_y_ids(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path, sesiones=SESIONES)
    with cli:
        assert cli.get("/api/proyectos/No existe/seguimiento").status_code == 404
        assert cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{'a' * 16}/hecho").status_code == 404
        assert cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/../../x/hecho").status_code in (400, 404)
        assert cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/xyz/reabrir").status_code == 400
        assert cli.get(f"/api/proyectos/{PROYECTO}/seguimiento", headers={"X-Token": "otro"}).status_code == 401


def test_un_seguimiento_danado_se_aparta_y_no_bloquea(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path, sesiones=SESIONES)
    carpeta = tmp_path / "seguimiento"
    carpeta.mkdir()
    (carpeta / "proyecto-ola-tres.json").write_text("{esto no es json", encoding="utf-8")
    with cli:
        r = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento").json()
        assert r["abiertos"] >= 1 and r["avisos"] and "apartó" in r["avisos"][0]
    assert any(p.name.startswith("proyecto-ola-tres.json.roto-") for p in carpeta.iterdir())


def test_los_pendientes_aceptados_sin_sesion_leida_tambien_salen(tmp_path):
    cli, gestor, cfg, g, bl, *_ = montaje(tmp_path)   # sin sesiones .md
    with cli:
        gestor.seguimiento.anadir_pendientes(PROYECTO, [{"texto": "Mandar el catálogo", "datos": {"dueno": "Luis", "fecha": "lunes"}}], {"sesion": "x.md", "fecha": "2026-11-06", "tema": "T"})
        r = cli.get(f"/api/proyectos/{PROYECTO}/seguimiento").json()
        assert len(r["pendientes"]) == 1 and r["pendientes"][0]["origen"] == "acciones" and r["pendientes"][0]["responsable"] == "Luis"
        iid = r["pendientes"][0]["id"]
        assert cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{iid}/hecho").json()["estado"] == "hecho"
        assert cli.post(f"/api/proyectos/{PROYECTO}/seguimiento/{iid}/reabrir").json()["estado"] == "abierto"
