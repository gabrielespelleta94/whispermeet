"""Confianza de Whisper y corrección al glosario (ola 4): palabras con probabilidad, dudosas, corrección en directo y propagación a lo derivado."""
import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from apuntes import correccion as CORR
from apuntes.glosario import Glosario, limpiar_termino
from apuntes.sesion import Sesion
from apuntes.transcripcion import Transcriptor, alinear_palabras
from ola4_utils import PROYECTO, cliente, esperar, esperar_async, montar


def _palabra(w, p):
    return SimpleNamespace(word=" " + w, probability=p, start=0.0, end=0.1)


def _seg(texto, probs, nsp=0.0, lp=-0.3):
    return SimpleNamespace(text=" " + texto, no_speech_prob=nsp, avg_logprob=lp, words=[_palabra(w, p) for w, p in zip(texto.split(), probs)])


class ModeloPalabras:
    def __init__(self, segs):
        self.segs, self.llamadas = segs, []

    def transcribe(self, audio, **kw):
        self.llamadas.append(kw)
        return iter(self.segs), None


class TranscriptorDoble(Transcriptor):
    def __init__(self, config, on_texto, modelo):
        super().__init__(config, on_texto)
        self._m = modelo

    def cargar_modelo(self):
        return self._m


def _correr(segs, cfg_extra=None, entrega=True, vocab=(), curados=()):
    recibidos, modelo = [], ModeloPalabras(segs)

    def on_texto(f, t, x, palabras=None):
        recibidos.append((f, x, palabras))
    tr = TranscriptorDoble({"idioma": "es", "whisper_beam": 5, "whisper_modelo": "x", "whisper_hilos": 1, **(cfg_extra or {})}, on_texto, modelo)
    tr.entrega_palabras = entrega
    tr.vocabulario, tr.vocabulario_curado = list(vocab), list(curados)
    tr.iniciar()
    try:
        tr.encolar("yo", np.zeros(1600, dtype=np.float32), 0.0)
        fin = time.time() + 5
        while not tr.vacio() and time.time() < fin:
            time.sleep(0.01)
        time.sleep(0.1)
    finally:
        tr.detener()
    return recibidos, modelo


# ------------------------------------------------------------------ alinear (función pura)
def test_alinear_palabras_marca_dudosas_por_debajo_del_umbral():
    r = alinear_palabras([("Hola", 0.99), ("equipo", 0.49), ("PMS", 0.5)], "Hola equipo PMS", 0.5)
    assert r == [{"w": "Hola", "p": 0.99, "d": False}, {"w": "equipo", "p": 0.49, "d": True}, {"w": "PMS", "p": 0.5, "d": False}]


def test_si_no_casan_las_palabras_no_se_adivina_nada():
    assert alinear_palabras([("a", 1.0)], "a b", 0.5) == []
    assert alinear_palabras([], "a b", 0.5) == [] and alinear_palabras(None, "", 0.5) == []


def test_el_texto_final_manda_en_las_palabras_y_la_probabilidad_se_acota():
    r = alinear_palabras([("sap", 1.7), ("hoy", -0.2)], "SAP hoy", 0.5)
    assert [x["w"] for x in r] == ["SAP", "hoy"] and r[0]["p"] == 1.0 and r[1]["p"] == 0.0 and r[1]["d"] is True


# ------------------------------------------------------------------ el transcriptor
def test_el_transcriptor_pide_word_timestamps_y_entrega_las_palabras():
    rec, modelo = _correr([_seg("Revisamos la integración con sap", [0.98, 0.9, 0.3, 0.95, 0.8, 0.2])],
                          vocab=["SAP"], curados=["SAP"], cfg_extra={"palabra_dudosa_umbral": 0.5})
    assert modelo.llamadas[0]["word_timestamps"] is True
    [(fuente, texto, palabras)] = rec
    assert texto == "Revisamos la integración con SAP"            # el glosario ya corrigió «sap» y las palabras llevan el texto final
    assert [p["w"] for p in palabras] == texto.split() and palabras[-1] == {"w": "SAP", "p": 0.8, "d": False}
    assert [p["w"] for p in palabras if p["d"]] == ["integración"] and palabras[2]["p"] == 0.3
    assert sum(1 for p in palabras if p["d"]) == 1


