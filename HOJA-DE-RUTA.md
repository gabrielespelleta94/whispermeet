# Hoja de ruta de WhisperMeet

Estado a 10 de noviembre de 2026. Recoge el análisis de punta a punta de la herramienta y el plan por olas para llevarla de «apuntador de reuniones» a «puesto de mando del proyecto»: que sepa qué documentación tiene cada proyecto, cómo es la solución, su modelo de datos, sus usuarios y su plan de sesiones, y que tenga agentes que ayuden también fuera de la reunión.

## Cómo está hoy

| Área | Qué hay | Qué falta |
|---|---|---|
| Reunión en directo | Transcripción local con Whisper, tarjetas, objetivos, checks, asesor, equipo de agentes y eco aplazado en origen. | Validar el eco con sonido real de sala. |
| Documentos del proyecto | Lee `.md`, `.txt`, `.docx`, `.pptx` y `.pdf` como contexto. Mapa de documentos por tipo y aviso de los tipos que faltan (ola A); tipo corregible a mano, resumen de una línea de los documentos clave y tipo propuesto para lo ambiguo (ola B). | Leer `.xlsx`; que el mapa entre en la preparación sugerida y en el resumen del proyecto. |
| Solución tal como está y modelo de datos | La plantilla `03-arquitectura-y-datos`, que se rellena a mano, y desde la ola B el Archivero: cobertura por faceta con el documento que lo dice y lo que falta. | Que proponga los huecos por el flujo de «aceptar cambios»; rellenar la plantilla a partir de lo que encuentra. |
| Usuarios y roles | Desde la ola B, el Archivero extrae los perfiles y roles de la solución que digan los documentos (nunca personas). Las secciones de contactos se excluyen a propósito del contexto de la IA. | Interlocutores del proyecto, sin enviar datos personales al modelo. |
| Planificación de sesiones | Plan de varias sesiones con Gantt, objetivos y checks. Desde la ola C se crea y se edita en la ficha del proyecto (sesiones, fecha, hora, objetivos, checks, dependencias, fichero prioritario), se guarda sin perder el Gantt ni lo que el editor no conoce, y «Proponer plan con Claude» da un borrador a partir del arranque, el alcance y la planificación. | Editar el Gantt y la ficha del plan desde la app (se conservan, pero hoy solo se cambian en el JSON); caché de la propuesta; fechas de hitos. |
| Agentes | Muchos dentro de la reunión. Fuera de ella, la preparación sugerida, el contexto de la reunión, el Archivero y el Planificador («Proponer plan»), los dos a mano desde la ficha. | Agente de proyecto: redactor de entregables. |
| Empaquetado | Desde la ola D, `instalar.bat` (un solo script, idempotente, con `--comprobar`): entorno, dependencias con versión fijada (`requirements.txt` para la app y `requirements-dev.txt` para pruebas), configuración inicial, carpetas locales, `claude`, modelo de Whisper y acceso directo. Panel «Antes de la primera reunión» (inicio y Ajustes) con la comprobación de requisitos. Carpeta de Knowledge, vocabulario de transcripción y ancho de búsqueda de Whisper editables en Ajustes. `MANUAL.md` para quien usa la app. | Un ejecutable sin Python previo; fijar también las dependencias indirectas (fichero de bloqueo); comprobar desde la app que la sesión de `claude` está iniciada (hoy solo se localiza el programa); probar el instalador en una máquina limpia de verdad. |
| Datos internos | Todo en ficheros (JSON, JSONL y Markdown) a través de `Guardian`, con escritura atómica. No hay base de datos. | Versión de esquema y migraciones, identificadores estables y copia de seguridad. |
| Entregables | Acta y resumen en Markdown; borrador de correo. | Exportar a Word o PDF con plantilla. |

### Modelo de datos interno, en una línea por entidad

- **Proyecto**: una carpeta bajo la raíz de proyectos o una entrada de `proyectos_extra`. No hay ficha persistida: se deduce de la carpeta.
- **Sesión**: identificador corto, proyecto (o Bandeja), tema, fecha, segmentos, tarjetas, objetivos, checks, acciones y cobertura. Se guarda como Markdown en la carpeta `02. Sesiones (transcripciones)` del proyecto.
- **Plan de sesiones**: un JSON por plan en la carpeta `planes` (local, fuera de git). La app lo lee y, desde la ola C, lo escribe solo desde el editor de la ficha (`Guardian.escribir_plan`: atómico, con copia `.bak`). Un plan que ya existe se localiza por el proyecto que declara dentro; uno nuevo se guarda como `plan-<hash>.json`.
- **Pendientes, decisiones y riesgos**: se extraen de las sesiones; su identificador se calcula con el texto, así que cambia si el texto cambia.
- **Seguimiento, métricas, glosario y reglas**: ficheros propios en la carpeta de datos de la app.
- **Usuarios**: no hay cuentas ni roles. La app es de un solo usuario, escucha solo en la máquina local y protege cada arranque con un token.

