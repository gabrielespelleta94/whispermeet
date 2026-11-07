"""Flujo del gestor con plan de sesiones y proyecto compartido (modelo falso, sin red ni audio)."""
import asyncio
import json
import shutil
from pathlib import Path

import pytest

from apuntes.analisis import ModeloLLM, Respuesta, Uso
from apuntes.config import Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import CARPETA_CONTEXTO, CARPETA_SESIONES, Guardian
from apuntes.simulador import LineaSim

PRUEBAS = Path(__file__).resolve().parent.parent / "pruebas"
COMPARTIDO = "Proyecto Compartido Beta"


class Falso(ModeloLLM):
    """Devuelve objetivos en el periódico (1ª llamada: 1 cubierto y 2 parcial; 2ª: intenta retroceder el 1)."""

    def __init__(self):
        self.llamadas = []
        self.n_periodicos = 0

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        self.llamadas.append((sistema, usuario, modelo))
        uso = [Uso(modelo, 100, 20)]
        if "compactar el contexto" in sistema:
            return Respuesta(json.dumps({"digest": "[02-alcance.md] Informe semanal en alcance."}), uso)
        if "análisis incremental" in sistema:
            self.n_periodicos += 1
            o = ([{"i": 1, "e": "c", "m": "01:30"}, {"i": 2, "e": "p", "m": "02:35"}] if self.n_periodicos == 1
                 else [{"i": 1, "e": "p", "m": "09:00"}, {"i": 2, "e": "c", "m": "03:15"}])  # el retroceso del 1 sin «d» se ignora
            return Respuesta(json.dumps({"resumen": "Se habló de datos.", "t": [{"k": "decision", "x": "Espacio beta-datos", "m": "01:30"}],
                                         "c": [], "o": o}), uso)
        if "cierre de la reunión" in sistema:
            return Respuesta(json.dumps({"resumen": "Resumen final.", "o": [{"i": 3, "e": "p", "m": "04:45"}], "cambios": [
                {"f": "02-alcance.md", "tipo": "anadir", "sec": "Cambios de alcance",
                 "nuevo": "| 2026-11-03 | Espacio beta-datos | Datos | Reunión |", "motivo": "m", "m": "01:30"}]}), uso)
        raise AssertionError("prompt inesperado")


def lineas(n=60):
    return [LineaSim(i * 5.0, "reunion" if i % 2 else "yo", "palabra " * 12) for i in range(n)]