def test_con_whisper_palabras_desactivado_no_se_pide_nada_ni_se_entrega():
    rec, modelo = _correr([_seg("Hola equipo", [0.9, 0.9])], cfg_extra={"whisper_palabras": False})
    assert "word_timestamps" not in modelo.llamadas[0] and rec == [("yo", "Hola equipo", None)]


def test_sin_entrega_de_palabras_el_dictado_sigue_como_siempre():
    emitidos = []
    modelo = ModeloPalabras([_seg("Hola equipo", [0.9, 0.9])])
    tr = TranscriptorDoble({"idioma": "es", "whisper_beam": 5, "whisper_modelo": "x", "whisper_hilos": 1}, lambda f, t, x: emitidos.append(x), modelo)
    tr.iniciar()
    try:
        tr.encolar("yo", np.zeros(1600, dtype=np.float32), 0.0)
        time.sleep(0.5)
    finally:
        tr.detener()
    assert emitidos == ["Hola equipo"] and "word_timestamps" not in modelo.llamadas[0]      # on_texto de 3 argumentos: sin romper


def test_los_segmentos_descartados_no_aportan_palabras():
    rec, _ = _correr([_seg("Ruido de fondo", [0.1, 0.1, 0.1], nsp=0.9), _seg("Hola equipo", [0.9, 0.4])])
    [(_, texto, palabras)] = rec
    assert texto == "Hola equipo" and [p["w"] for p in palabras] == ["Hola", "equipo"] and palabras[1]["d"] is True


def test_si_el_filtro_cambia_el_numero_de_palabras_se_entrega_sin_palabras():
    rec, _ = _correr([_seg("no no no no no no vale", [0.9] * 7)])      # el filtro de bucles colapsa la repetición
    [(_, texto, palabras)] = rec
    assert texto and palabras is None


# ------------------------------------------------------------------ la sesión
def _sesion(tmp_path):
    return Sesion("P", "Tema", 5, tmp_path / "s.md")


def test_el_segmento_publico_lleva_palabras_y_dudosas_solo_mientras_valen(tmp_path):
    s = _sesion(tmp_path)
    pal = [{"w": "Hola", "p": 0.9, "d": False}, {"w": "mundo", "p": 0.2, "d": True}]
    seg = s.agregar_segmento(3.0, "reunion", "Hola mundo", pal)
    pub = seg.publico()
    assert pub["palabras"] == pal and pub["dudosas"] == 1 and "corregido" not in pub
    assert "palabras" not in s.agregar_segmento(4.0, "yo", "Otra cosa").publico()          # sin word_timestamps: igual que siempre
    seg.texto = "Hola"                                                                      # p. ej. el filtro de eco recortó el texto
    assert "palabras" not in seg.publico()


# ------------------------------------------------------------------ corregir y propagar
def test_sustituciones_solo_cambios_de_palabras():
    assert CORR.sustituciones("revisamos el sap hoy", "revisamos el SAP hoy") == [("sap", "SAP")]
    assert CORR.sustituciones("la nordia reserva", "la Nórdia reserva") == [("nordia", "Nórdia")]
    assert CORR.sustituciones("una dos tres", "una dos tres cuatro") == []                  # una inserción no es una sustitución
    assert CORR.sustituciones("igual", "igual") == []


def test_corregir_un_segmento_lo_actualiza_y_propaga_a_lo_derivado(tmp_path):
    s = _sesion(tmp_path)
    s.filtrar_eco = False
    seg = s.agregar_segmento(5.0, "reunion", "Pasamos los datos a la nordia hoy", [{"w": "x", "p": 0.1, "d": True}])
    s.tarjetas = [{"id": "t1-abcd", "categoria": "pendiente", "texto": "Pasar datos a la nordia", "referencia": "contexto: nordia", "linea": "Pasamos los datos a la nordia hoy",
                   "nota": "", "responsable": "Ana"}]
    s.resumen_acumulado = "Se habló de la nordia."
    s.resumen_completo = "[00:05–00:10] Se habló de la nordia y de otra cosa."
    s.definiciones = [{"termino": "Nordia", "definicion": "la nordia del cliente", "origen": "local"}]
    equipo = SimpleNamespace(definiciones=SimpleNamespace(lista=s.definiciones, publico=lambda: [dict(d) for d in s.definiciones]),
                             monitor=SimpleNamespace(feed=[{"id": "m1", "texto": "señal: pendiente · «la nordia hoy»"}]))
    r = CORR.corregir_segmento(s, equipo, seg.id, "Pasamos los datos a la Nórdia hoy")
    assert r["segmento"]["texto"] == "Pasamos los datos a la Nórdia hoy" and r["segmento"]["corregido"] is True and "palabras" not in r["segmento"]
    assert r["sustituciones"] == [["nordia", "Nórdia"]]
    assert r["propagado"]["tarjetas"] == 1 and r["propagado"]["resumen"] == 2 and r["propagado"]["feed"] == 1
    t = s.tarjetas[0]
    assert t["texto"] == "Pasar datos a la Nórdia" and t["referencia"] == "contexto: Nórdia" and "Nórdia" in t["linea"]
    assert s.resumen_acumulado == "Se habló de la Nórdia." and "Nórdia" in s.resumen_completo
    assert equipo.monitor.feed[0]["texto"].endswith("«la Nórdia hoy»")
    assert "Nórdia" in s.render() and "nordia" not in s.render().split("## Transcripción")[1]


