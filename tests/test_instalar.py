"""Instalador (ola D, `instalar.py`): cada paso con dobles, sin crear entornos ni instalar nada de verdad. Idempotencia, `--comprobar` no escribe, no pisa
`datos/config.json`, no borra ni toca el contenido de las carpetas de datos, y los mensajes cuando falta Python o `claude`. Datos ficticios."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import instalar as I
from instalar import Entorno, Opciones, Resultado

REPO = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------- un mundo falso: nada se instala de verdad
class Mundo:
    """Un directorio temporal como «repositorio» y un `ejecutar` que imita lo que haría cada orden dejando los mismos rastros en disco."""

    def __init__(self, tmp: Path, python=(3, 12, 4), claude="ruta/claude.cmd", claude_version="2.1.0 (Claude Code)", respuesta_si=False):
        self.raiz = tmp / "repo"
        self.raiz.mkdir()
        for f in ("requirements.txt", "requirements-dev.txt", "config.example.json"):
            shutil.copy(REPO / f, self.raiz / f)
        self.tmp = tmp
        self.salida: list[str] = []
        self.ordenes: list[list[str]] = []
        self.instalados: dict[str, str] = {}
        self.claude, self.claude_version = claude, claude_version
        self.preguntas: list[str] = []
        self.respuesta = respuesta_si
        self.fallos: dict[str, int] = {}          # clave de la orden -> código de salida forzado
        self.python = python
        self.ent = Entorno(raiz=self.raiz, python_actual=python, python_exe="python-del-sistema", ejecutar=self.ejecutar, buscar=self.buscar,
                           preguntar=self.preguntar, imprimir=self.salida.append, home=tmp / "casa", appdata=str(tmp / "appdata"))

    def buscar(self, nombre):
        return self.claude if nombre == "claude" and self.claude else None

    def preguntar(self, texto):
        self.preguntas.append(texto)
        return self.respuesta

    def _clave(self, cmd):
        c = [str(x) for x in cmd]
        if c[:1] == [self.claude]:
            return "claude"
        if c[1:3] == ["-m", "venv"]:
            return "venv"
        if "pip" in c and "list" in c:
            return "pip-list"
        if "pip" in c and "install" in c:
            return "pip-install"
        if c[1:2] == ["-c"]:
            return "descarga"
        if c[1:2] and c[1].endswith("crear_acceso_directo.py"):
            return "acceso"
        if c[1:2] == ["--version"]:
            return "version"
        return "otra"

    def ejecutar(self, cmd, timeout=None, mostrar=False):
        cmd = [str(x) for x in cmd]
        self.ordenes.append(cmd)
        clave = self._clave(cmd)
        if clave in self.fallos:
            return self.fallos[clave], "fallo simulado"
        if clave == "venv":
            py = self.ent.venv_python
            py.parent.mkdir(parents=True)
            py.write_bytes(b"")
            return 0, ""
        if clave == "version":
            return 0, "Python %d.%d.%d" % self.python
        if clave == "pip-list":
            return 0, json.dumps([{"name": n, "version": v} for n, v in self.instalados.items()])
        if clave == "pip-install":
            nombre = Path(cmd[-1]).name
            self.instalados.update(dict(I.leer_requisitos(self.raiz / nombre)))
            return 0, ""
        if clave == "claude":
            return 0, self.claude_version + "\n"
        if clave == "descarga":
            snap = Path(cmd[-1]) / ("models--Systran--faster-whisper-" + cmd[-2]) / "snapshots" / "abc"
            snap.mkdir(parents=True)
            (snap / "model.bin").write_bytes(b"x")
            return 0, ""
        if clave == "acceso":
            lnk = I.ruta_acceso_directo(self.ent)
            lnk.parent.mkdir(parents=True, exist_ok=True)
            lnk.write_bytes(b"lnk")
            return 0, ""
        raise AssertionError(f"orden inesperada: {cmd}")

    def cmds(self, clave):
        return [c for c in self.ordenes if self._clave(c) == clave]


@pytest.fixture
def mundo(tmp_path):
    return Mundo(tmp_path)


def instantanea(base: Path):
    """{ruta relativa: (tamaño, mtime_ns, bytes)} de todo lo que hay bajo `base` (carpetas incluidas)."""
    out = {}
    for p in sorted(base.rglob("*")):
        st = p.stat()
        out[str(p.relative_to(base))] = None if p.is_dir() else (st.st_size, st.st_mtime_ns, p.read_bytes())
    return out


def nada_se_borra(monkeypatch):
    def prohibido(*a, **k):
        raise AssertionError("el instalador intentó borrar algo")
    for owner, name in ((os, "remove"), (os, "unlink"), (os, "rmdir"), (os, "removedirs"), (shutil, "rmtree"), (Path, "unlink"), (Path, "rmdir"), (os, "replace")):
        monkeypatch.setattr(owner, name, prohibido)


# ---------------------------------------------------------------- piezas puras
def test_los_requisitos_reales_estan_todos_fijados_y_el_dev_incluye_el_base():
    base, dev = I.leer_requisitos(REPO / "requirements.txt"), I.leer_requisitos(REPO / "requirements-dev.txt")
    lineas = [l.split("#")[0].strip() for l in (REPO / "requirements.txt").read_text(encoding="utf-8").splitlines() if l.split("#")[0].strip()]
    assert len(base) == len(lineas) >= 6 and all("==" in l for l in lineas)                    # ningún paquete sin versión fijada
    assert set(base) < set(dev) and {"pytest", "httpx"} <= {n for n, _ in dev}
    assert {"fastapi", "uvicorn", "pydantic", "pywebview", "pyaudiowpatch", "faster-whisper", "numpy"} == {n for n, _ in base}
    assert not ({"pytest", "httpx", "pyttsx3"} & {n for n, _ in base})                          # lo de pruebas, fuera de la app


def test_leer_requisitos_ignora_comentarios_extras_y_sigue_los_r(tmp_path):
    (tmp_path / "a.txt").write_text("# uno\n\nPaquete_Uno[extra]==1.0  # nota\notro.paquete == 2.5\nsin-version\n-r b.txt\n", encoding="utf-8")
    (tmp_path / "b.txt").write_text("tercero==3\n-r a.txt\n", encoding="utf-8")                 # ciclo: no se queda dando vueltas
    assert I.leer_requisitos(tmp_path / "a.txt") == [("paquete-uno", "1.0"), ("otro-paquete", "2.5"), ("tercero", "3")]
    assert I.leer_requisitos(tmp_path / "no-existe.txt") == []


def test_paquetes_que_faltan_compara_la_version_exacta():
    fijados = [("a", "1"), ("b", "2"), ("c", "3")]
    assert I.paquetes_que_faltan(fijados, {"a": "1", "b": "9"}) == ["b==2", "c==3"]
    assert I.paquetes_que_faltan(fijados, {"a": "1", "b": "2", "c": "3", "extra": "0"}) == []


def test_config_desde_ejemplo_sustituye_los_marcadores_y_el_ejemplo_real_no_los_conserva(tmp_path):
    ejemplo = json.loads((REPO / "config.example.json").read_text(encoding="utf-8"))
    c = I.config_desde_ejemplo(ejemplo, tmp_path / "casa")
    assert c["raiz_proyectos"] == str(tmp_path / "casa" / "Proyectos") and c["autor"] == "" and c["proyectos_extra"] == []
    assert "<" not in json.dumps(c) and c["whisper_modelo"] == ejemplo["whisper_modelo"]
    propio = I.config_desde_ejemplo({"raiz_proyectos": "D:/Mis", "autor": "Ana", "proyectos_extra": [{"nombre": "X", "ruta": "D:/X"}]}, tmp_path)
    assert propio == {"raiz_proyectos": "D:/Mis", "autor": "Ana", "proyectos_extra": [{"nombre": "X", "ruta": "D:/X"}]}   # lo que no es un marcador se respeta


def test_coherencia_con_el_resto_del_repo():
    from apuntes import requisitos
    assert I.PYTHON_MINIMO == requisitos.PYTHON_MINIMO
    ignorado = {l.strip().rstrip("/") for l in (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()}
    assert set(I.CARPETAS_LOCALES) <= ignorado                                                  # solo crea carpetas que git ya ignora (datos, sesiones, planes…)
    compile(I.DESCARGA_MODELO, "descarga", "exec")
    crear = pytest.importorskip("crear_acceso_directo")
    ent = Entorno(appdata=os.environ.get("APPDATA") or "X:/appdata")
    if os.environ.get("APPDATA"):
        assert I.ruta_acceso_directo(ent) == crear.ruta_por_defecto()


def test_instalar_bat_va_en_crlf_y_busca_python():
    b = (REPO / "instalar.bat").read_bytes()
    assert b.count(b"\r\n") == b.count(b"\n") > 10 and b"\r\r" not in b
    t = b.decode("ascii")                                                                       # solo ASCII: cmd lee el .bat en la página de códigos del equipo
    for pieza in ("py -3", "python", "instalar.py", "%*", "pause"):
        assert pieza in t, pieza


def test_instalar_bat_prueba_de_verdad_cada_python_y_funciona_desde_una_ruta_de_red():
    """`where python` encuentra el alias de la Tienda de Windows (no ejecuta nada) y `py -3` sin Python instalado puede quedarse esperando una respuesta:
    se prueba ejecutando cada candidato, sin stdin ni salida, y se acepta solo el que termina bien. `pushd` (no `cd /d`) para poder correr desde una ruta de red (UNC)."""
    t = (REPO / "instalar.bat").read_bytes().decode("ascii")
    lineas = [x.strip() for x in t.splitlines()]
    assert "where" not in t.replace("rem ", "")                                                  # ya no se fía de dónde está, sino de que funcione
    for cand in ('py -3 -c "import sys" <nul >nul 2>nul', 'python -c "import sys" <nul >nul 2>nul'):
        assert cand in lineas, cand
    assert 'pushd "%~dp0"' in lineas and "popd" in lineas and "cd /d" not in t
    assert lineas.index('pushd "%~dp0"') < lineas.index("popd") < max(i for i, x in enumerate(lineas) if x.startswith("exit /b"))
    # lo que sale del candidato se mira por su código de salida
    assert t.count("if not errorlevel 1") >= 2


# ---------------------------------------------------------------- Python
@pytest.mark.parametrize("v,estado", [((3, 12, 0), "ya"), ((3, 13, 2), "ya"), ((3, 11, 9), "falta"), ((3, 8, 10), "falta")])
def test_paso_python(mundo, v, estado):
    mundo.ent.python_actual = v
    r = I.paso_python(mundo.ent, Opciones())
    assert r.estado == estado
    if estado == "falta":
        assert "3.12" in r.mensaje and ".".join(map(str, v)) in r.mensaje and "python.org" in r.pendiente


def test_si_falta_python_no_se_hace_nada_y_se_dice(mundo):
    mundo.ent.python_actual = (3, 10, 1)
    antes = instantanea(mundo.tmp)
    rs = I.ejecutar_pasos(mundo.ent, Opciones())
    assert [r.estado for r in rs] == ["falta"] + ["omitido"] * 7
    assert mundo.ordenes == [] and instantanea(mundo.tmp) == antes
    lineas, codigo = I.resumen(rs, Opciones())
    assert codigo == 1 and any("python.org" in l for l in lineas) and any("no ha terminado" in l for l in lineas)
    assert any("falta" in l and "3.10.1" in l for l in mundo.salida)


# ---------------------------------------------------------------- entorno
def test_paso_venv_lo_crea_si_no_existe_y_si_existe_no_lo_toca(mundo):
    r = I.paso_venv(mundo.ent, Opciones())
    assert r.estado == "hecho" and len(mundo.cmds("venv")) == 1 and mundo.cmds("venv")[0][:3] == ["python-del-sistema", "-m", "venv"]
    antes = instantanea(mundo.raiz / ".venv")
    r = I.paso_venv(mundo.ent, Opciones())
    assert r.estado == "ya" and len(mundo.cmds("venv")) == 1 and instantanea(mundo.raiz / ".venv") == antes


def test_paso_venv_comprobar_no_crea(mundo):
    r = I.paso_venv(mundo.ent, Opciones(comprobar=True))
    assert r.estado == "haria" and mundo.ordenes == [] and not (mundo.raiz / ".venv").exists()


def test_venv_con_python_viejo_o_roto_se_avisa_pero_no_se_borra(mundo, monkeypatch):
    nada_se_borra(monkeypatch)
    py = mundo.ent.venv_python
    py.parent.mkdir(parents=True)
    py.write_bytes(b"")
    mundo.python = (3, 10, 4)
    r = I.paso_venv(mundo.ent, Opciones())
    assert r.estado == "falta" and "3.10.4" in r.mensaje and "no la borra" in r.pendiente and py.exists()
    mundo.fallos["version"] = 1
    r = I.paso_venv(mundo.ent, Opciones())
    assert r.estado == "falta" and "no arranca" in r.mensaje and py.exists()


def test_venv_carpeta_sin_interprete_no_se_pisa(mundo, monkeypatch):
    nada_se_borra(monkeypatch)
    (mundo.raiz / ".venv").mkdir()
    (mundo.raiz / ".venv" / "mio.txt").write_text("importante")
    r = I.paso_venv(mundo.ent, Opciones())
    assert r.estado == "falta" and mundo.ordenes == [] and (mundo.raiz / ".venv" / "mio.txt").read_text() == "importante"


def test_venv_que_no_se_puede_crear_es_un_error_con_el_motivo(mundo):
    mundo.fallos["venv"] = 1
    r = I.paso_venv(mundo.ent, Opciones())
    assert r.estado == "error" and "fallo simulado" in r.mensaje and r.pendiente


# ---------------------------------------------------------------- dependencias
def _con_venv(mundo):
    I.paso_venv(mundo.ent, Opciones())
    mundo.ordenes.clear()


def test_dependencias_se_instalan_una_vez_y_la_segunda_ya_estaban(mundo):
    _con_venv(mundo)
    r = I.paso_dependencias(mundo.ent, Opciones())
    assert r.estado == "hecho" and len(mundo.cmds("pip-install")) == 1
    orden = mundo.cmds("pip-install")[0]
    assert orden[1:3] == ["-m", "pip"] and orden[-2] == "-r" and orden[-1].endswith("requirements.txt")
    r = I.paso_dependencias(mundo.ent, Opciones())
    assert r.estado == "ya" and len(mundo.cmds("pip-install")) == 1                              # idempotente: no vuelve a llamar a pip install


def test_dependencias_solo_instala_lo_que_falta_de_verdad(mundo):
    _con_venv(mundo)
    mundo.instalados = dict(I.leer_requisitos(mundo.raiz / "requirements.txt"))
    mundo.instalados["numpy"] = "1.0"                                                           # versión distinta de la fijada
    r = I.paso_dependencias(mundo.ent, Opciones())
    assert r.estado == "hecho" and len(mundo.cmds("pip-install")) == 1


def test_dependencias_dev_usa_el_fichero_de_desarrollo(mundo):
    _con_venv(mundo)
    r = I.paso_dependencias(mundo.ent, Opciones(dev=True))
    assert r.estado == "hecho" and mundo.cmds("pip-install")[0][-1].endswith("requirements-dev.txt") and "pytest" in mundo.instalados
    assert I.paso_dependencias(mundo.ent, Opciones(dev=False)).estado == "ya"                  # el dev incluye el base


def test_dependencias_comprobar_no_instala(mundo):
    _con_venv(mundo)
    r = I.paso_dependencias(mundo.ent, Opciones(comprobar=True))
    assert r.estado == "haria" and "faltan" in r.mensaje and mundo.cmds("pip-install") == []


def test_dependencias_si_pip_falla_es_un_error(mundo):
    _con_venv(mundo)
    mundo.fallos["pip-install"] = 1
    r = I.paso_dependencias(mundo.ent, Opciones())
    assert r.estado == "error" and "código 1" in r.mensaje and "vuelve a ejecutar" in r.pendiente


def test_dependencias_sin_el_fichero_de_requisitos(mundo):
    _con_venv(mundo)
    (mundo.raiz / "requirements.txt").unlink()
    assert I.paso_dependencias(mundo.ent, Opciones()).estado == "error"


# ---------------------------------------------------------------- configuración: NO se pisa
def test_config_se_crea_si_no_existe(mundo):
    r = I.paso_config(mundo.ent, Opciones())
    destino = mundo.raiz / "datos" / "config.json"
    assert r.estado == "hecho" and destino.is_file()
    c = json.loads(destino.read_text(encoding="utf-8"))
    assert c["raiz_proyectos"] == str(mundo.tmp / "casa" / "Proyectos") and "<" not in json.dumps(c)
    assert "Proyectos" in r.pendiente                                                           # la carpeta de proyectos aún no existe: se avisa sin enseñar la ruta completa
    assert str(mundo.tmp) not in r.pendiente


def test_config_existente_no_se_pisa_ni_se_toca(mundo, monkeypatch):
    nada_se_borra(monkeypatch)
    (mundo.raiz / "datos").mkdir()
    destino = mundo.raiz / "datos" / "config.json"
    destino.write_bytes('{"autor": "Persona Ficticia", "whisper_modelo": "medium"}'.encode())
    antes = (destino.read_bytes(), destino.stat().st_mtime_ns)
    r = I.paso_config(mundo.ent, Opciones())
    assert r.estado == "ya" and (destino.read_bytes(), destino.stat().st_mtime_ns) == antes
    # también con --comprobar y en la ejecución completa
    assert I.paso_config(mundo.ent, Opciones(comprobar=True)).estado == "ya"
    I.ejecutar_pasos(mundo.ent, Opciones(sin_modelo=True, sin_acceso_directo=True))
    assert (destino.read_bytes(), destino.stat().st_mtime_ns) == antes


def test_config_si_aparece_a_la_vez_el_modo_exclusivo_impide_pisarlo(mundo, monkeypatch):
    """Segunda guarda: aunque la comprobación previa diga que no existe (otro proceso lo crea justo entonces), `open(..., "x")` falla en vez de sobrescribir."""
    (mundo.raiz / "datos").mkdir()
    destino = mundo.raiz / "datos" / "config.json"
    destino.write_text('{"autor": "Persona Ficticia"}', encoding="utf-8")
    original = Path.exists
    monkeypatch.setattr(Path, "exists", lambda self: False if self == destino else original(self))
    r = I.paso_config(mundo.ent, Opciones())
    assert r.estado == "ya" and destino.read_text(encoding="utf-8") == '{"autor": "Persona Ficticia"}'


def test_config_comprobar_no_crea_nada(mundo):
    r = I.paso_config(mundo.ent, Opciones(comprobar=True))
    assert r.estado == "haria" and not (mundo.raiz / "datos").exists()


def test_config_sin_ejemplo(mundo):
    (mundo.raiz / "config.example.json").unlink()
    assert I.paso_config(mundo.ent, Opciones()).estado == "error"


# ---------------------------------------------------------------- carpetas locales: solo se crean, nunca se tocan
def test_carpetas_se_crean_las_que_faltan_y_no_se_toca_el_contenido(mundo, monkeypatch):
    nada_se_borra(monkeypatch)
    for c, f in (("datos", "consumo.jsonl"), ("sesiones", "uno/2026-01-01-tema.md"), ("planes", "plan-x.json")):
        p = mundo.raiz / c / f
        p.parent.mkdir(parents=True)
        p.write_text(f"contenido ficticio de {c}", encoding="utf-8")
    antes = instantanea(mundo.raiz)
    r = I.paso_carpetas(mundo.ent, Opciones())
    assert r.estado == "hecho"
    despues = instantanea(mundo.raiz)
    assert {k for k in despues if k not in antes} == {c for c in I.CARPETAS_LOCALES if c not in ("datos", "sesiones", "planes")}   # solo carpetas nuevas, vacías
    assert all(despues[k] == antes[k] for k in antes)                                                                                # lo que había, intacto (bytes y fechas)
    assert I.paso_carpetas(mundo.ent, Opciones()).estado == "ya"


def test_carpetas_comprobar_no_crea_y_un_fichero_con_el_nombre_no_se_pisa(mundo):
    r = I.paso_carpetas(mundo.ent, Opciones(comprobar=True))
    assert r.estado == "haria" and not (mundo.raiz / "datos").exists()
    (mundo.raiz / "cache").write_text("soy un fichero")
    r = I.paso_carpetas(mundo.ent, Opciones())
    assert r.estado == "error" and (mundo.raiz / "cache").read_text() == "soy un fichero"


# ---------------------------------------------------------------- claude
def test_claude_no_encontrado_dice_que_falta_y_que_hacer(mundo):
    mundo.claude = None
    r = I.paso_claude(mundo.ent, Opciones())
    assert r.estado == "falta" and "PATH" in r.mensaje and "claude" in r.pendiente and "cuenta" in r.pendiente and mundo.ordenes == []


def test_claude_solo_ejecuta_version(mundo):
    r = I.paso_claude(mundo.ent, Opciones())
    assert r.estado == "ya" and "2.1.0" in r.mensaje and "iniciado sesión" in r.pendiente
    assert mundo.ordenes == [["ruta/claude.cmd", "--version"]]                                    # nada más: ni -p ni una sesión
    r = I.paso_claude(mundo.ent, Opciones(comprobar=True))
    assert r.estado == "ya" and mundo.ordenes[-1] == ["ruta/claude.cmd", "--version"]


def test_claude_que_falla_al_dar_la_version(mundo):
    mundo.fallos["claude"] = 1
    r = I.paso_claude(mundo.ent, Opciones())
    assert r.estado == "falta" and "--version" in r.mensaje


# ---------------------------------------------------------------- modelo de Whisper
def _listo_para_modelo(mundo):
    I.paso_venv(mundo.ent, Opciones())
    mundo.ordenes.clear()


def test_modelo_ya_descargado(mundo):
    snap = mundo.raiz / "modelos" / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
    snap.mkdir(parents=True)
    (snap / "model.bin").write_bytes(b"x")
    assert I.paso_modelo(mundo.ent, Opciones()).estado == "ya" and mundo.preguntas == [] and mundo.ordenes == []


def test_modelo_sin_modelo_no_pregunta_ni_descarga(mundo):
    _listo_para_modelo(mundo)
    r = I.paso_modelo(mundo.ent, Opciones(sin_modelo=True))
    assert r.estado == "omitido" and mundo.preguntas == [] and mundo.cmds("descarga") == [] and "primera reunión" in r.pendiente


def test_modelo_con_si_descarga_sin_preguntar(mundo):
    _listo_para_modelo(mundo)
    r = I.paso_modelo(mundo.ent, Opciones(si=True))
    assert r.estado == "hecho" and mundo.preguntas == []
    orden = mundo.cmds("descarga")[0]
    assert orden[-2:] == ["small", str(mundo.raiz / "modelos")]                                   # el modelo configurado y la carpeta de modelos de la app
    assert I.paso_modelo(mundo.ent, Opciones(si=True)).estado == "ya" and len(mundo.cmds("descarga")) == 1


def test_modelo_pregunta_y_respeta_la_respuesta(mundo):
    _listo_para_modelo(mundo)
    mundo.respuesta = False
    r = I.paso_modelo(mundo.ent, Opciones())
    assert r.estado == "falta" and len(mundo.preguntas) == 1 and "small" in mundo.preguntas[0] and mundo.cmds("descarga") == []
    mundo.respuesta = True
    assert I.paso_modelo(mundo.ent, Opciones()).estado == "hecho" and len(mundo.cmds("descarga")) == 1


def test_modelo_sin_consola_para_preguntar_cuenta_como_no(mundo):
    _listo_para_modelo(mundo)
    mundo.respuesta = None
    r = I.paso_modelo(mundo.ent, Opciones())
    assert r.estado == "falta" and "no hay consola" in r.mensaje and mundo.cmds("descarga") == []


def test_modelo_usa_el_de_la_configuracion_si_la_hay(mundo):
    _listo_para_modelo(mundo)
    (mundo.raiz / "datos").mkdir()
    (mundo.raiz / "datos" / "config.json").write_text('{"whisper_modelo": "base"}', encoding="utf-8")
    assert I.modelo_configurado(mundo.ent) == "base"
    I.paso_modelo(mundo.ent, Opciones(si=True))
    assert mundo.cmds("descarga")[0][-2] == "base"


def test_modelo_comprobar_no_pregunta_ni_descarga_y_si_falla_la_descarga_es_error(mundo):
    _listo_para_modelo(mundo)
    r = I.paso_modelo(mundo.ent, Opciones(comprobar=True))
    assert r.estado == "haria" and mundo.preguntas == [] and mundo.cmds("descarga") == [] and not (mundo.raiz / "modelos").exists()
    mundo.fallos["descarga"] = 1
    r = I.paso_modelo(mundo.ent, Opciones(si=True))
    assert r.estado == "error" and "falló" in r.mensaje


# ---------------------------------------------------------------- acceso directo
def test_acceso_directo_omitido_creado_y_ya_existente(mundo):
    _listo_para_modelo(mundo)
    r = I.paso_acceso_directo(mundo.ent, Opciones(sin_acceso_directo=True))
    assert r.estado == "omitido" and mundo.cmds("acceso") == []
    r = I.paso_acceso_directo(mundo.ent, Opciones())
    orden = mundo.cmds("acceso")[0]
    assert r.estado == "hecho" and orden[0] == str(mundo.ent.venv_python) and orden[1].endswith("crear_acceso_directo.py") and len(orden) == 2   # el script de siempre, sin --ruta
    r = I.paso_acceso_directo(mundo.ent, Opciones())
    assert r.estado == "ya" and len(mundo.cmds("acceso")) == 1


def test_acceso_directo_comprobar_no_crea(mundo):
    _listo_para_modelo(mundo)
    r = I.paso_acceso_directo(mundo.ent, Opciones(comprobar=True))
    assert r.estado == "haria" and mundo.cmds("acceso") == [] and not (mundo.tmp / "appdata").exists()


def test_acceso_directo_sin_appdata_o_con_error(mundo):
    _listo_para_modelo(mundo)
    mundo.ent.appdata = None
    assert I.paso_acceso_directo(mundo.ent, Opciones()).estado == "falta"
    mundo.ent.appdata = str(mundo.tmp / "appdata")
    mundo.fallos["acceso"] = 1
    assert I.paso_acceso_directo(mundo.ent, Opciones()).estado == "error"


# ---------------------------------------------------------------- todo junto
def test_instalacion_completa_es_idempotente_y_no_borra_nada(mundo, monkeypatch):
    nada_se_borra(monkeypatch)
    (mundo.raiz / "sesiones").mkdir()
    (mundo.raiz / "sesiones" / "a.md").write_text("ficticio", encoding="utf-8")
    op = Opciones(si=True)
    rs1 = I.ejecutar_pasos(mundo.ent, op)
    assert [r.estado for r in rs1] == ["ya", "hecho", "hecho", "hecho", "hecho", "ya", "hecho", "hecho"]
    lineas, codigo = I.resumen(rs1, op)
    assert codigo == 0 and any("iniciado sesión" in l for l in lineas) and any("Para empezar" in l for l in lineas)
    foto1, n_ordenes = instantanea(mundo.tmp), len(mundo.ordenes)
    mundo.ordenes.clear()
    rs2 = I.ejecutar_pasos(mundo.ent, op)
    assert [r.estado for r in rs2] == ["ya"] * 8                                                  # segunda vez: nada que hacer
    assert instantanea(mundo.tmp) == foto1                                                        # y el disco, byte a byte igual
    ejecutadas = {mundo._clave(c) for c in mundo.ordenes}
    assert ejecutadas <= {"version", "pip-list", "claude"} and n_ordenes > len(mundo.ordenes)     # solo lecturas
    assert I.resumen(rs2, op)[1] == 0


def test_comprobar_no_escribe_nada_en_ninguna_situacion(mundo, monkeypatch):
    nada_se_borra(monkeypatch)
    antes = instantanea(mundo.tmp)
    rs = I.ejecutar_pasos(mundo.ent, Opciones(comprobar=True))
    assert instantanea(mundo.tmp) == antes and mundo.ordenes == [["ruta/claude.cmd", "--version"]]      # ni un fichero ni una carpeta; solo `claude --version`
    assert [r.estado for r in rs] == ["ya", "haria", "haria", "haria", "haria", "ya", "haria", "haria"]
    lineas, codigo = I.resumen(rs, Opciones(comprobar=True))
    assert codigo == 1 and any("no se ha cambiado nada" in l for l in lineas) and any("haría" in l for l in lineas)
    # con la instalación ya hecha, --comprobar dice que todo está
    I.ejecutar_pasos(mundo.ent, Opciones(si=True))
    foto = instantanea(mundo.tmp)
    mundo.ordenes.clear()
    rs = I.ejecutar_pasos(mundo.ent, Opciones(comprobar=True))
    assert [r.estado for r in rs] == ["ya"] * 8 and instantanea(mundo.tmp) == foto
    assert {mundo._clave(c) for c in mundo.ordenes} <= {"version", "pip-list", "claude"} and I.resumen(rs, Opciones(comprobar=True))[1] == 0


def test_no_toca_el_contenido_de_las_carpetas_de_datos(mundo, monkeypatch):
    nada_se_borra(monkeypatch)
    ficheros = {}
    for c in ("datos", "bandeja", "sesiones", "planes", "checks", "backlog", "cache", "tipos_documento"):
        p = mundo.raiz / c / "sub" / "dato.txt"
        p.parent.mkdir(parents=True)
        p.write_text(f"ficticio {c}", encoding="utf-8")
        ficheros[p] = (p.read_bytes(), p.stat().st_mtime_ns)
    (mundo.raiz / "datos" / "config.json").write_text('{"autor": "Persona Ficticia"}', encoding="utf-8")
    ficheros[mundo.raiz / "datos" / "config.json"] = ((mundo.raiz / "datos" / "config.json").read_bytes(), (mundo.raiz / "datos" / "config.json").stat().st_mtime_ns)
    I.ejecutar_pasos(mundo.ent, Opciones(si=True))
    for p, v in ficheros.items():
        assert (p.read_bytes(), p.stat().st_mtime_ns) == v, p
    assert sorted(str(p.relative_to(mundo.raiz / "datos")) for p in (mundo.raiz / "datos").rglob("*")) == sorted(["config.json", "sub", str(Path("sub") / "dato.txt")])


def test_si_falla_el_entorno_los_pasos_que_dependen_de_el_se_omiten(mundo):
    mundo.fallos["venv"] = 1
    rs = I.ejecutar_pasos(mundo.ent, Opciones(si=True))
    por = {r.paso: r.estado for r in rs}
    assert por["Entorno (.venv)"] == "error" and por["Dependencias"] == "omitido" and por["Modelo de Whisper"] == "omitido" and por["Acceso directo"] == "omitido"
    assert por["Configuración"] == "hecho" and por["Carpetas locales"] == "hecho"                  # lo que no depende del entorno se hace igual
    assert I.resumen(rs, Opciones(si=True))[1] == 1 and mundo.cmds("pip-install") == [] and mundo.cmds("descarga") == []


def test_que_falte_claude_no_es_un_fallo_del_instalador_pero_se_dice(mundo):
    mundo.claude = None
    op = Opciones(sin_modelo=True, sin_acceso_directo=True)
    rs = I.ejecutar_pasos(mundo.ent, op)
    lineas, codigo = I.resumen(rs, op)
    assert codigo == 0 and any("claude" in l and "Queda" not in l and "cuenta" in l for l in lineas) and "Queda por hacer a mano:" in lineas
    assert any(l.startswith("[falta] Claude Code") for l in mundo.salida)
    # y con --comprobar sí es motivo de código 1 (falta algo)
    assert I.resumen(I.ejecutar_pasos(mundo.ent, Opciones(comprobar=True)), Opciones(comprobar=True))[1] == 1


def test_lineas_de_resultado_y_estados():
    assert Resultado("Paso", "ya", "x").linea() == "[ya estaba] Paso: x"
    assert Resultado("Paso", "falta", "x").linea().startswith("[falta] ")
    assert set(I.ETIQUETA) == set(I.ESTADOS)


def test_principal_lee_las_opciones_y_devuelve_el_codigo(mundo):
    codigo = I.principal(["--comprobar", "--sin-modelo"], mundo.ent)
    assert codigo == 1 and mundo.salida[0].startswith("WhisperMeet: comprobación") and not (mundo.raiz / ".venv").exists()
    codigo = I.principal(["--si", "--sin-acceso-directo", "--dev"], mundo.ent)
    assert codigo == 0 and "pytest" in mundo.instalados and mundo.cmds("acceso") == []
    with pytest.raises(SystemExit):
        I.principal(["--opcion-inventada"], mundo.ent)


# ---------------------------------------------------------------- lo real, sin instalar nada
def test_ejecutar_real_captura_y_gestiona_el_tiempo_y_los_errores():
    codigo, salida = I._ejecutar([sys.executable, "-c", "print('hola')"])
    assert codigo == 0 and salida.strip() == "hola"
    codigo, salida = I._ejecutar([sys.executable, "-c", "import time; time.sleep(5)"], timeout=0.3)
    assert codigo == 124 and "tiempo agotado" in salida
    codigo, _ = I._ejecutar(["programa-que-no-existe-xyz"])
    assert codigo == 127


def test_preguntar_sin_consola_devuelve_none(monkeypatch):
    class SinTty:
        def isatty(self):
            return False
    monkeypatch.setattr(sys, "stdin", SinTty())
    assert I._preguntar("¿Sí?") is None
    monkeypatch.setattr(sys, "stdin", None)
    assert I._preguntar("¿Sí?") is None


def test_instalar_py_solo_importa_biblioteca_estandar():
    import ast
    permitidos = set(sys.stdlib_module_names) | {"apuntes"}                                        # apuntes.requisitos se importa dentro de una función y solo usa la biblioteca estándar
    arbol = ast.parse((REPO / "instalar.py").read_text(encoding="utf-8"))
    raices = set()
    for n in ast.walk(arbol):
        if isinstance(n, ast.Import):
            raices |= {a.name.split(".")[0] for a in n.names}
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            raices.add(n.module.split(".")[0])
    assert raices <= permitidos, raices - permitidos


def test_requisitos_se_puede_importar_sin_terceros():
    """`apuntes.requisitos` es lo único de la app que el instalador importa; con el Python del sistema no hay numpy ni fastapi."""
    codigo = ("import sys\nfor m in ('numpy','fastapi','faster_whisper','pyaudiowpatch','webview'):\n    sys.modules[m] = None\n"
              "import apuntes.requisitos as r\nprint(r.comprobar_python((3,12,0))['estado'])\n")
    p = subprocess.run([sys.executable, "-c", codigo], cwd=str(REPO), capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(REPO)}, timeout=60)
    assert p.returncode == 0 and p.stdout.strip() == "bien", p.stderr


def test_gitattributes_fuerza_crlf_en_los_bat():
    """Sin esta regla, una descarga en ZIP o un clon sin autocrlf deja `instalar.bat` en LF, y cmd puede no encontrar la etiqueta de un `goto`."""
    reglas = [linea.split() for linea in (REPO / ".gitattributes").read_text(encoding="utf-8").splitlines() if linea.strip() and not linea.startswith("#")]
    assert any(r[0] == "*.bat" and "eol=crlf" in r[1:] for r in reglas)
