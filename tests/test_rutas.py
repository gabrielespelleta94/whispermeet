"""Reglas de rutas: escritura confinada y secretos excluidos."""
import os

import pytest

from apuntes.rutas import (CARPETA_CONTEXTO, CARPETA_SESIONES, RutaProhibida, es_secreto, limpiar_secretos,
                           slug, validar_componente)


# ---------------------------------------------------------------- escritura confinada
def test_sesion_va_a_su_carpeta_y_se_crea(entorno):
    g, raiz, _, _ = entorno
    ruta = g.ruta_sesion("ProyA", "2026-11-03", "Revisión de alcance")
    assert ruta == raiz / "ProyA" / CARPETA_SESIONES / "2026-11-03-revision-de-alcance.md"
    assert not ruta.parent.exists()
    g.escribir_sesion(ruta, "ProyA", "hola")
    assert ruta.read_text(encoding="utf-8") == "hola"


def test_sesion_repetida_no_pisa(entorno):
    g, *_ = entorno
    r1 = g.ruta_sesion("ProyA", "2026-11-03", "tema")
    g.escribir_sesion(r1, "ProyA", "uno")
    r2 = g.ruta_sesion("ProyA", "2026-11-03", "tema")
    assert r2.name == "2026-11-03-tema-2.md"


def test_bandeja(entorno):
    g, _, tmp, _ = entorno
    ruta = g.ruta_sesion(None, "2026-11-03", "Sin proyecto")
    assert ruta.parent == tmp / "bandeja"
    g.escribir_sesion(ruta, None, "x")
    assert ruta.is_file()


@pytest.mark.parametrize("proyecto", ["..", "../ProyA", "ProyA/..", "ProyA\\..\\..", "C:\\Windows", "", ".git",
                                      "ProyA:stream", "con", "ProyA.", " ProyA", "NoExiste", "node_modules"])
def test_proyecto_malicioso_rechazado(entorno, proyecto):
    g, *_ = entorno
    with pytest.raises(RutaProhibida):
        g.ruta_sesion(proyecto, "2026-11-03", "t")


def test_tema_con_traversal_se_neutraliza(entorno):
    g, raiz, *_ = entorno
    ruta = g.ruta_sesion("ProyA", "2026-11-03", "../../../CLAUDE")
    assert ruta.parent == raiz / "ProyA" / CARPETA_SESIONES
    assert ".." not in ruta.name and "/" not in ruta.name


def test_fecha_invalida(entorno):
    g, *_ = entorno
    with pytest.raises(RutaProhibida):
        g.ruta_sesion("ProyA", "../../x", "t")


@pytest.mark.parametrize("fichero", ["CLAUDE.md", "AGENTS.md", "../CLAUDE.md", "docs/x.md", "02-alcance.txt",
                                     "../../02-alcance.md", "02-alcance.md/../../x", "alcance.md", ".env",
                                     "02-alcance.md:ads", "en-curso/x.md"])
def test_contexto_solo_ficheros_nn_md(entorno, fichero):
    g, *_ = entorno
    with pytest.raises(RutaProhibida):
        g.escribir_contexto("ProyA", fichero, "x")


def test_contexto_valido(entorno):
    g, raiz, *_ = entorno
    ruta = g.escribir_contexto("ProyA", "02-alcance.md", "x")
    assert ruta == raiz / "ProyA" / CARPETA_CONTEXTO / "02-alcance.md"


def test_no_se_escribe_en_claude_agents_docs(entorno):
    g, raiz, *_ = entorno
    ps = g.ruta_sesion("ProyA", "2026-11-03", "claude")
    assert ps.parent.name == CARPETA_SESIONES
    for nombre in ("CLAUDE.md", "AGENTS.md"):
        with pytest.raises(RutaProhibida):
            g._comprobar_escritura(raiz / "ProyA" / nombre, raiz / "ProyA")
    with pytest.raises(RutaProhibida):
        g._comprobar_escritura(raiz / "ProyA" / "docs" / "x.md", raiz / "ProyA")


def test_knowledge_es_solo_lectura(entorno):
    g, _, _, knowledge = entorno
    with pytest.raises(RutaProhibida):
        g._comprobar_escritura(knowledge / "a.md", knowledge)


def test_escritura_fuera_de_la_base(entorno):
    g, raiz, tmp, _ = entorno
    with pytest.raises(RutaProhibida):
        g._comprobar_escritura(tmp / "otra" / "x.md", raiz / "ProyA")
    with pytest.raises(RutaProhibida):
        g._comprobar_escritura(raiz / "ProyA" / ".." / "ProyB" / "x.md", raiz / "ProyA")


def test_cache_solo_json_en_cache(entorno):
    g, _, tmp, _ = entorno
    assert g.escribir_cache("digest-x-1.json", "{}").parent == tmp / "cache"
    for malo in ("../x.json", "x.md", "a/b.json", ".env.json"):
        with pytest.raises(RutaProhibida):
            g.escribir_cache(malo, "{}")


