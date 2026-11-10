"""Huella del código (apuntes/huella.py): estable, sensible solo al código, indiferente a CRLF/LF, y el vigía recalcula como mucho cada `cada_s`.
Todo en carpetas temporales con ficheros ficticios; ni red, ni modelo, ni datos reales."""
from pathlib import Path

from apuntes import huella as H


def arbol(raiz: Path):
    """Una app ficticia mínima: app.py, un paquete y una web (lo que NO cuenta se añade en cada prueba)."""
    (raiz / "apuntes").mkdir(parents=True)
    (raiz / "web").mkdir()
    (raiz / "app.py").write_bytes(b"print('hola')\r\n")
    (raiz / "apuntes" / "a.py").write_bytes(b"X = 1\r\n")
    (raiz / "web" / "app.js").write_bytes(b"const a = 1;\r\n")
    (raiz / "web" / "index.html").write_bytes(b"<p>hola</p>\r\n")
    (raiz / "web" / "estilo.css").write_bytes(b"p { color: red; }\r\n")
    return raiz


class Reloj:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_la_huella_es_estable_y_un_sha256(tmp_path):
    raiz = arbol(tmp_path)
    a = H.huella_codigo(raiz)
    assert a == H.huella_codigo(raiz) and len(a) == 64 and int(a, 16) >= 0


def test_cambia_al_tocar_un_py_un_js_un_html_o_un_css(tmp_path):
    raiz = arbol(tmp_path)
    base = H.huella_codigo(raiz)
    for ruta, nuevo in (("app.py", b"print('adios')\n"), ("apuntes/a.py", b"X = 2\n"), ("web/app.js", b"const a = 2;\n"),
                        ("web/index.html", b"<p>adios</p>\n"), ("web/estilo.css", b"p { color: blue; }\n")):
        original = (raiz / ruta).read_bytes()
        (raiz / ruta).write_bytes(nuevo)
        assert H.huella_codigo(raiz) != base, ruta
        (raiz / ruta).write_bytes(original)
        assert H.huella_codigo(raiz) == base, ruta


def test_cambia_si_aparece_o_desaparece_un_fichero_de_codigo(tmp_path):
    raiz = arbol(tmp_path)
    base = H.huella_codigo(raiz)
    (raiz / "apuntes" / "b.py").write_bytes(b"Y = 1\n")
    assert H.huella_codigo(raiz) != base
    (raiz / "apuntes" / "b.py").unlink()
    assert H.huella_codigo(raiz) == base


def test_crlf_y_lf_dan_la_misma_huella(tmp_path):
    raiz = arbol(tmp_path)
    con_crlf = H.huella_codigo(raiz)
    for ruta in (p for p in raiz.rglob("*") if p.is_file()):
        ruta.write_bytes(ruta.read_bytes().replace(b"\r\n", b"\n"))
    assert H.huella_codigo(raiz) == con_crlf


