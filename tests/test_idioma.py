"""Idioma de la reunión (auto | es | ca): decisión pura por fragmento, el modelo recibe el idioma elegido en los tres modos (transcriptor, gestor,
servidor y dictado), initial_prompt coherente, filtros de alucinaciones en catalán y señales del Monitor en catalán SIN cambiar el español.
Todo con un modelo de Whisper falso: ni audio real ni descargas."""
import asyncio
import json
import time
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from apuntes import disparo as DP
from apuntes import transcripcion as TR
from apuntes.config import IDIOMAS_REUNION, Config, validar_idioma
from apuntes.dictado import Dictado
from apuntes.equipo import monitor as MO
from apuntes.gestor import Gestor
from apuntes.servidor import Difusor, crear_app
from apuntes.transcripcion import (MIN_CONFIANZA_AUTO, MIN_DURACION_DETECCION_S, MIN_MASA_AUTO, Transcriptor, decidir_idioma,
                                   filtrar_texto, prompt_tema)
from test_contexto_reunion import LLM, PROYECTO, TOKEN, iniciar_y_esperar, montar, correr
from test_transcripcion import ModeloDoble, TranscriptorDoble

FIXTURES = Path(__file__).resolve().parent / "fixtures"
SR = 16000


def probs(es=0.0, ca=0.0, **otros):
    """Lo que devuelve `detect_language` en su tercer elemento: [(idioma, p)] de mayor a menor."""
    return sorted([("es", es), ("ca", ca), *otros.items()], key=lambda x: -x[1])


# ================================================================ decisión pura
def test_con_confianza_y_duracion_suficientes_manda_la_deteccion():
    assert decidir_idioma(probs(es=0.9, ca=0.08), 5.0, None) == ("es", "detectado")
    assert decidir_idioma(probs(es=0.1, ca=0.85), 5.0, "es") == ("ca", "detectado")
    assert decidir_idioma({"es": 0.1, "ca": 0.85}, 5.0, "es") == ("ca", "detectado")        # también acepta un diccionario


def test_un_fragmento_corto_reutiliza_el_ultimo_idioma_o_el_primero_de_la_lista():
    p = probs(es=0.99, ca=0.0)
    assert decidir_idioma(p, MIN_DURACION_DETECCION_S - 0.01, "ca") == ("ca", "corto")
    assert decidir_idioma(p, 0.5, None) == ("es", "corto")                                   # sin ninguno: el primero de idiomas_auto
    assert decidir_idioma(probs(es=0.99), 0.5, None, ["ca", "es"]) == ("ca", "corto")
    assert decidir_idioma(p, MIN_DURACION_DETECCION_S, "ca") == ("es", "detectado")          # justo en el umbral ya cuenta


def test_poca_confianza_entre_los_dos_idiomas_reutiliza_el_ultimo():
    # 60/40 (renormalizado) está por debajo de MIN_CONFIANZA_AUTO: un fragmento dudoso no cambia de idioma
    assert decidir_idioma(probs(es=0.55, ca=0.36), 6.0, "ca") == ("ca", "poca_confianza")
    assert decidir_idioma(probs(es=0.36, ca=0.55), 6.0, "es") == ("es", "poca_confianza")
    assert decidir_idioma(probs(es=0.45, ca=0.45), 6.0, None) == ("es", "poca_confianza")   # fragmento con los dos idiomas a partes iguales