def test_enlace_que_escapa(entorno):
    g, raiz, tmp, _ = entorno
    fuera = tmp / "fuera"
    fuera.mkdir()
    try:
        os.symlink(fuera, raiz / "ProyB" / CARPETA_SESIONES, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("sin permiso para crear enlaces simbólicos")
    with pytest.raises(RutaProhibida):
        g.escribir_sesion(g.ruta_sesion("ProyB", "2026-11-03", "t"), "ProyB", "x")
    assert not list(fuera.iterdir())


def test_validar_componente():
    for ok in ("Proyecto Alfa", "a-b_c"):
        assert validar_componente(ok) == ok
    for mal in ("a/b", "a\\b", "..", ".", "nul", "COM1", "a:b", "x*", "a\x00b"):
        with pytest.raises(RutaProhibida):
            validar_componente(mal)


def test_slug():
    assert slug("Reunión: ¡Alcance y SAP!") == "reunion-alcance-y-sap"
    assert slug("") == "reunion"
    assert len(slug("a" * 300)) <= 60


# ---------------------------------------------------------------- secretos
@pytest.mark.parametrize("nombre", [".env", ".env.local", "prod.env", "credentials.json", "secrets.md", "api-key.txt",
                                    "id_rsa", "id_ed25519.pub", "cert.pfx", "server.key", "my-token.txt",
                                    "local.settings.json", "appsettings.Production.json", ".npmrc", "clave_privada.pem",
                                    "passwords.txt", "terraform.tfstate"])
def test_nombres_secretos(nombre):
    assert es_secreto(nombre)


@pytest.mark.parametrize("nombre", ["02-alcance.md", "reunion.md", "notas.md", "README.md", "plan.txt"])
def test_nombres_normales(nombre):
    assert not es_secreto(nombre)


@pytest.mark.parametrize("ruta", [".git/config", "x/node_modules/a.md", "a/.ssh/notas.md", "p/.venv/lib/x.md"])
def test_directorios_excluidos(ruta):
    assert es_secreto(ruta)


def test_lectura_confinada_y_sin_secretos(entorno):
    g, raiz, tmp, _ = entorno
    carpeta = raiz / "ProyA" / CARPETA_CONTEXTO
    (carpeta / "02-alcance.md").write_text("# Alcance\nTodo bien", encoding="utf-8")
    (carpeta / ".env").write_text("TOKEN=abc", encoding="utf-8")
    (carpeta / "secrets.md").write_text("pwd", encoding="utf-8")
    (carpeta / "binario.pdf").write_bytes(b"%PDF")
    (tmp / "fuera.md").write_text("fuera", encoding="utf-8")
    assert "Alcance" in g.leer(carpeta / "02-alcance.md", carpeta)
    for malo in (carpeta / ".env", carpeta / "secrets.md", carpeta / "binario.pdf", tmp / "fuera.md",
                 carpeta / ".." / ".." / ".." / "fuera.md"):
        with pytest.raises(RutaProhibida):
            g.leer(malo, carpeta)


def test_lectura_con_tope(entorno):
    g, raiz, *_ = entorno
    carpeta = raiz / "ProyA" / CARPETA_CONTEXTO
    (carpeta / "grande.md").write_text("a" * 5000, encoding="utf-8")
    t = g.leer(carpeta / "grande.md", carpeta, tope_bytes=1000)
    assert len(t) < 1100 and "recortado" in t


def test_lineas_con_secretos_se_omiten():
    texto = ("uno\npassword: SuperSecreta123\nclave sk-ant-api03-abcdefghijklmnop\ndos\n"
             "AKIAABCDEFGHIJKLMNOP\nBearer abcdefghijklmnopqrstuvwxyz0123")
    out = limpiar_secretos(texto)
    assert "SuperSecreta" not in out and "sk-ant" not in out and "AKIA" not in out and "Bearer" not in out
    assert "uno" in out and "dos" in out


def test_contexto_no_incluye_ficheros_secretos_ni_personales(entorno):
    from apuntes import contexto as CX
    g, raiz, *_ = entorno
    carpeta = raiz / "ProyA" / CARPETA_CONTEXTO
    (carpeta / "01-ficha.md").write_text(
        "# Ficha\nDatos\n\n## Contactos del cliente\nAna 600 000 000\n\n## Equipo\nMarta", encoding="utf-8")
    (carpeta / "credentials.md").write_text("# nada", encoding="utf-8")
    (carpeta / ".env").write_text("A=1", encoding="utf-8")
    f = CX.ficheros_contexto(g, "ProyA")
    assert list(f) == ["01-ficha.md"]
    assert "600 000" not in f["01-ficha.md"] and "Marta" in f["01-ficha.md"]


def test_lectura_normaliza_crlf_y_conserva_el_salto_final(entorno):
    g, raiz, *_ = entorno
    carpeta = raiz / "ProyA" / CARPETA_CONTEXTO
    (carpeta / "02-alcance.md").write_bytes(b"# A\r\n\r\n- uno\r\n- dos\r\n")
    assert g.leer(carpeta / "02-alcance.md", carpeta) == "# A\n\n- uno\n- dos\n"
