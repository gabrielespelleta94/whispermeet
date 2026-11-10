"""Comprobación de requisitos (ola D): cada comprobación en sus tres estados con dobles, el endpoint, y que no se abre el micrófono ni se llama a ningún modelo.
Datos ficticios; nada de rutas ni nombres reales."""
import json
import sys
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apuntes import requisitos as R
from apuntes.analisis import ModeloLLM
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.servidor import Difusor, crear_app

PUERTO, TOKEN = 8131, "t0k3n-req"
CLAVES = {"clave", "titulo", "estado", "detalle", "como_arreglarlo"}


def _sin_ruta(obj, base):
    """Ni la ruta de `base` ni su forma con barras ni la escapada de JSON (en Windows `json.dumps` duplica las barras invertidas: «str(base) not in json.dumps(x)» pasaba siempre)."""
    texto = json.dumps(obj, ensure_ascii=False)
    for forma in {str(base), str(base).replace("\\", "/"), json.dumps(str(base))[1:-1]}:
        assert forma not in texto, forma


def _forma(r):
    assert set(r) == CLAVES and r["estado"] in R.ESTADOS and r["titulo"] and r["detalle"], r


# ---------------------------------------------------------------- Python
@pytest.mark.parametrize("version,estado", [((3, 12, 0), "bien"), ((3, 13, 1), "bien"), ((3, 11, 9), "falta"), ((3, 9, 2), "falta")])
def test_python_bien_o_falta(version, estado):
    r = R.comprobar_python(version)
    _forma(r)
    assert r["estado"] == estado and r["clave"] == "python"
    if estado == "falta":
        assert "3.12" in r["como_arreglarlo"] and ".".join(map(str, version)) in r["detalle"]


# ---------------------------------------------------------------- claude
def test_claude_encontrado_y_no_encontrado_sin_ejecutarlo(monkeypatch):
    import subprocess
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("no se ejecuta claude"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("no se ejecuta claude"))
    ok = R.comprobar_claude(lambda nombre: "C:/herramientas/claude.exe" if nombre == "claude" else None)
    falta = R.comprobar_claude(lambda nombre: None)
    _forma(ok), _forma(falta)
    assert ok["estado"] == "bien" and falta["estado"] == "falta"
    assert "herramientas" not in json.dumps(ok)             # la ruta del ejecutable no sale
    assert "iniciado sesión" in ok["detalle"]               # y avisa de lo que no se puede saber desde aquí
    assert "claude" in falta["como_arreglarlo"]


# ---------------------------------------------------------------- modelo de Whisper
def _modelo(base: Path, repo: str, completo=True):
    snap = base / ("models--" + repo.replace("/", "--")) / "snapshots" / "abc123"
    snap.mkdir(parents=True)
    if completo:
        (snap / "model.bin").write_bytes(b"x")


def test_modelo_presente_incompleto_y_ausente(tmp_path):
    base = tmp_path / "modelos"
    base.mkdir()
    assert R.comprobar_modelo("small", base)["estado"] == "falta"
    _modelo(base, "Systran/faster-whisper-small", completo=False)
    r = R.comprobar_modelo("small", base)
    assert r["estado"] == "aviso" and "incompleta" in r["detalle"]
    _modelo(base, "mobiuslabsgmbh/faster-whisper-large-v3-turbo")
    assert R.comprobar_modelo("large-v3-turbo", base)["estado"] == "bien"
    _modelo(base, "Systran/faster-whisper-base")
    r = R.comprobar_modelo("base", base)
    _forma(r)
    assert r["estado"] == "bien" and "descargado" in r["detalle"]
    assert _sin_ruta(r, tmp_path) is None


def test_modelo_sin_configurar_desconocido_o_carpeta_propia(tmp_path):
    assert R.comprobar_modelo("", tmp_path)["estado"] == "falta"
    r = R.comprobar_modelo("modelo-inventado", tmp_path)
    assert r["estado"] == "falta" and "no es un modelo" in r["detalle"]
    propio = tmp_path / "mi-modelo-ct2"
    propio.mkdir()
    assert R.comprobar_modelo(str(propio), tmp_path)["estado"] == "falta"        # carpeta sin model.bin
    (propio / "model.bin").write_bytes(b"x")
    r = R.comprobar_modelo(str(propio), tmp_path)
    assert r["estado"] == "bien" and "mi-modelo-ct2" in r["detalle"] and _sin_ruta(r, tmp_path) is None


