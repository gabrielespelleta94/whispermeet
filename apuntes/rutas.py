"""Guardián de rutas: TODA escritura y lectura de ficheros del usuario pasa por aquí.

Reglas:
- Escritura automática solo en `<proyecto>/02. Sesiones (transcripciones)/AAAA-MM-DD-tema.md`,
  en `<proyecto>/00. CONTEXTO (IA)/NN-nombre.md` (solo tras aceptar el usuario) y en `bandeja/`.
  Además, la caché propia de la app (`cache/`).
- Proyectos extra (`proyectos_extra` de la configuración): carpetas fuera de la raíz. Si están marcadas
  como compartidas (OneDrive de otra persona), durante la reunión la sesión se guarda SOLO en local
  (`sesiones/<proyecto>/AAAA-MM-DD-tema.md`, escritura incremental); `02. Sesiones` solo se crea al PUBLICAR el
  documento final (`publicar_sesion`, tras terminar y sin sobrescribir nunca), y nunca si el usuario elige no publicar.
- Checks de preparación: `checks/<proyecto>.json`, locales (fuera de git); nunca en la carpeta del proyecto.
- Backlog: lectura de los .md de sesión (bandeja, sesiones locales y `02. Sesiones` de cada proyecto) con las mismas exclusiones y topes; lo único
  que se escribe es `backlog/estado.json` (local, fuera de git, escritura atómica). Los .md de sesión no se modifican nunca.
- Planes de sesiones: solo lectura de `planes/*.json` (locales de la app).
- Ola 3: `seguimiento/<proyecto>.json` (pendientes entre sesiones, local) y borradores `.eml` en una carpeta temporal propia (`WhisperMeet-borradores`).
- Nunca se escribe CLAUDE.md, AGENTS.md, docs/ ni nada bajo las raíces de solo lectura (Knowledge).
- Nada de path traversal: los nombres de proyecto y de fichero se validan por componente y la ruta
  resuelta (symlinks incluidos) debe quedar dentro de la carpeta permitida.
- Nunca se lee .env, credenciales, .git, node_modules ni ficheros con pinta de secreto.
"""
from __future__ import annotations

import os
import re
import tempfile
import unicodedata
from pathlib import Path

CARPETA_SESIONES = "02. Sesiones (transcripciones)"
CARPETA_CONTEXTO = "00. CONTEXTO (IA)"

DIRS_EXCLUIDOS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".ssh", ".aws", ".azure",
                  ".gnupg", ".idea", ".vscode"}
DIRS_EXCLUIDOS_MD = DIRS_EXCLUIDOS | {"dist", "build", "out", "target", ".next"}   # además: carpetas generadas (lectura de .md del proyecto)
EXT_SECRETAS = {".pem", ".key", ".pfx", ".p12", ".pkcs12", ".kdbx", ".jks", ".keystore", ".ppk",
                ".tfvars", ".tfstate", ".gpg", ".asc"}
NOMBRES_PROTEGIDOS = {"claude.md", "agents.md"}
DIRS_SOLO_LECTURA = {"docs"}
EXT_LEGIBLES = {".md", ".txt"}
RESERVADOS_WIN = {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}

_RE_NOMBRE_SECRETO = re.compile(
    r"""(^\.env(\..*)?$)|(\.env$)
       |(^|[._\-\s])(secret|secrets|secreto|secretos|credential|credentials|credencial|credenciales
                    |password|passwords|passwd|contrasena|contrasenas|token|tokens|apikey|api[-_]key
                    |private[-_]key|clave[-_]privada)([._\-\s]|$)
       |(^id_(rsa|dsa|ecdsa|ed25519))
       |(^\.(npmrc|pypirc|netrc|git-credentials|pgpass|htpasswd)$)
       |(^local\.settings\.json$)|(^appsettings\..+\.json$)|(^secrets?\.)""",
    re.I | re.X,
)

_RE_FICHERO_CONTEXTO = re.compile(r"^[0-9]{2}-[A-Za-z0-9][A-Za-z0-9\-]{0,80}\.md$")
_RE_FICHERO_SESION = re.compile(r"^\d{4}-\d{2}-\d{2}-[a-z0-9]+(-[a-z0-9]+)*\.md$")
_RE_CACHE = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,120}\.json$")
_RE_DATOS = re.compile(r"^[a-z0-9][a-z0-9_\-]{0,60}\.(json|jsonl)$")   # ola 4: ficheros de datos propios de la app (reglas de silencio, envíos, métricas…)
_RE_SESION_MD = re.compile(r"^\d{4}-\d{2}-\d{2}.*\.md$", re.I)   # lectura del backlog: más tolerante que _RE_FICHERO_SESION (que es para escribir)
NOMBRE_ESTADO_BACKLOG = "estado.json"

# Líneas con pinta de secreto dentro de un texto leído (defensa en profundidad).
_RE_LINEA_SECRETA = re.compile(
    r"""(sk-ant-[A-Za-z0-9_\-]{10,})|(sk-[A-Za-z0-9]{20,})|(AKIA[0-9A-Z]{16})|(ghp_[A-Za-z0-9]{20,})
       |(-----BEGIN [A-Z ]*PRIVATE KEY-----)|(eyJ[A-Za-z0-9_\-]{15,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{5,})
       |((password|passwd|contraseña|contrasena|secret|api[_-]?key|client[_-]?secret|token)\s*[:=]\s*\S{6,})
       |(Bearer\s+[A-Za-z0-9\._\-]{20,})|(AccountKey=[A-Za-z0-9+/=]{20,})""",
    re.I | re.X,
)


class RutaProhibida(Exception):
    """La operación pedida sale de lo permitido."""


