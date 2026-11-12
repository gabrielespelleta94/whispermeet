"""Cliente de la transcripción en la nube (protocolo compatible con OpenAI: `POST {url_base}/audio/transcriptions`, multipart). Sin política.

Este módulo es el ÚNICO que abre una conexión hacia la nube (y solo `motor_nube.MotorNube` lo instancia). Hace UN intento por llamada y lanza
`NubeError`; reintentos, respaldo local y cortacircuitos son de `motor_nube.py`.

Reglas que no se rompen aquí:
- Biblioteca estándar (`http.client`, conexión persistente: ahorra el TLS en cada trozo). Respeta el proxy del sistema (`urllib.request.getproxies`) con
  `set_tunnel`; no hay soporte de PAC ni de proxy con autenticación.
- El audio viaja como WAV PCM16 mono de 16 kHz en memoria (`io.BytesIO`): nunca a disco.
- El cuerpo de un error del servicio NO se guarda, ni se muestra ni se registra (un 401 repite parte de la clave en `message`): de él solo salen el estado
  HTTP y `error.code`, y este solo si casa con `[a-z0-9_-]{1,60}`. `NubeError` no lleva cuerpo ni cabeceras.
- Guarda de pruebas `WHISPERMEET_NUBE_SOLO_LOOPBACK`: con ella puesta, todo host que no sea de bucle local se rechaza antes de abrir un socket y no se usa proxy.
"""
from __future__ import annotations

import http.client
import io
import json
import math
import os
import re
import secrets
import socket
import ssl
import threading
import time
import urllib.request
import wave
from dataclasses import dataclass
from urllib.parse import urlsplit

import numpy as np

from .config import dialecto_efectivo, validar_autenticacion, validar_dialecto, validar_modelo_nube, validar_url_nube

CAUSAS_DEFINITIVAS = {"clave", "permiso", "credito", "config", "certificado", "bloqueada_pruebas"}
CAUSAS_REINTENTABLES = {"red", "tiempo", "servidor", "tasa"}
CAUSAS_DEL_TROZO = {"audio", "rechazo", "pistas"}   # no bloquean; "rechazo" cuenta para el cortacircuitos, "audio" no
ENV_SOLO_LOOPBACK = "WHISPERMEET_NUBE_SOLO_LOOPBACK"
HOSTS_LOOPBACK = {"127.0.0.1", "localhost", "::1"}
MAX_RESPUESTA_BYTES = 1_000_000
SR = 16000
_RE_CODIGO = re.compile(r"[a-z0-9_-]{1,60}")
_PARAMS_PISTAS = {"prompt", "keywords", "keywords[]"}
_PARAMS_CONFIG = {"model", "language", "languages", "languages[]", "response_format", "temperature"}
_MARCAS_CREDITO = ("quota", "credit", "spend_limit", "usage_limit", "billing")
_NOMBRES_IDIOMA = {"spanish": "es", "catalan": "ca", "english": "en", "castilian": "es", "valencian": "ca"}


class NubeError(Exception):
    """Fallo de una llamada a la nube. `str()` solo lleva la causa, el estado HTTP y el código: nunca el cuerpo ni las cabeceras."""

    def __init__(self, causa: str, http: int | None = None, codigo: str = "", retry_after: float | None = None):
        self.causa, self.http, self.retry_after = causa, http, retry_after
        self.codigo = codigo if isinstance(codigo, str) and _RE_CODIGO.fullmatch(codigo) else ""
        super().__init__(f"nube causa={self.causa} http={self.http or '-'} codigo={self.codigo or '-'}")

    @property
    def definitiva(self) -> bool:
        return self.causa in CAUSAS_DEFINITIVAS

    @property
    def reintentable(self) -> bool:
        return self.causa in CAUSAS_REINTENTABLES


@dataclass
class ResultadoNube:
    texto: str
    idioma: str | None                       # "es" | "ca" | "en" | otro código | None
    segmentos: list[dict] | None             # clasico/verbose_json: [{"start", "text", "no_speech_prob"?, "avg_logprob"?}]
    ms: int
    bytes_enviados: int