def test_solo_elige_entre_los_idiomas_permitidos():
    # el modelo cree que es francés/occitano: nunca se devuelve otro idioma (por defecto se elige entre es, ca y en)
    assert decidir_idioma(probs(es=0.04, ca=0.03, fr=0.9, oc=0.03), 6.0, "ca") == ("ca", "poca_masa")
    assert decidir_idioma(probs(es=0.30, ca=0.25, oc=0.4, fr=0.05), 6.0, None)[0] in ("es", "ca", "en")
    for p in (probs(es=0.9, fr=0.1), probs(ca=0.9, fr=0.1), probs(fr=1.0), [], None):
        assert decidir_idioma(p, 6.0, None)[0] in ("es", "ca", "en")
    # con solo es+ca (config antigua) el inglés queda fuera, como antes
    assert decidir_idioma(probs(es=0.04, ca=0.03, en=0.9, fr=0.03), 6.0, "ca", ("es", "ca")) == ("ca", "poca_masa")
    assert decidir_idioma(probs(es=0.4, ca=0.1), 6.0, None) == ("es", "detectado")           # es+ca = 0,5 justo: suficiente
    assert decidir_idioma(probs(es=0.4, ca=0.1), 6.0, None, min_masa=0.51) == ("es", "poca_masa")
    assert decidir_idioma(probs(es=0.9), 6.0, None, ["es"]) == ("es", "fijo")                # un solo idioma permitido: sin detectar
    assert decidir_idioma(probs(ca=0.9), 6.0, "es", ["es"]) == ("es", "fijo")


def test_sin_deteccion_o_con_un_ultimo_idioma_no_permitido():
    assert decidir_idioma(None, 6.0, "ca") == ("ca", "sin_deteccion")
    assert decidir_idioma([], 6.0, None) == ("es", "sin_deteccion")
    assert decidir_idioma(None, 6.0, "fr") == ("es", "sin_deteccion")                        # un último idioma ajeno a la lista se ignora
    assert decidir_idioma(None, 6.0, "en") == ("en", "sin_deteccion")


def test_ingles_entre_es_ca_y_en():
    assert decidir_idioma(probs(es=0.05, ca=0.03, en=0.9), 6.0, "es") == ("en", "detectado")
    assert decidir_idioma(probs(es=0.5, ca=0.1, en=0.4), 6.0, "en") == ("en", "poca_confianza")      # 50 % renormalizado: se mantiene
    assert decidir_idioma(probs(es=0.9, ca=0.05, en=0.05), 6.0, "en") == ("es", "detectado")          # un fragmento claro cambia de nuevo
    assert decidir_idioma(probs(en=0.99), 1.0, "en") == ("en", "corto")
    assert decidir_idioma(probs(en=0.02, es=0.01, ca=0.01, fr=0.9), 6.0, "en") == ("en", "poca_masa")
    assert decidir_idioma(probs(es=0.1, en=0.8), 6.0, None, ("en", "es")) == ("en", "detectado")
    assert prompt_tema("Kick-off", "en") == "Work meeting: Kick-off."
    assert TR.construir_prompt("Work meeting: X.", ["SAP"], etiqueta=TR.ETIQUETAS["en"]) == "Work meeting: X. Terms: SAP."


def test_la_reutilizacion_no_se_queda_pegada_en_la_funcion_pura():
    # Tras muchos fragmentos cortos en catalán, UN fragmento largo y claro en español cambia a español
    ultimo = "ca"
    for _ in range(6):
        ultimo, motivo = decidir_idioma(probs(es=0.9), 1.0, ultimo)
        assert (ultimo, motivo) == ("ca", "corto")
    assert decidir_idioma(probs(es=0.92, ca=0.05), 4.0, ultimo) == ("es", "detectado")


def test_constantes_razonables():
    assert 1.0 <= MIN_DURACION_DETECCION_S <= 3.0 and 0.5 < MIN_CONFIANZA_AUTO < 0.95 and 0 < MIN_MASA_AUTO <= 0.8


# ================================================================ el modelo recibe el idioma elegido
class ModeloIdioma(ModeloDoble):
    """Whisper falso con detect_language: devuelve las probabilidades guionizadas y registra cada llamada."""
    def __init__(self, respuestas, deteccion=()):
        super().__init__(respuestas)
        self.deteccion, self.detecciones = list(deteccion), []

    def detect_language(self, audio=None, **kw):
        self.detecciones.append(audio.size / SR)
        p = self.deteccion.pop(0) if self.deteccion else probs(es=0.9, ca=0.05)
        if isinstance(p, Exception):
            raise p
        return p[0][0], p[0][1], p


CFG = {"idioma": "es", "whisper_beam": 5, "whisper_modelo": "x", "whisper_hilos": 1}


