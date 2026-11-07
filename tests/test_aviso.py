"""Aviso flotante de llamada de Teams (apuntes/aviso.py, llamadas.vigilar_llamadas, VentanaAviso por Win32 aparte): con detector y ventana
FALSOS, sin registro, sin Teams, sin audio y sin modelo real. La ventana real se mide en pruebas\\probar_aviso_llamada.py."""
import asyncio
import shutil
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apuntes import aviso as AV
from apuntes import registro
from apuntes import ventana as V
from apuntes.analisis import ModeloLLM, Respuesta, Uso
from apuntes.aviso import AvisoLlamada, limpiar_titulo, tema_por_defecto
from apuntes.config import AVISO_CADUCA_S, Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.llamadas import vigilar_llamadas
from apuntes.rutas import Guardian
from apuntes.servidor import Difusor, crear_app
from apuntes.simulador import LineaSim

PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas" / "proyectos"
PROYECTO = "Proyecto Ficticio Alfa"


# ---------------------------------------------------------------------------------------------------- títulos de Teams
@pytest.mark.parametrize("crudo, esperado", [
    ("Unión a la reunión | NORDIA - Seguimiento Interno (EPM) | Microsoft Teams", "NORDIA - Seguimiento Interno (EPM)"),
    ("NORDIA - Seguimiento Interno (EPM) | Microsoft Teams", "NORDIA - Seguimiento Interno (EPM)"),
    ("NORDIA - Seguimiento Interno (EPM) - Microsoft Teams", "NORDIA - Seguimiento Interno (EPM)"),
    ("NORDIA - Seguimiento Interno (EPM) | ACME CONSULTING | usuario@example.com | Microsoft Teams",
     "NORDIA - Seguimiento Interno (EPM)"),
    ("Reunión | Revisión DataLake | Microsoft Teams", "Revisión DataLake"),
    ("Join meeting | Weekly sync | Microsoft Teams", "Weekly sync"),
    ("(2) Reunión con Ana Pérez | Microsoft Teams", "Reunión con Ana Pérez"),          # una llamada directa conserva su nombre
    ("Sprint​ review ​| Microsoft​ Teams", "Sprint review"),               # caracteres invisibles y espacios sueltos
    ("  Planning   Q4  |  Microsoft Teams ", "Planning Q4"),
])
def test_limpieza_de_titulos_de_teams(crudo, esperado):
    assert limpiar_titulo(crudo) == esperado


@pytest.mark.parametrize("crudo", [
    "Chat | Laura Gómez | ACME CONSULTING | usuario@example.com | Microsoft Teams",   # no es una reunión
    "Calendario | Microsoft Teams", "Microsoft Teams", "Unión a la reunión | Microsoft Teams", "Barra de control de uso compartido | Microsoft Teams",
    "", "   ", None, 42,
])
def test_un_titulo_que_no_es_de_reunion_no_da_tema(crudo):
    assert limpiar_titulo(crudo) == ""


def test_el_tema_nunca_pasa_del_tope_del_campo():
    assert len(limpiar_titulo("A" * 400 + " | Microsoft Teams")) <= AV.MAX_TEMA


def test_tema_por_defecto_con_la_hora_si_no_se_lee_el_titulo():
    ahora = datetime(2026, 11, 5, 13, 30)
    assert tema_por_defecto("", ahora) == "Llamada de Teams 13:30"
    assert tema_por_defecto("Revisión", ahora) == "Revisión"


def test_la_constante_de_caducidad_es_de_45_segundos():
    assert AVISO_CADUCA_S == 45


def test_la_geometria_del_aviso_esta_centrada_arriba_y_respeta_el_dpi():
    assert V.geometria_aviso((0, 0, 1920, 1040), 420, 190, 1.0) == (750, 14, 420, 190)
    x, y, w, h = V.geometria_aviso((0, 0, 1920, 1040), 420, 190, 1.5)    # 150 %: 630 x 285 px físicos
    assert (w, h, y) == (630, 285, 21) and x == (1920 - 630) // 2
    x, y, w, h = V.geometria_aviso((-1920, 40, 0, 1080), 420, 190, 1.0)     # el área de trabajo no empieza en (0, 0)
    assert x == -1920 + (1920 - 420) // 2 and y == 54


