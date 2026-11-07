"""Punto de entrada de WhisperMeet.

    .venv\\Scripts\\python.exe app.py                        # ventana propia
    .venv\\Scripts\\python.exe app.py --simular pruebas\\reunion-ficticia.txt --sin-ventana
"""
from __future__ import annotations

import argparse
import secrets
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn

from apuntes.analisis import crear_modelo
from apuntes.aviso import AvisoLlamada, limpiar_titulo, titulo_reunion_teams
from apuntes.config import APP_DIR, BACKLOG_DIR, BANDEJA_DIR, CACHE_DIR, CHECKS_DIR, DATOS_DIR, PLANES_DIR, SESIONES_DIR, Config
from apuntes.consumo import Consumo
from apuntes.gestor import Gestor
from apuntes.rutas import Guardian
from apuntes.servidor import HOST, Difusor, crear_app
from apuntes.simulador import cargar
from apuntes.ventana import llamar_atencion


def puerto_libre() -> int:
    with socket.socket() as s:
        s.bind((HOST, 0))
        return s.getsockname()[1]


def construir(args) -> tuple:
    cfg = Config(Path(args.config).resolve() if args.config else None)
    if args.raiz:
        cfg.actualizar({"raiz_proyectos": str(Path(args.raiz).resolve())}, guardar=False, solo_sesion=True)
    if args.extra:  # pruebas: sustituye los proyectos extra (sin tocar datos/config.json)
        extras = []
        for e in args.extra:
            nombre, _, ruta = e.partition("=")
            extras.append({"nombre": nombre, "ruta": str(Path(ruta).resolve()), "compartido": True})
        cfg.actualizar({"proyectos_extra": extras}, guardar=False, solo_sesion=True)
    elif args.simular:  # una simulación nunca ofrece carpetas compartidas reales: se publicaría en ellas
        cfg.actualizar({"proyectos_extra": []}, guardar=False, solo_sesion=True)
    planes = Path(args.planes).resolve() if args.planes else PLANES_DIR
    sesiones = Path(args.sesiones).resolve() if args.sesiones else SESIONES_DIR
    checks = Path(args.checks).resolve() if args.checks else CHECKS_DIR
    cache = Path(args.cache).resolve() if args.cache else CACHE_DIR
    bandeja = Path(args.bandeja).resolve() if args.bandeja else BANDEJA_DIR
    backlog = Path(args.backlog).resolve() if args.backlog else BACKLOG_DIR
    guardian = Guardian(cfg["raiz_proyectos"], bandeja, cache, solo_lectura=[cfg["knowledge"]],
                        extras=cfg["proyectos_extra"], sesiones_locales=sesiones, planes=planes, checks=checks, backlog=backlog)
    consumo = Consumo(Path(args.consumo).resolve() if args.consumo else DATOS_DIR / "consumo.jsonl")
    sim = cargar(args.simular) if args.simular else None
    difusor = Difusor()
    gestor = Gestor(cfg, guardian, consumo, crear_modelo(cfg), difusor.emitir, simulacion=sim, velocidad=args.velocidad)
    return cfg, guardian, gestor, difusor


def _asegurar_salida() -> None:
    """Con pythonw.exe no hay consola: sys.stdout y sys.stderr son None y uvicorn falla al mirar isatty. Se redirigen a un registro."""
    if sys.stdout is not None and sys.stderr is not None:
        return
    DATOS_DIR.mkdir(parents=True, exist_ok=True)
    log = open(DATOS_DIR / "apuntes.log", "a", encoding="utf-8", errors="replace", buffering=1)
    if sys.stdout is None:
        sys.stdout = log
    if sys.stderr is None:
        sys.stderr = log