def correr_tr(entradas, respuestas, deteccion=(), idioma=None, cfg=None, vocab=("PMS",), idiomas_auto=None):
    """Encola [(fuente, segundos)] de uno en uno (la continuidad depende del anterior). -> (modelo, transcriptor, emitidos)."""
    modelo, emitidos = ModeloIdioma(respuestas, deteccion), []
    config = dict(CFG, **(cfg or {}))
    if idiomas_auto:
        config["idiomas_auto"] = idiomas_auto
    tr = TranscriptorDoble(config, lambda f, t, x: emitidos.append((f, x)), modelo)
    tr.idioma = idioma
    tr.prompt, tr.prompt_ca, tr.vocabulario = prompt_tema("Seguimiento", "es"), prompt_tema("Seguimiento", "ca"), list(vocab)
    tr.iniciar()
    try:
        for i, (fuente, seg) in enumerate(entradas):
            tr.encolar(fuente, np.zeros(int(SR * seg), dtype=np.float32), float(i))
            fin = time.time() + 5
            while not tr.vacio() and time.time() < fin:
                time.sleep(0.01)
            time.sleep(0.05)
    finally:
        tr.detener()
    return modelo, tr, emitidos


def test_modo_es_fuerza_espanol_sin_detectar_y_con_el_prompt_de_siempre():
    modelo, tr, _ = correr_tr([("yo", 5.0)], ["Hola equipo"], idioma="es")
    kw = modelo.llamadas[0]
    assert kw["language"] == "es" and modelo.detecciones == []
    assert kw["initial_prompt"] == "Reunión de trabajo: Seguimiento. Términos: PMS."


def test_modo_ca_fuerza_catalan_sin_detectar_y_con_el_prompt_catalan():
    modelo, tr, _ = correr_tr([("yo", 5.0)], ["Hola equip"], idioma="ca")
    kw = modelo.llamadas[0]
    assert kw["language"] == "ca" and modelo.detecciones == []
    assert kw["initial_prompt"] == "Reunió de treball: Seguimiento. Termes: PMS."
    assert tr.prompt_para("yo").startswith("Reunió de treball: Seguimiento.")


def test_modo_en_fuerza_ingles_con_su_prompt():
    modelo, tr, _ = correr_tr([("yo", 5.0)], ["Hello team"], idioma="en", cfg={})
    assert modelo.llamadas[0]["language"] == "en" and modelo.detecciones == []
    tr2 = TranscriptorDoble(CFG, lambda *a: None, modelo)
    tr2.idioma, tr2.prompt, tr2.prompt_en, tr2.vocabulario = "en", "Reunión de trabajo: X.", prompt_tema("X", "en"), ["SAP"]
    assert tr2.prompt_para("yo") == "Work meeting: X. Terms: SAP."


def test_modo_auto_puede_elegir_ingles():
    modelo, tr, emitidos = correr_tr([("yo", 5.0)], ["Hello everyone."], idioma="auto",
                                     deteccion=[probs(es=0.05, ca=0.02, en=0.9)])
    assert modelo.llamadas[0]["language"] == "en"


def test_modo_auto_detecta_por_fragmento_y_el_prompt_sigue_al_idioma():
    modelo, tr, emitidos = correr_tr(
        [("yo", 5.0), ("yo", 5.0), ("yo", 5.0)], ["Bon dia a tothom.", "Buenos días a todos.", "Ara toca el pla."],
        deteccion=[probs(ca=0.9, es=0.06), probs(es=0.9, ca=0.07), probs(ca=0.8, es=0.15)], idioma="auto")
    assert [c["language"] for c in modelo.llamadas] == ["ca", "es", "ca"]
    assert modelo.detecciones == [5.0, 5.0, 5.0]
    ps = [c["initial_prompt"] for c in modelo.llamadas]
    assert ps[0].startswith("Reunió de treball: Seguimiento. Termes: PMS.")
    assert ps[1].startswith("Reunión de trabajo: Seguimiento. Términos: PMS.")
    assert ps[2].startswith("Reunió de treball: Seguimiento. Termes: PMS.")
    assert [x for _, x in emitidos] == ["Bon dia a tothom.", "Buenos días a todos.", "Ara toca el pla."]


