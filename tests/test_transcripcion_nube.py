"""El transcriptor con la nube (apuntes/transcripcion.py + motor_nube.py): el motor se decide en cada trozo, respaldo local sin perder texto, VAD, idioma,
pistas y cuentas. Servidor falso REAL en bucle local (tests/servidor_nube_falso.py) y un doble de Whisper para el respaldo: ni red ni modelo reales."""
import threading
import time

import numpy as np
import pytest

from apuntes import motor_nube as MN
from apuntes import transcripcion as TRN
from apuntes.config import Config
from apuntes.dictado import Dictado, _TranscriptorDictado
from apuntes.transcripcion import Transcriptor
from servidor_nube_falso import ServidorNubeFalso
from test_transcripcion import ModeloDoble

CLAVE = "sk-ficticia-0000000000"
SR = 16000


class Montaje:
    """Transcriptor + lo entregado + cuántas veces se cargó Whisper. `cfg` es un diccionario editable: cambiarlo cambia el motor del siguiente trozo."""

    def __init__(self, url, modelo=None, clave=CLAVE, permitir=None, iniciar=True, **cfg_extra):
        self.entregado, self.cargas, self.modelo = [], [], modelo
        self.permitir = {"si": True} if permitir is None else permitir
        self.cfg = {"idioma": "es", "whisper_modelo": "x", "whisper_hilos": 1, "whisper_beam": 5, "whisper_vad": False,
                    "transcripcion_motor": "nube", "nube_url_base": url, "nube_modelo": "gpt-transcribe", "nube_autenticacion": "bearer",
                    "nube_dialecto": "auto", **cfg_extra}
        yo = self

        class Tr(Transcriptor):
            def cargar_modelo(self):
                yo.cargas.append(1)
                if yo.modelo is None:
                    raise RuntimeError("sin modelo local en este test")
                return yo.modelo
        self.tr = Tr(self.cfg, lambda f, t, x, **kw: self.entregado.append((f, t, x, kw)), clave_nube=lambda: self.clave, permitir_nube=lambda: self.permitir["si"])
        self.clave = clave
        self.tr.prompt = "Reunión de trabajo: Tema."
        self.tr.prompt_ca = "Reunió de treball: Tema."
        self.tr.prompt_en = "Work meeting: Tema."
        if iniciar:
            self.tr.iniciar()

    def textos(self):
        return [x[2] for x in self.entregado]

    def trozo(self, seg=2.0, fuente="yo", t0=0.0, aplazar=False):
        self.tr.encolar(fuente, np.zeros(int(SR * seg), dtype=np.float32), t0, aplazar=aplazar)
        self.esperar()

    def esperar(self):
        fin = time.time() + 15
        while not self.tr.vacio() and time.time() < fin:
            time.sleep(0.01)
        time.sleep(0.05)

    def cerrar(self):
        self.tr.detener()
        self.tr.nube.cerrar()


@pytest.fixture
def servidor():
    with ServidorNubeFalso() as s:
        yield s


@pytest.fixture
def montar(servidor):
    creados = []

    def _montar(**kw):
        m = Montaje(servidor.url_base, **kw)
        creados.append(m)
        return m
    yield _montar
    for m in creados:
        m.cerrar()


def _local(*textos):
    return ModeloDoble(list(textos))


# ---------------------------------------------------------------- arranque y entrega
def test_motor_nube_no_carga_whisper_al_empezar(montar):
    m = montar(modelo=_local("x"))
    fin = time.time() + 5
    while m.tr.estado != "listo" and time.time() < fin:
        time.sleep(0.01)
    assert m.tr.estado == "listo"   # el hilo no espera al modelo: el respaldo se precarga aparte
    assert _esperar_hasta(lambda: m.cargas == [1]) and m.tr.motor_activo == "nube"
    assert m.tr.motor_activo == "nube"   # antes del primer trozo: el que se usaría


