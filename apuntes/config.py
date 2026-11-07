"""Configuración persistente (datos/config.json). Sin secretos: no se guarda ninguna clave."""
from __future__ import annotations

import contextlib
import copy
import getpass
import json
import threading
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
ASESOR_SONNET_HORA = 8   # llamadas sonnet del asesor por hora de reunión (escaladas y consejos estratégicos automáticos; «Profundizar» lo pulsa el usuario y no se bloquea)
AVISO_CADUCA_S = 45   # aviso flotante de llamada de Teams: sin tocarlo, se cierra a los N s (el ratón encima lo pausa) y no vuelve en esa llamada
DATOS_DIR = APP_DIR / "datos"
CACHE_DIR = APP_DIR / "cache"
BANDEJA_DIR = APP_DIR / "bandeja"
PLANES_DIR = APP_DIR / "planes"          # planes de sesiones (JSON locales, fuera de git)
CHECKS_DIR = APP_DIR / "checks"          # checks de preparación por proyecto y sesión (locales, fuera de git)
SESIONES_DIR = APP_DIR / "sesiones"      # transcripciones de proyectos compartidos (locales, fuera de git)
BACKLOG_DIR = APP_DIR / "backlog"        # estado local del backlog (estado.json: hecho/descartado/aprovechada y temas renombrados; fuera de git)
PLANTILLAS_DIR = APP_DIR / "plantillas" / "contexto"
WEB_DIR = APP_DIR / "web"
CLAUDE_CWD = DATOS_DIR / "claude_cwd"  # directorio neutro y vacío para `claude -p`

# Reparto de modelos: un único sitio. Nunca opus por defecto.
MODELOS_POR_DEFECTO = {
    "digest": "haiku",                  # contexto compacto, una vez por proyecto (cacheado)
    "periodico": "haiku",               # análisis periódico y «Analizar ahora»
    "contradicciones_marcar": "haiku",  # candidatas con cita del contexto (va dentro del periódico)
    "contradicciones_confirmar": "sonnet",  # llamada corta, solo si hay candidatas
    "final": "sonnet",                  # resumen final y cambios al contexto, una vez por reunión
    "consulta": "haiku",                # «Pregúntale»: una llamada por pregunta, solo si el usuario la lanza
    "consulta_sonnet": "sonnet",        # lo mismo, si el usuario elige sonnet para esa pregunta
    "equipo": "haiku",                  # los cuatro perfiles del equipo (un turno = una llamada corta)
    "contexto_reunion": "haiku",        # «Generar con Claude» en el inicio: UNA llamada, solo al pulsarlo, sin reintentos
    # ÚNICA excepción a «nunca opus»: solo al pulsar «Pulir con Opus» en la revisión (nunca automático, una llamada)
    "pulido": "opus",
    # El asesor en directo (apuntes/asesor.py): haiku al momento, sonnet en lo estratégico o al pulsar «Profundizar»
    "asesor_respuesta": "haiku",            # respuesta sugerida a una pregunta del cliente (con prioridad sobre los turnos)
    "asesor_respuesta_sonnet": "sonnet",    # la misma pregunta, si toca precio, alcance, plazos, contrato, competencia o compromiso
    "asesor_consejo": "haiku",              # el Estratega (quinto perfil del equipo): consejos de valor
    "asesor_consejo_sonnet": "sonnet",      # el Estratega con señales estratégicas (hasta ASESOR_SONNET_HORA por hora)
    "asesor_profundizar": "sonnet",         # botón «Profundizar»: UNA llamada con más extractos y, si el usuario lo marca, búsqueda web
    # ola 3 (capa agéntica)
    "brief": "haiku",                       # brief de preparación de un proyecto: UNA llamada al abrir la ficha (cacheada por hash de entrada)
    "pregunta_capitan": "haiku",            # pregunta propuesta por el Capitán para cerrar un objetivo sin tratar: una llamada ligera, una vez por objetivo
}