# ---------------------------------------------------------------------------------------------------- aviso con ventana falsa
class VentanaFalsa:
    def __init__(self, falla=False):
        self.falla, self.abierta, self.cerrada, self.url, self.altos, self.teclado = falla, False, False, None, [], []

    def abrir(self, url):
        if self.falla:
            raise RuntimeError("no hay interfaz nativa")
        self.abierta, self.url = True, url

    def cerrar(self):
        self.cerrada = True

    def redimensionar(self, alto):
        self.altos.append(alto)

    def pedir_teclado(self, si):
        self.teclado.append(si)


class GestorFalso:
    def __init__(self, estado="inactivo"):
        self.estado, self.llamada, self.llamada_flotante = estado, False, False
        self.eventos, self.iniciadas = [], []

    def emitir(self, tipo, **datos):
        self.eventos.append((tipo, datos))

    async def iniciar(self, *args):
        self.iniciadas.append(args)
        self.estado = "grabando"
        return {"ok": True}


def montar_aviso(tmp_path, titulo="Unión a la reunión | NORDIA - Seguimiento Interno (EPM) | Microsoft Teams", estado="inactivo", falla=False,
                 cfg_extra=None, **kw):
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"knowledge": "", **(cfg_extra or {})}, guardar=False)
    gestor = GestorFalso(estado)
    ventanas = []

    def fabrica():
        v = VentanaFalsa(falla)
        ventanas.append(v)
        return v

    aviso = AvisoLlamada(gestor, cfg, None, fabrica, "http://127.0.0.1:1/aviso?t=x", leer_titulo=lambda: limpiar_titulo(titulo),
                         ahora=lambda: datetime(2026, 11, 5, 13, 30), proyectos=lambda g: ["Cliente A", "Cliente B"], **kw)
    return aviso, gestor, cfg, ventanas


def run(coro):
    return asyncio.run(coro)


def test_mostrar_abre_la_ventana_con_el_tema_de_teams_y_los_valores_por_defecto(tmp_path):
    aviso, gestor, cfg, ventanas = montar_aviso(tmp_path)
    assert aviso.mostrar() is True
    assert len(ventanas) == 1 and ventanas[0].abierta and ventanas[0].url.endswith("/aviso?t=x")
    d = aviso.datos_publicos()
    assert d["tema"] == "NORDIA - Seguimiento Interno (EPM)" and d["activo"] is True
    assert d["proyecto"] == "" and d["idioma"] == "auto" and d["caduca_s"] == 45       # sin uso previo: Bandeja y Automático
    assert d["proyectos"] == ["Cliente A", "Cliente B"]
    aviso.cerrar("fin")


def test_sin_titulo_legible_el_tema_es_llamada_de_teams_con_la_hora(tmp_path):
    aviso, *_ = montar_aviso(tmp_path, titulo="Chat | Ana | Microsoft Teams")
    aviso.mostrar()
    assert aviso.datos_publicos()["tema"] == "Llamada de Teams 13:30"
    aviso.cerrar("fin")


def test_el_proyecto_y_el_idioma_por_defecto_son_los_ultimos_usados(tmp_path):
    aviso, *_ = montar_aviso(tmp_path, cfg_extra={"ultimo_proyecto": "cliente b", "ultimo_idioma": "ca"})
    aviso.mostrar()
    d = aviso.datos_publicos()
    assert d["proyecto"] == "Cliente B" and d["idioma"] == "ca"
    aviso.cerrar("fin")


def test_un_ultimo_proyecto_que_ya_no_existe_cae_a_la_bandeja(tmp_path):
    aviso, *_ = montar_aviso(tmp_path, cfg_extra={"ultimo_proyecto": "Borrado"})
    aviso.mostrar()
    assert aviso.datos_publicos()["proyecto"] == ""
    aviso.cerrar("fin")


def test_no_arranca_sin_la_casilla_de_aviso_a_los_asistentes(tmp_path):
    aviso, gestor, *_ = montar_aviso(tmp_path)
    aviso.mostrar()
    for marcada in (False, None, "true", 1):
        with pytest.raises(ValueError, match="avisado a los asistentes"):
            run(aviso.empezar("Cliente A", "Tema", "es", marcada))
    assert gestor.iniciadas == [] and aviso.activo      # nada empezó y el aviso sigue ahí
    aviso.cerrar("fin")


