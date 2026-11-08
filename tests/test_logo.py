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


def test_a_16_px_hay_tres_columnas_con_barras():
    png = next(e[4] for e in _entradas() if e[0] == 16)
    img = _decodificar(png)
    blanca = (img[..., 1] > 200) & (img[..., 3] == 255)   # barra color papel (verde alto); el fondo bermellón (#CD432C) tiene el verde en 67
    con_barra = blanca.any(axis=0)
    grupos = [i for i in range(16) if con_barra[i] and (i == 0 or not con_barra[i - 1])]
    assert len(grupos) == 3
    assert con_barra.sum() == 6                      # tres barras de 2 px de ancho
    assert [int(blanca[:, c].sum()) for c in (3, 7, 11)] == [6, 12, 6]   # alturas 6, 12, 6