def test_la_propagacion_es_exacta_y_no_toca_otras_palabras_ni_cambios_cortos(tmp_path):
    s = _sesion(tmp_path)
    s.filtrar_eco = False
    seg = s.agregar_segmento(1.0, "yo", "el sap y el sapo")
    s.tarjetas = [{"id": "t1-aaaa", "categoria": "idea", "texto": "El sapo del sap", "referencia": "", "linea": "", "nota": ""}]
    CORR.corregir_segmento(s, None, seg.id, "el SAP y el sapo")
    assert s.tarjetas[0]["texto"] == "El sapo del SAP"                                       # «sapo» intacto: palabras completas
    seg2 = s.agregar_segmento(2.0, "yo", "ir a la caja")
    s.tarjetas.append({"id": "t2-bbbb", "categoria": "idea", "texto": "ir a la caja", "referencia": "", "linea": "", "nota": ""})
    r = CORR.corregir_segmento(s, None, seg2.id, "ir a la cava")
    assert r["propagado"]["tarjetas"] == 1 and s.tarjetas[1]["texto"] == "ir a la cava"
    seg3 = s.agregar_segmento(3.0, "yo", "a b")
    s.tarjetas.append({"id": "t3-cccc", "categoria": "idea", "texto": "a b", "referencia": "", "linea": "", "nota": ""})
    r = CORR.corregir_segmento(s, None, seg3.id, "x b")
    assert r["propagado"]["tarjetas"] == 0 and s.tarjetas[2]["texto"] == "a b"               # «a»: menos de 3 caracteres, no se propaga


def test_corregir_valida(tmp_path):
    s = _sesion(tmp_path)
    s.agregar_segmento(1.0, "yo", "hola")
    with pytest.raises(ValueError):
        CORR.corregir_segmento(s, None, 99, "x")
    with pytest.raises(ValueError):
        CORR.corregir_segmento(s, None, 1, "   ")


# ------------------------------------------------------------------ glosario
def test_el_glosario_global_y_el_del_proyecto(tmp_path):
    gestor, _, _, g, cfg = montar(tmp_path)
    gl = Glosario(g, cfg)
    assert gl.anadir("Nórdia")["ambito"] == "global" and cfg["vocabulario_transcripcion"] == ["Nórdia"]
    assert gl.anadir("nórdia")["nuevo"] is False and len(cfg["vocabulario_transcripcion"]) == 1       # sin repetidos
    r = gl.anadir("Cupo Flex", PROYECTO)
    assert r["ambito"] == "proyecto" and r["nuevo"] is True and gl.de_proyecto(PROYECTO) == ["Cupo Flex"] and gl.de_proyecto(PROYECTO.upper()) == ["Cupo Flex"]
    assert gl.de_proyecto("Otro") == [] and gl.de_proyecto(None) == []
    with pytest.raises(ValueError):
        gl.anadir("x")
    with pytest.raises(ValueError):
        gl.anadir("y" * 41)
    assert (tmp_path / "datos-app" / "glosario.json").is_file()
    sin_datos = Glosario(montar(tmp_path / "otro", datos=False)[3], cfg)
    with pytest.raises(ValueError):
        sin_datos.anadir("Algo", PROYECTO)


