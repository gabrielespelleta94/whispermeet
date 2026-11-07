"""Backlog (sesiones pasadas + pendientes e ideas): lectura tolerante, deduplicado, estado local, seguridad de rutas y endpoints.

Todo con .md SINTÉTICOS en carpetas temporales (ni OneDrive ni contenido real) y sin llamar al modelo: el modelo que se pasa al Gestor falla si alguien lo llama."""
import hashlib
import json
import os
import re
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apuntes import backlog as BL
from apuntes.analisis import ModeloLLM
from apuntes.backlog import Backlog, clave_repetido, normalizar, parsear_sesion
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_SESIONES, Guardian, RutaProhibida
from apuntes.servidor import Difusor, crear_app

PUERTO, TOKEN = 8131, "t0k3n"
AHORA = datetime(2026, 11, 5, 15, 0)


# ------------------------------------------------------------------ material sintético
def sesion_md(tema="Reunión ficticia", fecha="2026-11-02", inicio="10:00", duracion="20:00", estado="finalizada", proyecto="Bandeja",
              insights=(), resumen="", transcripcion=("[00:05] **Reunión:** Hola a todos.", "[00:20] **Micro:** Buenos días."), extra=""):
    partes = ["---", f'tema: "{tema}"', f'proyecto: "{proyecto}"', f"fecha: {fecha}", f"inicio: {inicio}", f"duracion: {duracion}", f"estado: {estado}", extra,
              "origen: WhisperMeet (transcripción automática; revisar antes de citar)", "---", "", f"# {tema}", ""]
    if resumen:
        partes += ["## Resumen", "", resumen, ""]
    if insights:
        partes += ["## Insights", "", *insights, ""]
    partes += ["## Transcripción", "", *transcripcion, ""]
    return "\n".join(p for p in partes if p is not None and not (p == "" and False)) + "\n"


def escribir(carpeta: Path, nombre: str, texto: str, antiguedad_h: float | None = None) -> Path:
    carpeta.mkdir(parents=True, exist_ok=True)
    p = carpeta / nombre
    p.write_text(texto, encoding="utf-8", newline="\n")
    if antiguedad_h is not None:
        t = AHORA.timestamp() - antiguedad_h * 3600
        os.utime(p, (t, t))
    return p


class ModeloQueNoSeLlama(ModeloLLM):
    def completar(self, *a, **k):
        raise AssertionError("el backlog no puede llamar al modelo")


@pytest.fixture
def mundo(tmp_path):
    raiz = tmp_path / "proyectos"
    (raiz / "ProyA" / CARPETA_SESIONES).mkdir(parents=True)
    ajena = tmp_path / "ajena" / "Compartida"
    ajena.mkdir(parents=True)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones", backlog=tmp_path / "backlog",
                 extras=[{"nombre": "Compartida", "ruta": str(ajena), "compartido": True}])
    return g, tmp_path, raiz, ajena


def backlog(g, **k):
    return Backlog(g, None, ahora=lambda: AHORA, **k)


def hashes(*carpetas):
    out = {}
    for c in carpetas:
        for p in Path(c).rglob("*.md"):
            out[str(p)] = (hashlib.sha1(p.read_bytes()).hexdigest(), p.stat().st_mtime_ns)
    return out


def items(r):
    return r["items"]


# ------------------------------------------------------------------ lectura de una sesión
def test_formato_actual_con_sufijos_y_tipos():
    md = sesion_md(insights=[
        "- [04:37] **Decisión:** Liberar la herramienta a la espera de cerrar el workflow.",
        "- [04:12] **Pendiente:** Cerrar los pendientes del equipo en una semana (sin asignar)",
        "- [04:20] **Pendiente:** Enviar el fichero de tarifas (turno 2) (Ana)",
        "- [03:06] **Riesgo:** Construcción parada en la parte central.",
        "- [03:48] **Pregunta:** ¿Se cumple el objetivo del 15 de noviembre?",
        "- [06:24] **Regla:** Restringir los remitentes permitidos.",
        "- [08:31] **Idea:** Delegar proyectos en otras personas.",
        "- [02:10] **Contradicción:** El cliente pide SAP en fase 1. — contexto: «quedó como evolutivo para una fase dos»",
        "- [02:11] **Posible contradicción:** Meter SAP en fase 1 — contexto: «02-alcance.md: fuera de alcance»",
        "- [--:--] **Idea:** Una idea sin minuto.",
        "- [09:00] **Consejo (siguiente pregunta):** Pregunta quién valida el catálogo antes del piloto — por qué: sin catálogo no hay piloto firme",   # el Estratega
    ])
    p = parsear_sesion(md, "2026-11-02-reunion-ficticia.md")
    assert p["avisos"] == [] and p["tema"] == "Reunión ficticia" and p["fecha"] == "2026-11-02" and p["inicio"] == "10:00" and p["duracion_s"] == 1200
    por = {(i["tipo"], i["minuto"]): i for i in p["items"]}
    assert {i["tipo"] for i in p["items"]} == set(BL.TIPOS)
    assert por[("pendiente", "04:20")]["responsable"] == "Ana" and por[("pendiente", "04:20")]["texto"] == "Enviar el fichero de tarifas"
    assert por[("pendiente", "04:12")]["responsable"] is None and por[("pendiente", "04:12")]["texto"].endswith("en una semana")
    assert por[("contradiccion", "02:10")]["contexto"] == "quedó como evolutivo para una fase dos" and por[("contradiccion", "02:10")]["posible"] is False
    assert por[("contradiccion", "02:11")]["posible"] is True
    assert por[("idea", None)]["texto"] == "Una idea sin minuto."
    assert len(p["transcripcion"]) == 2 and p["transcripcion"][0] == {"t": 5, "m": "00:05", "f": "Reunión", "x": "Hola a todos."}


def test_no_se_inventan_responsables_ni_estados():
    md = sesion_md(insights=[
        "- [01:00] **Pendiente:** Confirmar cómo enviar el correo desde Fabric (Microsoft Graph)",   # dos palabras: es un término, no una persona
        "- [01:10] **Pendiente:** Revisar la integración con (SAP)",                                  # una sigla tampoco
        "- [01:20] **Decisión:** Se sigue con el plan (Luis)",                                        # solo los pendientes llevan responsable
    ])
    p = parsear_sesion(md, "2026-11-02-x.md")
    assert [i["responsable"] for i in p["items"]] == [None, None, None]
    assert p["items"][0]["texto"].endswith("(Microsoft Graph)") and p["items"][2]["texto"].endswith("(Luis)")


