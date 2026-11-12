"""Política de la transcripción en la nube: cuándo usarla, reintentos, respaldo local, cortacircuitos, bloqueo, contadores y eventos.

`nube.py` es el cliente (un intento, sin política); este módulo es el ÚNICO que lo instancia y decide qué hacer con sus errores. Seguro entre hilos
(`threading.Lock` propio): el hilo del transcriptor llama a `decidir`/`transcribir`, el del gestor a `publico`/`tomar_eventos`/`tomar_lote`.

Nada de lo que sale de aquí lleva contenido: ni texto, ni prompt, ni la clave, ni la URL completa, ni el cuerpo de una respuesta (solo estado HTTP, un código
corto y cifras). La ruta de la URL puede identificar un recurso del usuario: del host solo se publica el nombre.
"""
from __future__ import annotations

import math
import random
import threading
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

from .config import DEFAULTS, dialecto_efectivo
from .nube import CAUSAS_DEFINITIVAS, ClienteNube, NubeError, tono_prueba, wav_pcm16

REINTENTOS = 1
RETRY_AFTER_MAX_S = 3.0
REINTENTO_SI_ANTES_DE_S = 10.0
BACKOFF_S = 0.5
FALLOS_PARA_ABRIR = 2
CIRCUITO_S = (60, 120, 240, 300)
RETRY_AFTER_ABRE_S = 20.0
PISTAS_RECHAZOS_MAX = 3
VOZ_MIN_S = 0.25
LOTE_ENVIOS_S = 120.0
TIMEOUT_CONEXION_S, TIMEOUT_CONEXION_SONDA_S = 5.0, 3.0
PLAZO_TROZO_S = 12.0   # plazo TOTAL de un trozo en la nube (todos sus intentos, conexión incluida); pasado, el trozo va a Whisper local
MIN_INTENTO_S = 2.0    # con menos que esto de plazo no se intenta nada más
TIMEOUT_LECTURA_BASE_S, TIMEOUT_LECTURA_POR_VOZ, TIMEOUT_LECTURA_MAX_S = 6.0, 0.5, 20.0

# Textos visibles por causa (diseno.md §2.7). `{X}` = «Esta reunión sigue transcribiéndose en este equipo.» en el aviso; en «Probar», «Revisa …».
X_REUNION = "Esta reunión sigue transcribiéndose en este equipo."
_TEXTOS_REUNION = {
    "sin_clave": "La transcripción en la nube está activada, pero no hay clave. {X}",
    "solo_local": "Modo solo local: esta reunión se transcribe en este equipo, sin la nube.",
    "clave": "La nube rechaza la clave (401). {X} Revisa la clave en Ajustes › Audio.",
    "permiso": "La clave no tiene permiso para este modelo o esta dirección (403). {X}",
    "credito": "La cuenta de la nube no tiene crédito o llegó a su límite de gasto. {X}",
    "config": "La nube no acepta la configuración (modelo, dirección o dialecto). {X} Revisa Ajustes › Audio.",
    "certificado": "No se puede verificar el certificado del servicio (¿proxy de la empresa?). {X}",
    "bloqueada_pruebas": "La nube está bloqueada en este entorno de pruebas. {X}",
    "circuito_abierto": "Sin conexión con la nube: la transcripción sigue en este equipo y se vuelve a probar en {N} s.",
    "restablecida": "Transcripción en la nube restablecida.",
    "respaldo_sin_modelo": "Falló la nube y no se pudo cargar el modelo local: parte del audio no se ha transcrito. La grabación sigue.",
}
_TEXTOS_PRUEBA = {
    "sin_clave": "No hay clave: escríbela o guárdala antes de probar.",
    "sin_clave_otra_direccion": "Para probar otra dirección, escribe también la clave.",
    "clave": "La nube rechaza la clave (401). Revisa la clave.",
    "permiso": "La clave no tiene permiso para este modelo o esta dirección (403). Revisa el modelo y la dirección.",
    "credito": "La cuenta de la nube no tiene crédito o llegó a su límite de gasto. Revisa la cuenta del proveedor.",
    "config": "La nube no acepta la configuración (modelo, dirección o dialecto). Revisa Ajustes › Audio.",
    "certificado": "No se puede verificar el certificado del servicio (¿proxy de la empresa?). Revisa la red o el proxy.",
    "bloqueada_pruebas": "Este entorno de pruebas solo admite servidores de este equipo.",
    "red": "No se pudo conectar con la nube. Revisa la dirección, la red y el proxy.",
    "tiempo": "La nube no respondió a tiempo. Revisa la red y vuelve a probar.",
    "servidor": "El servicio de la nube falló. Vuelve a probar en un rato.",
    "tasa": "La nube pide esperar (demasiadas peticiones). Vuelve a probar en un rato.",
    "audio": "La nube no aceptó el audio de prueba. Revisa el modelo y el dialecto.",
    "pistas": "La nube rechazó la petición. Revisa el modelo y el dialecto.",
    "rechazo": "La nube rechazó la petición. Revisa el modelo y el dialecto.",
}


