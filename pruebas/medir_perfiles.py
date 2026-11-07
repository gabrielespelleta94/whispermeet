r"""Mide el supuesto clave del equipo: cada perfil, con su prompt corto y `--effort low`, sobre tramos reales de TR2.

    .venv\Scripts\python.exe pruebas\medir_perfiles.py [--fase base|cache|variantes] [--pausa 25] [--espera-larga 390]

Usa los mismos flags que la aplicación (`claude_cli.construir_comando` y `entorno_limpio`), el prompt de producción
(`apuntes/equipo/perfiles.py`) y la transcripción real de pruebas/_real (fuera de git). Por llamada guarda: entrada total
(entrada + caché creada + caché leída), salida, razonamiento (`output_tokens_details.thinking_tokens`), caché leída y creada,
tiempo y si el JSON es válido. Resultados en pruebas/_real/medicion_perfiles.txt y medicion_perfiles.json.
Gasta llamadas reales: la fase `base` son 12 (4 perfiles x 3 tramos) más 1 de digest; las demás son cortas y se declaran.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from apuntes import planes as PL  # noqa: E402
from apuntes.analisis import claude_cli as C  # noqa: E402
from apuntes.analisis import prompts as P  # noqa: E402
from apuntes.config import CLAUDE_CWD  # noqa: E402
from apuntes.equipo import perfiles as PF  # noqa: E402
from apuntes.simulador import cargar  # noqa: E402
from apuntes.texto import formatear_lineas, limpiar_transcripcion  # noqa: E402

REAL = AQUI / "_real"
TRAMOS_S = [(24 * 60 + 30, 27 * 60 + 30), (31 * 60, 34 * 60), (52 * 60, 55 * 60)]   # contienen decisiones de la lista (25:19, 31:55, 53:01)
EXE = C.ClaudeCLI().exe


def llamar(sistema: str, usuario: str, modelo: str = "haiku", extra_args=(), extra_env=None, sin_razonamiento: bool = True,
           esfuerzo: str = "low") -> dict:
    cmd = C.construir_comando(EXE, sistema, modelo, esfuerzo) + list(extra_args)
    env = C.entorno_limpio(sin_razonamiento=sin_razonamiento)
    env.update(extra_env or {})
    CLAUDE_CWD.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    p = subprocess.run(cmd, input=usuario, capture_output=True, text=True, encoding="utf-8", cwd=str(CLAUDE_CWD), env=env, timeout=300)
    d = json.loads(p.stdout)
    u = d["usage"]
    texto = d.get("result") or ""
    ok = P.extraer_json(texto) is not None
    return {"entrada": u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"], "sin_cache": u["input_tokens"],
            "cache_creada": u["cache_creation_input_tokens"], "cache_leida": u["cache_read_input_tokens"], "salida": u["output_tokens"],
            "razonamiento": int((u.get("output_tokens_details") or {}).get("thinking_tokens") or 0),
            "ms": d.get("duration_ms"), "json_ok": ok, "chars_salida": len(texto), "texto": texto, "hora": time.strftime("%H:%M:%S")}


def tramo_real(i: int) -> str:
    lineas = [l for l in cargar(REAL / "tr2.txt") if TRAMOS_S[i][0] <= l.t < TRAMOS_S[i][1]]
    return formatear_lineas(limpiar_transcripcion(lineas))


def digest_tramos() -> dict:
    ruta = REAL / "digest_tramos_tr2.json"
    if ruta.is_file():
        return json.loads(ruta.read_text(encoding="utf-8"))
    from apuntes import contexto as CX
    from apuntes.rutas import Guardian
    raiz = REAL / "proyectos"
    g = Guardian(raiz, AQUI.parent / "bandeja", AQUI.parent / "cache")
    f = CX.fuentes_digest(g, "Planificador TR2 (sin 09 ni 11)", "TR2", "", 14_000, "", "medicion")
    usr = P.usuario_digest(f.textos)
    r = llamar(PF.sistema_digest_tramos(False, "«Análisis con Revenue»"), usr)
    d = P.extraer_json(r["texto"])
    out = {"tramos": {k: d.get(k, "") for k in PF.TRAMOS}, "checks": d.get("checks"), "medida": {k: v for k, v in r.items() if k != "texto"},
           "entrada_chars": sum(len(t) for _, t in f.textos)}
    ruta.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def estado_revisor() -> str:
    """Igual que el director: «Objetivos (número [estado minuto] texto…)»."""
    obj = PL.objetivos_iniciales({"objetivos": [
        "Recorrer los bloques de cálculo y los cuatro estados", "Matrices mes por día de semana, cupos, MLOS, comisión e IVA",
        "Tipología con suplementos o tarifario propio", "Estrategia inicial por hotel", "Inventario fuera de alcance"]})
    return "Objetivos (número [estado minuto] texto; c cubierto, p parcial):\n" + PL.bloque_prompt(obj)


def caso(perfil: str, i_tramo: int, dg: dict, titulos=()) -> tuple[str, str]:
    p = PF.PERFILES[perfil]
    estado = estado_revisor() if perfil == "revisor" else ""
    return PF.sistema(p), PF.usuario(p, dg["tramos"][p.tramo], estado, list(titulos), tramo_real(i_tramo))


def escribir(f, texto: str) -> None:
    print(texto, flush=True)
    f.write(texto + "\n")
    f.flush()


def fase_base(a, f, dg) -> list[dict]:
    res = []
    escribir(f, f"== FASE BASE {time.strftime('%Y-%m-%d %H:%M')} · 12 llamadas (4 perfiles x 3 tramos de TR2), haiku, --effort low, MAX_THINKING_TOKENS=0")
    escribir(f, f"   tramos: {[f'{s // 60}:{s % 60:02d}-{e // 60}:{e % 60:02d}' for s, e in TRAMOS_S]} · digest por tramos: {sum(len(v) for v in dg['tramos'].values())} caracteres en 4 tramos")
    for i in range(3):
        if i == 2 and a.espera_larga:
            escribir(f, f"   (espera de {a.espera_larga} s para ver si algo sigue en caché pasados 5 minutos)")
            time.sleep(a.espera_larga)
        for perfil in PF.ORDEN_ROTACION:
            sis, usr = caso(perfil, i, dg)
            r = llamar(sis, usr)
            r.update(perfil=perfil, tramo=i, chars_sistema=len(sis), chars_usuario=len(usr))
            res.append(r)
            escribir(f, f"   {r['hora']} {perfil:11} tramo {i + 1} · entrada {r['entrada']:>5} (sin caché {r['sin_cache']}, caché creada {r['cache_creada']}, leída {r['cache_leida']})"
                        f" · salida {r['salida']:>4} (razonamiento {r['razonamiento']}) · {r['ms']} ms · json {'ok' if r['json_ok'] else 'MAL'}")
            time.sleep(a.pausa)
    return res


def resumen(f, res: list[dict], titulo: str) -> None:
    if not res:
        return
    n = len(res)
    tot = lambda k: sum(r[k] for r in res)   # noqa: E731
    escribir(f, f"   {titulo}: {n} llamadas · entrada media {tot('entrada') / n:.0f} · salida media {tot('salida') / n:.0f} · razonamiento medio {tot('razonamiento') / n:.0f} "
                f"({100 * tot('razonamiento') / max(1, tot('salida')):.0f} % de la salida) · caché leída media {tot('cache_leida') / n:.0f} · json válido {sum(r['json_ok'] for r in res)}/{n}")
    for perfil in PF.ORDEN_ROTACION:
        sub = [r for r in res if r.get("perfil") == perfil]
        if sub:
            escribir(f, f"      {perfil:11} entrada {sum(r['entrada'] for r in sub) / len(sub):.0f} · salida {sum(r['salida'] for r in sub) / len(sub):.0f} · razonamiento {sum(r['razonamiento'] for r in sub) / len(sub):.0f}")


def fase_variantes(a, f, dg) -> list[dict]:
    """Prompts de producción v2 (base más corta y límites explícitos) sobre los casos que dieron problemas: el Revisor en el tramo 3
    (1.439 tokens de razonamiento) y la Analista funcional (6 elementos y 543 de salida). 6 llamadas."""
    res = []
    escribir(f, f"== FASE VARIANTES {time.strftime('%Y-%m-%d %H:%M')} · prompts v2 (base de {len(PF.BASE_EQUIPO)} caracteres, límites «en total», «o» solo con evidencia) · 6 llamadas")
    for perfil, i in [("revisor", 2), ("revisor", 2), ("funcional", 0), ("funcional", 0), ("coordinador", 0), ("constructor", 0)]:
        sis, usr = caso(perfil, i, dg)
        r = llamar(sis, usr)
        r.update(perfil=perfil, tramo=i, chars_sistema=len(sis), chars_usuario=len(usr))
        res.append(r)
        escribir(f, f"   {r['hora']} {perfil:11} tramo {i + 1} · entrada {r['entrada']:>5} · salida {r['salida']:>4} (razonamiento {r['razonamiento']}) · {r['ms']} ms · json {'ok' if r['json_ok'] else 'MAL'}"
                    f" · elementos {sum(len(v) for v in (P.extraer_json(r['texto']) or {}).values() if isinstance(v, list))}")
        time.sleep(a.pausa)
    return res


def fase_ya_emitido(a, f, dg) -> list[dict]:
    """Causa del razonamiento en la pasada real: los turnos SIN bloque «ya_emitido» (los tres primeros) no razonaron y 6 de 7 con él, sí.
    Misma entrada (Analista funcional, tramo 2) con y sin los últimos títulos propios, dos veces cada una. 4 llamadas."""
    titulos = ["[03:19] regla: Si el día pedido es hot date, no se aceptan grupos", "[08:04] regla: Grupos grandes respecto a la capacidad del hotel los cotiza Revenue",
               "[08:04] pregunta: ¿Cuál es el umbral exacto de habitaciones a partir del cual pasa a Revenue?", "[17:27] regla: El precio no puede ser el de venta: se cotiza el precio objetivo"]
    res = []
    escribir(f, f"== FASE YA_EMITIDO {time.strftime('%Y-%m-%d %H:%M')} · funcional, tramo 2, con y sin «ya_emitido» · 4 llamadas")
    for con in (True, False, True, False):
        sis, usr = caso("funcional", 1, dg, titulos if con else ())
        r = llamar(sis, usr)
        r.update(perfil="funcional", tramo=1, con_ya_emitido=con, chars_sistema=len(sis), chars_usuario=len(usr))
        res.append(r)
        escribir(f, f"   {r['hora']} {'CON' if con else 'SIN'} ya_emitido · entrada {r['entrada']:>5} · salida {r['salida']:>4} (razonamiento {r['razonamiento']}) · {r['ms']} ms")
        time.sleep(a.pausa)
    return res


def fase_razon(a, f, dg) -> list[dict]:
    """¿Quita el razonamiento ocasional (5 de 10 turnos de la pasada real; 2 de 4 aquí)? La misma entrada de la Analista funcional (tramo 2, con
    «ya_emitido») con `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` y `--settings alwaysThinkingEnabled=false`. 4 llamadas."""
    titulos = ["[03:19] regla: Si el día pedido es hot date, no se aceptan grupos", "[08:04] regla: Grupos grandes respecto a la capacidad del hotel los cotiza Revenue",
               "[08:04] pregunta: ¿Cuál es el umbral exacto de habitaciones a partir del cual pasa a Revenue?", "[17:27] regla: El precio no puede ser el de venta: se cotiza el precio objetivo"]
    res = []
    escribir(f, f"== FASE RAZON {time.strftime('%Y-%m-%d %H:%M')} · funcional tramo 2 · DISABLE_ADAPTIVE_THINKING=1 + alwaysThinkingEnabled=false · 4 llamadas")
    for _ in range(4):
        sis, usr = caso("funcional", 1, dg, titulos)
        r = llamar(sis, usr, extra_args=["--settings", json.dumps({"alwaysThinkingEnabled": False})], extra_env={"CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING": "1"})
        r.update(perfil="funcional", tramo=1, chars_sistema=len(sis), chars_usuario=len(usr))
        res.append(r)
        escribir(f, f"   {r['hora']} entrada {r['entrada']:>5} · salida {r['salida']:>4} (razonamiento {r['razonamiento']}) · {r['ms']} ms")
        time.sleep(a.pausa)
    return res


def fase_cierre(a, f, dg) -> list[dict]:
    """Misma entrada de la fase «razon» sin flags, pero con una última línea tras la transcripción: «Responde ya con el JSON, sin pensar.» 4 llamadas."""
    titulos = ["[03:19] regla: Si el día pedido es hot date, no se aceptan grupos", "[08:04] regla: Grupos grandes respecto a la capacidad del hotel los cotiza Revenue",
               "[08:04] pregunta: ¿Cuál es el umbral exacto de habitaciones a partir del cual pasa a Revenue?", "[17:27] regla: El precio no puede ser el de venta: se cotiza el precio objetivo"]
    res = []
    escribir(f, f"== FASE CIERRE {time.strftime('%Y-%m-%d %H:%M')} · funcional tramo 2 · línea final «Responde ya con el JSON, sin pensar.» · 4 llamadas")
    for _ in range(4):
        sis, usr = caso("funcional", 1, dg, titulos)
        usr += "\nResponde ya con el JSON, sin pensar."
        r = llamar(sis, usr)
        r.update(perfil="funcional", tramo=1, chars_sistema=len(sis), chars_usuario=len(usr))
        res.append(r)
        escribir(f, f"   {r['hora']} entrada {r['entrada']:>5} · salida {r['salida']:>4} (razonamiento {r['razonamiento']}) · {r['ms']} ms")
        time.sleep(a.pausa)
    return res


def fase_extraer(a, f, dg) -> list[dict]:
    """Prompt de la Analista funcional como EXTRACCIÓN literal (sin «formula la pregunta exacta» ni «sin interpretar», que invitan a razonar)
    sobre la entrada que razonaba (tramo 2 con «ya_emitido»). 4 llamadas."""
    import dataclasses
    titulos = ["[03:19] regla: Si el día pedido es hot date, no se aceptan grupos", "[08:04] regla: Grupos grandes respecto a la capacidad del hotel los cotiza Revenue",
               "[08:04] pregunta: ¿Cuál es el umbral exacto de habitaciones a partir del cual pasa a Revenue?", "[17:27] regla: El precio no puede ser el de venta: se cotiza el precio objetivo"]
    p = dataclasses.replace(PF.PERFILES["funcional"], prompt=PF.PERFILES_V3["funcional"])
    res = []
    escribir(f, f"== FASE EXTRAER {time.strftime('%Y-%m-%d %H:%M')} · funcional tramo 2 · prompt de extracción · 4 llamadas")
    for _ in range(4):
        _, usr = caso("funcional", 1, dg, titulos)
        sis = PF.sistema(p)
        r = llamar(sis, usr)
        r.update(perfil="funcional", tramo=1, chars_sistema=len(sis), chars_usuario=len(usr))
        res.append(r)
        escribir(f, f"   {r['hora']} entrada {r['entrada']:>5} · salida {r['salida']:>4} (razonamiento {r['razonamiento']}) · {r['ms']} ms")
        time.sleep(a.pausa)
    return res


def fase_contexto(a, f, dg) -> list[dict]:
    """En la pasada real el Coordinador emitió como decisiones cosas del CONTEXTO que nadie dijo («Go-Live semana 8 confirmada por…»). Mismo
    tramo (03:00-08:10 de TR2) con la base que añade «lo que emitas tiene que decirse en la transcripción nueva». 2 llamadas."""
    lineas = [l for l in cargar(REAL / "tr2.txt") if 3 * 60 <= l.t < 8 * 60 + 10]
    nuevo = formatear_lineas(limpiar_transcripcion(lineas))
    p = PF.PERFILES["coordinador"]
    res = []
    escribir(f, f"== FASE CONTEXTO {time.strftime('%Y-%m-%d %H:%M')} · coordinador 03:00-08:10 · 2 llamadas")
    for _ in range(2):
        r = llamar(PF.sistema(p), PF.usuario(p, dg["tramos"][p.tramo], "", [], nuevo))
        r.update(perfil="coordinador", tramo=0, chars_sistema=len(PF.sistema(p)), chars_usuario=0)
        res.append(r)
        escribir(f, f"   {r['hora']} entrada {r['entrada']:>5} · salida {r['salida']:>4} (razonamiento {r['razonamiento']}) · {r['texto'][:600]}")
        time.sleep(a.pausa)
    return res


def fase_cache(a, f, dg) -> list[dict]:
    """¿Funciona la caché de prefijo entre perfiles y pasados 5 minutos? Sistema COMÚN y estable (base + los cuatro perfiles + los cuatro
    tramos del contexto, por encima del mínimo cacheable) y, en el mensaje, solo el perfil y lo nuevo. 3 llamadas: Coordinador, Analista funcional
    20 s después (otro perfil) y Revisor tras una espera real de más de 5 minutos."""
    comun = PF.BASE_EQUIPO + "\n" + "\n".join(f"[{p.nombre}] {p.prompt} {p.formato}" for p in PF.PERFILES.values()) + "\nContexto del proyecto:\n" + PF.digest_como_texto(dg["tramos"])
    escribir(f, f"== FASE CACHE {time.strftime('%Y-%m-%d %H:%M')} · sistema común de {len(comun)} caracteres · 3 llamadas")
    res = []
    for k, (perfil, i, espera) in enumerate([("coordinador", 0, 0), ("funcional", 0, 20), ("revisor", 1, a.espera_larga)]):
        if espera:
            escribir(f, f"   (espera de {espera} s)")
            time.sleep(espera)
        p = PF.PERFILES[perfil]
        usr = f"Hablas como {p.nombre}.\n" + PF.usuario(p, "", estado_revisor() if perfil == "revisor" else "", [], tramo_real(i))
        r = llamar(comun, usr)
        r.update(perfil=perfil, tramo=i, chars_sistema=len(comun), chars_usuario=len(usr))
        res.append(r)
        escribir(f, f"   {r['hora']} {perfil:11} · entrada {r['entrada']:>5} (sin caché {r['sin_cache']}, creada {r['cache_creada']}, leída {r['cache_leida']}) · salida {r['salida']} · {r['ms']} ms")
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fase", default="base", choices=["base", "variantes", "cache", "ya_emitido", "razon", "cierre", "extraer", "contexto"])
    ap.add_argument("--pausa", type=float, default=25.0, help="segundos entre llamadas seguidas")
    ap.add_argument("--espera-larga", type=int, default=390, help="segundos de espera antes del tercer tramo (>5 min)")
    a = ap.parse_args()
    REAL.mkdir(exist_ok=True)
    salida_json = REAL / "medicion_perfiles.json"
    previo = json.loads(salida_json.read_text(encoding="utf-8")) if salida_json.is_file() else {}
    with open(REAL / "medicion_perfiles.txt", "a", encoding="utf-8") as f:
        dg = digest_tramos()
        m = dg["medida"]
        if a.fase == "base":
          escribir(f, f"== DIGEST por tramos (1 llamada, haiku): entrada {m['entrada']} (caché creada {m['cache_creada']}) · salida {m['salida']} (razonamiento {m['razonamiento']}) · {m['ms']} ms · "
                    f"ficheros {dg['entrada_chars']} car. -> tramos {[len(v) for v in dg['tramos'].values()]} car.")
        res = {"base": fase_base, "variantes": fase_variantes, "cache": fase_cache, "ya_emitido": fase_ya_emitido, "razon": fase_razon, "cierre": fase_cierre, "extraer": fase_extraer, "contexto": fase_contexto}[a.fase](a, f, dg)
        resumen(f, res, a.fase.upper())
        previo.setdefault(a.fase, []).append([{k: v for k, v in r.items()} for r in res])
        salida_json.write_text(json.dumps(previo, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