def test_formato_anterior_resumen_sin_insights_con_apartados():
    resumen = "\n".join([
        "## Resumen final – Seguimiento portal", "",
        "**Objetivo:** revisar el estado del proyecto.", "",
        "### Decisiones", "- **Piloto:** se mantiene el 20 de enero con dos hoteles.", "",
        "### Pendientes",
        "- **Luis:** enviar la estimación de SAP el viernes [04:05].",
        "- **Equipo (sin responsable asignado):** valorar el impacto en licencias.",
        "- **08:42** Definir los campos obligatorios. Responsable: Pablo.",
        "- **09:53** Añadir el campo de presupuesto. Responsable: sin asignar.", "",
        "### Preguntas y riesgos abiertos",
        "- ¿Es definitiva la cifra de 20.000 por habitación? (05:45)",
        "- Activar una oportunidad relanza los parámetros (12:33).", "",
        "### Próximos pasos", "1. Viernes: estimación SAP de Luis.", ""])
    md = "\n".join(["---", 'tema: "Seguimiento"', 'proyecto: "Bandeja"', "fecha: 2026-11-03", "inicio: 19:06", "duracion: 20:21", "estado: finalizada", "---", "",
                    "# Seguimiento", "", "## Resumen", "", resumen, "", "## Transcripción", "", "[00:05] **Reunión:** Buenos días."])
    p = parsear_sesion(md, "2026-11-03-seguimiento.md")
    por = {(i["tipo"], i["texto"][:12]): i for i in p["items"]}
    assert all(i["origen"] == "resumen" for i in p["items"])
    assert por[("decision", "Piloto: se m")]["minuto"] is None
    luis = por[("pendiente", "Enviar la es")]
    assert luis["responsable"] == "Luis" and luis["minuto"] == "04:05" and luis["texto"].endswith("el viernes")
    assert por[("pendiente", "Valorar el i")]["responsable"] is None
    assert por[("pendiente", "Definir los ")]["responsable"] == "Pablo" and por[("pendiente", "Definir los ")]["minuto"] == "08:42"
    assert por[("pendiente", "Añadir el ca")]["responsable"] is None
    assert [i["tipo"] for i in p["items"] if i["minuto"] in ("05:45", "12:33")] == ["pregunta", "riesgo"]
    assert not any("Viernes" in i["texto"] for i in p["items"])   # «Próximos pasos» no es un tipo


def test_sin_insights_interrumpida_y_en_curso_no_rompen(mundo):
    g, tmp, *_ = mundo
    escribir(tmp / "bandeja", "2026-11-03-seguimiento.md", sesion_md(tema="seguimiento", fecha="2026-11-03", inicio="23:00", estado="interrumpida"), 40)
    escribir(tmp / "bandeja", "2026-11-05-ahora.md", sesion_md(tema="ahora", fecha="2026-11-05", inicio="14:30", estado="en curso", insights=["- [00:10] **Idea:** Probar algo."]), 0.01)
    r = backlog(g).sesiones()
    por = {s["tema"]: s for s in r["sesiones"]}
    assert por["seguimiento"]["estado"] == "interrumpida" and por["seguimiento"]["total"] == 0 and por["seguimiento"]["n_transcripcion"] == 2
    assert por["ahora"]["estado"] == "en_curso" and por["ahora"]["recuentos"]["idea"] == 1
    assert [s["tema"] for s in r["sesiones"]] == ["ahora", "seguimiento"]   # fecha descendente


@pytest.mark.parametrize("texto", [
    "", "\n\n", "sin cabecera ni nada\n", "---\ntema: \"Roto\nproyecto Bandeja\nfecha: 2026-13-45\n---\n# x\n## Insights\n- [00:01] **Idea:** a\n",
    "---\ntema: x\nfecha: 2026-11-02\n## Insights\n- [00:01] **Idea:** sin cerrar la cabecera\n", "---\n---\n---\n---\n", "\x00\x01\x02 binario \ufffd\ufffd",
    "---\ntema: ok\n---\n## Insights\n- **Decisión sin dos puntos\n- [xx:yy] **Idea:** minuto malo\n- [00:05] **Cosa rara:** tipo desconocido\n- texto suelto\n",
    "---\ntema: ok\nestado: en curso\n---\n## Resumen\n**Pendientes**\n- [99:99] **\n- ** \n## Transcripción\n[00:0",
    "## Resumen\n" + "- " * 5000 + "\n", "---\n" + "clave: valor\n" * 500,
])
def test_yaml_roto_y_ficheros_raros_nunca_lanzan(texto):
    p = parsear_sesion(texto, "2026-11-02-raro.md", "Bandeja")   # no debe lanzar
    assert isinstance(p["items"], list) and isinstance(p["avisos"], list)
    assert p["tema"] and p["proyecto"]
    json.dumps(p, ensure_ascii=False)   # y todo es serializable


def test_yaml_roto_devuelve_lo_que_puede_y_anota_el_motivo():
    p = parsear_sesion("---\ntema: \"Roto\nfecha: 2026-13-45\nduracion: abc\n---\n# Roto\n## Insights\n- [00:01] **Idea:** a\n", "2026-11-04-roto.md", "Bandeja")
    assert p["tema"] == "Roto" and p["fecha"] == "2026-11-04"   # la fecha mala se sustituye por la del nombre del fichero
    assert len(p["items"]) == 1
    assert any("fecha" in a.lower() for a in p["avisos"]) and any("duración" in a for a in p["avisos"])
    sin_cerrar = parsear_sesion("---\ntema: x\nfecha: 2026-11-02\n## Insights\n- [00:01] **Idea:** a\n", "2026-11-02-x.md")
    assert any("no se cierra" in a for a in sin_cerrar["avisos"]) and len(sin_cerrar["items"]) == 1


# ------------------------------------------------------------------ duplicados y recortes entre Insights y Resumen
def test_resumen_aporta_lo_que_no_esta_en_insights_y_no_duplica():
    resumen = "\n".join([
        "## Resumen de la reunión (20:00)", "", "**Decisiones**",
        "- [04:37] Liberar la herramienta para generar inversiones individuales, aunque sean demo.",     # = insight (casi idéntico)
        "", "**Pendientes (ninguno con responsable asignado)**",
        "- [04:12] Cerrar los pendientes del equipo para poner la herramienta en productivo en una semana.",   # = insight
        "- [23:29] Confirmar si la sesión de formación se puede grabar.",                                 # no está en insights
        "", "**Ideas (no son decisiones)**", "- [26:00–26:38] Con solo audio basta para optimizar el análisis.",   # idea nueva
        "", "**Preguntas abiertas**", "- [03:48] ¿Se cumple el objetivo del 15 de noviembre?",            # = insight
        "", "**Riesgos**", "- [03:06] Construcción parada en la parte central, dependiente de una persona.",   # = insight (parecido)
    ])
    md = sesion_md(resumen=resumen, insights=[
        "- [04:37] **Decisión:** Liberar la herramienta para generar inversiones individuales, aunque sean demo.",
        "- [04:12] **Pendiente:** Cerrar los pendientes del equipo para poner la herramienta en productivo en una semana",
        "- [03:48] **Pregunta:** ¿Se cumple el objetivo del 15 de noviembre?",
        "- [03:06] **Riesgo:** Construcción parada en la parte central, dependiente de una persona.",
    ])
    p = parsear_sesion(md, "2026-11-02-x.md")
    clave = sorted((i["tipo"], i["minuto"], i["origen"]) for i in p["items"])
    assert clave == sorted([("decision", "04:37", "insight"), ("pendiente", "04:12", "insight"), ("pregunta", "03:48", "insight"), ("riesgo", "03:06", "insight"),
                            ("pendiente", "23:29", "resumen"), ("idea", "26:00", "resumen")])


