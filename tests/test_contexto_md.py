"""Contexto ampliado (00. CONTEXTO + CLAUDE.md/AGENTS.md/README.md + todos los .md del proyecto) y vista previa de la pantalla de inicio.
Todo con un árbol ficticio en tmp_path."""
import os
import time

from fastapi.testclient import TestClient

from apuntes import contexto as CX
from apuntes.backlog import Backlog
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, Guardian
from apuntes.servidor import Difusor, crear_app
from test_gestor_plan import Falso, lineas

PUERTO, TOKEN = 8124, "t0k3n"
PROY = "Proyecto Ficticio"


def escribir(p, texto="# Titulo\nContenido de prueba con varias palabras para que no sea vacio."):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(texto, encoding="utf-8")
    return p


def arbol(tmp_path):
    raiz = tmp_path / "proyectos"
    p = raiz / PROY
    escribir(p / CARPETA_CONTEXTO / "02-alcance.md", "# Alcance\n" + "El alcance incluye informes y paneles de ventas. " * 12)
    escribir(p / CARPETA_CONTEXTO / "00-INDICE.md", "# Indice\nno se analiza")
    escribir(p / CARPETA_CONTEXTO / "equipos" / "LEEME.md", "# Equipos\n" + "Quien hace que dentro del equipo. " * 12)
    escribir(p / "CLAUDE.md", "# Reglas\nUsar Python 3.12 y probar antes de entregar.")
    escribir(p / "AGENTS.md", "# Agentes\nNo tocar produccion.")
    escribir(p / "README.md", "# Leeme\nApp ficticia.\n## Contactos\nPersona 600111222\n")
    escribir(p / "docs" / "arquitectura.md", "# Arquitectura\nTres capas.")
    escribir(p / "docs" / "a" / "b" / "c" / "d" / "e" / "muy-hondo.md", "# Hondo\nno entra por profundidad")
    escribir(p / "notas" / "ideas.md", "# Ideas\nUna idea.")
    escribir(p / CARPETA_SESIONES / "2026-11-01-reunion.md", "# Sesion\nesto no es contexto")
    escribir(p / "node_modules" / "x" / "leeme.md", "# no")
    escribir(p / ".oculta" / "n.md", "# no")
    escribir(p / "dist" / "gen.md", "# no")
    escribir(p / "docs" / "credenciales.md", "usuario admin")
    escribir(p / "docs" / "notas.txt", "no es md")
    return raiz, p


def guardian(tmp_path, raiz):
    return Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")


def test_lista_los_md_con_prioridad_y_exclusiones(tmp_path):
    raiz, p = arbol(tmp_path)
    g = guardian(tmp_path, raiz)
    r = CX.listar_md(g, PROY)
    rels = [e["rel"] for e in r["ficheros"]]
    assert rels[:4] == [f"{CARPETA_CONTEXTO}/02-alcance.md", f"{CARPETA_CONTEXTO}/00-INDICE.md", f"{CARPETA_CONTEXTO}/equipos/LEEME.md", "CLAUDE.md"]
    assert rels[4:6] == ["AGENTS.md", "README.md"]
    assert set(rels[6:]) == {"docs/arquitectura.md", "notas/ideas.md"}
    for fuera in ("node_modules", ".oculta", "dist", CARPETA_SESIONES, "credenciales", "muy-hondo", "notas.txt"):
        assert not any(fuera in x for x in rels)
    assert {e["grupo"] for e in r["ficheros"] if e["rel"] == "CLAUDE.md"} == {"raiz"}


def test_los_otros_md_van_por_cercania_y_novedad(tmp_path):
    raiz, p = arbol(tmp_path)
    escribir(p / "uno.md")
    escribir(p / "x" / "y" / "profundo.md")
    os.utime(p / "docs" / "arquitectura.md", (2_000_000_000, 2_000_000_000))
    os.utime(p / "notas" / "ideas.md", (1_700_000_000, 1_700_000_000))
    r = CX.listar_md(guardian(tmp_path, raiz), PROY)
    otros = [e["rel"] for e in r["ficheros"] if e["grupo"] == "otros"]
    assert otros == ["uno.md", "docs/arquitectura.md", "notas/ideas.md", "x/y/profundo.md"]


def test_topes_de_ficheros_tamano_y_profundidad(tmp_path):
    raiz, p = arbol(tmp_path)
    escribir(p / "grande.md", "x" * 5000)
    g = guardian(tmp_path, raiz)
    r = CX.listar_md(g, PROY, max_ficheros=5, tope_bytes=1000)
    estado = {e["rel"]: e["dejado"] for e in r["ficheros"]}
    assert estado["grande.md"] == "tamaño"                     # pasa del tope por fichero: no se lee
    assert sum(1 for v in estado.values() if v == "límite") >= 3
    assert estado["CLAUDE.md"] == ""                            # lo prioritario entra
    assert not any("muy-hondo" in k for k in estado)            # profundidad por defecto (4)
    hondo = CX.listar_md(g, PROY, profundidad=6)["ficheros"]
    assert any("muy-hondo" in e["rel"] for e in hondo)
    plano = CX.listar_md(g, PROY, profundidad=0)["ficheros"]
    assert all("/" not in e["rel"] for e in plano)


