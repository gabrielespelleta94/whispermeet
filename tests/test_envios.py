"""Registro de envíos (ola 4): cada llamada a `claude -p` deja fecha, sesión, agente/tarea, modelo, caracteres, tokens y un extracto corto, solo en local."""
import asyncio
import json
from types import SimpleNamespace

import pytest

from apuntes.analisis import ErrorAnalisis, Respuesta, Uso
from apuntes.envios import EXTRACTO_MAX, ModeloVigilado, RegistroEnvios, extracto, marcar_tarea
from apuntes.rutas import Guardian
from ola4_utils import Falso, cliente, esperar, esperar_async, montar


def _lineas_registro(g):
    return [json.loads(x) for x in (g.leer_datos("envios.jsonl") or "").splitlines()]


class GestorMinimo:
    """Lo único que la capa de modelo necesita del Gestor."""

    def __init__(self, g, local=False, sesion=None):
        self.envios = RegistroEnvios(g)
        self.sesion = sesion
        self.local = local
        self.eventos = []

    def modo_local_activo(self):
        return self.local

    def emitir(self, tipo, **d):
        self.eventos.append((tipo, d))


class ModeloUso(Falso):
    def completar(self, sistema, usuario, modelo, *a, **k):
        self.llamadas.append((sistema, usuario, modelo))
        if self.error:
            raise self.error
        return Respuesta("{}", [Uso(modelo, 100, 20, 30, 40), Uso("otro", 5, 6)], ms=123)


def test_el_extracto_es_corto_y_no_arrastra_las_marcas_de_datos():
    largo = "<<<DATOS transcripción>>>\n" + "palabra importante " * 100 + "\n<<<FIN>>>"
    e = extracto(largo)
    assert len(e) <= EXTRACTO_MAX == 120
    assert "<<<" not in e and ">>>" not in e and "\n" not in e