# Proyectos fuera de la raíz. `compartido: true` = carpeta de OneDrive compartida y de otra persona:
# la sesión se guarda en local (apuntes\sesiones\<proyecto>) y nunca se crea «02. Sesiones» allí.
# Vacío por defecto: cada instalación declara los suyos en datos/config.json (`proyectos_extra`).
PROYECTOS_EXTRA_POR_DEFECTO: list[dict] = []

# ola 3: autonomía por tipo de acción. «hacer» SOLO en lo local y reversible (marcar, consolidar, preaceptar); nada se envía fuera sin clic.
TIPOS_ACCION = ("pregunta", "pendiente", "cambio_contexto", "correo", "recordatorio")
TIPOS_AUTONOMIA = TIPOS_ACCION + ("consolidar_pendientes",)
NIVELES_AUTONOMIA = ("avisar", "proponer", "hacer")
HACER_ADMITIDO = ("cambio_contexto", "consolidar_pendientes")
AUTONOMIA_POR_DEFECTO = {t: ("hacer" if t == "consolidar_pendientes" else "proponer") for t in TIPOS_AUTONOMIA}


def validar_autonomia(cambios, base: dict | None = None) -> dict:
    """Mezcla `cambios` ({tipo: nivel}) con `base` y devuelve el resultado. ValueError si un tipo o un nivel no existe, o si se pide «hacer» donde no se admite."""
    if not isinstance(cambios, dict):
        raise ValueError("La autonomía debe ser un objeto {tipo: nivel}.")
    out = dict(base or AUTONOMIA_POR_DEFECTO)
    for t, n in cambios.items():
        if t not in TIPOS_AUTONOMIA:
            raise ValueError(f"Tipo de acción desconocido: {t}.")
        if n not in NIVELES_AUTONOMIA:
            raise ValueError("El nivel debe ser avisar, proponer o hacer.")
        if n == "hacer" and t not in HACER_ADMITIDO:
            raise ValueError("«Hacer» solo se admite para lo local y reversible (" + ", ".join(HACER_ADMITIDO) + "); lo demás se propone y decides tú.")
        out[t] = n
    return out