def test_trozo_nube_entrega_texto_filtrado_y_sin_palabras(montar, servidor):
    m = montar()
    m.tr.vocabulario, m.tr.vocabulario_curado = ["SAP"], ["SAP"]
    m.tr.entrega_palabras = True   # aunque se pida, la nube no da palabras
    servidor.ok("Hablamos de sap con el equipo.").ok("Gracias por ver el vídeo.").ok("Reunión de trabajo: Tema.").ok("")
    for i in range(4):
        m.trozo(t0=float(i))
    assert [(f, t, x) for f, t, x, _kw in m.entregado] == [("yo", 0.0, "Hablamos de SAP con el equipo.")]   # glosario aplicado; alucinación, copia del prompt y vacío fuera
    assert m.entregado[0][3] == {}   # sin `palabras=`
    assert m.tr.motor_activo == "nube" and m.tr.tramos_nube == 4 and m.tr.tramos_local == 0


def test_la_entrega_lleva_la_continuidad_de_la_nube(montar, servidor):
    m = montar()
    servidor.ok("Primera frase del tramo anterior.").ok("Segunda.")
    m.trozo()
    m.trozo()
    assert "Primera frase del tramo anterior." in servidor.valores("prompt", 1)[0]


# ---------------------------------------------------------------- respaldo
def test_fallo_nube_cae_a_local_con_carga_perezosa_y_no_pierde_texto(montar, servidor):
    m = montar(modelo=_local("Texto del respaldo local."))
    servidor.error(500).error(500)
    m.trozo()
    assert m.textos() == ["Texto del respaldo local."]
    assert m.cargas == [1] and m.tr.nube.respaldo_trozos == 1 and m.tr.perdidos_s == 0
    assert m.tr.motor_activo == "local" and m.tr.tramos_local == 1 and m.tr.error_respaldo == ""
    assert len(servidor.peticiones) == 2   # el intento y su reintento breve


def test_respaldo_sin_modelo_cuenta_perdido_y_no_pone_estado_error(montar, servidor):
    m = montar(modelo=None)
    servidor.error(422).error(422)
    m.trozo(seg=3.0)
    assert m.textos() == [] and abs(m.tr.perdidos_s - 3.0) < 0.01
    assert m.tr.estado == "listo" and m.tr.error_respaldo == "No se pudo cargar el modelo local de respaldo."
    assert {"evento": "respaldo_sin_modelo"} in m.tr.nube.tomar_eventos()
    m.trozo(seg=1.0)   # no se vuelve a intentar la carga antes de 60 s
    assert m.cargas == [1, 1] and abs(m.tr.perdidos_s - 4.0) < 0.01 and m.tr.estado == "listo"   # la precarga y la carga perezosa; después ya no


def test_reintento_de_procesar_va_solo_a_local(montar, servidor):
    class UnaCaida(ModeloDoble):
        def transcribe(self, audio, **kw):
            if not self.llamadas:
                self.llamadas.append(kw)
                raise RuntimeError("un tramo que el modelo no digiere")
            return super().transcribe(audio, **kw)
    m = montar(modelo=UnaCaida(["Texto tras el reintento."]))
    servidor.error(422)
    m.trozo()
    assert m.textos() == ["Texto tras el reintento."]
    assert len(servidor.peticiones) == 1 and m.tr.reintentos == 1   # el reintento de `_procesar` no vuelve a llamar a la nube


def test_cuentas_locales_solo_suman_trozos_locales(montar, servidor):
    m = montar(modelo=_local("Local."))
    servidor.ok("Uno.").ok("Dos.")
    m.trozo()
    m.trozo()
    assert (m.tr.audio_total_s, m.tr.calculo_total_s, m.tr.cpu_total_s) == (0.0, 0.0, 0.0) and m.tr.velocidad_x is None   # y la velocidad es de Whisper local
    m.cfg["transcripcion_motor"] = "local"
    m.trozo(seg=2.0)
    assert m.tr.audio_total_s == pytest.approx(2.0) and m.tr.calculo_total_s > 0


