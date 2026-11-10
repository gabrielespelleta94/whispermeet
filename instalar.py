"""Instalador de WhisperMeet: de una máquina Windows limpia a la primera reunión con un solo script.

    instalar.bat                      # doble clic (busca Python y llama a este script; la ventana queda abierta)
    py -3 instalar.py                 # lo mismo, desde una terminal
    py -3 instalar.py --comprobar     # no cambia nada: dice qué haría y qué falta
    py -3 instalar.py --dev           # instala también lo de desarrollo (pruebas y mediciones: requirements-dev.txt)
    py -3 instalar.py --si            # no pregunta (acepta descargar el modelo de Whisper)
    py -3 instalar.py --sin-modelo    # no descarga el modelo ni lo pregunta
    py -3 instalar.py --sin-acceso-directo

Solo biblioteca estándar: se ejecuta con el Python del sistema, antes de que exista el entorno. Cada paso es idempotente (ejecutarlo dos veces no cambia nada la segunda) y
dice «hecho», «ya estaba» o «falta: …». NUNCA borra nada ni pisa nada: `datos/config.json` solo se crea si no existe, y las carpetas de datos (`datos`, `sesiones`, `planes`…)
solo se crean si faltan; no se abre ni se toca nada de lo que contengan. La lógica está en funciones que reciben su entorno (`Entorno`) para probarla sin instalar nada.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

RAIZ = Path(__file__).resolve().parent
# Mínimo REAL: las versiones fijadas en requirements.txt (numpy 2.5 y av 19 exigen Python 3.12). Es el mismo valor que `apuntes.requisitos.PYTHON_MINIMO` (hay un test).
PYTHON_MINIMO = (3, 12)
ESTADOS = ("hecho", "ya", "falta", "omitido", "error", "haria")
ETIQUETA = {"hecho": "hecho", "ya": "ya estaba", "falta": "falta", "omitido": "omitido", "error": "error", "haria": "se haría"}
# Carpetas locales que la app espera (todas fuera de git). Solo se CREAN si faltan: su contenido no se mira nunca.
CARPETAS_LOCALES = ("datos", "bandeja", "cache", "planes", "checks", "sesiones", "backlog", "tipos_documento", "modelos")
MODELO_DEFECTO = "small"
DESCARGA_MODELO = (
    "import sys\n"
    "from faster_whisper import download_model\n"
    "print(download_model(sys.argv[1], cache_dir=sys.argv[2]))\n"
)


# ---------------------------------------------------------------- piezas comunes
@dataclass
class Opciones:
    comprobar: bool = False
    dev: bool = False
    si: bool = False
    sin_modelo: bool = False
    sin_acceso_directo: bool = False


@dataclass
class Resultado:
    paso: str
    estado: str                 # uno de ESTADOS
    mensaje: str
    pendiente: str = ""         # lo que queda por hacer a mano (sale en el resumen final)

    def linea(self) -> str:
        return f"[{ETIQUETA[self.estado]}] {self.paso}: {self.mensaje}"


def _ejecutar(cmd, timeout=None, mostrar=False):
    """(código, salida). `mostrar`: la salida del proceso va directa a la consola (para ver el progreso de pip) y no se captura."""
    try:
        if mostrar:
            return subprocess.run(cmd, cwd=str(RAIZ), timeout=timeout).returncode, ""
        p = subprocess.run(cmd, cwd=str(RAIZ), capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return 124, f"tiempo agotado ({timeout} s)"
    except OSError as e:
        return 127, str(e)


def _preguntar(texto: str) -> bool | None:
    """Sí/no en la consola; None si no hay consola interactiva (entonces se trata como «no» y se avisa)."""
    if not sys.stdin or not sys.stdin.isatty():
        return None
    try:
        return input(f"{texto} [s/N] ").strip().lower() in ("s", "si", "sí", "y", "yes")
    except EOFError:
        return None


@dataclass
class Entorno:
    """Todo lo que el instalador toca fuera de sí mismo, inyectable. Por defecto, el real."""
    raiz: Path = RAIZ
    python_actual: tuple = field(default_factory=lambda: tuple(sys.version_info[:3]))
    python_exe: str = field(default_factory=lambda: sys.executable)
    ejecutar: object = _ejecutar                      # (cmd, timeout=None, mostrar=False) -> (código, salida)
    buscar: object = shutil.which                     # nombre -> ruta o None
    preguntar: object = _preguntar                    # texto -> True | False | None (sin consola)
    imprimir: object = field(default=lambda *a: print(*a, flush=True))   # con flush: el orden con la salida de pip (otro proceso) se mantiene aunque se redirija
    home: Path = field(default_factory=Path.home)
    appdata: str | None = field(default_factory=lambda: os.environ.get("APPDATA"))

    @property
    def venv(self) -> Path:
        return self.raiz / ".venv"

    @property
    def venv_python(self) -> Path:
        return self.venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _version_texto(v) -> str:
    return ".".join(str(x) for x in tuple(v)[:3])


def _requisitos():
    """`apuntes.requisitos` (solo biblioteca estándar al importarlo): las mismas comprobaciones que la app, con su misma tabla de modelos."""
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    from apuntes import requisitos
    return requisitos


# ---------------------------------------------------------------- dependencias: lectura de los ficheros de requisitos (puro)
def normalizar_paquete(nombre: str) -> str:
    return re.sub(r"[-_.]+", "-", nombre).lower()


def leer_requisitos(ruta: Path, _vistos=None) -> list[tuple[str, str]]:
    """[(paquete normalizado, versión fijada)] de un requirements, siguiendo los `-r otro.txt`. Ignora comentarios, líneas en blanco y lo que no sea `nombre==versión`
    (los extras, como `uvicorn[standard]`, se quitan del nombre: lo que se compara es el paquete)."""
    ruta = Path(ruta)
    vistos = _vistos if _vistos is not None else set()
    if ruta in vistos or not ruta.is_file():
        return []
    vistos.add(ruta)
    out = []
    for linea in ruta.read_text(encoding="utf-8").splitlines():
        linea = linea.split("#", 1)[0].strip()
        if not linea:
            continue
        m = re.match(r"^-r\s+(\S+)$", linea)
        if m:
            out += leer_requisitos(ruta.parent / m.group(1), vistos)
            continue
        m = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)(?:\[[^\]]*\])?\s*==\s*([^\s;]+)", linea)
        if m:
            out.append((normalizar_paquete(m.group(1)), m.group(2)))
    return out


def paquetes_que_faltan(fijados: list[tuple[str, str]], instalados: dict[str, str]) -> list[str]:
    """Los `nombre==versión` fijados que no están instalados con esa versión exacta."""
    return [f"{n}=={v}" for n, v in fijados if instalados.get(n) != v]


# ---------------------------------------------------------------- configuración inicial (puro)
def config_desde_ejemplo(ejemplo: dict, home: Path) -> dict:
    """`config.example.json` con sus marcadores sustituidos: la raíz de proyectos de verdad (`<home>/Proyectos`, el valor por defecto de la app), el autor vacío (la app
    usa entonces el usuario de Windows) y sin los proyectos extra de ejemplo (rutas que no existen). Lo que no lleva marcador (`<…>`, «Tu Nombre») se conserva tal cual."""
    c = json.loads(json.dumps(ejemplo))
    if "<" in str(c.get("raiz_proyectos", "")):
        c["raiz_proyectos"] = str(Path(home) / "Proyectos")
    if str(c.get("autor", "")).strip().lower() == "tu nombre":
        c["autor"] = ""
    extras = [e for e in c.get("proyectos_extra", []) if isinstance(e, dict) and "<" not in str(e.get("ruta", ""))]
    c["proyectos_extra"] = extras
    return c


# ---------------------------------------------------------------- pasos
def paso_python(ent: Entorno, op: Opciones) -> Resultado:
    ver = tuple(ent.python_actual)[:2]
    if ver >= PYTHON_MINIMO:
        return Resultado("Python", "ya", f"Python {_version_texto(ent.python_actual)} (hace falta {_version_texto(PYTHON_MINIMO)} o superior).")
    return Resultado("Python", "falta", f"Este script corre con Python {_version_texto(ent.python_actual)} y se necesita {_version_texto(PYTHON_MINIMO)} o superior.",
                     pendiente=f"Instala Python {_version_texto(PYTHON_MINIMO)} o superior (python.org) y vuelve a ejecutar instalar.bat.")


def _version_del_venv(ent: Entorno):
    codigo, salida = ent.ejecutar([str(ent.venv_python), "--version"], timeout=60)
    m = re.search(r"(\d+)\.(\d+)(?:\.(\d+))?", salida or "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if codigo == 0 and m else None


def paso_venv(ent: Entorno, op: Opciones) -> Resultado:
    if ent.venv_python.is_file():
        v = _version_del_venv(ent)
        if v is None:
            return Resultado("Entorno (.venv)", "falta", "Existe la carpeta .venv pero su Python no arranca.",
                             pendiente="Cambia el nombre de la carpeta .venv (el instalador no la borra) y vuelve a ejecutar instalar.bat para crear una nueva.")
        if v[:2] < PYTHON_MINIMO:
            return Resultado("Entorno (.venv)", "falta", f"El entorno .venv usa Python {_version_texto(v)} y se necesita {_version_texto(PYTHON_MINIMO)} o superior.",
                             pendiente="Cambia el nombre de la carpeta .venv (el instalador no la borra) y vuelve a ejecutar instalar.bat para crear una nueva.")
        return Resultado("Entorno (.venv)", "ya", f"Entorno .venv con Python {_version_texto(v)}.")
    if ent.venv.exists():
        return Resultado("Entorno (.venv)", "falta", "Existe .venv pero no es un entorno de Python (falta su intérprete).",
                         pendiente="Cambia el nombre de .venv (el instalador no la borra) y vuelve a ejecutar instalar.bat.")
    if op.comprobar:
        return Resultado("Entorno (.venv)", "haria", "Crearía el entorno .venv.")
    codigo, salida = ent.ejecutar([ent.python_exe, "-m", "venv", str(ent.venv)], timeout=600)
    if codigo != 0 or not ent.venv_python.is_file():
        return Resultado("Entorno (.venv)", "error", "No se pudo crear el entorno: " + _cola(salida),
                         pendiente="Revisa el mensaje de arriba (¿Python instalado sin la opción de venv/pip?) y vuelve a ejecutar instalar.bat.")
    return Resultado("Entorno (.venv)", "hecho", "Entorno .venv creado.")


def _instalados(ent: Entorno) -> dict[str, str] | None:
    codigo, salida = ent.ejecutar([str(ent.venv_python), "-m", "pip", "list", "--format=json", "--disable-pip-version-check"], timeout=120)
    if codigo != 0:
        return None
    try:
        return {normalizar_paquete(p["name"]): p["version"] for p in json.loads(salida[salida.index("["):])}
    except (ValueError, KeyError, TypeError):
        return None


def paso_dependencias(ent: Entorno, op: Opciones) -> Resultado:
    nombre = "requirements-dev.txt" if op.dev else "requirements.txt"
    fichero = ent.raiz / nombre
    fijados = leer_requisitos(fichero)
    if not fijados:
        return Resultado("Dependencias", "error", f"No se encuentra {nombre} (o no fija ninguna versión).")
    instalados = _instalados(ent) if ent.venv_python.is_file() else {}
    faltan = paquetes_que_faltan(fijados, instalados) if instalados is not None else [f"{n}=={v}" for n, v in fijados]
    if ent.venv_python.is_file() and instalados is not None and not faltan:
        return Resultado("Dependencias", "ya", f"Los {len(fijados)} paquetes de {nombre} ya están instalados con su versión.")
    if op.comprobar:
        return Resultado("Dependencias", "haria", f"Instalaría {nombre}: faltan {len(faltan)} de {len(fijados)} paquetes.")
    ent.imprimir(f"      Instalando {nombre} (la primera vez descarga varios cientos de MB y puede tardar unos minutos)…")
    codigo, salida = ent.ejecutar([str(ent.venv_python), "-m", "pip", "install", "--disable-pip-version-check", "-r", str(fichero)], mostrar=True)
    if codigo != 0:
        return Resultado("Dependencias", "error", f"pip terminó con código {codigo}.", pendiente="Mira el error de pip de arriba (¿sin conexión?) y vuelve a ejecutar instalar.bat: retoma lo que falte.")
    return Resultado("Dependencias", "hecho", f"Instalado {nombre} ({len(fijados)} paquetes fijados).")


def ruta_config(ent: Entorno) -> Path:
    return ent.raiz / "datos" / "config.json"


def paso_config(ent: Entorno, op: Opciones) -> Resultado:
    destino = ruta_config(ent)
    if destino.exists():
        return Resultado("Configuración", "ya", "datos/config.json ya existe: no se toca.")
    ejemplo = ent.raiz / "config.example.json"
    if not ejemplo.is_file():
        return Resultado("Configuración", "error", "No se encuentra config.example.json.")
    if op.comprobar:
        return Resultado("Configuración", "haria", "Crearía datos/config.json a partir de config.example.json.")
    try:
        datos = config_desde_ejemplo(json.loads(ejemplo.read_text(encoding="utf-8")), ent.home)
        destino.parent.mkdir(parents=True, exist_ok=True)
        with open(destino, "x", encoding="utf-8") as f:   # modo «x»: si alguien lo crea a la vez, falla en vez de pisarlo
            f.write(json.dumps(datos, ensure_ascii=False, indent=2))
    except FileExistsError:
        return Resultado("Configuración", "ya", "datos/config.json ya existe: no se toca.")
    except (OSError, ValueError) as e:
        return Resultado("Configuración", "error", f"No se pudo crear datos/config.json: {e}")
    raiz = datos.get("raiz_proyectos", "")
    pendiente = "" if Path(raiz).is_dir() else f"Crea la carpeta de proyectos «{Path(raiz).name}» (o elige otra en Ajustes, sección Privacidad)."
    return Resultado("Configuración", "hecho", "datos/config.json creado a partir de config.example.json.", pendiente=pendiente)


def paso_carpetas(ent: Entorno, op: Opciones) -> Resultado:
    faltan = [c for c in CARPETAS_LOCALES if not (ent.raiz / c).is_dir()]
    if not faltan:
        return Resultado("Carpetas locales", "ya", "Existen todas (" + ", ".join(CARPETAS_LOCALES) + ").")
    if op.comprobar:
        return Resultado("Carpetas locales", "haria", "Crearía: " + ", ".join(faltan) + ".")
    creadas = []
    for c in faltan:
        try:
            (ent.raiz / c).mkdir(exist_ok=True)       # sin parents ni borrar nada: solo la carpeta, vacía
            creadas.append(c)
        except OSError as e:
            return Resultado("Carpetas locales", "error", f"No se pudo crear «{c}»: {e}")
    return Resultado("Carpetas locales", "hecho", "Creadas: " + ", ".join(creadas) + ".")


def paso_claude(ent: Entorno, op: Opciones) -> Resultado:
    """Solo `claude --version`: no gasta tokens y no abre sesión."""
    exe = ent.buscar("claude")
    if not exe:
        return Resultado("Claude Code", "falta", "No se encuentra «claude» en el PATH. Sin él hay transcripción, pero no análisis ni asesor.",
                         pendiente="Instala Claude Code, abre una terminal nueva, escribe «claude» y entra con tu cuenta.")
    codigo, salida = ent.ejecutar([exe, "--version"], timeout=30)
    if codigo != 0:
        return Resultado("Claude Code", "falta", "Está en el PATH, pero «claude --version» falla: " + _cola(salida),
                         pendiente="Reinstala Claude Code y comprueba «claude --version» en una terminal.")
    return Resultado("Claude Code", "ya", "claude " + (salida.strip().splitlines() or ["?"])[0][:60] + ".",
                     pendiente="Comprueba que has iniciado sesión: escribe «claude» en una terminal una vez (desde aquí no se puede saber).")


def modelo_configurado(ent: Entorno) -> str:
    """El modelo de Whisper de datos/config.json si existe y lo dice; si no, el de config.example.json; si no, `small`."""
    for ruta in (ruta_config(ent), ent.raiz / "config.example.json"):
        try:
            m = json.loads(ruta.read_text(encoding="utf-8")).get("whisper_modelo")
            if isinstance(m, str) and m.strip():
                return m.strip()
        except (OSError, ValueError, AttributeError):
            continue
    return MODELO_DEFECTO


def paso_modelo(ent: Entorno, op: Opciones) -> Resultado:
    modelo = modelo_configurado(ent)
    estado = _requisitos().comprobar_modelo(modelo, ent.raiz / "modelos")
    if estado["estado"] == "bien":
        return Resultado("Modelo de Whisper", "ya", f"Modelo «{modelo}» ya descargado.")
    if op.sin_modelo:
        return Resultado("Modelo de Whisper", "omitido", f"Modelo «{modelo}» sin descargar (--sin-modelo).",
                         pendiente="Modelo de Whisper: se descargará solo al empezar la primera reunión (hace falta conexión), o ejecuta instalar.bat sin --sin-modelo.")
    if op.comprobar:
        return Resultado("Modelo de Whisper", "haria", f"Ofrecería descargar el modelo «{modelo}».")
    if not ent.venv_python.is_file():
        return Resultado("Modelo de Whisper", "omitido", "Sin entorno no se puede descargar.", pendiente="Modelo de Whisper: descárgalo cuando el entorno esté creado (instalar.bat otra vez).")
    if op.si:
        acepta = True
    else:
        acepta = ent.preguntar(f"¿Descargar ahora el modelo de transcripción «{modelo}»? Son varios cientos de MB y se hace una sola vez.")
    if not acepta:
        return Resultado("Modelo de Whisper", "falta", f"Modelo «{modelo}» sin descargar" + ("" if acepta is False else " (no hay consola para preguntar)") + ".",
                         pendiente="Modelo de Whisper: se descargará solo al empezar la primera reunión (hace falta conexión), o ejecuta instalar.bat con --si.")
    (ent.raiz / "modelos").mkdir(exist_ok=True)
    codigo, salida = ent.ejecutar([str(ent.venv_python), "-c", DESCARGA_MODELO, modelo, str(ent.raiz / "modelos")], mostrar=True)
    if codigo != 0:
        return Resultado("Modelo de Whisper", "error", f"La descarga del modelo «{modelo}» falló (código {codigo}).",
                         pendiente="Comprueba la conexión y vuelve a ejecutar instalar.bat: retoma la descarga.")
    return Resultado("Modelo de Whisper", "hecho", f"Modelo «{modelo}» descargado.")


def ruta_acceso_directo(ent: Entorno) -> Path | None:
    """La misma ruta que `crear_acceso_directo.ruta_por_defecto` (menú Inicio del usuario); hay un test que las compara."""
    if not ent.appdata:
        return None
    return Path(ent.appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "WhisperMeet.lnk"


def paso_acceso_directo(ent: Entorno, op: Opciones) -> Resultado:
    if op.sin_acceso_directo:
        return Resultado("Acceso directo", "omitido", "No se crea (--sin-acceso-directo).")
    lnk = ruta_acceso_directo(ent)
    if lnk is None:
        return Resultado("Acceso directo", "falta", "No se puede saber dónde está el menú Inicio (falta APPDATA).", pendiente="Crea el acceso directo con crear_acceso_directo.py.")
    if lnk.exists():
        return Resultado("Acceso directo", "ya", "Ya existe «WhisperMeet» en el menú Inicio (no se recrea).")
    if op.comprobar:
        return Resultado("Acceso directo", "haria", "Crearía «WhisperMeet» en el menú Inicio (desde ahí, «Anclar a la barra de tareas»).")
    if not ent.venv_python.is_file():
        return Resultado("Acceso directo", "omitido", "Sin entorno no se puede crear.", pendiente="Ejecuta crear_acceso_directo.py cuando el entorno esté creado.")
    codigo, salida = ent.ejecutar([str(ent.venv_python), str(ent.raiz / "crear_acceso_directo.py")], timeout=120)
    if codigo != 0:
        return Resultado("Acceso directo", "error", "No se pudo crear: " + _cola(salida), pendiente="Ejecuta crear_acceso_directo.py a mano para ver el error.")
    return Resultado("Acceso directo", "hecho", "«WhisperMeet» creado en el menú Inicio (clic derecho, «Anclar a la barra de tareas»).")


def _cola(salida: str, n: int = 240) -> str:
    t = " ".join((salida or "").split())
    return t[-n:] if t else "sin detalle"


# ---------------------------------------------------------------- orquestación
def ejecutar_pasos(ent: Entorno, op: Opciones) -> list[Resultado]:
    """Todos los pasos, en orden. Los que dependen de un paso que ha fallado se omiten (con el motivo) en vez de fallar en cadena."""
    resultados: list[Resultado] = []

    def hacer(f) -> Resultado:
        r = f(ent, op)
        resultados.append(r)
        ent.imprimir(r.linea())
        return r

    py = hacer(paso_python)
    if py.estado == "falta":
        for nombre in ("Entorno (.venv)", "Dependencias", "Configuración", "Carpetas locales", "Claude Code", "Modelo de Whisper", "Acceso directo"):
            resultados.append(Resultado(nombre, "omitido", "Depende de Python."))
            ent.imprimir(resultados[-1].linea())
        return resultados
    venv = hacer(paso_venv)
    entorno_ok = venv.estado in ("ya", "hecho") or (op.comprobar and venv.estado == "haria")
    if entorno_ok:
        dep = hacer(paso_dependencias)
        dependencias_ok = dep.estado in ("ya", "hecho") or (op.comprobar and dep.estado == "haria")
    else:
        resultados.append(Resultado("Dependencias", "omitido", "Depende del entorno."))
        ent.imprimir(resultados[-1].linea())
        dependencias_ok = False
    hacer(paso_config)
    hacer(paso_carpetas)
    hacer(paso_claude)
    if dependencias_ok:
        hacer(paso_modelo)
        hacer(paso_acceso_directo)
    else:
        for nombre in ("Modelo de Whisper", "Acceso directo"):
            resultados.append(Resultado(nombre, "omitido", "Depende de las dependencias."))
            ent.imprimir(resultados[-1].linea())
    return resultados


def resumen(resultados: list[Resultado], op: Opciones) -> tuple[list[str], int]:
    """(líneas del resumen final, código de salida). Código 1 si un paso esencial (Python, entorno, dependencias) ha fallado o, con --comprobar, si falta algo por hacer.
    Que `claude` falte o que no se haya querido el modelo NO es un fallo del instalador: sale en «Queda por hacer a mano» y el código sigue siendo 0."""
    errores = [r for r in resultados if r.estado == "error"]
    esenciales = [r for r in resultados if r.estado == "falta" and r.paso in ("Python", "Entorno (.venv)")]
    faltas = [r for r in resultados if r.estado == "falta"]
    haria = [r for r in resultados if r.estado == "haria"]
    omitidos = [r for r in resultados if r.estado == "omitido" and r.pendiente]
    pendientes = []
    for r in resultados:
        if r.pendiente and r.pendiente not in pendientes:
            pendientes.append(r.pendiente)
    lineas = [""]
    if op.comprobar:
        lineas.append("Comprobación terminada: no se ha cambiado nada.")
        if haria:
            lineas.append("El instalador haría: " + "; ".join(r.paso for r in haria) + ".")
    elif errores or esenciales:
        lineas.append("La instalación no ha terminado: " + "; ".join(r.paso for r in errores + esenciales) + ".")
    elif faltas or omitidos:
        lineas.append("Instalación terminada, con cosas por hacer a mano.")
    else:
        lineas.append("Instalación terminada.")
    if pendientes:
        lineas.append("Queda por hacer a mano:")
        lineas += [f"  - {p}" for p in pendientes]
    if not errores and not esenciales and not (op.comprobar and (haria or faltas)):
        lineas.append("Para empezar: abre «WhisperMeet» del menú Inicio, o ejecuta .venv\\Scripts\\python.exe app.py. La app te dice si algo más falta (panel «Antes de la primera reunión»).")
    codigo = 1 if (errores or esenciales or (op.comprobar and (haria or faltas))) else 0
    return lineas, codigo


def principal(argv=None, ent: Entorno | None = None) -> int:
    ap = argparse.ArgumentParser(description="Instala WhisperMeet: entorno, dependencias, configuración, carpetas, modelo de Whisper y acceso directo.")
    ap.add_argument("--comprobar", action="store_true", help="no cambia nada: dice qué haría y qué falta")
    ap.add_argument("--dev", action="store_true", help="instala también lo de desarrollo (requirements-dev.txt)")
    ap.add_argument("--si", action="store_true", help="no pregunta: acepta descargar el modelo de Whisper")
    ap.add_argument("--sin-modelo", action="store_true", help="no descarga el modelo de Whisper (y no lo pregunta)")
    ap.add_argument("--sin-acceso-directo", action="store_true", help="no crea el acceso directo del menú Inicio")
    a = ap.parse_args(argv)
    op = Opciones(a.comprobar, a.dev, a.si, a.sin_modelo, a.sin_acceso_directo)
    ent = ent or Entorno()
    ent.imprimir("WhisperMeet: " + ("comprobación de la instalación (no cambia nada)" if op.comprobar else "instalación"))
    ent.imprimir("")
    resultados = ejecutar_pasos(ent, op)
    lineas, codigo = resumen(resultados, op)
    for linea in lineas:
        ent.imprimir(linea)
    return codigo


if __name__ == "__main__":
    for flujo in (sys.stdout, sys.stderr):
        try:
            flujo.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(principal())