def test_la_tabla_de_repositorios_coincide_con_faster_whisper():
    utils = pytest.importorskip("faster_whisper.utils")
    assert R.REPOS_WHISPER == utils._MODELS


# ---------------------------------------------------------------- audio
def test_audio_en_sus_tres_estados():
    fila = {"indice": 1, "nombre": "Dispositivo ficticio", "canales": 2, "frecuencia": 48000}
    bien = R.comprobar_audio(lambda: {"error": "", "entradas": [fila], "salidas": [fila]})
    aviso = R.comprobar_audio(lambda: {"error": "", "entradas": [fila], "salidas": []})
    sin_mic = R.comprobar_audio(lambda: {"error": "", "entradas": [], "salidas": [fila]})
    sin_lib = R.comprobar_audio(lambda: {"error": "pyaudiowpatch no disponible: x", "entradas": [], "salidas": []})
    for r in (bien, aviso, sin_mic, sin_lib):
        _forma(r)
    assert [bien["estado"], aviso["estado"], sin_mic["estado"], sin_lib["estado"]] == ["bien", "aviso", "falta", "falta"]
    assert "Dispositivo ficticio" not in json.dumps([bien, aviso])                   # no se listan nombres de dispositivos


def test_audio_que_falla_no_rompe_la_comprobacion():
    def mal():
        raise OSError("ruta-privada-del-usuario")
    r = R.comprobar_audio(mal)
    _forma(r)
    assert r["estado"] == "aviso" and "ruta-privada" not in json.dumps(r) and "OSError" in r["detalle"]


def test_audio_solo_enumera_y_nunca_abre_un_stream(monkeypatch):
    abiertos = []

    class PA:
        def __init__(self):
            pass

        def get_host_api_info_by_type(self, _):
            return {"index": 0, "defaultInputDevice": 1, "defaultOutputDevice": 2}

        def get_device_count(self):
            return 1

        def get_device_info_by_index(self, i):
            return {"index": 1, "name": "Micro ficticio", "hostApi": 0, "maxInputChannels": 1, "defaultSampleRate": 16000.0}

        def open(self, *a, **k):
            abiertos.append(1)
            raise AssertionError("se ha abierto un stream de audio")

        def get_loopback_device_info_generator(self):
            return iter(())

        def terminate(self):
            pass

    falso = types.ModuleType("pyaudiowpatch")
    falso.PyAudio, falso.paWASAPI = PA, 13
    monkeypatch.setitem(sys.modules, "pyaudiowpatch", falso)
    r = R.comprobar_audio()
    assert r["estado"] == "aviso" and abiertos == []          # un micrófono y ninguna salida; y no se abrió nada


# ---------------------------------------------------------------- carpetas
def test_carpetas_en_sus_estados(tmp_path):
    raiz = tmp_path / "Mis Proyectos"
    raiz.mkdir()
    ok = {r["clave"]: r for r in R.comprobar_carpetas(str(raiz), "", {"bandeja": tmp_path / "bandeja", "planes": tmp_path / "planes"})}
    assert {k: v["estado"] for k, v in ok.items()} == {"carpeta_proyectos": "bien", "carpeta_knowledge": "bien", "carpetas_locales": "bien"}
    assert "Mis Proyectos" in ok["carpeta_proyectos"]["detalle"] and _sin_ruta(ok, tmp_path) is None       # solo el nombre de la carpeta final
    mal = {r["clave"]: r for r in R.comprobar_carpetas(str(tmp_path / "no existe"), str(tmp_path / "Conocimiento"), {})}
    assert mal["carpeta_proyectos"]["estado"] == "falta" and mal["carpeta_knowledge"]["estado"] == "aviso" and "carpetas_locales" not in mal
    assert "no existe" in mal["carpeta_proyectos"]["detalle"] and "Conocimiento" in mal["carpeta_knowledge"]["detalle"] and _sin_ruta(mal, tmp_path) is None
    vacio = R.comprobar_carpetas("", "", None)
    assert vacio[0]["estado"] == "falta"
    for r in [*ok.values(), *mal.values(), *vacio]:
        _forma(r)