def test_cambio_de_motor_a_mitad_de_reunion_en_los_dos_sentidos(montar, servidor):
    m = montar(modelo=_local("Local uno.", "Local dos."))
    servidor.ok("Nube uno.").ok("Nube dos.")
    m.trozo()
    m.cfg["transcripcion_motor"] = "local"
    m.trozo()
    assert m.textos() == ["Nube uno.", "Local uno."] and m.tr.motor_activo == "local" and len(servidor.peticiones) == 1
    m.cfg["transcripcion_motor"] = "nube"
    m.trozo()
    assert m.textos()[-1] == "Nube dos." and m.tr.motor_activo == "nube" and len(servidor.peticiones) == 2
    assert m.tr.nube.respaldo_trozos == 0   # con el motor en local no es un «respaldo»


def test_solo_local_a_mitad_va_a_local_y_deja_el_evento(montar, servidor):
    m = montar(modelo=_local("Local."))
    servidor.ok("Nube.")
    m.trozo()
    m.permitir["si"] = False
    m.trozo()
    assert m.textos() == ["Nube.", "Local."] and len(servidor.peticiones) == 1
    assert m.tr.nube.tomar_eventos() == [{"evento": "solo_local"}] and m.tr.nube.respaldo_trozos == 1
    assert m.tr.nube.publico()["estado"] == "solo_local"


def test_sin_clave_va_a_local(montar, servidor):
    m = montar(modelo=_local("Local."), clave=None)
    m.trozo()
    assert m.textos() == ["Local."] and servidor.peticiones == [] and m.cargas == [1]   # con motor nube y sin clave Whisper se carga al empezar
    assert m.tr.nube.tomar_eventos() == [{"evento": "sin_clave"}]


def test_config_sin_clave_motor_se_comporta_como_hoy(servidor):
    cfg = {"idioma": "es", "whisper_modelo": "x", "whisper_hilos": 1, "whisper_beam": 5}   # sin ninguna de las claves de la nube
    modelo, entregado, cargas = _local("Texto de siempre."), [], []

    class Tr(Transcriptor):
        def cargar_modelo(self):
            cargas.append(1)
            return modelo
    tr = Tr(cfg, lambda f, t, x, **kw: entregado.append(x))
    assert tr.nube.decidir().motivo == "config" and tr.motor_activo == "local"
    tr.iniciar()
    try:
        tr.encolar("yo", np.zeros(SR, dtype=np.float32), 0.0)
        fin = time.time() + 10
        while not tr.vacio() and time.time() < fin:
            time.sleep(0.01)
        time.sleep(0.05)
    finally:
        tr.detener()
    assert entregado == ["Texto de siempre."] and cargas == [1] and tr.nube.respaldo_trozos == 0 and tr.nube.trozos == 0
    assert tr.audio_total_s == pytest.approx(1.0) and servidor.peticiones == []


def test_aplazados_tambien_van_a_la_nube(montar, servidor):
    m = montar()
    servidor.ok("Eco que en realidad también es lo que dice el micro.")
    m.trozo(aplazar=True)
    assert len(servidor.peticiones) == 1 and m.textos() == ["Eco que en realidad también es lo que dice el micro."]


def test_detener_durante_una_peticion_descarta_la_respuesta(montar, servidor):
    m = montar()
    servidor.lento(1.0, "texto que llega tarde")
    m.tr.encolar("yo", np.zeros(SR * 2, dtype=np.float32), 0.0)
    fin = time.time() + 5
    while not servidor.peticiones and time.time() < fin:
        time.sleep(0.01)
    m.tr.detener()
    time.sleep(1.3)
    assert m.entregado == []