def test_empezar_con_la_casilla_inicia_la_sesion_normal_cierra_el_aviso_y_recuerda_la_eleccion(tmp_path):
    aviso, gestor, cfg, ventanas = montar_aviso(tmp_path)
    aviso.mostrar()
    r = run(aviso.empezar("cliente a", "  Mi   tema  ", "ca", True))
    assert r == {"ok": True}
    assert gestor.iniciadas == [("Cliente A", "Mi tema", None, None, [], "", "ca")]   # (proyecto, tema, cadencia, plan, objetivos, contexto, idioma)
    assert ventanas[0].cerrada and not aviso.activo and aviso.atendida
    assert cfg["ultimo_proyecto"] == "Cliente A" and cfg["ultimo_idioma"] == "ca"
    with pytest.raises(ValueError, match="ya no está activo"):
        run(aviso.empezar("Cliente A", "otra vez", "es", True))                      # un segundo clic no empieza otra sesión
    assert len(gestor.iniciadas) == 1


def test_empezar_sin_proyecto_va_a_la_bandeja_y_con_tema_vacio_usa_el_de_teams(tmp_path):
    aviso, gestor, *_ = montar_aviso(tmp_path)
    aviso.mostrar()
    run(aviso.empezar("", "   ", "auto", True))
    assert gestor.iniciadas[0][:2] == (None, "NORDIA - Seguimiento Interno (EPM)")


def test_un_proyecto_que_no_esta_en_la_lista_se_rechaza(tmp_path):
    aviso, gestor, *_ = montar_aviso(tmp_path)
    aviso.mostrar()
    with pytest.raises(ValueError, match="no está en la lista"):
        run(aviso.empezar("../Otro", "x", "es", True))
    assert gestor.iniciadas == []
    aviso.cerrar("fin")


def test_ahora_no_cierra_y_no_vuelve_en_la_misma_llamada(tmp_path):
    aviso, gestor, cfg, ventanas = montar_aviso(tmp_path)
    aviso.mostrar()
    aviso.descartar()
    assert ventanas[0].cerrada and not aviso.activo
    assert aviso.mostrar() is True and len(ventanas) == 1       # la misma llamada: no abre otra (y True = no hay que caer al banner)
    aviso.cerrar("fin")                                         # cuelga
    assert aviso.mostrar() is True and len(ventanas) == 2       # la llamada siguiente vuelve a salir
    aviso.cerrar("fin")


def test_con_el_interruptor_apagado_o_con_reunion_en_curso_no_abre_nada(tmp_path):
    aviso, _, _, ventanas = montar_aviso(tmp_path, cfg_extra={"detectar_llamadas": False})
    assert aviso.mostrar() is True and ventanas == []
    aviso, _, _, ventanas = montar_aviso(tmp_path, estado="grabando")
    assert aviso.mostrar() is True and ventanas == []


def test_si_la_ventana_no_se_puede_abrir_mostrar_devuelve_false(tmp_path):
    aviso, _, _, ventanas = montar_aviso(tmp_path, falla=True)
    assert aviso.mostrar() is False
    assert not aviso.activo and ventanas[0].cerrada


def test_si_la_pagina_no_carga_se_cierra_y_se_vuelve_al_banner(tmp_path):
    fallos = []
    aviso, gestor, _, ventanas = montar_aviso(tmp_path, espera_pagina_s=0.05, al_fallar=lambda: fallos.append(1))
    gestor.llamada = True
    aviso.mostrar()
    import time
    for _ in range(100):
        if ventanas[0].cerrada:
            break
        time.sleep(0.02)
    assert ventanas[0].cerrada and not aviso.activo
    assert ("llamada", {"activa": True, "flotante": False}) in gestor.eventos and gestor.llamada_flotante is False and fallos == [1]


def test_si_la_pagina_pidio_sus_datos_el_vigia_no_la_cierra(tmp_path):
    aviso, gestor, _, ventanas = montar_aviso(tmp_path, espera_pagina_s=0.1)
    gestor.llamada = True
    aviso.mostrar()
    aviso.datos_publicos()
    import time
    time.sleep(0.3)
    assert aviso.activo and not ventanas[0].cerrada
    aviso.cerrar("fin")


def test_cerrar_la_ventana_desde_fuera_cuenta_como_ahora_no(tmp_path):
    aviso, _, _, ventanas = montar_aviso(tmp_path)
    aviso.mostrar()
    aviso.ventana_cerrada()
    assert aviso.atendida and not aviso.activo
    assert aviso.mostrar() is True and len(ventanas) == 1


