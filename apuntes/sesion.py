"""Sesión de reunión: datos en memoria y guardado completo y atómico del .md tras cada cambio.

Solo se persiste TEXTO (transcripción, notas, insights). El audio nunca toca el disco.
"""
from __future__ import annotations

import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import asesor as AS
from . import checks as CK
from . import eco as ECO
from . import correo_cierre as CC
from .planes import ETIQUETA
from .rutas import Guardian
from .texto import mmss

NOMBRE_FUENTE = {"yo": "Micro", "reunion": "Reunión"}   # «Micro» puede recoger a varias personas de una sala


@dataclass
class Segmento:
    id: int
    t: float
    fuente: str  # yo (micrófono; se muestra «Micro») | reunion
    texto: str   # lo que ven el .md, el Monitor y los análisis: sin el eco de Reunión si el filtro está activo ("" = todo era eco)
    original: str = ""    # tal como lo transcribió Whisper (de aquí se recalcula `texto`)
    llegada: float = 0.0  # reloj de la reunión al llegar (el Micro espera a su pareja de Reunión: ver `eco.micro_listo`)
    palabras: list = field(default_factory=list)   # ola 4: [{w, p, d}] palabra, probabilidad de Whisper y si es dudosa (vacío = sin word_timestamps)
    corregido: bool = False                        # ola 4: el usuario corrigió el texto a mano

    def __post_init__(self):
        if not self.original:
            self.original = self.texto

    def publico(self) -> dict:
        d = {"id": self.id, "t": round(self.t, 1), "mmss": mmss(self.t), "fuente": self.fuente, "texto": self.texto}
        # las palabras solo valen mientras el texto sea el de Whisper (si el filtro de eco lo recortó o el usuario lo corrigió, ya no casan)
        if self.palabras and self.texto == self.original and not self.corregido:
            d["palabras"] = [dict(p) for p in self.palabras]
            d["dudosas"] = sum(1 for p in self.palabras if p.get("d"))
        if self.corregido:
            d["corregido"] = True
        return d


def temas_fusionados(temas: list[dict]) -> list[dict]:
    """Temas por tramo -> temas con título: los tramos seguidos con el mismo título se unen, y cada tema llega hasta el
    inicio del siguiente (sin huecos). Sin título no hay barra (no se inventa)."""
    out: list[dict] = []
    for t in sorted((x for x in temas if x.get("titulo")), key=lambda x: x["desde_t"]):
        if out and out[-1]["titulo"].strip().lower() == t["titulo"].strip().lower():
            out[-1]["hasta_t"] = max(out[-1]["hasta_t"], t["hasta_t"])
            continue
        out.append({"titulo": t["titulo"], "desde_t": t["desde_t"], "hasta_t": t["hasta_t"]})
    for a, b in zip(out, out[1:]):
        a["hasta_t"] = max(a["hasta_t"], b["desde_t"])
    return out


_RE_TITULO_RESUMEN = re.compile(r"\s*#{1,6}\s*resumen\b", re.I)


def _abre_con_titulo_de_resumen(texto: str) -> bool:
    return bool(_RE_TITULO_RESUMEN.match(texto or ""))


def cronologia(temas: list[dict], tarjetas: list[dict], entradas: list[dict]) -> list[str]:
    """Cronología por tema y minuto para el .md: solo minutos y tipos (el texto de cada cosa ya está en Insights y en las
    anotaciones del usuario; aquí no se repite)."""
    tf = temas_fusionados(temas)
    if not tf:
        return []
    items = [(t.get("t_seg"), t["categoria"]) for t in tarjetas if t.get("t_seg") is not None]
    items += [(e["t_seg"], f"{e['tipo']} (tú)") for e in entradas]
    items.sort(key=lambda x: x[0])
    L = []
    for i, tema in enumerate(tf):
        fin = tf[i + 1]["desde_t"] if i + 1 < len(tf) else float("inf")
        inicio = tema["desde_t"] if i else 0
        marcas = [f"{mmss(t)} {k}" for t, k in items if inicio <= t < fin]
        L.append(f"- {mmss(tema['desde_t'])}–{mmss(tema['hasta_t'])} · {tema['titulo']}" + (f" — {'; '.join(marcas)}" if marcas else ""))
    return L