# ---------------------------------------------------------------- VAD
def test_vad_sin_voz_no_envia(montar, servidor, monkeypatch):
    monkeypatch.setattr(TRN, "timestamps_voz", lambda audio, ms: [])
    m = montar(whisper_vad=True, modelo=_local("No debería usarse."))
    m.trozo(seg=0.35)
    assert servidor.peticiones == [] and m.textos() == [] and m.tr.nube.silencio_trozos == 1 and m.tr.tramos_local == 0
    monkeypatch.setattr(TRN, "timestamps_voz", lambda audio, ms: [{"start": 0, "end": 3000}])   # 0,19 s de voz: por debajo de 0,25 s
    m.trozo(seg=2.0)
    assert servidor.peticiones == [] and m.tr.nube.silencio_trozos == 2


def test_vad_sube_solo_la_voz_concatenada(montar, servidor, monkeypatch):
    monkeypatch.setattr(TRN, "timestamps_voz", lambda audio, ms: [{"start": 0, "end": 8000}, {"start": 16000, "end": 24000}])
    m = montar(whisper_vad=True)
    servidor.ok("Voz.")
    m.trozo(seg=3.0)
    assert servidor.peticiones[0]["fichero"]["tam"] == 44 + 2 * 16000   # 1 s de voz en WAV PCM16 mono
    assert m.tr.nube.audio_s == pytest.approx(1.0)


def test_sin_vad_se_sube_el_trozo_entero(montar, servidor, monkeypatch):
    monkeypatch.setattr(TRN, "timestamps_voz", lambda audio, ms: None)   # el VAD no se pudo usar
    m = montar(whisper_vad=True)
    servidor.ok("Entero.")
    m.trozo(seg=1.5)
    assert servidor.peticiones[0]["fichero"]["tam"] == 44 + 2 * int(1.5 * SR)


def test_el_vad_real_no_rompe_y_es_opcional():
    voz = TRN.timestamps_voz(np.zeros(SR, dtype=np.float32), 500)
    assert voz is None or voz == []   # silencio: sin tramos con voz (o sin VAD en este entorno)


# ---------------------------------------------------------------- dialecto clásico, idioma y pistas
def test_clasico_aplica_filtro_no_speech_y_logprob(montar, servidor):
    m = montar(nube_modelo="whisper-1")
    servidor.ok("x", segmentos=[{"start": 0.0, "text": "buena", "no_speech_prob": 0.1, "avg_logprob": -0.3},
                                {"start": 1.0, "text": "silencio", "no_speech_prob": 0.9, "avg_logprob": -0.3},
                                {"start": 2.0, "text": "dudosa", "no_speech_prob": 0.1, "avg_logprob": -2.0},
                                {"start": 3.0, "text": "sin medidas"}])
    m.trozo()
    assert m.textos() == ["buena sin medidas"]
    assert servidor.valores("response_format") == ["verbose_json"] and servidor.valores("language") == ["es"]


def test_idioma_fuera_de_lista_repite_una_vez_con_el_de_partida(montar, servidor):
    m = montar(idioma="auto")
    servidor.ok("Hello there.", idiomas=["fr"]).ok("Bonjour.", idiomas=["es"])
    m.trozo()
    assert len(servidor.peticiones) == 2
    assert servidor.valores("languages[]", 0) == ["es", "ca", "en"] and servidor.valores("languages[]", 1) == ["es"]
    assert m.textos() == ["Bonjour."] and m.tr.nube.idioma_repetidos == 1
    servidor.ok("Otra vez.", idiomas=["fr"]).ok("Sigue en francés.", idiomas=["fr"])   # solo UNA repetición: la segunda respuesta se acepta
    m.trozo(t0=5.0)
    assert len(servidor.peticiones) == 4 and m.tr.nube.idioma_repetidos == 2 and m.textos()[-1] == "Sigue en francés."


def test_idioma_fuera_de_lista_en_clasico_repite_con_language(montar, servidor):
    m = montar(idioma="auto", nube_modelo="whisper-1")
    servidor.ok("Hello", idiomas=["fr"]).ok("Hola", idiomas=["es"])
    m.trozo()
    assert "language" not in servidor.nombres_de_campos(0) and servidor.valores("language", 1) == ["es"]


