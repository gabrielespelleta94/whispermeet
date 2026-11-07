"""Evalúa el asesor en directo con transcripciones REALES de bandeja\\ (solo lectura).

    .venv\\Scripts\\python.exe pruebas\\evaluar_asesor.py                  # SIN tokens: modelo falso, reloj simulado, reproduce las 4 sesiones
    .venv\\Scripts\\python.exe pruebas\\evaluar_asesor.py --detector       # solo el detector: aciertos y descartes por transcripción
    .venv\\Scripts\\python.exe pruebas\\evaluar_asesor.py --real --salida pruebas\\_real\\evaluar_asesor_real.json
        # CON tokens y LIMITADO: como máximo 8 llamadas haiku y 3 sonnet en total, con consumo y caché TEMPORALES (nunca datos\\consumo.jsonl)

El modo sin tokens lleva la transcripción por el Gestor de verdad (eco, Monitor, límites de 20 s, deduplicación, presupuesto, escalada, Estratega) con un
modelo falso que contesta al instante y mide el tamaño de cada prompt; los tokens son una ESTIMACIÓN (860 del suelo de `claude -p` + caracteres/3,3 + la salida).
Nada se escribe en bandeja\\, sesiones\\ ni datos\\: todo va a una carpeta temporal.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
import tempfile
import threading
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from apuntes import asesor as A  # noqa: E402
from apuntes.analisis import ModeloLLM, Respuesta, Uso  # noqa: E402
from apuntes.config import Config  # noqa: E402
from apuntes.consumo import Consumo  # noqa: E402
from apuntes.gestor import Gestor  # noqa: E402
from apuntes.rutas import Guardian  # noqa: E402

BANDEJA = RAIZ / "bandeja"
# Cuatro sesiones de bandeja\ (copias de reuniones propias, nunca versionadas). Los nombres de abajo son genéricos: para usar las tuyas,
# define APUNTES_SESIONES_EVAL con cuatro nombres de .md de bandeja\ separados por comas (A, B, C y D, en ese orden).
_POR_DEFECTO = ["2026-11-05-reunion-a.md", "2026-11-05-reunion-b.md", "2026-11-05-reunion-b-2.md", "2026-11-05-reunion-c.md"]
_ELEGIDAS = [s.strip() for s in os.environ.get("APUNTES_SESIONES_EVAL", "").split(",") if s.strip()]
SESIONES = _ELEGIDAS if len(_ELEGIDAS) == 4 else _POR_DEFECTO
SES_A, SES_B, SES_B2, SES_C = SESIONES
LATENCIA_TRANSCRIPCION_S = 8.0          # lo que tarda Whisper en entregar un fragmento después de decirse (estimación)
RE_LINEA = re.compile(r"^\[(\d+):(\d{2})\] \*\*([^*]+)\*\*:? ?(.*)$")


def cargar(nombre: str) -> tuple[list[tuple[float, str, str]], float]:
    """(segmentos [(t, fuente, texto)] en el orden del .md, duración s). Solo lectura."""
    txt = (BANDEJA / nombre).read_text(encoding="utf-8")
    dur = re.search(r"^duracion: (\d+):(\d{2})", txt, re.M)
    cuerpo = txt.split("## Transcripción")[-1]
    segs = []
    for linea in cuerpo.splitlines():
        m = RE_LINEA.match(linea)
        if m:
            segs.append((int(m.group(1)) * 60 + int(m.group(2)), "yo" if m.group(3).strip(": ").lower() == "micro" else "reunion", m.group(4).strip()))
    return segs, (int(dur.group(1)) * 60 + int(dur.group(2))) if dur else (segs[-1][0] if segs else 0)


# ================================================================ detector
def informe_detector() -> dict:
    out = {}
    for nombre in SESIONES:
        segs, dur = cargar(nombre)
        hay, aciertos, descartes = 0, [], []
        for t, f, texto in segs:
            for fr in A.frases_interrogativas(texto):
                hay += 1
                ok = A.detectar_preguntas(f"¿{fr}?")
                (aciertos if ok else descartes).append((t, f, fr))
        out[nombre] = {"con_interrogacion": hay, "detectadas": len(aciertos), "descartadas": len(descartes),
                       "ejemplos_detectadas": [f"{t // 60:02d}:{t % 60:02d} {f[:2].upper()} {x[:90]}" for t, f, x in aciertos[:10]],
                       "ejemplos_descartadas": [f"{t // 60:02d}:{t % 60:02d} {f[:2].upper()} {x[:90]}" for t, f, x in descartes[:12]],
                       "duracion_s": dur}
    return out


# ================================================================ modelo falso: contesta al instante y mide los prompts
class Medidor(ModeloLLM):
    def __init__(self):
        self.llamadas = []
        self._l = threading.Lock()

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False, web=False):
        if "compactar el contexto" in sistema:
            r = {"pm": "[04-plan.md] " + "Plan y fechas. " * 40, "fun": "[02-alcance.md] " + "Reglas y glosario. " * 35, "tec": "[03-datos.md] " + "Datos y sistemas. " * 35,
                 "rev": "[02-alcance.md] " + "Alcance y supuestos. " * 30, "checks": []}
            tarea = "digest"
        elif "acaba de hacer la pregunta" in sistema:
            r = {"v": ["Lo confirmo con el equipo y vuelvo con la respuesta exacta hoy mismo.", "Mientras tanto, te cuento lo que ya está acordado en el proyecto."], "c": "media", "f": [], "b": True}
            tarea = "respuesta_" + modelo
        elif "estratega comercial" in sistema:
            r = {"k": [{"t": "pregunta", "a": "Pregunta quién valida el siguiente entregable antes del cierre", "p": "Sin validador no hay fecha firme para el cliente", "m": "00:10"}]}
            tarea = "consejo_" + modelo
        elif "compañero del equipo" in sistema:
            r = {"t": [], "e": "Tema", "c": [], "o": [], "k": []}
            tarea = "equipo"
        elif "verificar candidatas" in sistema:
            r, tarea = {"v": []}, "verificar"
        else:
            r, tarea = {"resumen": "Resumen.", "cambios": []}, "final"
        texto = json.dumps(r, ensure_ascii=False)
        entrada = int(860 + (len(sistema) + len(usuario)) / 3.3)
        salida = int(len(texto) / 3.3) + 40
        with self._l:
            self.llamadas.append({"tarea": tarea, "modelo": modelo, "entrada": entrada, "salida": salida})
        return Respuesta(texto, [Uso(modelo, entrada, salida)], 10)


def proyecto_sintetico(base: Path) -> Path:
    """Un proyecto ficticio con contexto de unos 18.000 caracteres: el digest y los extractos llenan sus topes, como en una reunión real."""
    raiz = base / "proyectos"
    ctx = raiz / "Proyecto Evaluacion" / "00. CONTEXTO (IA)"
    ctx.mkdir(parents=True)
    tema = ("El alcance incluye el alta de inversiones, el calendario de aprobaciones, el envío de correos de aviso y los informes de seguimiento en Power BI. "
            "La simulación de presupuesto, la integración con el sistema de facturación y los permisos por hotel se tratan en la fase siguiente. ")
    for i, nombre in enumerate(["01-ficha-del-proyecto.md", "02-alcance.md", "03-datos-y-sistemas.md", "04-plan-y-gobierno.md"], 1):
        (ctx / nombre).write_text(f"# {nombre}\n\n" + "\n\n".join(f"## Sección {j}\n\n{tema * 3}" for j in range(1, 6)), encoding="utf-8")
    return raiz


def estimar(llamadas: list[dict], duracion_s: float) -> dict:
    por = {}
    for c in llamadas:
        k = por.setdefault(c["tarea"], {"n": 0, "tokens": 0})
        k["n"] += 1
        k["tokens"] += c["entrada"] + c["salida"]
    h = 3600.0 / max(duracion_s, 1)
    asesor = {k: v for k, v in por.items() if k.startswith(("respuesta_", "consejo_"))}
    return {"por_tarea": por, "asesor_llamadas": sum(v["n"] for v in asesor.values()), "asesor_tokens": sum(v["tokens"] for v in asesor.values()),
            "asesor_llamadas_hora": round(sum(v["n"] for v in asesor.values()) * h, 1), "asesor_tokens_hora": round(sum(v["tokens"] for v in asesor.values()) * h),
            "asesor_sonnet_hora": round(sum(v["n"] for k, v in asesor.items() if k.endswith("sonnet")) * h, 1)}


async def reproducir(nombre: str, tmp: Path) -> dict:
    segs, dur = cargar(nombre)
    raiz = proyecto_sintetico(tmp / nombre)
    g = Guardian(raiz, tmp / nombre / "bandeja", tmp / nombre / "cache")
    cfg = Config(tmp / nombre / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": ""}, guardar=False)
    modelo = Medidor()
    gestor = Gestor(cfg, g, Consumo(None), modelo, lambda e: None, simulacion=[], velocidad=1)
    await gestor.iniciar("Proyecto Evaluacion", "Evaluación", "equipo")
    for t in list(gestor._tareas):
        if t is not gestor._digest_tarea:
            t.cancel()
    await asyncio.wait({gestor._digest_tarea}, timeout=30)
    await asyncio.to_thread(gestor.fuentes.listo_proyecto.wait, 20)
    llegada = [(t + LATENCIA_TRANSCRIPCION_S, t, f, x) for t, f, x in segs]
    reloj = 0.0
    i = 0
    fin = max([l[0] for l in llegada] + [dur]) + 60
    siguiente_monitor = 30.0

    async def asentar():
        for _ in range(400):
            if not gestor.asesor.en_curso and not any(r["estado"] == "en_curso" or r["escalada"] in ("pendiente", "en_curso") for r in gestor.sesion.respuestas) \
                    and gestor.equipo.en_curso is None and gestor.equipo.eligiendo is None:
                return
            await asyncio.sleep(0.005)

    while reloj <= fin:
        gestor.reloj.fijar(reloj)
        while i < len(llegada) and llegada[i][0] <= reloj:
            _, t, f, x = llegada[i]
            gestor._agregar(t, f, x)
            i += 1
        if reloj >= siguiente_monitor:
            siguiente_monitor += 30
            await gestor._vigilar()
            await asentar()
        if gestor._asesor_paso():
            await asentar()
        reloj += 1.0
    await asentar()
    s, a = gestor.sesion, gestor.asesor
    res = [r for r in s.respuestas]
    out = {"duracion_s": dur, "segmentos": len(segs), "preguntas_detectadas": a.stats["detectadas"], "duplicadas": a.stats["duplicadas"],
           "sustituidas_por_otra_mas_reciente": a.stats["sustituidas"], "caducadas": a.stats["caducadas"], "sin_presupuesto": a.stats["sin_presupuesto"],
           "respuestas_haiku": sum(1 for r in res), "escaladas_sonnet": sum(1 for r in res if r["escalada"] == "hecha"), "sin_sonnet_por_limite": sum(1 for r in res if r["escalada"] == "limite"),
           "consejos": len(s.consejos), "turnos_estratega": sum(1 for c in modelo.llamadas if c["tarea"].startswith("consejo_")),
           "preguntas_respondidas": [f"{r['minuto']} {r['canal'][:2]} {r['pregunta'][:80]}" + (f"  [{', '.join(r['temas'])}]" if r["temas"] else "") for r in res],
           **estimar(modelo.llamadas, dur)}
    await gestor.terminar() if False else None
    return out


def informe_sin_tokens() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="evaluar-asesor-"))
    try:
        return {n: asyncio.run(reproducir(n, tmp)) for n in SESIONES}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ================================================================ CON tokens, limitado (--real)
LIMITE_HAIKU, LIMITE_SONNET = 8, 3
# (sesión, minuto de la pregunta, pregunta, qué se espera, ¿escalar a sonnet?): el asesor tiene a mano la transcripción hasta ese minuto y las sesiones anteriores
PREGUNTAS_REALES = [
    (SES_A, 5 * 60 + 12, "¿Qué servicio de correo envía el mail al crear un registro?",
     "sin base en las fuentes: debe decir que no hay base (la respuesta llega después en la reunión) y no inventar un servicio", False),
    (SES_A, 4 * 60 + 50, "¿Se cumple el objetivo del 15 de noviembre?",
     "base en la transcripción (04:12): empezar el presupuesto con la herramienta el 15 de noviembre; casi productiva en una semana; depende de otro equipo", True),
    (SES_B, 2 * 60 + 12, "¿Qué tengo comprometido? ¿Qué tengo de obligación?",
     "base en la transcripción (01:21-02:11): primero lo comprometido sin detalle, luego el detalle; no prometer nada", False),
    (SES_A, 26 * 60 + 2, "¿Y va ganando el audio o también el vídeo?",
     "base débil en la transcripción: se habla de transcribir la reunión; no debe afirmar que graba vídeo", False),
]


def real(salida: Path | None, falso: bool = False, repaso: bool = False, tope_haiku: int = LIMITE_HAIKU, tope_sonnet: int = LIMITE_SONNET) -> dict:
    """`repaso`: SOLO dos comprobaciones tras ajustar el prompt (la pregunta de plazos con haiku y la búsqueda web sobre la del correo, también con haiku); con los
    topes que se pasen (el total de las dos pasadas reales no pasa de 8 llamadas haiku y 3 sonnet)."""
    from apuntes import backlog as BL
    from apuntes.analisis import claude_cli, crear_modelo
    tmp = Path(tempfile.mkdtemp(prefix="evaluar-asesor-real-"))
    consumo_ruta = tmp / "consumo-temporal.jsonl"          # NUNCA datos\consumo.jsonl
    raiz = tmp / "proyectos"
    n_proyectos = [0]
    cfg = Config(tmp / "config.json")
    cfg.actualizar({"raiz_proyectos": str(raiz), "knowledge": "", "proyectos_extra": []}, guardar=False)
    g = Guardian(raiz, tmp / "bandeja", tmp / "cache")
    llm = Medidor() if falso else crear_modelo(cfg)
    contadores = {"haiku": 0, "sonnet": 0}
    original = llm.completar

    def contado(sistema, usuario, modelo, *a, **k):
        clave = "sonnet" if "sonnet" in modelo else "haiku" if "haiku" in modelo else modelo
        if contadores.get(clave, 0) >= {"haiku": tope_haiku, "sonnet": tope_sonnet}.get(clave, 0):
            raise RuntimeError(f"tope de llamadas reales alcanzado ({clave})")
        contadores[clave] = contadores.get(clave, 0) + 1
        if os.environ.get("APUNTES_VOLCAR"):   # para revisar a mano lo que viaja al modelo (el contenido no se guarda en ningún otro sitio)
            d = Path(os.environ["APUNTES_VOLCAR"])
            d.mkdir(parents=True, exist_ok=True)
            nombre = f"{sum(contadores.values()):02d}-{clave}{'-web' if k.get('web') else ''}.txt"
            (d / nombre).write_text("=== SISTEMA ===\n" + sistema + "\n\n=== USUARIO ===\n" + usuario, encoding="utf-8")
        return original(sistema, usuario, modelo, *a, **k)
    llm.completar = contado
    resultados = []

    async def nueva_sesion(tema: str, excluir: str, desde: float, hasta: float, sesion_md: str, sonnet_libre: bool):
        # un proyecto temporal por pregunta: sus «sesiones anteriores» son las OTRAS reuniones del mismo día (copias; los originales no se tocan) y nunca la que se reproduce
        n_proyectos[0] += 1
        nombre = f"Eval{n_proyectos[0]}"
        ses_dir = raiz / nombre / "02. Sesiones (transcripciones)"
        ses_dir.mkdir(parents=True)
        for n in (SES_B, SES_B2):
            if n != excluir:
                shutil.copyfile(BANDEJA / n, ses_dir / n)
        gestor = Gestor(cfg, g, Consumo(consumo_ruta), llm, lambda e: None, simulacion=[], velocidad=1)
        gestor.fuentes.backlog = BL.Backlog(g, cfg)
        await gestor.iniciar(nombre, tema, "manual")
        for t in list(gestor._tareas):
            t.cancel()
        await asyncio.to_thread(gestor.fuentes.listo_proyecto.wait, 30)
        segs, _ = cargar(sesion_md)
        for t, f, x in segs:
            if desde <= t <= hasta:
                gestor._agregar(t, f, x)
        gestor.reloj.fijar(hasta + 4)
        gestor.asesor.sonnet_t = [] if sonnet_libre else [1e12] * 8       # solo se escala la pregunta pedida: el resto se queda con haiku (y lo dice)
        return gestor

    def resumen(gestor, esperado=""):
        r = dict(gestor.sesion.respuestas[-1])
        return {"pregunta": r["pregunta"], "minuto": r["minuto"], "esperado": esperado, **{k: r.get(k) for k in (
            "estado", "vinetas", "confianza", "citas", "sin_base", "orientacion", "modelo", "escalada", "temas", "previa", "tokens", "error", "error_escalada")}}

    async def todo_repaso():
        # 1) la pregunta de plazos SOLO con haiku (sin escalar): ¿encuentra ahora lo dicho en la transcripción reciente (04:12)?
        sesion, minuto, pregunta, esperado, _ = PREGUNTAS_REALES[1]
        gst = await nueva_sesion(f"Repaso {minuto}", sesion, 0, minuto, sesion, False)
        gst.asesor.en_curso = True
        await gst.asesor.responder({"pregunta": pregunta, "t": float(minuto), "canal": "reunion", "detectada": float(minuto)})
        for _ in range(4000):
            r = gst.sesion.respuestas[-1]
            if r["estado"] != "en_curso" and r["escalada"] not in ("pendiente", "en_curso"):
                break
            await asyncio.sleep(0.05)
        resultados.append({"sesion": sesion, **resumen(gst, esperado)})
        # 2) la búsqueda web (con haiku, para no gastar sonnet) sobre una pregunta genérica de tecnología, partiendo de una respuesta sin base que ya existía
        cfg.actualizar({"modelos": {"asesor_profundizar": "haiku"}}, guardar=False)
        sesion, minuto, pregunta, esperado, _ = PREGUNTAS_REALES[0]
        gst = await nueva_sesion(f"Repaso web {minuto}", sesion, 0, minuto, sesion, False)
        gst.sesion.respuestas.append({"id": "r1", "pregunta": pregunta, "minuto": "05:12", "t_seg": 312.0, "canal": "Reunión", "estado": "ok", "vinetas": ["No hay base en tus fuentes: propón comprobarlo y volver con la respuesta"],
                                      "confianza": "baja", "citas": [], "base": False, "sin_base": True, "orientacion": False, "sin_cita": False, "modelo": "haiku", "temas": [], "escalada": "",
                                      "fijada": False, "descartada": False, "profundizada": None, "error": "", "tokens": None})
        ok, motivo = claude_cli.capacidad_web()
        resultados.append({"web_disponible": ok, "motivo": motivo})
        if ok:
            try:
                res2 = await gst.asesor.profundizar("r1", web=True)
            except Exception as e:  # noqa: BLE001
                res2 = {"ok": False, "error": str(e)}
            resultados.append({"profundizar_con_web": res2, "pregunta": pregunta, "r": gst.sesion.respuestas[0]["profundizada"]})

    async def todo():
        gestores = []
        for sesion, minuto, pregunta, esperado, escalar in PREGUNTAS_REALES:
            gst = await nueva_sesion(f"Evaluación {minuto}", sesion, 0, minuto, sesion, escalar)
            gst.asesor.en_curso = True
            await gst.asesor.responder({"pregunta": pregunta, "t": float(minuto), "canal": "reunion", "detectada": float(minuto)})
            for _ in range(4000):
                r = gst.sesion.respuestas[-1]
                if r["estado"] != "en_curso" and r["escalada"] not in ("pendiente", "en_curso"):
                    break
                await asyncio.sleep(0.05)
            gestores.append(gst)
            resultados.append({"sesion": sesion, **resumen(gst, esperado)})
        # el Estratega: UN turno (haiku) sobre el tramo de la presentación del cliente
        gst = await nueva_sesion("Evaluación estratega", SES_B, 12 * 60, 15 * 60 + 30, SES_A, False)
        res = await gst.equipo.turno_estratega("a petición", manual=True)
        resultados.append({"estratega": res, "consejos": [{k: c.get(k) for k in ("etiqueta", "accion", "porque", "minuto", "modelo", "tokens")} for c in gst.sesion.consejos]})
        # «Profundizar» sin web sobre la pregunta de plazos (sonnet) y con web sobre la del correo (sonnet)
        res1 = await gestores[1].asesor.profundizar("r1", web=False)
        resultados.append({"profundizar_sin_web": res1, "pregunta": gestores[1].sesion.respuestas[0]["pregunta"], "r": gestores[1].sesion.respuestas[0]["profundizada"]})
        ok, motivo = claude_cli.capacidad_web()
        resultados.append({"web_disponible": ok, "motivo": motivo})
        if ok:
            try:
                res2 = await gestores[0].asesor.profundizar("r1", web=True)
            except Exception as e:  # noqa: BLE001
                res2 = {"ok": False, "error": str(e)}
            resultados.append({"profundizar_con_web": res2, "pregunta": gestores[0].sesion.respuestas[0]["pregunta"], "r": gestores[0].sesion.respuestas[0]["profundizada"]})
    try:
        asyncio.run(todo_repaso() if repaso else todo())
    finally:
        sal = {"llamadas_reales": contadores, "resultados": resultados, "consumo_temporal": str(consumo_ruta)}
        if salida:
            salida.parent.mkdir(parents=True, exist_ok=True)
            salida.write_text(json.dumps(sal, ensure_ascii=False, indent=1), encoding="utf-8")
    return sal


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detector", action="store_true")
    ap.add_argument("--real", action="store_true", help="CON tokens: como mucho 8 llamadas haiku y 3 sonnet")
    ap.add_argument("--falso", action="store_true", help="con --real: ensayo con el modelo falso (sin tokens)")
    ap.add_argument("--repaso", action="store_true", help="con --real: solo las dos comprobaciones de después de ajustar el prompt")
    ap.add_argument("--tope-haiku", type=int, default=LIMITE_HAIKU)
    ap.add_argument("--tope-sonnet", type=int, default=LIMITE_SONNET)
    ap.add_argument("--salida", type=Path)
    a = ap.parse_args()
    if a.detector:
        print(json.dumps(informe_detector(), ensure_ascii=False, indent=1))
    elif a.real:
        print(json.dumps(real(a.salida, a.falso, a.repaso, a.tope_haiku, a.tope_sonnet), ensure_ascii=False, indent=1))
    else:
        print(json.dumps(informe_sin_tokens(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