def test_cada_llamada_registra_sesion_agente_modelo_chars_y_tokens(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")
    gm = GestorMinimo(g, sesion=SimpleNamespace(id="abc12345"))
    m = ModeloVigilado(ModeloUso(), gm)
    marcar_tarea("final")
    r = m.completar("sistema corto", "U" * 500 + "COLA-QUE-NO-SE-GUARDA", "sonnet", "low", 100, False)
    assert r.texto == "{}"
    [reg] = _lineas_registro(g)
    assert reg["sesion"] == "abc12345" and reg["tarea"] == "final" and reg["agente"] == "Redactor del resumen final" and reg["modelo"] == "sonnet"
    assert reg["chars"] == len("sistema corto") + 521
    assert reg["entrada"] == 100 + 30 + 40 + 5 and reg["salida"] == 26      # entrada con caché; salida de todos los modelos
    assert reg["ok"] is True and reg["bloqueado"] is False and reg["ts"]
    assert len(reg["extracto"]) <= 120 and "COLA-QUE-NO-SE-GUARDA" not in json.dumps(reg)
    assert gm.eventos and gm.eventos[0][0] == "envio" and gm.eventos[0][1]["tarea"] == "final"


def test_un_error_del_modelo_tambien_queda_anotado_y_se_relanza(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")
    modelo = ModeloUso()
    modelo.error = ErrorAnalisis("limite", "tope del plan")
    m = ModeloVigilado(modelo, GestorMinimo(g))
    marcar_tarea("consulta")
    with pytest.raises(ErrorAnalisis) as e:
        m.completar("s", "u", "haiku")
    assert e.value.tipo == "limite"
    [reg] = _lineas_registro(g)
    assert reg["ok"] is False and reg["error"] == "limite" and reg["agente"] == "Consultas" and reg["entrada"] == 0


def test_la_tarea_no_se_hereda_entre_llamadas(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")
    m = ModeloVigilado(ModeloUso(), GestorMinimo(g))
    marcar_tarea("digest")
    m.completar("s", "u", "haiku")
    m.completar("s", "u", "haiku")   # sin pasar por Analista._llamar
    regs = _lineas_registro(g)
    assert [r["tarea"] for r in regs] == ["digest", "otra"]


def test_sin_carpeta_de_datos_no_se_rompe_nada(tmp_path):
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c")        # sin `datos`
    m = ModeloVigilado(ModeloUso(), GestorMinimo(g))
    marcar_tarea("digest")
    assert m.completar("s", "u", "haiku").texto == "{}"
    assert not (tmp_path / "datos").exists()


def test_una_sesion_real_registra_todas_sus_llamadas_y_el_endpoint_las_da(tmp_path):
    gestor, llm, _, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        r = cli.post("/api/sesion/iniciar", json={"proyecto": "Proyecto Ficticio Alfa", "tema": "Seguimiento", "cadencia": 5})
        assert r.status_code == 200, r.text
        sid = r.json()["sesion"]["id"]
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 40)
        assert cli.post("/api/sesion/analizar").json()["ok"]
        data = cli.get("/api/envios", params={"sesion": sid}).json()
        tareas = {e["tarea"] for e in data["envios"]}
        assert {"digest", "periodico"} <= tareas
        assert all(e["sesion"] == sid and e["modelo"] in ("haiku", "sonnet") and e["chars"] > 0 and len(e["extracto"]) <= 120 for e in data["envios"])
        per = [e for e in data["envios"] if e["tarea"] == "periodico"][0]
        assert per["entrada"] == 100 and per["salida"] == 20 and per["agente"] == "Analista"
        assert data["resumen"]["enviadas"] == len(llm.llamadas) and data["resumen"]["entrada"] == 100 * len(llm.llamadas)
        assert data["resumen"]["por_agente"]["Analista"]["llamadas"] == 1
        # el resumen por sesión (sin filtrar) y otra sesión que no existe
        todas = cli.get("/api/envios").json()
        assert [s["sesion"] for s in todas["sesiones"]] == [sid]
        assert cli.get("/api/envios", params={"sesion": "nada"}).json()["envios"] == []
        assert cli.get("/api/envios/resumen").json()["sesiones"][0]["llamadas"] == len(llm.llamadas)
        cli.post("/api/sesion/terminar")
        esperar(lambda: cli.get("/api/sesion").json()["revision"]["estado"] == "lista")
    final = [e for e in _lineas_registro(g) if e["tarea"] == "final"]
    assert final and final[0]["agente"] == "Redactor del resumen final"


def test_el_registro_no_guarda_la_transcripcion_entera(tmp_path):
    gestor, llm, eventos, g, cfg = montar(tmp_path)
    cli = cliente(gestor, cfg, g)
    with cli:
        cli.post("/api/sesion/iniciar", json={"proyecto": "Proyecto Ficticio Alfa", "tema": "Seguimiento", "cadencia": 5})
        esperar(lambda: len(cli.get("/api/sesion").json()["segmentos"]) >= 40)
        cli.post("/api/sesion/analizar")
    crudo = g.leer_datos("envios.jsonl")
    usuario_mayor = max(len(u) for _, u, _ in llm.llamadas)
    assert usuario_mayor > 500 and len(crudo) < usuario_mayor * 2   # las líneas son metadatos + 120 caracteres, no los prompts
    assert all(len(json.loads(x)["extracto"]) <= 120 for x in crudo.splitlines())
    assert any(e.get("tipo") == "envio" for e in eventos)


# ---------------------------------------------------------------- transcripción en la nube
def test_resumir_separa_transcripcion_nube():
    llamada = {"agente": "Redactor del resumen final", "tarea": "final", "chars": 100, "entrada": 30, "salida": 10, "ok": True}
    lote = {"tarea": "transcripcion_nube", "tipo": "transcripcion_nube", "agente": "Transcripción en la nube", "audio_s": 96.4, "trozos": 13, "fallos": 1,
            "chars": 1820, "bloqueado": False, "ok": True, "entrada": 0, "salida": 0}
    prueba = {**lote, "tarea": "nube_prueba", "audio_s": 1.0, "trozos": 1, "chars": 0}
    bloqueado = {**lote, "bloqueado": True, "ok": False, "error": "local", "audio_s": 0, "trozos": 0, "chars": 0}
    r = RegistroEnvios.resumir([llamada, lote, lote, prueba, bloqueado])
    assert (r["llamadas"], r["enviadas"], r["bloqueadas"], r["errores"], r["chars"], r["entrada"], r["salida"]) == (1, 1, 0, 0, 100, 30, 10)
    assert list(r["por_agente"]) == ["Redactor del resumen final"]   # la nube no es un agente
    assert r["nube"] == {"lotes": 2, "trozos": 26, "audio_s": 192.8, "fallos": 2, "bloqueadas": 1}
    assert RegistroEnvios.resumir([])["nube"] == {"lotes": 0, "trozos": 0, "audio_s": 0.0, "fallos": 0, "bloqueadas": 0}


def test_el_evento_envio_de_la_nube_no_choca_con_el_nombre_del_evento(tmp_path):
    """`emitir(tipo, **datos)`: un registro que lleve `tipo` (el de la nube) daría «multiple values for argument 'tipo'». El registro guardado lo conserva; el evento, no."""
    g = Guardian(tmp_path / "r", tmp_path / "b", tmp_path / "c", datos=tmp_path / "datos")
    gm = GestorMinimo(g, sesion=SimpleNamespace(id="abc12345"))
    m = ModeloVigilado(ModeloUso(), gm)
    reg = {"ts": "2026-11-11T10:02:00", "sesion": "", "agente": "Transcripción en la nube", "tarea": "nube_prueba", "tipo": "transcripcion_nube", "modelo": "gpt-transcribe",
           "host": "api.openai.com", "audio_s": 1.0, "trozos": 1, "fallos": 0, "chars": 0, "bloqueado": False, "ok": True, "entrada": 0, "salida": 0, "extracto": ""}
    m._anotar(reg)
    [(tipo, d)] = gm.eventos
    assert tipo == "envio" and "tipo" not in d and d["tarea"] == "nube_prueba" and d["host"] == "api.openai.com"
    [guardado] = _lineas_registro(g)
    assert guardado["tipo"] == "transcripcion_nube" and guardado["tarea"] == "nube_prueba"
    assert reg["tipo"] == "transcripcion_nube"   # y el registro original no se toca
