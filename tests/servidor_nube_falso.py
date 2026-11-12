"""Servidor falso de transcripción en la nube (protocolo compatible con OpenAI) para los tests. Solo `127.0.0.1`, hilo demonio, sin tocar disco ni stdout.

    with ServidorNubeFalso() as s:
        s.ok("hola", idiomas=["es"])      # la próxima petición recibe esto
        s.error(401, code="invalid_api_key", param=None)
        ... usar s.url_base ...
        s.peticiones                       # lo que llegó: ruta, campos (sin el fichero), fichero (tamaño, RIFF/WAVE) y cabeceras de autenticación

Las respuestas se programan en una cola; si está vacía, contesta `ok("")`. Todas las entradas de la cola son autosuficientes (no modifican a la siguiente).
El mensaje de los errores repite la clave recibida y una cadena centinela: así los tests comprueban que el cliente no los deja pasar.
"""
from __future__ import annotations

import json
import re
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CENTINELA_MENSAJE = "mensaje-del-servicio-centinela"
_NOMBRES = {"es": "spanish", "ca": "catalan", "en": "english"}


def _partes_multipart(cuerpo: bytes, tipo: str):
    m = re.search(r"boundary=(\S+)", tipo or "")
    if not m:
        return []
    delim = b"--" + m.group(1).strip('"').encode()
    salida = []
    for parte in cuerpo.split(delim)[1:]:
        if parte.startswith(b"--"):
            break
        parte = parte[2:] if parte.startswith(b"\r\n") else parte
        corte = parte.find(b"\r\n\r\n")
        if corte < 0:
            continue
        cab, contenido = parte[:corte].decode("utf-8", "replace"), parte[corte + 4:]
        if contenido.endswith(b"\r\n"):
            contenido = contenido[:-2]
        nombre = re.search(r'name="([^"]*)"', cab)
        fichero = re.search(r'filename="([^"]*)"', cab)
        tipo_p = re.search(r"Content-Type:\s*([^\r\n]+)", cab, re.I)
        salida.append({"nombre": nombre.group(1) if nombre else "", "filename": fichero.group(1) if fichero else None,
                       "tipo": tipo_p.group(1).strip() if tipo_p else None, "contenido": contenido})
    return salida


