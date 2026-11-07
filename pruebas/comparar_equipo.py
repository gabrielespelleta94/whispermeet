r"""Compara la pasada del equipo con la anterior (cada 5 min, un solo analista) sobre la misma reunión real TR2.

    .venv\Scripts\python.exe pruebas\comparar_equipo.py [pruebas\_real\resultado_tr2_pasada1.json] [pruebas\_real\resultado_equipo.json]

Imprime: tokens por modelo y total (y ajustados a una hora de reunión), turnos por perfil, tarjetas por categoría y por perfil,
definiciones y, de la lista de decisiones que no deben perderse, cuáles aparecen (con la tarjeta o definición que las recoge) y cuáles no.
Todo sale de los JSON de pruebas/_real (contenido real: no se copia fuera de esa carpeta).
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

AQUI = Path(__file__).resolve().parent
REAL = AQUI / "_real"
# minuto aproximado de la decisión y palabras clave (sin acentos, minúsculas) que la delatan en una tarjeta o definición
DECISIONES = [
    ("03:53", "días sin grupos en estrategia", ["sin grupos", "hot day", "dias sin", "estrategia"]),
    ("07:01", "blackouts en el calendario anual", ["blackout", "calendario anual", "calendario"]),
    ("08:04", "grupos grandes a Revenue", ["grupos grandes", "grande", "revenue"]),
    ("10:04", "cupo superado a Revenue", ["cupo"]),
    ("25:19", "simulador en el caso", ["simulador"]),
    ("31:55", "tarifa negociada de Salesforce", ["tarifa negociada", "negociada"]),
    ("53:01", "motivo de denegada aparte", ["denegad", "motivo"]),
    ("62:37", "datos de plaza en segunda fase", ["plaza", "segunda fase", "fase 2"]),
    ("67:18", "forecast fuera de esta fase", ["forecast"]),
    ("69:53", "modelo funcional el día 5", ["modelo funcional", "dia 5", "día 5", "funcional"]),
]
VENTANA_S = 240


def sin_acentos(t: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn").lower()


def seg(m: str) -> int:
    a, b = m.split(":")
    return int(a) * 60 + int(b)


def tokens(r: dict) -> dict:
    out = {}
    for m, v in r["consumo_por_modelo"].items():
        k = "haiku" if "haiku" in m else "sonnet" if "sonnet" in m else m
        o = out.setdefault(k, {"llamadas": 0, "entrada": 0, "salida": 0})
        o["llamadas"] += v["llamadas"]; o["entrada"] += v["entrada_con_cache"]; o["salida"] += v["salida"]
    return out


def resumen(r: dict, nombre: str) -> dict:
    dur = r["duracion_s"]
    t = tokens(r)
    total = sum(v["entrada"] + v["salida"] for v in t.values())
    print(f"== {nombre}: {dur / 60:.1f} min de reunión · {r['palabras']} palabras · {r.get('analisis')} análisis/turnos")
    for k, v in t.items():
        print(f"   {k:7} {v['llamadas']:>3} llamadas · entrada {v['entrada']:>7} · salida {v['salida']:>6} · total {v['entrada'] + v['salida']:>7}")
    print(f"   TOTAL {total} tokens · ajustado a una hora de reunión: {total * 3600 / dur:,.0f}".replace(",", "."))
    return {"total": total, "hora": total * 3600 / dur, "t": t}


def main() -> int:
    a = Path(sys.argv[1]) if len(sys.argv) > 1 else REAL / "resultado_tr2_pasada1.json"
    b = Path(sys.argv[2]) if len(sys.argv) > 2 else REAL / "resultado_equipo.json"
    A, B = json.loads(a.read_text(encoding="utf-8")), json.loads(b.read_text(encoding="utf-8"))
    ra, rb = resumen(A, "ANTES (" + a.name + ")"), resumen(B, "DESPUÉS (" + b.name + ")")
    print(f"== Variación: total {100 * (rb['total'] / ra['total'] - 1):+.0f} %; por hora {100 * (rb['hora'] / ra['hora'] - 1):+.0f} %")
    por_tarea = B.get("consumo_por_tarea", {})
    print("   llamadas por tarea (después):", {k: v["llamadas"] for k, v in por_tarea.items()})
    tareas = [t for t in B.get("tareas", []) if str(t.get("agente")) in ("coordinador", "funcional", "constructor", "revisor")]
    print("== Turnos por perfil:", dict(Counter(t["agente"] for t in tareas)), "· razonamiento: ver consumo.jsonl (campo razonamiento) en medicion")
    for nombre, R in (("antes", A), ("después", B)):
        tj = R.get("tarjetas_finales") or R["tarjetas"]
        print(f"== Tarjetas {nombre}: {len(tj)} · por categoría {dict(Counter(t['categoria'] for t in tj))}"
              + (f" · por perfil {dict(Counter(t.get('perfil', '—') for t in tj))}" if nombre == "después" else ""))
    defs = B.get("definiciones", [])
    print(f"== Definiciones detectadas (después): {len(defs)} · {dict(Counter(d['origen'] for d in defs))}")
    for d in sorted(defs, key=lambda x: x.get('t') or 0):
        print(f"   {d.get('minuto', '--:--')} [{d['origen']}] {d['termino']}: {d['definicion'][:110]}")
    print("== Decisiones de la lista (ventana ±%d s):" % VENTANA_S)
    for nombre, R in (("antes", A), ("después", B)):
        tj = R.get("tarjetas_finales") or R["tarjetas"]
        textos = [(t.get("t_seg"), t["categoria"], t.get("perfil", ""), t["texto"]) for t in tj] + [(d.get("t"), "definición", d["origen"], f"{d['termino']}: {d['definicion']}") for d in (R.get("definiciones") or [])]
        enc = 0
        for minuto, que, claves in DECISIONES:
            s = seg(minuto)
            hits = [x for x in textos if x[0] is not None and abs(x[0] - s) <= VENTANA_S and any(sin_acentos(k) in sin_acentos(x[3]) for k in claves)]
            enc += bool(hits)
            if nombre == "después" or not hits:
                h = hits[0] if hits else None
                print(f"   [{nombre:7}] {minuto} {que:34} " + (f"SÍ · {h[1]} {h[2]} · {int(h[0]) // 60:02d}:{int(h[0]) % 60:02d} · {h[3][:90]}" if h else "NO"))
        print(f"   [{nombre:7}] encontradas {enc} de {len(DECISIONES)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