def test_sin_idioma_en_la_reunion_se_usa_el_de_la_configuracion():
    for cfg_idioma, esperado in (("es", "es"), ("ca", "ca")):
        modelo, _, _ = correr_tr([("yo", 5.0)], ["Hola"], idioma=None, cfg={"idioma": cfg_idioma})
        assert modelo.llamadas[0]["language"] == esperado and modelo.detecciones == []
    modelo, _, _ = correr_tr([("yo", 5.0)], ["Hola"], idioma=None, cfg={"idioma": "auto"}, deteccion=[probs(ca=0.9)])
    assert modelo.llamadas[0]["language"] == "ca" and len(modelo.detecciones) == 1
    # configuración con un valor ajeno: se comporta como español (nunca pasa un idioma desconocido a Whisper)
    modelo, _, _ = correr_tr([("yo", 5.0)], ["Hola"], idioma=None, cfg={"idioma": "klingon"})
    assert modelo.llamadas[0]["language"] == "es"


def test_un_fragmento_corto_no_gasta_deteccion_y_no_se_queda_pegado():
    """Varios fragmentos cortos en un idioma reutilizan el último SIN detectar; un fragmento largo y claro en el otro cambia."""
    entradas = [("yo", 6.0), ("yo", 1.0), ("yo", 1.2), ("yo", 0.8), ("yo", 6.0)]
    respuestas = ["Bon dia, comencem la reunió.", "Sí.", "D'acord.", "Molt bé.", "Vale, pues ahora hablamos del plan de pruebas."]
    modelo, tr, _ = correr_tr(entradas, respuestas, idioma="auto",
                              deteccion=[probs(ca=0.93, es=0.04), probs(es=0.9, ca=0.05)])
    assert [c["language"] for c in modelo.llamadas] == ["ca", "ca", "ca", "ca", "es"]
    assert modelo.detecciones == [6.0, 6.0]                      # los tres cortos no detectaron
    assert tr._ultimo_idioma["yo"] == "es"


def test_un_fragmento_largo_pero_dudoso_no_cambia_el_idioma():
    modelo, _, _ = correr_tr([("yo", 6.0), ("yo", 6.0), ("yo", 6.0)], ["a b c d e f", "g h i j k l", "m n o p q r"], idioma="auto",
                             deteccion=[probs(ca=0.9, es=0.05), probs(es=0.5, ca=0.4),       # mezcla de los dos idiomas: 56/44
                                        probs(es=0.9, ca=0.05)])
    assert [c["language"] for c in modelo.llamadas] == ["ca", "ca", "es"]


def test_cada_fuente_recuerda_su_propio_idioma():
    modelo, tr, _ = correr_tr([("yo", 6.0), ("reunion", 6.0), ("yo", 1.0), ("reunion", 1.0)], ["a b c d e f", "g h i j k l", "m n o p q r", "s t u v w x"],
                              idioma="auto", deteccion=[probs(ca=0.9, es=0.05), probs(es=0.9, ca=0.05)])
    assert [c["language"] for c in modelo.llamadas] == ["ca", "es", "ca", "es"]      # los cortos heredan de SU fuente, no de la otra
    assert tr._ultimo_idioma == {"yo": "ca", "reunion": "es"}


def test_sin_ultimo_idioma_el_corto_empieza_por_el_primero_de_idiomas_auto():
    modelo, _, _ = correr_tr([("yo", 0.8)], ["Hola"], idioma="auto")
    assert modelo.llamadas[0]["language"] == "es"
    modelo, _, _ = correr_tr([("yo", 0.8)], ["Hola"], idioma="auto", idiomas_auto=["ca", "es"])
    assert modelo.llamadas[0]["language"] == "ca"


def test_si_la_deteccion_falla_se_transcribe_igual_con_el_ultimo_idioma():
    modelo, _, emitidos = correr_tr([("yo", 6.0), ("yo", 6.0)], ["Bon dia a tothom.", "Seguim amb el pla."], idioma="auto",
                                    deteccion=[probs(ca=0.9, es=0.05), RuntimeError("sin memoria")])
    assert [c["language"] for c in modelo.llamadas] == ["ca", "ca"] and len(emitidos) == 2


