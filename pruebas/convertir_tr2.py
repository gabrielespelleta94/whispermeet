r"""Convierte el docx de transcripción de Teams (TR2) al formato de --simular. Solo lee el docx; escribe en pruebas/_real/.

    .venv\Scripts\python.exe pruebas\convertir_tr2.py "<ruta.docx>" pruebas\_real\tr2.txt
Cada turno trae solo su minuto de inicio; las frases se reparten entre ese minuto y el del turno siguiente
en proporción a sus palabras y, como mucho, hasta la duración real de la reunión (73:09): ningún minuto la supera.
«Sala Sants» (la sala: el micro recoge a varias personas) -> Micro; el resto -> Reunión. El simulador respeta estos minutos tal cual.
"""
import re
import sys
import zipfile
from pathlib import Path

DURACION_TOTAL = 4389  # 1 h 13 min 9 s, según la cabecera del docx


def parrafos(ruta):
    x = zipfile.ZipFile(ruta).read("word/document.xml").decode("utf8")
    for p in re.findall(r"<w:p[ >].*?</w:p>", x, re.S):
        yield "".join(re.findall(r"<w:t[^>]*>([^<]*)</w:t>", p))


def seg(s):
    v = [int(a) for a in s.split(":")]
    return v[0] * 3600 + v[1] * 60 + v[2] if len(v) == 3 else v[0] * 60 + v[1]


def main(ruta, salida):
    turnos = []
    for p in parrafos(ruta):
        m = re.match(r"^(.+?)\s{2,}(\d+(?::\d{2}){1,2})(.*)$", p)
        if m:
            turnos.append((m.group(1).strip(), seg(m.group(2)), m.group(3)))
    out, nlin, npal = [], 0, 0
    for i, (quien, t0, texto) in enumerate(turnos):
        t1 = turnos[i + 1][1] if i + 1 < len(turnos) else DURACION_TOTAL
        frases = [f.strip() for f in re.split(r"(?<=[.?!])(?=\S)|(?<=[.?!])\s+", texto) if f.strip()]
        bloques, act = [], []
        for f in frases:  # frases a líneas de ~30 palabras
            act.append(f)
            if sum(len(a.split()) for a in act) >= 30:
                bloques.append(" ".join(act)); act = []
        if act:
            bloques.append(" ".join(act))
        total = sum(len(b.split()) for b in bloques) or 1
        acum = 0
        for b in bloques:
            t = t0 + (t1 - t0) * acum / total
            acum += len(b.split())
            t = min(t, DURACION_TOTAL)
            out.append(f"[{int(t)//60:02d}:{int(t)%60:02d}] {'Micro' if quien == 'Sala Sants' else 'Reunión'}: {b}")
            nlin += 1
            npal += len(b.split())
    Path(salida).write_text("# TR2 convertida (turnos con minuto real; frases repartidas por palabras)\n" + "\n".join(out) + "\n", encoding="utf-8")
    print("turnos", len(turnos), "lineas", nlin, "palabras", npal, "ultimo", out[-1][:8])


main(sys.argv[1], sys.argv[2])