def test_contexto_ampliado_junta_todo_sin_secretos_ni_contactos(tmp_path):
    raiz, p = arbol(tmp_path)
    escribir(p / "docs" / "claves.md", "Nota\npassword: hunter2hunter2\n")
    ficheros, grupos, solo_lectura = CX.contexto_ampliado(guardian(tmp_path, raiz), PROY)
    assert solo_lectura is False
    assert list(ficheros)[:2] == ["02-alcance.md", "00-INDICE.md"]
    assert "equipos/LEEME.md" in ficheros and grupos["equipos/LEEME.md"] == "ctx"
    assert "CLAUDE.md" in ficheros and "AGENTS.md" in ficheros and "docs/arquitectura.md" in ficheros
    assert "Persona" not in ficheros["README.md"] and "hunter2" not in ficheros["docs/claves.md"]
    assert not any("sesiones" in k.lower() or "node_modules" in k for k in ficheros)


def test_digest_prioriza_00_y_deja_hueco_a_la_raiz_y_la_clave_cambia_con_el_conjunto(tmp_path):
    raiz, p = arbol(tmp_path)
    escribir(p / CARPETA_CONTEXTO / "03-grande.md", "# Grande\n" + "palabra distinta " * 900)
    g = guardian(tmp_path, raiz)
    f = CX.fuentes_digest(g, PROY, "t", None, 9000)
    nombres = [e for e, _ in f.textos]
    assert nombres[0] == "02-alcance.md" and "00-INDICE.md" not in nombres
    assert "CLAUDE.md" in nombres                                # 00 no se come el 100 % del tope
    assert sum(len(t) for _, t in f.textos) <= 9000
    clave = f.clave
    assert CX.fuentes_digest(g, PROY, "t", None, 9000).clave == clave
    escribir(p / "zzz" / "nuevo.md", "# Nuevo\nOtro documento mas.")   # el conjunto cambia, aunque no quepa en el tope
    assert CX.fuentes_digest(g, PROY, "t", None, 9000).clave != clave


def test_sin_00_el_proyecto_es_solo_lectura_y_con_00_no_se_escribe_nada_mas(tmp_path):
    raiz, p = arbol(tmp_path)
    antes = sorted(str(x.relative_to(p)) for x in p.rglob("*"))
    g = guardian(tmp_path, raiz)
    CX.fuentes_digest(g, PROY, "t", None)
    CX.listar_md(g, PROY)
    assert sorted(str(x.relative_to(p)) for x in p.rglob("*")) == antes
    escribir(raiz / "Libre" / "README.md", "# Libre\n" + "texto de prueba suficiente " * 5)
    assert CX.fuentes_digest(g, "Libre", "t", None).solo_lectura is True


def test_estimar_uso_marca_los_que_no_caben(tmp_path):
    raiz, p = arbol(tmp_path)
    for i in range(6):
        escribir(p / f"doc{i}.md", "# D\n" + "x" * 2900)
    r = CX.listar_md(guardian(tmp_path, raiz), PROY)["ficheros"]
    CX.estimar_uso(r, 8000)
    por = {e["rel"]: e for e in r}
    assert por["CLAUDE.md"]["en_digest"] is True
    assert por[f"{CARPETA_CONTEXTO}/00-INDICE.md"]["dejado"] == "no se analiza"
    assert any(e["dejado"] == "texto" for e in r)


def test_metadatos_de_proyecto_n_sesiones_ultima_y_md(tmp_path):
    raiz, p = arbol(tmp_path)
    escribir(p / CARPETA_SESIONES / "2026-11-05-otra.md")
    g = guardian(tmp_path, raiz)
    lista = CX.enriquecer_proyectos(g, CX.listar_proyectos(g))
    m = {x["nombre"]: x for x in lista}[PROY]
    assert m["n_sesiones"] == 2 and m["ultima_sesion"] == "2026-11-05" and m["n_md"] == 8


# ---------------------------------------------------------------- API
def cliente(tmp_path, abiertos):
    raiz, p = arbol(tmp_path)
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", sesiones_locales=tmp_path / "sesiones")
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), Falso(), dif.emitir, simulacion=lineas(), velocidad=200)
    bl = Backlog(g, cfg, abridor=abiertos.append)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO, backlog=bl)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN}), p