def test_modelo_sin_detect_language_no_rompe_nada():
    """Un modelo que no ofrezca la API (versión antigua): se trata como fallo de detección."""
    modelo = ModeloDoble(["Hola a todos."])
    emitidos = []
    tr = TranscriptorDoble(dict(CFG), lambda f, t, x: emitidos.append(x), modelo)
    tr.idioma, tr.prompt = "auto", "Reunión de trabajo: X."
    tr.iniciar()
    tr.encolar("yo", np.zeros(SR * 5, np.float32), 0.0)
    fin = time.time() + 5
    while not tr.vacio() and time.time() < fin:
        time.sleep(0.01)
    time.sleep(0.05)
    tr.detener()
    assert modelo.llamadas[0]["language"] == "es" and emitidos == ["Hola a todos."]


def test_la_copia_del_prompt_catalan_tambien_se_descarta():
    _, _, emitidos = correr_tr([("reunion", 5.0), ("reunion", 5.0)], ["Reunió de treball: Seguimiento.", "El PMS falla."], idioma="ca")
    assert [x for _, x in emitidos] == ["El PMS falla."]


def test_el_prompt_en_espanol_es_el_de_siempre():
    assert prompt_tema("Seguimiento de alcance", "es") == "Reunión de trabajo: Seguimiento de alcance."
    assert prompt_tema("Seguimiento de alcance") == "Reunión de trabajo: Seguimiento de alcance."
    assert prompt_tema("Seguiment d'abast", "ca") == "Reunió de treball: Seguiment d'abast."
    assert TR.construir_prompt("Base.", ["PMS"]) == "Base. Términos: PMS."                  # etiqueta por defecto, como antes
    assert TR.construir_prompt("Base.", ["PMS"], etiqueta=TR.ETIQUETA_VOCABULARIO_CA) == "Base. Termes: PMS."


# ================================================================ config
def test_la_configuracion_guardada_con_es_sigue_valiendo(tmp_path):
    ruta = tmp_path / "config.json"
    ruta.write_text(json.dumps({"idioma": "es", "whisper_modelo": "small"}), encoding="utf-8")
    c = Config(ruta)
    assert c["idioma"] == "es" and c["idiomas_auto"] == ["es", "ca", "en"]
    c.actualizar({"idioma": "ca"}, guardar=False)
    assert c["idioma"] == "ca"
    c.actualizar({"idioma": " AUTO "}, guardar=False)
    assert c["idioma"] == "auto"
    for malo in ("fr", "", 3, None, ["es"]):
        c.actualizar({"idioma": malo}, guardar=False)
        assert c["idioma"] == "auto"                      # un valor ajeno se descarta y se conserva el anterior


def test_idiomas_auto_solo_admite_es_ca_y_en(tmp_path):
    c = Config(tmp_path / "c.json")
    assert c["idioma"] == "auto" and c["idiomas_auto"] == ["es", "ca", "en"]
    c.actualizar({"idiomas_auto": ["ca", "es", "ca", "en", "fr"]}, guardar=False)
    assert c["idiomas_auto"] == ["ca", "es", "en"]
    c.actualizar({"idiomas_auto": ["ca", "es"]}, guardar=False)
    assert c["idiomas_auto"] == ["ca", "es"]
    c.actualizar({"idiomas_auto": ["xx", "fr"]}, guardar=False)
    assert c["idiomas_auto"] == ["ca", "es"]              # sin ninguno válido, se conserva el anterior
    c.actualizar({"idiomas_auto": "es"}, guardar=False)
    assert c["idiomas_auto"] == ["ca", "es"]


def test_validar_idioma():
    assert [validar_idioma(v) for v in ("auto", "es", "ca", " Ca ")] == ["auto", "es", "ca", "ca"]
    assert IDIOMAS_REUNION == ("auto", "es", "ca", "en")
    assert validar_idioma(" EN ") == "en"
    for malo in ("fr", "", None, 5):
        with pytest.raises(ValueError):
            validar_idioma(malo)
    assert validar_idioma("xx", defecto="auto") == "auto"


