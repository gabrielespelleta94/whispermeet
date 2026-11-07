"""Capa de análisis. Interfaz única (`ModeloLLM`) con una sola implementación: `claude -p`.

El análisis usa SOLO Claude Code con la licencia del usuario; nunca la API ni claves.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Uso:
    modelo: str
    entrada: int = 0
    salida: int = 0
    cache_creacion: int = 0
    cache_lectura: int = 0
    coste_ref_usd: float = 0.0
    razonamiento: int = 0   # tokens de salida gastados en razonar (incluidos en `salida`), si el CLI los informa


@dataclass
class Respuesta:
    texto: str
    uso: list[Uso] = field(default_factory=list)
    ms: int = 0


class ErrorAnalisis(Exception):
    """tipo: sesion | limite | tiempo | salida | otro. `mensaje` es apto para mostrar al usuario."""

    def __init__(self, tipo: str, mensaje: str, transitorio: bool = False):
        super().__init__(mensaje)
        self.tipo, self.mensaje, self.transitorio = tipo, mensaje, transitorio

    @property
    def bloqueante(self) -> bool:
        """Sesión no iniciada o límite del plan: no tiene sentido reintentar solo."""
        return self.tipo in ("sesion", "limite")


class ModeloLLM(ABC):
    @abstractmethod
    def completar(self, sistema: str, usuario: str, modelo: str, esfuerzo: str = "", timeout_s: int = 240,
                  sin_razonamiento: bool = False, web: bool = False) -> Respuesta:
        """Una llamada sin herramientas (`web`: solo la búsqueda web, y solo cuando el usuario la pidió en «Profundizar»). Lanza ErrorAnalisis."""


def crear_modelo(config) -> ModeloLLM:
    from .claude_cli import ClaudeCLI
    return ClaudeCLI()
