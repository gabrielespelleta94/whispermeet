"""Aviso de llamada de Teams: detecta cuándo Teams empieza a usar el micrófono y propone grabar (nunca graba sola).

Lee el registro de consentimiento de Windows (ConsentStore\\microphone, HKCU, solo lectura): cada aplicación tiene
LastUsedTimeStart y LastUsedTimeStop, y mientras usa el micro Start != 0 y Stop == 0. Cero tokens, cero modelos.
Teams nuevo aparece como subclave directa «MSTeams_…»; el clásico, bajo «NonPackaged», como «…teams.exe».
"""
from __future__ import annotations

import asyncio
import contextlib

try:
    import winreg
except ImportError:  # fuera de Windows no hay registro: nunca hay llamada detectada
    winreg = None

from .registro import registrar_error

RUTA_MICRO = r"Software\Microsoft\Windows\CurrentVersion\CapabilityAccessManager\ConsentStore\microphone"


def micro_en_uso(inicio: int, fin: int) -> bool:
    """Una aplicación usa el micro si empezó a usarlo y aún no ha soltado."""
    return inicio != 0 and fin == 0


def _subclaves(clave):
    """Nombres de las subclaves de `clave` (vacío si no tiene ninguna o no se puede leer)."""
    i = 0
    while True:
        try:
            yield winreg.EnumKey(clave, i)
        except OSError:
            return
        i += 1


def _valor(clave, nombre: str) -> int:
    """Valor numérico de la clave; ausente o ilegible cuenta como 0."""
    try:
        valor, _ = winreg.QueryValueEx(clave, nombre)
        return int(valor)
    except (OSError, TypeError, ValueError):
        return 0


def _rutas_teams(raiz) -> list[str]:
    """Subclaves del ConsentStore que son Teams: el nuevo (MSTeams_*) y el clásico (teams.exe bajo NonPackaged)."""
    rutas = []
    for nombre in _subclaves(raiz):
        bajo = nombre.lower()
        if bajo.startswith("msteams_"):
            rutas.append(nombre)
        elif bajo == "nonpackaged":
            with winreg.OpenKey(raiz, nombre) as no_empaquetadas:
                rutas += [f"{nombre}\\{exe}" for exe in _subclaves(no_empaquetadas) if exe.lower().endswith("teams.exe")]
    return rutas


def teams_usando_micro() -> bool:
    """True si Teams (nuevo o clásico) está usando el micro ahora. Nunca lanza: cualquier fallo cuenta como False."""
    if winreg is None:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUTA_MICRO) as raiz:
            for ruta in _rutas_teams(raiz):
                with winreg.OpenKey(raiz, ruta) as clave:
                    if micro_en_uso(_valor(clave, "LastUsedTimeStart"), _valor(clave, "LastUsedTimeStop")):
                        return True
    except Exception:  # noqa: BLE001 — una lectura fallida no debe tumbar la vigilancia
        return False
    return False


class DetectorLlamada:
    """Convierte lecturas sueltas del micro en eventos «inicio» y «fin» de una llamada.

    Una llamada empieza tras 2 lecturas seguidas con el micro en uso y termina tras 2 libres. Si ya se está grabando
    cuando empieza, la llamada queda vista y no avisa. Si se empieza a grabar durante un aviso, se da «fin» para
    quitarlo y no se repite en esa llamada.
    """

    def __init__(self):
        self.en_uso_seguidas = 0
        self.libre_seguidas = 0
        self.en_llamada = False   # hay una llamada contada (avisada o vista mientras se grababa)
        self.avisando = False     # se dio «inicio» y aún no «fin»

    def actualizar(self, en_uso: bool, ocupado: bool) -> str | None:
        """`ocupado`: la app ya está grabando o revisando una reunión. Devuelve «inicio», «fin» o None."""
        if en_uso:
            self.en_uso_seguidas += 1
            self.libre_seguidas = 0
        else:
            self.libre_seguidas += 1
            self.en_uso_seguidas = 0

        if not self.en_llamada:
            if self.en_uso_seguidas < 2:
                return None
            self.en_llamada = True
            if ocupado:
                return None                  # ya graba: la llamada queda vista, sin aviso
            self.avisando = True
            return "inicio"

        if self.avisando and ocupado:        # el usuario empezó a grabar: se quita el aviso y no vuelve a salir en esta llamada
            self.avisando = False
            return "fin"
        if self.libre_seguidas >= 2:         # el micro está libre: la llamada ha terminado; una nueva contará
            self.en_llamada = False
            if self.avisando:
                self.avisando = False
                return "fin"
        return None


async def vigilar_llamadas(gestor, cfg, al_avisar=None, intervalo: float = 5.0, leer=teams_usando_micro, aviso=None):
    """Bucle de fondo: lee el micro cada `intervalo` s y avisa a la interfaz. Una excepción en una vuelta no lo para.

    `aviso`: el aviso flotante (`aviso.AvisoLlamada`, solo con ventana nativa). Si lo abre, el banner de la pantalla de inicio no sale
    (el evento lleva `flotante=True`); si falla o no existe (`--sin-ventana`), banner y parpadeo de la barra de tareas como siempre."""
    detector = DetectorLlamada()
    while True:
        await asyncio.sleep(intervalo)
        try:
            detectar = cfg.datos.get("detectar_llamadas", True)
            en_uso = bool(await asyncio.to_thread(leer)) if detectar else False
            ocupado = gestor.estado != "inactivo"
            evento = detector.actualizar(en_uso, ocupado)
            if evento == "inicio":
                gestor.llamada = True
                flotante = False
                if aviso is not None:
                    try:
                        flotante = bool(await asyncio.to_thread(aviso.mostrar))   # crear la ventana espera a la interfaz nativa: fuera del bucle
                    except Exception as e:  # noqa: BLE001 — el aviso flotante falla: banner y parpadeo
                        registrar_error("vigilar_llamadas.aviso", e)
                gestor.llamada_flotante = flotante
                if flotante:
                    gestor.emitir("llamada", activa=True, flotante=True)
                else:
                    gestor.emitir("llamada", activa=True)
                    if al_avisar:
                        with contextlib.suppress(Exception):   # el aviso en la ventana nunca debe romper la vigilancia
                            al_avisar()
            elif evento == "fin":
                gestor.llamada = False
                gestor.llamada_flotante = False
                if aviso is not None:
                    with contextlib.suppress(Exception):
                        aviso.cerrar("fin")
                gestor.emitir("llamada", activa=False)
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            registrar_error("vigilar_llamadas", e)
