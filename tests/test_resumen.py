"""Resumen visual por proyecto (apuntes/resumen.py, GET /api/proyectos/resumen y /pendientes). Todo con árboles ficticios en tmp_path."""
import json
import os
import time
from datetime import date

from fastapi.testclient import TestClient

from apuntes import resumen as RS
from apuntes.backlog import Backlog
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, Guardian
from apuntes.servidor import Difusor, crear_app
from test_backlog import sesion_md
from test_gestor_plan import Falso, lineas

PUERTO, TOKEN = 8127, "t0k3n"
HOY = date(2026, 11, 7)            # sábado


def escribir(p, texto):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8", newline="\n")
    return p


# ---------------------------------------------------------------- descripción
def test_frase_toma_la_primera_frase_con_sentido_y_quita_markdown():
    md = "# Ficha\n\n| Campo | Valor |\n|---|---|\n\n**Cliente:** Demo SA\n\nEste proyecto **ordena** las [reservas de grupos](http://x.y) del hotel ficticio. Segunda frase que no sale.\n"
    assert RS.frase_descriptiva(md) == "Este proyecto ordena las reservas de grupos del hotel ficticio."


def test_frase_nunca_sale_de_contactos_ni_de_lineas_con_pinta_de_secreto_o_personales():
    md = ("# Ficha\n\n## Contactos\n\nPara cualquier duda llamar a la responsable del proyecto al despacho principal.\n\n## Resumen\n\n"
          "La contraseña de acceso al portal es la que enviamos por correo a todo el equipo.\n"
          "Escribe a ana.lopez@ejemplo.test para pedir acceso al repositorio del proyecto completo.\n"
          "Llamar al 600 111 222 para coordinar las visitas de obra con la propiedad del solar.\n"
          "token: abcdef123456 en el fichero de entorno que usa la aplicacion del proyecto.\n"
          "Plataforma ficticia para planificar visitas de obra de una promotora.\n")
    assert RS.frase_descriptiva(md) == "Plataforma ficticia para planificar visitas de obra de una promotora."
    assert RS.frase_descriptiva("## Contactos\n\nPersona de contacto principal del proyecto en el cliente final.\n") is None


def test_frase_recorta_a_140_y_descarta_plantillas_sin_rellenar():
    larga = "Este documento describe con mucho detalle " + "un conjunto enorme de procesos de negocio interrelacionados " * 6 + "y termina."
    f = RS.frase_descriptiva(larga)
    assert f is not None and len(f) <= 140 and f.endswith("…")
    assert RS.frase_descriptiva("# Ficha\n\n{{CLIENTE}} describe aquí el objetivo del proyecto en una frase corta.\n") is None
    assert RS.frase_descriptiva("---\ntitulo: x\nautor: y\n---\n# T\n\nPanel de seguimiento mensual para la dirección comercial ficticia.\n") == \
        "Panel de seguimiento mensual para la dirección comercial ficticia."


def test_frase_salta_metadatos_de_la_ficha():
    md = ("# 01 · Ficha\n\nÚltima actualización: 2026-10-01 · Persona Ficticia\n\n## Datos\n\n| a | b |\n|---|---|\n| Cliente | Demo |\n\n"
          "Responsable: Persona Uno del equipo de proyecto ficticio\n")
    assert RS.frase_descriptiva(md) is None


# ---------------------------------------------------------------- semanas, calidad, hito
def test_sesiones_por_semana_ocho_semanas_la_ultima_es_la_actual():
    fechas = ["2026-11-02", "2026-11-06", "2026-10-27", "2026-09-14", "2026-09-13", "2026-08-01", "x"]
    # semana actual = lunes 2 nov; la anterior = 26 oct; la más antigua de las 8 = lunes 14 sep
    assert RS.sesiones_por_semana(fechas, HOY) == [1, 0, 0, 0, 0, 0, 1, 2]
    assert RS.sesiones_por_semana([], HOY) == [0] * 8


