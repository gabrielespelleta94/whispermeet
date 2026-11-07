"""Monitor: el vigía local del equipo. Escucha cada 30 s, cuenta, detecta señales y reparte turnos. Cero tokens.

Todo es regex y aritmética sobre la transcripción (minúsculas y sin acentos): ni una llamada al modelo para decidir quién habla.
Las reglas son las de DESIGN-equipo.md §3. Una precisión que la especificación no resolvía: si dos señales casan el MISMO
fragmento («se encarga» es a la vez `pendiente` y `responsable`), el fragmento cuenta para una sola, la más específica; así «para el viernes»
+ «se encarga Ana» puntúa 4 para el Coordinador (fecha 2 + responsable 2) y no 5.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from ..disparo import _SENALES as _BASE
from ..rutas import sin_acentos
from ..texto import mmss, palabras
from .perfiles import ORDEN_ROTACION

ETIQUETA = {"decision": "decisión", "alcance": "alcance", "prioridad": "prioridad", "pendiente": "pendiente", "fecha": "fecha",
            "riesgo": "riesgo", "cifra": "cifra", "pregunta": "pregunta", "responsable": "responsable", "definicion": "definición",
            "regla": "regla", "dato": "dato", "sistema": "sistema", "contraste": "contraste",
            "toca": "toca objetivo", "sin_tratar": "objetivo sin tratar"}

_NUEVAS = {
    # Cada señal lleva, tras las palabras en español, las variantes catalanas que el español no usa (el texto llega sin acentos y en minúsculas).
    "responsable": r"\b(se encarga|me encargo|te encargas|lo lleva|lo hace|responsable|asignad[oa]|lo miro yo|lo mira|"
                   r"s.encarrega|m.encarrego|t.encarregues|ho porta|ho fa|assignat|assignada|ho miro jo|ho mira)\b",
    "definicion": r"\b(definimos|se define|se entiende por|entendemos por|llamamos|llamaremos|significa|quiere decir|es lo que llamamos|a eso le llamamos|"
                  r"definim|es defineix|s.enten per|entenem per|anomenem|anomenarem|vol dir|es el que anomenem|a aixo li diem)\b",
    "regla": r"\b(siempre que|solo si|salvo que|en ningun caso|obligatori[oa]|no se permite|tiene(n)? que|debe(n|ra|ria)?|la regla es|"
             r"sempre que|nomes si|tret que|en cap cas|obligatori(a|s|es)?|no es permet|cal que|haurien? de)\b",
    "dato": r"\b(tabla|campo|columna|api|integracion|interfaz|fichero|csv|excel|sap|base de datos|los datos|carga|exportar|importar|clave|sincroniza(r)?|"
            r"taula|camp|columna|interficie|fitxer|base de dades|les dades|els camps|carrega|clau|sincronitza(r)?)\b",
    "sistema": r"\b(power bi|fabric|sharepoint|teams|servidor|entorno|despliegue|produccion|desarrollo|portal|app|"
               r"entorn|desplegament|desenvolupament)\b",
    "contraste": r"\b(antes (era|estaba|dijimos)|en el documento|segun el (alcance|contexto|plan)|eso no es asi|no era asi|habiamos dicho|no estaba previsto|cambia respecto|"
                 r"abans (era|estava|vam dir|diem)|al document|segons (l.abast|el context|el pla)|aixo no es aixi|no era aixi|haviem dit|no estava previst|canvia respecte)\b",
}
# Orden de prioridad para el feed (las ocho de siempre y después las nuevas) y especificidad para desempatar fragmentos iguales.
ORDEN_SENALES = [sin_acentos(e).lower() for e, _ in _BASE] + list(_NUEVAS)
PATRONES: dict[str, re.Pattern] = {sin_acentos(e).lower(): p for e, p in _BASE}
PATRONES.update({k: re.compile(v) for k, v in _NUEVAS.items()})
ESPECIFICIDAD = ["definicion", "responsable", "contraste", "regla", "fecha", "alcance", "decision", "pendiente", "prioridad", "riesgo",
                 "pregunta", "dato", "sistema", "cifra"]

PUNTOS = {
    "coordinador": {"fecha": 2, "responsable": 2, "pendiente": 1, "decision": 1},
    "funcional": {"definicion": 3, "regla": 2, "alcance": 2, "pregunta": 1},
    "constructor": {"dato": 2, "sistema": 2, "cifra": 1, "riesgo": 1},
    "revisor": {"contraste": 3, "toca": 1, "sin_tratar": 1, "prioridad": 1},
}
MAX_ENTRADAS_PASADA = 4
CITA_MAX = 60

_VACIAS = set("""para como pero porque cuando donde sobre entre desde hasta este esta estos estas esto ese esa eso esos esas tiene tienen
tener hacer hace hacen puede pueden poder todo toda todos todas algo mas menos muy bien aqui alli vamos vale bueno entonces tambien ahora
luego despues antes siempre nunca cada otro otra otros otras sido sera seria seran estar estan estamos somos fue era eran habia hay habra
quien quienes cual cuales con por una uno unos unas del los las les nos sus mis tus sin ser son soy reunion sesion proyecto""".split())


def _norm(s: str) -> str:
    return sin_acentos(s or "").lower()


def _raiz(w: str) -> str:
    """Quita la s final: cupos = cupo."""
    return w[:-2] if w.endswith("es") and len(w) > 6 else (w[:-1] if w.endswith("s") and len(w) > 5 else w)


def terminos(texto: str) -> set[str]:
    """Términos de ≥5 letras de un título (sin vacías)."""
    return {_raiz(w) for w in re.findall(r"[a-z0-9]{5,}", _norm(texto)) if w not in _VACIAS}


def cortar_palabra(texto: str, maximo: int) -> tuple[str, bool]:
    """(texto, cortado): como mucho `maximo` caracteres, cortado en la última palabra completa y SIN elipsis."""
    texto = " ".join((texto or "").split())
    if len(texto) <= maximo:
        return texto, False
    corte = texto[:maximo + 1]
    i = corte.rfind(" ")
    return (corte[:i] if i > 0 else texto[:maximo]).rstrip(" ,;:.-"), True


# ------------------------------------------------------------------ señales
def _emparejar(norm: str) -> dict[str, tuple[int, int]]:
    """tipo -> (inicio, fin) de su primer fragmento no cedido a otro tipo más específico o más largo."""
    cands: list[tuple[int, int, int, str]] = []   # (-largo, rango, inicio, tipo)
    for tipo, pat in PATRONES.items():
        for k, m in enumerate(pat.finditer(norm)):
            if k >= 12:
                break
            if m.end() > m.start():
                cands.append((-(m.end() - m.start()), ESPECIFICIDAD.index(tipo) if tipo in ESPECIFICIDAD else 99, m.start(), tipo, m.end()))
    cands.sort()
    ocupado: list[tuple[int, int]] = []
    res: dict[str, tuple[int, int]] = {}
    for _, _, ini, tipo, fin in cands:
        if any(ini < b and fin > a for a, b in ocupado):
            continue
        ocupado.append((ini, fin))
        if tipo not in res or ini < res[tipo][0]:
            res[tipo] = (ini, fin)
    return res


def detectar(texto: str) -> dict[str, tuple[int, int]]:
    """Señales de un texto: tipo -> (inicio, fin) sobre el texto normalizado (mismas posiciones que el original)."""
    return _emparejar(_norm(texto))


def cita(texto: str, inicio: int, maximo: int = CITA_MAX) -> str:
    """Desde el inicio del fragmento, hasta `maximo` caracteres, cortada en palabra completa (sin elipsis)."""
    resto = texto[inicio:]
    fin = re.search(r"[.?!;]", resto)
    if fin and fin.start() > 12:
        resto = resto[:fin.start()]
    return cortar_palabra(resto, maximo)[0]


# ------------------------------------------------------------------ definiciones locales
_ART = r"(?:el|la|los|las|un|una|unos|unas|els|les|uns|unes)"   # y los catalanes
_W = r"[\w/-]+"
_RELLENO = {"y", "pues", "entonces", "vale", "o", "sea", "que", "es", "a", "de", "en", "si", "no", "bueno", "ya", "lo", "eso", "esto", "se", "nos", "le"}
_P_VERBO_TERMINO = re.compile(
    rf"\b(?:definimos|llamamos|llamaremos|vamos a llamar|definim|anomenem|anomenarem|anem a anomenar)\s+(?:a\s+)?(?:{_ART}\s+)?(?P<t>{_W}(?:\s+{_W}){{0,3}}?)(?:\s+(?:como|com|a la|a los|a las|a les|als|al|a)\s+|\s*:\s*)(?P<d>[^.?!;]+)")
_P_ENTIENDE = re.compile(
    rf"\b(?:se entiende por|entendemos por|s.enten per|entenem per)\s+(?:{_ART}\s+)?(?P<t>{_W}(?:\s+{_W}){{0,2}}?)\s+(?P<d>(?:{_ART}|lo|aquel|aquella|todo|toda|aquell|tot|tota)\s+[^.?!;]+)")
_P_TERMINO_VERBO = re.compile(
    rf"(?P<t>[^.?!;,:]{{2,70}}?)\s+(?:se define como|se define|significa|quiere decir|se llama|es defineix com|es defineix|vol dir)\s+(?P<d>[^.?!;]+)")
_P_ES_LO_QUE = re.compile(rf"(?P<d>[^.?!;]{{8,}}?)\s+(?:es lo que llamamos|es el que anomenem)\s+(?:{_ART}\s+)?(?P<t>{_W}(?:\s+{_W}){{0,2}})")
_GENERAL_CA = r"\b(definim|es defineix|s.enten per|entenem per|anomenem|anomenarem|es el que anomenem|a aixo li diem)\b"   # regla general, catalán
_P_A_ESO = re.compile(rf"\b(?:a (?:eso|esto|ello) le llamamos|a (?:aixo|aco) li diem)\s+(?:{_ART}\s+)?(?P<t>{_W}(?:\s+{_W}){{0,2}})")


def _limpiar_termino(t: str, orig_t: str) -> tuple[str, bool]:
    """(término, marcado). De las palabras antes del verbo, hasta 4: las capitalizadas o entrecomilladas más cercanas; si no hay, las 3 últimas
    (`marcado` False: un término en minúsculas sin comillas, menos fiable)."""
    comillas = re.findall(r"[«\"“'](.{1,40}?)[»\"”']", orig_t)
    if comillas:
        return comillas[-1].strip(), True
    ws = orig_t.split()
    cap = []
    sueltas = _RELLENO | {"el", "la", "los", "las", "un", "una"}
    for w in reversed(ws):
        if (w[:1].isupper() or w.isupper()) and _norm(w).strip(".,") not in sueltas:   # «El» al empezar la frase no es un nombre propio
            cap.insert(0, w)
            if len(cap) == 4:
                break
        elif cap:
            break
    elegidas = cap or ws[-3:]
    while elegidas and _norm(elegidas[0]).strip(".,") in _RELLENO | {"el", "la", "los", "las", "un", "una"}:
        elegidas = elegidas[1:]
    while elegidas and _norm(elegidas[-1]).strip(".,") in _RELLENO:
        elegidas = elegidas[:-1]
    return " ".join(elegidas[:4]).strip(" ,.:;«»\"'"), bool(cap)


def extraer_definiciones(texto: str, previo: str = "") -> list[dict]:
    """Definiciones LOCALES de un texto: [{termino, definicion, parcial}]. Sin modelo. `previo`: la frase anterior (para «a eso le llamamos X»).
    «significa» y «quiere decir» son muy habituales al hablar («a un paso quiere decir, mira…»): solo valen con el término capitalizado o entre comillas."""
    out: list[dict] = []
    orig = " ".join((texto or "").split())
    norm = _norm(orig)
    if len(norm) != len(orig):
        orig = norm
    if not PATRONES["definicion"].search(norm):
        return out

    def trozo(m, g):
        return orig[m.start(g):m.end(g)]

    def anadir(termino: str, definicion: str, exigir_marca: bool = False):
        termino, marcado = _limpiar_termino(_norm(termino), termino)
        termino = termino.strip()
        d, parcial = cortar_palabra(definicion.strip(" ,.:;"), 140)
        if exigir_marca and not marcado:
            return
        if termino and len(termino) <= 40 and palabras(d) >= 2 and not any(_norm(x["termino"]) == _norm(termino) for x in out):
            out.append({"termino": termino, "definicion": d, "parcial": parcial})
    for m in _P_VERBO_TERMINO.finditer(norm):
        anadir(trozo(m, "t"), trozo(m, "d"))
    for m in _P_ENTIENDE.finditer(norm):
        anadir(trozo(m, "t"), trozo(m, "d"))
    for m in _P_ES_LO_QUE.finditer(norm):
        anadir(trozo(m, "t"), trozo(m, "d"))
    for m in _P_A_ESO.finditer(norm):
        if previo.strip():
            anadir(trozo(m, "t"), previo)
    if not out:
        for m in _P_TERMINO_VERBO.finditer(norm):
            debil = bool(re.search(r"\b(significa|quiere decir)\b", m.group(0)[len(m.group("t")):len(m.group("t")) + 20]))
            debil = debil or bool(re.search(r"\bvol dir\b", m.group(0)[len(m.group("t")):len(m.group("t")) + 20]))   # catalán: igual de habitual al hablar
            anadir(trozo(m, "t"), trozo(m, "d"), exigir_marca=debil)
    if not out:   # regla general: las 3 palabras anteriores al verbo y el resto de la frase (solo con un verbo explícito de definir)
        # En español el verbo ha de ser inequívoco («llamamos» a secas es «te llamamos mañana») y el término ha de ir marcado (capitalizado o
        # entrecomillado) y no ser la primera palabra de la frase («Revenue definimos aquí…»); en catalán se acepta como siempre.
        m = re.search(r"\b(definimos|se define|se entiende por|entendemos por|es lo que llamamos|a eso le llamamos)\b", norm)
        castellano = bool(m)
        m = m or re.search(_GENERAL_CA, norm)   # catalán
        if m:
            antes, despues = orig[:m.start()].split(), orig[m.end():]
            fin = re.search(r"[.?!;]", despues)
            despues = despues[:fin.start()] if fin else despues
            if not castellano or len(antes) >= 2:
                anadir(" ".join(antes[-3:]), despues, exigir_marca=castellano)
    return out


def _clave_termino(t: str) -> str:
    return " ".join(w for w in _norm(t).split() if w not in {"el", "la", "los", "las", "un", "una"})


def mismo_termino(a: str, b: str) -> bool:
    """Mismo término sin acentos ni mayúsculas ni artículos, con ≥0,8 de solape de caracteres."""
    ka, kb = _clave_termino(a), _clave_termino(b)
    return bool(ka and kb) and (ka == kb or SequenceMatcher(None, ka, kb).ratio() >= 0.8)


# ------------------------------------------------------------------ el Monitor
@dataclass
class Pasada:
    t: float
    minuto: str
    palabras: int
    senales: list[dict] = field(default_factory=list)       # entradas de feed de señales
    entradas: list[dict] = field(default_factory=list)      # todo lo que se añade al feed en esta pasada
    definiciones: list[dict] = field(default_factory=list)  # locales nuevas
    tipos: list[str] = field(default_factory=list)
    toca: list[int] = field(default_factory=list)
    puntos: dict = field(default_factory=dict)

    def publico(self) -> dict:
        return {"t": round(self.t, 1), "minuto": self.minuto, "palabras": self.palabras, "senales": [s["texto"] for s in self.senales],
                "tipos": list(self.tipos), "toca": list(self.toca), "puntos": dict(self.puntos), "definiciones": [d["termino"] for d in self.definiciones]}


class Monitor:
    """Estado del vigía. `t` es siempre el reloj de la reunión (segundos)."""

    def __init__(self, cfg: dict | None = None):
        c = {"equipo_puntuacion_min": 3, "equipo_enfriamiento_global_s": 240, "equipo_enfriamiento_perfil_s": 360, "equipo_rotacion_s": 300,
             "equipo_palabras_min": 120, "equipo_objetivo_sin_tratar_min": 15,
             "equipo_toque_repetido_s": 120, "equipo_silencio_aviso_s": 300, "equipo_rotacion_palabras": 150,
             "asesor_separacion_llamada_s": 90, "asesor_rotacion_s": 480, "asesor_rotacion_palabras": 200}
        c.update(cfg or {})
        self.c = c
        self.reiniciar()

    def reiniciar(self) -> None:
        self.puntos = {p: 0 for p in ORDEN_ROTACION}
        self.contrib: dict[str, dict[str, int]] = {p: {} for p in ORDEN_ROTACION}
        self.palabras_desde = {p: 0 for p in ORDEN_ROTACION}
        self.ultimo_turno = {p: 0.0 for p in ORDEN_ROTACION}
        self.hubo_turno = {p: False for p in ORDEN_ROTACION}
        # El Estratega (quinto perfil) lleva su estado aparte: no entra en el reparto por puntuación y rotación de los cuatro, se elige después (`elegir_estratega`)
        self.estratega = {"puntos": 0, "contrib": {}, "palabras_desde": 0, "ultimo_turno": 0.0, "hubo_turno": False}
        self.ultima_llamada = 0.0             # fin de la última llamada de cualquier perfil
        self.ultimo_id = 0                    # último segmento visto
        self.palabras_total = 0
        self.t_pasada = 0.0
        self.ultima_pasada_real = None
        self.ultimo_toque: dict[int, float] = {}
        self.ultimo_toque_check: dict[str, float] = {}
        self.sin_tratar_avisado: set[tuple[int, int]] = set()
        self.ultimo_aviso_silencio = 0.0
        self.n_senales = 0
        self._n_entrada = 0
        self.feed: list[dict] = []
        self.pasadas: list[dict] = []
        self.locales: list[dict] = []   # definiciones locales detectadas (término, definición, minuto)
        self.frase_previa = ""
        self._terminos_obj: dict[int, set[str]] = {}
        self._terminos_chk: dict[str, set[str]] = {}

    # ---------------------------------------------------------- una pasada
    def _entrada(self, t: float, tipo: str, texto: str, **extra) -> dict:
        self._n_entrada += 1
        e = {"id": f"m{self._n_entrada}", "t": round(t, 1), "minuto": mmss(t), "tipo": tipo, "texto": texto, "local": True, **extra}
        self.feed.append(e)
        del self.feed[:-600]
        return e

    def pasada(self, ahora: float, segmentos: list, objetivos: list[dict] | None = None, checks: list[dict] | None = None) -> Pasada:
        """`segmentos`: objetos con id, t, texto NUEVOS desde la pasada anterior. `objetivos`: los activos, con n, texto y estado."""
        nuevos = [s for s in segmentos if s.id > self.ultimo_id]
        if nuevos:
            self.ultimo_id = max(s.id for s in nuevos)
        n_pal = sum(palabras(s.texto) for s in nuevos)
        self.palabras_total += n_pal
        self.estratega["palabras_desde"] += n_pal
        for p in ORDEN_ROTACION:
            self.palabras_desde[p] += n_pal
        pas = Pasada(ahora, mmss(ahora), n_pal)
        vistos: set[str] = set()
        candidatos: list[tuple[int, int, dict]] = []   # (prioridad, orden, entrada)
        for s in nuevos:
            texto = " ".join(s.texto.split())
            sen = detectar(texto)
            for tipo, (ini, _fin) in sen.items():
                if tipo in vistos:
                    continue
                vistos.add(tipo)
                q = cita(texto, ini)
                candidatos.append((ORDEN_SENALES.index(tipo), len(candidatos),
                                   {"t": s.t, "tipo": tipo, "q": q}))
            for d in extraer_definiciones(texto, self.frase_previa):
                if not any(mismo_termino(d["termino"], x["termino"]) for x in self.locales):
                    reg = {"termino": d["termino"][:1].upper() + d["termino"][1:], "definicion": d["definicion"], "parcial": d["parcial"],
                           "t": s.t, "minuto": mmss(s.t), "origen": "local"}
                    self.locales.append(reg)
                    pas.definiciones.append(reg)
                    pas.entradas.append(self._entrada(s.t, "definicion", f"definición (local) · {reg['termino']}", termino=reg["termino"]))
            self.frase_previa = texto
        candidatos.sort()
        for _prio, _orden, c in candidatos[:MAX_ENTRADAS_PASADA]:
            e = self._entrada(c["t"], "senal", f"señal: {ETIQUETA[c['tipo']]} · «{c['q']}»", senal=c["tipo"])
            pas.senales.append(e)
            pas.entradas.append(e)
        pas.tipos = sorted(vistos)
        self.n_senales = len(pas.senales)
        # objetivos y checks tocados
        texto_ventana = _norm(" ".join(s.texto for s in nuevos))
        palabras_ventana = {_raiz(w) for w in re.findall(r"[a-z0-9]{5,}", texto_ventana)}
        for o in (objetivos or []):
            n = o["n"]
            if n not in self._terminos_obj or self._terminos_obj[n][0] != o["texto"]:
                self._terminos_obj[n] = (o["texto"], terminos(o["texto"]))
            ts = self._terminos_obj[n][1]
            if ts and len(ts & palabras_ventana) >= (1 if len(ts) == 1 else 2):
                prev = self.ultimo_toque.get(n)
                self.ultimo_toque[n] = ahora
                pas.toca.append(n)
                if prev is None or ahora - prev >= self.c["equipo_toque_repetido_s"]:
                    pas.entradas.append(self._entrada(ahora, "toca", f"toca objetivo {n}", objetivo=n))
        for c in (checks or []):
            cid = c["id"]
            if cid not in self._terminos_chk:
                self._terminos_chk[cid] = terminos(c["texto"])
            ts = self._terminos_chk[cid]
            if ts and len(ts & palabras_ventana) >= (1 if len(ts) == 1 else 2):
                self.ultimo_toque_check[cid] = ahora
        # objetivos sin tratar (cada 5 min, una vez por objetivo y cuarto de hora)
        sin_tratar = False
        if int(ahora // 300) != int(self.t_pasada // 300) or self.t_pasada == 0:
            limite = self.c["equipo_objetivo_sin_tratar_min"] * 60
            for o in (objetivos or []):
                if o.get("estado") == "cubierto":
                    continue
                n = o["n"]
                desde = ahora - self.ultimo_toque.get(n, 0.0)
                if desde >= limite:
                    cuarto = int(desde // limite)
                    if (n, cuarto) not in self.sin_tratar_avisado:
                        self.sin_tratar_avisado.add((n, cuarto))
                        pas.entradas.append(self._entrada(ahora, "sin_tratar", f"objetivo {n} sin tratar desde hace {int(desde // 60)} min", objetivo=n))
                        sin_tratar = True
        # puntuación
        presentes = set(vistos)
        if pas.toca:
            presentes.add("toca")
        if sin_tratar:
            presentes.add("sin_tratar")
        for perfil, tabla in PUNTOS.items():
            for tipo, pts in tabla.items():
                if tipo in presentes:
                    self.puntos[perfil] += pts
                    self.contrib[perfil][tipo] = self.contrib[perfil].get(tipo, 0) + pts
        pas.puntos = dict(self.puntos)
        self.t_pasada = ahora
        self.pasadas.append(pas.publico())
        del self.pasadas[:-300]
        return pas

    def silencio(self, ahora: float, n_pal: int) -> dict | None:
        """«94 palabras nuevas · nadie tiene turno»: como mucho una vez cada 5 minutos."""
        if ahora - self.ultimo_aviso_silencio < self.c["equipo_silencio_aviso_s"] or n_pal < 30:
            return None
        self.ultimo_aviso_silencio = ahora
        return self._entrada(ahora, "silencio", f"{n_pal} palabras nuevas · nadie tiene turno")

    # ---------------------------------------------------------- turnos
    def motivo(self, perfil: str) -> str:
        c = self.contrib[perfil]
        tipos = sorted(c, key=lambda k: (-c[k], list(PUNTOS[perfil]).index(k)))[:2]
        return " + ".join(ETIQUETA[t] for t in tipos)

    def _ajustes(self, nivel: str) -> tuple[float, float, bool]:
        if nivel == "ahorro":
            return 2 * self.c["equipo_enfriamiento_global_s"], 2 * self.c["equipo_enfriamiento_perfil_s"], False
        return self.c["equipo_enfriamiento_global_s"], self.c["equipo_enfriamiento_perfil_s"], True

    def elegir(self, ahora: float, nivel: str = "normal", ocupado: bool = False) -> tuple[str | None, str]:
        """(perfil, motivo) del próximo turno automático, o (None, «»). Niveles: normal | ahorro (80 %) | agotado (100 %)."""
        if ocupado or nivel == "agotado":
            return None, ""
        glob, por_perfil, rotacion = self._ajustes(nivel)
        if ahora - self.ultima_llamada < glob:
            return None, ""
        cand = [p for p in ORDEN_ROTACION
                if self.puntos[p] >= self.c["equipo_puntuacion_min"] and self.palabras_desde[p] >= self.c["equipo_palabras_min"]
                and self._perfil_listo(p, ahora, por_perfil)]
        if cand:
            p = max(cand, key=lambda x: (ahora - self.ultimo_turno[x], -ORDEN_ROTACION.index(x)))
            return p, self.motivo(p)
        if rotacion and ahora - self.ultima_llamada >= self.c["equipo_rotacion_s"]:
            antiguo = max(ORDEN_ROTACION, key=lambda x: (ahora - self.ultimo_turno[x], -ORDEN_ROTACION.index(x)))
            if self.palabras_desde[antiguo] >= self.c["equipo_rotacion_palabras"]:
                return antiguo, "rotación"
        return None, ""

    def _perfil_listo(self, p: str, ahora: float, por_perfil: float) -> bool:
        """El enfriamiento propio solo cuenta si el perfil ya habló: el primer turno de cada uno no espera 6 minutos."""
        return not self.hubo_turno[p] or ahora - self.ultimo_turno[p] >= por_perfil

    def a_peticion(self) -> str:
        """«Analizar ahora»: el perfil con mayor puntuación (empate: Coordinador)."""
        return max(ORDEN_ROTACION, key=lambda p: (self.puntos[p], -ORDEN_ROTACION.index(p)))

    def turno_hecho(self, perfil: str, ahora: float) -> None:
        if perfil == "estratega":   # su presupuesto y su ritmo son propios: su turno no retrasa los del resto del equipo
            self.estratega.update(puntos=0, contrib={}, palabras_desde=0, ultimo_turno=ahora, hubo_turno=True)
            return
        self.puntos[perfil] = 0
        self.contrib[perfil] = {}
        self.palabras_desde[perfil] = 0
        self.ultimo_turno[perfil] = ahora
        self.hubo_turno[perfil] = True
        self.ultima_llamada = ahora

    # ---------------------------------------------------------- el Estratega (quinto perfil): señales estratégicas y elección propia
    PUNTOS_ESTRATEGA_POR_TEMA = 2

    def sumar_estratega(self, temas) -> int:
        """Suma al Estratega los puntos de los temas estratégicos (precio, plazos, oportunidad, cierre…) presentes en la ventana: cada tema cuenta una vez."""
        n = 0
        for t in temas:
            self.estratega["puntos"] += self.PUNTOS_ESTRATEGA_POR_TEMA
            self.estratega["contrib"][t] = self.estratega["contrib"].get(t, 0) + self.PUNTOS_ESTRATEGA_POR_TEMA
            n += self.PUNTOS_ESTRATEGA_POR_TEMA
        return n

    def motivo_estratega(self) -> str:
        c = self.estratega["contrib"]
        tipos = sorted(c, key=lambda k: (-c[k], k))[:2]
        return " + ".join(tipos) if tipos else "rotación"

    def elegir_estratega(self, ahora: float, nivel_asesor: str = "normal", cada_s: float = 360, ocupado: bool = False) -> tuple[str | None, str]:
        """(«estratega», motivo) si le toca. Va DESPUÉS del reparto normal (solo si nadie más tiene turno), con su enfriamiento propio (`cada_s`; el doble al 80 %
        de SU presupuesto), sin pegarse a la llamada de otro perfil (90 s), con las mismas palabras y puntuación mínimas que los demás y, sin señales, una
        rotación cada 8 minutos con ≥200 palabras nuevas. Con su presupuesto agotado, nunca."""
        if ocupado or nivel_asesor == "agotado":
            return None, ""
        cada = cada_s * (2 if nivel_asesor == "ahorro" else 1)
        e = self.estratega
        if e["hubo_turno"] and ahora - e["ultimo_turno"] < cada:
            return None, ""
        if ahora - self.ultima_llamada < self.c["asesor_separacion_llamada_s"]:
            return None, ""
        if e["puntos"] >= self.c["equipo_puntuacion_min"] and e["palabras_desde"] >= self.c["equipo_palabras_min"]:
            return "estratega", self.motivo_estratega()
        if nivel_asesor != "ahorro" and ahora - e["ultimo_turno"] >= self.c["asesor_rotacion_s"] and e["palabras_desde"] >= self.c["asesor_rotacion_palabras"]:
            return "estratega", "rotación"
        return None, ""

    def siguiente_estratega(self, ahora: float, nivel_asesor: str = "normal", cada_s: float = 360) -> dict | None:
        e = self.estratega
        if nivel_asesor == "agotado" or e["puntos"] < self.c["equipo_puntuacion_min"]:
            return None
        cada = cada_s * (2 if nivel_asesor == "ahorro" else 1)
        en = max(0.0, (e["ultimo_turno"] + cada - ahora) if e["hubo_turno"] else 0.0, self.ultima_llamada + self.c["asesor_separacion_llamada_s"] - ahora)
        return {"en": round(en), "motivo": self.motivo_estratega()}

    def siguiente(self, ahora: float, nivel: str = "normal") -> dict[str, dict]:
        """Por perfil: segundos hasta que le toca y motivo, solo si hay candidato claro (si no, {}).
        Con puntuación ≥ mínima: espera el enfriamiento; el perfil más antiguo sin candidatos: la rotación."""
        if nivel == "agotado":
            return {}
        glob, por_perfil, rotacion = self._ajustes(nivel)
        out: dict[str, dict] = {}
        cola = []
        for p in ORDEN_ROTACION:
            if self.puntos[p] >= self.c["equipo_puntuacion_min"]:
                en = max(0.0, self.ultima_llamada + glob - ahora, (self.ultimo_turno[p] + por_perfil - ahora) if self.hubo_turno[p] else 0.0)
                out[p] = {"en": round(en), "motivo": self.motivo(p)}
                cola.append(p)
        if not cola and rotacion:
            antiguo = max(ORDEN_ROTACION, key=lambda x: (ahora - self.ultimo_turno[x], -ORDEN_ROTACION.index(x)))
            out[antiguo] = {"en": round(max(0.0, self.ultima_llamada + self.c["equipo_rotacion_s"] - ahora)), "motivo": "rotación"}
        elif len(cola) > 1:   # solo habla uno cada vez: el resto espera su vez
            primero = max(cola, key=lambda x: (ahora - self.ultimo_turno[x], -ORDEN_ROTACION.index(x)))
            for p in cola:
                if p != primero:
                    out[p]["en"] = out[p]["en"] + int(glob)
        return out

    def publico(self, ahora: float, nivel: str = "normal") -> dict:
        return {"puntos": dict(self.puntos), "palabras_desde": dict(self.palabras_desde), "palabras": self.palabras_total, "senales": self.n_senales,
                "ultima_pasada_t": round(self.t_pasada, 1), "siguiente": self.siguiente(ahora, nivel),
                # copias atómicas: la pasada del Monitor corre en otro hilo mientras el tick lee el estado
                "toques": {str(k): round(v, 1) for k, v in list(self.ultimo_toque.items())},
                "toques_checks": {k: round(v, 1) for k, v in list(self.ultimo_toque_check.items())}}


# ------------------------------------------------------------------ qué lee cada perfil cuando hay más de lo que cabe
def pesos_de_lineas(perfil: str, textos: list[str]) -> list[int]:
    """Peso de cada línea para ese perfil: los puntos de las señales de su oficio que aparecen en ella (ver `PUNTOS`)."""
    tabla = PUNTOS[perfil]
    return [sum(tabla.get(tipo, 0) for tipo in detectar(t)) for t in textos]


def seleccionar_para(perfil: str, lineas: list, tope: int, formatear) -> tuple[str, list[int]]:
    """Texto nuevo de un turno que cabe en `tope` caracteres. Si todo cabe, es todo. Si no, en lugar de quedarse solo con las últimas
    líneas (se perdería lo dicho antes), cada perfil conserva lo más relevante para su oficio (las líneas con señales suyas) más lo
    último que se dijo (un tercio del tope, para enlazar con su siguiente turno), siempre con su minuto y en orden; los saltos se marcan con «[…]».
    Todo local, sin modelo. `formatear(linea)` da la línea con su minuto. Devuelve (texto, posiciones elegidas)."""
    textos = [formatear(l) for l in lineas]
    if sum(len(t) + 1 for t in textos) <= tope:
        return "\n".join(textos), list(range(len(textos)))
    pesos = pesos_de_lineas(perfil, textos)
    elegidos: set[int] = set()
    usado = 0
    for i in range(len(textos) - 1, -1, -1):          # lo último que se dijo
        if usado + len(textos[i]) + 1 > tope // 3:
            break
        elegidos.add(i)
        usado += len(textos[i]) + 1
    for i in sorted(range(len(textos)), key=lambda k: (-pesos[k], -k)):   # lo más relevante para su oficio
        if pesos[i] <= 0 or i in elegidos:
            continue
        if usado + len(textos[i]) + 1 + 4 <= tope:
            elegidos.add(i)
            usado += len(textos[i]) + 1 + 4
    for i in range(len(textos) - 1, -1, -1):          # si aún cabe, lo reciente aunque no tenga señal
        if i not in elegidos and usado + len(textos[i]) + 1 + 4 <= tope:
            elegidos.add(i)
            usado += len(textos[i]) + 1 + 4
    orden = sorted(elegidos)
    salida: list[str] = []
    for k, i in enumerate(orden):
        if k and i != orden[k - 1] + 1:
            salida.append("[…]")
        salida.append(textos[i])
    return "\n".join(salida), orden