def test_ante_la_duda_se_conservan_los_dos():
    resumen = "**Pendientes**\n- [10:00] Enviar el presupuesto del proyecto al cliente.\n- [20:00] Revisar contrato."
    md = sesion_md(resumen=resumen, insights=[
        "- [10:00] **Pendiente:** Organizar la formación del equipo comercial el jueves.",   # mismo minuto, texto distinto: son dos cosas
        "- [30:00] **Pendiente:** Revisar contrato.",                                          # mismo texto, 10 minutos después: no se funde
    ])
    p = parsear_sesion(md, "2026-11-02-x.md")
    assert len(p["items"]) == 4


def test_insight_recortado_usa_la_entrada_completa_del_resumen():
    completo = "Paso 1: lo comprometido sin entrar al detalle; paso 2: entrar al detalle de actuaciones; paso 3: qué está comprometido y de qué se compone cada partida."
    md = sesion_md(resumen=f"**Reglas y acuerdos a confirmar**\n- [02:00] {completo}", insights=[
        "- [02:00] **Regla:** Paso 1: lo comprometido sin entrar al detalle; paso 2: entrar al detalle de actuaciones; paso 3: qué está comprometido y de…",
        "- [05:00] **Pregunta:** ¿Qué servicio de correo envía el mail automático al crear una inversión y quién lo configura? Transcripción poco…",   # sin entrada completa
    ])
    p = parsear_sesion(md, "2026-11-02-x.md")
    reglas = [i for i in p["items"] if i["tipo"] == "regla"]
    assert len(reglas) == 1 and reglas[0]["texto"] == completo and reglas[0]["completado"] is True and reglas[0]["recortado"] is False and reglas[0]["origen"] == "insight"
    preg = next(i for i in p["items"] if i["tipo"] == "pregunta")
    assert preg["recortado"] is True and preg["texto"].endswith("…")


def test_la_sesion_parseada_mantiene_los_ids_aunque_cambie_el_orden():
    a = ["- [01:00] **Pendiente:** Enviar tarifas.", "- [02:00] **Pendiente:** Llamar al cliente.", "- [03:00] **Idea:** Un solo hotel."]
    r1 = BL.parsear_sesion(sesion_md(insights=a), "2026-11-02-x.md")["items"]
    r2 = BL.parsear_sesion(sesion_md(insights=list(reversed(a))), "2026-11-02-x.md")["items"]
    ids = lambda r: {(i["tipo"], i["texto"]): BL.id_item("C:/x/2026-11-02-x.md", i["tipo"], i["texto"]) for i in r}   # noqa: E731
    assert ids(r1) == ids(r2) and len(set(ids(r1).values())) == 3
    assert BL.id_item("C:/x/a.md", "pendiente", "Enviar tarifas.") != BL.id_item("C:/x/b.md", "pendiente", "Enviar tarifas.")   # depende de la ruta
    assert BL.id_item("C:/x/a.md", "pendiente", "Enviar TARIFAS") == BL.id_item("C:/x/a.md", "pendiente", "enviar  tarifas…")   # texto normalizado
    assert BL.id_item("C:/x/a.md", "pendiente", "x") != BL.id_item("C:/x/a.md", "idea", "x")


# ------------------------------------------------------------------ fuentes, exclusiones y topes
def test_fuentes_bandeja_local_proyecto_y_extra_con_exclusiones(mundo):
    g, tmp, raiz, ajena = mundo
    escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(tema="A"))
    escribir(tmp / "bandeja", "2026-11-01-token-de-acceso.md", sesion_md(tema="Con nombre de secreto"))     # se omite por el nombre
    escribir(tmp / "bandeja", "notas.md", sesion_md(tema="Sin fecha en el nombre"))                          # no es una sesión
    escribir(tmp / "bandeja", "2026-11-01-b.txt", sesion_md(tema="No es markdown"))
    escribir(tmp / "sesiones" / "compartida", "2026-11-02-b.md", sesion_md(tema="B local", proyecto="Compartida"))
    escribir(raiz / "ProyA" / CARPETA_SESIONES, "2026-11-03-c.md", sesion_md(tema="C", proyecto="ProyA"))
    escribir(ajena / CARPETA_SESIONES, "2026-11-04-d.md", sesion_md(tema="D", proyecto="Compartida"))
    escribir(raiz / ".git" / CARPETA_SESIONES, "2026-11-05-e.md", sesion_md(tema="En carpeta excluida"))
    r = backlog(g).sesiones()
    assert [s["tema"] for s in r["sesiones"]] == ["D", "C", "B local", "A"]
    assert {s["tema"]: s["origen"] for s in r["sesiones"]} == {"D": "publicada", "C": "proyecto", "B local": "local", "A": "bandeja"}
    assert any("omitido" in a for a in r["avisos"])
    assert r["proyectos"] == ["Bandeja", "Compartida", "ProyA"]


def test_lineas_con_pinta_de_secreto_no_llegan_al_backlog(mundo):
    g, tmp, *_ = mundo
    escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(transcripcion=("[00:01] **Micro:** la clave es password: SuperSecreto123", "[00:02] **Micro:** hola")))
    d = backlog(g)
    sid = d.sesiones()["sesiones"][0]["id"]
    ts = d.sesion(sid)["transcripcion"]
    assert "SuperSecreto123" not in json.dumps(ts) and any("omitida" in t["x"] for t in ts) and ts[1]["x"] == "hola"


def test_el_tope_de_lectura_recorta_y_avisa(mundo):
    g, tmp, *_ = mundo
    escribir(tmp / "bandeja", "2026-11-01-grande.md", sesion_md(transcripcion=[f"[{i // 60:02d}:{i % 60:02d}] **Reunión:** línea número {i} con algo de relleno" for i in range(2000)]))
    r = backlog(g, tope_bytes=20_000).sesiones()
    s = r["sesiones"][0]
    assert any("recortada" in a for a in s["avisos"]) and 100 < s["n_transcripcion"] < 2000


def test_guardian_rechaza_rutas_fuera_secretos_y_no_md(mundo):
    g, tmp, raiz, _ = mundo
    ok = escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md())
    fuera = escribir(tmp, "2026-11-01-fuera.md", sesion_md())
    secreto = escribir(tmp / "bandeja", "2026-11-01-secretos.md", sesion_md())
    txt = escribir(tmp / "bandeja", "2026-11-01-a.txt", "x")
    assert "tema" in g.leer_sesion_md(ok, tmp / "bandeja")
    for ruta in (fuera, tmp / "bandeja" / ".." / "2026-11-01-fuera.md", secreto, txt, tmp / "bandeja" / "no-existe.md", tmp / "bandeja"):
        with pytest.raises(RutaProhibida):
            g.leer_sesion_md(ruta, tmp / "bandeja")
        with pytest.raises(RutaProhibida):
            g.abrir_sesion_md(ruta, tmp / "bandeja", lambda p: pytest.fail("no debía abrirse"))
    abierto = []
    g.abrir_sesion_md(ok, tmp / "bandeja", abierto.append)
    assert abierto == [str(ok)]


