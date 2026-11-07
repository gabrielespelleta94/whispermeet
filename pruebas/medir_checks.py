"""Mide lo que añaden los checks a UNA llamada periódica (haiku, `claude -p`, texto ficticio del proyecto Beta).

    .venv\\Scripts\\python.exe pruebas\\medir_checks.py [repeticiones]

Compara la misma llamada con objetivos pero sin checks, con 6 checks y con 15 checks abiertos. Solo usa el proyecto
ficticio de pruebas; no escribe nada fuera de la memoria.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))

from apuntes import planes as PL  # noqa: E402
from apuntes.analisis import crear_modelo  # noqa: E402
from apuntes.analisis.analista import Analista  # noqa: E402
from apuntes.analisis import prompts as P  # noqa: E402
from apuntes.config import Config  # noqa: E402
from apuntes.consumo import Consumo  # noqa: E402
from apuntes.rutas import Guardian  # noqa: E402
from apuntes.simulador import cargar  # noqa: E402
from apuntes.texto import formatear_lineas, limpiar_transcripcion  # noqa: E402

EXTRA = ["Confirmar quién da acceso al entorno de pruebas", "Fecha de entrega del catálogo de hoteles", "Responsable de la carga nocturna",
         "Alertas si falla la carga", "Histórico disponible desde la fecha acordada", "Tabla de tarifas en esquema separado",
         "Permisos de lectura para el consultor", "Calendario de la siguiente sesión", "Contacto del equipo de tarifas"]


def main() -> int:
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    plan = PL.normalizar_plan(json.loads((AQUI / "planes-beta" / "beta.json").read_text(encoding="utf-8")))
    ses = PL.sesion_de(plan, "S1")
    objetivos = PL.objetivos_iniciales(ses)
    digest = (AQUI / "compartidos" / "Proyecto Compartido Beta" / "00. CONTEXTO (IA)" / "02-alcance.md").read_text(encoding="utf-8")[:4000]
    lineas = [l for l in cargar(AQUI / "reunion-datos-beta.txt") if l.t < 300]
    nuevo = formatear_lineas(limpiar_transcripcion([{"t": l.t, "fuente": l.fuente, "texto": l.texto} for l in lineas]))
    base = [{"id": f"c{i}", "texto": t} for i, t in enumerate(ses["checks"] + EXTRA)]
    cfg = Config(AQUI / "no-existe.json")
    g = Guardian(AQUI, AQUI / "salida" / "b", AQUI / "salida" / "c")
    filas = []
    for nombre, n in (("sin checks", 0), ("6 checks", 6), ("15 checks", 15)):
        for r in range(reps):
            consumo = Consumo(None)
            an = Analista(crear_modelo(cfg), cfg, consumo, g, "medida")
            res = an.periodico(digest, "", [], "", nuevo, objetivos, base[:n])
            tot = consumo.resumen()["total"]
            entrada = tot["entrada"] + tot["cache_creacion"] + tot["cache_lectura"]
            sis = len(P.sistema_periodico(2500, True, bool(n)))
            filas.append((nombre, r + 1, entrada, tot["salida"], sis, len(res["checks"])))
            print(f"{nombre:11s} rep {r + 1}: entrada {entrada:6d}  salida {tot['salida']:5d}  system {sis} car  marcas {len(res['checks'])}", flush=True)
    for nombre in ("sin checks", "6 checks", "15 checks"):
        e = [f[2] for f in filas if f[0] == nombre]
        s = [f[3] for f in filas if f[0] == nombre]
        print(f"MEDIA {nombre:11s} entrada {sum(e) / len(e):8.0f}  salida {sum(s) / len(s):6.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
