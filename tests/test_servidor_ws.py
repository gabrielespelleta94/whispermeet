"""WebSocket /ws: un cliente atascado (cola desbordada) se desconecta del Difusor Y se le cierra el socket para que reconecte."""
import pytest
from starlette.websockets import WebSocketDisconnect

from apuntes.servidor import Difusor
from test_servidor_plan import PUERTO, TOKEN, cliente


@pytest.fixture
def difusores(monkeypatch):
    """Los Difusor que se crean durante la prueba (`cliente` no devuelve el suyo)."""
    creados = []
    original = Difusor.__init__

    def init(self):
        original(self)
        creados.append(self)
    monkeypatch.setattr(Difusor, "__init__", init)
    return creados


def test_cliente_atascado_se_cierra_y_sale_del_difusor(tmp_path, monkeypatch, difusores):
    monkeypatch.setattr(Difusor, "MAX_COLA", -1)   # cualquier evento desborda la cola: simula un cliente que no consume
    cli, _ = cliente(tmp_path)
    dif = difusores[0]
    with cli, cli.websocket_connect(f"/ws?t={TOKEN}", headers={"host": f"127.0.0.1:{PUERTO}"}) as ws:
        assert ws.receive_json()["tipo"] == "snapshot"
        assert len(dif.colas) == 1 and len(dif.cierres) == 1
        dif.emitir({"tipo": "prueba"})
        with pytest.raises(WebSocketDisconnect) as e:
            ws.receive_json()
        assert e.value.code == 1013
    assert not dif.colas and not dif.cierres


def test_cliente_al_dia_sigue_recibiendo_eventos(tmp_path, difusores):
    cli, _ = cliente(tmp_path)
    dif = difusores[0]
    with cli, cli.websocket_connect(f"/ws?t={TOKEN}", headers={"host": f"127.0.0.1:{PUERTO}"}) as ws:
        ws.receive_json()
        dif.emitir({"tipo": "prueba", "n": 1})
        assert ws.receive_json() == {"tipo": "prueba", "n": 1}
        assert len(dif.colas) == 1
