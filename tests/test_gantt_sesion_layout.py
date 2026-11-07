"""Gantt de la sesión: con muchos marcadores en el mismo minuto no hay solapes entre elementos del mismo carril ni nada se
sale de su carril. Se mide con getBoundingClientRect en un Edge sin cabeza a 1440 y a 1920 px. Se omite si no hay Edge/Chrome."""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

PAGINA = Path(__file__).resolve().parent / "pagina_gantt_sesion.html"


def navegador():
    for ruta in (r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe", r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
                 r"C:\Program Files\Google\Chrome\Application\chrome.exe"):
        if Path(ruta).is_file():
            return ruta
    return shutil.which("msedge") or shutil.which("chrome") or shutil.which("chromium")


def medir(ancho: int, tmp_path, consulta: str = "") -> dict:
    exe = navegador()
    if not exe:
        pytest.skip("No hay Edge ni Chrome para medir el layout.")
    perfil = tmp_path / f"perfil{ancho}"
    url = PAGINA.as_uri() + ("?" + consulta if consulta else "")
    salida = subprocess.run([exe, "--headless=new", "--disable-gpu", "--no-first-run", f"--user-data-dir={perfil}",
                             f"--window-size={ancho + 26},900", "--virtual-time-budget=4000", "--dump-dom", url],
                            capture_output=True, text=True, timeout=90, encoding="utf-8").stdout
    m = re.search(r'<pre id="res">(.*?)</pre>', salida, re.S)
    assert m and m.group(1).strip().startswith("{"), salida[-400:]
    return json.loads(m.group(1).replace("&amp;", "&"))


@pytest.mark.parametrize("ancho", [1440, 1920])
def test_sin_solapes_con_muchos_marcadores_en_el_mismo_minuto(ancho, tmp_path):
    r = medir(ancho, tmp_path)
    assert r["ancho"] == ancho, r                                   # el viewport medido es el pedido
    assert r["solapes"] == [], r["solapes"][:5]
    assert r["fuera"] == [], r["fuera"][:5]
    assert r["grupos"] > 0, "la prueba debe forzar agrupaciones"       # se agrupan con contador en vez de solaparse
    assert r["representados"] == r["esperados"], r                        # y ningún dato se pierde al agrupar
    assert r["temas"] == 12 and r["obj"] == 8
    print(f"\n{ancho} px: {r['marcadores']} elementos de marcador ({r['grupos']} grupos) para {r['esperados']} datos, 0 solapes")


def test_sin_solapes_en_una_reunion_corta_y_densa(tmp_path):
    r = medir(1440, tmp_path, "n=300&t=240&semilla=3")                   # 300 marcas en 4 minutos
    assert r["solapes"] == [] and r["fuera"] == [] and r["representados"] == r["esperados"], r


def test_el_detector_ve_los_solapes_si_los_hay(tmp_path):
    """Control negativo: si se apilan a mano todos los marcadores en el mismo punto, la medida lo detecta."""
    r = medir(1440, tmp_path, "romper=1")
    assert len(r["solapes"]) > 50, r["solapes"][:3]