def test_calidad_niveles_y_motivos():
    c = RS.calidad_contexto
    assert c(n_md=0, n_ctx=0, n_contenido=0, dias=None, hay_claude=False)["nivel"] == 0
    r1 = c(n_md=2, n_ctx=0, n_contenido=0, dias=None, hay_claude=True)
    assert r1["nivel"] == 1 and any("00. CONTEXTO (IA)" in m for m in r1["motivos"])
    r2 = c(n_md=5, n_ctx=2, n_contenido=1, dias=10, hay_claude=True)
    assert r2["nivel"] == 2 and any("3 o más" in m for m in r2["motivos"])
    r3 = c(n_md=9, n_ctx=5, n_contenido=4, dias=10, hay_claude=True)
    assert r3["nivel"] == 3 and r3["motivos"] == []
    r4 = c(n_md=9, n_ctx=5, n_contenido=4, dias=200, hay_claude=True)
    assert r4["nivel"] == 2 and any("200 días" in m for m in r4["motivos"])


def test_proximo_hito_del_plan():
    plan = {"gantt": {"hitos": [{"id": "h1", "nombre": "Piloto", "fecha_iso": "2026-11-20", "fecha_texto": "20 nov"},
                                {"id": "h2", "nombre": "Cierre", "fecha_iso": "", "fecha_texto": "por definir"}], "proximos_hitos": ["h1", "h2"]}}
    assert RS.proximo_hito(plan) == {"nombre": "Piloto", "fecha_iso": "2026-11-20", "fecha_texto": "20 nov"}
    assert RS.proximo_hito(None) is None and RS.proximo_hito({"gantt": {"hitos": [], "proximos_hitos": []}}) is None


# ---------------------------------------------------------------- resumen sobre un árbol
def arbol(tmp_path):
    raiz = tmp_path / "proyectos"
    a = raiz / "Alfa Ficticio"
    escribir(a / CARPETA_CONTEXTO / "01-ficha-del-proyecto.md", "# Ficha\n\n## Contactos\n\nLlamar a Persona Uno al despacho para cualquier duda del cliente.\n\n## Qué es\n\nPortal ficticio para gestionar las reservas de grupos de una cadena hotelera.\n")
    for n in ("02-alcance.md", "04-plan.md"):
        escribir(a / CARPETA_CONTEXTO / n, "# T\n" + "Contenido de alcance y plan del proyecto ficticio. " * 12)
    escribir(a / CARPETA_SESIONES / "2026-11-04-seguimiento.md", "# s")
    escribir(a / CARPETA_SESIONES / "2026-11-05-otra.md", "# s")
    escribir(raiz / "Beta Sin Nada" / "datos.txt", "x")
    escribir(raiz / "Gamma Claude" / "CLAUDE.md", "# Reglas\n\nAplicación interna ficticia para repartir tareas entre los equipos de soporte.\n")
    return raiz


def test_resumir_arbol_ficticio(tmp_path):
    raiz = arbol(tmp_path)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")
    lista = RS.CX.listar_proyectos(g)
    r = RS.resumir(g, lista, {}, {}, {"alfa ficticio": 3}, HOY)
    m = r["resumen"]
    assert r["parcial"] is False
    a = m["Alfa Ficticio"]
    assert a["descripcion"] == "Portal ficticio para gestionar las reservas de grupos de una cadena hotelera."
    assert a["sesiones_por_semana"] == [0, 0, 0, 0, 0, 0, 0, 2] and a["pendientes_abiertos"] == 3
    assert a["calidad_contexto"]["nivel"] == 3 and a["calidad_contexto"]["motivos"] == []
    assert m["Beta Sin Nada"]["calidad_contexto"]["nivel"] == 0 and m["Beta Sin Nada"]["descripcion"] is None
    assert m["Beta Sin Nada"]["pendientes_abiertos"] == 0
    gm = m["Gamma Claude"]
    assert gm["descripcion"].startswith("Aplicación interna ficticia") and gm["calidad_contexto"]["nivel"] == 1
    assert "Persona Uno" not in json.dumps(m, ensure_ascii=False)                   # la sección «Contactos» no sale


def test_pendientes_none_omite_el_campo(tmp_path):
    raiz = arbol(tmp_path)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")
    r = RS.resumir(g, RS.CX.listar_proyectos(g), {}, {}, None, HOY)
    assert all("pendientes_abiertos" not in v for v in r["resumen"].values())