def test_auto_gpt_envia_idiomas_auto_con_el_ultimo_primero(montar, servidor):
    m = montar(idioma="auto")
    servidor.ok("Bon dia.", idiomas=["ca"]).ok("Bon dia de nou.", idiomas=["ca"]).ok("Hola.", idiomas=["es"])
    m.trozo(fuente="yo")
    m.trozo(fuente="yo", t0=3.0)
    m.trozo(fuente="reunion", t0=6.0)
    assert servidor.valores("languages[]", 0) == ["es", "ca", "en"]
    assert servidor.valores("languages[]", 1) == ["ca", "es", "en"]   # el último usado en esa fuente, primero
    assert servidor.valores("languages[]", 2) == ["es", "ca", "en"]   # la otra fuente no se mezcla


def test_idioma_fijo_se_envia_tal_cual(montar, servidor):
    m = montar(idioma="ca")
    servidor.ok("Bon dia.")
    m.trozo()
    assert servidor.valores("languages[]") == ["ca"] and "Reunió de treball" in servidor.valores("prompt")[0]


def test_rapido_acorta_prompt_y_keywords(montar, servidor):
    m = montar(iniciar=False)
    m.tr.vocabulario = [f"Termino{i:02d}" for i in range(40)]
    m.tr._ultima["yo"] = "Esta es la última frase conservada del tramo anterior."
    servidor.ok("a").ok("b")
    audio = np.zeros(SR * 2, dtype=np.float32)
    m.tr._segmentos_nube(audio, "yo", False, False)
    m.tr._segmentos_nube(audio, "yo", True, False)
    normal, rapido = servidor.valores("prompt", 0)[0], servidor.valores("prompt", 1)[0]
    assert len(normal) <= TRN.MAX_PROMPT_CHARS and "última frase conservada" in normal and len(servidor.valores("keywords[]", 0)) == 30
    assert len(rapido) <= TRN.MAX_PROMPT_CHARS_RAPIDO and "última frase" not in rapido and len(servidor.valores("keywords[]", 1)) == 10
    assert servidor.valores("keywords[]", 1) == [f"Termino{i:02d}" for i in range(10)]   # los primeros mandan
    assert "Términos" not in normal   # en gpt-transcribe el vocabulario va en keywords, no en el prompt
    assert m.tr.prompt_llamadas == 2 and m.tr.prompt_chars_total == len(normal) + len(rapido)


def test_clasico_lleva_el_vocabulario_en_el_prompt(montar, servidor):
    m = montar(nube_modelo="whisper-1", iniciar=False)
    m.tr.vocabulario = ["SAP", "Fiori"]
    servidor.ok("a")
    m.tr._segmentos_nube(np.zeros(SR * 2, dtype=np.float32), "yo", False, False)
    assert "Términos: SAP, Fiori." in servidor.valores("prompt")[0] and "keywords[]" not in servidor.nombres_de_campos()


# ---------------------------------------------------------------- dictado
def test_dictado_siempre_local(tmp_path, servidor):
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"transcripcion_motor": "nube", "nube_url_base": servidor.url_base}, guardar=False)
    assert _TranscriptorDictado.forzar_local is True and Transcriptor.forzar_local is False
    t = _TranscriptorDictado(cfg, lambda *a, **k: None, clave_nube=lambda: CLAVE)
    assert t.nube is None and t.motor_activo == "local"
    modelo = _local("Dictado local.")
    t._modelo = modelo
    assert t._segmentos(np.zeros(SR, dtype=np.float32), "yo")[0][1] == "Dictado local."
    d = Dictado(cfg, lambda ev: None)
    assert d._transcriptor_real(lambda *a: None).nube is None
    assert servidor.peticiones == []


