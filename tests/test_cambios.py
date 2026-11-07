import pytest

from apuntes import cambios as CB

TEXTO = """# 02 · Alcance

## Qué entra

- A
- B

## Qué no entra

- SAP

## Cambios de alcance

| Fecha | Cambio |
|---|---|
| 2026-10-05 | Uno |
"""


def cambio(**kw):
    base = dict(id="c1", fichero="02-alcance.md", tipo="anadir", motivo="m", minuto="01:00")
    base.update(kw)
    return CB.Cambio(**base)


def test_anadir_al_final_de_seccion():
    out = CB.aplicar(TEXTO, cambio(seccion="Qué entra", nuevo="- C"))
    assert "- B\n- C\n\n## Qué no entra" in out


def test_anadir_en_ultima_seccion_y_sin_seccion():
    out = CB.aplicar(TEXTO, cambio(seccion="## Cambios de alcance", nuevo="| 2026-11-03 | Dos |"))
    assert out.rstrip().endswith("| 2026-11-03 | Dos |")
    assert CB.aplicar(TEXTO, cambio(nuevo="Nota final")).rstrip().endswith("Nota final")


def test_reemplazar_exige_texto_unico():
    out = CB.aplicar(TEXTO, cambio(tipo="reemplazar", anterior="- SAP", nuevo="- SAP (fase 2)"))
    assert "- SAP (fase 2)" in out
    with pytest.raises(ValueError):
        CB.aplicar(TEXTO, cambio(tipo="reemplazar", anterior="no está", nuevo="x"))
    with pytest.raises(ValueError):
        CB.aplicar(TEXTO, cambio(tipo="reemplazar", anterior="-", nuevo="x"))


def test_seccion_inexistente():
    with pytest.raises(ValueError):
        CB.aplicar(TEXTO, cambio(seccion="No existe", nuevo="x"))


def test_normalizar_rechaza_ficheros_peligrosos():
    contenidos = {"02-alcance.md": TEXTO, "10-registro-de-cambios.md": "x"}
    raw = [{"f": f, "tipo": "anadir", "nuevo": "x", "motivo": "m"} for f in
           ["02-alcance.md", "CLAUDE.md", "AGENTS.md", "../02-alcance.md", "docs/a.md", "10-registro-de-cambios.md"]]
    res = CB.normalizar(raw, contenidos)
    validos = [c.fichero for c in res if c.valido]
    assert validos == ["02-alcance.md"]


def test_normalizar_diff_y_limites():
    contenidos = {"02-alcance.md": TEXTO}
    raw = [{"f": "02-alcance.md", "tipo": "reemplazar", "ant": "- SAP", "nuevo": "- SAP en fase 2",
            "motivo": "m", "m": "03:05"}] * 9
    res = CB.normalizar(raw, contenidos)
    assert len(res) == CB.MAX_CAMBIOS and res[0].valido and "+- SAP en fase 2" in res[0].diff
    assert res[0].minuto == "03:05"


def test_crear_no_pisa_existentes():
    contenidos = {"02-alcance.md": TEXTO}
    ok = CB.normalizar([{"f": "11-sesion-x.md", "tipo": "crear", "nuevo": "# x"}], contenidos)[0]
    assert ok.valido
    mal = CB.normalizar([{"f": "02-alcance.md", "tipo": "crear", "nuevo": "# x"}], contenidos)[0]
    assert not mal.valido


def test_registro_arriba_y_respeta_plantilla():
    reg = ("# 10\n\n## Plantilla\n\n```markdown\n### AAAA-MM-DD HH:MM · Qué\n```\n\n---\n\n"
           "### 2026-10-01 00:00 · Antes\n\n- x\n")
    out = CB.insertar_en_registro(reg, CB.entrada_registro("Yo", "Tema", ["02-alcance.md"], "f.md"))
    assert out.index("Contexto actualizado") < out.index("2026-10-01 00:00 · Antes")
    assert out.index("```markdown") < out.index("Contexto actualizado")