def test_api_proyectos_trae_metadatos_y_el_contexto_agrupado(tmp_path):
    abiertos = []
    cli, p = cliente(tmp_path, abiertos)
    with cli:
        pr = {x["nombre"]: x for x in cli.get("/api/proyectos").json()["proyectos"]}[PROY]
        assert pr["n_sesiones"] == 1 and pr["ultima_sesion"] == "2026-11-01" and pr["n_md"] >= 8
        d = cli.get(f"/api/proyectos/{PROY}/contexto").json()
        assert [g["clave"] for g in d["grupos"]] == ["ctx", "raiz", "otros"]
        ctx = d["grupos"][0]["ficheros"]
        assert [f["nombre"] for f in ctx][:2] == ["02-alcance.md", "00-INDICE.md"]
        assert all(set(f) == {"id", "nombre", "rel", "tam", "dejado", "en_digest"} for g in d["grupos"] for f in g["ficheros"])
        assert d["solo_lectura"] is False and d["limites"]["max_ficheros"] == 80
        assert "ruta" not in str(d).lower().replace("rutas", "")   # ninguna ruta del disco sale por la API
        assert str(p) not in str(d)
        assert cli.get("/api/proyectos/NoExiste/contexto").status_code == 404


def test_api_abrir_solo_con_ids_del_servidor(tmp_path):
    abiertos = []
    cli, p = cliente(tmp_path, abiertos)
    with cli:
        d = cli.get(f"/api/proyectos/{PROY}/contexto").json()
        claude = next(f for g in d["grupos"] for f in g["ficheros"] if f["rel"] == "CLAUDE.md")
        assert cli.post(f"/api/proyectos/{PROY}/contexto/{claude['id']}/abrir").status_code == 200
        assert abiertos == [str(p / "CLAUDE.md")]
        # ids desconocidos, rutas y ids de otro proyecto: rechazados y no se abre nada
        for malo in ("0123456789abcdef", "C:/Windows/win.ini", "..%2F..%2Fx", "CLAUDE.md"):
            assert cli.post(f"/api/proyectos/{PROY}/contexto/{malo}/abrir").status_code in (404, 405)
        assert cli.post(f"/api/proyectos/Otro/contexto/{claude['id']}/abrir").status_code == 404
        assert abiertos == [str(p / "CLAUDE.md")]
        # abrir carpeta: por nombre de proyecto conocido
        assert cli.post(f"/api/proyectos/{PROY}/abrir-carpeta").status_code == 200
        assert abiertos[-1] == str(p)
        assert cli.post("/api/proyectos/Desconocido/abrir-carpeta").status_code == 404
        assert cli.post("/api/proyectos/..%2F/abrir-carpeta").status_code in (404, 400, 403)
        assert len(abiertos) == 2


def test_guardian_no_abre_sesiones_ni_secretos_ni_fuera(tmp_path):
    import pytest
    from apuntes.rutas import RutaProhibida
    raiz, p = arbol(tmp_path)
    g = guardian(tmp_path, raiz)
    for ruta in (p / CARPETA_SESIONES / "2026-11-01-reunion.md", p / "docs" / "credenciales.md", p / "node_modules" / "x" / "leeme.md",
                 tmp_path / "bandeja" / "x.md", p / "docs" / "notas.txt"):
        with pytest.raises(RutaProhibida):
            g.abrir_md_proyecto(PROY, ruta, abridor=lambda _x: None)
    llamadas = []
    g.abrir_md_proyecto(PROY, p / "docs" / "arquitectura.md", abridor=llamadas.append)
    assert llamadas == [str(p / "docs" / "arquitectura.md")]


def test_un_proyecto_lento_sale_sin_metadatos_y_no_bloquea(tmp_path, monkeypatch):
    raiz, p = arbol(tmp_path)
    g = guardian(tmp_path, raiz)
    CX._META_CACHE.clear()

    def lento(*a, **k):
        time.sleep(0.6)
        return {"n_sesiones": 9, "ultima_sesion": None, "n_md": 1}
    monkeypatch.setattr(CX, "_calcular_meta", lento)
    t0 = time.monotonic()
    lista = CX.enriquecer_proyectos(g, CX.listar_proyectos(g), plazo_s=0.1)
    assert time.monotonic() - t0 < 0.5
    assert "n_sesiones" not in lista[0]
    time.sleep(0.8)   # el hilo termina y la caché lo deja listo para la siguiente petición
    assert CX.enriquecer_proyectos(g, CX.listar_proyectos(g), plazo_s=0.5)[0]["n_sesiones"] == 9
    CX._META_CACHE.clear()


def test_el_indice_del_asesor_incluye_todos_los_md(tmp_path):
    from apuntes import fuentes as FU
    raiz, p = arbol(tmp_path)
    docs = FU.docs_de_proyecto(guardian(tmp_path, raiz), PROY, lambda g, pr: CX.contexto_legible(g, pr))
    assert {"02-alcance.md", "CLAUDE.md", "AGENTS.md", "docs/arquitectura.md", "notas/ideas.md", "equipos/LEEME.md"} <= set(docs)
    assert "00-INDICE.md" not in docs and not any("sesion" in k.lower() for k in docs)
