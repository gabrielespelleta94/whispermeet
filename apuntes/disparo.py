"""Cadencias y señales locales. Todo local: ni una llamada al modelo para decidir si se llama al modelo.

Modos: «equipo» (por defecto; el Monitor de `apuntes/equipo` reparte turnos a cuatro perfiles), «5» y «10» (el análisis generalista de
siempre, cada N minutos) y «manual» (solo «Analizar ahora»). La cadencia adaptativa anterior la sustituye el equipo. Las expresiones regulares
de señales (`_SENALES`) las reutiliza el Monitor, que añade las suyas.
"""
from __future__ import annotations

import re
from .rutas import sin_acentos

MODOS = ("equipo", "5", "10", "manual")
MODO_POR_DEFECTO = "equipo"
ETIQUETA_MODO = {"equipo": "Equipo", "5": "Cada 5 min", "10": "Cada 10 min", "manual": "Solo cuando lo pida"}


def normalizar_modo(valor) -> str:
    """Acepta 5/10 (como número o texto), «equipo» (y «adaptativo», su nombre antes del equipo) y «manual»; lo demás es un error del llamador."""
    if isinstance(valor, bool):
        raise ValueError("Cadencia no válida.")
    v = str(valor if valor is not None else MODO_POR_DEFECTO).strip().lower()
    if v == "adaptativo":
        return "equipo"
    if v in MODOS:
        return v
    raise ValueError("La cadencia debe ser el equipo, de 5 o 10 minutos, o solo a petición.")


def minutos_de(modo: str) -> int:
    """Minutos de la cadencia fija (0 si no la tiene)."""
    return int(modo) if modo in ("5", "10") else 0


# (etiqueta, patrón) sobre texto en minúsculas y SIN acentos. El primero que casa da el motivo que se muestra.
_SENALES: list[tuple[str, re.Pattern]] = [(e, re.compile(p)) for e, p in [
    ("decisión", r"\b(decidimos|decidido|decidid[oa]s|acordamos|acordado|acordad[oa]s|queda(n|mos)?\b|lo hacemos|lo dejamos|"
                 r"nos quedamos|aprobad[oa]|cerramos|vamos a (hacer|dejar|usar|ir con|montar)|lo damos por|"
                 # catalán (solo palabras que el español no usa; «queda» ya es común a los dos)
                 r"decidim|decidit|acordem|acordat|ho fem|ho deixem|ens quedem|aprovat|aprovada|tanquem|"
                 r"anem a (fer|deixar|usar|utilitzar|anar amb|muntar))"),
    ("alcance", r"\b(no entra(n)?|queda(n)? fuera|fuera de(l)? alcance|entra en (esta )?fase|"
                r"queda(n)? fora|fora de l.abast|entra en aquesta fase)"),
    ("prioridad", r"\b(prioridad|prioritari[oa]s?|lo primero|lo mas urgente|prioritat(s)?|prioritari(es|s|a)?|el primer de tot|el mes urgent)\b"),
    ("pendiente", r"\b(pendientes?|me encargo|te encargas|se encarga|nos encargamos|queda por|falta por|hay que|"
                  r"pendents?|m.encarrego|t.encarregues|s.encarrega|ens n.encarreguem|queda per|falta per|hem de|cal que)\b"),
    ("fecha", r"\b(fecha|plazo|deadline|para el (lunes|martes|miercoles|jueves|viernes|dia|proximo)|"
              r"\d{1,2} de (enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|setiembre|octubre|noviembre|diciembre)|"
              r"\d{1,2}/\d{1,2}(/\d{2,4})?|semana que viene|la semana (del|proxima)|antes del? (lunes|viernes|fin)|"
              r"termini|per (al |a )?(dilluns|dimarts|dimecres|dijous|divendres|dia|proper)|"
              r"\d{1,2} (de |d.)(gener|febrer|marc|abril|maig|juny|juliol|agost|setembre|octubre|novembre|desembre)|"
              r"setmana (que ve|vinent)|la setmana (del|propera|vinent)|abans (del?|de l.) ?(dilluns|divendres|final))"),
    ("riesgo", r"\b(riesgos?|bloqueo|bloqueado|bloquea|no llegamos|nos pasamos|problema serio|dependemos de|"
               r"riscos?|bloqueig|bloquejat|bloquejada|bloqueja|no hi arribem|ens passem|problema serios|depenem de)\b"),
    ("cifra", r"(\d+([.,]\d+)?\s?(%|€|euros?|mil\b|k\b|dias|horas|jornadas|semanas|meses|personas|hoteles|habitaciones|noches|usuarios|"
              r"dies|hores|jornades|setmanes|mesos|persones|hotels|habitacions|nits|usuaris)|"
              r"\b\d{3,}\b)"),
    ("pregunta", r"(\?|\balguien sabe|\bsabeis si|\bsabes si|\bpuedes (confirmar|decirme|mirar)|\bpodeis (confirmar|decir)|"
                 r"\balgu sap|\bsabeu si|\bsaps si|\bpots (confirmar|dir-me|mirar)|\bpodeu (confirmar|dir))"),
]]


def detectar_senal(texto: str) -> str | None:
    """Etiqueta de la primera señal local que aparece en `texto`, o None. Sin LLM."""
    t = sin_acentos(texto or "").lower()
    if not t.strip():
        return None
    for etiqueta, patron in _SENALES:
        if patron.search(t):
            return etiqueta
    return None