DEFAULTS: dict = {
    "raiz_proyectos": str(Path.home() / "Proyectos"),
    "knowledge": "",                       # carpeta de conocimiento de solo lectura (vacío = sin Knowledge)
    "autor": "",                           # vacío = el usuario del sistema operativo (ver Config.__getitem__)
    "idioma": "auto",                      # idioma de la reunión si la petición no trae uno: auto | es | ca (un «es» guardado sigue valiendo)
    "idiomas_auto": ["es", "ca", "en"],          # entre cuáles elige el modo automático: nunca acaba en otro idioma por un error de detección
    "whisper_modelo": "small",
    "whisper_beam": 5,
    "whisper_hilos": 6,
    "whisper_vad": True,                   # Silero VAD de faster-whisper sobre cada fragmento (recorta silencios y ruido de sala; menos alucinaciones)
    "whisper_vad_min_silencio_ms": 500,    # silencio mínimo para separar dos tramos de voz dentro del fragmento
    "vocabulario_transcripcion": [],       # términos propios para el prompt de Whisper (mandan sobre los extraídos del contexto)
    "proyectos_extra": PROYECTOS_EXTRA_POR_DEFECTO,
    "modelos": MODELOS_POR_DEFECTO,
    "esfuerzo": "low",
    "sin_razonamiento": ["digest", "periodico", "consulta", "equipo", "contexto_reunion", "brief", "pregunta_capitan"],  # tareas haiku: sin tokens de razonamiento
    "timeout_s": 240,
    "cadencia_min": 5,
    "cadencia_defecto": "equipo",          # equipo | 5 | 10 | manual (selector de inicio; «adaptativo» de versiones anteriores = equipo)
    "min_palabras_analisis": 150,
    # Disparo adaptativo (apuntes/disparo.py): el reloj comprueba en local, sin LLM
    "adaptativo_comprobar_s": 30,          # cada cuánto mira si toca analizar
    "adaptativo_palabras_senal": 120,      # palabras nuevas mínimas para analizar por señal local
    "adaptativo_espera_senal_s": 240,      # enfriamiento mínimo desde el último análisis para el disparo por señal
    "adaptativo_tope_s": 300,              # tope por tiempo
    "adaptativo_palabras_tope": 150,       # palabras nuevas mínimas para analizar al llegar al tope
    # El equipo (apuntes/equipo): el Monitor local mira cada `adaptativo_comprobar_s` y reparte turnos a cuatro perfiles haiku
    "equipo_puntuacion_min": 3,            # puntos de señales locales para que un perfil pueda hablar
    "equipo_enfriamiento_global_s": 240,   # entre dos llamadas de perfil cualesquiera (150 s daban 21-24 turnos/hora en TR2; 240 s, 13)
    "equipo_enfriamiento_perfil_s": 360,   # entre dos turnos del mismo perfil
    "equipo_rotacion_s": 300,              # sin candidato: turno rotatorio si pasó este tiempo desde la última llamada
    "equipo_palabras_min": 120,            # palabras nuevas desde su último turno para que un perfil hable por puntuación
    "equipo_chars_nuevo": 4000,            # transcripción nueva máxima por turno (las últimas, si hay más)
    "equipo_toque_repetido_s": 120,        # un objetivo ya tocado no genera otra entrada en el Minuto a minuto hasta pasado este tiempo
    "equipo_silencio_aviso_s": 300,        # el aviso «N palabras nuevas · nadie tiene turno» sale como mucho una vez cada tanto
    "equipo_rotacion_palabras": 150,       # palabras nuevas que necesita el perfil más antiguo para un turno de rotación
    "asesor_separacion_llamada_s": 90,     # el Estratega no se pega a la llamada de otro perfil: espera este tiempo desde la última
    "asesor_rotacion_s": 480,              # sin señales estratégicas, el Estratega rota si pasó este tiempo desde su último turno…
    "asesor_rotacion_palabras": 200,       # …y hay al menos tantas palabras nuevas
    "equipo_objetivo_sin_tratar_min": 15,  # un objetivo sin tocar desde hace tanto genera aviso en el Minuto a minuto
    "final_max_ficheros": 3,               # ficheros de contexto que viajan al resumen final (antes 4): el cierre de sonnet es lo más caro de la reunión
    "final_tope_fichero": 4000,            # caracteres de cada uno (antes 5.000)
    "final_chars_tramo": 6000,             # transcripción aún no analizada que viaja al cierre (antes 12.000)
    "final_chars_huecos": 20000,           # transcripción de lo que ningún análisis leyó (sin eco), tramo a tramo, que viaja al cierre. Medido con una reunión real de 12 min:
                                           # 18.500 caracteres en bruto (19.400 con las etiquetas «[MM:SS] M:») y 14.000 sin eco: entra ENTERA con o sin filtro. Si hay más,
                                           # el recorte se reparte entre todos los tramos y la revisión avisa de los minutos que quedan fuera
    "filtrar_eco": True,                   # quita de Micro lo que ya dijo Reunión (apuntes/eco.py): local, sin modelo y sin audio a disco
    "presupuesto_tokens_hora": 60000,      # tokens por hora de reunión (ventana deslizante de 60 min); al 80 % ahorro, al 100 % solo a petición
    # Asesor en directo (respuestas sugeridas, Estratega y Profundizar): presupuesto PROPIO, aparte del del equipo
    "asesor_activo": True,                 # detecta preguntas del cliente y propone qué responder; sin él, la app se comporta como antes
    "presupuesto_asesor_tokens_hora": 100000,   # tokens por hora de reunión de TODAS las llamadas del asesor (al 80 % sin sonnet automático; al 100 % solo «Profundizar»)
    "asesor_respuesta_cada_s": 20,         # como mucho una respuesta sugerida cada tanto; si llegan varias preguntas, gana la más reciente
    "asesor_chars_extractos": 3500,        # extractos de fuentes que viajan con una respuesta sugerida
    "asesor_chars_extractos_profundizar": 9000,   # y con «Profundizar»
    "asesor_chars_transcripcion": 2500,    # últimas líneas de la reunión que viajan con una respuesta sugerida
    "asesor_max_consejos": 14,             # consejos del Estratega como máximo por reunión (sin duplicados con las tarjetas ni entre sí)
    "asesor_consejo_cada_s": 360,          # enfriamiento propio del Estratega (el doble al 80 % del presupuesto del asesor)
    "asesor_web": True,                    # ofrece la casilla «Buscar también en la web» en «Profundizar» (nunca automática; solo si `claude -p` lo permite)
    "fuentes_max_ficheros": 800,           # ficheros de Knowledge que se indexan como máximo (el resto, en la pasada siguiente)
    "fuentes_tiempo_s": 40,                # tiempo máximo de una pasada de indexado de Knowledge (OneDrive lento = índice parcial, nunca bloquea)
    # Pregúntale
    "consulta_lineas": 40,                 # últimas líneas de transcripción que viajan con la pregunta
    "consulta_chars_transcripcion": 5000,  # tope de caracteres de esas líneas
    "consulta_chars_extractos": 6000,      # tope total de extractos de ficheros (solo si la pregunta los nombra)
    "consulta_max_ficheros": 3,
    "max_objetivos_sugeridos": 5,          # el digest puede sugerir hasta 5 objetivos y 8 checks (proyecto sin plan)
    "excluir_captura": True,
    "ultimo_proyecto": "",                 # el último proyecto con el que se empezó a grabar (vacío = Bandeja): lo propone el aviso flotante de llamada
    "ultimo_idioma": "auto",               # el último idioma de reunión elegido al empezar (auto | es | ca)
    "detectar_llamadas": True,             # propone grabar cuando Teams usa el micro (apuntes/llamadas.py); nunca graba sola
    # Modo reunión: medidas recordadas de los paneles (px CSS; None = 25 % del ancho) y opacidad (60-100)
    "modo_reunion": {"izq": None, "der": None, "uno": None, "opacidad": 100},
    "dispositivo_mic": None,
    "dispositivo_sistema": None,
    "tope_digest_chars": 4500,             # ~1.200 tokens de salida del digest (antes 6000 -> ~2.400 medidos)
    "tope_resumen_chars": 2500,            # resumen acumulado que viaja en cada análisis periódico (el del final se guarda entero)
    "max_tarjetas_analisis": 3,            # tarjetas nuevas como máximo por análisis (por prioridad)
    "max_candidatas_confirmar": 8,         # candidatas a contradicción como máximo por reunión (van a UNA llamada de sonnet al terminar)
    "tope_fichero_bytes": 200_000,
    # Contexto ampliado de cada proyecto (apuntes/contexto.py): 00. CONTEXTO + CLAUDE.md/AGENTS.md/README.md + el resto de .md (solo lectura)
    "contexto_md_max_ficheros": 80,        # .md del proyecto que se leen como máximo (por prioridad: 00. CONTEXTO, CLAUDE.md…, cercanía a la raíz y novedad)
    "contexto_md_profundidad": 4,          # niveles de subcarpetas que se recorren
    "contexto_md_tope_total_chars": 14000, # caracteres de contexto que entran en el digest (como siempre; subirlo gasta más tokens por reunión)
    # ola 3: capa agéntica (apuntes/acciones.py, brief.py, seguimiento.py, api_ola3.py)
    "autonomia": dict(AUTONOMIA_POR_DEFECTO),   # por tipo de acción: avisar | proponer | hacer («hacer» solo en lo local y reversible: ver HACER_ADMITIDO)
    "objetivo_sin_tratar_min": 10,         # minutos sin tocar un objetivo para que el Capitán proponga la pregunta que lo cierra (una por objetivo)
    "seguimiento_umbral": 0.6,             # fracción de las palabras clave de un pendiente que debe aparecer en una frase de una sesión posterior para darlo por hecho
    "brief_max_chars": 6000,               # tope de caracteres de la última sesión y los pendientes que viajan a la llamada del brief
    # ola 4: confianza y escala (palabras dudosas, silencio, envíos, modo solo local, cartera)
    "whisper_palabras": True,              # word_timestamps: cada segmento lleva sus palabras con probabilidad (algo más de CPU por fragmento)
    "palabra_dudosa_umbral": 0.5,          # una palabra con probabilidad menor que esto se marca como dudosa
    "modo_local": False,                   # sin agentes en vivo: solo transcripción y Monitor; ninguna llamada sale (conmutable por sesión)
    "cartera_ventana_dias": 30,            # «sesiones recientes» de la vista de cartera
    "cartera_pendiente_antiguo_dias": 14,  # un pendiente abierto de hace más de estos días cuenta como antiguo
}