def test_nunca_se_modifica_ningun_md_ni_se_llama_al_modelo(mundo):
    g, tmp, raiz, ajena = mundo
    escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(tema="A", insights=["- [01:00] **Pendiente:** Enviar tarifas.", "- [02:00] **Idea:** Un solo hotel."]))
    escribir(tmp / "sesiones" / "compartida", "2026-11-02-b.md", sesion_md(tema="B", estado="en curso", proyecto="Compartida"), 30)
    escribir(ajena / CARPETA_SESIONES, "2026-11-04-d.md", sesion_md(tema="D", proyecto="Compartida"))
    antes = hashes(tmp / "bandeja", tmp / "sesiones", ajena, raiz)
    d = backlog(g)
    for it in items(d.items(True)):
        if it["estados"]:
            d.fijar_estado(it["id"], it["estados"][-1])
    for s in d.sesiones()["sesiones"]:
        d.fijar_tema(s["id"], "Otro nombre")
        d.sesion(s["id"])
    assert hashes(tmp / "bandeja", tmp / "sesiones", ajena, raiz) == antes   # contenido Y fecha de modificación intactos
    assert sorted(p.name for p in (tmp / "backlog").iterdir()) == ["estado.json"]   # y lo único escrito es backlog\estado.json (sin temporales)


# ------------------------------------------------------------------ sin cerrar
def test_sin_cerrar_segun_antiguedad_y_escritura_reciente(mundo):
    g, tmp, *_ = mundo
    escribir(tmp / "bandeja", "2026-11-04-vieja.md", sesion_md(tema="vieja", fecha="2026-11-04", inicio="08:00", estado="en curso"), 20)         # 31 h en curso, sin escribir
    escribir(tmp / "bandeja", "2026-11-05-escribiendo.md", sesion_md(tema="escribiendo", fecha="2026-11-05", inicio="01:00", estado="en curso"), 0.001)   # 14 h y escribiendo ahora
    escribir(tmp / "bandeja", "2026-11-04-tocada.md", sesion_md(tema="tocada", fecha="2026-11-04", inicio="08:00", estado="en curso"), 0.001)   # 31 h: el fichero se tocó hace poco, pero no puede seguir en curso
    escribir(tmp / "bandeja", "2026-11-05-hace-poco.md", sesion_md(tema="hace poco", fecha="2026-11-05", inicio="12:00", estado="en curso"), 1)   # 3 h: aún no
    escribir(tmp / "bandeja", "2026-11-05-terminada.md", sesion_md(tema="terminada", fecha="2026-11-05", inicio="09:00", estado="finalizada"), 5)
    escribir(tmp / "bandeja", "2026-11-05-sin-hora.md", sesion_md(tema="sin hora", fecha="2026-11-05", inicio="", estado="en curso"), 14)           # sin hora: manda el fichero
    por = {s["tema"]: s["estado"] for s in backlog(g).sesiones()["sesiones"]}
    assert por == {"vieja": "sin_cerrar", "escribiendo": "en_curso", "tocada": "sin_cerrar", "hace poco": "en_curso", "terminada": "finalizada", "sin hora": "sin_cerrar"}


# ------------------------------------------------------------------ compartida local + publicada
def test_sesion_local_y_publicada_se_muestra_una_vez_y_conserva_el_vinculo(mundo):
    g, tmp, raiz, ajena = mundo
    publicada = escribir(ajena / CARPETA_SESIONES, "2026-11-02-b.md", sesion_md(tema="B", proyecto="Compartida", insights=["- [01:00] **Pendiente:** Enviar tarifas."]))
    escribir(tmp / "sesiones" / "compartida", "2026-11-02-b.md", sesion_md(tema="B", proyecto="Compartida", extra=f'publicada_en: "{publicada}"',
                                                                         insights=["- [01:00] **Pendiente:** Enviar tarifas."]))
    # otra pareja sin `publicada_en`: se une por proyecto + fecha + hora + tema
    escribir(ajena / CARPETA_SESIONES, "2026-11-03-c.md", sesion_md(tema="C", fecha="2026-11-03", proyecto="Compartida"))
    escribir(tmp / "sesiones" / "compartida", "2026-11-03-c.md", sesion_md(tema="C", fecha="2026-11-03", proyecto="Compartida"))
    # y una local que no está publicada sigue saliendo
    escribir(tmp / "sesiones" / "compartida", "2026-11-04-d.md", sesion_md(tema="D", fecha="2026-11-04", proyecto="Compartida"))
    d = backlog(g)
    r = d.sesiones()
    assert [s["tema"] for s in r["sesiones"]] == ["D", "C", "B"]
    b = next(s for s in r["sesiones"] if s["tema"] == "B")
    assert b["origen"] == "publicada" and b["vinculada"] == {"archivo": "2026-11-02-b.md", "origen": "local"}
    assert next(s for s in r["sesiones"] if s["tema"] == "D")["vinculada"] is None
    # el estado marcado sobre la copia local sigue valiendo cuando se publica (ids alternativos)
    it = items(d.items())[0]
    d.fijar_estado(it["id"], "hecho")
    estado = json.loads((tmp / "backlog" / "estado.json").read_text(encoding="utf-8"))
    local_id = BL.id_item(tmp / "sesiones" / "compartida" / "2026-11-02-b.md", "pendiente", "Enviar tarifas.")
    estado["items"][local_id] = estado["items"].pop(it["id"])
    (tmp / "backlog" / "estado.json").write_text(json.dumps(estado), encoding="utf-8")
    assert backlog(g).items(True)["items"][0]["estado"] == "hecho"


# ------------------------------------------------------------------ caché y fuentes lentas
def test_cache_por_ruta_y_fecha_de_modificacion(mundo, monkeypatch):
    g, tmp, *_ = mundo
    p = escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(tema="A", insights=["- [01:00] **Pendiente:** Uno."]))
    escribir(tmp / "bandeja", "2026-11-02-b.md", sesion_md(tema="B", fecha="2026-11-02"))
    lecturas = []
    original = g.leer_sesion_md
    monkeypatch.setattr(g, "leer_sesion_md", lambda ruta, base, tope=200_000: (lecturas.append(Path(ruta).name), original(ruta, base, tope))[1])
    d = backlog(g)
    d.sesiones()
    assert sorted(lecturas) == ["2026-11-01-a.md", "2026-11-02-b.md"]
    d.sesiones(); d.items(True)
    assert len(lecturas) == 2                                 # nada cambió: ni una lectura más
    p.write_text(sesion_md(tema="A", insights=["- [01:00] **Pendiente:** Uno.", "- [02:00] **Pendiente:** Dos."]), encoding="utf-8")
    os.utime(p, ns=(p.stat().st_atime_ns, p.stat().st_mtime_ns + 5_000_000_000))
    assert next(s for s in d.sesiones()["sesiones"] if s["tema"] == "A")["total"] == 2 and lecturas[2:] == ["2026-11-01-a.md"]   # cambió: solo se relee esa


