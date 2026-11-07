"""Arranca Apuntes con un MODELO FALSO (sin `claude -p`, sin red) y latencia configurable, para ver y medir la interfaz.

    .venv\\Scripts\\python.exe pruebas\\servir_modelo_falso.py --retardo 4 --limite-desde 3 -- --simular pruebas\\reunion-ficticia.txt --sin-ventana ...

Todo lo que va tras `--` se pasa a app.py. `--retardo S`: segundos que tarda cada llamada falsa (para ver trabajar a los nodos).
`--limite-desde N`: a partir de la llamada periódica N lanza «límite del plan» (criterio 12). Solo datos ficticios.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

import app as aplicacion  # noqa: E402
from apuntes.analisis import ErrorAnalisis, ModeloLLM, Respuesta, Uso  # noqa: E402


class FalsoLento(ModeloLLM):
    def __init__(self, retardo: float, limite_desde: int):
        self.retardo, self.limite_desde, self.n_periodicos = retardo, limite_desde, 0

    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False, web=False):
        time.sleep(self.retardo)
        uso = [Uso(modelo, 3000, 800)]
        if "acaba de hacer la pregunta" in sistema:   # el asesor en directo: respuesta sugerida a una pregunta del cliente (datos ficticios)
            q = usuario.split("<<<DATOS pregunta>>>")[-1].lower()
            if "cuesta" in q or "cuánto" in q:
                d = {"v": ["No puedo confirmar ese importe ahora: lo valido con el equipo y te respondo hoy.", "Lo que sí está acordado es el alcance de la primera fase."], "c": "media", "f": [{"s": "F1"}], "b": True}
            elif "usuarios" in q:
                d = {"v": ["Hasta tres usuarios por hotel entran en la primera fase.", "Más usuarios serían un cambio de alcance que habría que estimar."], "c": "alta", "f": [{"s": "F1"}], "b": True}
            elif "comprometéis" in q or "catálogo" in q:
                d = {"v": ["El catálogo de hoteles depende de que el cliente lo entregue a tiempo: es un riesgo del plan.", "Propongo fijar una fecha de entrega y revisarla en el próximo seguimiento."], "c": "media", "f": [{"s": "F1"}], "b": True}
            else:
                d = {"v": ["No hay base en tus fuentes: propón comprobarlo y volver con la respuesta"], "c": "baja", "f": [], "b": False}
            if "sonnet" in modelo and d["b"]:
                d["v"] = [d["v"][0] + " (afinado)"] + d["v"][1:]
            return Respuesta(json.dumps(d), uso, int(self.retardo * 1000))
        if "estratega comercial" in sistema:
            self.n_consejos = getattr(self, "n_consejos", 0) + 1
            k = self.n_consejos
            lote = [[{"t": "pregunta", "a": "Pregunta quién valida el catálogo de hoteles antes del piloto", "p": "Sin ese fichero el piloto del veinte de enero no es firme", "m": "03:10"},
                     {"t": "cierre", "a": "Propón fijar hoy una fecha de entrega del catálogo con el cliente", "p": "Hay prisa por cerrar la oferta y el plazo preocupa", "m": "03:00"}],
                    [{"t": "oportunidad", "a": "Ofrece la segunda fase con el informe de ocupación por hotel", "p": "El cliente la pidió de forma espontánea", "m": "06:00"}]]
            return Respuesta(json.dumps({"k": lote[min(k - 1, len(lote) - 1)]}), uso, int(self.retardo * 1000))
        if "PROFUNDIZAR" in sistema:
            d = {"v": ["Primero confirma con el equipo qué incluye exactamente la primera fase.", "Después, si piden más usuarios, plantéalo como cambio de alcance con estimación.", "Pregunta de vuelta: ¿cuántos usuarios necesita realmente cada hotel?"],
                 "c": "media", "f": [{"s": "F1"}], "b": True}
            if web:
                d["w"] = [{"u": "https://learn.microsoft.com/es-es/fabric/", "t": "Documentación de Microsoft Fabric"}]
            return Respuesta(json.dumps(d), uso, int(self.retardo * 1000))
        if "pulir el resumen final" in sistema:
            return Respuesta(json.dumps({"resumen": "## Resumen\nEl piloto se mantiene el 20 de enero con dos hoteles; la estimación de SAP queda pendiente."}), uso, int(self.retardo * 1000))
        if "compactar el contexto" in sistema:
            return Respuesta(json.dumps({"pm": "[04-calendario.md] Piloto el 20/01 con dos hoteles; estimación de SAP pendiente.",
                                         "fun": "[02-alcance.md] Cupo: máximo de habitaciones sin pasar por Revenue. SAP fuera de la fase 1.",
                                         "tec": "[03-datos.md] El catálogo de hoteles llega por CSV; SAP fuera de alcance.",
                                         "rev": "[02-alcance.md] No entra: SAP (fase 2). [04] Piloto 20/01.",
                                         "checks": ["Confirmar el alcance con el cliente", "Pedir el catálogo de hoteles al cliente"],
                                         "objetivos": ["Cerrar el alcance de SAP", "Acordar la fecha del piloto"]}), uso, int(self.retardo * 1000))
        if "compañero del equipo" in sistema:   # un turno de perfil del equipo (datos ficticios, distintos en cada turno)
            self.n_turnos = getattr(self, "n_turnos", 0) + 1
            k = self.n_turnos
            if self.limite_desde and k >= self.limite_desde:
                raise ErrorAnalisis("limite", "Has alcanzado el límite de tu plan de Claude.")
            if "coordinador del proyecto" in sistema:
                d = {"t": [{"k": "decision", "x": f"El piloto sigue el 20 de enero (turno {k})", "m": "01:55"},
                           {"k": "pendiente", "x": f"Enviar el fichero de tarifas (turno {k})", "m": "04:05", "r": "Ana", "f": "el viernes"}], "e": "Calendario del piloto"}
            elif "analista funcional" in sistema:
                d = {"d": [{"n": "Cupo", "x": "Número máximo de habitaciones que se reservan sin pasar por Revenue", "m": "03:10"}],
                     "t": [{"k": "regla", "x": f"Si se supera el cupo, la solicitud pasa a Revenue (turno {k})", "m": "03:40"}], "e": "Reglas del cupo"}
            elif "constructor técnico" in sistema:
                d = {"t": [{"k": "riesgo", "x": f"El catálogo de hoteles no ha llegado (turno {k})", "m": "05:40", "s": "Catálogo CSV"},
                           {"k": "idea", "x": f"Empezar con un solo hotel (turno {k})", "m": "03:10"}], "e": "Catálogo de hoteles"}
            else:
                d = {"c": [{"x": "Meter SAP en fase 1", "m": "02:10", "q": "02-alcance.md: integración con SAP fuera de alcance"}] if k <= 4 else [],
                     "o": [{"i": 1, "e": "p", "m": "01:30"}], "k": []}
            return Respuesta(json.dumps(d), uso, int(self.retardo * 1000))
        if "análisis incremental" in sistema:
            self.n_periodicos += 1
            if self.limite_desde and self.n_periodicos >= self.limite_desde:
                raise ErrorAnalisis("limite", "Has alcanzado el límite de tu plan de Claude.")
            k = self.n_periodicos
            return Respuesta(json.dumps({
                "resumen": f"Tramo {k}: se habló de SAP y del piloto.",
                "e": ["Alcance de SAP", "Calendario del piloto", "Catálogo de hoteles"][(k - 1) % 3],
                "t": [{"k": "decision", "x": f"El piloto sigue el 20 de enero (tramo {k})", "m": "01:55"},
                      {"k": "pendiente", "x": f"Estimar SAP (tramo {k})", "m": "04:05", "r": "Luis"},
                      {"k": "riesgo", "x": f"El catálogo de hoteles no ha llegado (tramo {k})", "m": "05:40"},
                      {"k": "idea", "x": f"Empezar con un solo hotel (tramo {k})", "m": "03:10"}],
                "c": [{"x": "Meter SAP en fase 1", "m": "02:10", "q": "02-alcance.md: integración con SAP fuera de alcance"}] if k == 1 else [],
                "o": [{"i": 1, "e": "c" if k > 1 else "p", "m": "01:30"}], "k": []}), uso, int(self.retardo * 1000))
        if "responder a UNA pregunta" in sistema:
            return Respuesta(json.dumps({"r": "Se acordó dejar SAP fuera de la fase 1 y estimarlo aparte.", "c": [{"m": "01:55", "f": "02-alcance.md"}], "b": True}), uso, int(self.retardo * 1000))
        if "verificar candidatas" in sistema:
            return Respuesta(json.dumps({"v": [{"i": 0, "ok": True, "x": "Contradice el alcance acordado"}]}), uso, int(self.retardo * 1000))
        if "cierre de la reunión" in sistema:
            return Respuesta(json.dumps({"resumen": "## Resumen\nSe decidió mantener el piloto el 20 de enero. SAP queda pendiente de estimar.",
                                         "cambios": [{"f": "02-alcance.md", "tipo": "anadir", "sec": "Cambios de alcance",
                                                      "nuevo": "| 2026-11-03 | Se estima SAP | Comité | Reunión |", "motivo": "Decisión de alcance", "m": "04:05"}]}), uso, int(self.retardo * 1000))
        raise AssertionError("prompt inesperado")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retardo", type=float, default=3.0)
    ap.add_argument("--limite-desde", type=int, default=0)
    args, resto = ap.parse_known_args()
    if resto and resto[0] == "--":
        resto = resto[1:]
    if "--consumo" not in resto:   # las llamadas falsas no pueden acabar en el registro de consumo real
        ap.error("con el modelo falso hay que pasar --consumo <fichero.jsonl> tras el «--» (nunca datos/consumo.jsonl)")
    if "--cache" not in resto:   # un digest falso en la caché real contaminaría la siguiente pasada con el modelo de verdad
        ap.error("con el modelo falso hay que pasar --cache <carpeta> tras el «--» (nunca la caché real)")
    aplicacion.crear_modelo = lambda cfg: FalsoLento(args.retardo, args.limite_desde)
    return aplicacion.main(resto)


if __name__ == "__main__":
    sys.exit(main())
