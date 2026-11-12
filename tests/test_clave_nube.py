"""Clave de la nube (apuntes/clave_nube.py): DPAPI, fichero cifrado hermano de config.json, variable de entorno, validación y confinamiento en el Guardián.
Claves ficticias (`sk-ficticia-…`), siempre en carpetas temporales."""
import base64
import json
import os
import sys

import pytest

from apuntes import clave_nube as CN
from apuntes.clave_nube import ENV_CLAVE, ClaveNube, validar_clave
from apuntes.rutas import EXT_SECRETAS, NOMBRE_SECRETO_NUBE, Guardian, RutaProhibida

CLAVE = "sk-ficticia-0000000000"
windows = pytest.mark.skipif(sys.platform != "win32", reason="DPAPI solo existe en Windows")


def _guardian(tmp_path, con_ajustes=True):
    return Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c",
                    ajustes=(tmp_path / "datos" / "config.json") if con_ajustes else None)


def _falsa_proteccion():
    """Cifrado de juguete reversible (nunca devuelve la clave en claro) y contador de descifrados: para probar sin depender de DPAPI."""
    n = {"descifrados": 0}

    def proteger(datos):
        return bytes(b ^ 0x5A for b in datos)[::-1]

    def desproteger(blob):
        n["descifrados"] += 1
        return bytes(b ^ 0x5A for b in blob[::-1])
    return proteger, desproteger, n


@windows
def test_dpapi_ida_y_vuelta():
    blob = CN.proteger(CLAVE.encode())
    assert CLAVE.encode() not in blob and blob != CLAVE.encode()
    assert CN.desproteger(blob) == CLAVE.encode()
    with pytest.raises(OSError):
        CN.desproteger(b"esto no es un blob de DPAPI")
    # la entropía forma parte del cifrado: un blob sin ella no se abre (se comprueba cambiándola)
    original = CN.ENTROPIA
    try:
        CN.ENTROPIA = b"otra-entropia"
        with pytest.raises(OSError):
            CN.desproteger(blob)
    finally:
        CN.ENTROPIA = original


@windows
def test_fichero_con_dpapi_real_no_contiene_la_clave_en_claro(tmp_path):
    g = _guardian(tmp_path)
    c = ClaveNube(g, entorno={})
    c.guardar(CLAVE)
    ruta = tmp_path / "datos" / NOMBRE_SECRETO_NUBE
    assert ruta == g.ruta_secreto_nube() and ruta.parent == g.ajustes.parent
    crudo = ruta.read_bytes()
    assert CLAVE.encode() not in crudo and base64.b64encode(CLAVE.encode()) not in crudo and len(crudo) < 4096
    d = json.loads(crudo)
    assert d["v"] == 1 and set(d) == {"v", "dpapi", "guardada"} and CLAVE.encode() not in base64.b64decode(d["dpapi"])
    assert not list((tmp_path / "datos").glob("*.tmp"))
    assert ClaveNube(g, entorno={}).obtener() == CLAVE   # otra instancia: lee de disco y descifra de verdad
    assert c.estado() == {"puesta": True, "origen": "fichero", "error": ""}


def test_fichero_no_contiene_la_clave_en_claro(tmp_path):
    prot, desprot, _ = _falsa_proteccion()
    g = _guardian(tmp_path)
    c = ClaveNube(g, entorno={}, proteger=prot, desproteger=desprot)
    c.guardar("  " + CLAVE + "  ")   # se recorta
    crudo = (tmp_path / "datos" / NOMBRE_SECRETO_NUBE).read_bytes()
    assert CLAVE.encode() not in crudo and json.loads(crudo)["v"] == 1
    assert c.obtener() == CLAVE
    assert CLAVE not in json.dumps(c.estado())


def test_entorno_manda_sobre_fichero(tmp_path):
    prot, desprot, _ = _falsa_proteccion()
    g = _guardian(tmp_path)
    ClaveNube(g, entorno={}, proteger=prot, desproteger=desprot).guardar(CLAVE)
    c = ClaveNube(g, entorno={ENV_CLAVE: "sk-ficticia-del-entorno"}, proteger=prot, desproteger=desprot)
    assert c.obtener() == "sk-ficticia-del-entorno"
    assert c.estado() == {"puesta": True, "origen": "entorno", "error": ""}
    sin_fichero = ClaveNube(_guardian(tmp_path / "otra", con_ajustes=False), entorno={ENV_CLAVE: "sk-ficticia-del-entorno"})
    assert sin_fichero.obtener() == "sk-ficticia-del-entorno" and sin_fichero.estado()["origen"] == "entorno"   # sin carpeta de datos, la variable basta
    assert ClaveNube(g, entorno={ENV_CLAVE: "   "}, proteger=prot, desproteger=desprot).estado()["origen"] == "fichero"   # una variable en blanco no cuenta


@pytest.mark.parametrize("contenido", ['{"v": 1, "dpapi": "AAAA"}', '{"v": 2, "dpapi": "AAAA"}', "{no es json", "[]", '{"v": 1, "dpapi": 7}',
                                      '{"v": 1, "dpapi": "%%%no-base64%%%"}', ""])
def test_blob_ilegible_da_error_y_no_puesta(tmp_path, contenido):
    def desproteger_de_otro_usuario(blob):
        raise OSError("DPAPI falló (-2146893813)")
    g = _guardian(tmp_path)
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / NOMBRE_SECRETO_NUBE).write_text(contenido, encoding="utf-8")
    c = ClaveNube(g, entorno={}, desproteger=desproteger_de_otro_usuario)
    assert c.obtener() is None
    e = c.estado()
    assert e == {"puesta": False, "origen": "ninguna",
                 "error": "La clave guardada no se puede leer con este usuario de Windows: vuelve a ponerla."}