# ================================================================ gestor, servidor y dictado: el modelo recibe el idioma elegido
class CapturaNula:
    errores: dict = {}

    def __init__(self, *a, **k):
        pass

    def iniciar(self):
        pass

    def detener(self):
        pass


def gestor_con_audio(tmp_path, monkeypatch, config=None):
    """Gestor SIN simulación (usa `_iniciar_audio`) con un Whisper falso y sin micro. -> (gestor, modelo, cfg)."""
    modelo = ModeloIdioma([])
    modelo.respuestas = ["Bon dia."] * 20

    class TrFalso(Transcriptor):
        def cargar_modelo(self):
            return modelo
    monkeypatch.setattr("apuntes.transcripcion.Transcriptor", TrFalso)
    monkeypatch.setattr("apuntes.audio.Captura", CapturaNula)
    g0, llm, g, cfg, raiz, eventos = montar(tmp_path)
    if config:
        cfg.actualizar(config, guardar=False)
    gestor = Gestor(cfg, g, g0.consumo, llm, eventos.append, simulacion=None, velocidad=1)
    return gestor, modelo, cfg


def esperar_modelo(gestor, n=1):
    fin = time.time() + 5
    while time.time() < fin and not (gestor.transcriptor and gestor.transcriptor.estado == "listo"):
        time.sleep(0.01)
    return gestor.transcriptor


def transcribir_y_ver(gestor, modelo, seg=5.0, n=1):
    tr = esperar_modelo(gestor)
    for i in range(n):
        tr.encolar("yo", np.zeros(int(SR * seg), np.float32), float(i))
    fin = time.time() + 5
    while not tr.vacio() and time.time() < fin:
        time.sleep(0.01)
    time.sleep(0.05)


@pytest.mark.parametrize("idioma,lenguas,prompt", [
    ("es", ["es"], "Reunión de trabajo: Tema X."),
    ("ca", ["ca"], "Reunió de treball: Tema X."),
    ("auto", ["ca"], "Reunió de treball: Tema X."),
])
def test_el_gestor_pasa_el_idioma_elegido_al_modelo_en_los_tres_modos(tmp_path, monkeypatch, idioma, lenguas, prompt):
    gestor, modelo, _ = gestor_con_audio(tmp_path, monkeypatch)
    modelo.deteccion = [probs(ca=0.95, es=0.02)]
    correr(iniciar_y_esperar(gestor, PROYECTO, "Tema X", 5, None, [], "", idioma))
    assert gestor.idioma == idioma and gestor.transcriptor.idioma == idioma
    transcribir_y_ver(gestor, modelo)
    gestor.transcriptor.detener()
    assert [c["language"] for c in modelo.llamadas] == lenguas
    assert modelo.llamadas[0]["initial_prompt"].startswith(prompt)
    assert len(modelo.detecciones) == (1 if idioma == "auto" else 0)


def test_sin_idioma_en_la_peticion_el_gestor_usa_el_de_la_configuracion(tmp_path, monkeypatch):
    gestor, modelo, _ = gestor_con_audio(tmp_path, monkeypatch, {"idioma": "es"})      # un «es» guardado de versiones anteriores
    correr(iniciar_y_esperar(gestor, PROYECTO, "Tema X", 5, None, []))
    transcribir_y_ver(gestor, modelo)
    gestor.transcriptor.detener()
    assert gestor.idioma == "es" and modelo.llamadas[0]["language"] == "es" and modelo.detecciones == []


def test_un_idioma_no_valido_se_rechaza_antes_de_tocar_nada(tmp_path):
    gestor, llm, *_ = montar(tmp_path)
    with pytest.raises(ValueError, match="idioma"):
        correr(gestor.iniciar(PROYECTO, "Tema", 5, None, [], "", "fr"))
    assert gestor.estado == "inactivo" and gestor.sesion is None