# ---------------------------------------------------------------- piezas puras
def wav_pcm16(audio: np.ndarray, sr: int = SR) -> bytes:
    """WAV PCM de 16 bits mono. Lo que pasa de ±1 se recorta. Todo en memoria."""
    x = np.nan_to_num(np.asarray(audio, dtype=np.float32).reshape(-1), nan=0.0, posinf=1.0, neginf=-1.0)
    pcm = (np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(sr))
        w.writeframes(pcm.tobytes())
    return buf.getvalue()


def multipart(campos: list[tuple[str, str]], fichero: tuple[str, bytes, str]) -> tuple[bytes, str]:
    """(cuerpo, content-type con boundary). Los campos repetidos (`languages[]`, `keywords[]`) se repiten tal cual. `fichero`: (nombre, bytes, tipo), parte `file`, al final."""
    borde = "----WhisperMeet" + secrets.token_hex(16)
    partes: list[bytes] = []
    for nombre, valor in campos:
        partes.append(f'--{borde}\r\nContent-Disposition: form-data; name="{nombre}"\r\n\r\n'.encode("utf-8") + str(valor).encode("utf-8") + b"\r\n")
    nombre_f, datos, tipo = fichero
    partes.append(f'--{borde}\r\nContent-Disposition: form-data; name="file"; filename="{nombre_f}"\r\nContent-Type: {tipo}\r\n\r\n'.encode("utf-8")
                  + datos + b"\r\n")
    partes.append(f"--{borde}--\r\n".encode("ascii"))
    return b"".join(partes), f"multipart/form-data; boundary={borde}"


def _solo_loopback(entorno) -> bool:
    return str(entorno.get(ENV_SOLO_LOOPBACK, "") or "").strip() not in ("", "0")


def host_permitido(host: str, entorno=os.environ) -> bool:
    """False si la guarda de pruebas está puesta y el host no es de bucle local."""
    if not _solo_loopback(entorno):
        return True
    return str(host or "").strip().strip("[]").lower() in HOSTS_LOOPBACK


def idioma_de_respuesta(cuerpo: dict, dialecto: str) -> str | None:
    """gpt-transcribe: `languages[0].code`. Clásico: `language` (`spanish` → `es`, `catalan` → `ca`, `english` → `en`; un código se deja)."""
    if not isinstance(cuerpo, dict):
        return None
    if dialecto == "gpt-transcribe":
        langs = cuerpo.get("languages")
        if isinstance(langs, list) and langs:
            primero = langs[0]
            codigo = primero.get("code") if isinstance(primero, dict) else primero
            if isinstance(codigo, str) and codigo.strip():
                return codigo.strip().lower()
        return None
    leng = cuerpo.get("language")
    if isinstance(leng, str) and leng.strip():
        v = leng.strip().lower()
        return _NOMBRES_IDIOMA.get(v, v)
    return None


def _retry_after(cabeceras) -> float | None:
    valor = None
    try:
        for k, v in cabeceras.items():
            if str(k).lower() == "retry-after":
                valor = v
                break
    except AttributeError:
        return None
    try:
        s = float(str(valor).strip())
    except (TypeError, ValueError):
        return None   # una fecha HTTP o un valor ilegible
    return s if math.isfinite(s) and s >= 0 else None


def clasificar(status: int, cuerpo: dict | None, cabeceras) -> NubeError:
    """Causa de un estado HTTP que no es éxito (tabla de `diseno.md` §2.4). Del cuerpo solo se miran `error.param`, `error.code` y `error.type`."""
    err = cuerpo.get("error") if isinstance(cuerpo, dict) else None
    err = err if isinstance(err, dict) else {}
    param = str(err.get("param") or "").strip().lower()
    codigo_crudo = str(err.get("code") or "").strip()
    codigo = codigo_crudo.lower()
    tipo = str(err.get("type") or "").strip().lower()
    ra = _retry_after(cabeceras)

    def e(causa: str, con_retry: bool = False) -> NubeError:
        return NubeError(causa, status, codigo_crudo, ra if con_retry else None)

    if status == 401:
        return e("clave")
    if status == 403:
        return e("permiso")
    if status in (404, 405, 415):
        return e("config")
    if status == 408:
        return e("tiempo")
    if status == 413:
        return e("audio")
    if status == 400:
        if param in _PARAMS_PISTAS or "prompt" in codigo or "keyword" in codigo:
            return e("pistas")
        if param in _PARAMS_CONFIG:
            return e("config")
        if param == "file" or "audio" in codigo:
            return e("audio")
        return e("rechazo")
    if status == 422:
        return e("rechazo")
    if status == 429:
        if any(m in codigo or m in tipo for m in _MARCAS_CREDITO):
            return e("credito")
        return e("tasa", True)
    if status in (500, 502, 503, 504):
        return e("servidor", True)
    return e("rechazo")


