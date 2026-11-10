# Hoja de ruta de WhisperMeet

Estado a 9 de noviembre de 2026. Recoge el análisis de punta a punta de la herramienta y el plan por olas para llevarla de «apuntador de reuniones» a «puesto de mando del proyecto»: que sepa qué documentación tiene cada proyecto, cómo es la solución, su modelo de datos, sus usuarios y su plan de sesiones, y que tenga agentes que ayuden también fuera de la reunión.

## Cómo está hoy

| Área | Qué hay | Qué falta |
|---|---|---|
| Reunión en directo | Transcripción local con Whisper, tarjetas, objetivos, checks, asesor, equipo de agentes y eco aplazado en origen. | Validar el eco con sonido real de sala. |
| Documentos del proyecto | Lee `.md`, `.txt`, `.docx`, `.pptx` y `.pdf` como contexto. Mapa de documentos por tipo y aviso de los tipos que faltan (ola A); tipo corregible a mano, resumen de una línea de los documentos clave y tipo propuesto para lo ambiguo (ola B). | Leer `.xlsx`; que el mapa entre en la preparación sugerida y en el resumen del proyecto. |
| Solución tal como está y modelo de datos | La plantilla `03-arquitectura-y-datos`, que se rellena a mano, y desde la ola B el Archivero: cobertura por faceta con el documento que lo dice y lo que falta. | Que proponga los huecos por el flujo de «aceptar cambios»; rellenar la plantilla a partir de lo que encuentra. |
| Usuarios y roles | Desde la ola B, el Archivero extrae los perfiles y roles de la solución que digan los documentos (nunca personas). Las secciones de contactos se excluyen a propósito del contexto de la IA. | Interlocutores del proyecto, sin enviar datos personales al modelo. |
| Planificación de sesiones | Plan de varias sesiones con Gantt, objetivos y checks, pero el JSON se escribe a mano fuera de la app. | Crear y editar el plan en la app; proponerlo a partir del arranque y el alcance. |
| Agentes | Muchos dentro de la reunión. Fuera de ella, la preparación sugerida, el contexto de la reunión y el Archivero (a mano, desde la ficha). | Agentes de proyecto: planificador y redactor de entregables. |
| Empaquetado | Clonar, crear el entorno, instalar dependencias y lanzar; un acceso directo. | Instalador, comprobación de requisitos al primer arranque y ajustes que hoy solo se cambian en el fichero. |
| Datos internos | Todo en ficheros (JSON, JSONL y Markdown) a través de `Guardian`, con escritura atómica. No hay base de datos. | Versión de esquema y migraciones, identificadores estables y copia de seguridad. |
| Entregables | Acta y resumen en Markdown; borrador de correo. | Exportar a Word o PDF con plantilla. |

### Modelo de datos interno, en una línea por entidad

- **Proyecto**: una carpeta bajo la raíz de proyectos o una entrada de `proyectos_extra`. No hay ficha persistida: se deduce de la carpeta.
- **Sesión**: identificador corto, proyecto (o Bandeja), tema, fecha, segmentos, tarjetas, objetivos, checks, acciones y cobertura. Se guarda como Markdown en la carpeta `02. Sesiones (transcripciones)` del proyecto.
- **Plan de sesiones**: un JSON por plan en la carpeta `planes`, de solo lectura para la app.
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

### Ola C — Planificación de sesiones en la app

- Editor del plan: crear, mover y cerrar sesiones, con sus objetivos y checks, guardado a través de `Guardian`.
- «Proponer plan»: un agente lee los documentos de arranque y alcance y propone las sesiones; se revisa antes de guardar.
- Hecho cuando: se puede crear un plan desde cero sin tocar un JSON y una reunión nueva queda enlazada a su sesión del plan.

### Ola D — Empaquetado

- Script de instalación: entorno, dependencias, acceso directo y comprobaciones.
- Comprobación de requisitos al primer arranque: Python, `claude` con sesión iniciada, modelo de Whisper, micrófono y carpetas.
- Dependencias separadas (app y desarrollo) y con versión fijada.
- Ajustes que hoy solo están en el fichero: carpeta de Knowledge, vocabulario de transcripción y ancho de búsqueda de Whisper.
- README al día y manual de usuario.
- Hecho cuando: una máquina limpia llega a la primera reunión con un solo script y la app explica qué falta si falta algo.

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