def test_volver_a_ponerla_sustituye_al_fichero_ilegible(tmp_path):
    prot, desprot, _ = _falsa_proteccion()
    g = _guardian(tmp_path)
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / NOMBRE_SECRETO_NUBE).write_text("{roto", encoding="utf-8")
    c = ClaveNube(g, entorno={}, proteger=prot, desproteger=desprot)
    assert c.estado()["error"]
    c.guardar(CLAVE)
    assert c.estado() == {"puesta": True, "origen": "fichero", "error": ""} and c.obtener() == CLAVE


def test_fichero_de_mas_de_16kb_es_ilegible(tmp_path):
    g = _guardian(tmp_path)
    (tmp_path / "datos").mkdir()
    (tmp_path / "datos" / NOMBRE_SECRETO_NUBE).write_bytes(b"x" * 20_000)
    c = ClaveNube(g, entorno={})
    assert c.obtener() is None and c.estado()["error"]
    with pytest.raises(RutaProhibida):
        g.leer_secreto_nube()


def test_descifra_una_sola_vez_mientras_el_fichero_no_cambia(tmp_path):
    prot, desprot, n = _falsa_proteccion()
    g = _guardian(tmp_path)
    c = ClaveNube(g, entorno={}, proteger=prot, desproteger=desprot)
    c.guardar(CLAVE)
    for _ in range(5):
        assert c.obtener() == CLAVE
        c.estado()
    assert n["descifrados"] == 1
    c.guardar("sk-ficticia-9999999999")
    assert c.obtener() == "sk-ficticia-9999999999" and n["descifrados"] == 2


@pytest.mark.parametrize("valor,ok", [
    (CLAVE, True), ("  " + CLAVE + "\n", True), ("12345678", True), ("a" * 400, True), ("sk-proj-AbC_123-xyz.456~", True),
    ("1234567", False), ("a" * 401, False), ("con espacio dentro", False), ("tab\tdentro", False), ("salto\ndentro", False),
    ("acentuada-é-clave", False), ("", False), ("   ", False), (None, False), (12345678, False), (["x" * 10], False),
])
def test_validar_clave(valor, ok):
    if ok:
        assert validar_clave(valor) == valor.strip()
    else:
        with pytest.raises(ValueError) as e:
            validar_clave(valor)
        assert str(e.value) == "La clave tiene de 8 a 400 caracteres visibles, sin espacios."


def test_guardar_sin_ajustes_es_ruta_prohibida(tmp_path):
    prot, desprot, _ = _falsa_proteccion()
    c = ClaveNube(_guardian(tmp_path, con_ajustes=False), entorno={}, proteger=prot, desproteger=desprot)
    with pytest.raises(RutaProhibida):
        c.guardar(CLAVE)
    with pytest.raises(ValueError):
        c.guardar("corta")   # la validación va antes
    assert c.obtener() is None and c.estado() == {"puesta": False, "origen": "ninguna", "error": ""}
    c.borrar()   # y tampoco falla


def test_borrar_sin_clave_no_falla(tmp_path):
    prot, desprot, _ = _falsa_proteccion()
    g = _guardian(tmp_path)
    c = ClaveNube(g, entorno={}, proteger=prot, desproteger=desprot)
    c.borrar()
    c.guardar(CLAVE)
    assert (tmp_path / "datos" / NOMBRE_SECRETO_NUBE).is_file()
    c.borrar()
    assert not (tmp_path / "datos" / NOMBRE_SECRETO_NUBE).exists() and c.obtener() is None and c.estado()["origen"] == "ninguna"
    c.borrar()
    assert g.borrar_secreto_nube() is False


def test_escribir_datos_normal_sigue_rechazando_nombres_secretos(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos", ajustes=tmp_path / "datos" / "config.json")
    for nombre in (NOMBRE_SECRETO_NUBE, "secreto-nube.json", "token.json", "clave.dpapi"):
        with pytest.raises(RutaProhibida):
            g.escribir_datos(nombre, "x")
    assert ".dpapi" in EXT_SECRETAS
    assert not (tmp_path / "datos").exists() or not list((tmp_path / "datos").glob("*secreto*"))


def test_el_guardian_confina_el_secreto_y_no_sigue_enlaces(tmp_path):
    g = _guardian(tmp_path)
    ruta = g.escribir_secreto_nube('{"v": 1}')
    assert ruta.parent == g.ajustes.parent and ruta.name == NOMBRE_SECRETO_NUBE and g.leer_secreto_nube() == '{"v": 1}'
    assert not _guardian(tmp_path / "nada").ruta_secreto_nube().exists() and _guardian(tmp_path / "nada").leer_secreto_nube() is None
    ruta.unlink()
    destino = tmp_path / "otro.txt"
    destino.write_text("ajeno", encoding="utf-8")
    try:
        os.symlink(destino, ruta)
    except (OSError, NotImplementedError):
        pytest.skip("no se pueden crear enlaces simbólicos sin privilegios")
    with pytest.raises(RutaProhibida):
        g.escribir_secreto_nube("x")
    with pytest.raises(RutaProhibida):
        g.borrar_secreto_nube()
    assert g.leer_secreto_nube() is None and destino.read_text(encoding="utf-8") == "ajeno"