## Olas

### Ola A — Mapa de documentos del proyecto (hecha)

La ficha de cada proyecto muestra qué documentación hay, por tipo, cuál es el último documento de cada tipo y qué tipos no aparecen.

- Recorre la carpeta del proyecto mirando solo nombre, tamaño y fecha: no abre ningún fichero, no descarga los que están solo en la nube y no gasta tokens.
- Clasificación determinista y explicable (nombre del fichero, después carpeta, después extensión); cada documento dice por qué cayó en su tipo.
- Tipos: arranque (kick-off), oferta y alcance, funcional, técnico, modelo de datos, usuarios y roles, planificación, seguimiento y actas, pruebas y formación, contexto para la IA y sin clasificar.
- Piezas: `apuntes/inventario.py`, `Guardian.ficheros_del_proyecto`, `GET /api/proyectos/{nombre}/documentos` y el bloque «Documentos del proyecto» de la ficha.

### Ola B — Agente Archivero (hecha)

Un agente que se lanza a mano desde la ficha y trabaja sobre el mapa de la ola A. Hecho: `apuntes/archivero.py`, `apuntes/api_archivero.py`, el bloque «Agente Archivero» de la ficha y el tipo corregible a mano (`PUT .../documentos/{id}/tipo`, `tipos_documento\`). Una sola llamada a `claude -p` (sonnet), con una selección acotada y determinista de documentos (nunca los que están solo en la nube), sin datos personales ni secretos en lo que sale, cacheada y con respaldo local sin licencia. «Guardar en el contexto del proyecto» enseña la vista previa y escribe `NN-mapa-de-documentacion.md` solo tras confirmar.

Lo que quedó fuera de esta ola:
- Proponer los huecos para `07-fuentes-y-huecos` por el flujo de «aceptar cambios» de la reunión: el Archivero guarda su propio `NN-mapa-de-documentacion.md` (con lo que falta en cada faceta) y no toca las plantillas del kit.
- Que el mapa entre en la preparación sugerida (brief) y en el resumen del proyecto: hoy llega a la reunión solo por el contexto del proyecto, y solo si el usuario guarda el resultado.
- Leer `.xlsx` (y otros formatos sin lector): salen en «No se va a leer» con su motivo. El `.pdf` solo se lee si hay una librería de PDF instalada.
- Usuarios y roles solo cubre perfiles y roles de la solución, no los interlocutores del proyecto (las secciones de contactos siguen fuera del contexto de la IA).

El plan original, como referencia:

- Clasifica lo que las reglas dejan en «sin clasificar» y permite corregir un tipo a mano.
- Resume en una línea cada documento clave.
- Cobertura por faceta, con la evidencia de dónde sale: solución tal como está, modelo de datos, usuarios y roles, alcance y plan.
- Propone los huecos para `07-fuentes-y-huecos` por el flujo de «aceptar cambios» que ya existe; nunca escribe sin que se acepte.
- El mapa de documentos entra en la preparación sugerida y en el resumen del proyecto.
- Hecho cuando: en un proyecto de prueba con documentos ficticios, el agente da la cobertura de las cinco facetas con su fuente y la propuesta de huecos se puede aceptar o rechazar.

### Ola C — Planificación de sesiones en la app (hecha)

Se puede crear un plan desde cero sin tocar un JSON y una reunión nueva queda enlazada a su sesión del plan.

- Editor del plan en la ficha del proyecto: crear el plan, y añadir, editar, reordenar (con botones, también con el teclado) y quitar sesiones, con su nombre, fecha, hora, objetivos, checks, dependencias y fichero prioritario. «Cambios sin guardar» visible, Guardar y Descartar, aviso al salir de la ficha, errores de validación junto a su campo y quitar con confirmación en línea.
- Guardado por `Guardian.escribir_plan`: atómico, confinado a `planes\`, con copia `.bak` del anterior; conserva `ficha`, `gantt` y cualquier clave que el editor no conozca (también dentro de cada sesión). Control de concurrencia: el `PUT` lleva la versión (hash del fichero) y, si el fichero cambió fuera de la app, responde 409 y no escribe. Los ids de sesión los pone la app, son estables y no se reutilizan.
- «Proponer plan con Claude»: una llamada a `claude -p` (sonnet), a mano, sobre arranque, oferta y alcance, planificación y funcional (misma selección y lectura segura que el Archivero). Devuelve un borrador que entra en el editor; nada se guarda hasta pulsar «Guardar»; con un plan existente solo añade sesiones. Las fechas solo se proponen si están escritas en los documentos.
- Piezas: `apuntes/plan_editor.py`, `apuntes/plan_propuesto.py`, `apuntes/api_plan.py`, `web/plan-editor.js`, `GET/PUT /api/proyectos/{nombre}/plan`, `GET/POST .../plan/proponer`, `pruebas/probar_plan_propuesto.py`.

Lo que quedó fuera de esta ola:
- Editar el Gantt (semanas, fases, hitos) y la ficha del plan desde la app: se conservan al guardar, pero se siguen cambiando en el JSON.
- Caché de la propuesta de «Proponer plan»: cada propuesta es una llamada nueva (gasta tokens), aunque nada haya cambiado.
- Enseñar y editar las sesiones del fichero que la app no puede leer (sin id, id repetido o no válido, sin nombre, más de 20): el editor avisa de cuántas hay (también al crear un plan) y las conserva tal cual al final del fichero al guardar, pero no se ven ni se editan aquí.
- Un `.json` ilegible en la carpeta de planes: el editor solo avisa (con su nombre) cuando el proyecto no tiene plan; no sabe de qué proyecto es, así que no impide crear uno nuevo al lado.
- Los límites de «Proponer plan»: las fechas solo se comprueban contra el conjunto de los documentos enviados (que la fecha esté escrita en alguno, no que sea la de esa sesión) y los nombres de personas no se filtran al validar la salida; dependen de la regla del prompt y de haber quitado antes las secciones de contactos.
- Marcar una sesión como celebrada o enlazar a mano una reunión pasada con su sesión; la reunión se enlaza al empezarla, como antes.
- Que el agente rellene participantes: es un campo que el editor conserva pero no edita.

El plan original, como referencia:

- Editor del plan: crear, mover y cerrar sesiones, con sus objetivos y checks, guardado a través de `Guardian`.
- «Proponer plan»: un agente lee los documentos de arranque y alcance y propone las sesiones; se revisa antes de guardar.
- Hecho cuando: se puede crear un plan desde cero sin tocar un JSON y una reunión nueva queda enlazada a su sesión del plan.

### Ola D — Empaquetado (hecha)

- Script de instalación: entorno, dependencias, acceso directo y comprobaciones.
- Comprobación de requisitos al primer arranque: Python, `claude` con sesión iniciada, modelo de Whisper, micrófono y carpetas.
- Dependencias separadas (app y desarrollo) y con versión fijada.
- Ajustes que hoy solo están en el fichero: carpeta de Knowledge, vocabulario de transcripción y ancho de búsqueda de Whisper.
- README al día y manual de usuario.
- Hecho cuando: una máquina limpia llega a la primera reunión con un solo script y la app explica qué falta si falta algo.

Hecho: `instalar.bat` + `instalar.py` (solo biblioteca estándar; opciones `--comprobar`, `--dev`, `--si`, `--sin-modelo`, `--sin-acceso-directo`; nunca borra ni pisa: `datos\config.json` solo se crea si falta y las carpetas locales solo se crean), `requirements.txt` (solo la app, versiones fijadas con Python 3.12.10) y `requirements-dev.txt`, `apuntes/requisitos.py` y `GET /api/requisitos` (Python, `claude`, modelo de Whisper, audio, carpetas; sin tokens, sin abrir el micrófono, sin descargar ni escribir), el panel «Antes de la primera reunión» en el inicio y en Ajustes, los tres ajustes nuevos con validación en el servidor y error junto al campo (`knowledge` por `Guardian.validar_knowledge`, `vocabulario_transcripcion`, `whisper_beam`), la sección «Instalación» del `README.md` y `MANUAL.md`.

Lo que quedó fuera de esta ola:
- Probarlo en una máquina limpia de verdad: el instalador se probó en una carpeta temporal con el Python del sistema y la caché de pip del equipo, con dobles para los pasos que descargan o escriben fuera del repositorio (modelo, acceso directo). Con la red fría la primera instalación tarda más (varios cientos de MB).
- Python 3.12 como mínimo no es una exigencia del código (el análisis estático da 3.9) sino de las versiones fijadas (`numpy` 2.5 y `av` 19); relajar las versiones permitiría Python más antiguo.
- Las dependencias indirectas no están fijadas (no hay fichero de bloqueo): dos instalaciones en fechas distintas pueden traer versiones distintas de las transitivas. `pypdf` (lectura de `.pdf`) sigue siendo opcional y no se instala.
- La sesión de `claude`: el instalador y el panel solo localizan el programa (y el instalador lanza `claude --version`); saber si hay sesión iniciada exigiría una llamada que gasta tokens, así que se deja como paso manual.
- Permisos de escritura de las carpetas locales: se miran con `os.access`, que en Windows solo ve los atributos de solo lectura, no las listas de acceso; un bloqueo por permisos finos solo se vería al escribir.
- Si ya existe un acceso directo `WhisperMeet` que apunta a otra carpeta, el instalador no lo recrea ni lo avisa.
- El panel no sale en Modo reunión ni durante la reunión (con una reunión en curso, el audio ni se enumera); el vocabulario se edita como texto con un término por línea, no como lista de etiquetas.
- Cambiar la carpeta de Knowledge reindexa las fuentes en segundo plano, pero un cambio hecho mientras una reunión graba se rechaza y hay que repetirlo al terminar; lo mismo vale para la carpeta de proyectos y el modelo de transcripción, y el resto de Ajustes sí se guarda durante la reunión.

### Ola E — Entregables

- Exportar acta, resumen y estado del proyecto a Word o PDF con plantilla.
- Hojas de cálculo (`.xlsx`) como fuente de contexto.

### Ola F — Datos internos

- Versión de esquema en cada fichero de datos y migraciones al arrancar.
- Identificadores estables para pendientes, decisiones y riesgos.
- Copia de seguridad y exportación de los datos de la app.
- Se mantiene el almacenamiento en ficheros: es lo que permite que el proyecto viaje con su carpeta. Una base de datos solo se justificaría con varios usuarios.

## Transcripción: qué modelo de Whisper usar

Medido en un portátil sin GPU, con 6 hilos y voz sintética en español con jerga de proyecto. Una velocidad por encima de 1× significa que transcribe más rápido de lo que se habla; con dos canales (micrófono y reunión) hace falta margen.

| Modelo | Errores, audio limpio | Errores, llamada | Jerga reconocida (de 12), limpio / llamada | Velocidad, limpio / llamada | Memoria |
|---|---|---|---|---|---|
| `small` (por defecto) | 2,7 % | 10,0 % | 8 / 6 | 2,85× / 3,54× | 1,0 GB |
| `small` con la jerga en el glosario | 1,9 % | 9,6 % | 10 / 7 | 3,16× / 3,63× | 1,0 GB |
| `large-v3-turbo` | 1,2 % | 10,0 % | 11 / 11 | 1,84× / 1,58× | 1,9 GB |
| `medium` | 1,9 % | 8,5 % | 10 / 10 | 0,35× / 1,01× | 2,2 GB |

- `small` sigue siendo el modelo por defecto: es el único con margen de velocidad de sobra con la máquina cargada. `large-v3-turbo` se midió con el equipo más libre que los otros dos, así que su velocidad real en reunión es menor que la de la tabla.
- Lo más rentable es añadir la jerga del proyecto al glosario de la app: con `small` baja los errores en audio limpio del 2,7 % al 1,9 % y sube la jerga reconocida de 8 a 10 términos, sin perder velocidad.
- `large-v3-turbo` es el que mejor reconoce la jerga, sobre todo en llamada, y queda como opción en Ajustes para equipos libres. Si aparece retraso, se vuelve a `small`.
- `medium` queda descartado en este tipo de equipo: no sigue el ritmo de la conversación.
- Con el micrófono lejos de quien habla fallan todos (entre el 27 % y más del 100 % de errores): ahí manda el micrófono, no el modelo.

## Principios que no cambian

- Todo en local. La IA se usa solo con `claude -p`.
- El audio nunca se guarda en disco.
- El contexto del proyecto solo se modifica después de que el usuario acepte el cambio.
- Todo acceso a disco pasa por `Guardian`; los ficheros con pinta de secreto no se leen ni se listan.
- Los datos personales (contactos) no se envían al modelo.