def tono_prueba() -> np.ndarray:
    """1 s de un tono de 440 Hz a -30 dBFS, float32 a 16 kHz: lo que envía «Probar» (ningún dato del usuario)."""
    t = np.arange(SR, dtype=np.float32) / SR
    return (10 ** (-30 / 20) * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)


# ---------------------------------------------------------------- el cliente
class ClienteNube:
    def __init__(self, url_base: str, modelo: str, clave: str, autenticacion: str = "bearer", dialecto: str = "auto",
                 entorno=os.environ, proxies=None):
        """ValueError si la dirección, el modelo, la autenticación o el dialecto no son válidos (las mismas reglas que Ajustes)."""
        self.url_base = validar_url_nube(url_base)
        self.modelo = validar_modelo_nube(modelo)
        self.autenticacion = validar_autenticacion(autenticacion)
        self.dialecto_pedido = validar_dialecto(dialecto)
        self.dialecto = dialecto_efectivo(self.modelo, self.dialecto_pedido)
        self._clave = clave
        self.entorno = entorno
        partes = urlsplit(self.url_base)
        self.esquema = partes.scheme.lower()
        self.host = partes.hostname or ""
        self.puerto = partes.port or (443 if self.esquema == "https" else 80)
        self.ruta = partes.path.rstrip("/") + "/audio/transcriptions"
        self._proxies = proxies
        self._conn: http.client.HTTPConnection | None = None
        self._cerrado = False   # tras `cerrar()` no se reconecta ni se reenvía

    def __repr__(self) -> str:   # sin la clave
        return f"ClienteNube(host={self.host!r}, modelo={self.modelo!r}, dialecto={self.dialecto!r})"

    # ---------------------------------------------------------------- proxy y conexión
    def _proxy(self) -> tuple[str, int] | None:
        """(host, puerto) del proxy del sistema para este destino, o None. Nada de proxy con la guarda de pruebas ni hacia http (solo bucle local)."""
        if _solo_loopback(self.entorno) or self.esquema != "https":
            return None
        try:
            proxies = self._proxies if self._proxies is not None else urllib.request.getproxies()
            valor = proxies.get("https") or proxies.get("http")
            if not valor or urllib.request.proxy_bypass(self.host):
                return None
            p = urlsplit(valor if "//" in valor else "//" + valor)
            if not p.hostname:
                return None
            return p.hostname, p.port or (443 if p.scheme == "https" else 80)
        except Exception:  # noqa: BLE001  (un proxy ilegible: se sale directo)
            return None

    def _nueva_conexion(self, timeout: float) -> http.client.HTTPConnection:
        if self.esquema == "https":
            proxy = self._proxy()
            if proxy:
                c = http.client.HTTPSConnection(proxy[0], proxy[1], timeout=timeout, context=ssl.create_default_context())
                c.set_tunnel(self.host, self.puerto)
                return c
            return http.client.HTTPSConnection(self.host, self.puerto, timeout=timeout, context=ssl.create_default_context())
        return http.client.HTTPConnection(self.host, self.puerto, timeout=timeout)

    def _soltar(self) -> None:
        """Descarta la conexión actual (un error, un cuerpo sin leer…); el cliente sigue siendo utilizable."""
        c, self._conn = self._conn, None
        if c is not None:
            try:
                c.close()
            except Exception:  # noqa: BLE001
                pass

    def cerrar(self) -> None:
        """Cierra la conexión y deja una marca: después de esto no se reconecta ni se reenvía nada (fin de la reunión o cambio de ajustes)."""
        self._cerrado = True
        self._soltar()

    def _conectar(self, conn: http.client.HTTPConnection, timeout: float) -> None:
        """`connect()` (DNS + TCP + TLS) acotado de verdad: corre en un hilo demonio y se espera con límite. Si vence, la conexión se abandona (el hilo
        la cierra si llega a completarse) y se lanza `TimeoutError`."""
        conn.timeout = timeout
        cerradura = threading.Lock()
        hecho = threading.Event()
        estado = {"error": None, "terminado": False, "abandonada": False}

        def tarea() -> None:
            error = None
            try:
                conn.connect()
            except BaseException as e:  # noqa: BLE001
                error = e
            with cerradura:
                estado["error"], estado["terminado"] = error, True
                abandonada = estado["abandonada"]
            if abandonada:
                try:
                    conn.close()
                except Exception:  # noqa: BLE001
                    pass
            hecho.set()

        threading.Thread(target=tarea, daemon=True, name="nube-conexion").start()
        hecho.wait(max(0.05, timeout))
        with cerradura:
            vencida = not estado["terminado"]
            if vencida:
                estado["abandonada"] = True
        if vencida:
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            raise TimeoutError("conexion")
        if estado["error"] is not None:
            raise estado["error"]

    def _leer(self, resp, limite: float) -> bytes:
        """El cuerpo de la respuesta con plazo TOTAL (`limite`, instante de `time.monotonic()`) y el tope de `MAX_RESPUESTA_BYTES`."""
        trozos: list[bytes] = []
        total = 0
        while total <= MAX_RESPUESTA_BYTES:
            resta = limite - time.monotonic()
            if resta <= 0:
                raise TimeoutError("lectura")
            sock = getattr(self._conn, "sock", None)
            if sock is not None:
                sock.settimeout(resta)
            trozo = resp.read(min(65536, MAX_RESPUESTA_BYTES + 1 - total))
            if not trozo:
                break
            trozos.append(trozo)
            total += len(trozo)
        return b"".join(trozos)

    # ---------------------------------------------------------------- petición
    def _campos(self, idiomas: list[str], prompt: str, palabras_clave: list[str]) -> list[tuple[str, str]]:
        if self.dialecto == "gpt-transcribe":
            campos = [("model", self.modelo), ("response_format", "json"), ("temperature", "0")]
            campos += [("languages[]", i) for i in idiomas]
            if prompt:
                campos.append(("prompt", prompt))
            for t in palabras_clave or ():
                t = " ".join(str(t).split()) if not re.search(r"[<>\r\n]", str(t)) else ""   # con `<`, `>`, CR o LF el servicio rechazaría TODA la petición: se omite el término
                if t:
                    campos.append(("keywords[]", t))
            return campos
        campos = [("model", self.modelo), ("response_format", "verbose_json"), ("temperature", "0")]
        if len(idiomas) == 1:
            campos.append(("language", idiomas[0]))
        if prompt:
            campos.append(("prompt", prompt))
        return campos

    def _cabeceras(self, ctype: str, largo: int) -> dict:
        h = {"Content-Type": ctype, "Content-Length": str(largo), "Accept": "application/json", "User-Agent": "WhisperMeet"}
        if self.autenticacion == "api-key":
            h["api-key"] = self._clave   # una sola de las dos, nunca ambas
        else:
            h["Authorization"] = f"Bearer {self._clave}"
        return h

    def transcribir(self, wav: bytes, *, idiomas: list[str], prompt: str, palabras_clave: list[str],
                    timeout_conexion: float, timeout_lectura: float, plazo_total: float | None = None) -> ResultadoNube:
        """UN intento. Lanza `NubeError`. `timeout_conexion` acota DNS + TCP + TLS; `timeout_lectura` es el plazo TOTAL de envío y respuesta (no el de cada
        lectura). `plazo_total`: tope de todo el intento (conexión incluida)."""
        t_ini = time.monotonic()
        if not host_permitido(self.host, self.entorno):
            raise NubeError("bloqueada_pruebas")
        if self._cerrado:
            raise NubeError("red")
        cuerpo, ctype = multipart(self._campos(list(idiomas or ()), prompt or "", list(palabras_clave or ())), ("trozo.wav", wav, "audio/wav"))
        cabeceras = self._cabeceras(ctype, len(cuerpo))
        ini = time.perf_counter()
        repetido = False
        while True:
            reutilizada = self._conn is not None and getattr(self._conn, "sock", None) is not None
            try:
                if self._cerrado:
                    raise NubeError("red")
                if self._conn is None:
                    self._conn = self._nueva_conexion(timeout_conexion)
                if getattr(self._conn, "sock", None) is None:
                    self._conectar(self._conn, timeout_conexion if plazo_total is None else min(timeout_conexion, plazo_total))
                    reutilizada = False
                lectura = timeout_lectura if plazo_total is None else min(timeout_lectura, plazo_total - (time.monotonic() - t_ini))
                if lectura <= 0:
                    raise TimeoutError("plazo")
                limite = time.monotonic() + lectura   # plazo TOTAL de envío y respuesta (no por lectura)
                if self._conn.sock is not None:
                    self._conn.sock.settimeout(lectura)
                self._conn.request("POST", self.ruta, body=cuerpo, headers=cabeceras)
                resta = limite - time.monotonic()
                if resta <= 0:
                    raise TimeoutError("envio")
                if self._conn.sock is not None:
                    self._conn.sock.settimeout(resta)
                resp = self._conn.getresponse()
                crudo = self._leer(resp, limite)
                if len(crudo) > MAX_RESPUESTA_BYTES:
                    crudo = crudo[:MAX_RESPUESTA_BYTES]
                    self._soltar()   # queda cuerpo sin leer: la conexión no se reutiliza
                estado, cab = resp.status, resp.headers
                break
            except NubeError:
                self._soltar()
                raise
            except (ConnectionResetError, ConnectionAbortedError, BrokenPipeError, http.client.RemoteDisconnected):
                self._soltar()
                if reutilizada and not repetido and not self._cerrado:
                    repetido = True   # keep-alive caducado: se reabre y se repite UNA vez, sin contarlo como fallo
                    continue
                raise NubeError("red") from None
            except TimeoutError:
                self._soltar()
                raise NubeError("tiempo") from None
            except ssl.SSLCertVerificationError:
                self._soltar()
                raise NubeError("certificado") from None
            except (OSError, http.client.HTTPException, socket.gaierror):
                self._soltar()
                raise NubeError("red") from None
            except Exception:  # noqa: BLE001  (cualquier otra cosa: la conexión no se fía)
                self._soltar()
                raise NubeError("red") from None
        try:
            datos = json.loads(crudo.decode("utf-8")) if crudo else None
        except (ValueError, UnicodeDecodeError):
            datos = None
        if 200 <= estado < 300:
            if not isinstance(datos, dict):
                raise NubeError("rechazo", estado)
            return self._resultado(datos, int((time.perf_counter() - ini) * 1000), len(cuerpo), estado)
        raise clasificar(estado, datos if isinstance(datos, dict) else None, cab)

    def _resultado(self, datos: dict, ms: int, enviados: int, estado: int = 200) -> ResultadoNube:
        texto = datos.get("text")
        if not isinstance(texto, str):   # un 200 sin `text` (un portal cautivo, un proxy, un dialecto que no casa) NO es un éxito; `{"text": ""}` sí (silencio)
            raise NubeError("rechazo", estado)
        texto = texto.strip()
        if self.dialecto == "clasico" and datos.get("segments") is not None and not isinstance(datos.get("segments"), list):
            raise NubeError("rechazo", estado)
        segmentos = None
        if self.dialecto == "clasico" and isinstance(datos.get("segments"), list):
            segmentos = []
            for s in datos["segments"]:
                if not isinstance(s, dict) or not isinstance(s.get("text"), str):
                    continue
                seg = {"start": float(s["start"]) if isinstance(s.get("start"), (int, float)) else 0.0, "text": s["text"].strip()}
                for k in ("no_speech_prob", "avg_logprob"):
                    if isinstance(s.get(k), (int, float)) and not isinstance(s.get(k), bool):
                        seg[k] = float(s[k])
                segmentos.append(seg)
            if not segmentos and texto:   # un servidor que da texto sin segmentos: no se pierde
                segmentos = None
        return ResultadoNube(texto, idioma_de_respuesta(datos, self.dialecto), segmentos, ms, enviados)