# ---------------------------------------------------------------------------------------------------- vigilancia con aviso
async def esperar(cond, t=10):
    for _ in range(int(t / 0.01)):
        if cond():
            return
        await asyncio.sleep(0.01)
    raise AssertionError("tiempo agotado")


def secuencia(valores, resto=True):
    """Lecturas falsas del micro: la secuencia y, después, `resto` para siempre (por defecto la llamada sigue)."""
    cola = list(valores)
    return lambda: cola.pop(0) if cola else resto


class AvisoFalso:
    def __init__(self, resultado=True, falla=False):
        self.resultado, self.falla, self.mostrados, self.cierres = resultado, falla, 0, []

    def mostrar(self):
        self.mostrados += 1
        if self.falla:
            raise RuntimeError("ventana rota")
        return self.resultado

    def cerrar(self, motivo=""):
        self.cierres.append(motivo)


def vigilar(gestor, leer, aviso, al_avisar=None, espera=0.8, cfg=None):
    cfg = cfg or SimpleNamespace(datos={"detectar_llamadas": True})

    async def go():
        t = asyncio.create_task(vigilar_llamadas(gestor, cfg, al_avisar, intervalo=0.001, leer=leer, aviso=aviso))
        await asyncio.sleep(espera)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    run(go())


def test_inicio_y_fin_de_llamada_abren_y_cierran_el_aviso_y_el_banner_no_sale():
    gestor, aviso, flash = GestorFalso(), AvisoFalso(), []
    vigilar(gestor, secuencia([True, True, True, False, False], resto=False), aviso, al_avisar=lambda: flash.append(1))
    assert gestor.eventos == [("llamada", {"activa": True, "flotante": True}), ("llamada", {"activa": False})]
    assert aviso.mostrados == 1 and aviso.cierres == ["fin"]
    assert flash == []                                  # con la ventana flotante no hace falta parpadear
    assert gestor.llamada is False and gestor.llamada_flotante is False


def test_una_sola_vez_por_llamada_y_otra_en_la_llamada_siguiente():
    gestor, aviso = GestorFalso(), AvisoFalso()
    vigilar(gestor, secuencia([True] * 6 + [False, False] + [True] * 3), aviso)
    assert aviso.mostrados == 2                         # 6 lecturas seguidas: un solo aviso; tras colgar y volver, otro
    assert [e[1].get("activa") for e in gestor.eventos] == [True, False, True]


def test_con_reunion_en_curso_no_abre_el_aviso():
    gestor, aviso = GestorFalso("grabando"), AvisoFalso()
    vigilar(gestor, secuencia([True] * 5), aviso)
    assert aviso.mostrados == 0 and gestor.eventos == []


def test_si_se_empieza_a_grabar_con_el_aviso_abierto_se_quita():
    gestor, aviso = GestorFalso(), AvisoFalso()

    async def go():
        cfg = SimpleNamespace(datos={"detectar_llamadas": True})
        t = asyncio.create_task(vigilar_llamadas(gestor, cfg, intervalo=0.001, leer=lambda: True, aviso=aviso))
        await esperar(lambda: aviso.mostrados == 1)
        gestor.estado = "grabando"                      # la persona empezó a grabar desde la ventana principal
        await esperar(lambda: aviso.cierres == ["fin"])
        await asyncio.sleep(0.05)
        t.cancel()
        with pytest.raises(asyncio.CancelledError):
            await t
    run(go())
    assert aviso.mostrados == 1                         # y no vuelve a salir en esta llamada


def test_si_el_aviso_flotante_falla_cae_al_banner_y_al_parpadeo():
    for aviso in (AvisoFalso(resultado=False), AvisoFalso(falla=True)):
        gestor, flash = GestorFalso(), []
        vigilar(gestor, secuencia([True, True, True]), aviso, al_avisar=lambda: flash.append(1))
        assert gestor.eventos[0] == ("llamada", {"activa": True})      # sin `flotante`: el banner de la pantalla de inicio sale
        assert flash == [1] and gestor.llamada is True and gestor.llamada_flotante is False


def test_sin_aviso_flotante_con_sin_ventana_sigue_el_banner_de_siempre():
    gestor, flash = GestorFalso(), []
    vigilar(gestor, secuencia([True, True, True]), None, al_avisar=lambda: flash.append(1))
    assert gestor.eventos == [("llamada", {"activa": True})] and flash == [1]