_CLAVES_LISTA = {"sin_razonamiento"}
_CLAVES_STR = {"raiz_proyectos", "knowledge", "autor", "whisper_modelo", "esfuerzo", "ultimo_proyecto"}
IDIOMAS_REUNION = ("auto", "es", "ca", "en")   # valores válidos de «Idioma de la reunión»
IDIOMAS_FIJOS = ("es", "ca", "en")             # idiomas concretos que sabe tratar la app (prompt de Whisper, filtros, señales)
_CADENCIAS = {"equipo", "adaptativo", "5", "10", "manual"}
_CLAVES_INT = {"whisper_beam", "whisper_hilos", "timeout_s", "cadencia_min", "min_palabras_analisis",
               "tope_digest_chars", "tope_resumen_chars", "tope_fichero_bytes", "max_tarjetas_analisis",
               "max_candidatas_confirmar",
               "adaptativo_comprobar_s", "adaptativo_palabras_senal", "adaptativo_espera_senal_s", "adaptativo_tope_s",
               "adaptativo_palabras_tope", "equipo_puntuacion_min", "equipo_enfriamiento_global_s", "equipo_enfriamiento_perfil_s",
               "equipo_rotacion_s", "equipo_palabras_min", "equipo_chars_nuevo", "equipo_objetivo_sin_tratar_min", "equipo_toque_repetido_s", "equipo_silencio_aviso_s", "equipo_rotacion_palabras",
               "asesor_separacion_llamada_s", "asesor_rotacion_s", "asesor_rotacion_palabras", "whisper_vad_min_silencio_ms", "presupuesto_tokens_hora", "final_max_ficheros", "final_tope_fichero", "final_chars_tramo", "final_chars_huecos",
               "consulta_lineas", "consulta_chars_transcripcion", "consulta_chars_extractos",
               "consulta_max_ficheros", "max_objetivos_sugeridos", "presupuesto_asesor_tokens_hora", "asesor_respuesta_cada_s",
               "asesor_chars_extractos", "asesor_chars_extractos_profundizar", "asesor_chars_transcripcion", "asesor_max_consejos",
               "asesor_consejo_cada_s", "fuentes_max_ficheros", "fuentes_tiempo_s",
               "contexto_md_max_ficheros", "contexto_md_profundidad", "contexto_md_tope_total_chars",
               "objetivo_sin_tratar_min", "brief_max_chars"}   # ola 3