# ---------------------------------------------------------------- revisión crítica: 200 sin texto, plazo, «Solo local» entre intentos, contadores y carga del respaldo
def test_un_200_sin_text_cae_a_local_y_cuenta_como_fallo(montar, servidor):
    m = montar(modelo=_local("Texto del respaldo.", "Otro del respaldo."))
    servidor.crudo(b'{"error": "portal cautivo"}').crudo(b'{"message": "proxy"}')
    m.trozo()
    n = m.tr.nube
    assert m.textos() == ["Texto del respaldo."] and len(servidor.peticiones) == 1   # "rechazo" no se reintenta
    assert (n.fallos, n.respaldo_trozos, n.trozos) == (1, 1, 0)
    m.trozo(t0=3.0)   # el segundo seguido abre el cortacircuitos
    assert m.textos() == ["Texto del respaldo.", "Otro del respaldo."] and n.publico()["estado"] == "respaldo"


def test_un_trozo_con_servidor_lento_no_retiene_mas_del_plazo(montar, servidor, monkeypatch):
    monkeypatch.setattr(MN, "PLAZO_TROZO_S", 2.5)   # el plazo real es de 12 s: aquí se acorta para no dormir de verdad
    m = montar(modelo=_local("Respaldo."))
    servidor.lento(8.0, "tarde")
    ini = time.monotonic()
    m.trozo()
    assert m.textos() == ["Respaldo."] and len(servidor.peticiones) == 1   # sin tiempo para reintentar: a local
    assert time.monotonic() - ini < 2.5 + 2.5


def test_solo_local_entre_el_primer_intento_y_el_reintento_no_hay_segunda_peticion(montar, servidor):
    m = montar(modelo=_local("Respaldo local."))
    m.tr.nube.dormir = lambda s: m.permitir.update(si=False)   # el usuario activa «Solo local» mientras espera el reintento
    servidor.error(503).ok("No debe llegar.")
    m.trozo()
    assert len(servidor.peticiones) == 1 and m.textos() == ["Respaldo local."]


def test_la_repeticion_por_idioma_no_cuenta_dos_trozos_ni_dos_veces_el_audio(montar, servidor):
    m = montar(idioma="auto")
    servidor.ok("Hello there.", idiomas=["fr"]).ok("Bonjour.", idiomas=["es"])
    m.trozo()
    n = m.tr.nube
    assert len(servidor.peticiones) == 2 and (n.trozos, n.idioma_repetidos) == (1, 1) and n.audio_s == pytest.approx(2.0)
    assert n.bytes_enviados > 2 * 44 and n.resumen()["trozos"] == 1


def test_velocidad_x_solo_se_actualiza_con_trozos_de_whisper_local(montar, servidor):
    m = montar(modelo=_local("Local."))
    servidor.ok("Nube.")
    m.trozo()
    assert m.tr.tramos_nube == 1 and m.tr.velocidad_x is None   # un trozo de la nube no es una medida de Whisper
    m.cfg["transcripcion_motor"] = "local"
    m.trozo(t0=3.0)
    assert m.tr.tramos_local == 1 and m.tr.velocidad_x and m.tr.velocidad_x > 0


def test_con_el_motor_en_local_a_mitad_de_reunion_el_estado_publico_es_local(montar, servidor):
    m = montar(modelo=_local("Local."))
    servidor.ok("Nube.")
    m.trozo()
    assert m.tr.nube.publico()["estado"] == "activa"
    m.cfg["transcripcion_motor"] = "local"
    assert m.tr.nube.publico()["estado"] == "local" and m.tr.nube.publico()["mensaje"] == ""


# ---- el respaldo local nunca descarga el modelo en plena reunión
def _whisper_falso(monkeypatch, tmp_path, retardo=0.0, falla=False):
    import sys
    import types
    creados = []

    class WhisperModelFalso:   # doble: el modelo real no se carga jamás en los tests
        def __init__(self, nombre, **kw):
            if retardo:
                time.sleep(retardo)
            if falla:
                raise OSError("el modelo no está en disco (ficticio)")
            creados.append(kw)
    monkeypatch.setitem(sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=WhisperModelFalso))
    monkeypatch.setattr(TRN, "MODELOS_DIR", tmp_path / "modelos")
    return creados