def test_carpetas_locales_sin_permiso_dicen_cual(tmp_path):
    locales = {"bandeja": tmp_path / "bandeja", "sesiones": tmp_path / "sesiones"}
    r = {x["clave"]: x for x in R.comprobar_carpetas(str(tmp_path), "", locales, puede_escribir=lambda p: Path(p).name != "sesiones")}
    assert r["carpetas_locales"]["estado"] == "falta" and "sesiones" in r["carpetas_locales"]["detalle"] and "bandeja" not in r["carpetas_locales"]["detalle"]
    assert _sin_ruta(r, tmp_path) is None


def test_escribible_no_crea_nada(tmp_path):
    futura = tmp_path / "a" / "b" / "c"
    assert R.escribible(futura) is True and not (tmp_path / "a").exists()                # sube hasta lo que existe y solo mira el permiso
    fichero = tmp_path / "fichero.txt"
    fichero.write_text("x")
    assert R.escribible(fichero) is False


# ---------------------------------------------------------------- todo junto, sin efectos
class SinModelo(ModeloLLM):
    def completar(self, *a, **k):
        raise AssertionError("las comprobaciones no llaman a ningún modelo")


def _montaje(tmp_path, modelo="small"):
    raiz = tmp_path / "proyectos"
    raiz.mkdir(exist_ok=True)
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", "proyectos_extra": [], "whisper_modelo": modelo}, guardar=False)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", planes=tmp_path / "planes", sesiones_locales=tmp_path / "sesiones", checks=tmp_path / "checks",
                 backlog=tmp_path / "backlog", datos=tmp_path / "datos", tipos=tmp_path / "tipos")
    return cfg, g


def _instantanea(base: Path):
    return sorted(str(p.relative_to(base)) for p in base.rglob("*"))


def test_comprobar_todo_no_escribe_ni_llama_a_nada(tmp_path, monkeypatch):
    import subprocess
    cfg, g = _montaje(tmp_path)
    modelos = tmp_path / "modelos"
    _modelo(modelos, "Systran/faster-whisper-small")
    antes = _instantanea(tmp_path)
    # ni un subproceso, ni la librería de transcripción, ni el cliente de claude
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subproceso"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("subproceso"))

    class Bomba(types.ModuleType):
        def __getattr__(self, nombre):
            raise AssertionError("se ha tocado faster_whisper")
    monkeypatch.setitem(sys.modules, "faster_whisper", Bomba("faster_whisper"))
    from apuntes.analisis import claude_cli
    monkeypatch.setattr(claude_cli.ClaudeCLI, "completar", lambda *a, **k: pytest.fail("llamada a claude"))
    fila = {"indice": 1, "nombre": "x", "canales": 1, "frecuencia": 16000}
    res = R.comprobar_todo(cfg, g, version=(3, 12, 4), buscar_claude=lambda n: "claude", listar_audio=lambda: {"error": "", "entradas": [fila], "salidas": [fila]}, modelos_dir=modelos)
    assert res["estado"] == "bien" and res["faltan"] == 0 and res["avisos"] == 0
    assert [x["clave"] for x in res["comprobaciones"]] == ["python", "claude", "modelo_whisper", "audio", "carpeta_proyectos", "carpeta_knowledge", "carpetas_locales"]
    assert _instantanea(tmp_path) == antes                                               # ni siquiera crea las carpetas locales que faltan
    assert _sin_ruta(res, tmp_path) is None and "\\" not in json.dumps(res["comprobaciones"][-1]["detalle"])


def test_el_estado_global_es_el_peor():
    mk = lambda e: {"clave": "x", "titulo": "t", "estado": e, "detalle": "d", "como_arreglarlo": ""}  # noqa: E731
    assert R.resumen([mk("bien"), mk("bien")])["estado"] == "bien"
    assert R.resumen([mk("bien"), mk("aviso")])["estado"] == "aviso"
    r = R.resumen([mk("aviso"), mk("falta"), mk("falta")])
    assert r["estado"] == "falta" and r["faltan"] == 2 and r["avisos"] == 1


# ---------------------------------------------------------------- el endpoint
def _cliente(tmp_path, monkeypatch, audio=None):
    cfg, g = _montaje(tmp_path)
    modelos = tmp_path / "modelos"
    _modelo(modelos, "Systran/faster-whisper-small")
    monkeypatch.setattr("apuntes.transcripcion.MODELOS_DIR", modelos)
    fila = {"indice": 1, "nombre": "x", "canales": 1, "frecuencia": 16000}
    monkeypatch.setattr("apuntes.audio.listar_dispositivos", audio or (lambda: {"error": "", "entradas": [fila], "salidas": [fila]}))
    monkeypatch.setattr("apuntes.analisis.claude_cli.shutil.which", lambda n: "claude" if n == "claude" else None)
    dif = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), SinModelo(), dif.emitir)
    app = crear_app(gestor, dif, cfg, g, TOKEN, PUERTO)
    return TestClient(app, base_url=f"http://127.0.0.1:{PUERTO}", headers={"X-Token": TOKEN}), gestor


