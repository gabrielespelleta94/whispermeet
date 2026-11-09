import numpy as np

from apuntes.audio import Captura, elegir_dispositivo

ENTRADAS = [{"indice": 14}, {"indice": 15}]


def test_indice_guardado_valido_se_respeta():
    assert elegir_dispositivo(15, ENTRADAS, 14) == 15


def test_indice_que_ya_no_captura_pasa_al_de_por_defecto():
    assert elegir_dispositivo(9, ENTRADAS, 14) == 14


def test_sin_indice_guardado_usa_el_de_por_defecto():
    assert elegir_dispositivo(None, ENTRADAS, 14) == 14


def test_al_entrar_en_pausa_se_entrega_el_enunciado_a_medias_y_despues_se_descarta():
    entregados = []
    c = Captura(lambda: 0.0, lambda f, a, t: entregados.append((f, a.size)), lambda *a: None)
    voz = (np.sin(np.linspace(0, 2000, 16000)) * 12000).astype(np.int16).tobytes()   # 1 s de voz: el segmentador queda «en voz»

    class Cola:   # sin dispositivos: el hilo de trabajo lee de una cola simulada
        n = 0

        def get(self, timeout=None):
            self.n += 1
            if self.n == 2:
                c.pausada = True      # el usuario pulsa «Pausa» con la frase a medias
            if self.n == 4:
                c._parar.set()
            return voz
    c._trabajo("yo", Cola(), 16000, 1)
    assert entregados == [("yo", 33 * 480)]   # solo la voz previa a la pausa; la de durante la pausa se descarta


def test_la_captura_pasa_cada_bloque_ya_convertido_a_on_bloque_y_un_fallo_suyo_no_la_detiene():
    bloques, entregados = [], []
    reloj = iter([1.0, 1.05, 1.1, 1.15, 1.2, 1.25, 1.3, 1.35])

    def on_bloque(fuente, x, t):
        bloques.append((fuente, x.dtype.name, x.size, float(abs(x).max()) <= 1.0))
        if len(bloques) == 2:
            raise RuntimeError("el observador falla")   # el detector de eco nunca puede parar la captura

    c = Captura(lambda: next(reloj, 9.0), lambda f, a, t: entregados.append(f), lambda *a: None, on_bloque=on_bloque)
    voz = (np.sin(np.linspace(0, 100, 800)) * 12000).astype(np.int16).tobytes()   # un bloque de 50 ms a 16 kHz

    class Cola:
        n = 0

        def get(self, timeout=None):
            self.n += 1
            if self.n == 4:
                c._parar.set()
            return voz
    c._trabajo("reunion", Cola(), 16000, 1)
    assert bloques == [("reunion", "float32", 800, True)] * 4   # los cuatro bloques, en float32 mono normalizado, también tras el fallo


def test_en_pausa_no_se_pasa_ningun_bloque_a_on_bloque():
    bloques = []
    c = Captura(lambda: 0.0, lambda *a: None, lambda *a: None, on_bloque=lambda f, x, t: bloques.append(f))
    c.pausada = True
    voz = (np.sin(np.linspace(0, 100, 800)) * 12000).astype(np.int16).tobytes()

    class Cola:
        n = 0

        def get(self, timeout=None):
            self.n += 1
            if self.n == 3:
                c._parar.set()
            return voz
    c._trabajo("reunion", Cola(), 16000, 1)
    assert bloques == []