class _Manejador(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"   # conexión persistente, como el servicio real

    def log_message(self, *args):   # nada a stdout ni stderr
        pass

    def _enviar(self, status: int, cuerpo: bytes, cabeceras: dict | None = None, cerrar: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        for k, v in (cabeceras or {}).items():
            self.send_header(k, str(v))
        self.end_headers()
        self.wfile.write(cuerpo)
        self.wfile.flush()
        if cerrar:
            self.close_connection = True   # sin avisar con `Connection: close`: un keep-alive que caduca

    def do_POST(self):
        srv: ServidorNubeFalso = self.server.falso
        largo = int(self.headers.get("Content-Length") or 0)
        cuerpo = self.rfile.read(largo) if largo else b""
        campos, fichero = [], None
        for p in _partes_multipart(cuerpo, self.headers.get("Content-Type", "")):
            if p["filename"] is not None:
                c = p["contenido"]
                fichero = {"nombre_campo": p["nombre"], "filename": p["filename"], "tipo": p["tipo"], "tam": len(c),
                           "riff_wave": c[:4] == b"RIFF" and c[8:12] == b"WAVE"}
            else:
                campos.append((p["nombre"], p["contenido"].decode("utf-8", "replace")))
        auth = self.headers.get("Authorization")
        clave = (auth or "")[7:] if (auth or "").startswith("Bearer ") else (self.headers.get("api-key") or "")
        with srv._lock:
            srv.peticiones.append({"ruta": self.path, "metodo": "POST", "campos": campos, "fichero": fichero,
                                   "authorization": auth, "api_key": self.headers.get("api-key"), "bytes": largo,
                                   "content_type": self.headers.get("Content-Type", "")})
            paso = srv._cola.popleft() if srv._cola else srv._por_defecto()
        tipo = paso["tipo"]
        if tipo == "lento":
            time.sleep(paso["s"])
            paso = srv._respuesta_ok(paso.get("texto", ""), None, None, campos)
            tipo = paso["tipo"]
        if tipo == "corte":
            self.close_connection = True
            self.connection.close()
            return
        if tipo == "ok":
            self._enviar(200, json.dumps(srv._cuerpo_ok(paso, campos), ensure_ascii=False).encode(), cerrar=paso.get("cerrar", False))
        elif tipo == "crudo":
            self._enviar(paso["status"], paso["cuerpo"], paso.get("cabeceras"))
        elif tipo == "error":
            err = {"message": f"Incorrect API key provided: {clave}. {CENTINELA_MENSAJE}", "type": "invalid_request_error",
                   "param": paso["param"], "code": paso["code"]}
            cab = {"Retry-After": paso["retry_after"]} if paso["retry_after"] is not None else {}
            self._enviar(paso["status"], json.dumps({"error": err}).encode(), cab)


class ServidorNubeFalso:
    def __init__(self):
        self._cola: deque = deque()
        self._lock = threading.Lock()
        self.peticiones: list[dict] = []
        self._servidor: ThreadingHTTPServer | None = None
        self._hilo: threading.Thread | None = None

    # ---------------------------------------------------------------- ciclo de vida
    def __enter__(self):
        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), _Manejador)
        self._servidor.daemon_threads = True
        self._servidor.block_on_close = False
        self._servidor.falso = self
        self._hilo = threading.Thread(target=self._servidor.serve_forever, daemon=True, name="servidor-nube-falso")
        self._hilo.start()
        return self

    def __exit__(self, *exc):
        if self._servidor is not None:
            self._servidor.shutdown()
            self._servidor.server_close()
        return False

    @property
    def puerto(self) -> int:
        return self._servidor.server_address[1]

    @property
    def url_base(self) -> str:
        return f"http://127.0.0.1:{self.puerto}/v1"

    # ---------------------------------------------------------------- programación de respuestas
    def _encolar(self, paso: dict) -> None:
        with self._lock:
            self._cola.append(paso)

    @staticmethod
    def _respuesta_ok(texto, idiomas, segmentos, _campos=None, cerrar=False) -> dict:
        return {"tipo": "ok", "texto": texto, "idiomas": idiomas, "segmentos": segmentos, "cerrar": cerrar}

    def _por_defecto(self) -> dict:
        return self._respuesta_ok("", None, None)

    def ok(self, texto: str, idiomas=None, segmentos=None) -> "ServidorNubeFalso":
        """200 con `texto`. `idiomas`: códigos (`languages` en gpt-transcribe, `language` en clásico). `segmentos`: lista de dicts de `verbose_json`
        (solo clásico); sin ella se inventa uno bueno con el texto."""
        self._encolar(self._respuesta_ok(texto, idiomas, segmentos))
        return self

    def error(self, status: int, code=None, param=None, retry_after=None) -> "ServidorNubeFalso":
        self._encolar({"tipo": "error", "status": status, "code": code, "param": param, "retry_after": retry_after})
        return self

    def lento(self, segundos: float, texto: str = "") -> "ServidorNubeFalso":
        """Espera `segundos` y después contesta 200 con `texto`."""
        self._encolar({"tipo": "lento", "s": segundos, "texto": texto})
        return self

    def corte(self) -> "ServidorNubeFalso":
        """Cierra el socket sin responder."""
        self._encolar({"tipo": "corte"})
        return self

    def cerrar_tras_respuesta(self, texto: str = "ok") -> "ServidorNubeFalso":
        """Contesta 200 y cierra el socket sin avisar: la siguiente petición por la misma conexión falla (keep-alive caducado)."""
        self._encolar(self._respuesta_ok(texto, None, None, cerrar=True))
        return self

    def crudo(self, cuerpo: bytes, status: int = 200, cabeceras: dict | None = None) -> "ServidorNubeFalso":
        """Un cuerpo tal cual (JSON ilegible, respuesta gigante…)."""
        self._encolar({"tipo": "crudo", "cuerpo": cuerpo, "status": status, "cabeceras": cabeceras})
        return self

    # ---------------------------------------------------------------- lo recibido
    def valores(self, nombre: str, i: int = -1) -> list[str]:
        """Los valores del campo `nombre` (en orden) de la petición `i`."""
        with self._lock:
            return [v for k, v in self.peticiones[i]["campos"] if k == nombre]

    def nombres_de_campos(self, i: int = -1) -> list[str]:
        with self._lock:
            return [k for k, _v in self.peticiones[i]["campos"]]

    # ---------------------------------------------------------------- cuerpo de un 200
    def _cuerpo_ok(self, paso: dict, campos: list) -> dict:
        formato = next((v for k, v in campos if k == "response_format"), "json")
        texto, idiomas = paso["texto"], paso["idiomas"]
        if formato == "verbose_json":
            cuerpo = {"task": "transcribe", "duration": 1.0, "text": texto}
            if idiomas:
                cuerpo["language"] = _NOMBRES.get(idiomas[0], idiomas[0])
            segs = paso["segmentos"]
            if segs is None:
                segs = [{"id": 0, "start": 0.0, "end": 1.0, "text": texto, "avg_logprob": -0.2, "no_speech_prob": 0.01}] if texto else []
            cuerpo["segments"] = segs
            return cuerpo
        cuerpo = {"text": texto}
        if idiomas:
            cuerpo["languages"] = [{"code": c} for c in idiomas]
        return cuerpo
