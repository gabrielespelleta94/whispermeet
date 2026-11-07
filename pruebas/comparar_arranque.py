"""Compara UNA llamada periódica con arranque limpio frente a un `claude -p` por defecto (texto ficticio).

    .venv\\Scripts\\python.exe pruebas\\comparar_arranque.py
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from apuntes.analisis import claude_cli as C  # noqa: E402
from apuntes.analisis import prompts as P  # noqa: E402
from apuntes.config import CLAUDE_CWD  # noqa: E402
from apuntes.simulador import cargar  # noqa: E402
from apuntes.texto import formatear_lineas, limpiar_transcripcion  # noqa: E402

AQUI = Path(__file__).resolve().parent
lineas = [l for l in cargar(AQUI / "reunion-ficticia.txt") if l.t < 300]
nuevo = formatear_lineas(limpiar_transcripcion(lineas))
digest = ("[02-alcance.md] Entra: reservas de grupos, calendario de disponibilidad, informe semanal Power BI, 3 usuarios por hotel. "
          "No entra: integración SAP (fase 2), app móvil. [04-plan.md] Piloto 20/01/2027 con 2 hoteles; go live 15/03/2027.")
sistema = P.sistema_periodico(2500)
usuario = P.usuario_periodico(digest, "", [], "", nuevo)
CLAUDE_CWD.mkdir(parents=True, exist_ok=True)


def lanzar(cmd, entrada, sin_razonamiento=False):
    p = subprocess.run(cmd, input=entrada, capture_output=True, text=True, encoding="utf-8", cwd=str(CLAUDE_CWD),
                       env=C.entorno_limpio(sin_razonamiento=sin_razonamiento), timeout=300)
    d = json.loads(p.stdout)
    u = d["usage"]
    return {"entrada": u["input_tokens"], "cache_creacion": u["cache_creation_input_tokens"],
            "cache_lectura": u["cache_read_input_tokens"], "salida": u["output_tokens"],
            "coste_lista_usd": round(d.get("total_cost_usd", 0), 4), "ms": d.get("duration_ms"),
            "modelo": list(d.get("modelUsage", {}))}


exe = C.ClaudeCLI().exe
limpio = lanzar(C.construir_comando(exe, sistema, "haiku", "low"), usuario, sin_razonamiento=True)
defecto = lanzar([exe, "-p", "--output-format", "json", "--model", "haiku"], sistema + "\n\n" + usuario)
for nombre, r in (("arranque limpio", limpio), ("claude -p por defecto", defecto)):
    total = r["entrada"] + r["cache_creacion"] + r["cache_lectura"]
    print(f"{nombre:24} entrada_total={total:>6}  (nueva={r['entrada']}, cache_crea={r['cache_creacion']}, cache_lee={r['cache_lectura']})"
          f"  salida={r['salida']:>4}  coste_lista=${r['coste_lista_usd']}  ms={r['ms']}")
print("tamaño del prompt propio (caracteres):", len(sistema) + len(usuario))
