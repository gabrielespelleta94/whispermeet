"""El icono de WhisperMeet: ICO con 9 entradas PNG válidas y la geometría de 16 px (marca/generar_logo.py)."""
import struct
import zlib
from pathlib import Path

import numpy as np

ICO = Path(__file__).resolve().parent.parent / "web" / "marca" / "apuntes.ico"
TAMANOS = [16, 20, 24, 32, 40, 48, 64, 128, 256]


def _entradas():
    datos = ICO.read_bytes()
    reservado, tipo, n = struct.unpack_from("<HHH", datos, 0)
    assert (reservado, tipo) == (0, 1)
    sal = []
    for i in range(n):
        w, h, _c, _r, planos, bpp, tam, desp = struct.unpack_from("<BBBBHHII", datos, 6 + 16 * i)
        sal.append((w or 256, h or 256, planos, bpp, datos[desp:desp + tam]))
    return sal


def _decodificar(png: bytes) -> np.ndarray:
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ihdr = 8, b"", None
    while pos < len(png):
        largo, tipo = struct.unpack_from(">I4s", png, pos)
        cuerpo = png[pos + 8:pos + 8 + largo]
        assert struct.unpack_from(">I", png, pos + 8 + largo)[0] == zlib.crc32(tipo + cuerpo)
        if tipo == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", cuerpo)
        elif tipo == b"IDAT":
            idat += cuerpo
        pos += 12 + largo
    w, h, prof, color, *_ = ihdr
    assert (prof, color) == (8, 6)   # RGBA de 8 bits
    crudo = zlib.decompress(idat)
    paso = w * 4 + 1
    filas = []
    for y in range(h):
        assert crudo[y * paso] == 0   # sin filtro (lo escribe así generar_logo.py)
        filas.append(np.frombuffer(crudo, np.uint8, w * 4, y * paso + 1).reshape(w, 4))
    return np.array(filas)


def test_ico_tiene_nueve_entradas_png_validas():
    entradas = _entradas()
    assert [e[0] for e in entradas] == TAMANOS
    for w, h, planos, bpp, png in entradas:
        assert (w, h, planos, bpp) == (w, w, 1, 32)
        img = _decodificar(png)
        assert img.shape == (w, w, 4)
        assert img[0, 0, 3] == 0                    # esquina redondeada: transparente
        assert img[w // 4, w // 2, 3] == 255        # el cuadrado es opaco por dentro


def test_a_16_px_hay_los_dos_canales():
    """Marca Estéreo (DESIGN-visual.md §0): barra de la sala (rosa, 4×10) a la izquierda y del micro (azul, 4×7) a la derecha, sobre noche fría, con la misma base."""
    png = next(e[4] for e in _entradas() if e[0] == 16)
    img = _decodificar(png).astype(int)
    opaco = img[..., 3] == 255
    rosa = (img[..., 0] > 200) & (img[..., 2] < 160) & opaco
    azul = (img[..., 2] > 200) & (img[..., 0] < 120) & opaco
    assert [c for c in range(16) if rosa[:, c].any()] == [3, 4, 5, 6]
    assert [c for c in range(16) if azul[:, c].any()] == [9, 10, 11, 12]
    assert int(rosa[:, 4].sum()) == 10 and int(azul[:, 10].sum()) == 7          # alturas 10 y 7
    assert max(r for r in range(16) if rosa[r, 4]) == max(r for r in range(16) if azul[r, 10]) == 12   # misma base
    assert img[1, 8, :3].max() < 40                                               # fondo de noche fría
