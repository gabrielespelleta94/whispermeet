"""Doble de la API de las olas 3 y 4 (contratos en `demo/api-ola3.md` y `demo/api-ola4.md`) para probar la interfaz REAL en un Edge sin cabeza, sin servidor ni modelo.
Datos ficticios. `instalar(edge)` sustituye `fetch`: cada llamada queda en `window.__llamadas` como `[método, url, cuerpo]` y las que cambian acciones, reglas o modo local
actualizan el estado del doble y emiten el evento de WebSocket que emitiría el servidor."""
from __future__ import annotations

import json
from datetime import date, timedelta


def _dia(d: int) -> str:
    return (date.today() - timedelta(days=d)).isoformat()


PROYECTOS = [
    {"nombre": "Alfa Demo", "compartido": False, "extra": False, "tiene_contexto": True, "tiene_sesiones": True, "ruta": "X:/r/Alfa Demo", "plan": None, "n_sesiones": 3, "ultima_sesion": _dia(3), "n_md": 9},
    {"nombre": "Beta Demo", "compartido": False, "extra": False, "tiene_contexto": False, "tiene_sesiones": False, "ruta": "X:/r/Beta Demo", "plan": None, "n_md": 2},
    {"nombre": "Zeta Antigua", "compartido": False, "extra": False, "tiene_contexto": True, "tiene_sesiones": True, "ruta": "X:/r/Zeta", "plan": None, "n_sesiones": 2, "ultima_sesion": _dia(120), "n_md": 4},
]
RESUMEN = {"Alfa Demo": {"descripcion": "Portal ficticio de reservas de grupos para una cadena hotelera.", "sesiones_por_semana": [0, 0, 1, 0, 2, 0, 1, 1], "pendientes_abiertos": 4, "ultima_sesion_tema": "Seguimiento",
                         "calidad_contexto": {"nivel": 3, "etiqueta": "Contexto completo", "breve": "Completo", "motivos": []}},
           "Beta Demo": {"descripcion": None, "sesiones_por_semana": [0] * 8, "pendientes_abiertos": 0, "calidad_contexto": {"nivel": 1, "etiqueta": "Contexto básico", "breve": "Falta 00. CONTEXTO (IA)", "motivos": ["Falta la carpeta de contexto."]}},
           "Zeta Antigua": {"descripcion": "Proyecto parado ficticio.", "sesiones_por_semana": [0] * 8, "pendientes_abiertos": 0, "calidad_contexto": {"nivel": 3, "etiqueta": "Contexto completo", "breve": "Completo", "motivos": []}}}
PEND = {"total": 2, "avisos": [], "pendientes": [{"id": f"{i:016x}", "texto": f"Pendiente ficticio número {i}", "minuto": "01:00", "responsable": None, "fecha": _dia(3), "tema": "Seguimiento", "sesion_id": "aaaaaaaaaaaaaaaa"} for i in range(2)]}
CTX = {"proyecto": "Alfa Demo", "solo_lectura": False, "truncado": False, "total": 1, "fuera": 0, "limites": {}, "grupos": []}

BRIEF = {"proyecto": "Alfa Demo", "origen": "modelo", "desde_cache": False, "generado": "2026-11-07T10:31:05", "aviso": "",
         "objetivos": ["Cerrar el modelo de datos", "Fijar el calendario del piloto", "Confirmar quién valida el catálogo"],
         "preguntas": ["¿Quién valida el modelo de datos?", "¿Qué hoteles entran en el piloto?"], "datos": ["Listado de licencias vigentes", "Catálogo de hoteles en CSV"],
         "ultima_sesion": {"id": "aaaaaaaaaaaaaaaa", "fecha": "2026-11-04", "tema": "Seguimiento"}, "siguiente_sesion": None,
         "pendientes": [{"id": "bbbbbbbbbbbbbbbb", "texto": "Enviar el fichero de tarifas", "responsable": "Ana", "plazo": "viernes", "veces": 2, "fecha": "2026-11-04", "tema": "Seguimiento"}],
         "recordatorios": [{"id": "r1a2b3c4d5e", "texto": "Retomar la cuestión de licencias", "fecha": "2026-11-04", "tema": "Seguimiento"}]}