_ESFUERZOS = {"low", "medium", "high", "xhigh", "max", ""}
# ola 4: tipos de sus claves (bloque propio; `Config.actualizar` solo tiene una rama para ellas)
_OLA4_BOOL = {"whisper_palabras", "modo_local"}
_OLA4_INT = {"cartera_ventana_dias", "cartera_pendiente_antiguo_dias"}


def _validar_extras(lista: list) -> list[dict]:
    """Solo forma y tipos; la comprobación de rutas la hace el Guardian."""
    out, vistos = [], set()
    for e in lista:
        if not isinstance(e, dict):
            continue
        nombre, ruta = e.get("nombre"), e.get("ruta")
        if not (isinstance(nombre, str) and isinstance(ruta, str) and nombre.strip() and ruta.strip()):
            continue
        if nombre.strip().lower() in vistos:
            continue
        vistos.add(nombre.strip().lower())
        out.append({"nombre": nombre.strip(), "ruta": ruta.strip(), "compartido": e.get("compartido") is True})
    return out


def validar_idioma(valor, defecto: str | None = None) -> str:
    """«auto», «es» o «ca» (sin importar mayúsculas ni espacios). Cualquier otra cosa: ValueError, o `defecto` si se da."""
    v = valor.strip().lower() if isinstance(valor, str) else None
    if v in IDIOMAS_REUNION:
        return v
    if defecto is not None:
        return defecto
    raise ValueError("El idioma de la reunión debe ser automático (auto), español (es), catalán (ca) o inglés (en).")