def test_endpoint_requisitos_responde_y_esta_protegido(tmp_path, monkeypatch):
    cli, gestor = _cliente(tmp_path, monkeypatch)
    with cli:
        assert cli.get("/api/requisitos", headers={"X-Token": "otro"}).status_code == 401     # protegido como el resto
        assert cli.get("/api/requisitos", headers={"X-Token": ""}).status_code == 401
        d = cli.get("/api/requisitos").json()
        assert d["estado"] in R.ESTADOS and len(d["comprobaciones"]) == 7
        for r in d["comprobaciones"]:
            _forma(r)
        por = {r["clave"]: r["estado"] for r in d["comprobaciones"]}
        assert por["claude"] == "bien" and por["modelo_whisper"] == "bien" and por["audio"] == "bien" and por["carpeta_proyectos"] == "bien"
        assert _sin_ruta(d, tmp_path) is None                                                # nada de rutas del usuario
        assert gestor.estado == "inactivo"                                                       # y no se ha empezado nada


def test_endpoint_dice_que_falta_cuando_falta(tmp_path, monkeypatch):
    cli, _ = _cliente(tmp_path, monkeypatch, audio=lambda: {"error": "", "entradas": [], "salidas": []})
    monkeypatch.setattr("apuntes.analisis.claude_cli.shutil.which", lambda n: None)
    with cli:
        d = cli.get("/api/requisitos").json()
    por = {r["clave"]: r for r in d["comprobaciones"]}
    assert d["estado"] == "falta" and d["faltan"] == 2
    assert por["claude"]["estado"] == "falta" and por["audio"]["estado"] == "falta" and por["audio"]["como_arreglarlo"]


def test_endpoint_no_abre_el_microfono_ni_llama_al_modelo(tmp_path, monkeypatch):
    """Con espías de verdad: la enumeración de audio se llama (parado) una vez por petición y NUNCA con una reunión en curso; no se abre ninguna captura, no se
    lanza ningún subproceso (así se ejecuta `claude`) y no se llama al modelo. Si se quita la guarda `audio_en_uso` del endpoint, falla."""
    import subprocess
    from apuntes import audio
    from apuntes.analisis import claude_cli
    enumeraciones = []
    fila = {"indice": 1, "nombre": "x", "canales": 1, "frecuencia": 16000}

    def espia_audio():
        enumeraciones.append(1)
        return {"error": "", "entradas": [fila], "salidas": [fila]}
    cli, gestor = _cliente(tmp_path, monkeypatch, audio=espia_audio)
    monkeypatch.setattr(audio.Captura, "iniciar", lambda *a, **k: pytest.fail("se ha abierto el micrófono"))
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: pytest.fail("subproceso: así se ejecutaría claude"))
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("subproceso: así se ejecutaría claude"))
    monkeypatch.setattr(claude_cli.ClaudeCLI, "completar", lambda *a, **k: pytest.fail("llamada a claude"))
    with cli:
        assert cli.get("/api/requisitos").status_code == 200
        assert cli.get("/api/requisitos").status_code == 200       # y repetirlo no cambia nada: «Volver a comprobar»
        assert len(enumeraciones) == 2                              # parado, sí se enumera (el espía funciona)
        for estado in ("grabando", "pausada", "procesando"):
            gestor.estado = estado
            assert cli.get("/api/requisitos").status_code == 200
        assert len(enumeraciones) == 2                              # con una reunión en curso, ni una vez más
    assert gestor.consumo.llamadas == []                           # ninguna llamada al modelo registrada


def test_con_una_reunion_en_curso_no_se_vuelve_a_enumerar_el_audio(tmp_path, monkeypatch):
    """No se toca el audio de una grabación en marcha: ni siquiera enumerando."""
    def bomba():
        raise AssertionError("se ha enumerado el audio con una reunión en curso")
    r = R.comprobar_audio(bomba, en_uso=True)
    _forma(r)
    assert r["estado"] == "bien" and "reunión en curso" in r["detalle"]
    cli, gestor = _cliente(tmp_path, monkeypatch, audio=bomba)
    gestor.estado = "grabando"
    with cli:
        d = cli.get("/api/requisitos").json()
    assert {x["clave"]: x["estado"] for x in d["comprobaciones"]}["audio"] == "bien"