def test_una_carpeta_lenta_no_bloquea_y_se_recoge_despues(mundo):
    g, tmp, raiz, ajena = mundo
    escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(tema="Local"))
    escribir(ajena / CARPETA_SESIONES, "2026-11-04-d.md", sesion_md(tema="De OneDrive", proyecto="Compartida"))
    suelta = threading.Event()
    original = g.listar_sesiones_md

    def lento(carpeta, tope=2000):
        if "Compartida" in str(carpeta):
            suelta.wait(10)   # OneDrive sin conexión
        return original(carpeta, tope)
    g.listar_sesiones_md = lento
    d = backlog(g, tiempo_fuente_s=0.4)
    t0 = time.monotonic()
    r = d.sesiones()
    assert time.monotonic() - t0 < 3
    assert [s["tema"] for s in r["sesiones"]] == ["Local"] and any("tarda en responder" in a and "Compartida" in a for a in r["avisos"])
    suelta.set()
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        r = d.sesiones()
        if len(r["sesiones"]) == 2:
            break
        time.sleep(0.05)
    assert [s["tema"] for s in r["sesiones"]] == ["De OneDrive", "Local"] and not any("tarda" in a for a in r["avisos"])


def test_un_fallo_al_leer_una_sesion_se_anota_y_el_resto_sale(mundo, monkeypatch):
    g, tmp, *_ = mundo
    escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(tema="A"))
    escribir(tmp / "bandeja", "2026-11-02-b.md", sesion_md(tema="B", fecha="2026-11-02"))
    original = g.leer_sesion_md

    def falla(ruta, base, tope=200_000):
        if Path(ruta).name.endswith("-a.md"):
            raise PermissionError("el fichero está abierto por otro proceso")
        return original(ruta, base, tope)
    monkeypatch.setattr(g, "leer_sesion_md", falla)
    r = backlog(g).sesiones()
    assert [s["tema"] for s in r["sesiones"]] == ["B"] and any("2026-11-01-a.md" in a and "no se pudo leer" in a for a in r["avisos"])


# ------------------------------------------------------------------ estado local y tema renombrado
def _sesion_con_pendientes(tmp, orden=(0, 1, 2)):
    todos = ["- [01:00] **Pendiente:** Enviar tarifas.", "- [02:00] **Pendiente:** Llamar al cliente.", "- [03:00] **Idea:** Un solo hotel."]
    return escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(tema="Presupuesto", insights=[todos[i] for i in orden]))


def test_estado_y_tema_persisten_entre_ejecuciones_y_ante_cambios_de_orden(mundo):
    g, tmp, *_ = mundo
    p = _sesion_con_pendientes(tmp)
    d = backlog(g)
    por = {i["texto"]: i for i in items(d.items(True))}
    assert por["Enviar tarifas."]["estado"] == "abierto" and por["Un solo hotel."]["estado"] == "nueva" and por["Enviar tarifas."]["estados"] == ["abierto", "hecho", "descartado"]
    d.fijar_estado(por["Enviar tarifas."]["id"], "hecho")
    d.fijar_estado(por["Llamar al cliente."]["id"], "descartado")
    d.fijar_estado(por["Un solo hotel."]["id"], "aprovechada")
    sid = d.sesiones()["sesiones"][0]["id"]
    assert d.fijar_tema(sid, "  Presupuesto   — pricing ")["tema"] == "Presupuesto — pricing"
    # «otra ejecución»: un Backlog nuevo sobre el mismo disco, con el .md reordenado y reescrito
    p.write_text(sesion_md(tema="Presupuesto", insights=["- [03:00] **Idea:** Un solo hotel.", "- [02:00] **Pendiente:** Llamar al cliente.", "- [01:00] **Pendiente:** Enviar tarifas."]), encoding="utf-8")
    nuevo = backlog(g)
    r = {i["texto"]: i["estado"] for i in items(nuevo.items(True))}
    assert r == {"Enviar tarifas.": "hecho", "Llamar al cliente.": "descartado", "Un solo hotel.": "aprovechada"}
    s = nuevo.sesiones()["sesiones"][0]
    assert s["tema"] == "Presupuesto — pricing" and s["tema_original"] == "Presupuesto" and s["renombrado"] is True and nuevo.sesion(s["id"])["tema"] == "Presupuesto — pricing"
    assert all(i["sesion_tema"] == "Presupuesto — pricing" for i in items(nuevo.items()))
    # volver al estado inicial borra la entrada; el tema vacío restaura el original
    nuevo.fijar_estado(next(i["id"] for i in items(nuevo.items()) if i["texto"] == "Enviar tarifas."), "abierto")
    nuevo.fijar_tema(s["id"], "")
    datos = json.loads((tmp / "backlog" / "estado.json").read_text(encoding="utf-8"))
    assert len(datos["items"]) == 2 and datos["temas"] == {}
    assert backlog(g).sesiones()["sesiones"][0]["tema"] == "Presupuesto"


def test_solo_pendientes_e_ideas_tienen_estado_y_los_validos_son_los_suyos(mundo):
    g, tmp, *_ = mundo
    escribir(tmp / "bandeja", "2026-11-01-a.md", sesion_md(insights=["- [01:00] **Pendiente:** P.", "- [02:00] **Idea:** I.", "- [03:00] **Decisión:** D.", "- [04:00] **Riesgo:** R."]))
    d = backlog(g)
    por = {i["tipo"]: i for i in items(d.items(True))}
    assert por["decision"]["estado"] is None and por["riesgo"]["estados"] == [] and por["pendiente"]["estado"] == "abierto"
    for tipo, malo in (("decision", "hecho"), ("riesgo", "abierto"), ("pendiente", "aprovechada"), ("idea", "hecho"), ("pendiente", "")):
        with pytest.raises(ValueError):
            d.fijar_estado(por[tipo]["id"], malo)
    assert d.fijar_estado("0" * 16, "hecho") is None and not (tmp / "backlog" / "estado.json").exists()   # ni se crea el fichero


def test_estado_json_roto_se_aparta_y_no_bloquea(mundo):
    g, tmp, *_ = mundo
    _sesion_con_pendientes(tmp)
    (tmp / "backlog").mkdir()
    (tmp / "backlog" / "estado.json").write_text('{"items": {"a": ', encoding="utf-8")
    d = backlog(g)
    r = d.items(True)
    assert len(r["items"]) == 3 and all(i["estado"] in ("abierto", "nueva") for i in r["items"])
    assert any("dañado" in a for a in r["avisos"])
    rotos = [p.name for p in (tmp / "backlog").iterdir() if p.name.startswith("estado.json.roto-")]
    assert len(rotos) == 1 and not (tmp / "backlog" / "estado.json").exists()
    assert (tmp / "backlog" / rotos[0]).read_text(encoding="utf-8") == '{"items": {"a": '       # se aparta, no se borra
    d.fijar_estado(r["items"][0]["id"], "hecho")                                                # y se puede seguir escribiendo
    assert json.loads((tmp / "backlog" / "estado.json").read_text(encoding="utf-8"))["items"]
    # forma inesperada (JSON válido pero no un objeto con items): lo mismo
    (tmp / "backlog" / "estado.json").write_text("[1, 2, 3]", encoding="utf-8")
    assert len(backlog(g).items(True)["items"]) == 3
    assert len([p for p in (tmp / "backlog").iterdir() if p.name.startswith("estado.json.roto-")]) == 2