SEGUIMIENTO = {"proyecto": "Alfa Demo", "abiertos": 2, "hechos": 1, "autonomia": "hacer", "umbral": 0.6, "avisos": [], "pendientes": [
    {"id": "1111111111111111", "texto": "Enviar la estimación de tarifas del piloto", "responsable": "Ana", "plazo": "viernes", "minuto": "04:20", "fecha": "2026-10-20", "tema": "Arranque", "sesion_id": "aaaaaaaaaaaaaaaa",
     "veces": 1, "estado": "hecho", "auto": True, "cita": {"sesion_id": "aaaaaaaaaaaaaaaa", "sesion": "sesión 2026-10-27 · Seguimiento", "fecha": "2026-10-27", "tema": "Seguimiento",
                                                        "texto": "Se envió la estimación de tarifas del piloto al cliente y quedó validada.", "coincidencia": 0.75},
     "cierre_propuesto": None, "aceptado": False, "origen": "sesiones"},
    {"id": "2222222222222222", "texto": "Revisar el catálogo de habitaciones con Revenue", "responsable": None, "plazo": "", "minuto": "09:10", "fecha": "2026-10-27", "tema": "Seguimiento", "sesion_id": "aaaaaaaaaaaaaaaa",
     "veces": 2, "estado": "abierto", "auto": False, "cita": None, "cierre_propuesto": None, "aceptado": False, "origen": "sesiones"},
    {"id": "3333333333333333", "texto": "Confirmar fecha del piloto con el cliente", "responsable": "Luis", "plazo": "lunes", "minuto": "11:00", "fecha": "2026-11-04", "tema": "Seguimiento", "sesion_id": "aaaaaaaaaaaaaaaa",
     "veces": 1, "estado": "abierto", "auto": False, "cita": None, "cierre_propuesto": None, "aceptado": True, "origen": "acciones"}]}
METRICAS_PROY = {"proyecto": "Alfa Demo", "sesiones": 2, "duracion_total_s": 3600.0, "objetivos": {"total": 7, "cerrados": 5, "ratio_cerrados": 0.71, "minutos_medio_hasta_cierre": 3.8, "con_tiempo_de_cierre": 5},
                 "avisos": {"emitidos": 12, "aceptados": 5, "descartados": 3, "marcados_mal": 2, "tasa_aceptacion": 0.62}, "tokens": {"entrada": 3000, "salida": 300, "total": 3300, "por_sesion": 1650, "por_objetivo_cerrado": 660},
                 "serie": [{"sesion": "s1", "fecha": "2026-11-01", "tema": "Seguimiento", "objetivos": 4, "cerrados": 2, "ratio_cerrados": 0.5, "minutos_medio_hasta_cierre": 5.0, "tokens": 1100, "aceptados": 3, "descartados": 1, "modo_local": False},
                           {"sesion": "s2", "fecha": "2026-11-04", "tema": "Diseño", "objetivos": 3, "cerrados": 3, "ratio_cerrados": 1.0, "minutos_medio_hasta_cierre": 2.6, "tokens": 2200, "aceptados": 2, "descartados": 2, "modo_local": False}]}
