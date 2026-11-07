"""Presupuesto de tokens por hora: ventana deslizante de 60 minutos sobre el reloj de la reunión.

Cuenta TODO lo que consume la sesión (entrada con caché, caché leída y salida), igual que `consumo.jsonl`. Niveles:
- normal (< 80 %);
- ahorro (≥ 80 %): enfriamiento global 300 s, por perfil 720 s y sin rotación (lo aplica el Monitor);
- agotado (≥ 100 %): solo Monitor, «Analizar ahora» y Pregúntale. El cierre con sonnet nunca se bloquea por presupuesto.
"""
from __future__ import annotations

VENTANA_S = 3600.0
UMBRAL_AHORRO = 0.8


class Presupuesto:
    def __init__(self, limite: int = 60_000):
        self.limite = max(1, int(limite))
        self.registros: list[tuple[float, int, str]] = []   # (t de la reunión, tokens, tarea)

    def fijar_limite(self, limite: int) -> None:
        self.limite = max(1, int(limite))

    def reiniciar(self) -> None:
        self.registros = []

    def sumar(self, t: float, tokens: int, tarea: str = "") -> None:
        if tokens > 0:
            self.registros.append((float(t), int(tokens), tarea))

    def usado(self, t: float) -> int:
        return sum(k for ts, k, _ in self.registros if t - ts < VENTANA_S)

    def total(self) -> int:
        return sum(k for _, k, _ in self.registros)

    def fraccion(self, t: float) -> float:
        return self.usado(t) / self.limite

    def nivel(self, t: float) -> str:
        f = self.fraccion(t)
        return "agotado" if f >= 1.0 else "ahorro" if f >= UMBRAL_AHORRO else "normal"

    def libera_en(self, t: float) -> float | None:
        """Segundos hasta que la ventana libera tokens suficientes para volver por debajo del 100 %, o None si ya lo está."""
        vivos = sorted((ts, k) for ts, k, _ in self.registros if t - ts < VENTANA_S)
        total = sum(k for _, k in vivos)
        if total < self.limite:
            return None
        for ts, k in vivos:
            total -= k
            if total < self.limite:
                return max(0.0, ts + VENTANA_S - t)
        return None

    def publico(self, t: float, velocidad: float = 1.0, hora_actual=None) -> dict:
        """`hora_actual`: datetime de ahora (para dar la hora real de liberación). `velocidad`: aceleración de la simulación."""
        libera = self.libera_en(t)
        d = {"usado": self.usado(t), "limite": self.limite, "fraccion": round(self.fraccion(t), 3), "nivel": self.nivel(t), "libera_en": None, "libera_a": ""}
        if libera is not None:
            d["libera_en"] = round(libera)
            if hora_actual is not None:
                from datetime import timedelta
                d["libera_a"] = (hora_actual + timedelta(seconds=libera / max(velocidad, 1e-6))).strftime("%H:%M")
        return d