def test_la_escritura_del_estado_es_atomica_y_solo_en_backlog(mundo, monkeypatch):
    g, tmp, *_ = mundo
    _sesion_con_pendientes(tmp)
    d = backlog(g)
    it = items(d.items(True))[0]
    llamadas = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (llamadas.append((Path(a).name, Path(b).name)), real(a, b))[1])
    d.fijar_estado(it["id"], "hecho" if it["tipo"] == "pendiente" else "aprovechada")
    assert llamadas == [("estado.json.tmp", "estado.json")]            # temporal + os.replace
    assert not (tmp / "backlog" / "estado.json.tmp").exists()
    with pytest.raises(RutaProhibida):                                    # sin carpeta de backlog configurada no se escribe en ninguna parte
        Guardian(tmp / "p", tmp / "b", tmp / "c").escribir_backlog_estado("{}")
    with pytest.raises(RutaProhibida):
        g._comprobar_escritura(tmp / "bandeja" / "2026-11-01-a.md", g.backlog)   # y el Guardian no deja escribir un .md de sesión desde esa carpeta


# ------------------------------------------------------------------ endpoints
def cliente(tmp_path, abridor=None, g=None, **kw):
    raiz = tmp_path / "proyectos"
    raiz.mkdir(exist_ok=True)
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", "proyectos_extra": []}, guardar=False)
    g = g or Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones", backlog=tmp_path / "backlog")
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), ModeloQueNoSeLlama(), dif.emitir)
    bl = Backlog(g, cfg, ahora=lambda: AHORA, abridor=abridor, **kw)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO, backlog=bl)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN})


def test_endpoints_listas_detalle_estado_tema_y_abrir(tmp_path):
    p = escribir(tmp_path / "bandeja", "2026-11-01-a.md", sesion_md(tema="Presupuesto", resumen="**Pendientes**\n- [05:00] Del resumen.", insights=[
        "- [01:00] **Pendiente:** Enviar tarifas.", "- [02:00] **Decisión:** Seguimos adelante."]))
    abiertos = []
    cli = cliente(tmp_path, abridor=abiertos.append)
    antes = hashes(tmp_path / "bandeja")
    with cli:
        assert cli.get("/api/backlog/sesiones", headers={"X-Token": "otro"}).status_code == 401
        r = cli.get("/api/backlog/sesiones").json()
        s = r["sesiones"][0]
        assert s["tema"] == "Presupuesto" and s["recuentos"]["pendiente"] == 2 and s["recuentos"]["decision"] == 1 and "items" not in s
        assert str(tmp_path) not in json.dumps(r)   # ninguna ruta del disco sale al navegador
        lista = cli.get("/api/backlog/items").json()["items"]
        assert sorted(i["tipo"] for i in lista) == ["decision", "pendiente", "pendiente"]
        det = cli.get(f"/api/backlog/sesiones/{s['id']}").json()
        assert len(det["items"]) == 3 and det["transcripcion"][0]["m"] == "00:05" and "Del resumen." in det["resumen"] and det["tema"] == "Presupuesto"
        pend = next(i for i in det["items"] if i["texto"] == "Enviar tarifas.")
        r = cli.put(f"/api/backlog/items/{pend['id']}", json={"estado": "hecho"})
        assert r.status_code == 200 and r.json()["estado"] == "hecho"
        assert next(i for i in cli.get("/api/backlog/items").json()["items"] if i["id"] == pend["id"])["estado"] == "hecho"
        deci = next(i for i in det["items"] if i["tipo"] == "decision")
        assert cli.put(f"/api/backlog/items/{deci['id']}", json={"estado": "hecho"}).status_code == 400   # las decisiones solo se consultan
        assert cli.put(f"/api/backlog/items/{pend['id']}", json={"estado": "inventado"}).status_code == 400
        r = cli.put(f"/api/backlog/sesiones/{s['id']}/tema", json={"tema": "Presupuesto — pricing"})
        assert r.status_code == 200 and r.json()["tema"] == "Presupuesto — pricing"
        assert cli.put(f"/api/backlog/sesiones/{s['id']}/tema", json={"tema": "x" * 500}).status_code == 400
        assert cli.get("/api/backlog/sesiones").json()["sesiones"][0]["tema"] == "Presupuesto — pricing"
        assert cli.post(f"/api/backlog/sesiones/{s['id']}/abrir").json() == {"ok": True, "archivo": "2026-11-01-a.md"}
    assert abiertos == [str(p)]
    assert hashes(tmp_path / "bandeja") == antes                     # el .md ni se tocó: ni el contenido ni la fecha
    assert json.loads((tmp_path / "backlog" / "estado.json").read_text(encoding="utf-8"))["temas"]


@pytest.mark.parametrize("malo", ["..", "../../datos/config", "..%2F..%2Fdatos%2Fconfig.json", "%2e%2e%2f%2e%2e%2fCLAUDE.md", "..\\..\\CLAUDE.md", "C:\\Windows\\win.ini",
                                  "2026-11-01-a.md", "2026-11-01-a", "0" * 15, "0" * 17, "G" * 16, "0" * 16 + "%00", "%00", "a b"])
def test_path_traversal_en_los_endpoints(tmp_path, malo):
    escribir(tmp_path / "bandeja", "2026-11-01-a.md", sesion_md())
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / "config.json").write_text("SECRETO-DE-PRUEBA", encoding="utf-8")
    abiertos = []
    cli = cliente(tmp_path, abridor=abiertos.append)
    with cli:
        for r in (cli.get(f"/api/backlog/sesiones/{malo}"), cli.put(f"/api/backlog/items/{malo}", json={"estado": "hecho"}),
                  cli.put(f"/api/backlog/sesiones/{malo}/tema", json={"tema": "x"}), cli.post(f"/api/backlog/sesiones/{malo}/abrir")):
            assert r.status_code in (400, 404, 405, 422), (malo, r.status_code)
            assert "SECRETO-DE-PRUEBA" not in r.text and "Windows" not in r.text.split("detail")[0]
        # un id con la forma correcta pero desconocido: 404, y nunca se abre nada
        assert cli.post(f"/api/backlog/sesiones/{'0' * 16}/abrir").status_code == 404
    assert abiertos == [] and not (tmp_path / "backlog" / "estado.json").exists()


