"""Orquesta las llamadas (digest, periódico, confirmación, final) sobre un `ModeloLLM`."""
from __future__ import annotations

import json

from . import ErrorAnalisis, ModeloLLM
from . import prompts as P
from .. import checks as CK
from .. import planes as PL
from ..envios import marcar_tarea   # ola 4: el registro de envíos y el modo solo local necesitan saber qué tarea llama
from ..contexto import Fuentes, digest_de_contexto
from ..equipo import perfiles as PF
from ..rutas import Guardian, slug


TAREAS_ASESOR_SIN_RAZONAMIENTO = ("asesor_respuesta", "asesor_consejo")   # haiku: respuestas al momento, sin tokens de razonamiento


class Analista:
    def __init__(self, modelo: ModeloLLM, config, consumo, guardian: Guardian, sesion_id: str = ""):
        self.modelo, self.config, self.consumo, self.g = modelo, config, consumo, guardian
        self.sesion_id = sesion_id
        self.tramos: dict[str, str] = {}        # el digest por tramos (pm, fun, tec, rev) de la reunión: cada perfil lee solo el suyo
        self.ficheros_digest: list[str] = []   # nombres de los ficheros que alimentan el contexto (los únicos citables además de los extractos)
        self.checks_sugeridos: list[str] = []   # los del último digest (generado o de la caché)
        self.objetivos_sugeridos: list[str] = []   # idem (solo si se pidieron: proyecto sin plan)

    # ---- llamada genérica: medición, un único reintento y errores claros
    def _llamar(self, tarea: str, sistema: str, usuario: str, parsear, intentos: int = 2, web: bool = False):
        ultimo: ErrorAnalisis | None = None
        extra = {"web": True} if web else {}   # solo se pasa cuando hace falta: los modelos de prueba antiguos no lo conocen
        for intento in range(intentos):  # como máximo UN reintento (el pulido no reintenta)
            marcar_tarea(tarea)
            try:
                r = self.modelo.completar(sistema, usuario, self.config.modelo(tarea),
                                          self.config["esfuerzo"], self.config["timeout_s"],
                                          tarea.startswith("equipo_") or tarea == "contexto_reunion" or tarea in self.config["sin_razonamiento"]
                                          or tarea in TAREAS_ASESOR_SIN_RAZONAMIENTO, **extra)
            except ErrorAnalisis as e:
                self.consumo.registrar(self.sesion_id, tarea, [], 0, False, e.tipo)
                ultimo = e
                if e.bloqueante or not e.transitorio:
                    raise
                continue
            self.consumo.registrar(self.sesion_id, tarea, r.uso, r.ms, True)
            try:
                return parsear(P.extraer_json(r.texto))
            except ValueError:
                ultimo = ErrorAnalisis("salida", "Claude devolvió una respuesta que no se pudo interpretar.", True)
        raise ultimo or ErrorAnalisis("otro", "El análisis falló.")

    # ---- digest cacheado por hash de las fuentes: UNA llamada que devuelve cuatro tramos (uno por perfil), checks y, sin plan, objetivos
    def digest(self, proyecto: str, fuentes: Fuentes, foco: str = "", checks_existentes: list[str] | None = None,
               con_checks: bool = False, con_objetivos: bool = False,
               objetivos_existentes: list[str] | None = None, prioritario: bool = False, contexto_reunion: str = "") -> tuple[str, str]:
        """(texto, origen) con origen en vacio|cache|generado. `texto` son los cuatro tramos juntos y etiquetados (lo usan Pregúntale y el
        resumen final); cada perfil lee solo el suyo (`self.tramos`). Los checks sugeridos (`self.checks_sugeridos`) y, sin plan, los
        objetivos (`self.objetivos_sugeridos`) viajan en la misma llamada. `contexto_reunion`: lo que el usuario aceptó en «Contexto de la
        reunión» (vacío = prompts idénticos a los de siempre); si el proyecto no tiene nada que compactar, ese texto es el contexto, sin llamada."""
        self.checks_sugeridos, self.objetivos_sugeridos, self.tramos = [], [], {}
        if fuentes.vacio:
            return (digest_de_contexto(contexto_reunion), "contexto_usuario") if contexto_reunion else ("", "vacio")
        nombre = f"digest-{slug(proyecto, 40)}-{fuentes.clave}.json"
        ruta = self.g.ruta_cache(nombre)
        if ruta.is_file():
            try:
                d = json.loads(ruta.read_text(encoding="utf-8"))
                if isinstance(d.get("digest"), str) and d["digest"] and isinstance(d.get("tramos"), dict):
                    self.tramos = {k: str(d["tramos"].get(k) or "") for k in PF.TRAMOS}
                    if con_checks:
                        self.checks_sugeridos = CK.normalizar_sugeridos(d.get("checks"))
                    if con_objetivos:
                        self.objetivos_sugeridos = PF.normalizar_tramos({"digest": "x", "objetivos": d.get("objetivos")}, self.config["max_objetivos_sugeridos"])[2]
                    return d["digest"], "cache"
            except (OSError, ValueError):
                pass
        maximo = self.config["max_objetivos_sugeridos"]
        tramos, sugeridos, objetivos = self._llamar(
            "digest", PF.sistema_digest_tramos(con_objetivos, foco, prioritario, bool(contexto_reunion)),
            P.usuario_digest(fuentes.textos, checks_existentes or [], objetivos_existentes or [], contexto_reunion),
            lambda d: PF.normalizar_tramos(d, maximo))
        texto = PF.digest_como_texto(tramos)
        self.tramos, self.checks_sugeridos, self.objetivos_sugeridos = tramos, sugeridos, (objetivos if con_objetivos else [])
        cuerpo = {"digest": texto, "tramos": tramos, "modelo": self.config.modelo("digest"), "origen": [e for e, _ in fuentes.textos]}
        if con_checks or con_objetivos:
            cuerpo["checks"] = sugeridos
        if con_objetivos:
            cuerpo["objetivos"] = self.objetivos_sugeridos
        self.g.escribir_cache(nombre, json.dumps(cuerpo, ensure_ascii=False))
        return texto, "generado"

    def contexto_reunion(self, tema: str, texto: str) -> dict:
        """«Generar con Claude» (Contexto de la reunión): UNA llamada, solo al pulsar el botón, sin reintentos, con el modelo de la tarea
        `contexto_reunion` (haiku). El texto del usuario va entre marcas <<<DATOS …>>> y la salida se valida. -> {contexto, objetivos}."""
        return self._llamar("contexto_reunion", P.sistema_contexto_reunion(), P.usuario_contexto_reunion(tema, texto),
                            P.normalizar_contexto_reunion, intentos=1)

    def asesorar(self, tarea: str, sistema: str, usuario: str, validar, web: bool = False) -> dict:
        """UNA llamada del asesor en directo (respuesta sugerida, consejo del Estratega o «Profundizar»), sin reintentos: el momento pasó y el
        siguiente turno ya trae lo nuevo. `validar` convierte la respuesta del modelo (o lanza ValueError). Pasa por `_llamar`, el punto único."""
        return self._llamar(tarea, sistema, usuario, validar, intentos=1, web=web)

    def turno(self, perfil: str, usuario: str, n_objetivos: int = 0, n_checks: int = 0) -> dict:
        """UN turno de un perfil del equipo: una llamada corta a haiku. Lanza ErrorAnalisis."""
        p = PF.PERFILES[perfil]
        return self._llamar(p.tarea, PF.sistema(p), usuario, lambda d: PF.normalizar(p, d, n_objetivos, n_checks))

    def periodico(self, digest: str, resumen: str, titulos: list[str], notas: str, nuevo: str,
                  objetivos: list[dict] | None = None, checks: list[dict] | None = None,
                  con_entradas: bool = False) -> dict:
        """`objetivos`: los de la sesión del plan. `checks`: SOLO los abiertos y sin bloquear (máx. 15). Sin plan y sin
        checks el prompt es idéntico al de siempre."""
        tope = self.config["tope_resumen_chars"]
        objetivos = objetivos or []
        checks = (checks or [])[:CK.MAX_PROMPT]
        return self._llamar("periodico", P.sistema_periodico(tope, bool(objetivos), bool(checks), con_entradas),
                            P.usuario_periodico(digest, resumen, titulos, notas, nuevo, PL.bloque_prompt(objetivos),
                                                CK.bloque_prompt(checks)),
                            lambda d: P.normalizar_periodico(d, tope, len(objetivos), len(checks)))

    def consultar(self, pregunta: str, digest: str, resumen: str, transcripcion: str, extractos: dict[str, str],
                  duracion_s: float, sonnet: bool = False) -> dict:
        """«Pregúntale»: UNA llamada por pregunta, solo si el usuario la lanza (haiku; sonnet si lo elige para esa pregunta).
        Sin reintentos. Devuelve {respuesta, citas, base}."""
        from ..texto import mmss
        validos = set(extractos) | {n.strip() for n in (self.ficheros_digest or [])}
        return self._llamar("consulta_sonnet" if sonnet else "consulta", P.sistema_consulta(),
                            P.usuario_consulta(pregunta, digest, resumen, transcripcion, extractos, mmss(duracion_s)),
                            lambda d: P.normalizar_consulta(d, validos, duracion_s), intentos=1)

    def confirmar(self, candidatas: list[dict]) -> dict[int, str]:
        """UNA sola llamada (sonnet) para todas las candidatas de la reunión, al terminar."""
        if not candidatas:
            return {}
        return self._llamar("contradicciones_confirmar", P.sistema_confirmar(), P.usuario_confirmar(candidatas),
                            lambda d: P.normalizar_confirmacion(d, len(candidatas)))

    def pulir(self, resumen: str, titulos: list[str], duracion: str = "") -> str:
        """Botón opcional «Pulir con Opus»: UNA llamada, sin reintentos, solo con el resumen de sonnet y las tarjetas
        compactas (ni transcripción ni contexto). Lanza ErrorAnalisis."""
        return self._llamar("pulido", P.sistema_pulido(), P.usuario_pulido(resumen, titulos, duracion),
                            P.normalizar_pulido, intentos=1)

    def final(self, digest: str, resumen: str, titulos: list[str], notas: str, tramo: str,
              ficheros: dict[str, str], objetivos: list[dict] | None = None, duracion: str = "",
              definiciones: list[str] | None = None, huecos: str = "") -> dict:
        """`resumen`: el de TODA la reunión; `titulos`: TODAS las tarjetas en forma compacta (no solo las últimas); `huecos`: la transcripción
        (sin eco) de lo que ningún análisis leyó, con el inicio y el fin de cada tramo: va en esta MISMA llamada."""
        objetivos = objetivos or []
        return self._llamar("final", P.sistema_final(bool(ficheros), bool(objetivos), bool(huecos)),
                            P.usuario_final(digest, resumen, titulos, notas, tramo, ficheros, PL.bloque_prompt(objetivos), duracion, definiciones or [], huecos),
                            lambda d: P.normalizar_final(d, len(objetivos)))