def sin_acentos(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def slug(texto: str, maximo: int = 60) -> str:
    s = sin_acentos(texto or "").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    s = s[:maximo].strip("-")
    return s or "reunion"


def _norm(p: os.PathLike | str) -> str:
    return os.path.normcase(os.path.realpath(os.fspath(p)))


def esta_dentro(base: os.PathLike | str, ruta: os.PathLike | str) -> bool:
    b, r = _norm(base), _norm(ruta)
    return r == b or r.startswith(b.rstrip("\\/") + os.sep)


def validar_componente(nombre: str) -> str:
    """Un único componente de ruta, sin separadores ni trucos de Windows."""
    if not isinstance(nombre, str) or not nombre or nombre in (".", ".."):
        raise RutaProhibida("nombre vacío o relativo")
    if any(c in nombre for c in '/\\:*?"<>|') or any(ord(c) < 32 for c in nombre):
        raise RutaProhibida("caracteres no permitidos en el nombre")
    if nombre != nombre.strip() or nombre.endswith("."):
        raise RutaProhibida("el nombre no puede acabar en punto ni llevar espacios en los extremos")
    if nombre.split(".")[0].lower() in RESERVADOS_WIN:
        raise RutaProhibida("nombre reservado de Windows")
    return nombre


def es_secreto(ruta: os.PathLike | str) -> bool:
    """Por el nombre del fichero o de cualquiera de sus carpetas."""
    p = Path(ruta)
    partes = [x for x in p.parts if x not in (p.anchor, "")]
    for parte in partes:
        if parte.lower() in DIRS_EXCLUIDOS:
            return True
    nombre = p.name
    if p.suffix.lower() in EXT_SECRETAS:
        return True
    return bool(_RE_NOMBRE_SECRETO.search(nombre))


def limpiar_secretos(texto: str) -> str:
    """Sustituye las líneas con pinta de secreto antes de enviar nada a ningún sitio."""
    out = []
    for linea in texto.splitlines():
        out.append("[línea omitida: posible secreto]" if _RE_LINEA_SECRETA.search(linea) else linea)
    return "\n".join(out) + ("\n" if texto.endswith("\n") else "")


def raiz_onedrive(entorno=None) -> str | None:
    """Carpeta de OneDrive del usuario (la de la organización primero) si existe en disco; sirve de punto de partida del selector de
    carpetas. Solo lee variables de entorno y mira si la carpeta existe: no entra en ella ni usa la API de ningún servicio."""
    env = os.environ if entorno is None else entorno
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        v = (env.get(var) or "").strip()
        if v and Path(v).is_absolute() and Path(v).is_dir():
            return v
    return None


def sugerir_compartida(ruta: str | os.PathLike, entorno=None) -> bool:
    """True si la ruta parece una carpeta que OTRA persona ha compartido en OneDrive: cuelga de OneDrive y alguno de sus componentes
    empieza por «Archivos de » (así las llama OneDrive en el equipo de quien recibe el acceso). Es solo una propuesta."""
    p = Path(str(ruta))
    partes = [x for x in p.parts if x not in (p.anchor, "")]
    if not any(x.lower().startswith("archivos de ") for x in partes):
        return False
    env = os.environ if entorno is None else entorno
    for var in ("OneDriveCommercial", "OneDrive", "OneDriveConsumer"):
        v = (env.get(var) or "").strip()
        if v and Path(v).is_absolute() and esta_dentro(v, p):
            return True
    return any(x.lower().startswith("onedrive") for x in partes)


class Guardian:
    def __init__(self, raiz_proyectos, bandeja, cache, solo_lectura=(), extras=(), sesiones_locales=None,
                 planes=None, checks=None, backlog=None, datos=None):
        self.raiz = Path(raiz_proyectos)
        self.bandeja = Path(bandeja)
        self.cache = Path(cache)
        self.solo_lectura = [Path(p) for p in solo_lectura if p]
        self.sesiones_locales = Path(sesiones_locales) if sesiones_locales else None
        self.planes = Path(planes) if planes else None
        self.checks = Path(checks) if checks else None
        self.backlog = Path(backlog) if backlog else None   # carpeta local del estado del backlog (estado.json); fuera de git
        # ola 3: seguimiento entre sesiones (<seguimiento>/<proyecto>.json, local, fuera de git) y borradores .eml (carpeta temporal PROPIA de la app)
        self.seguimiento = (self.backlog.parent / "seguimiento") if self.backlog else None
        self.borradores = Path(tempfile.gettempdir()) / "WhisperMeet-borradores"
        self.datos = Path(datos) if datos else None         # ola 4: carpeta local de datos de la app (reglas de silencio, envíos, métricas, glosario); fuera de git
        self.extras: dict[str, tuple[Path, bool]] = {}
        self._nombres_extra: dict[str, str] = {}
        self.fijar_extras(extras)

    # ---------- proyectos extra (fuera de la raíz) ----------
    def fijar_extras(self, extras) -> None:
        """`extras`: lista de {nombre, ruta, compartido}. Se descartan las entradas no válidas o peligrosas."""
        nuevos: dict[str, tuple[Path, bool]] = {}
        nombres: dict[str, str] = {}
        for e in extras or []:
            try:
                nombre, ruta = validar_componente(str(e["nombre"])), Path(str(e["ruta"]))
            except (KeyError, TypeError, RutaProhibida):
                continue
            if nombre.startswith(".") or nombre.lower() in DIRS_EXCLUIDOS or not ruta.is_absolute()                     or ruta == Path(ruta.anchor) or es_secreto(ruta) or not ruta.is_dir():
                continue
            if any(esta_dentro(ro, ruta) for ro in self.solo_lectura):
                continue
            nuevos[nombre.lower()] = (ruta, bool(e.get("compartido", False)))
            nombres[nombre.lower()] = nombre
        self.extras = nuevos
        self._nombres_extra = nombres

    def validar_extra(self, nombre: str, ruta: str, compartido: bool = False) -> dict:
        """Valida una carpeta de proyecto que el usuario quiere añadir («Añadir carpeta de proyecto»). Devuelve la entrada
        normalizada {nombre, ruta, compartido} o lanza RutaProhibida con el motivo. Misma exigencia que `fijar_extras`, más:
        que el nombre no choque con otro proyecto y que la carpeta no sea la raíz de proyectos ni una ya añadida."""
        nombre = (nombre or "").strip()
        texto = (ruta or "").strip().strip('"')
        if not texto:
            raise RutaProhibida("Indica la ruta de la carpeta.")
        validar_componente(nombre)   # nombre vacío, con separadores o reservado de Windows
        if nombre.startswith(".") or nombre.lower() in DIRS_EXCLUIDOS:
            raise RutaProhibida("Ese nombre de proyecto no está permitido.")
        p = Path(texto)
        if not p.is_absolute():
            raise RutaProhibida("La ruta debe ser absoluta (por ejemplo D:\\Clientes\\Proyecto).")
        if p == Path(p.anchor):
            raise RutaProhibida("No se admite la raíz de una unidad como carpeta de proyecto.")
        if not p.is_dir():
            raise RutaProhibida("La carpeta no existe o no es una carpeta.")
        if es_secreto(p):
            raise RutaProhibida("La ruta tiene pinta de contener secretos o credenciales.")
        if any(esta_dentro(ro, p) for ro in self.solo_lectura):
            raise RutaProhibida("Esa carpeta está dentro de una ubicación de solo lectura (Knowledge).")
        if _norm(p) == _norm(self.raiz):
            raise RutaProhibida("Esa es la raíz de proyectos: elige la carpeta de un proyecto concreto.")
        if nombre.lower() in self.extras or (self.raiz / nombre).is_dir():
            raise RutaProhibida("Ya existe un proyecto con ese nombre.")
        if any(_norm(r) == _norm(p) for r, _c in self.extras.values()):
            raise RutaProhibida("Esa carpeta ya está añadida como proyecto.")
        return {"nombre": nombre, "ruta": str(p), "compartido": bool(compartido)}

    def validar_carpeta_nueva(self, nombre: str, ubicacion: str | None = None) -> Path:
        """Valida la carpeta que el usuario quiere CREAR desde la app («Nueva carpeta») y devuelve su ruta (no crea nada).
        `ubicacion`: carpeta existente donde irá (por defecto, la raíz de proyectos). Mismas exclusiones que `validar_extra`
        (nombre de un solo componente, sin punto inicial ni carpetas técnicas, sin pinta de secreto, fuera de Knowledge, sin raíz de
        unidad) y además: nunca se sobrescribe ni se reutiliza una carpeta o fichero que ya exista con ese nombre."""
        nombre = (nombre or "").strip()
        validar_componente(nombre)   # nombre vacío, con separadores, reservado de Windows o con punto/espacio final
        if nombre.startswith(".") or nombre.lower() in DIRS_EXCLUIDOS:
            raise RutaProhibida("Ese nombre de carpeta no está permitido.")
        if es_secreto(nombre):
            raise RutaProhibida("El nombre tiene pinta de contener secretos o credenciales.")
        texto = (str(ubicacion).strip().strip('"') if ubicacion is not None else "")
        base = Path(texto) if texto else self.raiz
        if not base.is_absolute():
            raise RutaProhibida("La ubicación debe ser una ruta absoluta (por ejemplo D:\\Clientes).")
        if base == Path(base.anchor):
            raise RutaProhibida("No se admite crear carpetas en la raíz de una unidad.")
        if not base.is_dir():
            raise RutaProhibida("La ubicación no existe o no es una carpeta.")
        if es_secreto(base):
            raise RutaProhibida("La ubicación tiene pinta de contener secretos o credenciales.")
        if any(esta_dentro(ro, base) for ro in self.solo_lectura):
            raise RutaProhibida("Esa ubicación está dentro de una carpeta de solo lectura (Knowledge).")
        destino = base / nombre
        if os.path.lexists(destino):
            raise RutaProhibida("Ya existe una carpeta o un fichero con ese nombre en esa ubicación: elige otro nombre (no se reutiliza ni se sobrescribe).")
        if nombre.lower() in self.extras or (self.raiz / nombre).exists():
            raise RutaProhibida("Ya existe un proyecto con ese nombre.")
        if es_secreto(destino) or not esta_dentro(base, destino):
            raise RutaProhibida("Esa ruta no está permitida.")
        return destino

    def crear_carpeta_proyecto(self, nombre: str, ubicacion: str | None = None) -> dict:
        """Crea UNA carpeta vacía (`mkdir` sin `parents` y sin `exist_ok`: si aparece otra a la vez, falla en vez de reutilizarla).
        Devuelve {nombre, ruta, en_raiz}; `en_raiz` = cuelga directamente de la raíz de proyectos y ya sale en la lista sin más."""
        destino = self.validar_carpeta_nueva(nombre, ubicacion)
        try:
            destino.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            raise RutaProhibida("Ya existe una carpeta con ese nombre en esa ubicación: elige otro nombre.")
        except OSError as e:
            raise RutaProhibida(f"No se pudo crear la carpeta: {e}")
        return {"nombre": destino.name, "ruta": str(destino), "en_raiz": _norm(destino.parent) == _norm(self.raiz)}

    def deshacer_carpeta_nueva(self, ruta: str | os.PathLike) -> None:
        """Retira una carpeta que acabamos de crear y que sigue vacía (solo para deshacer un alta que ha fallado a medias)."""
        p = Path(ruta)
        try:
            if p.is_dir() and not any(p.iterdir()):
                p.rmdir()
        except OSError:
            pass

    def extras_ordenados(self) -> list[tuple[str, tuple[Path, bool]]]:
        """[(nombre original, (ruta, compartido))] por orden alfabético."""
        return sorted(((self._nombres_extra[k], v) for k, v in self.extras.items()), key=lambda x: x[0].lower())

    def _extra(self, nombre: str):
        return self.extras.get((nombre or "").lower())

    def es_compartido(self, nombre: str | None) -> bool:
        e = self._extra(nombre) if nombre else None
        return bool(e and e[1])

    def carpeta_sesiones_local(self, proyecto: str) -> Path:
        if self.sesiones_locales is None:
            raise RutaProhibida("no hay carpeta local de sesiones configurada")
        return self.sesiones_locales / slug(proyecto, 60)

    # ---------- planes de sesiones (solo lectura) ----------
    def leer_planes(self, tope_bytes: int = 100_000) -> list[tuple[str, str]]:
        """[(nombre_fichero, texto)] de `planes/*.json`. Solo ficheros directos de la carpeta local."""
        out: list[tuple[str, str]] = []
        if self.planes is None or not self.planes.is_dir():
            return out
        for p in sorted(self.planes.glob("*.json")):
            if not p.is_file() or es_secreto(p.name) or not esta_dentro(self.planes, p):
                continue
            with open(p, "rb") as f:
                datos = f.read(tope_bytes + 1)
            if len(datos) > tope_bytes:
                continue
            out.append((p.name, datos.decode("utf-8-sig", errors="replace")))
        return out

    # ---------- proyectos ----------
    def proyecto_dir(self, nombre: str) -> Path:
        validar_componente(nombre)
        if nombre.startswith(".") or nombre.lower() in DIRS_EXCLUIDOS:
            raise RutaProhibida("proyecto no permitido")
        extra = self._extra(nombre)
        if extra:
            if not extra[0].is_dir():
                raise RutaProhibida("el proyecto no existe")
            return extra[0]
        p = self.raiz / nombre
        if not p.is_dir():
            raise RutaProhibida("el proyecto no existe")
        esperado = os.path.join(_norm(self.raiz), os.path.normcase(nombre))
        if _norm(p) != esperado:
            raise RutaProhibida("el proyecto no es una subcarpeta directa de la raíz")
        return p

    # ---------- .md del proyecto (SOLO LECTURA: contexto ampliado, vista previa y «abrir») ----------
    def md_del_proyecto(self, proyecto: str, profundidad: int = 4, tope_bytes: int = 200_000,
                        plazo_s: float = 6.0, max_visitas: int = 6000) -> dict:
        """Todos los .md bajo la carpeta del proyecto (recursivo, acotado), sin leerlos. Excluye `02. Sesiones (transcripciones)`
        (las sesiones entran por el backlog), carpetas ocultas o generadas (.git, node_modules, .venv, dist, build…), enlaces
        simbólicos y nombres con pinta de secreto. Devuelve `{ficheros, truncado}`; cada fichero: `ruta` (Path), `rel` (posix, desde
        la carpeta del proyecto), `tam`, `mtime`, `prof` (0 = raíz) y `dejado` ("" o el motivo por el que NO se leerá: «tamaño» si
        supera `tope_bytes`, «nube» si es un marcador de OneDrive sin descargar). La profundidad máxima y `plazo_s` y `max_visitas` acotan el recorrido (una carpeta lenta no bloquea: `truncado`)."""
        import time as _t
        pdir = self.proyecto_dir(proyecto)
        base = os.fspath(pdir)
        fin = _t.monotonic() + plazo_s
        encontrados: list[dict] = []
        truncado = False
        visitas = 0
        nivel = [(base, 0)]
        while nivel and not truncado:
            siguiente: list[tuple[str, int]] = []
            for carpeta, prof in nivel:
                try:
                    with os.scandir(carpeta) as it:
                        entradas = sorted(it, key=lambda e: e.name.lower())
                except OSError:
                    continue
                for e in entradas:
                    visitas += 1
                    if visitas > max_visitas or _t.monotonic() > fin:
                        truncado = True
                        break
                    nl = e.name.lower()
                    try:
                        if e.is_dir(follow_symlinks=False):
                            if (prof >= profundidad or e.name.startswith(".") or nl in DIRS_EXCLUIDOS_MD or es_secreto(e.name)
                                    or (prof == 0 and nl == CARPETA_SESIONES.lower())):
                                continue
                            siguiente.append((e.path, prof + 1))
                        elif e.is_file(follow_symlinks=False) and nl.endswith(".md") and not es_secreto(e.name):
                            st = e.stat()
                            dejado = "tamaño" if st.st_size > tope_bytes else ""
                            if not dejado and getattr(st, "st_file_attributes", 0) & (0x400000 | 0x40000 | 0x1000):
                                dejado = "nube"
                            rel = os.path.relpath(e.path, base).replace(os.sep, "/")
                            encontrados.append({"ruta": Path(e.path), "rel": rel, "tam": st.st_size, "mtime": st.st_mtime,
                                                "prof": prof, "dejado": dejado})
                    except OSError:
                        continue
                if truncado:
                    break
            nivel = siguiente
        return {"ficheros": encontrados, "truncado": truncado}

    def leer_md_proyecto(self, proyecto: str, ruta: os.PathLike | str, tope_bytes: int = 200_000) -> str:
        """Lee un .md del proyecto (dentro de su carpeta, no de `02. Sesiones`, sin secretos, con tope y sin líneas con pinta de secreto)."""
        pdir = self.proyecto_dir(proyecto)
        self._comprobar_md_proyecto(ruta, pdir)
        return self.leer(ruta, pdir, tope_bytes)

    def _comprobar_md_proyecto(self, ruta, pdir: Path) -> Path:
        p = Path(ruta)
        if p.suffix.lower() != ".md":
            raise RutaProhibida("solo se abren .md")
        if not esta_dentro(pdir, p):
            raise RutaProhibida("fuera de la carpeta del proyecto")
        rel = Path(_norm(p)).relative_to(Path(_norm(pdir)))
        if rel.parts and (es_secreto(rel) or any(x.startswith(".") or x.lower() in DIRS_EXCLUIDOS_MD for x in rel.parts[:-1])):
            raise RutaProhibida("fichero no permitido")
        if len(rel.parts) > 1 and rel.parts[0].lower() == CARPETA_SESIONES.lower():
            raise RutaProhibida("las sesiones se abren desde el backlog")
        if not p.is_file():
            raise RutaProhibida("no es un fichero")
        return p

    def abrir_md_proyecto(self, proyecto: str, ruta, abridor=None) -> None:
        """Abre un .md del proyecto con la aplicación del sistema (no escribe nada). `abridor` sustituye a `os.startfile` (pruebas)."""
        p = self._comprobar_md_proyecto(ruta, self.proyecto_dir(proyecto))
        self._abrir(p, abridor)

    def abrir_carpeta_proyecto(self, proyecto: str, abridor=None) -> None:
        """Abre la carpeta del proyecto en el explorador del sistema (no escribe nada)."""
        self._abrir(self.proyecto_dir(proyecto), abridor)

    @staticmethod
    def _abrir(p: Path, abridor=None) -> None:
        if abridor is None:
            abridor = getattr(os, "startfile", None)
            if abridor is None:
                raise RutaProhibida("abrir con el sistema solo está disponible en Windows")
        abridor(str(p))

    # ---------- comprobación común de escritura ----------
    def _comprobar_escritura(self, destino: Path, base: Path) -> None:
        if not esta_dentro(base, destino):
            raise RutaProhibida("destino fuera de la carpeta permitida")
        for ro in self.solo_lectura:
            if esta_dentro(ro, destino):
                raise RutaProhibida("destino en una carpeta de solo lectura")
        if destino.name.lower() in NOMBRES_PROTEGIDOS:
            raise RutaProhibida("fichero protegido")
        rel = Path(_norm(destino)).relative_to(Path(_norm(base))) if _norm(destino) != _norm(base) else Path(".")
        if any(parte.lower() in DIRS_SOLO_LECTURA | DIRS_EXCLUIDOS for parte in rel.parts):
            raise RutaProhibida("carpeta protegida")
        if es_secreto(destino.name):
            raise RutaProhibida("nombre con pinta de secreto")

    # ---------- rutas permitidas ----------
    def ruta_sesion(self, proyecto: str | None, fecha: str, tema: str, evitar_existente: bool = True) -> Path:
        """`<proyecto>/02. Sesiones (transcripciones)/AAAA-MM-DD-tema.md` o `bandeja/...`."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
            raise RutaProhibida("fecha no válida")
        base_nombre = f"{fecha}-{slug(tema)}"
        if proyecto is None:
            carpeta = self.bandeja
        elif self.es_compartido(proyecto):
            self.proyecto_dir(proyecto)  # valida que existe
            carpeta = self.carpeta_sesiones_local(proyecto)  # NUNCA en la carpeta compartida
        else:
            carpeta = self.proyecto_dir(proyecto) / CARPETA_SESIONES
        n = 1
        while True:
            nombre = f"{base_nombre}.md" if n == 1 else f"{base_nombre}-{n}.md"
            destino = carpeta / nombre
            if not (evitar_existente and destino.exists()):
                break
            n += 1
        self._validar_ruta_sesion(destino, proyecto)
        return destino

    def _validar_ruta_sesion(self, destino: Path, proyecto: str | None, publicar: bool = False) -> None:
        """`publicar`: solo para el documento final de un proyecto compartido, que va a su `02. Sesiones`.
        Sin `publicar`, un proyecto compartido solo admite la carpeta local (escritura incremental)."""
        if not _RE_FICHERO_SESION.match(destino.name):
            raise RutaProhibida("nombre de sesión no válido")
        if publicar and not (proyecto and self.es_compartido(proyecto)):
            raise RutaProhibida("solo se publica el documento final de un proyecto compartido")
        if proyecto is None:
            self._comprobar_escritura(destino, self.bandeja)
            if _norm(destino.parent) != _norm(self.bandeja):
                raise RutaProhibida("la bandeja no admite subcarpetas")
        elif publicar:
            pdir = self.proyecto_dir(proyecto)
            carpeta = pdir / CARPETA_SESIONES
            self._comprobar_escritura(destino, carpeta)
            if _norm(destino.parent) != _norm(carpeta):
                raise RutaProhibida("la sesión publicada va directamente en «02. Sesiones» del proyecto")
            if carpeta.exists() and (not carpeta.is_dir() or not esta_dentro(pdir, carpeta)):
                raise RutaProhibida("la carpeta de sesiones no es válida o sale del proyecto")
        elif self.es_compartido(proyecto):
            pdir = self.proyecto_dir(proyecto)
            carpeta = self.carpeta_sesiones_local(proyecto)
            if esta_dentro(pdir, destino):
                raise RutaProhibida("durante la reunión la sesión de un proyecto compartido se guarda solo en local")
            self._comprobar_escritura(destino, carpeta)
            if _norm(destino.parent) != _norm(carpeta):
                raise RutaProhibida("las sesiones van directamente en la carpeta local del proyecto")
        else:
            pdir = self.proyecto_dir(proyecto)
            carpeta = pdir / CARPETA_SESIONES
            self._comprobar_escritura(destino, carpeta)
            if _norm(destino.parent) != _norm(carpeta):
                raise RutaProhibida("las sesiones van directamente en la carpeta de sesiones")
            # la carpeta de sesiones no puede ser un enlace que escape del proyecto
            if carpeta.exists() and not esta_dentro(pdir, carpeta):
                raise RutaProhibida("la carpeta de sesiones sale del proyecto")

    def ruta_publicacion(self, proyecto: str, fecha: str, tema: str) -> Path:
        """Destino del documento final de un proyecto compartido: `<proyecto>/02. Sesiones (transcripciones)/AAAA-MM-DD-tema.md`,
        con sufijo si ya existe (nunca sobrescribe). No crea nada."""
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", fecha):
            raise RutaProhibida("fecha no válida")
        if not self.es_compartido(proyecto):
            raise RutaProhibida("solo se publica en proyectos compartidos")
        carpeta = self.proyecto_dir(proyecto) / CARPETA_SESIONES
        base_nombre, n = f"{fecha}-{slug(tema)}", 1
        while True:
            destino = carpeta / (f"{base_nombre}.md" if n == 1 else f"{base_nombre}-{n}.md")
            if not destino.exists():
                break
            n += 1
        self._validar_ruta_sesion(destino, proyecto, publicar=True)
        return destino

    def publicar_sesion(self, proyecto: str, fecha: str, tema: str, texto: str) -> Path:
        """Crea `02. Sesiones` si falta y escribe el documento final SIN sobrescribir nunca (creación exclusiva)."""
        for _ in range(100):
            destino = self.ruta_publicacion(proyecto, fecha, tema)
            destino.parent.mkdir(parents=True, exist_ok=True)
            try:
                with open(destino, "x", encoding="utf-8", newline="\n") as f:
                    f.write(texto)
                    f.flush()
                    os.fsync(f.fileno())
            except FileExistsError:
                continue
            return destino
        raise RutaProhibida("no se encontró un nombre libre para publicar la sesión")

    # ---------- checks de preparación (locales) ----------
    def ruta_checks(self, proyecto: str | None) -> Path:
        if self.checks is None:
            raise RutaProhibida("no hay carpeta local de checks configurada")
        if proyecto is not None:
            self.proyecto_dir(proyecto)  # el proyecto debe existir
        destino = self.checks / (slug(proyecto, 60) if proyecto else "bandeja")
        destino = destino.with_name(destino.name + ".json")
        self._comprobar_escritura(destino, self.checks)
        return destino

    def leer_checks(self, proyecto: str | None) -> str | None:
        p = self.ruta_checks(proyecto)
        if not p.is_file():
            return None
        with open(p, "rb") as f:
            return f.read(500_000).decode("utf-8-sig", errors="replace")

    def escribir_checks(self, proyecto: str | None, texto: str) -> Path:
        destino = self.ruta_checks(proyecto)
        self._escribir(destino, texto)
        return destino

    # ---------- backlog: sesiones pasadas (solo lectura) y estado local (backlog/estado.json) ----------
    def fuentes_sesiones(self) -> list[dict]:
        """Carpetas con sesiones pasadas: [{clave, etiqueta, proyecto, carpeta, origen, lenta}]. Solo mira nombres de carpetas locales; las de
        proyectos extra (p. ej. OneDrive) se marcan `lenta` y NO se tocan aquí: las lee su propio hilo con tiempo acotado (`Backlog`)."""
        vistas: set[str] = set()
        fuentes: list[dict] = []

        def anadir(clave, etiqueta, proyecto, carpeta, origen, lenta):
            n = os.path.normcase(os.path.abspath(os.fspath(carpeta)))   # sin realpath: no toca el disco (una carpeta de OneDrive puede tardar)
            if n in vistas:
                return
            vistas.add(n)
            fuentes.append({"clave": clave, "etiqueta": etiqueta, "proyecto": proyecto, "carpeta": Path(carpeta), "origen": origen, "lenta": lenta})

        anadir("bandeja", "Bandeja", "Bandeja", self.bandeja, "bandeja", False)
        nombres_extra = {slug(n, 60): n for n in self._nombres_extra.values()}
        if self.sesiones_locales is not None and self.sesiones_locales.is_dir():
            try:
                with os.scandir(self.sesiones_locales) as it:
                    subs = sorted((e for e in it if e.is_dir(follow_symlinks=False)), key=lambda e: e.name.lower())
            except OSError:
                subs = []
            for e in subs:
                if e.name.startswith(".") or e.name.lower() in DIRS_EXCLUIDOS or es_secreto(e.name):
                    continue
                anadir("local:" + e.name, f"{nombres_extra.get(e.name, e.name)} (local)", nombres_extra.get(e.name), e.path, "local", False)
        extras_norm = {_norm(r) for r, _c in self.extras.values()}
        try:
            with os.scandir(self.raiz) as it:
                dirs = sorted((e for e in it if e.is_dir(follow_symlinks=False)), key=lambda e: e.name.lower())
        except OSError:
            dirs = []
        for e in dirs:
            if e.name.startswith(".") or e.name.lower() in DIRS_EXCLUIDOS or es_secreto(e.name) or e.name.lower() in self.extras or _norm(e.path) in extras_norm:
                continue
            c = Path(e.path) / CARPETA_SESIONES
            if c.is_dir():
                anadir("proyecto:" + e.name, e.name, e.name, c, "proyecto", False)
        for nombre, (ruta, compartido) in self.extras_ordenados():
            anadir("extra:" + nombre, nombre + (" (compartida)" if compartido else ""), nombre, Path(ruta) / CARPETA_SESIONES,
                   "publicada" if compartido else "proyecto", True)
        return fuentes

    def listar_sesiones_md(self, carpeta: os.PathLike | str, tope: int = 2000) -> tuple[list[Path], int]:
        """([.md de sesión de la carpeta, más recientes primero], omitidos por nombre de secreto). Solo ficheros directos con nombre de fecha."""
        c = Path(carpeta)
        if not c.is_dir():
            return [], 0
        archivos, omitidos = [], 0
        with os.scandir(c) as it:
            for e in it:
                if not e.is_file() or not _RE_SESION_MD.match(e.name):
                    continue
                if es_secreto(e.name):
                    omitidos += 1
                    continue
                archivos.append(Path(e.path))
        archivos.sort(key=lambda p: p.name, reverse=True)
        return archivos[:tope], omitidos

    def _comprobar_sesion_md(self, ruta, base) -> Path:
        p = Path(ruta)
        if p.suffix.lower() != ".md":
            raise RutaProhibida("solo se leen .md")
        if not esta_dentro(base, p):
            raise RutaProhibida("lectura fuera de la carpeta permitida")
        if es_secreto(p.name) or es_secreto(Path(_norm(p)).name):
            raise RutaProhibida("fichero con pinta de secreto")
        if not p.is_file():
            raise RutaProhibida("no es un fichero")
        return p

    def estado_sesion_md(self, ruta, base) -> tuple[int, int]:
        """(fecha de modificación en ns, tamaño) de un .md de sesión permitido: la clave de la caché del backlog."""
        st = os.stat(self._comprobar_sesion_md(ruta, base))
        return st.st_mtime_ns, st.st_size

    def leer_sesion_md(self, ruta, base, tope_bytes: int = 200_000) -> str:
        """Texto de un .md de sesión dentro de `base`, con las mismas exclusiones y topes que `leer` (secretos fuera; recortado por tamaño)."""
        p = self._comprobar_sesion_md(ruta, base)
        return self.leer(p, base, tope_bytes)

    def abrir_sesion_md(self, ruta, base, abridor=None) -> None:
        """Abre un .md de sesión con la aplicación del sistema (solo lectura: no escribe nada). `abridor` sustituye a `os.startfile` (pruebas)."""
        p = self._comprobar_sesion_md(ruta, base)
        if abridor is None:
            abridor = getattr(os, "startfile", None)
            if abridor is None:
                raise RutaProhibida("abrir con el sistema solo está disponible en Windows")
        abridor(str(p))

    def ruta_backlog_estado(self) -> Path:
        if self.backlog is None:
            raise RutaProhibida("no hay carpeta local del backlog configurada")
        destino = self.backlog / NOMBRE_ESTADO_BACKLOG
        self._comprobar_escritura(destino, self.backlog)
        return destino

    def leer_backlog_estado(self, tope_bytes: int = 2_000_000) -> str | None:
        p = self.ruta_backlog_estado()
        if not p.is_file():
            return None
        with open(p, "rb") as f:
            return f.read(tope_bytes + 1).decode("utf-8-sig", errors="replace")

    def escribir_backlog_estado(self, texto: str) -> Path:
        destino = self.ruta_backlog_estado()
        self._escribir(destino, texto)   # temporal + os.replace: atómico
        return destino

    def apartar_backlog_estado(self) -> Path | None:
        """Aparta un estado.json dañado (lo renombra a estado.json.roto-AAAAMMDD-HHMMSS, sin borrar nada) para que no bloquee. Devuelve la nueva ruta."""
        p = self.ruta_backlog_estado()
        if not p.is_file():
            return None
        from datetime import datetime
        for n in range(100):
            nuevo = p.with_name(f"{p.name}.roto-{datetime.now():%Y%m%d-%H%M%S}" + (f"-{n}" if n else ""))
            if not nuevo.exists():
                os.replace(p, nuevo)
                return nuevo
        return None

    # ---------- datos locales de la app (ola 4): solo ficheros NOMBRE.json|jsonl en `self.datos`, nunca dentro de un proyecto ----------
    def ruta_datos(self, nombre: str) -> Path:
        if self.datos is None:
            raise RutaProhibida("no hay carpeta local de datos configurada")
        if not isinstance(nombre, str) or not _RE_DATOS.match(nombre):
            raise RutaProhibida("nombre de fichero de datos no válido")
        destino = self.datos / nombre
        self._comprobar_escritura(destino, self.datos)
        return destino

    def hay_datos(self) -> bool:
        return self.datos is not None

    def leer_datos(self, nombre: str, tope_bytes: int = 4_000_000) -> str | None:
        """Texto del fichero de datos, o None si no existe (o no hay carpeta). Con tope: de un .jsonl se lee el FINAL (lo más reciente)."""
        if self.datos is None:
            return None
        p = self.ruta_datos(nombre)
        if not p.is_file():
            return None
        with open(p, "rb") as f:
            tam = p.stat().st_size
            if tam > tope_bytes:
                f.seek(tam - tope_bytes)
                f.readline()   # una línea cortada no vale
            return f.read().decode("utf-8-sig", errors="replace")

    def escribir_datos(self, nombre: str, texto: str) -> Path:
        destino = self.ruta_datos(nombre)
        self._escribir(destino, texto)   # temporal + os.replace: atómico
        return destino

    def anadir_datos(self, nombre: str, linea: str) -> Path:
        """Añade UNA línea a un .jsonl (la carpeta se crea si falta)."""
        destino = self.ruta_datos(nombre)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "a", encoding="utf-8", newline="\n") as f:
            f.write(linea.rstrip("\r\n") + "\n")
        return destino

    # ---------- ola 3: seguimiento de pendientes entre sesiones (local) ----------
    def ruta_seguimiento(self, proyecto: str) -> Path:
        if self.seguimiento is None:
            raise RutaProhibida("no hay carpeta local de seguimiento configurada")
        self.proyecto_dir(proyecto)  # el proyecto debe existir
        destino = self.seguimiento / (slug(proyecto, 60) + ".json")
        self._comprobar_escritura(destino, self.seguimiento)
        return destino

    def leer_seguimiento(self, proyecto: str, tope_bytes: int = 2_000_000) -> str | None:
        p = self.ruta_seguimiento(proyecto)
        if not p.is_file():
            return None
        with open(p, "rb") as f:
            return f.read(tope_bytes + 1).decode("utf-8-sig", errors="replace")

    def escribir_seguimiento(self, proyecto: str, texto: str) -> Path:
        destino = self.ruta_seguimiento(proyecto)
        self._escribir(destino, texto)   # temporal + os.replace: atómico
        return destino

    def apartar_seguimiento(self, proyecto: str) -> Path | None:
        """Aparta un seguimiento dañado (renombra a <proyecto>.json.roto-AAAAMMDD-HHMMSS, sin borrar nada)."""
        p = self.ruta_seguimiento(proyecto)
        if not p.is_file():
            return None
        from datetime import datetime
        for n in range(100):
            nuevo = p.with_name(f"{p.name}.roto-{datetime.now():%Y%m%d-%H%M%S}" + (f"-{n}" if n else ""))
            if not nuevo.exists():
                os.replace(p, nuevo)
                return nuevo
        return None

    # ---------- ola 3: borradores de correo (.eml con X-Unsent: 1) en una carpeta temporal propia; NUNCA datos del usuario ni el repo ----------
    def escribir_borrador(self, nombre: str, contenido: bytes) -> Path:
        if not re.fullmatch(r"borrador-[0-9a-f]{8,32}\.eml", nombre or ""):
            raise RutaProhibida("nombre de borrador no válido")
        destino = self.borradores / nombre
        self._comprobar_escritura(destino, self.borradores)
        self.borradores.mkdir(parents=True, exist_ok=True)
        with open(destino, "wb") as f:
            f.write(contenido)
        return destino

    def abrir_borrador(self, ruta, abridor=None) -> None:
        """Abre un .eml de la carpeta de borradores con el programa del sistema (Outlook lo muestra como borrador). Nunca envía nada."""
        p = Path(ruta)
        if not esta_dentro(self.borradores, p) or p.suffix.lower() != ".eml" or not p.is_file():
            raise RutaProhibida("solo se abren borradores de la carpeta de borradores")
        if abridor is None:
            abridor = getattr(os, "startfile", None)
            if abridor is None:
                raise RutaProhibida("abrir con el sistema solo está disponible en Windows")
        abridor(str(p))

    def ruta_contexto(self, proyecto: str, fichero: str, permitir_subcarpeta_plantilla: bool = False) -> Path:
        pdir = self.proyecto_dir(proyecto)
        carpeta = pdir / CARPETA_CONTEXTO
        if permitir_subcarpeta_plantilla and fichero in ("equipos/LEEME.md", "en-curso/LEEME.md"):
            destino = carpeta / fichero.split("/")[0] / "LEEME.md"
        else:
            if not isinstance(fichero, str) or not _RE_FICHERO_CONTEXTO.match(fichero):
                raise RutaProhibida("solo ficheros NN-nombre.md en la raíz de 00. CONTEXTO (IA)")
            destino = carpeta / fichero
        self._comprobar_escritura(destino, carpeta)
        if carpeta.exists() and not esta_dentro(pdir, carpeta):
            raise RutaProhibida("la carpeta de contexto sale del proyecto")
        return destino

    def ruta_cache(self, nombre: str) -> Path:
        if not _RE_CACHE.match(nombre):
            raise RutaProhibida("nombre de caché no válido")
        destino = self.cache / nombre
        self._comprobar_escritura(destino, self.cache)
        return destino

    # ---------- escritura ----------
    def _escribir(self, destino: Path, texto: str) -> None:
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_name(destino.name + ".tmp")
        with open(tmp, "w", encoding="utf-8", newline="\n") as f:
            f.write(texto)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp, destino)
        except PermissionError:  # lector con el fichero abierto en Windows
            with open(destino, "w", encoding="utf-8", newline="\n") as f:
                f.write(texto)
            try:
                os.remove(tmp)
            except OSError:
                pass

    def escribir_sesion(self, destino: Path, proyecto: str | None, texto: str) -> None:
        self._validar_ruta_sesion(destino, proyecto)  # sin publicar: un proyecto compartido solo admite la carpeta local
        self._escribir(destino, texto)

    def escribir_contexto(self, proyecto: str, fichero: str, texto: str, plantilla: bool = False) -> Path:
        destino = self.ruta_contexto(proyecto, fichero, permitir_subcarpeta_plantilla=plantilla)
        self._escribir(destino, texto)
        return destino

    def asegurar_cache(self) -> Path:
        """Crea la carpeta de la caché si falta, ANTES de que dos hilos escriban a la vez (con la carpeta recién creada entre las dos normalizaciones de ruta de
        `_comprobar_escritura`, una de ellas decía «destino fuera de la carpeta permitida»). Solo la carpeta de la caché; nada más."""
        try:
            self.cache.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
        return self.cache

    def escribir_cache(self, nombre: str, texto: str) -> Path:
        destino = self.ruta_cache(nombre)
        self._escribir(destino, texto)
        return destino

    # ---------- lectura ----------
    def leer(self, ruta: os.PathLike | str, base: os.PathLike | str, tope_bytes: int = 200_000) -> str:
        """Lee un .md/.txt dentro de `base`, sin secretos y con tope de tamaño."""
        p = Path(ruta)
        if not esta_dentro(base, p):
            raise RutaProhibida("lectura fuera de la carpeta permitida")
        if es_secreto(p):
            raise RutaProhibida("fichero con pinta de secreto")
        rel = Path(_norm(p)).relative_to(Path(_norm(base))) if _norm(p) != _norm(base) else Path(".")
        if rel.parts and es_secreto(rel):
            raise RutaProhibida("fichero con pinta de secreto")
        if p.suffix.lower() not in EXT_LEGIBLES:
            raise RutaProhibida("solo se leen .md y .txt")
        if not p.is_file():
            raise RutaProhibida("no es un fichero")
        with open(p, "rb") as f:
            datos = f.read(tope_bytes + 1)
        texto = datos[:tope_bytes].decode("utf-8", errors="replace")
        if len(datos) > tope_bytes:
            texto += "\n[…recortado por tamaño]"
        return limpiar_secretos(texto.replace("\r\n", "\n"))  # se trabaja con LF; al escribir se respeta el EOL original

    def leer_documento(self, ruta: os.PathLike | str, base: os.PathLike | str, tope_bytes: int = 200_000, tope_chars: int = 120_000) -> str:
        """Como `leer`, pero además admite .docx, .pptx y .pdf (este solo si hay librería instalada) para la recuperación de fuentes (SOLO LECTURA).
        Mismas reglas: dentro de `base`, sin nombre de secreto, con tope de tamaño; el texto sale sin líneas con pinta de secreto. Lanza
        `RutaProhibida` o `documentos.Indisponible`."""
        from . import documentos as DOC
        p = Path(ruta)
        if p.suffix.lower() in EXT_LEGIBLES:
            return self.leer(p, base, tope_bytes)
        if p.suffix.lower() not in DOC.EXT_OFICINA | DOC.EXT_PDF:
            raise RutaProhibida("solo se leen .md, .txt, .docx, .pptx y .pdf")
        if not esta_dentro(base, p):
            raise RutaProhibida("lectura fuera de la carpeta permitida")
        if es_secreto(p):
            raise RutaProhibida("fichero con pinta de secreto")
        rel = Path(_norm(p)).relative_to(Path(_norm(base))) if _norm(p) != _norm(base) else Path(".")
        if rel.parts and es_secreto(rel):
            raise RutaProhibida("fichero con pinta de secreto")
        if not p.is_file():
            raise RutaProhibida("no es un fichero")
        if DOC.en_la_nube(p):
            raise RutaProhibida("el fichero está en la nube sin descargar: no se abre")
        return limpiar_secretos(DOC.texto_de(p, tope_chars))