@pytest.fixture
def montaje(tmp_path):
    raiz = tmp_path / "proyectos"
    shutil.copytree(PRUEBAS / "proyectos", raiz)
    ajena = tmp_path / "OneDrive ajeno" / COMPARTIDO
    shutil.copytree(PRUEBAS / "compartidos" / COMPARTIDO, ajena)
    shutil.copytree(PRUEBAS / "planes-beta", tmp_path / "planes")
    g = Guardian(raiz, tmp_path / "bandeja", tmp_path / "cache", planes=tmp_path / "planes",
                 sesiones_locales=tmp_path / "sesiones",
                 extras=[{"nombre": COMPARTIDO, "ruta": str(ajena), "compartido": True}])
    cfg = Config(tmp_path / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    llm = Falso()
    eventos = []
    gestor = Gestor(cfg, g, Consumo(None), llm, eventos.append, simulacion=lineas(), velocidad=200)
    return gestor, llm, eventos, ajena, tmp_path


async def esperar(cond, t=15):
    for _ in range(int(t / 0.05)):
        if cond():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("tiempo agotado")


async def cerrar(gestor):
    await gestor.terminar()
    await esperar(lambda: gestor.revision["estado"] in ("lista", "error"))


def ejecutar(coro):
    return asyncio.run(coro)


def test_recorrido_completo_plan_objetivos_resumen_y_aceptacion(montaje):
    gestor, llm, eventos, ajena, tmp = montaje
    antes = sorted(p.relative_to(ajena).as_posix() for p in ajena.rglob("*"))
    alcance_antes = (ajena / CARPETA_CONTEXTO / "02-alcance.md").read_text(encoding="utf-8")

    async def go():
        # 1. el proyecto sale en la lista como compartido y con plan; se elige la sesión
        from apuntes import contexto as CX, planes as PL
        lista = {p["nombre"]: p for p in CX.listar_proyectos(gestor.g, "", (), PL.cargar_planes(gestor.g))}
        assert lista[COMPARTIDO]["compartido"] and [s["id"] for s in lista[COMPARTIDO]["plan"]["sesiones"]] == ["S1", "S2", "otra"]
        st = await gestor.iniciar(COMPARTIDO, "", 5, "S1")  # tema vacío -> el de la sesión
        s = gestor.sesion
        assert s.tema == "Revisión del almacén de datos" and st["sesion"]["plan"] == {"id": "S1", "nombre": "Revisión del almacén de datos"}
        assert st["sesion"]["compartido"] is True and st["sesion"]["carpeta"] == "sesiones\\" + s.ruta.parent.name
        assert [(o["n"], o["estado"]) for o in st["objetivos"]] == [(1, "sin_tratar"), (2, "sin_tratar"), (3, "sin_tratar"), (4, "sin_tratar")]
        # la transcripción va a local, nunca a la carpeta compartida
        assert s.ruta.parent == tmp / "sesiones" / "proyecto-compartido-beta"
        await esperar(lambda: len(s.segmentos) >= 30)
        assert s.ruta.is_file() and not (ajena / CARPETA_SESIONES).exists()
        # 2. un análisis actualiza los objetivos citando el minuto
        assert (await gestor.analizar(manual=True))["ok"]
        assert [(o["estado"], o["minuto"]) for o in s.objetivos][:2] == [("cubierto", "01:30"), ("parcial", "02:35")]
        assert gestor.estado_ligero()["objetivos"][0]["estado"] == "cubierto"
        assert any(e["tipo"] == "tarjetas" and e["objetivos"][0]["estado"] == "cubierto" for e in eventos)
        # 3. el cubierto no retrocede sin evidencia; el parcial avanza
        await esperar(lambda: len(s.segmentos) >= 60)
        assert (await gestor.analizar(manual=True))["ok"]
        assert [(o["estado"], o["minuto"]) for o in s.objetivos] == [
            ("cubierto", "01:30"), ("cubierto", "03:15"), ("sin_tratar", ""), ("sin_tratar", "")]
        # 4. resumen final con cumplidos y pendientes (el cierre del modelo marca el 3 como parcial)
        await cerrar(gestor)
        rev = gestor.revision
        assert rev["estado"] == "lista" and rev["compartido"] is True and rev["destino_contexto"] == str(ajena / CARPETA_CONTEXTO)
        r = rev["resumen"]
        assert r.startswith("Resumen final.") and "## Objetivos de la sesión Revisión del almacén de datos" in r
        assert "Cubiertos 2 de 4" in r and "**Cumplidos**" in r and "**Parciales (quedan pendientes)**" in r
        assert "- Inquilino y espacio de trabajo de la plataforma de datos (minuto 01:30)" in r
        assert "**Sin tratar (quedan pendientes)**" in r and "- Frecuencia y calidad de la carga" in r
        assert [o["estado"] for o in rev["objetivos"]] == ["cubierto", "cubierto", "parcial", "sin_tratar"]
        # 5. aceptación de un cambio: se escribe en el contexto compartido, tras aceptar, y solo ahí
        assert (ajena / CARPETA_CONTEXTO / "02-alcance.md").read_text(encoding="utf-8") == alcance_antes
        res = await gestor.aplicar_revision([c["id"] for c in rev["cambios"] if c["valido"]])
        assert res["ficheros"] == ["02-alcance.md"] and not res["carpeta_creada"]
        assert "Espacio beta-datos" in (ajena / CARPETA_CONTEXTO / "02-alcance.md").read_text(encoding="utf-8")
        registro = (ajena / CARPETA_CONTEXTO / "10-registro-de-cambios.md").read_text(encoding="utf-8")
        # el registro es neutro: copia local y, si el usuario publica, «02. Sesiones» de la carpeta compartida
        assert "guardada en local por WhisperMeet" in registro and "si el usuario la publica" in registro
        guardada = s.ruta.read_text(encoding="utf-8")
        assert "sesion_plan: \"S1 · Revisión del almacén de datos\"" in guardada and "almacenamiento: local" in guardada
        assert "## Objetivos de la sesión" in guardada and "Frecuencia y calidad de la carga" in guardada
        # 6. hasta aquí (reunión y revisión) «02. Sesiones» no existe; se crea SOLO al publicar, al cerrar
        assert not (ajena / CARPETA_SESIONES).exists()
        assert rev["publicacion"]["publicar"] is True and rev["publicacion"]["estado"] == "pendiente"
        assert (await gestor.cerrar_revision())["ok"]

    ejecutar(go())
    publicadas = list((ajena / CARPETA_SESIONES).glob("*.md"))
    assert len(publicadas) == 1
    doc = publicadas[0].read_text(encoding="utf-8")
    assert "almacenamiento: publicada en la carpeta compartida" in doc and "## Objetivos de la sesión" in doc
    # solo cambian los dos ficheros de contexto aceptados y aparece la sesión publicada; nada más
    despues = sorted(p.relative_to(ajena).as_posix() for p in ajena.rglob("*"))
    nuevos = sorted(set(despues) - set(antes))
    assert nuevos == sorted([CARPETA_SESIONES, f"{CARPETA_SESIONES}/{publicadas[0].name}"])


def test_solo_se_envian_los_objetivos_de_la_sesion_elegida(montaje):
    gestor, llm, *_ = montaje

    async def go():
        await gestor.iniciar(COMPARTIDO, "x", 5, "S2")
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await gestor.analizar(manual=True)
        await cerrar(gestor)

    ejecutar(go())
    for sistema, usuario, _ in (c for c in llm.llamadas if "análisis incremental" in c[0] or "cierre" in c[0]):
        bloque = usuario.split("<<<DATOS objetivos_sesion>>>")[1].split("<<<FIN>>>")[0]
        assert "Presentación del diseño funcional" in bloque and "Aprobación en acta" in bloque
        assert "Inquilino" not in bloque and "Frecuencia" not in bloque and "OBJETIVOS" in sistema


def test_sin_plan_el_periodico_no_cambia_y_otra_reunion_tampoco(montaje):
    gestor, llm, *_ = montaje

    async def una(sesion_plan):
        gestor.sim = lineas()
        await gestor.iniciar(COMPARTIDO, "Libre", 5, sesion_plan)
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        assert (await gestor.analizar(manual=True))["ok"]
        assert gestor.sesion.objetivos == [] and gestor.estado_ligero()["objetivos"] == []
        await cerrar(gestor)
        assert "Objetivos" not in gestor.revision["resumen"]
        await gestor.cerrar_revision()

    ejecutar(una("otra"))
    ejecutar(una(None))
    periodicos = [(s, u) for s, u, _ in llm.llamadas if "análisis incremental" in s]
    assert len(periodicos) == 2
    for sistema, usuario in periodicos:
        assert "OBJETIVOS" not in sistema and "objetivos_sesion" not in usuario


def test_digest_usa_el_prioritario_primero_y_la_cache_distingue_sesiones(montaje):
    gestor, llm, *_ = montaje

    async def una(sesion_plan):
        gestor.sim = lineas()
        await gestor.iniciar(COMPARTIDO, "t", 5, sesion_plan)
        await esperar(lambda: gestor.digest_origen in ("generado", "cache"))
        origen = gestor.digest_origen
        await cerrar(gestor)
        await gestor.cerrar_revision()
        return origen

    assert ejecutar(una("S1")) == "generado"
    assert ejecutar(una("S1")) == "cache"
    assert ejecutar(una("S2")) == "generado"  # otra sesión, otra clave
    assert ejecutar(una("otra")) == "generado"  # sin plan: clave propia (tema y objetivos propios)
    digests = [(s, u) for s, u, _ in llm.llamadas if "compactar el contexto" in s]
    assert len(digests) == 3
    sistema, usuario = digests[0]
    assert usuario.lstrip().startswith("<<<DATOS fichero 12-guion-sesion-datos.md>>>")
    assert "Revisión del almacén de datos" in sistema and "prioritario" in sistema
    assert "prioritario" not in digests[2][0] and "objetivos: " not in digests[2][0]   # «Otra reunión»: sin fichero prioritario ni objetivos del plan


def test_sesion_de_plan_inexistente_o_proyecto_sin_plan(montaje):
    gestor, *_ = montaje

    async def go():
        with pytest.raises(ValueError, match="no existe"):
            await gestor.iniciar(COMPARTIDO, "t", 5, "TR9")
        with pytest.raises(ValueError, match="no tiene plan"):
            await gestor.iniciar("Proyecto Ficticio Alfa", "t", 5, "S1")
        assert gestor.estado == "inactivo" and gestor.sesion is None

    ejecutar(go())


def test_no_se_crea_la_carpeta_de_contexto_en_un_proyecto_compartido(montaje):
    gestor, llm, _, ajena, _ = montaje
    shutil.rmtree(ajena / CARPETA_CONTEXTO)

    async def go():
        await gestor.iniciar(COMPARTIDO, "t", 5, "S1")
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await cerrar(gestor)
        validos = [c["id"] for c in gestor.revision["cambios"] if c["valido"]]
        assert validos and gestor.revision["compartido"] is True
        with pytest.raises(ValueError, match="no la crea"):
            await gestor.aplicar_revision(validos)

    ejecutar(go())
    assert not (ajena / CARPETA_CONTEXTO).exists() and not (ajena / CARPETA_SESIONES).exists()


def test_los_objetivos_añaden_pocos_tokens_al_periodico(montaje):
    """Medida con el modelo falso: caracteres enviados con y sin plan en la misma llamada periódica."""
    gestor, llm, *_ = montaje

    gestor.checks.para_prompt = lambda *a, **k: []  # aquí se mide solo lo que añaden los objetivos (los checks tienen su test)

    async def una(sesion_plan):
        gestor.sim = lineas()
        await gestor.iniciar(COMPARTIDO, "t", 5, sesion_plan)
        await esperar(lambda: len(gestor.sesion.segmentos) >= 30)
        await gestor.analizar(manual=True)
        await cerrar(gestor)
        await gestor.cerrar_revision(publicar=False)

    ejecutar(una("otra"))
    ejecutar(una("S1"))
    (s0, u0), (s1, u1) = [(s, u) for s, u, _ in llm.llamadas if "análisis incremental" in s]
    extra = (len(s1) + len(u1)) - (len(s0) + len(u0))
    assert 0 < extra < 1500, extra  # unos 400 tokens como máximo; en la práctica ~250
