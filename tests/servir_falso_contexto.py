"""Arranca WhisperMeet con MODELO FALSO, VENTANA NATIVA FALSA (el «selector de carpetas» devuelve una carpeta fija, sin diálogo de
Windows) y MICRO FALSO (el dictado «oye» frases de ejemplo), para ver y probar a mano el selector de carpetas, «Nueva carpeta» y el
«Contexto de la reunión» sin licencia, sin micro y sin tocar OneDrive.

    .venv\\Scripts\\python.exe tests\\servir_falso_contexto.py --carpeta-falsa <carpeta existente> [--retardo 2] -- \\
        --sin-ventana --raiz <raiz de proyectos de prueba> --cache <carpeta> --consumo <fichero.jsonl> --config <fichero.json> \\
        [--simular pruebas\\reunion-ficticia.txt] [--planes <carpeta>] [--sesiones <carpeta>] [--checks <carpeta>]

Es `pruebas\\servir_modelo_falso.py` más tres piezas: la respuesta de la tarea `contexto_reunion` (si el texto lleva la palabra FALLA, el
modelo falso falla, para ver cómo se muestra el error), la ventana falsa y el micro falso. Todo lo que va tras `--` se pasa a app.py.
Solo datos ficticios.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "pruebas"))
# Antes de importar la app: su registro, a un fichero temporal y nunca a datos/apuntes.log (pytest ya lo deja puesto; esto cubre el uso a mano).
os.environ.setdefault("WHISPERMEET_REGISTRO", str(Path(tempfile.gettempdir()) / "whispermeet-pruebas.log"))
os.environ.setdefault("WHISPERMEET_SIN_PRIORIDAD", "1")   # una reunión de prueba no sube la prioridad del servidor

import app as aplicacion  # noqa: E402
import servir_modelo_falso as base  # noqa: E402
from apuntes.analisis import ErrorAnalisis, Respuesta, Uso  # noqa: E402
from apuntes.dictado import Dictado  # noqa: E402

FRASES = ["Queremos cerrar el alcance de la fase uno.", "Hay dudas sobre la integración con SAP.", "Necesitamos decidir la fecha del piloto con el cliente.",
          "También hay que revisar el catálogo de hoteles."]


class ModeloFalsoContexto(base.FalsoLento):
    def completar(self, sistema, usuario, modelo, esfuerzo="", timeout_s=240, sin_razonamiento=False):
        if "preparar el contexto de una reunión" not in sistema:
            return super().completar(sistema, usuario, modelo, esfuerzo, timeout_s, sin_razonamiento)
        time.sleep(self.retardo)
        texto = usuario.split("<<<DATOS texto_del_usuario>>>", 1)[-1].split("<<<FIN>>>", 1)[0].strip()
        if "FALLA" in texto:
            raise ErrorAnalisis("otro", "El análisis falló: fallo simulado por el modelo falso.", transitorio=True)
        frases = [f.strip() for f in re.split(r"(?<=[.!?])\s+", texto) if f.strip()][:4] or [texto[:80]]
        salida = {"contexto": "**Resumen (modelo falso)**\n" + "\n".join(f"- {f}" for f in frases),
                  "objetivos": [("Aclarar: " + f.rstrip(".!?"))[:100] for f in frases[:3]]}
        return Respuesta(json.dumps(salida, ensure_ascii=False), [Uso(modelo, 900, 200)], int(self.retardo * 1000))


class VentanaFalsa:
    """Hace de `Ventana`: el selector devuelve siempre la carpeta pasada en --carpeta-falsa (sin abrir ningún diálogo)."""
    modo_activo = False

    def __init__(self, carpeta: str):
        self.carpeta = carpeta

    def elegir_carpeta(self, inicial: str = ""):
        print(f"[ventana falsa] selector de carpetas pedido; empezaría en: {inicial or '(lo decide Windows)'}", flush=True)
        time.sleep(0.4)
        return self.carpeta

    def estado_modo(self):
        return {"activo": False, "opacidad": 100, "opacidad_soportada": False}

    def entrar(self, *a, **k):
        raise ValueError("El Modo reunión no está disponible con la ventana falsa.")

    actualizar = salir = entrar

    def fijar_opacidad(self, *a, **k):
        return False


class CapturaFalsa:
    """Cada 1,3 s entrega un enunciado de silencio (en memoria): el transcriptor falso lo convierte en una frase de ejemplo."""
    def __init__(self, reloj, on_enunciado, on_nivel):
        self.on_enunciado, self.on_nivel, self.errores, self.pausada = on_enunciado, on_nivel, {}, False
        self._parar = threading.Event()

    def iniciar(self):
        time.sleep(0.5)
        threading.Thread(target=self._bucle, daemon=True).start()

    def _bucle(self):
        while not self._parar.wait(1.3):
            if not self.pausada:
                self.on_nivel("yo", -20.0)
                self.on_enunciado("yo", np.zeros(16000, np.float32), 0.0)

    def detener(self):
        self._parar.set()


class TranscriptorFalso:
    def __init__(self, on_texto):
        self.on_texto, self.estado, self.error, self.n = on_texto, "listo", "", 0

    def iniciar(self):
        pass

    def encolar(self, fuente, audio, t0):
        self.on_texto(fuente, t0, FRASES[self.n % len(FRASES)])
        self.n += 1

    def vacio(self):
        return True

    def detener(self):
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--retardo", type=float, default=2.0)
    ap.add_argument("--carpeta-falsa", required=True, help="carpeta (existente) que devolverá el selector de carpetas falso")
    args, resto = ap.parse_known_args()
    if resto and resto[0] == "--":
        resto = resto[1:]
    for obligatoria in ("--consumo", "--cache", "--config"):
        if obligatoria not in resto:
            ap.error(f"con el modelo falso hay que pasar {obligatoria} tras el «--» (nunca los reales)")
    if not Path(args.carpeta_falsa).is_dir():
        ap.error("--carpeta-falsa debe ser una carpeta existente")
    ventana = VentanaFalsa(str(Path(args.carpeta_falsa).resolve()))
    aplicacion.crear_modelo = lambda cfg: ModeloFalsoContexto(args.retardo, 0)
    crear_original = aplicacion.crear_app

    def crear_app(*a, **k):
        gestor, cfg = a[0], a[2]
        gestor.dictado = Dictado(cfg, gestor._emitir, bloqueo=gestor._bloqueo_dictado,
                                 fabrica_captura=CapturaFalsa, fabrica_transcriptor=TranscriptorFalso)
        a = list(a)
        a[7] = lambda: ventana
        return crear_original(*a, **k)
    aplicacion.crear_app = crear_app
    return aplicacion.main(resto)


if __name__ == "__main__":
    sys.exit(main())