def main(argv=None) -> int:
    _asegurar_salida()
    ap = argparse.ArgumentParser(description="WhisperMeet: transcripción de reuniones con insights.")
    ap.add_argument("--simular", metavar="FICHERO.txt", help="alimenta una transcripción ficticia (sin audio)")
    ap.add_argument("--velocidad", type=float, default=30.0, help="aceleración de la simulación (por defecto 30x)")
    ap.add_argument("--raiz", help="raíz de proyectos (por defecto la configurada)")
    ap.add_argument("--extra", action="append", metavar="NOMBRE=RUTA",
                    help="pruebas: proyecto compartido extra (sustituye a proyectos_extra de la configuración)")
    ap.add_argument("--planes", metavar="CARPETA", help="pruebas: carpeta de planes de sesiones")
    ap.add_argument("--sesiones", metavar="CARPETA", help="pruebas: carpeta local de sesiones de proyectos compartidos")
    ap.add_argument("--checks", metavar="CARPETA", help="pruebas: carpeta local de checks de preparación")
    ap.add_argument("--bandeja", metavar="CARPETA", help="pruebas: carpeta de la Bandeja (por defecto, la real)")
    ap.add_argument("--backlog", metavar="CARPETA", help="pruebas: carpeta del estado local del backlog (por defecto, backlog\\ de la app)")
    ap.add_argument("--consumo", metavar="FICHERO.jsonl", help="pruebas: registro de consumo alternativo (con modelo falso, NUNCA datos/consumo.jsonl: mezclaría llamadas falsas con las reales)")
    ap.add_argument("--cache", metavar="CARPETA", help="pruebas: carpeta de la caché de digests (con modelo falso, NUNCA la real: un digest falso contaminaría una pasada real)")
    ap.add_argument("--config", metavar="FICHERO.json", help="pruebas: configuración alternativa (no toca datos/config.json)")
    ap.add_argument("--puerto", type=int, default=0, help="puerto en 127.0.0.1 (0 = libre)")
    ap.add_argument("--sin-ventana", action="store_true", help="solo servidor; abre la URL en un navegador")
    ap.add_argument("--mostrar-en-captura", action="store_true", help="no excluir la ventana de la captura de pantalla")
    ap.add_argument("--cerrar-tras", type=float, help=argparse.SUPPRESS)  # pruebas: cierra la ventana a los N s
    ap.add_argument("--llamada-prueba", metavar="FICHERO", help=argparse.SUPPRESS)  # pruebas: hay «llamada de Teams» mientras exista este fichero (su texto es el título de la ventana de Teams)
    args = ap.parse_args(argv)

    cfg, guardian, gestor, difusor = construir(args)
    if not args.simular:   # el asesor: índice de fuentes en segundo plano (Knowledge, solo lectura) y capacidad de búsqueda web de `claude -p` (sin tokens)
        gestor.fuentes.arrancar()
        gestor.asesor.sondear_web()
    if args.mostrar_en_captura:
        cfg.actualizar({"excluir_captura": False}, guardar=False, solo_sesion=True)
    token = secrets.token_urlsafe(24)
    puerto = args.puerto or puerto_libre()
    ventana = None

    def al_cambiar_captura(activo: bool):
        if ventana:
            ventana.aplicar(activo)

    aviso = None
    leer_micro, leer_titulo, intervalo = None, titulo_reunion_teams, 5.0
    if args.llamada_prueba:   # pruebas: una llamada simulada, sin leer el registro ni la ventana de Teams
        marca = Path(args.llamada_prueba)
        leer_micro = marca.exists
        leer_titulo = lambda: limpiar_titulo(marca.read_text(encoding="utf-8")) if marca.exists() else ""  # noqa: E731
        intervalo = 0.5
    if not args.sin_ventana:   # el aviso flotante necesita la ventana nativa; sin ella, banner y parpadeo de siempre
        from apuntes.ventana import VentanaAviso
        url_aviso = f"http://{HOST}:{puerto}/aviso?t={token}"
        aviso = AvisoLlamada(gestor, cfg, guardian, lambda: VentanaAviso(cfg["excluir_captura"], al_cerrar=lambda: aviso.ventana_cerrada()),
                             url_aviso, leer_titulo=leer_titulo, al_fallar=llamar_atencion)
    app = crear_app(gestor, difusor, cfg, guardian, token, puerto, al_cambiar_captura, lambda: ventana,
                    al_avisar_llamada=llamar_atencion, vigilar_llamadas_activo=not args.simular or bool(args.llamada_prueba),
                    aviso=aviso, leer_micro=leer_micro, intervalo_llamadas=intervalo)
    servidor = uvicorn.Server(uvicorn.Config(app, host=HOST, port=puerto, log_level="warning", ws="websockets-sansio"))
    hilo = threading.Thread(target=servidor.run, daemon=True, name="uvicorn")
    hilo.start()
    while not servidor.started:
        time.sleep(0.05)
    url = f"http://{HOST}:{puerto}/?t={token}"
    print(f"APUNTES_URL={url}", flush=True)
    if args.simular:
        print(f"Modo simulación: {args.simular} a {args.velocidad:g}x", flush=True)

    try:
        if args.sin_ventana:
            while hilo.is_alive():
                time.sleep(0.5)
        else:
            from apuntes.ventana import Ventana
            ventana = Ventana(url, cfg["excluir_captura"], args.cerrar_tras)
            ventana.abrir()
            if args.cerrar_tras is not None:
                print(f"AFINIDAD_VENTANA={ventana.afinidad}", flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        gestor.apagar()
        servidor.should_exit = True
        hilo.join(timeout=5)
    if args.simular:
        r = gestor.consumo.resumen()
        print("CONSUMO_TOTAL", r, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