def test_el_endpoint_de_abrir_solo_abre_ficheros_de_sesion_ya_listados(tmp_path):
    escribir(tmp_path / "bandeja", "2026-11-01-a.md", sesion_md())
    escribir(tmp_path, "CLAUDE.md", "no es una sesión")
    abiertos = []
    cli = cliente(tmp_path, abridor=abiertos.append)
    with cli:
        sid = cli.get("/api/backlog/sesiones").json()["sesiones"][0]["id"]
        assert cli.post(f"/api/backlog/sesiones/{sid}/abrir", json={"ruta": str(tmp_path / "CLAUDE.md")}).status_code == 200   # el cuerpo se ignora: solo cuenta el id
        assert cli.post(f"/api/backlog/sesiones/{sid}/abrir?ruta=../CLAUDE.md").status_code == 200
    assert abiertos == [str(tmp_path / "bandeja" / "2026-11-01-a.md")] * 2


def test_endpoints_sin_carpeta_de_estado_leen_pero_no_escriben(tmp_path):
    escribir(tmp_path / "bandeja", "2026-11-01-a.md", sesion_md(insights=["- [01:00] **Pendiente:** Enviar tarifas."]))
    raiz = tmp_path / "proyectos"
    raiz.mkdir()
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")   # sin backlog=
    cli = cliente(tmp_path, g=g)
    with cli:
        it = cli.get("/api/backlog/items").json()["items"][0]
        assert it["estado"] == "abierto"
        assert cli.put(f"/api/backlog/items/{it['id']}", json={"estado": "hecho"}).status_code == 403


def test_el_servidor_lento_de_una_carpeta_no_tumba_la_api(tmp_path):
    raiz = tmp_path / "proyectos"
    raiz.mkdir()
    ajena = tmp_path / "ajena"
    ajena.mkdir()
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones", backlog=tmp_path / "backlog",
                 extras=[{"nombre": "Lenta", "ruta": str(ajena), "compartido": True}])
    suelta = threading.Event()
    original = g.listar_sesiones_md
    g.listar_sesiones_md = lambda c, tope=2000: (suelta.wait(10), original(c, tope))[1] if "ajena" in str(c) else original(c, tope)
    escribir(tmp_path / "bandeja", "2026-11-01-a.md", sesion_md())
    cli = cliente(tmp_path, g=g, tiempo_fuente_s=0.3)
    with cli:
        t0 = time.monotonic()
        r = cli.get("/api/backlog/sesiones").json()
        assert time.monotonic() - t0 < 3 and len(r["sesiones"]) == 1 and any("tarda en responder" in a for a in r["avisos"])
    suelta.set()


def test_utilidades_de_texto_y_minutos():
    assert normalizar("  ¿Qué  Decisión, ÚLTIMA…? ") == "que decision ultima"
    assert BL.a_segundos("03:48") == 228 and BL.a_segundos("112:05") == 6725 and BL.a_segundos("1:02:03") == 3723 and BL.a_segundos("xx") is None and BL.a_segundos(None) is None
    assert BL.a_mmss(228) == "03:48"
    assert BL.tipo_de("Posible contradicción") == ("contradiccion", True, False) and BL.tipo_de("Idea (tú)") == ("idea", False, True) and BL.tipo_de("Definición")[0] is None
    assert BL.tipo_apartado("Preguntas y riesgos abiertos") == ("pregunta", True) and BL.tipo_apartado("Pendientes (ninguno con responsable asignado)") == ("pendiente", False)
    assert BL.tipo_apartado("Próximos pasos")[0] is None and BL.tipo_apartado("Puntos abiertos")[0] is None


# ------------------------------------------------------------------ interfaz (estáticos y, si hay Edge, con la página real y datos ficticios)
WEB = Path(__file__).resolve().parent.parent / "web"


def test_ui_estaticos_el_boton_la_pantalla_y_sin_html_inyectado():
    html = (WEB / "index.html").read_text(encoding="utf-8")
    js = (WEB / "backlog.js").read_text(encoding="utf-8")
    css = (WEB / "backlog.css").read_text(encoding="utf-8")
    assert 'id="b-sesiones"' in html and 'id="v-backlog"' in html and "/static/backlog.js" in html and "/static/backlog.css" in html
    for prohibido in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", 'setAttribute("href"', "srcdoc"):
        assert prohibido not in js, prohibido
    assert "backdrop-filter" not in css and "will-change" not in css and "gradient" not in css          # DESIGN-visual.md §6: sin filtros ni gradientes en listas
    assert not re.findall(r"font-size: (?!var\(--f-)", re.sub(r"/\*.*?\*/", "", css, flags=re.S))      # la escala tipográfica va por variable
    assert "fetch(" not in js and "http://" not in js.replace("http://www.w3.org/2000/svg", "")        # sin red: solo la API local por el `api()` de app.js


SES_UI = [{"id": "a" * 16, "tema": "Seguimiento ficticio", "tema_original": "Seguimiento ficticio", "renombrado": False, "proyecto": "Bandeja", "fecha": "2026-11-05", "inicio": "11:05",
           "duracion": "27:39", "estado": "finalizada", "estado_texto": "Finalizada", "origen": "bandeja", "archivo": "2026-11-05-seguimiento.md", "vinculada": None,
           "recuentos": {"pendiente": 2, "idea": 1, "decision": 1, "riesgo": 0, "pregunta": 0, "regla": 0, "contradiccion": 0}, "total": 4, "n_transcripcion": 3, "avisos": [], "busqueda": "enviar tarifas"},
          {"id": "b" * 16, "tema": "Sin cerrar", "tema_original": "Sin cerrar", "renombrado": False, "proyecto": "Otro", "fecha": "2026-11-04", "inicio": "18:15", "duracion": "10:10",
           "estado": "sin_cerrar", "estado_texto": "Sin cerrar", "origen": "bandeja", "archivo": "2026-11-04-sin-cerrar.md", "vinculada": None,
           "recuentos": {t: 0 for t in BL.TIPOS}, "total": 0, "n_transcripcion": 0, "avisos": [], "busqueda": ""}]


def _item(n, tipo, texto, minuto, estado):
    return {"id": f"{n:016x}", "sesion_id": "a" * 16, "tipo": tipo, "etiqueta": BL.ETIQUETA[tipo], "texto": texto, "minuto": minuto, "t": BL.a_segundos(minuto), "responsable": None, "contexto": None,
            "origen": "insight", "posible": False, "recortado": False, "completado": False, "estados": list(BL.ESTADOS.get(tipo, ())), "estado": estado, "sesion_tema": "Seguimiento ficticio",
            "proyecto": "Bandeja", "fecha": "2026-11-05", "inicio": "11:05", "sesion_estado": "finalizada"}


ITEMS_UI = [_item(1, "pendiente", "Enviar tarifas", "00:20", "abierto"), _item(2, "pendiente", "Llamar al cliente", "00:40", "hecho"),
            _item(3, "idea", "Un solo hotel", "00:50", "nueva"), _item(4, "decision", "Seguimos adelante", "01:00", None)]
DET_UI = {**SES_UI[0], "resumen": "**Pendientes**\n- [00:20] Enviar tarifas\n\n<img src=x onerror=\"document.title='HACKEADO'\"> y <script>document.title='HACKEADO'</script> [enlace](javascript:alert(1))",
          "items": ITEMS_UI, "definiciones": [],
          "transcripcion": [{"t": 5, "m": "00:05", "f": "Reunión", "x": "Hola"}, {"t": 20, "m": "00:20", "f": "Micro", "x": "Enviamos las tarifas"}, {"t": 65, "m": "01:05", "f": "Reunión", "x": "Adiós"}]}

