r"""Reproduce el reparto de turnos del equipo sobre una transcripción SIN llamar al modelo (cero tokens): el Monitor real, los
enfriamientos reales y la ventana de 2.600 caracteres de cada turno. Sirve para ver cuántos turnos habría, a quién le tocaría y qué parte de
la reunión llegaría a leer algún perfil, antes de gastar una pasada real.

    .venv\Scripts\python.exe pruebas\simular_equipo.py [pruebas\_real\tr2.txt] [--min-palabras 120] [--chars 2600] [--minutos 03:53,07:01,...]

Duración de cada llamada: 10 s (la media medida). Un perfil lee lo que se ha dicho desde SU último turno, con tope de `--chars` (las últimas).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace as N

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from apuntes.equipo import perfiles as PF  # noqa: E402
from apuntes.equipo.monitor import Monitor, seleccionar_para  # noqa: E402
from apuntes.simulador import cargar  # noqa: E402
from apuntes.texto import ETIQUETAS, a_segundos, formatear_lineas, limpiar_transcripcion, mmss  # noqa: E402

MINUTOS_LISTA = "03:53,07:01,08:04,10:04,25:19,31:55,53:01,62:37,67:18,69:53"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("transcripcion", nargs="?", default=str(AQUI / "_real" / "tr2.txt"))
    ap.add_argument("--chars", type=int, default=2600)
    ap.add_argument("--min-palabras", type=int, default=120)
    ap.add_argument("--duracion-llamada", type=float, default=10.0)
    ap.add_argument("--minutos", default=MINUTOS_LISTA)
    ap.add_argument("--enfriamiento-global", type=float, default=None)
    ap.add_argument("--enfriamiento-perfil", type=float, default=None)
    ap.add_argument("--ultimas", action="store_true", help="la regla literal de la especificación: solo las últimas --chars caracteres")
    ap.add_argument("--objetivos", default="", help="objetivos de la sesión separados por «;» (dan puntos al Revisor)")
    a = ap.parse_args()
    lineas = cargar(a.transcripcion)
    segs = [N(id=i, t=l.t, fuente=l.fuente, texto=l.texto) for i, l in enumerate(lineas, 1)]
    fin = max(s.t for s in segs)
    OBJ = [{"n": i, "texto": x.strip(), "estado": "sin_tratar"} for i, x in enumerate(a.objetivos.split(";"), 1) if x.strip()]
    cfg = {"equipo_palabras_min": a.min_palabras}
    if a.enfriamiento_global is not None:
        cfg["equipo_enfriamiento_global_s"] = a.enfriamiento_global
    if a.enfriamiento_perfil is not None:
        cfg["equipo_enfriamiento_perfil_s"] = a.enfriamiento_perfil
    m = Monitor(cfg)
    ultimo_id = {p: 0 for p in PF.ORDEN_ROTACION}
    cubierto: list[tuple[float, float, str]] = []     # (desde, hasta, perfil)
    turnos = []
    t, hasta_llamada = 30.0, 0.0
    while t <= fin + 30:
        visibles = [s for s in segs if s.t <= t]
        pas = m.pasada(t, [s for s in visibles if s.id > m.ultimo_id], OBJ)
        if t >= hasta_llamada:
            perfil, motivo = m.elegir(t, "normal", False)
            if perfil:
                nuevos = [s for s in visibles if s.id > ultimo_id[perfil]]
                lns = limpiar_transcripcion(nuevos)
                texto = formatear_lineas(lns)
                if a.ultimas:
                    leido = PF.recortar_nuevo(texto, a.chars)
                    ts = [l.t for l in lns if f"[{mmss(l.t)}]" in leido]
                else:
                    leido, pos = seleccionar_para(perfil, lns, a.chars, lambda l: f"[{mmss(l.t)}] {ETIQUETAS.get(l.fuente, 'R')}: {l.texto}")
                    ts = [lns[i].t for i in pos]
                cubierto.extend((x - 40, x + 40, perfil) for x in ts)
                turnos.append({"t": t, "perfil": perfil, "motivo": motivo, "chars_nuevos": len(texto), "chars_leidos": len(leido)})
                ultimo_id[perfil] = nuevos[-1].id
                m.turno_hecho(perfil, t + a.duracion_llamada)
                hasta_llamada = t + a.duracion_llamada
        t += 30
    print(f"{Path(a.transcripcion).name}: {mmss(fin)} · {len(turnos)} turnos ({len(turnos) * 3600 / fin:.1f} por hora)")
    por = {}
    for x in turnos:
        por[x["perfil"]] = por.get(x["perfil"], 0) + 1
    print("por perfil:", por, "· motivos:", {k: sum(1 for x in turnos if x["motivo"] == k) for k in sorted({x["motivo"] for x in turnos})})
    for x in turnos:
        print(f"  {mmss(x['t'])} {x['perfil']:11} {x['motivo']:28} leyó {x['chars_leidos']:>5} de {x['chars_nuevos']:>6} caracteres nuevos")
    perdidos = sum(max(0, x["chars_nuevos"] - x["chars_leidos"]) for x in turnos)
    print(f"caracteres que un perfil no llega a leer por el tope de {a.chars}: {perdidos}")
    tot = sum(len(s.texto) for s in segs)
    cub = 0
    for s in segs:
        if any(d <= s.t <= h for d, h, _ in cubierto):
            cub += len(s.texto)
    print(f"transcripción que lee AL MENOS un perfil: {100 * cub / tot:.0f} % (de {tot} caracteres)")
    for mm in a.minutos.split(","):
        seg = a_segundos(mm)
        quien = sorted({p for d, h, p in cubierto if d <= seg <= h})
        print(f"  {mm}: {'leído por ' + ', '.join(quien) if quien else 'NO lo lee ningún perfil'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