def test_con_el_interruptor_de_llamadas_apagado_no_abre_el_aviso():
    gestor, aviso = GestorFalso(), AvisoFalso()
    vigilar(gestor, lambda: True, aviso, cfg=SimpleNamespace(datos={"detectar_llamadas": False}))
    assert aviso.mostrados == 0 and gestor.eventos == []


def test_un_error_en_la_vigilancia_se_registra_y_sigue(tmp_path):
    gestor, aviso = GestorFalso(), AvisoFalso()
    gestor.emitir = lambda *a, **k: (_ for _ in ()).throw(ValueError("difusor roto"))   # revienta dentro de la vuelta
    vigilar(gestor, secuencia([True, True, True, True]), aviso)
    texto = registro.RUTA_LOG.read_text(encoding="utf-8")
    assert "vigilar_llamadas" in texto and ": difusor roto" not in texto and aviso.mostrados == 1


# ---------------------------------------------------------------------------------------------------- _vigilar sobrevive a una excepción
class LlmMinimo(ModeloLLM):
    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        import json
        if "compactar el contexto" in sistema:
            return Respuesta(json.dumps({"pm": "x", "fun": "x", "tec": "x", "rev": "x", "checks": [], "objetivos": []}), [Uso(modelo, 10, 10)], 1)
        raise AssertionError("prompt inesperado")


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    eventos = []
    gestor = Gestor(cfg, g, Consumo(None), LlmMinimo(), eventos.append, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    return gestor, cfg, g, tmp_path


def test_vigilar_registra_el_error_y_la_reunion_sigue(montaje):
    gestor, *_ = montaje

    async def go():
        await gestor.iniciar(PROYECTO, "Tema", "equipo")
        reales = gestor.equipo.comprobar
        fallos = {"n": 0}

        def rota(*a, **k):
            fallos["n"] += 1
            raise RuntimeError("monitor roto")

        gestor.equipo.comprobar = rota
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()                         # antes: la excepción subía a _bucle y la tarea moría sin avisar
        assert fallos["n"] == 1
        assert "RuntimeError" in registro.RUTA_LOG.read_text(encoding="utf-8") and ": monitor roto" not in registro.RUTA_LOG.read_text(encoding="utf-8")
        assert gestor.equipo._ultima_comprobacion > -1e8     # el siguiente intento espera a su cadencia, no se repite cada segundo
        gestor.equipo.comprobar = reales                # la vigilancia vuelve a funcionar cuando el fallo desaparece
        gestor.equipo._ultima_comprobacion = -1e9
        await gestor._vigilar()
        assert gestor.equipo._ultima_comprobacion > -1e8
        assert gestor.estado == "grabando"
        gestor.apagar()
    asyncio.run(go())


def test_el_bucle_de_la_grabacion_no_muere_por_un_fallo_del_monitor(montaje):
    gestor, *_ = montaje

    async def go():
        await gestor.iniciar(PROYECTO, "Tema", "equipo")

        def rota(*a, **k):
            raise RuntimeError("monitor roto en el bucle")

        gestor.equipo.comprobar = rota
        gestor.equipo._ultima_comprobacion = -1e9
        await asyncio.sleep(2.6)                        # _bucle pasa por _vigilar cada segundo
        bucles = [t for t in gestor._tareas if "_bucle" in repr(t)]
        assert bucles and not bucles[0].done(), "el bucle de la grabación murió"
        assert "RuntimeError" in registro.RUTA_LOG.read_text(encoding="utf-8") and ": monitor roto en el bucle" not in registro.RUTA_LOG.read_text(encoding="utf-8")
        gestor.apagar()
    asyncio.run(go())


def test_registro_no_repite_el_mismo_error_en_un_minuto(tmp_path):
    ruta = tmp_path / "x.log"
    assert registro.registrar_error("lugar", ValueError("a"), ruta) is True
    assert registro.registrar_error("lugar", ValueError("a"), ruta) is False
    assert registro.registrar_error("lugar", ValueError("b"), ruta) is True
    assert ruta.read_text(encoding="utf-8").count("ERROR en lugar") == 2


# ---------------------------------------------------------------------------------------------------- API
def cliente(tmp_path, aviso_real=True):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS, raiz)
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache")
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    difusor = Difusor()
    gestor = Gestor(cfg, g, Consumo(None), LlmMinimo(), difusor.emitir, simulacion=[LineaSim(9999.0, "yo", "fin")], velocidad=1)
    ventanas = []
    aviso = AvisoLlamada(gestor, cfg, g, lambda: ventanas.append(VentanaFalsa()) or ventanas[-1], "http://127.0.0.1:8123/aviso?t=tok",
                         leer_titulo=lambda: "Revisión de alcance") if aviso_real else None
    app = crear_app(gestor, difusor, cfg, g, "tok", 8123, aviso=aviso)
    cli = TestClient(app, headers={"X-Token": "tok", "host": "127.0.0.1:8123"}, base_url="http://127.0.0.1:8123")
    return cli, gestor, aviso, ventanas, cfg


