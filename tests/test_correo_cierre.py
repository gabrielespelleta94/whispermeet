"""Borrador del correo de cierre: local, texto plano, sin inventar nada (apuntes/correo_cierre.py)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from apuntes import correo_cierre as CC
from apuntes.sesion import Sesion
from test_gestor import esperar, montaje  # noqa: F401  (fixture)
import asyncio

OBJ = [{"texto": "Cerrar el alcance", "estado": "cubierto"}, {"texto": "Fijar el calendario", "estado": "parcial"},
       {"texto": "Revisar el presupuesto", "estado": "sin_tratar"}]
TJ = [{"categoria": "decisión", "texto": "Se usa el cupo del 10 %"},
      {"categoria": "pendiente", "texto": "Enviar la tarifa", "responsable": "Marta"},
      {"categoria": "pendiente", "texto": "Revisar el contrato", "responsable": "sin asignar"},
      {"categoria": "pendiente", "texto": "Llamar al hotel"},
      {"categoria": "pregunta", "texto": "¿Quién paga el transporte?"},
      {"categoria": "idea", "texto": "Probar un piloto"}, {"categoria": "riesgo", "texto": "Retraso del proveedor"}]


def test_asunto_y_bloques():
    t = CC.construir_correo("Seguimiento TR2", "06/11/2026", OBJ, TJ, [{"tipo": "pregunta", "texto": "¿Hay presupuesto extra?"}, {"tipo": "idea", "texto": "x"}])
    L = t.split("\n")
    assert L[0] == "Asunto: Resumen: Seguimiento TR2 (06/11/2026)"
    assert t.index("\nCerrado\n") < t.index("\nAbierto\n")
    cerrado, abierto = t.split("\nCerrado\n")[1].split("\nAbierto\n")
    assert "- Objetivo cubierto: Cerrar el alcance" in cerrado and "- Decisión: Se usa el cupo del 10 %" in cerrado
    assert "Fijar el calendario" not in cerrado
    assert "- Objetivo sin cerrar: Fijar el calendario" in abierto and "- Objetivo sin tratar: Revisar el presupuesto" in abierto
    assert "- Pendiente: Enviar la tarifa (Marta)" in abierto
    assert "- Pregunta abierta: ¿Quién paga el transporte?" in abierto and "- Pregunta abierta: ¿Hay presupuesto extra?" in abierto
    assert "piloto" not in t and "Retraso" not in t        # ideas y riesgos no son ni cerrado ni abierto
    assert t.rstrip().endswith("Un saludo.") and "Hola:" in t


def test_el_responsable_nunca_se_inventa():
    t = CC.construir_correo("T", "01/01/2026", tarjetas=TJ)
    assert "- Pendiente: Revisar el contrato\n" in t + "\n" and "sin asignar" not in t
    assert "- Pendiente: Llamar al hotel\n" in t + "\n"


def test_sin_nada_que_contar_no_hay_correo():
    assert CC.construir_correo("T", "01/01/2026") == ""
    assert CC.construir_correo("T", "01/01/2026", tarjetas=[{"categoria": "idea", "texto": "x"}]) == ""
    assert CC.seccion_md("") == []


def test_solo_un_bloque_si_el_otro_esta_vacio():
    t = CC.construir_correo("T", "01/01/2026", tarjetas=[{"categoria": "decisión", "texto": "Vamos con A"}])
    assert "\nCerrado\n" in t and "Abierto" not in t
    t = CC.construir_correo("T", "01/01/2026", tarjetas=[{"categoria": "pregunta", "texto": "¿Fecha?"}])
    assert "\nAbierto\n" in t and "Cerrado" not in t


def test_sin_duplicados_ni_florituras():
    t = CC.construir_correo("T", "01/01/2026", tarjetas=[{"categoria": "decisión", "texto": "Vamos con A."}, {"categoria": "decisión", "texto": " vamos  con a "}])
    assert t.count("Decisión:") == 1
    for palabra in ("IA", "inteligencia", "automático", "Claude", "espero que"):
        assert palabra not in t


def test_la_sesion_lo_guarda_en_el_md_solo_si_hay_contenido(tmp_path):
    s = Sesion("Proy", "Tema de prueba", 5, tmp_path / "s.md", inicio=datetime(2026, 11, 6, 10, 0))
    s.estado = "finalizada"
    assert "## Correo de cierre" not in s.render()
    s.objetivos = [dict(o, n=i, minuto="", t_seg=None) for i, o in enumerate(OBJ, 1)]
    s.tarjetas = [dict(t, minuto="01:00") for t in TJ]
    md = s.render()
    assert "## Correo de cierre" in md and "Asunto: Resumen: Tema de prueba (06/11/2026)" in md
    assert md.index("## Correo de cierre") < md.index("## Transcripción")
    s.estado = "en curso"
    assert "## Correo de cierre" not in s.render()      # en directo no hay correo: solo al terminar


def test_la_revision_lleva_el_correo_y_el_md_su_seccion(montaje):
    gestor, llm, eventos, raiz, tmp = montaje

    async def go():
        await gestor.iniciar("Proyecto Ficticio Alfa", "Seguimiento", 5)
        await esperar(lambda: len(gestor.sesion.segmentos) >= 40)
        assert (await gestor.analizar(manual=True))["ok"]
        await esperar(lambda: len(gestor.sesion.segmentos) >= 60)
        assert gestor.estado_ligero()["revision"] is None
        await gestor.terminar()
        await esperar(lambda: gestor.revision["estado"] == "lista")
        correo = gestor.revision_publica()["correo"]
        assert correo.startswith("Asunto: Resumen: Seguimiento (")
        assert "- Decisión: El piloto sigue el 20 de enero" in correo and "- Pendiente: Estimar SAP (Luis)" in correo
        assert gestor.estado_ligero()["revision"]["correo"] == correo
        md = gestor.sesion.ruta.read_text(encoding="utf-8")
        assert "## Correo de cierre" in md and correo in md
        await gestor.cerrar_revision()

    asyncio.run(go())