def test_el_vocabulario_de_la_reunion_incluye_el_glosario_del_proyecto(tmp_path):
    gestor, _, _, g, cfg = montar(tmp_path)
    cfg.actualizar({"vocabulario_transcripcion": ["PMS"]}, guardar=False)
    gestor.glosario.anadir("Cupo Flex", PROYECTO)

    async def go():
        await gestor.iniciar(PROYECTO, "T", 5)
        gestor.transcriptor = SimpleNamespace(vocabulario=[], vocabulario_curado=[])
        gestor._vocabulario_contexto = ["Reserva", "pms"]
        gestor._actualizar_vocabulario()
        assert gestor.transcriptor.vocabulario == ["PMS", "Cupo Flex", "Reserva"]
        assert gestor.transcriptor.vocabulario_curado == ["PMS", "Cupo Flex"]                  # el del usuario se corrige siempre
        gestor.transcriptor = None
        await gestor.terminar()
        await esperar_async(lambda: gestor.revision["estado"] in ("lista", "error"))
        await gestor.cerrar_revision()

    asyncio.run(go())


# ------------------------------------------------------------------ endpoints
def test_endpoints_glosario_y_correccion_en_directo(tmp_path):
    gestor, llm, eventos, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        assert cli.post("/api/sesion/segmento/1/corregir", json={"texto": "x"}).status_code == 400          # sin reunión
        cli.post("/api/sesion/iniciar", json={"proyecto": PROYECTO, "tema": "Seguimiento", "cadencia": "manual"})
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 5)
        gestor.sesion.agregar_segmento(900.0, "reunion", "Pasamos los datos a la nordia hoy")
        sid = gestor.sesion.segmentos[-1].id
        r = cli.post(f"/api/sesion/segmento/{sid}/corregir", json={"texto": "Pasamos los datos a la Nórdia hoy", "glosario": "proyecto"})
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["segmento"]["texto"].endswith("Nórdia hoy") and d["sustituciones"] == [["nordia", "Nórdia"]]
        assert d["glosario"][0]["termino"] == "Nórdia" and d["glosario"][0]["ambito"] == "proyecto"
        assert gestor.glosario.de_proyecto(PROYECTO) == ["Nórdia"]
        assert any(e.get("tipo") == "segmento_corregido" and e["segmento"]["id"] == sid for e in eventos)
        assert "Nórdia hoy" in gestor.sesion.ruta.read_text(encoding="utf-8")                              # el .md ya lleva la corrección
        # glosario global
        assert cli.post("/api/glosario", json={"termino": "Cupo Flex"}).json()["ambito"] == "global"
        assert "Cupo Flex" in cfg["vocabulario_transcripcion"]
        assert cli.post("/api/glosario", json={"termino": "Hotel Uno", "proyecto": PROYECTO}).json()["ambito"] == "proyecto"
        assert cli.post("/api/glosario", json={"termino": "x"}).status_code == 400
        assert cli.post(f"/api/sesion/segmento/{sid}/corregir", json={"texto": "otra", "glosario": "mundo"}).status_code == 400
        assert cli.post("/api/sesion/segmento/9999/corregir", json={"texto": "otra"}).status_code == 400
        # una frase larga corregida no se mete en el glosario (no es un término)
        r = cli.post(f"/api/sesion/segmento/{sid}/corregir", json={"texto": "Una frase completamente distinta de la anterior sin parecido", "glosario": "global"})
        assert r.status_code == 200 and r.json()["glosario"] == [] or all(len(x["termino"]) <= 40 for x in r.json()["glosario"])


def test_un_segmento_con_palabras_llega_al_snapshot_y_al_evento(tmp_path):
    gestor, _, eventos, g, cfg = montar(tmp_path, simulacion=[])

    async def go():
        await gestor.iniciar(PROYECTO, "T", "manual")
        gestor._on_texto("reunion", 1.0, "Hola equipo", palabras=[{"w": "Hola", "p": 0.9, "d": False}, {"w": "equipo", "p": 0.3, "d": True}])
        ev = [e for e in eventos if e.get("tipo") == "segmento"][-1]
        assert ev["palabras"][1] == {"w": "equipo", "p": 0.3, "d": True} and ev["dudosas"] == 1
        snap = gestor.snapshot()
        assert snap["segmentos"][-1]["palabras"][0]["w"] == "Hola"
        await gestor.terminar()
        await esperar_async(lambda: gestor.revision["estado"] in ("lista", "error"))
        await gestor.cerrar_revision()

    asyncio.run(go())
