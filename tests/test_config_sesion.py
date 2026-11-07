"""Las opciones de arranque (--raiz, --extra, --mostrar-en-captura) nunca llegan a datos/config.json."""
import json

from apuntes.config import Config


def _en_disco(ruta):
    return json.loads(ruta.read_text(encoding="utf-8"))


def test_opcion_de_sesion_no_se_guarda_aunque_se_guarde_otra_clave(tmp_path):
    ruta = tmp_path / "config.json"
    cfg = Config(ruta)
    original = cfg["raiz_proyectos"]
    cfg.actualizar({"raiz_proyectos": r"C:\pruebas"}, guardar=False, solo_sesion=True)
    assert cfg["raiz_proyectos"] == r"C:\pruebas"
    cfg.actualizar({"whisper_modelo": "base"})
    assert _en_disco(ruta)["raiz_proyectos"] == original
    assert _en_disco(ruta)["whisper_modelo"] == "base"
    assert Config(ruta)["raiz_proyectos"] == original


def test_cambio_guardado_de_la_misma_clave_vuelve_a_ser_persistente(tmp_path):
    ruta = tmp_path / "config.json"
    cfg = Config(ruta)
    cfg.actualizar({"raiz_proyectos": r"C:\pruebas"}, guardar=False, solo_sesion=True)
    cfg.actualizar({"raiz_proyectos": r"C:\real"})
    assert _en_disco(ruta)["raiz_proyectos"] == r"C:\real"