PLANTILLAS = {"plantillas": [
    {"id": "descubrimiento", "nombre": "Descubrimiento", "version": 1, "origen": "base", "descripcion": "Primera conversación con un cliente: entender qué necesita y si hay encaje.",
     "objetivos": ["Entender la necesidad y el problema", "Conocer el presupuesto disponible", "Acordar el plazo y los hitos", "Identificar quién decide"],
     "perfiles": {"coordinador": {"peso": 1, "foco": ""}, "funcional": {"peso": 2, "foco": "la necesidad"}, "constructor": {"peso": 0, "foco": ""}, "revisor": {"peso": 1, "foco": ""}, "estratega": {"peso": 2, "foco": "presupuesto y decisor"}},
     "ritmo": {"cadencia": "equipo", "duracion_min": 45, "ajustes": {}}},
    {"id": "diseno-funcional", "nombre": "Diseño funcional", "version": 1, "origen": "base", "descripcion": "Definir reglas, datos y flujos.", "objetivos": ["Cerrar las reglas de negocio", "Validar el modelo de datos", "Listar lo que queda fuera"],
     "perfiles": {"coordinador": {"peso": 1, "foco": ""}, "funcional": {"peso": 2, "foco": ""}, "constructor": {"peso": 2, "foco": ""}, "revisor": {"peso": 1, "foco": ""}, "estratega": {"peso": 0, "foco": ""}}, "ritmo": {"cadencia": "equipo", "duracion_min": 60, "ajustes": {}}},
    {"id": "seguimiento", "nombre": "Seguimiento", "version": 1, "origen": "base", "descripcion": "Revisar el estado y desbloquear.", "objetivos": ["Revisar los pendientes", "Detectar riesgos", "Acordar los próximos pasos"],
     "perfiles": {"coordinador": {"peso": 2, "foco": ""}, "funcional": {"peso": 1, "foco": ""}, "constructor": {"peso": 1, "foco": ""}, "revisor": {"peso": 1, "foco": ""}, "estratega": {"peso": 1, "foco": ""}}, "ritmo": {"cadencia": "equipo", "duracion_min": 30, "ajustes": {}}},
    {"id": "comite", "nombre": "Comité", "version": 1, "origen": "base", "descripcion": "Decisiones con varias personas.", "objetivos": ["Presentar el estado", "Tomar las decisiones pendientes"],
     "perfiles": {"coordinador": {"peso": 2, "foco": ""}, "funcional": {"peso": 1, "foco": ""}, "constructor": {"peso": 0, "foco": ""}, "revisor": {"peso": 2, "foco": ""}, "estratega": {"peso": 1, "foco": ""}}, "ritmo": {"cadencia": "equipo", "duracion_min": 45, "ajustes": {}}}]}
CARTERA = {"hoy": "2026-11-05", "ventana_dias": 30, "pendiente_antiguo_dias": 14, "resumen": {"proyectos": 3, "critico": 1, "atencion": 1, "bien": 1}, "avisos": [], "proyectos": [
    {"proyecto": "Alfa Demo", "nivel": "critico", "atencion": 8, "motivos": ["1 riesgo(s) repetido(s) en varias sesiones", "1 pendiente(s) abierto(s) de hace más de 14 días", "solo se cierra el 33 % de los objetivos"],
     "sesiones": {"total": 3, "recientes": 2, "ventana_dias": 30, "ultima_fecha": "2026-11-03", "dias_desde_ultima": 2, "ultima_tema": "Seguimiento"},
     "pendientes": {"abiertos": 2, "antiguos": 1, "mas_antiguos": [{"texto": "Cerrar el catálogo de habitaciones antiguo.", "fecha": "2026-09-28", "dias": 38, "sesion_id": "a1b2c3d4e5f60718"}]},
     "objetivos": {"cerrados": 2, "total": 6, "ratio_cerrados": 0.33, "sesiones_con_objetivos": 2}, "riesgos_repetidos": [{"texto": "El proveedor de pagos puede retrasar el piloto.", "sesiones": 2, "ultima_fecha": "2026-11-03"}]},
    {"proyecto": "Beta Demo", "nivel": "atencion", "atencion": 4, "motivos": ["2 pendiente(s) abierto(s) de hace más de 14 días"], "sesiones": {"total": 2, "recientes": 1, "ventana_dias": 30, "ultima_fecha": "2026-10-20", "dias_desde_ultima": 16, "ultima_tema": "Arranque"},
     "pendientes": {"abiertos": 3, "antiguos": 2, "mas_antiguos": []}, "objetivos": {"cerrados": 3, "total": 4, "ratio_cerrados": 0.75, "sesiones_con_objetivos": 1}, "riesgos_repetidos": []},
    {"proyecto": "Zeta Antigua", "nivel": "bien", "atencion": 1, "motivos": [], "sesiones": {"total": 5, "recientes": 3, "ventana_dias": 30, "ultima_fecha": "2026-11-04", "dias_desde_ultima": 1, "ultima_tema": "Comité"},
     "pendientes": {"abiertos": 0, "antiguos": 0, "mas_antiguos": []}, "objetivos": {"cerrados": 5, "total": 5, "ratio_cerrados": 1.0, "sesiones_con_objetivos": 3}, "riesgos_repetidos": []}]}

