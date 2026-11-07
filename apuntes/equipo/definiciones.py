"""Panel de Definiciones: la detección local (Monitor) vale hasta que la Analista funcional emite la misma con su modelo.

Reglas (DESIGN-equipo.md §3 y criterio 7): una `d` de la Analista con el mismo término (sin acentos ni mayúsculas, ≥0,8 de solape)
SUSTITUYE a la local —no se duplica— y conserva el minuto MÁS ANTIGUO. Dos de la Analista con el mismo término se funden en una.
"""
from __future__ import annotations

from ..texto import a_segundos, mmss
from .monitor import mismo_termino


class Definiciones:
    def __init__(self):
        self.lista: list[dict] = []

    def reiniciar(self) -> None:
        self.lista = []

    @staticmethod
    def _t(d: dict) -> float:
        return d["t"] if d.get("t") is not None else 10 ** 9

    def anadir_local(self, d: dict) -> bool:
        """Local del Monitor: {termino, definicion, parcial, t, minuto}. No se añade si ya hay una para el mismo término."""
        if any(mismo_termino(d["termino"], x["termino"]) for x in self.lista):
            return False
        self.lista.append({**d, "origen": "local"})
        return True

    def desde_analista(self, termino: str, definicion: str, minuto: str, t_ahora: float | None = None) -> dict:
        """Definición de la Analista funcional. Devuelve la fila resultante."""
        seg = a_segundos(minuto or "")
        t = float(seg) if seg is not None else t_ahora
        for x in self.lista:
            if mismo_termino(termino, x["termino"]):
                if x["origen"] == "analista":
                    x["t"] = min(self._t(x), self._t({"t": t}))
                    x["minuto"] = mmss(x["t"]) if x["t"] < 10 ** 9 else x["minuto"]
                    return x
                antiguo = min(self._t(x), self._t({"t": t}))
                x.update(termino=termino, definicion=definicion, origen="analista", parcial=False, t=antiguo if antiguo < 10 ** 9 else None,
                         minuto=mmss(antiguo) if antiguo < 10 ** 9 else (minuto or ""))
                return x
        fila = {"termino": termino, "definicion": definicion, "parcial": False, "origen": "analista", "t": t, "minuto": mmss(t) if t is not None else (minuto or "")}
        self.lista.append(fila)
        return fila

    def publico(self) -> list[dict]:
        """Orden cronológico inverso (lo último arriba)."""
        return [dict(x) for x in sorted(self.lista, key=lambda d: -(d["t"] if d.get("t") is not None else -1))]

    def lineas(self) -> list[str]:
        """Para el resumen final: `[MM:SS] término: definición`."""
        return [f"[{d.get('minuto') or '--:--'}] {d['termino']}: {d['definicion']}" for d in sorted(self.lista, key=self._t)]
