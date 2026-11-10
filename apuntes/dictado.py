"""Dictado del «Contexto de la reunión» por el micrófono (inicio de la app, antes de empezar la reunión).

Reutiliza la captura del micro (`audio.Captura`, SOLO la fuente «yo») y `faster-whisper` (`transcripcion.Transcriptor`) que ya usa la
reunión. Reglas:
- El audio nunca va a disco: son los mismos buffers en memoria de la reunión, que el transcriptor descarta al transcribir.
- Solo el texto sale de aquí (eventos `dictado` por el WebSocket y la respuesta de «parar»); el usuario lo revisa en la caja de texto.
- No hay llamadas al modelo de lenguaje: el dictado es local. Con una reunión en marcha el dictado no está disponible (comparten micro
  y modelo de transcripción) y, si el usuario empieza una reunión con el dictado abierto, el dictado se cancela.
"""
from __future__ import annotations

import threading
import time

from .audio import Captura
from .config import validar_idioma
from .transcripcion import Transcriptor, prompt_tema

MAX_DICTADO_S = 10 * 60          # un dictado de contexto no pasa de 10 minutos
ESPERA_VACIAR_S = 120            # al parar, lo que falta por transcribir (incluida la primera carga del modelo) se espera hasta este tope
MAX_CHARS = 8000


class _TranscriptorDictado(Transcriptor):
    """El modelo de Whisper se carga una vez y se reutiliza entre dictados (cargarlo cuesta segundos)."""
    _modelo_compartido = None   # (nombre del modelo, modelo)
    tope_retraso_s = None       # un dictado es un texto seguido: sus tramos van en orden de llegada y ninguno se deja para después
    _candado = threading.Lock()

    def cargar_modelo(self):
        with self._candado:
            nombre = self.config["whisper_modelo"]
            if _TranscriptorDictado._modelo_compartido is None or _TranscriptorDictado._modelo_compartido[0] != nombre:
                _TranscriptorDictado._modelo_compartido = (nombre, super().cargar_modelo())
            return _TranscriptorDictado._modelo_compartido[1]