ACCIONES = [
    {"id": "a1", "tipo": "pendiente", "origen": "Capitán", "texto": "Enviar el fichero de tarifas", "cita": {"texto": "yo las envío el viernes", "minuto": "04:12"}, "estado": "propuesta", "datos": {"dueno": "Ana", "fecha": "viernes"},
     "creada": "2026-11-07T10:31:05", "prioridad": "normal", "modo": "proponer", "auto": False, "minuto": "04:12"},
    {"id": "a2", "tipo": "pregunta", "origen": "Capitán", "texto": "¿Quién valida el catálogo de hoteles antes del piloto?", "cita": None, "estado": "propuesta", "datos": {"objetivo": 3, "objetivo_texto": "Confirmar quién valida el catálogo"},
     "creada": "2026-11-07T10:32:05", "prioridad": "normal", "modo": "avisar", "auto": False, "minuto": "05:10"},
    {"id": "a3", "tipo": "cambio_contexto", "origen": "Arquitecto", "texto": "Añadir a 02-alcance.md que SAP queda fuera de la fase 1", "cita": {"texto": "eso estaba fuera de alcance, lo acordamos en el kick off", "minuto": "02:45"}, "estado": "aceptada",
     "datos": {"cambio_id": "c1", "fichero": "02-alcance.md", "tipo_cambio": "anadir"}, "creada": "2026-11-07T10:33:05", "prioridad": "normal", "modo": "hacer", "auto": True, "minuto": "02:45"}]
AUTONOMIA = {"autonomia": {"pregunta": "proponer", "pendiente": "proponer", "cambio_contexto": "proponer", "correo": "proponer", "recordatorio": "proponer", "consolidar_pendientes": "hacer"},
             "defecto": {}, "tipos": ["pregunta", "pendiente", "cambio_contexto", "correo", "recordatorio", "consolidar_pendientes"], "tipos_accion": ["pregunta", "pendiente", "cambio_contexto", "correo", "recordatorio"],
             "niveles": ["avisar", "proponer", "hacer"], "hacer_admitido": ["cambio_contexto", "consolidar_pendientes"]}
REGLAS = {"reglas": [{"id": "9f2c1a7b3d0e", "tipo": "senal:fecha", "clave": "para el viernes que viene", "ejemplo": "señal: fecha · «para el viernes que viene»", "creada": "2026-11-07T10:31:02", "sesion": "3b78ba54", "veces": 4}], "total": 1}
ENVIO = {"tipo": "envio", "ts": "2026-11-07T10:32:10", "sesion": "3b78ba54", "agente": "Analista", "tarea": "periodico", "modelo": "haiku", "chars": 18342, "entrada": 4210, "salida": 380, "ms": 5200, "ok": True, "bloqueado": False,
         "extracto": "Resumen hasta ahora: Se habló del piloto y del calendario de disponibilidad…"}
ENVIOS = {"sesion": None, "envios": [ENVIO, dict(ENVIO, ts="2026-11-07T10:38:10", agente="Coordinador", tarea="equipo_coordinador", entrada=2800, salida=410, chars=9000)],
          "resumen": {"llamadas": 2, "enviadas": 2, "bloqueadas": 0, "errores": 0, "chars": 27342, "entrada": 7010, "salida": 790, "por_agente": {}},
          "sesiones": [{"sesion": "3b78ba54", "primera": "2026-11-07T10:30:00", "ultima": "2026-11-07T10:38:10", "llamadas": 2, "enviadas": 2, "bloqueadas": 0, "errores": 0, "chars": 27342, "entrada": 7010, "salida": 790, "por_agente": {}}]}
METRICAS = {"sesion": "3b78ba54", "proyecto": "Alfa Demo", "tema": "Seguimiento", "fecha": "2026-11-07", "duracion_s": 1810.4, "duracion": "30:10", "plan": None, "modo_local": False,
            "objetivos": [], "objetivos_resumen": {"total": 3, "cerrados": 2, "parciales": 0, "sin_tratar": 1, "ratio_cerrados": 0.67, "minutos_medio_hasta_cierre": 8.5, "primer_cierre_min": "10:00"},
            "avisos": {"emitidos": 13, "aceptados": 4, "descartados": 5, "marcados_mal": 2, "sin_valorar": 4, "tasa_aceptacion": 0.44, "por_tipo": {}},
            "tokens": {"entrada": 31200, "salida": 3100, "total": 34300, "llamadas": 9, "por_tarea": {}}, "envios": None}

