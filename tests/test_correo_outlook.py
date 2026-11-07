"""Ola 3, punto 5: «Abrir en Outlook». Escribe un .eml con X-Unsent: 1 en la carpeta temporal propia y lo abre con el abridor INYECTADO (aquí no se abre nada)."""
import tempfile
from email import policy
from email.parser import BytesParser
from pathlib import Path

import pytest

from apuntes.correo_outlook import construir_eml, limpiar_destinatarios
from apuntes.rutas import Guardian, RutaProhibida
from ola3_util import montaje


def leer(ruta):
    return BytesParser(policy=policy.default).parsebytes(Path(ruta).read_bytes())


def test_el_eml_lleva_x_unsent_asunto_cuerpo_y_destinatarios():
    m = BytesParser(policy=policy.default).parsebytes(construir_eml("Resumen: Reunión ñandú (06/11/2026)", "Hola:\n\nOs dejo lo acordado.\n- Uno\n", "ana@ejemplo.com; luis@ejemplo.com"))
    assert m["X-Unsent"] == "1" and m["Subject"] == "Resumen: Reunión ñandú (06/11/2026)"
    assert m["To"] == "ana@ejemplo.com, luis@ejemplo.com" and "From" not in m and "Date" not in m
    assert "Os dejo lo acordado." in m.get_content()


def test_sin_destinatarios_y_validacion():
    assert "To" not in BytesParser(policy=policy.default).parsebytes(construir_eml("A", "B"))
    assert limpiar_destinatarios("a@x.com; no-es-correo, b@y.org\nc@z.es, A@X.com") == ["a@x.com", "b@y.org", "c@z.es"]
    assert limpiar_destinatarios(["a@x.com\r\nBcc: mala@x.com"]) == []   # nada de inyección de cabeceras
    for asunto, cuerpo in (("", "x"), ("x", "  "), ("  ", "")):
        with pytest.raises(ValueError):
            construir_eml(asunto, cuerpo)
    m = BytesParser(policy=policy.default).parsebytes(construir_eml("Asunto\r\nBcc: mala@x.com", "cuerpo"))
    assert m["Bcc"] is None and m["Subject"] == "Asunto Bcc: mala@x.com"


def test_endpoint_escribe_en_carpeta_temporal_propia_y_abre_sin_enviar(tmp_path):
    abiertos = []
    cli, gestor, cfg, g, *_ = montaje(tmp_path, abridor=abiertos.append)
    with cli:
        r = cli.post("/api/correo/outlook", json={"asunto": "Resumen: Piloto (06/11/2026)", "cuerpo": "Hola:\n\n- Cerrado: algo\n", "para": "ana@ejemplo.com"})
        assert r.status_code == 200 and r.json() == {"ok": True}
    assert len(abiertos) == 1
    ruta = Path(abiertos[0])
    assert ruta.parent == tmp_path / "borradores" and ruta.suffix == ".eml" and ruta.name.startswith("borrador-")
    assert leer(ruta)["X-Unsent"] == "1" and leer(ruta)["To"] == "ana@ejemplo.com"
    assert not list((tmp_path / "proyectos").rglob("*.eml"))   # nada en los proyectos del usuario


def test_errores_devuelven_ok_false_sin_abrir_nada(tmp_path):
    abiertos = []
    cli, *_ = montaje(tmp_path, abridor=abiertos.append)
    with cli:
        r = cli.post("/api/correo/outlook", json={"asunto": " ", "cuerpo": "x"}).json()
        assert r["ok"] is False and "asunto" in r["error"]
        assert cli.post("/api/correo/outlook", json={"asunto": "x", "cuerpo": ""}).json()["ok"] is False
        assert cli.post("/api/correo/outlook", json={"asunto": "x"}).status_code == 422
        assert cli.post("/api/correo/outlook", json={"asunto": "x", "cuerpo": "y"}, headers={"X-Token": "otro"}).status_code == 401
    assert abiertos == []


def test_el_abridor_que_falla_se_informa(tmp_path):
    def roto(ruta):
        raise OSError("sin programa asociado")
    cli, *_ = montaje(tmp_path, abridor=roto)
    with cli:
        r = cli.post("/api/correo/outlook", json={"asunto": "x", "cuerpo": "y"}).json()
        assert r["ok"] is False and "sin programa asociado" in r["error"]


def test_el_guardian_solo_abre_borradores_de_su_carpeta(tmp_path):
    g = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c")
    g.borradores = tmp_path / "borr"
    ajeno = tmp_path / "otro.eml"
    ajeno.write_bytes(b"x")
    abiertos = []
    for ruta in (ajeno, tmp_path / "borr" / "nada.eml", tmp_path / "borr" / ".." / "otro.eml"):
        with pytest.raises(RutaProhibida):
            g.abrir_borrador(ruta, abiertos.append)
    for nombre in ("../x.eml", "borrador-zz.eml", "borrador-1234abcd.txt", "borrador-1234abcd.eml.exe"):
        with pytest.raises(RutaProhibida):
            g.escribir_borrador(nombre, b"x")
    assert abiertos == [] and not (tmp_path / "borr").exists()


def test_por_defecto_la_carpeta_de_borradores_es_temporal_y_no_el_repo(tmp_path):
    g = Guardian(tmp_path / "p", tmp_path / "b", tmp_path / "c")
    assert g.borradores == Path(tempfile.gettempdir()) / "WhisperMeet-borradores"