def cliente_idioma(tmp_path, monkeypatch):
    gestor, modelo, cfg = gestor_con_audio(tmp_path, monkeypatch)
    dif = Difusor()
    gestor._emitir = dif.emitir
    app = crear_app(gestor, dif, cfg, gestor.g, TOKEN, 8127)
    return TestClient(app, base_url="http://127.0.0.1:8127", headers={"X-Token": TOKEN}), gestor, modelo


def test_el_servidor_valida_el_idioma_y_lo_pasa(tmp_path, monkeypatch):
    cli, gestor, modelo = cliente_idioma(tmp_path, monkeypatch)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "T", "cadencia": "manual", "idioma": "fr"})
        assert r.status_code == 400 and "idioma" in r.json()["detail"].lower()
        assert gestor.estado == "inactivo"
        r = cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "T", "cadencia": "manual", "idioma": "ca"})
        assert r.status_code == 200 and gestor.idioma == "ca" and gestor.transcriptor.idioma == "ca"
        gestor.transcriptor.detener()
        for t in gestor._tareas:
            t.cancel()


def test_el_dictado_usa_el_idioma_elegido_y_su_prompt():
    cfg = Config(Path("no-existe.json"))
    piezas = {}

    def cap(reloj, on_enunciado, on_nivel):
        return CapturaNula()

    d = Dictado(cfg, lambda e: None, None, cap, None)
    d._fabrica_transcriptor = lambda on_texto: piezas.setdefault("tr", d._transcriptor_real(on_texto))
    d.iniciar("ca")
    tr = piezas["tr"]
    assert d.idioma == "ca" and tr.idioma == "ca" and tr.prompt_ca.startswith("Dictat de notes")
    assert tr.prompt_para("yo").startswith("Dictat de notes")
    d.cancelar()
    d2 = Dictado(cfg, lambda e: None, None, cap, None)
    d2._fabrica_transcriptor = lambda on_texto: piezas.setdefault("tr2", d2._transcriptor_real(on_texto))
    d2.iniciar()                                          # sin valor: el de la configuración (auto)
    assert d2.idioma == "auto" and piezas["tr2"].idioma == "auto"
    d2.cancelar()
    d3 = Dictado(cfg, lambda e: None, None, cap, None)
    d3._fabrica_transcriptor = lambda on_texto: piezas.setdefault("tr3", d3._transcriptor_real(on_texto))
    d3.iniciar("en")
    assert piezas["tr3"].idioma == "en" and piezas["tr3"].prompt_para("yo").startswith("Dictation of notes")
    d3.cancelar()
    with pytest.raises(ValueError, match="idioma"):
        Dictado(cfg, lambda e: None, None, cap, None).iniciar("fr")


def test_el_endpoint_de_dictado_acepta_el_idioma(tmp_path, monkeypatch):
    cli, gestor, modelo = cliente_idioma(tmp_path, monkeypatch)
    vistos = {}

    class Tr:
        def __init__(self, on_texto):
            vistos["tr"] = self
            self.estado = "listo"

        def iniciar(self): pass
        def detener(self): pass
        def vacio(self): return True
        def encolar(self, *a): pass
    gestor.dictado = Dictado(gestor.cfg, lambda e: None, None, lambda *a: CapturaNula(), Tr)
    with cli:
        assert cli.post("/api/contexto-reunion/dictado/iniciar", json={"idioma": "es"}).json()["estado"] == "dictando"
        assert gestor.dictado.idioma == "es"
        cli.post("/api/contexto-reunion/dictado/parar")
        assert cli.post("/api/contexto-reunion/dictado/iniciar").json()["estado"] == "dictando"      # sin cuerpo: sigue funcionando
        cli.post("/api/contexto-reunion/dictado/parar")
        r = cli.post("/api/contexto-reunion/dictado/iniciar", json={"idioma": "xx"})
        assert r.status_code == 400


# ================================================================ filtros de alucinaciones
@pytest.mark.parametrize("texto", [
    "Subtítols realitzats per la comunitat d'Amara.org", "Gràcies per veure el vídeo", "Gràcies per mirar", "Gràcies.", "  Gràcies  ",
    "Subscriu-te al canal", "No t'oblidis de subscriure't al canal", "Subscriviu-vos al canal",
])
def test_se_descartan_los_creditos_y_formulas_de_video_en_catalan(texto):
    assert filtrar_texto(texto) == ""