STUB = r"""(() => {
  const D = __DATOS__;
  window.__llamadas = []; window.__iniciar = null;
  const CFG = { raiz_proyectos: 'C:/ejemplo', whisper_modelo: 'small', min_palabras_analisis: 40, esfuerzo: '', excluir_captura: true, detectar_llamadas: true, filtrar_eco: true, cadencia_defecto: 'equipo',
    adaptativo_comprobar_s: 30, equipo_puntuacion_min: 3, equipo_enfriamiento_global_s: 240, equipo_enfriamiento_perfil_s: 360, equipo_rotacion_s: 300, equipo_palabras_min: 120, equipo_objetivo_sin_tratar_min: 20, presupuesto_tokens_hora: 60000,
    modelos: { digest: 'haiku', periodico: 'haiku', contradicciones_confirmar: 'sonnet', final: 'sonnet', consulta: 'haiku', pulido: 'opus' }, proyectos_extra: [], modo_local: false, autonomia: D.autonomia.autonomia };
  const r = (d, ok = true, status = 200) => ({ ok, status, json: async () => d });
  const emitirAcc = () => window.__emitir && window.__emitir({ tipo: 'acciones', acciones: D.acciones, nuevas: [], autonomia: D.autonomia.autonomia });
  window.fetch = async (u, o) => {
    const m = (o && o.method) || 'GET'; const cuerpo = o && o.body ? JSON.parse(o.body) : null; window.__llamadas.push([m, String(u), cuerpo]);
    u = String(u);
    let x;
    if (/api\/proyectos\?/.test(u)) return r({ raiz: 'X:/r', proyectos: D.proyectos });
    if (/api\/proyectos\/resumen/.test(u)) return r({ resumen: D.resumen, parcial: false });
    if (/\/brief/.test(u)) { if (D.brief_retardo) await new Promise((f) => setTimeout(f, D.brief_retardo)); return D.brief_error ? r({ detail: 'sin modelo' }, false, 500) : r(D.brief); }
    if (/\/seguimiento\/[0-9a-f]{16}\/(hecho|reabrir)$/.test(u)) { const id = u.match(/seguimiento\/([0-9a-f]{16})/)[1]; const p = D.seguimiento.pendientes.find((q) => q.id === id); const hecho = /hecho$/.test(u);
      p.estado = hecho ? 'hecho' : 'abierto'; p.auto = false; if (hecho) p.cita = p.cita || null; else p.cita = null; return r(p); }
    if (/\/seguimiento/.test(u)) return r(D.seguimiento);
    if (/\/pendientes$/.test(u)) return r(D.pend);
    if (/\/contexto$/.test(u)) return r(D.ctx);
    if (/sesiones-recientes/.test(u)) return r({ sesiones: [{ id: 'aaaaaaaaaaaaaaaa', fecha: '2026-11-04', tema: 'Seguimiento', inicio: '10:00' }], avisos: [] });
    if (/api\/proyectos\/[^/]+\/metricas/.test(u)) return r(D.metricas_proy);
    if (/api\/plantillas/.test(u)) return r(D.plantillas);
    if (/api\/cartera/.test(u)) return r(D.cartera);
    if (/api\/acciones\/(a\d+)\/(aceptar|descartar|reabrir|hecha)$/.test(u)) { x = u.match(/acciones\/(a\d+)\/(\w+)/); const a = D.acciones.find((q) => q.id === x[1]);
      a.estado = { aceptar: 'aceptada', descartar: 'descartada', reabrir: 'propuesta', hecha: 'hecha' }[x[2]]; if (x[2] === 'reabrir') a.auto = false; emitirAcc(); return r(a); }
    if (/api\/acciones\/(a\d+)$/.test(u) && m === 'PUT') { const a = D.acciones.find((q) => q.id === u.match(/acciones\/(a\d+)/)[1]); if (cuerpo.texto) { a.texto = cuerpo.texto; a.editada = true; } emitirAcc(); return r(a); }
    if (/api\/acciones/.test(u)) return r({ acciones: D.acciones, autonomia: D.autonomia.autonomia, en_reunion: true });
    if (/api\/autonomia/.test(u)) { if (m === 'PUT') { Object.assign(D.autonomia.autonomia, cuerpo.autonomia); } return r(D.autonomia); }
    if (/api\/reglas-silencio\/[0-9a-f]+$/.test(u) && m === 'DELETE') { const id = u.split('/').pop(); D.reglas.reglas = D.reglas.reglas.filter((q) => q.id !== id); D.reglas.total = D.reglas.reglas.length; return r({ ok: true, id }); }
    if (/api\/reglas-silencio/.test(u)) return r(D.reglas);
    if (/api\/avisos\/[^/]+\/mal$/.test(u)) { const regla = { id: '9f2c1a7b3d0f', tipo: 'senal:dato', clave: 'dato', ejemplo: 'señal: dato', creada: '2026-11-07T10:40:00', sesion: 's', veces: 0, nueva: true }; D.reglas.reglas.push(regla); return r({ id: u.split('/')[3], origen: 'monitor', regla }); }
    if (/segmento\/\d+\/corregir$/.test(u)) { const id = Number(u.match(/segmento\/(\d+)/)[1]); return r({ segmento: { id, texto: cuerpo.texto, corregido: true }, sustituciones: [['nordia', 'Nórdia']], propagado: { tarjetas: 1, resumen: 2, definiciones: 0, feed: 1 },
      glosario: cuerpo.glosario ? [{ termino: 'Nórdia', ambito: cuerpo.glosario, proyecto: null, nuevo: true, total: 1 }] : [] }); }
    if (/api\/glosario/.test(u)) return r({ termino: cuerpo.termino, ambito: cuerpo.proyecto ? 'proyecto' : 'global', proyecto: cuerpo.proyecto || null, nuevo: true, total: 1 });
    if (/api\/envios\/resumen/.test(u)) return r({ sesiones: D.envios.sesiones });
    if (/api\/envios/.test(u)) return r(D.envios);
    if (/api\/modo-local/.test(u)) { if (m === 'POST') { D.modo_local.activo = !!cuerpo.activo; D.modo_local.config = !!cuerpo.activo; } return r(D.modo_local); }
    if (/api\/revision\/agentes/.test(u)) return r({ ok: true });
    if (/api\/sesion\/iniciar/.test(u)) { window.__iniciar = cuerpo; return r({ ok: true }); }
    if (/api\/sesion\/metricas/.test(u)) return r(D.metricas);
    if (/api\/correo\/outlook/.test(u)) return r({ ok: true });
    if (/dispositivos/.test(u)) return r({ entradas: [{ indice: 1, nombre: 'Micrófono de ejemplo' }], salidas: [{ indice: 2, nombre: 'Altavoces de ejemplo' }], mic_defecto: 1, sistema_defecto: 2 });
    if (/api\/config/.test(u)) { if (m === 'PUT' && cuerpo) Object.assign(CFG, cuerpo, cuerpo.modelos ? { modelos: Object.assign({}, CFG.modelos, cuerpo.modelos) } : {}); return r({ config: CFG }); }
    if (/api\/info/.test(u)) return r({ simulacion: false, config: CFG });
    if (/ventana/.test(u)) return r({ nativa: false });
    return r({});
  };
})()"""


def datos() -> dict:
    return {"proyectos": PROYECTOS, "resumen": RESUMEN, "pend": PEND, "ctx": CTX, "brief": BRIEF, "seguimiento": SEGUIMIENTO, "metricas_proy": METRICAS_PROY, "plantillas": PLANTILLAS,
            "cartera": CARTERA, "acciones": json.loads(json.dumps(ACCIONES)), "autonomia": json.loads(json.dumps(AUTONOMIA)), "reglas": json.loads(json.dumps(REGLAS)), "envios": ENVIOS,
            "metricas": METRICAS, "brief_retardo": 0, "modo_local": {"activo": False, "sesion": None, "config": False, "agentes_cierre_confirmados": False}, "brief_error": False}


def instalar(edge, **cambios) -> None:
    d = datos()
    d.update(cambios)
    edge.js(STUB.replace("__DATOS__", json.dumps(d)) + "; 1")
