"""Comprobación de requisitos de la app (ola D): lo que hace falta para llegar a la primera reunión.

Todo es BARATO y SIN EFECTOS: no llama a ningún modelo (ni gasta tokens), no abre el micrófono (solo enumera dispositivos), no descarga nada y no escribe
nada en disco (ni siquiera un fichero de prueba: la escritura de las carpetas locales se mira con `os.access`). Cada comprobación recibe sus dependencias
por parámetro para poder probarla con dobles.

Cada resultado es `{clave, titulo, estado: "bien" | "aviso" | "falta", detalle, como_arreglarlo}`. La respuesta no lleva rutas absolutas: de lo que el usuario
configuró (raíz de proyectos, Knowledge) solo sale el nombre de la carpeta final; de las carpetas locales de la app, su nombre."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from .analisis.claude_cli import localizar_claude
from .rutas import RutaProhibida

# Mínimo REAL: las versiones fijadas en requirements.txt (numpy 2.5 y av 19 exigen Python 3.12). El código de la app, por sí solo, funcionaría desde 3.9.
PYTHON_MINIMO = (3, 12)
ESTADOS = ("bien", "aviso", "falta")

# Repositorio de cada modelo de faster-whisper (copia de `faster_whisper.utils._MODELS` para no importar la librería, que es pesada; hay un test que las compara).
REPOS_WHISPER = {
    "tiny.en": "Systran/faster-whisper-tiny.en", "tiny": "Systran/faster-whisper-tiny",
    "base.en": "Systran/faster-whisper-base.en", "base": "Systran/faster-whisper-base",
    "small.en": "Systran/faster-whisper-small.en", "small": "Systran/faster-whisper-small",
    "medium.en": "Systran/faster-whisper-medium.en", "medium": "Systran/faster-whisper-medium",
    "large-v1": "Systran/faster-whisper-large-v1", "large-v2": "Systran/faster-whisper-large-v2",
    "large-v3": "Systran/faster-whisper-large-v3", "large": "Systran/faster-whisper-large-v3",
    "distil-large-v2": "Systran/faster-distil-whisper-large-v2", "distil-medium.en": "Systran/faster-distil-whisper-medium.en",
    "distil-small.en": "Systran/faster-distil-whisper-small.en", "distil-large-v3": "Systran/faster-distil-whisper-large-v3",
    "distil-large-v3.5": "distil-whisper/distil-large-v3.5-ct2",
    "large-v3-turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo", "turbo": "mobiuslabsgmbh/faster-whisper-large-v3-turbo",
}


def _r(clave: str, titulo: str, estado: str, detalle: str, como: str = "") -> dict:
    return {"clave": clave, "titulo": titulo, "estado": estado, "detalle": detalle, "como_arreglarlo": como}


def _micros(n: int) -> str:
    return f"{n} micrófono" + ("" if n == 1 else "s")


def _salidas(n: int) -> str:
    return f"{n} salida" + ("" if n == 1 else "s") + " de audio"


def nombre_carpeta(ruta) -> str:
    """Solo la carpeta final (nunca la ruta completa): lo único que sale de una ruta configurada por el usuario."""
    p = Path(str(ruta))
    return p.name or p.drive.rstrip(":\\/") or "(raíz de unidad)"


def escribible(ruta) -> bool:
    """¿Se podría escribir en esta carpeta (o, si aún no existe, en la primera carpeta existente por encima)? No crea ni escribe nada: `os.access`."""
    p = Path(str(ruta))
    while not p.exists() and p.parent != p:
        p = p.parent
    return p.is_dir() and os.access(p, os.W_OK)


# ---------------------------------------------------------------- una comprobación por función
def comprobar_python(version=None) -> dict:
    v = tuple(version if version is not None else sys.version_info[:3])
    texto = ".".join(str(x) for x in v[:3])
    minimo = ".".join(str(x) for x in PYTHON_MINIMO)
    if v[:2] >= PYTHON_MINIMO:
        return _r("python", "Python", "bien", f"Python {texto}.")
    return _r("python", "Python", "falta", f"Esta app corre con Python {texto} y necesita {minimo} o superior.",
              f"Instala Python {minimo} o superior desde python.org y vuelve a ejecutar instalar.bat para crear el entorno de nuevo.")


def comprobar_claude(buscar=None) -> dict:
    """Solo localiza `claude` en el PATH (no lo ejecuta). No se puede saber desde aquí si has iniciado sesión: eso se ve la primera vez que se usa."""
    exe = localizar_claude(buscar)
    if exe:
        return _r("claude", "Claude Code (claude)", "bien", "Se encuentra «claude» en el PATH. Desde aquí no se puede saber si has iniciado sesión: si el primer análisis falla por eso, escribe «claude» en una terminal y entra con tu cuenta.")
    return _r("claude", "Claude Code (claude)", "falta", "No se encuentra «claude» en el PATH. Sin él la transcripción funciona, pero no hay análisis, resúmenes ni asesor.",
              "Instala Claude Code, abre una terminal nueva, escribe «claude» y entra con tu cuenta. Después pulsa «Volver a comprobar».")


def _snapshot_completo(carpeta: Path) -> bool:
    try:
        return any((s / "model.bin").is_file() for s in (carpeta / "snapshots").iterdir() if s.is_dir())
    except OSError:
        return False


def comprobar_modelo(modelo, modelos_dir) -> dict:
    """El modelo de Whisper configurado, en la carpeta de modelos de la app (faster-whisper lo guarda como `models--<organización>--<nombre>`)."""
    modelo = str(modelo or "").strip()
    titulo = "Modelo de transcripción (Whisper)"
    como = ("Ejecuta instalar.bat y acepta descargar el modelo, o empieza una reunión con conexión a internet: se descarga la primera vez. "
            "También puedes elegir otro en Ajustes.")
    if not modelo:
        return _r("modelo_whisper", titulo, "falta", "No hay modelo de transcripción configurado.", "Elige uno en Ajustes (Audio, «Precisión de la transcripción»).")
    local = Path(modelo)
    if local.is_absolute() and local.is_dir():   # una carpeta propia con el modelo ya convertido
        if (local / "model.bin").is_file():
            return _r("modelo_whisper", titulo, "bien", f"Modelo de la carpeta «{nombre_carpeta(local)}».")
        return _r("modelo_whisper", titulo, "falta", f"La carpeta «{nombre_carpeta(local)}» no tiene un modelo (falta model.bin).", como)
    repo = REPOS_WHISPER.get(modelo)
    if repo is None:   # un identificador de otro repositorio: la misma convención de nombre de carpeta
        repo = modelo if "/" in modelo else None
    if repo is None:
        return _r("modelo_whisper", titulo, "falta", f"«{modelo}» no es un modelo que conozca la app.", "Elige uno de la lista en Ajustes (Audio, «Precisión de la transcripción»).")
    carpeta = Path(str(modelos_dir)) / ("models--" + repo.replace("/", "--"))
    if _snapshot_completo(carpeta):
        return _r("modelo_whisper", titulo, "bien", f"Modelo «{modelo}» descargado.")
    if carpeta.exists():
        return _r("modelo_whisper", titulo, "aviso", f"La descarga del modelo «{modelo}» parece incompleta.", como)
    return _r("modelo_whisper", titulo, "falta", f"El modelo «{modelo}» todavía no está descargado.", como)


def comprobar_nube(cfg, estado_clave: dict | None) -> dict | None:
    """Transcripción en la nube: None si el motor es local. SIN llamadas de red (no se envía nada ni se prueba el servicio: eso es el botón «Probar»).
    `estado_clave`: lo que da `ClaveNube.estado()` ({puesta, origen, error}); nunca lleva la clave."""
    try:
        if cfg["transcripcion_motor"] != "nube":
            return None
    except (KeyError, TypeError):
        return None
    titulo = "Transcripción en la nube"
    ec = estado_clave or {}
    if ec.get("puesta"):
        from urllib.parse import urlsplit
        try:
            host = urlsplit(str(cfg["nube_url_base"])).hostname or ""
        except ValueError:
            host = ""
        origen = "de la variable de entorno" if ec.get("origen") == "entorno" else "guardada cifrada en este equipo"
        return _r("nube", titulo, "bien", f"Con «{cfg['nube_modelo']}» en {host}; clave {origen}.")
    if ec.get("error"):
        return _r("nube", titulo, "aviso", str(ec["error"]))
    return _r("nube", titulo, "aviso", "Está activada pero no hay clave: las reuniones se transcribirán en este equipo.",
              "Pon la clave en Ajustes › Audio o en la variable WHISPERMEET_CLAVE_NUBE.")


def comprobar_audio(listar=None, en_uso: bool = False) -> dict:
    """¿Hay dispositivos de entrada de audio? Solo enumera (`audio.listar_dispositivos`): no abre ningún stream. `en_uso`: hay una reunión en curso, que ya
    tiene el audio abierto: no se vuelve a enumerar (no se toca el audio de una grabación en marcha) y se da por bueno."""
    titulo = "Micrófono y audio de la reunión"
    if en_uso:
        return _r("audio", titulo, "bien", "Hay una reunión en curso: el audio ya se está usando y no se vuelve a enumerar.")
    if listar is None:
        from .audio import listar_dispositivos as listar
    try:
        d = listar() or {}
    except Exception as e:  # noqa: BLE001 — una comprobación nunca debe romper la pantalla
        return _r("audio", titulo, "aviso", f"No se pudieron enumerar los dispositivos de audio ({type(e).__name__}).", "Vuelve a comprobar; si sigue igual, reinicia la app.")
    if d.get("error"):
        return _r("audio", titulo, "falta", "La biblioteca de audio no está disponible en este entorno.", "Ejecuta instalar.bat para instalar las dependencias.")
    entradas, salidas = d.get("entradas") or [], d.get("salidas") or []
    if not entradas:
        return _r("audio", titulo, "falta", "Windows no muestra ningún micrófono.", "Conecta un micrófono (o activa el integrado en Configuración, Sistema, Sonido) y pulsa «Volver a comprobar».")
    if not salidas:
        return _r("audio", titulo, "aviso", f"{_micros(len(entradas))}, pero ninguna salida de audio de la que recoger lo que dicen los demás.",
                  "Sin audio de la reunión solo se transcribe tu micrófono. Revisa los altavoces o auriculares que usa Windows.")
    return _r("audio", titulo, "bien", f"{_micros(len(entradas))} y {_salidas(len(salidas))}.")


def comprobar_carpetas(raiz_proyectos, knowledge, locales: dict | None = None, existe=None, puede_escribir=None, validar_knowledge=None) -> list[dict]:
    """`validar_knowledge(ruta)`: las reglas que Ajustes aplica a la carpeta de Knowledge (`Guardian.validar_knowledge`; lanza RutaProhibida). Un `config.json` escrito
    a mano puede traer una que hoy no se admitiría (raíz de unidad, carpeta personal, solape con proyectos): no se desactiva, pero se avisa."""
    existe = existe or (lambda p: Path(str(p)).is_dir())
    puede_escribir = puede_escribir or escribible
    out = []
    raiz = str(raiz_proyectos or "").strip()
    if raiz and existe(raiz):
        out.append(_r("carpeta_proyectos", "Carpeta de proyectos", "bien", f"Carpeta «{nombre_carpeta(raiz)}»."))
    elif raiz:
        out.append(_r("carpeta_proyectos", "Carpeta de proyectos", "falta", f"La carpeta «{nombre_carpeta(raiz)}» no existe.",
                      "Crea la carpeta o elige otra en Ajustes (Privacidad, «Carpeta que contiene tus proyectos»)."))
    else:
        out.append(_r("carpeta_proyectos", "Carpeta de proyectos", "falta", "No hay carpeta de proyectos configurada.", "Elígela en Ajustes (Privacidad)."))
    k = str(knowledge or "").strip()
    if not k:
        out.append(_r("carpeta_knowledge", "Carpeta de Knowledge", "bien", "Sin Knowledge: es opcional (documentos de consulta de solo lectura)."))
    elif existe(k):
        motivo = ""
        if validar_knowledge is not None:
            try:
                validar_knowledge(k)
            except RutaProhibida as e:
                motivo = str(e)
        if motivo:
            out.append(_r("carpeta_knowledge", "Carpeta de Knowledge", "aviso", f"La carpeta «{nombre_carpeta(k)}» está configurada, pero hoy no se admitiría como Knowledge. {motivo}",
                          "Cámbiala en Ajustes, Privacidad."))
        else:
            out.append(_r("carpeta_knowledge", "Carpeta de Knowledge", "bien", f"Carpeta «{nombre_carpeta(k)}» (solo lectura)."))
    else:
        out.append(_r("carpeta_knowledge", "Carpeta de Knowledge", "aviso", f"La carpeta «{nombre_carpeta(k)}» no existe o no está disponible (¿OneDrive sin conexión?).",
                      "Sin ella no se consultan esos documentos. Corrígela o vacíala en Ajustes (Privacidad)."))
    if locales:
        nombres = sorted(locales)
        mal = [n for n in nombres if not puede_escribir(locales[n])]
        if mal:
            out.append(_r("carpetas_locales", "Carpetas locales de la app", "falta", "No se puede escribir en: " + ", ".join(mal) + ".",
                          "Mueve la app a una carpeta donde tu usuario pueda escribir (por ejemplo, dentro de tu carpeta personal) o revisa los permisos de esas carpetas."))
        else:
            out.append(_r("carpetas_locales", "Carpetas locales de la app", "bien", "Se puede escribir donde la app guarda sus datos; las carpetas que falten se crean al usarlas."))
    return out


def carpetas_locales(guardian) -> dict[str, Path]:
    """Las carpetas locales donde escribe la app (nombre → ruta), de las que tenga el Guardian."""
    nombres = {"bandeja": "bandeja", "cache": "cache", "sesiones": "sesiones_locales", "planes": "planes", "checks": "checks", "backlog": "backlog",
               "tipos_documento": "tipos", "datos": "datos"}
    return {n: Path(str(getattr(guardian, a))) for n, a in nombres.items() if getattr(guardian, a, None)}


def comprobar_todo(cfg, guardian=None, *, version=None, buscar_claude=None, listar_audio=None, modelos_dir=None, existe=None, puede_escribir=None,
                   audio_en_uso: bool = False, clave_nube: dict | None = None) -> dict:
    """Todas las comprobaciones. -> {estado (la peor), faltan, avisos, comprobaciones: [...]}. `clave_nube`: `ClaveNube.estado()` (solo importa con el motor en la nube)."""
    if modelos_dir is None:
        from .transcripcion import MODELOS_DIR as modelos_dir
    modelo = comprobar_modelo(cfg["whisper_modelo"], modelos_dir)
    nube = comprobar_nube(cfg, clave_nube)
    if nube is not None:   # con la nube, Whisper local es el respaldo
        modelo["detalle"] += " Es el respaldo si falla la nube."
    lista = [comprobar_python(version), comprobar_claude(buscar_claude), modelo] + ([nube] if nube is not None else []) + [comprobar_audio(listar_audio, audio_en_uso)]
    validar = None
    if guardian is not None:
        from .config import APP_DIR
        validar = lambda k: guardian.validar_knowledge(k, raiz=cfg["raiz_proyectos"], apartadas=(APP_DIR,))   # noqa: E731
    lista += comprobar_carpetas(cfg["raiz_proyectos"], cfg["knowledge"], carpetas_locales(guardian) if guardian is not None else None, existe, puede_escribir, validar)
    return resumen(lista)


def resumen(lista: list[dict]) -> dict:
    faltan = sum(1 for x in lista if x["estado"] == "falta")
    avisos = sum(1 for x in lista if x["estado"] == "aviso")
    return {"estado": "falta" if faltan else ("aviso" if avisos else "bien"), "faltan": faltan, "avisos": avisos, "comprobaciones": lista}
