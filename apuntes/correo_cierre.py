"""Borrador del correo de cierre de una reunión. TODO LOCAL: sin modelo, sin red, sin abrir ningún cliente de correo.

Solo texto plano que el usuario copia a mano. Se construye con lo que ya hay en la sesión: objetivos, decisiones, pendientes y preguntas.
No se inventa nada: un responsable solo sale si ya estaba detectado (nunca «sin asignar»), y sin contenido no hay correo (cadena vacía).
"""
from __future__ import annotations

SIN_RESPONSABLE = {"", "sin asignar", "sin responsable", "—", "-", "?"}
TITULO_MD = "## Correo de cierre"


def _limpio(t) -> str:
    return " ".join(str(t or "").split())


def _unicos(lineas: list[str]) -> list[str]:
    vistos, out = set(), []
    for l in lineas:
        k = l.lower().rstrip(" .")
        if l and k not in vistos:
            vistos.add(k)
            out.append(l)
    return out


def _con_responsable(t: dict) -> str:
    texto = _limpio(t.get("texto")).rstrip()
    r = _limpio(t.get("responsable"))
    if r.lower() in SIN_RESPONSABLE:
        return texto
    return f"{texto} ({r})"


def construir_correo(tema: str, fecha: str, objetivos=(), tarjetas=(), entradas=(), extras=()) -> str:
    """Texto plano del correo («Asunto: …» + cuerpo) o «» si no hay nada cerrado ni abierto que contar. FUNCIÓN PURA.
    `fecha`: ya formateada (dd/mm/aaaa). Cerrado = objetivos cubiertos + decisiones. Abierto = objetivos sin cubrir (sin tratar o parciales)
    + pendientes (con responsable solo si ya lo traen) + preguntas abiertas (tarjetas y preguntas anotadas por el usuario).
    `extras` (ola 3): frases de acciones `correo` que el usuario aceptó; salen en «Además»."""
    objetivos, tarjetas, entradas = list(objetivos or ()), list(tarjetas or ()), list(entradas or ())
    cerrado = [f"Objetivo cubierto: {_limpio(o.get('texto'))}" for o in objetivos if o.get("estado") == "cubierto"]
    cerrado += [f"Decisión: {_limpio(t.get('texto'))}" for t in tarjetas if t.get("categoria") == "decisión"]
    abierto = [("Objetivo sin cerrar" if o.get("estado") == "parcial" else "Objetivo sin tratar") + f": {_limpio(o.get('texto'))}"
               for o in objetivos if o.get("estado") != "cubierto"]
    abierto += [f"Pendiente: {_con_responsable(t)}" for t in tarjetas if t.get("categoria") == "pendiente"]
    abierto += [f"Pregunta abierta: {_limpio(t.get('texto'))}" for t in tarjetas if t.get("categoria") == "pregunta"]
    abierto += [f"Pregunta abierta: {_limpio(e.get('texto'))}" for e in entradas if e.get("tipo") == "pregunta"]
    cerrado = _unicos([c for c in cerrado if not c.endswith(": ")])
    abierto = _unicos([a for a in abierto if not a.endswith(": ")])
    ademas = _unicos([_limpio(x) for x in (extras or ()) if _limpio(x)])
    if not cerrado and not abierto and not ademas:
        return ""
    tema, fecha = _limpio(tema) or "Reunión", _limpio(fecha)
    asunto = f"Resumen: {tema} ({fecha})" if fecha else f"Resumen: {tema}"
    L = [f"Asunto: {asunto}", "", "Hola:", "", f"Os dejo lo que ha quedado de la reunión «{tema}»." , ""]
    for titulo, items in (("Cerrado", cerrado), ("Abierto", abierto), ("Además", ademas)):
        if items:
            L += [titulo] + [f"- {i}" for i in items] + [""]
    L += ["Un saludo."]
    return "\n".join(L)


def correo_de_sesion(s) -> str:
    """El correo de una `Sesion` (objetivos, tarjetas y anotaciones tal cual están en ese momento)."""
    with s._lock:
        return construir_correo(s.tema, f"{s.inicio:%d/%m/%Y}", [dict(o) for o in s.objetivos], [dict(t) for t in s.tarjetas],
                                [dict(e) for e in s.entradas],
                                [a.get("texto", "") for a in getattr(s, "acciones", []) if a.get("tipo") == "correo" and a.get("estado") in ("aceptada", "hecha")])


def seccion_md(texto: str) -> list[str]:
    """Líneas de la sección «## Correo de cierre» del .md (vacío si no hay correo). En bloque de código para que se conserve tal cual."""
    if not texto:
        return []
    return [TITULO_MD, "", "```text", texto, "```", ""]