STUB_BACKLOG = """<script>
(() => {
  const SES = %s, ITEMS = %s, DET = %s; const previa = window.fetch; window.__llamadas = [];
  window.fetch = async (u, o) => {
    u = String(u); if (!u.includes('/api/backlog/')) return previa(u, o);
    const metodo = (o && o.method) || 'GET'; const cuerpo = o && o.body ? JSON.parse(o.body) : null; window.__llamadas.push([metodo, u, cuerpo]);
    let datos = {};
    if (u.includes('/api/backlog/sesiones/') && metodo === 'GET') datos = DET;
    else if (u.includes('/api/backlog/sesiones')) datos = { sesiones: SES, proyectos: ['Bandeja', 'Otro'], avisos: ['Aviso de prueba'] };
    else if (u.includes('/api/backlog/items') && metodo === 'GET') datos = { items: ITEMS, tipos: [], avisos: [] };
    else if (u.includes('/api/backlog/items/')) { const it = ITEMS.find((i) => u.endsWith(i.id)); it.estado = cuerpo.estado; datos = it; }
    return { ok: true, status: 200, json: async () => datos };
  };
})();
</script>""" % tuple(json.dumps(x).replace("</", "<\\/") for x in (SES_UI, ITEMS_UI, DET_UI))   # «</script>» dentro del JSON cerraría la etiqueta


def test_ui_pantalla_sesiones_con_datos_ficticios_en_el_navegador(tmp_path):
    import socket

    from _visual_harness import Edge, pagina_html
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        puerto = s.getsockname()[1]
    pagina = pagina_html(tmp_path / "app.html")
    pagina.write_text(pagina.read_text(encoding="utf-8").replace("</head>", STUB_BACKLOG + "</head>", 1), encoding="utf-8")
    e = Edge(tmp_path, puerto)
    try:
        e.abrir(pagina.as_uri(), "!window.__viejo && !!document.querySelector('#b-sesiones') && !!window.AP && !!AP.backlog")
        e.js("document.querySelector('#b-sesiones').click(); 1")
        for _ in range(40):
            if e.js("document.querySelectorAll('.bl-ses').length") == 2:
                break
            time.sleep(0.15)
        assert e.js("document.querySelectorAll('.bl-ses').length") == 2 and e.js("document.querySelector('#bl-avisos').hidden") is False
        assert "Sin cerrar" in e.js("document.querySelectorAll('.bl-ses')[1].textContent")
        e.js("document.querySelectorAll('.bl-ses')[0].click(); 1")
        for _ in range(40):
            if e.js("!!document.querySelector('.bl-md')"):
                break
            time.sleep(0.15)
        # markdown seguro: el HTML crudo se ve como texto, no crea elementos ni ejecuta nada, y los enlaces no se siguen
        assert e.js("document.querySelectorAll('.bl-md img, .bl-md script, .bl-md a').length") == 0 and e.js("document.title") == "WhisperMeet"
        assert "<img src=x" in e.js("document.querySelector('.bl-md').textContent") and e.js("document.querySelectorAll('.bl-md .bl-min').length") >= 1
        # lista conjunta: por defecto solo pendientes abiertos
        e.js("document.querySelector('#bl-t-pendientes').click(); 1")
        time.sleep(0.4)
        assert e.js("[...document.querySelectorAll('.bl-it .bl-it-tx')].map((x) => x.textContent).join('|')") == "Enviar tarifas"
        e.js("document.querySelector('.bl-it [data-estado=hecho]').click(); 1")
        time.sleep(0.5)
        assert e.js("window.__llamadas.filter((l) => l[0] === 'PUT')") == [["PUT", "/api/backlog/items/" + f"{1:016x}", {"estado": "hecho"}]]
        assert e.js("document.querySelectorAll('.bl-it').length") == 0                       # sale de «abiertos»
        e.js("(() => { document.querySelector('.bl-chip[data-tipo=decision]').click(); const s = document.querySelector('#bl-f-estado'); s.value = 'todos'; s.dispatchEvent(new Event('change')); return 1; })()")
        time.sleep(0.4)
        assert e.js("document.querySelectorAll('.bl-it').length") == 3 and e.js("document.querySelectorAll('.bl-it[data-tipo=decision] .bl-estados').length") == 0   # las decisiones solo se consultan
        # el minuto lleva a la transcripción con la línea resaltada
        e.js("document.querySelector('.bl-it .bl-min').click(); 1")
        time.sleep(0.6)
        assert e.js("document.querySelector('.bl-lin.destino') && document.querySelector('.bl-lin.destino').dataset.t") == "20"
    finally:
        e.cerrar()


# ------------------------------------------------------------------ ola 1: consejos tras «## Asesor», pendientes repetidos
def test_consejos_del_asesor_cuentan_aunque_asesor_vaya_antes_que_insights():
    md = sesion_md(tema="X", insights=["- [01:00] **Decisión:** Hacemos X."])
    asesor = ("## Asesor\n\n### Consejos\n\n- [02:00] **Consejo (valor):** Proponer un piloto — por qué: baja el riesgo\n"
              "- [03:30] **Consejo (cierre):** Fijar la fecha — por qué: mantiene el ritmo\n\n## Insights")
    md = md.replace("## Insights", asesor, 1)   # «## Asesor» va ANTES que «## Insights», como lo escribe Sesion.render
    r = parsear_sesion(md, "2026-11-01-x.md")
    assert [i["tipo"] for i in r["items"]].count("consejo") == 2
    assert any(i["tipo"] == "decision" for i in r["items"])


def test_pendiente_repetido_sale_una_vez_con_el_numero_de_sesiones(mundo):
    g, tmp, *_ = mundo
    textos = ["Enviar el listado de habitaciones al cliente", "enviar el listado de habitaciónes al cliente.", "¡Enviar el listado de habitaciones al  cliente!"]
    for n, t in enumerate(textos):
        escribir(tmp / "bandeja", f"2026-11-0{n + 1}-r.md", sesion_md(tema=f"S{n}", fecha=f"2026-11-0{n + 1}", insights=[f"- [01:00] **Pendiente:** {t}", "- [02:00] **Pendiente:** Otro distinto."]))
    d = backlog(g)
    pend = [i for i in d.items()["items"] if i["tipo"] == "pendiente"]
    repetido = [i for i in pend if clave_repetido(i["texto"]) == clave_repetido(textos[0])]
    assert len(repetido) == 1 and repetido[0]["veces"] == 3 and repetido[0]["sesion_tema"] == "S2"   # el de la sesión más reciente
    assert len([i for i in pend if i["texto"].startswith("Otro")]) == 1 and len(pend) == 2
    (proy,) = d.resumen_proyectos().values()
    assert proy["abiertos"] == 2 and {p["texto"] for p in proy["pendientes"]} == {repetido[0]["texto"], "Otro distinto."}
    assert next(p for p in proy["pendientes"] if p["texto"] == repetido[0]["texto"])["veces"] == 3