def texto_aviso(clave: str, vuelve_s: int | None = None, con_reunion: bool = True) -> str:
    """Texto visible de una causa o evento. `con_reunion=False` quita el «{X}» (estado público)."""
    t = _TEXTOS_REUNION.get(clave, "")
    t = t.replace("{N}", str(vuelve_s if vuelve_s is not None else 60))
    return " ".join(t.replace("{X}", X_REUNION if con_reunion else "").split())


@dataclass
class Decision:
    motor: str          # "nube" | "local"
    motivo: str         # "" | "config" | "solo_local" | "sin_clave" | "bloqueada" | "circuito"
    sonda: bool = False


class NubeFallo(Exception):
    """El trozo no se pudo transcribir en la nube: quien llama lo resuelve con Whisper local."""

    def __init__(self, error: NubeError):
        super().__init__(str(error))
        self.error = error


def _host_de(url: str) -> str:
    try:
        return urlsplit(url).hostname or ""
    except ValueError:
        return ""


class MotorNube:
    def __init__(self, config, proveedor_clave=lambda: None, permitir=lambda: True, reloj=time.monotonic, dormir=time.sleep,
                 fabrica_cliente=ClienteNube, azar=random.random):
        self.config, self.proveedor_clave, self.permitir = config, proveedor_clave, permitir
        self.reloj, self.dormir, self.fabrica_cliente, self.azar = reloj, dormir, fabrica_cliente, azar
        self._lock = threading.Lock()
        self._cerrado = False   # `cerrar()`: el fin de la reunión corta lo que esté en marcha y no se sube nada más
        self._cliente = None
        self._firma = None
        self._eventos: list[dict] = []
        self._avisados: set[str] = set()   # sin_clave y solo_local: una vez por reunión (no los borra `reiniciar`)
        # estado de la política
        self._bloqueo: NubeError | None = None
        self._abierto_hasta: float | None = None   # cortacircuitos abierto hasta ese instante del reloj
        self._causa_circuito = ""
        self._nivel = 0                            # siguiente posición de CIRCUITO_S
        self._fallos_seguidos = 0
        self._abierto_desde: float | None = None   # primera apertura de la racha, para `tras_s` de «restablecida»
        self._pistas_rechazos = 0
        self._pistas_off = False
        self._ultimo_lote = {"trozos": 0, "audio_s": 0.0, "chars": 0, "fallos": 0}
        # contadores públicos
        self.trozos = 0
        self.audio_s = 0.0
        self.ms_total = 0
        self.ms_max = 0
        self.fallos = 0
        self.reintentos = 0
        self.respaldo_trozos = 0
        self.respaldo_s = 0.0
        self.silencio_trozos = 0
        self.aperturas = 0
        self.bloqueos = 0
        self.idioma_repetidos = 0
        self.pistas_reintentos = 0
        self.bytes_enviados = 0
        self.chars_prompt = 0

    # ---------------------------------------------------------------- configuración
    def _cfg(self, clave: str):
        try:
            return self.config[clave]
        except (KeyError, TypeError):
            return DEFAULTS[clave]

    def _clave(self):
        try:
            return self.proveedor_clave()
        except Exception:  # noqa: BLE001  (pedir la clave nunca rompe la transcripción)
            return None

    def _permitido(self) -> bool:
        try:
            return bool(self.permitir())
        except Exception:  # noqa: BLE001
            return False   # ante la duda, nada sale

    def _evento(self, **datos) -> None:
        self._eventos.append(datos)

    # ---------------------------------------------------------------- decisión
    def decidir(self) -> Decision:
        if self._cfg("transcripcion_motor") != "nube":
            return Decision("local", "config")
        with self._lock:
            if not self._permitido():
                if "solo_local" not in self._avisados:
                    self._avisados.add("solo_local")
                    self._evento(evento="solo_local")
                return Decision("local", "solo_local")
            if not self._clave():
                if "sin_clave" not in self._avisados:
                    self._avisados.add("sin_clave")
                    self._evento(evento="sin_clave")
                return Decision("local", "sin_clave")
            if self._bloqueo is not None:
                return Decision("local", "bloqueada")
            if self._abierto_hasta is not None:
                if self.reloj() < self._abierto_hasta:
                    return Decision("local", "circuito")
                return Decision("nube", "", sonda=True)
            return Decision("nube", "")

    # ---------------------------------------------------------------- transcribir un trozo
    def _cliente_para(self, clave: str):
        firma = (self._cfg("nube_url_base"), self._cfg("nube_modelo"), self._cfg("nube_autenticacion"), self._cfg("nube_dialecto"), clave)
        with self._lock:
            if self._cliente is None or self._firma != firma:
                if self._cliente is not None:
                    self._cerrar_cliente()
                url, modelo, auth, dialecto, _clave = firma
                self._cliente = self.fabrica_cliente(url, modelo, clave, auth, dialecto)   # el orden de `ClienteNube`
                self._firma = firma
            return self._cliente

    def _cerrar_cliente(self) -> None:
        c, self._cliente, self._firma = self._cliente, None, None
        try:
            if c is not None:
                c.cerrar()
        except Exception:  # noqa: BLE001
            pass

    def nuevo_plazo(self) -> float:
        """El instante (del reloj del motor) en que vence el plazo total de un trozo que empieza ahora. Lo comparten todos sus intentos."""
        return self.reloj() + PLAZO_TROZO_S

    def transcribir(self, wav: bytes, dur_s: float, *, idiomas, prompt, palabras_clave, rapido: bool, sonda: bool,
                    hasta: float | None = None, repeticion: bool = False):
        """Un trozo con voz hacia la nube, con reintento breve. Lanza `NubeFallo` si el trozo debe ir a Whisper local.
        `hasta`: plazo total del trozo (`nuevo_plazo()`; lo comparten el primer intento, los reintentos y la repetición por idioma): cada intento
        recibe `min(tiempo configurado, lo que queda)` y con menos de `MIN_INTENTO_S` no se intenta nada más. `repeticion`: segunda petición del mismo
        trozo (idioma); no cuenta otra vez `trozos` ni `audio_s`, y si no hay permiso o tiempo se lanza `NubeFallo` sin contar fallo."""
        if hasta is None:
            hasta = self.nuevo_plazo()
        if self._cerrado:
            raise NubeFallo(NubeError("solo_local"))
        clave = self._clave()
        if not clave:
            raise NubeFallo(NubeError("sin_clave"))   # la clave desapareció entre `decidir` y aquí: sin contar como fallo del servicio
        try:
            cliente = self._cliente_para(clave)
        except ValueError:
            e = NubeError("config")
            with self._lock:
                self._tras_fallo_del_trozo(e, sonda)
            raise NubeFallo(e) from None
        conexion_cfg = TIMEOUT_CONEXION_SONDA_S if sonda else TIMEOUT_CONEXION_S
        lectura_cfg = min(TIMEOUT_LECTURA_MAX_S, TIMEOUT_LECTURA_BASE_S + TIMEOUT_LECTURA_POR_VOZ * max(0.0, dur_s))
        con_pistas = not self._pistas_off
        reintentos_hechos = 0
        intentos = 0
        while True:
            if self._cerrado or not self._permitido():   # «Solo local» (o el cierre) a mitad del trozo: no se sube nada más
                raise NubeFallo(NubeError("solo_local"))
            resta = hasta - self.reloj()
            if resta < MIN_INTENTO_S:   # sin tiempo para otro intento: el trozo va a local
                e = NubeError("tiempo")
                if not (repeticion and intentos == 0):
                    with self._lock:
                        self.fallos += 1
                        self._tras_fallo_del_trozo(e, sonda)
                raise NubeFallo(e)
            conexion, lectura = min(conexion_cfg, resta), min(lectura_cfg, resta)
            intentos += 1
            inicio = self.reloj()
            pr, kw = (prompt or "", list(palabras_clave or ())) if con_pistas else ("", [])
            try:
                res = cliente.transcribir(wav, idiomas=list(idiomas or ()), prompt=pr, palabras_clave=kw,
                                          timeout_conexion=conexion, timeout_lectura=lectura, plazo_total=resta)
            except NubeError as e:
                dur_intento = self.reloj() - inicio
                with self._lock:
                    if e.causa == "pistas" and con_pistas:
                        self.pistas_reintentos += 1
                        self._pistas_rechazos += 1
                        if self._pistas_rechazos >= PISTAS_RECHAZOS_MAX and not self._pistas_off:
                            self._pistas_off = True
                            self._evento(evento="pistas_off", rechazos=self._pistas_rechazos)
                        con_pistas = False   # reintento al momento sin pistas: no gasta el reintento breve
                        continue
                    if e.causa == "pistas":
                        e = NubeError("rechazo", e.http, e.codigo)   # sin pistas y aun así las rechaza: es un rechazo cualquiera
                    self.fallos += 1
                    espera = e.retry_after if e.retry_after is not None else BACKOFF_S * (0.75 + 0.5 * self.azar())
                    puede = (e.reintentable and not sonda and reintentos_hechos < REINTENTOS and dur_intento < REINTENTO_SI_ANTES_DE_S
                             and (e.retry_after is None or e.retry_after <= RETRY_AFTER_MAX_S)
                             and hasta - self.reloj() - espera >= MIN_INTENTO_S)
                    if puede:
                        reintentos_hechos += 1
                        self.reintentos += 1
                    else:
                        self._tras_fallo_del_trozo(e, sonda)
                if puede:
                    self.dormir(espera)
                    continue
                raise NubeFallo(e) from None
            with self._lock:
                if not repeticion:   # la repetición por idioma es el MISMO trozo: no cuenta dos veces
                    self.trozos += 1
                    self.audio_s += dur_s
                    self.ms_total += res.ms
                self.ms_max = max(self.ms_max, res.ms)
                self.bytes_enviados += res.bytes_enviados
                if con_pistas:
                    self.chars_prompt += len(pr) + sum(len(k) for k in kw)
                self._fallos_seguidos = 0
                if self._abierto_hasta is not None:   # la sonda acertó: se cierra el cortacircuitos
                    self._abierto_hasta = None
                    self._nivel = 0
                    tras = int(max(0.0, self.reloj() - (self._abierto_desde if self._abierto_desde is not None else self.reloj())))
                    self._abierto_desde = None
                    self._evento(evento="restablecida", tras_s=tras)
            return res

    def _tras_fallo_del_trozo(self, e: NubeError, sonda: bool) -> None:
        """Con `_lock` cogido: el trozo acabó en respaldo local por `e`. Bloquea, abre el cortacircuitos o no hace nada según la causa."""
        causa = e.causa
        if causa in CAUSAS_DEFINITIVAS:
            if self._bloqueo is None:
                self.bloqueos += 1
            self._bloqueo = e
            self._evento(evento="bloqueada", causa=causa, http=e.http, codigo=e.codigo)
            return
        if causa in ("audio", "sin_clave"):
            return   # un problema de ESTE trozo: no cuenta para el cortacircuitos
        ahora = self.reloj()
        if e.retry_after is not None and e.retry_after >= RETRY_AFTER_ABRE_S and causa in ("tasa", "servidor"):
            self._abrir(ahora, min(e.retry_after, float(CIRCUITO_S[-1])), e, avanzar=False)
            return
        if sonda:
            self._abrir(ahora, float(CIRCUITO_S[self._nivel]), e, avanzar=True)
            return
        self._fallos_seguidos += 1
        if self._fallos_seguidos >= FALLOS_PARA_ABRIR:
            self._abrir(ahora, float(CIRCUITO_S[self._nivel]), e, avanzar=True)

    def _abrir(self, ahora: float, segundos: float, e: NubeError, avanzar: bool) -> None:
        self._abierto_hasta = ahora + segundos
        self._causa_circuito = e.causa
        if self._abierto_desde is None:
            self._abierto_desde = ahora
        if avanzar:
            self._nivel = min(self._nivel + 1, len(CIRCUITO_S) - 1)
        self.aperturas += 1
        self._evento(evento="circuito_abierto", causa=e.causa, http=e.http, codigo=e.codigo, fallos_seguidos=self._fallos_seguidos,
                     vuelve_s=int(segundos))

    # ---------------------------------------------------------------- anotaciones de quien llama
    def anotar_respaldo(self, dur_s: float) -> None:
        """Un trozo con el motor configurado en la nube se resolvió en local."""
        with self._lock:
            self.respaldo_trozos += 1
            self.respaldo_s += max(0.0, dur_s)

    def anotar_silencio(self) -> None:
        with self._lock:
            self.silencio_trozos += 1

    def anotar_idioma_repetido(self) -> None:
        with self._lock:
            self.idioma_repetidos += 1

    def anotar_sin_modelo(self) -> None:
        """Falló la nube y tampoco se pudo cargar Whisper local: el trozo se pierde."""
        with self._lock:
            self._evento(evento="respaldo_sin_modelo")

    def reiniciar(self) -> None:
        """Quita bloqueo, cortacircuitos y pistas apagadas; conserva los contadores. Se llama al cambiar clave, URL, modelo, autenticación o dialecto."""
        with self._lock:
            self._bloqueo = None
            self._abierto_hasta = None
            self._abierto_desde = None
            self._causa_circuito = ""
            self._nivel = 0
            self._fallos_seguidos = 0
            self._pistas_off = False
            self._pistas_rechazos = 0

    # ---------------------------------------------------------------- lo que se publica (sin contenido)
    def tomar_eventos(self) -> list[dict]:
        with self._lock:
            e, self._eventos = self._eventos, []
        return e

    def _estado(self) -> tuple[str, str, int | None]:
        """Con `_lock` cogido: (estado, causa, vuelve_en_s)."""
        if self._cfg("transcripcion_motor") != "nube":
            return "local", "", None   # volvió a local a mitad de reunión: ahora se transcribe en este equipo
        if not self._permitido():
            return "solo_local", "", None
        if not self._clave():
            return "sin_clave", "", None
        if self._bloqueo is not None:
            return "bloqueada", self._bloqueo.causa, None
        if self._abierto_hasta is not None:
            resta = self._abierto_hasta - self.reloj()
            if resta > 0:
                return "respaldo", self._causa_circuito, int(math.ceil(resta))
            return "sonda", self._causa_circuito, 0
        return "activa", "", None

    def publico(self) -> dict | None:
        """El bloque `nube` del estado de la transcripción (diseno.md §2.3). None con el motor local si en esta reunión no se ha usado nunca la nube."""
        with self._lock:
            usada = bool(self.trozos or self.fallos or self.respaldo_trozos or self.silencio_trozos or self._bloqueo or self._abierto_hasta is not None
                         or self._avisados or self._eventos)
            if self._cfg("transcripcion_motor") != "nube" and not usada:
                return None
            estado, causa, vuelve = self._estado()
            if estado == "bloqueada":
                mensaje = texto_aviso(causa, con_reunion=False)
            elif estado == "respaldo":
                mensaje = texto_aviso("circuito_abierto", vuelve, con_reunion=False)
            elif estado in ("sin_clave", "solo_local"):
                mensaje = texto_aviso(estado, con_reunion=False)
            else:
                mensaje = ""
            return {"estado": estado, "causa": causa, "mensaje": mensaje, "vuelve_en_s": vuelve,
                    "trozos": self.trozos, "audio_s": round(self.audio_s, 1),
                    "ms_medio": int(self.ms_total / self.trozos) if self.trozos else None,
                    "fallos": self.fallos, "respaldo_trozos": self.respaldo_trozos}

    def tomar_lote(self) -> dict | None:
        """Deltas desde el último lote para el registro de envíos, o None si no hubo trozos nuevos (los fallos se acumulan para el siguiente)."""
        with self._lock:
            ant = self._ultimo_lote
            d_trozos = self.trozos - ant["trozos"]
            if d_trozos <= 0:
                return None
            lote = {"trozos": d_trozos, "audio_s": round(self.audio_s - ant["audio_s"], 1), "chars": self.chars_prompt - ant["chars"],
                    "fallos": self.fallos - ant["fallos"], "ok": self.fallos - ant["fallos"] <= 0, "modelo": str(self._cfg("nube_modelo")), "host": _host_de(self._cfg("nube_url_base"))}
            self._ultimo_lote = {"trozos": self.trozos, "audio_s": self.audio_s, "chars": self.chars_prompt, "fallos": self.fallos}
            return lote

    def resumen(self) -> dict:
        """Totales para la línea de cierre `nube_resumen`."""
        with self._lock:
            return {"trozos": self.trozos, "audio_s": int(round(self.audio_s)), "ms_medio": int(self.ms_total / self.trozos) if self.trozos else 0,
                    "ms_max": self.ms_max, "fallos": self.fallos, "reintentos": self.reintentos, "respaldo_trozos": self.respaldo_trozos,
                    "respaldo_s": int(round(self.respaldo_s)), "silencio_trozos": self.silencio_trozos, "aperturas": self.aperturas,
                    "bloqueos": self.bloqueos, "idioma_repetidos": self.idioma_repetidos, "pistas_reintentos": self.pistas_reintentos,
                    "bytes_enviados": self.bytes_enviados, "kb": self.bytes_enviados // 1024,
                    "dialecto": dialecto_efectivo(str(self._cfg("nube_modelo")), str(self._cfg("nube_dialecto"))),
                    "host": _host_de(self._cfg("nube_url_base")), "modelo": str(self._cfg("nube_modelo"))}

    def cerrar(self) -> None:
        with self._lock:
            self._cerrado = True
            self._cerrar_cliente()

    # ---------------------------------------------------------------- «Probar»
    @staticmethod
    def otra_direccion(url_guardada: str, url_pedida: str) -> bool:
        """True si el host de `url_pedida` no es el de `url_guardada`: la clave guardada no se usa para probar otra dirección."""
        return _host_de(url_guardada).lower() != _host_de(url_pedida).lower()

    @staticmethod
    def respuesta_otra_direccion() -> dict:
        return {"ok": False, "causa": "sin_clave", "http": None, "mensaje": _TEXTOS_PRUEBA["sin_clave_otra_direccion"]}

    @staticmethod
    def probar(config_efectiva: dict, clave: str, fabrica_cliente=ClienteNube) -> dict:
        """Un tono sintético de 1 s con los valores dados: UNA petición, sin reintentos ni política. Es la respuesta de `POST /api/nube/probar`."""
        if not clave:
            return {"ok": False, "causa": "sin_clave", "http": None, "mensaje": _TEXTOS_PRUEBA["sin_clave"]}
        try:
            cliente = fabrica_cliente(config_efectiva["nube_url_base"], config_efectiva["nube_modelo"], clave,
                                      config_efectiva["nube_autenticacion"], config_efectiva["nube_dialecto"])
        except (ValueError, KeyError):
            return {"ok": False, "causa": "config", "http": None, "mensaje": _TEXTOS_PRUEBA["config"]}
        try:
            res = cliente.transcribir(wav_pcm16(tono_prueba()), idiomas=["es"], prompt="", palabras_clave=[],
                                      timeout_conexion=TIMEOUT_CONEXION_S, timeout_lectura=15.0)
        except NubeError as e:
            return {"ok": False, "causa": e.causa, "http": e.http, "mensaje": _TEXTOS_PRUEBA.get(e.causa, _TEXTOS_PRUEBA["rechazo"])}
        finally:
            try:
                cliente.cerrar()
            except Exception:  # noqa: BLE001
                pass
        return {"ok": True, "ms": res.ms, "modelo": config_efectiva["nube_modelo"],
                "dialecto": dialecto_efectivo(str(config_efectiva["nube_modelo"]), str(config_efectiva["nube_dialecto"])),
                "host": _host_de(config_efectiva["nube_url_base"]), "idioma": res.idioma}