@pytest.mark.parametrize("texto", [
    "Gràcies per l'ajuda amb el pla de proves.", "Gràcies, Marta, però això no entra en aquesta fase.", "Cal subscriure el contracte abans de divendres.",
    "Els subtítols del vídeo formatiu els revisem demà.", "D'acord, ho deixem així.", "Vale, d'acord.",
])
def test_se_conservan_las_frases_validas_en_catalan(texto):
    assert filtrar_texto(texto) == texto


@pytest.mark.parametrize("texto", ["Gracias.", "Suscríbete al canal", "Gracias por ver el vídeo", "Subtítulos realizados por la comunidad de Amara.org"])
def test_los_filtros_en_espanol_siguen_igual(texto):
    assert filtrar_texto(texto) == ""
    assert filtrar_texto("Gracias por el esfuerzo con la propuesta.") != ""


# ================================================================ Monitor: español idéntico, catalán reconocido
def test_las_senales_y_definiciones_en_espanol_no_cambian():
    """233 frases (reuniones ficticias de pruebas\\ + casos límite) con el resultado capturado ANTES de añadir el catalán."""
    base = json.loads((FIXTURES / "senales_es.json").read_text(encoding="utf-8"))
    assert len(base) > 200
    for o in base:
        t = o["texto"]
        ahora = {"texto": t, "senal": DP.detectar_senal(t), "tipos": sorted(MO.detectar(t).keys()),
                 "defs": [[d["termino"], d["definicion"]] for d in MO.extraer_definiciones(t)]}
        assert ahora == o, t


@pytest.mark.parametrize("texto,senal,tipos", [
    ("Hem decidit deixar-ho per a la segona fase.", "decisión", {"decision"}),
    ("Això queda fora de l'abast d'aquesta fase.", "decisión", {"alcance"}),
    ("La prioritat és tancar el pla.", "prioridad", {"prioridad"}),
    ("M'encarrego jo, per al divendres.", "pendiente", {"fecha", "responsable"}),
    ("El termini és el 12 d'abril.", "fecha", {"fecha"}),
    ("Tenim un risc de bloqueig amb el proveïdor.", "riesgo", {"riesgo"}),
    ("Són 20 dies i 15 persones.", "cifra", {"cifra"}),
    ("Algú sap si el portal està en producció?", "pregunta", {"pregunta", "sistema"}),
    ("Sempre que hi hagi més places, només si ho aprova Revenue.", None, {"regla"}),
    ("La taula de reserves té un camp nou.", None, {"dato"}),
    ("L'entorn de desenvolupament no té dades.", None, {"sistema"}),
    ("Abans era diferent, al document posa una altra cosa.", None, {"contraste"}),
])
def test_el_monitor_reconoce_las_senales_en_catalan(texto, senal, tipos):
    assert DP.detectar_senal(texto) == senal
    assert set(MO.detectar(texto)) == tipos


@pytest.mark.parametrize("texto,previo,esperado", [
    ("Definim Cupo com el màxim d'habitacions per hotel.", "", ("Cupo", "el màxim d'habitacions per hotel")),
    ("Entenem per Cupo el màxim d'habitacions d'un hotel.", "", ("Cupo", "el màxim d'habitacions d'un hotel")),
    ("Cupo vol dir el màxim d'habitacions.", "", ("Cupo", "el màxim d'habitacions")),
    ("A això li diem Pack Grup.", "El màxim d'habitacions per hotel.", ("Pack Grup", "El màxim d'habitacions per hotel")),
])
def test_definiciones_locales_en_catalan(texto, previo, esperado):
    d = MO.extraer_definiciones(texto, previo)
    assert [(x["termino"], x["definicion"]) for x in d] == [esperado]


def test_vol_dir_en_minusculas_no_es_una_definicion_como_significa_en_espanol():
    # el habla corriente («això vol dir que…», «a un pas vol dir, mira…») daría falsos positivos
    assert MO.extraer_definiciones("a un pas vol dir que passem a la fase dos") == []