class Dictado:
    def __init__(self, cfg, emitir, bloqueo=None, fabrica_captura=None, fabrica_transcriptor=None, prioridad=None):
        """`emitir(dict)`: eventos por el WebSocket (seguro desde cualquier hilo). `bloqueo()`: motivo (texto) por el que ahora no se puede
        dictar, o None. Las fábricas permiten sustituir micro y transcriptor (tests y pruebas con micro falso). `prioridad(activa)`: el Gestor sube
        la prioridad del proceso mientras se dicta y la baja al cerrar las piezas (se llama una vez al subir y una al bajar)."""
        self.cfg, self._emitir, self._bloqueo = cfg, emitir, bloqueo or (lambda: None)
        self._prioridad, self._prioridad_subida = prioridad, False
        self._fabrica_captura = fabrica_captura or self._captura_real
        self._fabrica_transcriptor = fabrica_transcriptor or self._transcriptor_real
        self._lock = threading.Lock()
        self.estado = "parado"            # parado | iniciando | dictando | cerrando
        self.error = ""
        self.idioma = validar_idioma(cfg["idioma"], defecto="auto")   # idioma del dictado en curso (auto | es | ca): el mismo que el de la reunión
        self.fragmentos: list[dict] = []  # [{n, texto}], solo texto
        self._captura = None
        self._transcriptor = None
        self._t0 = 0.0
        self._cancelado = False

    # ---------------------------------------------------------------- piezas reales (sustituibles)
    def _captura_real(self, reloj, on_enunciado, on_nivel):
        return Captura(reloj, on_enunciado, on_nivel, self.cfg["dispositivo_mic"], None, fuentes=("yo",), vaciar_al_parar=True)

    def _transcriptor_real(self, on_texto):
        t = _TranscriptorDictado(self.cfg, on_texto)
        t.idioma = self.idioma
        t.prompt = "Dictado de notas para preparar una reunión de trabajo."
        t.prompt_ca = "Dictat de notes per preparar una reunió de treball."
        t.prompt_en = "Dictation of notes to prepare a work meeting."
        t.vocabulario = list(self.cfg["vocabulario_transcripcion"])
        return t

    # ---------------------------------------------------------------- estado
    @property
    def activo(self) -> bool:
        return self.estado != "parado"

    def publico(self) -> dict:
        return {"estado": self.estado, "error": self.error, "palabras": sum(len(f["texto"].split()) for f in self.fragmentos),
                "fragmentos": [dict(f) for f in self.fragmentos]}

    def _avisar(self, **datos) -> None:
        try:
            self._emitir({"tipo": "dictado", **datos})
        except Exception:  # noqa: BLE001  (un aviso nunca rompe el dictado)
            pass

    def _estado(self, estado: str, error: str = "") -> None:
        self.estado, self.error = estado, error
        self._avisar(fase="estado", estado=estado, error=error)

    # ---------------------------------------------------------------- texto que llega del transcriptor (hilo del transcriptor)
    def _on_texto(self, fuente: str, t0: float, texto: str) -> None:
        texto = " ".join((texto or "").split())
        if not texto or self._cancelado:
            return
        with self._lock:
            if sum(len(f["texto"]) for f in self.fragmentos) + len(texto) > MAX_CHARS:
                return
            f = {"n": len(self.fragmentos) + 1, "texto": texto}
            self.fragmentos.append(f)
        self._avisar(fase="texto", **f)

    def _on_enunciado(self, fuente: str, audio, t0: float) -> None:
        if self._transcriptor is not None and not self._cancelado:
            self._transcriptor.encolar(fuente, audio, t0)

    def _on_nivel(self, fuente: str, db: float) -> None:
        self._avisar(fase="nivel", db=round(db, 1))

    # ---------------------------------------------------------------- control (se llaman desde un hilo de trabajo, no desde el bucle de eventos)
    def iniciar(self, idioma: str | None = None) -> dict:
        """`idioma`: auto | es | ca (el «Idioma de la reunión» del inicio); sin valor, el de la configuración. ValueError si no es válido."""
        idioma = validar_idioma(self.cfg["idioma"] if idioma is None else idioma)
        motivo = self._bloqueo()
        if motivo:
            raise ValueError(motivo)
        with self._lock:
            if self.estado != "parado":
                raise ValueError("Ya hay un dictado en curso.")
            self.estado, self.error, self.fragmentos, self._cancelado = "iniciando", "", [], False
            self.idioma = idioma
        self._avisar(fase="estado", estado="iniciando", error="")
        self._t0 = time.monotonic()
        try:
            self._transcriptor = self._fabrica_transcriptor(self._on_texto)
            self._transcriptor.iniciar()
            cap = self._captura = self._fabrica_captura(lambda: time.monotonic() - self._t0, self._on_enunciado, self._on_nivel)
            cap.iniciar()
            fallo = dict(getattr(cap, "errores", {}) or {}).get("yo")
            if fallo:
                raise RuntimeError(f"no se pudo abrir el micrófono: {fallo}")
            if not self._cancelado:
                self._cambiar_prioridad(True)
            if self._cancelado:   # `cancelar` cerró las piezas mientras se iniciaba: no se sigue y la prioridad no queda subida
                self._cerrar_piezas()
                return self.publico()
        except Exception as e:  # noqa: BLE001
            self._cerrar_piezas()
            mensaje = f"No se pudo empezar el dictado: {e}"
            self._estado("parado", mensaje)
            raise ValueError(mensaje)
        self._estado("dictando")
        threading.Thread(target=self._tope, args=(self._t0,), daemon=True, name="dictado-tope").start()
        return self.publico()

    def _tope(self, t0: float) -> None:
        """Seguridad: un micro abierto por olvido deja de escuchar a los 10 minutos (el texto dictado queda para recogerlo con «parar»)."""
        while self.estado == "dictando" and self._t0 == t0:
            if time.monotonic() - t0 > MAX_DICTADO_S:
                if self._captura is not None:
                    self._captura.pausada = True   # deja de recoger voz; «Parar» cierra el micro y entrega lo dictado
                self._cambiar_prioridad(False)   # el dictado sigue abierto pero ya no captura: no hay motivo para la prioridad alta (no se reanuda)
                self._avisar(fase="estado", estado="dictando", error="Se dejó de escuchar a los 10 minutos; pulsa «Parar» para recoger el texto.")
                return
            time.sleep(1.0)

    def detener(self) -> dict:
        """Cierra el micro, espera a que se transcriba lo que quedaba y devuelve el texto dictado. Idempotente."""
        with self._lock:
            if self.estado in ("parado", "cerrando"):
                return self.publico() | {"texto": self.texto()}
            self.estado = "cerrando"
        self._avisar(fase="estado", estado="cerrando", error="")
        try:
            if self._captura is not None:
                self._captura.detener()
            tr = self._transcriptor
            if tr is not None:
                fin = time.time() + ESPERA_VACIAR_S
                while not tr.vacio() and time.time() < fin and tr.estado != "error":
                    time.sleep(0.2)
                if tr.estado == "error" and not self.fragmentos:
                    self.error = tr.error
        finally:
            self._cerrar_piezas()
        self._estado("parado", self.error)
        return self.publico() | {"texto": self.texto()}

    def cancelar(self) -> None:
        """Descarta el dictado (empieza una reunión o se cierra la app): sin esperar y sin conservar el texto."""
        self._cancelado = True
        self._cerrar_piezas()
        if self.estado != "parado":
            self._estado("parado")
        self.fragmentos = []

    def _cambiar_prioridad(self, activa: bool) -> None:
        """Avisa al Gestor (si lo hay) de que empieza o acaba la captura del dictado; solo una vez por sentido y nunca lanza."""
        if self._prioridad is None or self._prioridad_subida == activa:
            return
        self._prioridad_subida = activa
        try:
            self._prioridad(activa)
        except Exception:  # noqa: BLE001  (un favor al rendimiento: nunca rompe el dictado)
            pass

    def _cerrar_piezas(self) -> None:
        cap, tr, self._captura, self._transcriptor = self._captura, self._transcriptor, None, None
        for pieza, metodo in ((cap, "detener"), (tr, "detener")):
            if pieza is not None:
                try:
                    getattr(pieza, metodo)()
                except Exception:  # noqa: BLE001
                    pass
        self._cambiar_prioridad(False)

    def texto(self) -> str:
        return " ".join(f["texto"] for f in self.fragmentos)