def _validar_idiomas_auto(lista: list) -> list[str]:
    """Subconjunto sin repetir de es/ca/en, en el orden dado (el primero es el de partida mientras no haya ningún idioma previo)."""
    out = []
    for x in lista:
        x = x.strip().lower() if isinstance(x, str) else None
        if x in IDIOMAS_FIJOS and x not in out:
            out.append(x)
    return out


def _validar_vocabulario(lista: list) -> list[str]:
    """Términos de texto (≤40 caracteres, sin repetir ignorando mayúsculas, máximo 60)."""
    out, vistos = [], set()
    for t in lista:
        if not isinstance(t, str):
            continue
        t = " ".join(t.split())
        if t and len(t) <= 40 and t.lower() not in vistos:
            vistos.add(t.lower())
            out.append(t)
    return out[:60]


class Config:
    def __init__(self, ruta: Path | None = None):
        self.ruta = ruta or (DATOS_DIR / "config.json")
        self._lock = threading.Lock()
        self.datos = copy.deepcopy(DEFAULTS)
        self._solo_sesion: dict = {}  # valor persistente de las claves cambiadas solo para esta ejecución
        self.cargar()

    def cargar(self) -> None:
        try:
            crudo = json.loads(self.ruta.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(crudo, dict):
            self.actualizar(crudo, guardar=False)

    def guardar(self) -> None:
        try:
            self.ruta.parent.mkdir(parents=True, exist_ok=True)
            self.ruta.write_text(json.dumps({**self.datos, **self._solo_sesion}, ensure_ascii=False, indent=2), encoding="utf-8")
        except OSError:
            pass

    def actualizar(self, cambios: dict, guardar: bool = True, solo_sesion: bool = False) -> None:
        """Valida tipos y descarta claves desconocidas. `solo_sesion`: opciones de arranque que nunca llegan a disco,
        aunque después se guarde otra clave; un cambio guardado de esa misma clave vuelve a ser persistente."""
        with self._lock:
            for k in cambios:
                if k in DEFAULTS:
                    if solo_sesion:
                        self._solo_sesion.setdefault(k, copy.deepcopy(self.datos[k]))
                    elif guardar:
                        self._solo_sesion.pop(k, None)
            for k, v in cambios.items():
                if k not in DEFAULTS:
                    continue
                if k == "modelos" and isinstance(v, dict):
                    for kk, vv in v.items():
                        if kk in MODELOS_POR_DEFECTO and isinstance(vv, str) and vv.strip():
                            self.datos["modelos"][kk] = vv.strip()
                elif k == "modo_reunion" and isinstance(v, dict):
                    for kk in ("izq", "der", "uno"):
                        if kk in v and (v[kk] is None or (isinstance(v[kk], (int, float)) and not isinstance(v[kk], bool) and 100 <= v[kk] <= 4000)):
                            self.datos[k][kk] = None if v[kk] is None else round(v[kk])
                    if isinstance(v.get("opacidad"), (int, float)) and not isinstance(v["opacidad"], bool):
                        self.datos[k]["opacidad"] = max(60, min(100, round(v["opacidad"])))
                elif k == "autonomia" and isinstance(v, dict):   # ola 3: lo no válido se descarta (la API lo rechaza antes con un error claro)
                    for kk, vv in v.items():
                        with contextlib.suppress(ValueError):
                            self.datos[k] = validar_autonomia({kk: vv}, self.datos[k])
                elif k in _OLA4_BOOL and isinstance(v, bool):   # ola 4
                    self.datos[k] = v
                elif k in _OLA4_INT and isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 3650:
                    self.datos[k] = v
                elif k == "palabra_dudosa_umbral" and isinstance(v, (int, float)) and not isinstance(v, bool) and 0.0 <= v <= 1.0:
                    self.datos[k] = float(v)
                elif k == "seguimiento_umbral" and isinstance(v, (int, float)) and not isinstance(v, bool) and 0.2 <= v <= 1.0:
                    self.datos[k] = float(v)
                elif k == "proyectos_extra" and isinstance(v, list):
                    self.datos[k] = _validar_extras(v)
                elif k == "vocabulario_transcripcion" and isinstance(v, list):
                    self.datos[k] = _validar_vocabulario(v)
                elif k in ("idioma", "ultimo_idioma"):
                    self.datos[k] = validar_idioma(v, defecto=self.datos[k])
                elif k == "idiomas_auto" and isinstance(v, list):
                    validos = _validar_idiomas_auto(v)
                    if validos:
                        self.datos[k] = validos
                elif k in _CLAVES_LISTA and isinstance(v, list):
                    self.datos[k] = [x for x in v if x in MODELOS_POR_DEFECTO]
                elif k in _CLAVES_STR and isinstance(v, str):
                    if k == "esfuerzo" and v not in _ESFUERZOS:
                        continue
                    self.datos[k] = v.strip()
                elif k in _CLAVES_INT and isinstance(v, int) and not isinstance(v, bool) and v >= 0:
                    self.datos[k] = v
                elif k == "cadencia_defecto" and str(v) in _CADENCIAS:
                    self.datos[k] = "equipo" if str(v) == "adaptativo" else str(v)
                elif k in ("excluir_captura", "detectar_llamadas", "filtrar_eco", "asesor_activo", "asesor_web", "whisper_vad") and isinstance(v, bool):
                    self.datos[k] = v
                elif k in ("dispositivo_mic", "dispositivo_sistema") and (v is None or isinstance(v, (int, str))):
                    self.datos[k] = v
            if self.datos["cadencia_min"] not in (5, 10):
                self.datos["cadencia_min"] = 5
            if guardar:
                self.guardar()

    def __getitem__(self, k):
        v = self.datos[k]
        if k == "autor" and not v:
            try:
                return getpass.getuser()
            except Exception:  # noqa: BLE001
                return "Autor"
        return v

    @staticmethod
    def clave(tarea: str) -> str:
        """Los turnos de los perfiles (`equipo_coordinador`…) comparten modelo y ajustes bajo la clave `equipo`."""
        return "equipo" if tarea.startswith("equipo_") else tarea

    def modelo(self, tarea: str) -> str:
        tarea = self.clave(tarea)
        return self.datos["modelos"].get(tarea) or MODELOS_POR_DEFECTO[tarea]

    def publico(self) -> dict:
        return copy.deepcopy(self.datos)