def test_api_del_aviso_empezar_exige_la_casilla_y_empieza_solo_con_ella(tmp_path):
    cli, gestor, aviso, ventanas, cfg = cliente(tmp_path)
    with cli:
        assert aviso.mostrar() is True
        d = cli.get("/api/aviso").json()
        assert d["tema"] == "Revisión de alcance" and PROYECTO in d["proyectos"] and d["activo"] is True
        r = cli.post("/api/aviso/empezar", json={"proyecto": PROYECTO, "tema": "Revisión de alcance", "idioma": "es", "avisado": False})
        assert r.status_code == 400 and "avisado" in r.json()["detail"]
        assert gestor.estado == "inactivo"              # sin casilla no hay grabación
        r = cli.post("/api/aviso/empezar", json={"proyecto": PROYECTO, "tema": "Revisión de alcance", "idioma": "es", "avisado": True})
        assert r.status_code == 200 and gestor.estado == "grabando" and gestor.sesion.tema == "Revisión de alcance"
        assert ventanas[0].cerrada and cfg["ultimo_proyecto"] == PROYECTO and cfg["ultimo_idioma"] == "es"
        cli.post("/api/sesion/terminar")


def test_api_del_aviso_descartar_tamano_y_teclado(tmp_path):
    cli, gestor, aviso, ventanas, _ = cliente(tmp_path)
    with cli:
        aviso.mostrar()
        assert cli.post("/api/aviso/tamano", json={"alto": 321}).status_code == 200 and ventanas[0].altos == [321]
        assert cli.post("/api/aviso/teclado", json={"activo": True}).status_code == 200 and ventanas[0].teclado == [True]
        assert cli.post("/api/aviso/descartar").status_code == 200
        assert ventanas[0].cerrada and gestor.estado == "inactivo"


def test_api_del_aviso_sin_ventana_nativa_responde_400_y_la_pagina_existe(tmp_path):
    cli, *_ = cliente(tmp_path, aviso_real=False)
    with cli:
        assert cli.get("/api/aviso").status_code == 400
        assert cli.post("/api/aviso/empezar", json={"avisado": True}).status_code == 400
        assert cli.get("/api/aviso", headers={"X-Token": "malo"}).status_code == 401      # como el resto de la API: con token
        pagina = cli.get("/aviso")
        assert pagina.status_code == 200 and "He avisado a los asistentes" in pagina.text and "Empezar a transcribir" in pagina.text


def test_empezar_por_la_ventana_principal_cierra_un_aviso_abierto(tmp_path):
    cli, gestor, aviso, ventanas, cfg = cliente(tmp_path)
    with cli:
        aviso.mostrar()
        assert cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "x", "idioma": "ca"}).status_code == 200
        assert ventanas[0].cerrada and cfg["ultimo_idioma"] == "ca"
        cli.post("/api/sesion/terminar")


def test_el_snapshot_dice_si_el_aviso_flotante_atiende_la_llamada(tmp_path):
    cli, gestor, *_ = cliente(tmp_path)
    with cli:
        assert cli.get("/api/sesion").json()["llamada_flotante"] is False
        gestor.llamada, gestor.llamada_flotante = True, True
        d = cli.get("/api/sesion").json()
        assert d["llamada"] is True and d["llamada_flotante"] is True


def test_la_pagina_del_aviso_no_depende_de_la_red():
    web = Path(__file__).resolve().parent.parent / "web"
    for nombre in ("aviso.html", "aviso.css", "aviso.js"):
        texto = (web / nombre).read_text(encoding="utf-8")
        assert "http://" not in texto.replace("http://www.w3.org", "") and "https://" not in texto and "//cdn" not in texto, nombre