@dataclass
class Sesion:
    proyecto: str | None
    tema: str
    cadencia_min: int
    ruta: Path
    inicio: datetime = field(default_factory=datetime.now)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    segmentos: list[Segmento] = field(default_factory=list)
    notas: str = ""
    tarjetas: list[dict] = field(default_factory=list)
    resumen_acumulado: str = ""          # lo que viaja en cada análisis periódico (con tope: pierde lo más antiguo)
    resumen_completo: str = ""           # TODO lo resumido, tramo a tramo con su minuto: es lo que usa el resumen final
    resumen_final: str = ""              # el que entra en el .md y en el documento publicado (el elegido en la revisión)
    resumen_modelo: str = ""             # solo el texto que redactó sonnet (sin los bloques de objetivos y checks)
    cambios_aplicados: list[str] = field(default_factory=list)
    estado: str = "en curso"  # en curso | finalizada | interrumpida
    duracion_s: float = 0.0
    ultimo_analizado_id: int = 0
    notas_enviadas: str = ""
    compartido: bool = False            # proyecto en carpeta compartida: la sesión vive solo en local
    plan_id: str = ""                   # sesión del plan elegida al empezar (vacío = sin plan)
    plan_nombre: str = ""
    objetivos: list[dict] = field(default_factory=list)  # {n, texto, estado, minuto, t_seg}
    checks: list[dict] = field(default_factory=list)     # copia de los checks de preparación (la fuente es el almacén local)
    publicada_en: str = ""              # ruta del documento final publicado en la carpeta compartida
    modo_cadencia: str = ""             # adaptativo | 5 | 10 | manual (vacío = la cadencia fija de `cadencia_min`)
    temas: list[dict] = field(default_factory=list)      # {analisis, desde_t, hasta_t, titulo}: un tema por tramo analizado
    entradas: list[dict] = field(default_factory=list)   # comentarios, preguntas e ideas del usuario: {id, tipo, texto, minuto, t_seg}
    consultas: list[dict] = field(default_factory=list)  # historial de «Pregúntale»
    respuestas: list[dict] = field(default_factory=list)  # asesor: respuestas sugeridas a las preguntas del cliente (apuntes/asesor_directo.py)
    consejos: list[dict] = field(default_factory=list)    # asesor: consejos del Estratega (el quinto perfil)
    analisis_marcas: list[dict] = field(default_factory=list)  # {n, t, motivo}: cuándo y por qué se analizó (para el Gantt y la traza)
    definiciones: list[dict] = field(default_factory=list)  # panel de Definiciones (detección local y de la Analista funcional)
    filtrar_eco: bool = True            # quita de Micro lo que ya dijo Reunión (apuntes/eco.py); lo decide `filtrar_eco` en la configuración
    cubiertos: set = field(default_factory=set)             # ids de segmentos que algún análisis LEYÓ (lo recortado por tope no está aquí)
    cobertura: list[dict] = field(default_factory=list)     # por análisis: qué tramo leyó y qué recortó (apuntes/cobertura.py)
    incidencias: list[str] = field(default_factory=list)    # fallos del análisis automático: «[mm:ss] tipo: Excepción» (sin traza ni contenido de la reunión)
    avisos_resumen: list[str] = field(default_factory=list)  # avisos locales sobre el resumen final (falta de contenido, tramos sin cubrir)
    acciones: list[dict] = field(default_factory=list)       # ola 3: bandeja de acciones propuestas (apuntes/acciones.py); viven en la sesión, no en el .md

    def __post_init__(self):
        self._lock = threading.RLock()
        self._ahora: Callable[[], float] | None = None
        self._cambios_eco: dict[int, str] = {}
        self._guardian: Guardian | None = None
        self._ultimo_guardado = 0.0
        self._entradas_enviadas: set[str] = set()
        self._n_entrada = 0

    def vincular(self, g: Guardian) -> None:
        self._guardian = g

    def vincular_reloj(self, ahora: Callable[[], float]) -> None:
        """Reloj de la reunión (segundos): marca la llegada de cada fragmento y decide cuándo un Micro deja de esperar a su pareja."""
        self._ahora = ahora

    # ------------------------------------------------------------ edición
    def agregar_segmento(self, t: float, fuente: str, texto: str, palabras: list | None = None) -> Segmento:
        with self._lock:
            seg = Segmento(len(self.segmentos) + 1, t, fuente, texto, llegada=self._ahora() if self._ahora else t, palabras=list(palabras or []))
            self.segmentos.append(seg)
            if self.filtrar_eco:
                self._recalcular_eco(seg)
        return seg

    # ------------------------------------------------------------ eco entre canales (apuntes/eco.py)
    def _reunion(self) -> list[tuple[float, str]]:
        return [(x.t, x.original) for x in self.segmentos if x.fuente == "reunion"]

    def _recalcular_eco(self, nuevo: Segmento) -> None:
        """Al llegar un fragmento se recalcula el texto de los Micro a los que puede afectar, llegue primero Micro o Reunión: el resultado es
        una función del conjunto, no del orden. Los cambios en fragmentos ANTERIORES quedan en `_cambios_eco` para avisar a la interfaz."""
        reunion = self._reunion()
        if nuevo.fuente == "yo":
            objetivos = [nuevo]
        else:
            objetivos = [x for x in self.segmentos[-400:] if x.fuente == "yo" and -ECO.VENTANA_DESPUES_S <= nuevo.t - x.t <= ECO.VENTANA_ANTES_S]
        for x in objetivos:
            texto = ECO.quitar_eco(x.original, x.t, reunion)
            if texto != x.texto:
                x.texto = texto
                if x is not nuevo:
                    self._cambios_eco[x.id] = texto

    def recoger_cambios_eco(self) -> list[dict]:
        with self._lock:
            out = [{"id": i, "texto": t} for i, t in self._cambios_eco.items()]
            self._cambios_eco = {}
            return out

    def estables(self, desde_id: int = 0, final: bool = False, esperar: bool = True) -> list[Segmento]:
        """Segmentos con id > `desde_id` ya DEFINITIVOS y con texto (sin el eco de Reunión), en orden de llegada. Un Micro espera a su pareja de
        Reunión (`eco.micro_listo`): mientras espera, ni él ni los que llegaron después se entregan a un análisis o al Monitor. En el cierre
        (`final`) se entrega todo; una petición manual («Analizar ahora») usa `esperar=False`: lee lo recibido hasta ese momento."""
        with self._lock:
            ahora = self._ahora() if self._ahora else float("inf")
            reunion = None
            out = []
            for x in self.segmentos:
                if x.id <= desde_id:
                    continue
                if self.filtrar_eco and esperar and not final and x.fuente == "yo":
                    if reunion is None:
                        reunion = self._reunion()
                    if not ECO.micro_listo(x.llegada, ahora, reunion, x.t):
                        break
                if x.texto.strip():
                    out.append(x)
            return out

    def nuevos_desde_ultimo_analisis(self, final: bool = False, esperar: bool = True) -> list[Segmento]:
        return self.estables(self.ultimo_analizado_id, final, esperar)

    def notas_nuevas(self) -> str:
        with self._lock:
            if self.notas.startswith(self.notas_enviadas):
                return self.notas[len(self.notas_enviadas):].strip()
            return self.notas.strip()

    # ------------------------------------------------------------ entradas del usuario (comentario | pregunta | idea)
    TIPOS_ENTRADA = ("comentario", "pregunta", "idea")

    def anadir_entrada(self, tipo: str, texto: str, t: float) -> dict:
        tipo = (tipo or "").strip().lower()
        texto = " ".join((texto or "").split())[:500]
        if tipo not in self.TIPOS_ENTRADA:
            raise ValueError("El tipo debe ser comentario, pregunta o idea.")
        if not texto:
            raise ValueError("Escribe algo antes de guardarlo.")
        with self._lock:
            self._n_entrada += 1
            e = {"id": f"u{self._n_entrada}", "tipo": tipo, "texto": texto, "minuto": mmss(t), "t_seg": round(float(t), 1), "editado": False}
            self.entradas.append(e)
        return dict(e)

    def _entrada(self, ident: str) -> dict:
        e = next((x for x in self.entradas if x["id"] == ident), None)
        if e is None:
            raise ValueError("Esa anotación ya no existe.")
        return e

    def editar_entrada(self, ident: str, texto: str, tipo: str | None = None) -> dict:
        texto = " ".join((texto or "").split())[:500]
        if not texto:
            raise ValueError("El texto no puede quedar vacío.")
        with self._lock:
            e = self._entrada(ident)
            if tipo is not None:
                if tipo not in self.TIPOS_ENTRADA:
                    raise ValueError("El tipo debe ser comentario, pregunta o idea.")
                e["tipo"] = tipo
            e["texto"], e["editado"] = texto, True
            return dict(e)

    def borrar_entrada(self, ident: str) -> None:
        with self._lock:
            self.entradas.remove(self._entrada(ident))
            self._entradas_enviadas.discard(ident)

    def entradas_pendientes(self) -> list[dict]:
        with self._lock:
            return [dict(e) for e in self.entradas if e["id"] not in self._entradas_enviadas]

    @staticmethod
    def linea_entrada(e: dict) -> str:
        return f"[{e['minuto']}] {e['tipo']} del usuario: {e['texto']}"

    def notas_para_modelo(self) -> str:
        """Lo que viaja como «notas nuevas»: las notas libres y las anotaciones del usuario aún no enviadas."""
        partes = [self.notas_nuevas()] + [self.linea_entrada(e) for e in self.entradas_pendientes()]
        return "\n".join(p for p in partes if p)

    def marcar_entradas_enviadas(self, ids) -> None:
        with self._lock:
            self._entradas_enviadas.update(ids)

    def titulos_recientes(self, n: int = 25) -> list[str]:
        with self._lock:
            return [f"[{t.get('minuto') or '--:--'}] {t['categoria']}: {t['texto'][:70]}" for t in self.tarjetas[-n:]]

    # ------------------------------------------------------------ render
    def render(self, publicado: bool = False) -> str:
        """`publicado`: es el documento final que se publica en la carpeta compartida (no lleva rutas locales)."""
        with self._lock:
            L = ["---",
                 f"tema: \"{self.tema.replace(chr(34), chr(39))}\"",
                 f"proyecto: \"{self.proyecto or 'Bandeja'}\"",
                 f"fecha: {self.inicio:%Y-%m-%d}",
                 f"inicio: {self.inicio:%H:%M}",
                 f"duracion: {mmss(self.duracion_s)}",
                 f"estado: {self.estado}",
                 f"cadencia: {self.modo_cadencia or self.cadencia_min}",
                 *([f"sesion_plan: \"{self.plan_id} · {self.plan_nombre.replace(chr(34), chr(39))}\""] if self.plan_id else []),
                 *(["almacenamiento: publicada en la carpeta compartida del proyecto" if publicado
                    else "almacenamiento: local (proyecto compartido)"] if self.compartido else []),
                 *([f"publicada_en: \"{self.publicada_en}\""] if self.publicada_en and not publicado else []),
                 "origen: WhisperMeet (transcripción automática; revisar antes de citar)",
                 "---", "", f"# {self.tema}", ""]
            if self.resumen_final:
                # el modelo suele abrir con su propio título («## Resumen de la reunión (12:26)»): no se pone otro encima
                L += ([] if _abre_con_titulo_de_resumen(self.resumen_final) else ["## Resumen", ""]) + [self.resumen_final, ""]
            if self.avisos_resumen:
                L += ["## Aviso sobre el resumen", ""] + [f"- {a}" for a in self.avisos_resumen] + [""]
            if self.objetivos and "## Objetivos de la sesión" not in self.resumen_final:
                L += ["## Objetivos de la sesión", ""]
                for o in self.objetivos:
                    L.append(f"- [{ETIQUETA[o['estado']]}] {o['texto']}" + (f" (minuto {o['minuto']})" if o["minuto"] else ""))
                L.append("")
            if self.checks and "## Checks de la sesión" not in self.resumen_final:
                L += ["## Checks de la sesión", ""]
                for c in self.checks:
                    marca = "x" if c["estado"] == CK.HECHO else " "
                    extra = (f" (automático, minuto {c['minuto']}" + (f": «{c['cita']}»" if c.get("cita") else "") + ")") if c["auto"] and c["minuto"]                         else " (a mano)" if c["bloqueado"] and c["estado"] == CK.HECHO else ""
                    L.append(f"- [{marca}] {c['texto']}{extra}")
                L.append("")
            if self.incidencias:
                L += ["## Incidencias del análisis automático", ""] + [f"- {i}" for i in self.incidencias] + [""]
            if self.cambios_aplicados:
                L += ["## Contexto actualizado", ""] + [f"- `{f}`" for f in self.cambios_aplicados] + [""]
            if self.notas.strip():
                L += ["## Notas", "", self.notas.strip(), ""]
            if self.entradas:
                L += ["## Tus comentarios, preguntas e ideas", ""]
                for e in self.entradas:
                    L.append(f"- [{e['minuto']}] **{e['tipo'].capitalize()} (tú):** {e['texto']}")
                L.append("")
            if self.consultas:
                L += ["## Consultas", ""]
                for c in self.consultas:
                    cab = f"- [{c['minuto']}] **Pregunta ({c['modelo']}):** {c['pregunta']}"
                    if c["estado"] == "error":
                        L.append(f"{cab}\n  - No se pudo responder: {c.get('error', '')}")
                    elif c["estado"] == "ok":
                        citas = ", ".join(x for x in [(f"minuto {q['minuto']}" if q.get("minuto") else "") + (" " if q.get("minuto") and q.get("fichero") else "")
                                                       + (q["fichero"] if q.get("fichero") else "") for q in c.get("citas", [])] if x.strip())
                        L.append(f"{cab}\n  - {c['respuesta']}" + (f" ({citas})" if citas else ""))
                    else:
                        L.append(cab)
                L.append("")
            if self.estado != "en curso":   # el borrador del correo de cierre (local) solo cuando la reunión ya terminó
                L += CC.seccion_md(CC.correo_de_sesion(self))
            L += AS.seccion_md(self.respuestas, self.consejos)   # «## Asesor»: respuestas sugeridas y consejos (vacío si no hubo)
            if self.definiciones:
                L += ["## Definiciones", ""]
                for d in sorted(self.definiciones, key=lambda x: x.get("t") if x.get("t") is not None else 10 ** 9):
                    quien = "detección local" if d.get("origen") == "local" else "Analista funcional"
                    L.append(f"- [{d.get('minuto') or '--:--'}] **{d['termino']}:** {d['definicion']} ({quien})")
                L.append("")
            crono = cronologia(self.temas, self.tarjetas, self.entradas)
            if crono:
                L += ["## Cronología", ""] + crono + [""]
            if self.tarjetas:
                L += ["## Insights", ""]
                for t in self.tarjetas:
                    resp = f" ({t['responsable']})" if t.get("responsable") else ""
                    ref = f" — contexto: «{t['referencia']}»" if t.get("referencia") else ""
                    nombre = "Posible contradicción" if t.get("estado") == "posible" else t["categoria"].capitalize()
                    L.append(f"- [{t.get('minuto') or '--:--'}] **{nombre}:** {t['texto']}{resp}{ref}")
                L.append("")
            L += ["## Transcripción", ""]
            for s in self.segmentos:
                if s.texto.strip():   # un Micro que era todo eco de Reunión no se escribe
                    L.append(f"[{mmss(s.t)}] **{NOMBRE_FUENTE.get(s.fuente, s.fuente)}:** {s.texto}")
            return "\n".join(L) + "\n"

    def guardar(self, forzar: bool = True) -> None:
        if not self._guardian:
            return
        with self._lock:
            self._guardian.escribir_sesion(self.ruta, self.proyecto, self.render())
            self._ultimo_guardado = time.monotonic()