def test_un_proyecto_lento_sale_sin_campos_y_no_bloquea(tmp_path, monkeypatch):
    raiz = arbol(tmp_path)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")
    RS._CACHE.clear()
    original = RS._calcular

    def lento(g_, nombre, *a, **k):
        if nombre == "Beta Sin Nada":
            time.sleep(1.5)
        return original(g_, nombre, *a, **k)
    monkeypatch.setattr(RS, "_calcular", lento)
    t0 = time.monotonic()
    r = RS.resumir(g, RS.CX.listar_proyectos(g), {}, {}, {}, HOY, plazo_s=0.3)
    assert time.monotonic() - t0 < 1.2 and r["parcial"] is True
    assert "calidad_contexto" not in r["resumen"]["Beta Sin Nada"] and "calidad_contexto" in r["resumen"]["Alfa Ficticio"]
    time.sleep(1.4)   # el hilo termina y deja la caché lista
    r2 = RS.resumir(g, RS.CX.listar_proyectos(g), {}, {}, {}, HOY, plazo_s=0.3)
    assert r2["parcial"] is False


def test_la_cache_se_invalida_al_cambiar_el_contexto(tmp_path):
    raiz = arbol(tmp_path)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")
    RS._CACHE.clear()
    lista = RS.CX.listar_proyectos(g)
    assert RS.resumir(g, lista, {}, {}, {}, HOY)["resumen"]["Gamma Claude"]["calidad_contexto"]["nivel"] == 1
    escribir(raiz / "Gamma Claude" / CARPETA_CONTEXTO / "01-ficha.md", "# F\n" + "Texto de la ficha ficticia con bastante contenido. " * 10)
    st = os.stat(raiz / "Gamma Claude")
    os.utime(raiz / "Gamma Claude", ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
    assert RS.resumir(g, lista, {}, {}, {}, HOY)["resumen"]["Gamma Claude"]["calidad_contexto"]["nivel"] >= 2


# ---------------------------------------------------------------- API
def cliente(tmp_path):
    raiz = arbol(tmp_path)
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones", backlog=tmp_path / "backlog")
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), Falso(), dif.emitir, simulacion=lineas(), velocidad=200)
    bl = Backlog(g, cfg)
    return TestClient(crear_app(gestor, dif, cfg, g, TOKEN, PUERTO, backlog=bl), base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN}), raiz


def test_api_resumen_y_pendientes_abiertos(tmp_path):
    cli, raiz = cliente(tmp_path)
    escribir(raiz / "Alfa Ficticio" / CARPETA_SESIONES / "2026-11-04-seguimiento.md", sesion_md(
        tema="Seguimiento", fecha="2026-11-04", proyecto="Alfa Ficticio",
        insights=["- [01:00] **Pendiente:** Enviar el listado de habitaciones al cliente (Ana)", "- [02:00] **Pendiente:** Revisar el presupuesto de la fase uno",
                  "- [03:00] **Decisión:** Se aprueba el alcance de la primera fase"]))
    with cli:
        r = cli.get("/api/proyectos/resumen").json()
        a = r["resumen"]["Alfa Ficticio"]
        assert a["pendientes_abiertos"] == 2 and len(a["sesiones_por_semana"]) == 8 and a["descripcion"].startswith("Portal ficticio")
        assert r["resumen"]["Beta Sin Nada"]["pendientes_abiertos"] == 0
        assert str(raiz) not in json.dumps(r)                                      # ninguna ruta del disco sale por la API
        p = cli.get("/api/proyectos/Alfa Ficticio/pendientes").json()
        assert p["total"] == 2 and len(p["pendientes"]) == 2 and {x["texto"] for x in p["pendientes"]} >= {"Revisar el presupuesto de la fase uno"}
        # marcar uno como hecho: baja el recuento (el estado local vive en backlog/estado.json)
        assert cli.put(f"/api/backlog/items/{p['pendientes'][0]['id']}", json={"estado": "hecho"}).status_code == 200
        assert cli.get("/api/proyectos/resumen").json()["resumen"]["Alfa Ficticio"]["pendientes_abiertos"] == 1
        assert cli.get("/api/proyectos/Alfa Ficticio/pendientes").json()["total"] == 1
        assert cli.get("/api/proyectos/NoExiste/pendientes").json()["total"] == 0