def _tr_nube(motor="nube"):
    cfg = {"idioma": "es", "whisper_modelo": "x", "whisper_hilos": 1, "whisper_beam": 5, "whisper_vad": False, "transcripcion_motor": motor,
           "nube_url_base": "http://127.0.0.1:9/v1", "nube_modelo": "gpt-transcribe", "nube_autenticacion": "bearer", "nube_dialecto": "auto"}
    return Transcriptor(cfg, lambda *a, **k: None, clave_nube=lambda: CLAVE, permitir_nube=lambda: True)


def _esperar_hasta(cond, s=5.0):
    fin = time.time() + s
    while not cond() and time.time() < fin:
        time.sleep(0.01)
    return cond()


def test_con_motor_nube_el_respaldo_se_precarga_aparte_y_solo_desde_disco(monkeypatch, tmp_path):
    creados = _whisper_falso(monkeypatch, tmp_path)
    tr = _tr_nube()
    tr.iniciar()
    try:
        assert _esperar_hasta(lambda: tr._modelo is not None)
        assert tr.estado == "listo" and len(creados) == 1 and creados[0]["local_files_only"] is True
        tr._asegurar_local()   # ya está: la carga perezosa no lo duplica
        assert len(creados) == 1
    finally:
        tr.detener()


def test_la_precarga_sin_modelo_en_disco_no_avisa_ni_para_el_transcriptor(monkeypatch, tmp_path):
    _whisper_falso(monkeypatch, tmp_path, falla=True)
    tr = _tr_nube()
    tr.iniciar()
    try:
        assert _esperar_hasta(lambda: tr.estado == "listo")
        assert _esperar_hasta(lambda: not any(t.name == "precarga-whisper" for t in threading.enumerate()))
        assert tr._modelo is None and tr.error_respaldo == "" and tr.nube.tomar_eventos() == []   # sin avisos: «Requisitos» ya lo dice
    finally:
        tr.detener()


def test_precarga_y_carga_perezosa_no_duplican_el_modelo(monkeypatch, tmp_path):
    creados = _whisper_falso(monkeypatch, tmp_path, retardo=0.4)
    tr = _tr_nube()
    tr.iniciar()
    try:
        hilos = [threading.Thread(target=tr._asegurar_local) for _ in range(3)]
        for h in hilos:
            h.start()
        for h in hilos:
            h.join(10)
        assert _esperar_hasta(lambda: tr._modelo is not None) and len(creados) == 1
    finally:
        tr.detener()


def test_la_carga_perezosa_usa_local_files_only_y_si_falla_es_respaldo_sin_modelo(monkeypatch, tmp_path):
    creados = _whisper_falso(monkeypatch, tmp_path)
    tr = _tr_nube()
    tr._asegurar_local()
    assert len(creados) == 1 and creados[0]['local_files_only'] is True
    assert tr._solo_en_disco is False
    _whisper_falso(monkeypatch, tmp_path, falla=True)
    tr2 = _tr_nube()
    with pytest.raises(OSError):
        tr2._asegurar_local()
    assert tr2._modelo is None and tr2.nube.tomar_eventos() == [{"evento": "respaldo_sin_modelo"}]


def test_la_carga_inicial_del_modo_local_queda_como_hoy(monkeypatch, tmp_path):
    creados = _whisper_falso(monkeypatch, tmp_path)
    tr = _tr_nube(motor="local")
    tr.iniciar()
    try:
        assert _esperar_hasta(lambda: tr._modelo is not None)
        assert len(creados) == 1 and "local_files_only" not in creados[0]   # puede descargar el modelo, como siempre
    finally:
        tr.detener()