# ---------------------------------------------------------------- textos: plural de verdad, sin «(s)»
@pytest.mark.parametrize("n_in,n_out,esperado", [
    (1, 1, "1 micrófono y 1 salida de audio."),
    (2, 1, "2 micrófonos y 1 salida de audio."),
    (1, 2, "1 micrófono y 2 salidas de audio."),
    (3, 2, "3 micrófonos y 2 salidas de audio."),
])
def test_audio_dice_los_numeros_en_singular_o_plural(n_in, n_out, esperado):
    fila = {"indice": 1, "nombre": "x", "canales": 1, "frecuencia": 16000}
    r = R.comprobar_audio(lambda: {"error": "", "entradas": [fila] * n_in, "salidas": [fila] * n_out})
    assert r["estado"] == "bien" and r["detalle"] == esperado, r["detalle"]


@pytest.mark.parametrize("n_in,esperado", [(1, "1 micrófono, pero"), (2, "2 micrófonos, pero")])
def test_audio_sin_salidas_tambien_concuerda(n_in, esperado):
    fila = {"indice": 1, "nombre": "x", "canales": 1, "frecuencia": 16000}
    r = R.comprobar_audio(lambda: {"error": "", "entradas": [fila] * n_in, "salidas": []})
    assert r["estado"] == "aviso" and esperado in r["detalle"]


def test_los_textos_de_requisitos_no_llevan_plural_entre_parentesis():
    assert "(s)" not in Path(R.__file__).read_text(encoding="utf-8")


# ---------------------------------------------------------------- la Knowledge del fichero también pasa las reglas nuevas (aviso, nunca bloqueo)
def _res_knowledge(tmp_path, knowledge, **kw):
    cfg, g = _montaje(tmp_path)
    cfg.actualizar({"knowledge": knowledge}, guardar=False)
    fila = {"indice": 1, "nombre": "x", "canales": 1, "frecuencia": 16000}
    res = R.comprobar_todo(cfg, g, version=(3, 12, 4), buscar_claude=lambda n: "claude", listar_audio=lambda: {"error": "", "entradas": [fila], "salidas": [fila]},
                           modelos_dir=tmp_path / "modelos", **kw)
    return res, {x["clave"]: x for x in res["comprobaciones"]}["carpeta_knowledge"]


def test_una_knowledge_que_es_la_raiz_de_una_unidad_sale_como_aviso_sin_ruta(tmp_path):
    res, k = _res_knowledge(tmp_path, tmp_path.anchor)
    _forma(k)
    assert k["estado"] == "aviso" and "unidad" in k["detalle"] and "Cámbiala en Ajustes, Privacidad" in k["como_arreglarlo"]
    assert res["avisos"] >= 1
    _sin_ruta(res, tmp_path)
    assert tmp_path.anchor not in json.dumps(res, ensure_ascii=False)


def test_una_knowledge_que_se_solapa_con_la_carpeta_de_proyectos_sale_como_aviso(tmp_path):
    (tmp_path / "proyectos" / "Docs").mkdir(parents=True)
    for ruta in (tmp_path / "proyectos" / "Docs", tmp_path):                       # dentro de la raíz de proyectos y conteniéndola
        res, k = _res_knowledge(tmp_path, str(ruta))
        assert k["estado"] == "aviso" and "solapa" in k["detalle"] and "Cámbiala en Ajustes, Privacidad" in k["como_arreglarlo"], k
        _sin_ruta(res, tmp_path)


def test_una_knowledge_valida_o_vacia_no_da_aviso(tmp_path):
    (tmp_path / "Documentacion").mkdir()
    _res, k = _res_knowledge(tmp_path, str(tmp_path / "Documentacion"))
    assert k["estado"] == "bien" and "Documentacion" in k["detalle"]
    _res, k = _res_knowledge(tmp_path, "")
    assert k["estado"] == "bien"


def test_una_knowledge_que_no_existe_sigue_siendo_aviso_como_antes(tmp_path):
    _res, k = _res_knowledge(tmp_path, str(tmp_path / "Perdida"))
    assert k["estado"] == "aviso" and "no existe" in k["detalle"]
