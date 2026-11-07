r"""Genera el icono de WhisperMeet: web/marca/apuntes.ico (PNG en 9 tamaños), apuntes.svg y apuntes-256.png.

    .venv\Scripts\python.exe marca\generar_logo.py

Cuadrado redondeado azul #007AFF (radio 0,22 del lado) con barras verticales blancas de extremos redondeados. Solo numpy y stdlib.
Hasta 48 px la geometría es exacta en píxeles enteros (tabla PEQUENOS); desde 64 es proporcional al lado.
"""
from __future__ import annotations

import struct
import zlib
from pathlib import Path

import numpy as np

SALIDA = Path(__file__).resolve().parent.parent / "web" / "marca"
AZUL, BLANCO = (0, 122, 255), (255, 255, 255)
TAMANOS = (16, 20, 24, 32, 40, 48, 64, 128, 256)
RADIO = 0.22                 # del lado del cuadrado
MARGEN = 0.03                # a cada lado, desde 32 px (hasta 24 el cuadrado llena el lienzo)
ANCHO, PASO = 0.09, 0.15     # proporcionales (desde 64 px)
ALTURAS = (0.2, 0.42, 0.6, 0.42, 0.2)

# n: (ancho de barra, hueco, alturas) en píxeles; margen del cuadrado en píxeles
PEQUENOS = {
    16: (2, 2, (6, 12, 6)),
    20: (2, 3, (8, 14, 8)),
    24: (2, 2, (4, 10, 16, 10, 4)),
    32: (2, 3, (6, 14, 20, 14, 6)),
    40: (4, 3, (8, 18, 26, 18, 8)),
    48: (4, 4, (10, 20, 30, 20, 10)),
}
MARGEN_PEQUENO = {16: 0, 20: 0, 24: 0, 32: 1, 40: 1, 48: 1}


def _cuadrado(n: int):
    """(x0, y0, lado, radio) del cuadrado azul en píxeles."""
    m = MARGEN_PEQUENO[n] if n in MARGEN_PEQUENO else (MARGEN * n if n >= 32 else 0)
    lado = n - 2 * m
    return m, m, lado, RADIO * lado


def _barras(n: int):
    """Lista de (x0, y0, ancho, alto) de cada barra, en píxeles, centradas en el lienzo."""
    if n in PEQUENOS:
        w, hueco, alturas = PEQUENOS[n]
        paso = w + hueco
        total = len(alturas) * w + (len(alturas) - 1) * hueco
        x0 = (n - total) / 2
        return [(x0 + i * paso, (n - h) / 2, w, h) for i, h in enumerate(alturas)]
    w, paso, k = ANCHO * n, PASO * n, len(ALTURAS) // 2
    return [(n / 2 + (i - k) * paso - w / 2, (n - h * n) / 2, w, h * n) for i, h in enumerate(ALTURAS)]


def _cobertura_rrect(X, Y, x0, y0, w, h, r):
    """Cobertura (0..1) de un rectángulo redondeado: distancia con signo y suavizado de medio píxel."""
    cx, cy = x0 + w / 2, y0 + h / 2
    qx, qy = np.abs(X - cx) - (w / 2 - r), np.abs(Y - cy) - (h / 2 - r)
    d = np.hypot(np.maximum(qx, 0), np.maximum(qy, 0)) + np.minimum(np.maximum(qx, qy), 0) - r
    return np.clip(0.5 - d, 0, 1)


def pintar(n: int) -> np.ndarray:
    """RGBA uint8 (n, n, 4): alfa = cobertura del cuadrado; color = azul mezclado con blanco según la cobertura de barra."""
    Y, X = np.mgrid[0:n, 0:n]
    X, Y = X + 0.5, Y + 0.5
    x0, y0, lado, radio = _cuadrado(n)
    alfa = _cobertura_rrect(X, Y, x0, y0, lado, lado, radio)
    barra = np.zeros((n, n))
    for bx, by, bw, bh in _barras(n):
        barra = np.maximum(barra, _cobertura_rrect(X, Y, bx, by, bw, bh, bw / 2))
    barra = np.minimum(barra, alfa)
    rgb = np.array(AZUL, float) * (1 - barra[..., None]) + np.array(BLANCO, float) * barra[..., None]
    return np.dstack([np.rint(rgb), np.rint(alfa * 255)]).astype(np.uint8)


def _chunk(tipo: bytes, datos: bytes) -> bytes:
    return struct.pack(">I", len(datos)) + tipo + datos + struct.pack(">I", zlib.crc32(tipo + datos))


def png_bytes(rgba: np.ndarray) -> bytes:
    """PNG RGBA de 8 bits (color type 6), sin filtro."""
    h, w = rgba.shape[:2]
    crudo = b"".join(b"\0" + rgba[y].tobytes() for y in range(h))
    return (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + _chunk(b"IDAT", zlib.compress(crudo, 9)) + _chunk(b"IEND", b""))


def ico_bytes(pngs: dict[int, bytes]) -> bytes:
    """ICO con una entrada PNG por tamaño (256 se escribe como 0)."""
    n = len(pngs)
    cabecera = struct.pack("<HHH", 0, 1, n)
    entradas, datos, desplazamiento = b"", b"", 6 + 16 * n
    for tam, png in pngs.items():
        b = 0 if tam >= 256 else tam
        entradas += struct.pack("<BBBBHHII", b, b, 0, 0, 1, 32, len(png), desplazamiento + len(datos))
        datos += png
    return cabecera + entradas + datos


def _f(x: float) -> str:
    return f"{x:.4f}".rstrip("0").rstrip(".")


def svg_texto() -> str:
    """SVG (viewBox 0 0 64 64) con las proporciones de los tamaños grandes y colores directos."""
    n = 64
    x0, y0, lado, radio = _cuadrado(n)
    barras = "\n".join(
        f'  <rect x="{_f(bx)}" y="{_f(by)}" width="{_f(bw)}" height="{_f(bh)}" rx="{_f(bw / 2)}"/>' for bx, by, bw, bh in _barras(n))
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="64" height="64">\n'
            f'  <rect x="{_f(x0)}" y="{_f(y0)}" width="{_f(lado)}" height="{_f(lado)}" rx="{_f(radio)}" fill="#007AFF"/>\n'
            f'<g fill="#FFFFFF">\n{barras}\n</g>\n</svg>\n')


def main() -> None:
    SALIDA.mkdir(parents=True, exist_ok=True)
    pngs = {n: png_bytes(pintar(n)) for n in TAMANOS}
    (SALIDA / "apuntes.ico").write_bytes(ico_bytes(pngs))
    (SALIDA / "apuntes-256.png").write_bytes(pngs[256])
    (SALIDA / "apuntes.svg").write_text(svg_texto(), encoding="utf-8")
    print(f"Escrito en {SALIDA}: apuntes.ico ({len(TAMANOS)} tamaños), apuntes.svg, apuntes-256.png")


if __name__ == "__main__":
    main()
