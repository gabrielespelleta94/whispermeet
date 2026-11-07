"""Checks de preparación de una sesión: lista de comprobaciones que se marcan a mano o solas.

Reglas (las fija el usuario, no el modelo):
- Lo que hace el usuario manda: un check marcado o desmarcado a mano queda BLOQUEADO y el modelo no lo cambia.
- El modelo solo marca checks abiertos y no bloqueados, con minuto y una cita de hasta 15 palabras. Se deshace
  con un clic (y al deshacer queda bloqueado: el modelo no vuelve a marcarlo).
- Al modelo se le envían solo los abiertos y no bloqueados, en formato compacto, y como máximo 15.
- Persistencia: un fichero local por proyecto (`checks\\<proyecto>.json`, fuera de git), con las sesiones dentro.
  Se escribe siempre a través del Guardian; nunca en la carpeta del proyecto ni en la compartida.
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
import uuid
from datetime import datetime

from .rutas import Guardian, sin_acentos
from .texto import a_segundos, mmss, recortar

MAX_PROMPT = 15        # checks abiertos que se envían al modelo por llamada periódica
MAX_SUGERIDOS = 8      # sugeridos que puede devolver el digest
MAX_CHECKS = 60        # por lista (proyecto + sesión)
MAX_TEXTO = 140
MAX_CITA_PALABRAS = 15
ABIERTO, HECHO = "abierto", "hecho"
PLAN, MANUAL, SUGERIDO = "plan", "manual", "sugerido"
_RE_SESION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]{0,19}$")


def _limpio(v, maximo: int = MAX_TEXTO) -> str:
    return recortar(" ".join(str(v or "").split()), maximo)


def clave_sesion(sesion_id: str | None) -> str:
    sid = (sesion_id or "").strip()
    if not sid:
        return "general"
    if not _RE_SESION.match(sid):
        raise ValueError("Sesión no válida.")
    return sid


def id_base(texto: str) -> str:
    """Id estable de un check del plan: cambia solo si cambia el texto."""
    return "p-" + hashlib.sha1(sin_acentos(texto).lower().encode("utf-8")).hexdigest()[:8]


def _nuevo(origen: str, texto: str, ident: str | None = None) -> dict:
    return {"id": ident or f"{origen[0]}-{uuid.uuid4().hex[:8]}", "texto": texto, "origen": origen, "estado": ABIERTO,
            "bloqueado": False, "auto": False, "minuto": "", "t_seg": None, "cita": "", "borrado": False}


def cita_corta(texto, maximo: int = MAX_CITA_PALABRAS) -> str:
    palabras = " ".join(str(texto or "").split()).split(" ")
    palabras = [p for p in palabras if p]
    corta = " ".join(palabras[:maximo])
    return corta + ("…" if len(palabras) > maximo else "")


def visibles(lista: list[dict]) -> list[dict]:
    return [dict(c) for c in lista if not c.get("borrado")]


def _jaccard(a: str, b: str) -> float:
    ta, tb = set(sin_acentos(a).lower().split()), set(sin_acentos(b).lower().split())
    return len(ta & tb) / len(ta | tb) if ta and tb else 0.0


class AlmacenChecks:
    """Lee y escribe `checks\\<proyecto>.json` a través del Guardian. Seguro entre hilos."""

    def __init__(self, guardian: Guardian):
        self.g = guardian
        self._lock = threading.RLock()
        self._memoria: dict[str, str] = {}  # sin carpeta de checks configurada (tests): solo en memoria

    # ---------------------------------------------------------- disco
    def _cargar(self, proyecto: str | None) -> dict:
        crudo = self._memoria.get(proyecto or "") if self.g.checks is None else self.g.leer_checks(proyecto)
        try:
            datos = json.loads(crudo) if crudo else {}
        except ValueError:
            datos = {}
        if not isinstance(datos, dict) or not isinstance(datos.get("sesiones"), dict):
            datos = {"version": 1, "sesiones": {}}
        return datos

    def _guardar(self, proyecto: str | None, datos: dict) -> None:
        datos["actualizado"] = datetime.now().isoformat(timespec="seconds")
        texto = json.dumps(datos, ensure_ascii=False, indent=1)
        if self.g.checks is None:
            self._memoria[proyecto or ""] = texto
        else:
            self.g.escribir_checks(proyecto, texto)

    @staticmethod
    def _lista(datos: dict, sid: str) -> list[dict]:
        entrada = datos["sesiones"].setdefault(sid, {"checks": []})
        if not isinstance(entrada.get("checks"), list):
            entrada["checks"] = []
        lim = []
        for c in entrada["checks"]:
            if isinstance(c, dict) and c.get("id") and c.get("texto"):
                base = _nuevo(c.get("origen") if c.get("origen") in (PLAN, MANUAL, SUGERIDO) else MANUAL, "", c["id"])
                base.update({k: c[k] for k in base if k in c})
                lim.append(base)
        entrada["checks"] = lim
        return lim

    # ---------------------------------------------------------- lectura
    def listar(self, proyecto: str | None, sesion_id: str | None, base: list[str] | None = None) -> list[dict]:
        """Checks visibles. Los del plan (`base`) se incorporan la primera vez (y los nuevos que aparezcan);
        uno del plan que el usuario borró no vuelve."""
        sid = clave_sesion(sesion_id)
        with self._lock:
            datos = self._cargar(proyecto)
            lista = self._lista(datos, sid)
            cambio = sid not in (self._cargar(proyecto)["sesiones"])
            existentes = {c["id"] for c in lista}
            for texto in (base or []):
                t = _limpio(texto)
                if t and id_base(t) not in existentes and len(lista) < MAX_CHECKS:
                    lista.append(_nuevo(PLAN, t, id_base(t)))
                    existentes.add(id_base(t))
                    cambio = True
            if cambio:
                self._guardar(proyecto, datos)
            return visibles(lista)

    # ---------------------------------------------------------- operaciones del usuario
    def _buscar(self, lista: list[dict], ident: str) -> dict:
        for c in lista:
            if c["id"] == ident and not c.get("borrado"):
                return c
        raise ValueError("El check no existe.")

    def _operar(self, proyecto, sesion_id, base, fn):
        sid = clave_sesion(sesion_id)
        with self._lock:
            self.listar(proyecto, sid, base)  # asegura la base del plan
            datos = self._cargar(proyecto)
            lista = self._lista(datos, sid)
            fn(lista)
            self._guardar(proyecto, datos)
            return visibles(lista)

    def anadir(self, proyecto, sesion_id, texto: str, base=None, origen: str = MANUAL) -> list[dict]:
        t = _limpio(texto)
        if not t:
            raise ValueError("Escribe el texto del check.")

        def f(lista):
            if len([c for c in lista if not c.get("borrado")]) >= MAX_CHECKS:
                raise ValueError(f"Hay demasiados checks (máximo {MAX_CHECKS}).")
            lista.append(_nuevo(origen, t))
        return self._operar(proyecto, sesion_id, base, f)

    def editar(self, proyecto, sesion_id, ident: str, texto: str, base=None) -> list[dict]:
        t = _limpio(texto)
        if not t:
            raise ValueError("El texto del check no puede quedar vacío.")

        def f(lista):
            c = self._buscar(lista, ident)
            c["texto"] = t
            if c.get("origen") == SUGERIDO:   # «Confirmar» en la interfaz: la sugerencia pasa a ser un check propio
                c["origen"] = MANUAL
        return self._operar(proyecto, sesion_id, base, f)

    def borrar(self, proyecto, sesion_id, ident: str, base=None) -> list[dict]:
        def f(lista):
            c = self._buscar(lista, ident)
            if c["origen"] == PLAN:
                c["borrado"] = True      # se recuerda para que el plan no lo vuelva a meter
            else:
                lista.remove(c)
        return self._operar(proyecto, sesion_id, base, f)

    def marcar(self, proyecto, sesion_id, ident: str, hecho: bool, base=None) -> list[dict]:
        """Marcar o desmarcar a mano: queda bloqueado y el modelo ya no lo toca."""
        def f(lista):
            c = self._buscar(lista, ident)
            c.update(estado=HECHO if hecho else ABIERTO, bloqueado=True, auto=False, minuto="", t_seg=None, cita="")
        return self._operar(proyecto, sesion_id, base, f)

    def deshacer_auto(self, proyecto, sesion_id, ident: str, base=None) -> list[dict]:
        """Deshace un marcado automático: vuelve a abierto y queda bloqueado (decisión del usuario)."""
        def f(lista):
            c = self._buscar(lista, ident)
            if not c["auto"]:
                raise ValueError("Este check no se marcó automáticamente.")
            c.update(estado=ABIERTO, bloqueado=True, auto=False, minuto="", t_seg=None, cita="")
        return self._operar(proyecto, sesion_id, base, f)

    # ---------------------------------------------------------- modelo
    def para_prompt(self, proyecto, sesion_id, base=None) -> list[dict]:
        """Los que se envían al modelo: abiertos, no bloqueados, en orden (plan y manuales antes que sugeridos)
        y como máximo `MAX_PROMPT`."""
        lista = self.listar(proyecto, sesion_id, base)
        abiertos = [c for c in lista if c["estado"] == ABIERTO and not c["bloqueado"]]
        abiertos.sort(key=lambda c: c["origen"] == SUGERIDO)  # estable: respeta el orden dentro de cada grupo
        return abiertos[:MAX_PROMPT]

    def aplicar_marcas(self, proyecto, sesion_id, enviados: list[dict], marcas: list[dict], base=None) -> list[str]:
        """`marcas`: [{n, minuto, cita}] del modelo (n = posición 1..N en `enviados`). Solo se marca lo que SIGUE
        abierto y sin bloquear en este momento (el usuario puede haber tocado el check mientras el modelo pensaba)."""
        tocados: list[str] = []
        if not marcas:
            return tocados

        def f(lista):
            for m in marcas:
                if not 1 <= m["n"] <= len(enviados):
                    continue
                ident = enviados[m["n"] - 1]["id"]
                c = next((x for x in lista if x["id"] == ident and not x.get("borrado")), None)
                if not c or c["estado"] != ABIERTO or c["bloqueado"]:
                    continue
                seg = a_segundos(m.get("minuto") or "")
                c.update(estado=HECHO, auto=True, minuto=mmss(seg) if seg is not None else "", t_seg=seg,
                         cita=cita_corta(m.get("cita")))
                tocados.append(ident)
        self._operar(proyecto, sesion_id, base, f)
        return tocados

    def incorporar_sugeridos(self, proyecto, sesion_id, textos: list[str], base=None) -> list[dict]:
        """Sugeridos del digest (hasta MAX_SUGERIDOS), sin repetir lo que ya hay."""
        nuevos = []
        def f(lista):
            existentes = [c["texto"] for c in lista]
            for t in textos[:MAX_SUGERIDOS]:
                t = _limpio(t, 100)
                if not t or any(_jaccard(t, e) >= 0.6 for e in existentes) or len(lista) >= MAX_CHECKS:
                    continue
                lista.append(_nuevo(SUGERIDO, t))
                existentes.append(t)
                nuevos.append(t)
        out = self._operar(proyecto, sesion_id, base, f)
        return out


# ------------------------------------------------------------------ prompt y salida del modelo
def bloque_prompt(checks: list[dict]) -> str:
    """Compacto: «1 texto» (la posición es el número que devuelve el modelo)."""
    return "\n".join(f"{i} {c['texto']}" for i, c in enumerate(checks, 1))


def normalizar_marcas(lista, n_checks: int) -> list[dict]:
    """Salida del modelo -> [{n, minuto, cita}] válidas (1..n, una marca por check, cita de hasta 15 palabras)."""
    out, vistos = [], set()
    if not isinstance(lista, list):
        return out
    for u in lista[: max(0, n_checks)]:
        if not isinstance(u, dict):
            continue
        n = u.get("i")
        if isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= n_checks or n in vistos:
            continue
        vistos.add(n)
        seg = a_segundos(str(u.get("m") or "").strip().strip("[]"))
        out.append({"n": n, "minuto": mmss(seg) if seg is not None else "", "cita": cita_corta(u.get("q"))})
    return out


_VERBOS_FINITOS = set("""es son esta estan hay debe deben puede pueden tiene tienen existe existen falta faltan queda quedan corresponde
corresponden depende dependen incluye incluyen cubre cubren aplica aplican cumple cumplen consta sera seran sea sean fue ha han""".split())
_NO_VERBO = set("""lugar hogar mar mujer taller cantidad calidad ciudad verdad prioridad voluntad realidad capacidad disponibilidad""".split())


def tiene_verbo(texto: str) -> bool:
    """Heurística local para el español: algún infinitivo (-ar, -er, -ir), gerundio, participio o verbo muy frecuente conjugado."""
    for w in re.findall(r"[a-z]+", sin_acentos(texto or "").lower()):
        if w in _NO_VERBO:
            continue
        if w in _VERBOS_FINITOS:
            return True
        if len(w) >= 5 and re.search(r"(ar|er|ir|ando|iendo|ado|ido|ados|idos|adas|idas)$", w):
            return True
    return False


def con_sentido(texto: str, minimo_palabras: int = 3) -> bool:
    """Un check sugerido útil es una frase: al menos `minimo_palabras` palabras y un verbo reconocible («estamos todos» no lo es)."""
    palabras = re.findall(r"[^\W\d_]{2,}", texto or "")
    return len(palabras) >= minimo_palabras and tiene_verbo(texto)


def normalizar_sugeridos(lista) -> list[str]:
    """Sugeridos del digest: texto limpio, sin repetidos, solo frases con sentido (≥3 palabras y un verbo reconocible), máx. `MAX_SUGERIDOS`."""
    if not isinstance(lista, list):
        return []
    out = []
    for t in lista:
        t = _limpio(t, 100) if isinstance(t, str) else ""
        if t and con_sentido(t) and t.lower() not in [x.lower() for x in out]:
            out.append(t)
        if len(out) >= MAX_SUGERIDOS:
            break
    return out


# ------------------------------------------------------------------ resumen para el .md y el final
def resumen_markdown(checks: list[dict], nombre_sesion: str = "") -> str:
    """Bloque determinista: qué checks se dieron por hechos (y cómo) y cuáles quedan pendientes."""
    if not checks:
        return ""
    hechos = [c for c in checks if c["estado"] == HECHO]
    pend = [c for c in checks if c["estado"] != HECHO]
    L = [f"## Checks de la sesión{' ' + nombre_sesion if nombre_sesion else ''}", "",
         f"Hechos {len(hechos)} de {len(checks)}; pendientes {len(pend)}.", ""]
    if hechos:
        L.append("**Hechos**")
        for c in hechos:
            if c["auto"]:
                extra = f" (automático, minuto {c['minuto']}" + (f": «{c['cita']}»" if c["cita"] else "") + ")" if c["minuto"] else " (automático)"
            else:
                extra = " (a mano)"
            L.append(f"- {c['texto']}{extra}")
        L.append("")
    if pend:
        L.append("**Pendientes**")
        for c in pend:
            L.append(f"- {c['texto']}" + (" (desmarcado a mano)" if c["bloqueado"] else ""))
        L.append("")
    return "\n".join(L).rstrip() + "\n"