def test_ignora_pycache_y_ficheros_que_no_son_codigo(tmp_path):
    raiz = arbol(tmp_path)
    base = H.huella_codigo(raiz)
    (raiz / "apuntes" / "__pycache__").mkdir()
    (raiz / "apuntes" / "__pycache__" / "a.py").write_bytes(b"basura\n")
    (raiz / "apuntes" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\x00\x01")
    (raiz / "apuntes" / "notas.txt").write_bytes(b"no cuenta\n")
    (raiz / "web" / "logo.png").write_bytes(b"\x89PNG")
    (raiz / "README.md").write_bytes(b"# no cuenta\n")
    (raiz / "datos").mkdir()
    (raiz / "datos" / "x.py").write_bytes(b"no cuenta: son datos\n")
    (raiz / "tests").mkdir()
    (raiz / "tests" / "test_x.py").write_bytes(b"no cuenta: fuera de app.py, apuntes y web\n")
    assert H.huella_codigo(raiz) == base


def test_la_ruta_cuenta_aunque_el_contenido_sea_el_mismo(tmp_path):
    raiz = arbol(tmp_path)
    base = H.huella_codigo(raiz)
    (raiz / "apuntes" / "a.py").rename(raiz / "apuntes" / "z.py")
    assert H.huella_codigo(raiz) != base


def test_un_fichero_ilegible_se_salta_y_nunca_lanza(tmp_path, monkeypatch):
    raiz = arbol(tmp_path)
    original = Path.read_bytes

    def lee(self):
        if self.name == "a.py":
            raise PermissionError("bloqueado")
        return original(self)
    monkeypatch.setattr(Path, "read_bytes", lee)
    a = H.huella_codigo(raiz)
    assert a == H.huella_codigo(raiz) and len(a) == 64


def test_una_raiz_que_no_existe_no_lanza(tmp_path):
    assert len(H.huella_codigo(tmp_path / "no_existe")) == 64


def test_el_vigia_no_avisa_al_arrancar_y_si_cambia_el_codigo(tmp_path):
    raiz, reloj = arbol(tmp_path), Reloj()
    v = H.VigiaCodigo(raiz, reloj=reloj, cada_s=60.0)
    assert v.cambiado() is False
    (raiz / "apuntes" / "a.py").write_bytes(b"X = 99\n")
    reloj.t += 60.0
    assert v.cambiado() is True


def test_el_vigia_respeta_cada_s_y_entre_medias_devuelve_lo_ultimo(tmp_path):
    raiz, reloj = arbol(tmp_path), Reloj()
    v = H.VigiaCodigo(raiz, reloj=reloj, cada_s=60.0)
    (raiz / "apuntes" / "a.py").write_bytes(b"X = 99\n")
    reloj.t = 59.9
    assert v.cambiado() is False                  # aún no toca recalcular
    reloj.t = 60.0
    assert v.cambiado() is True
    (raiz / "apuntes" / "a.py").write_bytes(b"X = 1\r\n")   # el disco vuelve a coincidir con lo cargado…
    reloj.t = 119.0
    assert v.cambiado() is True                   # …pero hasta dentro de 60 s no se vuelve a mirar
    reloj.t = 120.0
    assert v.cambiado() is False                  # y entonces vuelve a False


def test_el_vigia_cuenta_las_lecturas_con_reloj_falso(tmp_path, monkeypatch):
    raiz, reloj, calculos = arbol(tmp_path), Reloj(), []
    real = H._calcular
    monkeypatch.setattr(H, "_calcular", lambda r: calculos.append(1) or real(r))
    v = H.VigiaCodigo(raiz, reloj=reloj, cada_s=10.0)
    assert len(calculos) == 1                     # la huella del arranque
    for t in (1, 5, 9.9):
        reloj.t = t
        v.cambiado()
    assert len(calculos) == 1
    reloj.t = 10.0
    v.cambiado()
    reloj.t = 15.0
    v.cambiado()
    assert len(calculos) == 2


def test_cualquier_error_del_vigia_es_false(tmp_path, monkeypatch):
    raiz, reloj = arbol(tmp_path), Reloj()
    v = H.VigiaCodigo(raiz, reloj=reloj, cada_s=1.0)

    def roto(_r):
        raise OSError("disco caído")
    monkeypatch.setattr(H, "_calcular", roto)
    reloj.t = 5.0
    assert v.cambiado() is False
    v2 = H.VigiaCodigo(raiz, reloj=reloj, cada_s=1.0)   # ni siquiera hay huella de partida
    assert v2.cambiado() is False

    def reloj_roto():
        raise RuntimeError("sin reloj")
    v._reloj = reloj_roto
    assert v.cambiado() is False


def test_el_vigia_sobre_la_app_real_no_avisa_nada_mas_arrancar():
    from apuntes.config import APP_DIR
    assert H.VigiaCodigo(APP_DIR).cambiado() is False
