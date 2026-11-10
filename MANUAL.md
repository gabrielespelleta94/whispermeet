# Manual de WhisperMeet

Para quien usa la app, no para quien la programa (eso está en `README.md` y `CLAUDE.md`). WhisperMeet es una app de escritorio para Windows que transcribe tus reuniones en el momento, te va dando avisos útiles mientras hablan y, al terminar, te propone un resumen y cambios al contexto del proyecto. Todo corre en tu equipo; para analizar el texto usa Claude Code con tu propia licencia.

## 1. La primera vez

1. Ejecuta `instalar.bat` (doble clic). Prepara el entorno, instala lo necesario, crea tu configuración, las carpetas locales y el acceso directo, y ofrece descargar el modelo de transcripción (unos 460 MB, una sola vez). Si algo no se puede hacer solo, al final te dice qué queda por hacer a mano. Puedes repetirlo cuando quieras: lo que ya está hecho, lo deja como está.
2. Si no tienes Claude Code, instálalo, abre una terminal, escribe `claude` y entra con tu cuenta. Sin él la transcripción funciona, pero no hay análisis, resumen ni asesor.
3. Abre WhisperMeet desde el menú Inicio (o ancla el acceso directo a la barra de tareas).
4. Si algo falta, en la pantalla de inicio verás el panel **Antes de la primera reunión**: una lista con el estado de Python, Claude Code, el modelo de transcripción, el micrófono y las carpetas, y qué hacer en cada caso. No bloquea nada. Cuando lo arregles, pulsa **Volver a comprobar**. Con **Ocultar** se quita hasta la próxima vez que abras la app; si solo había avisos, no vuelve a salir. La misma lista está en **Ajustes**, en la sección Audio.
5. En **Ajustes**, sección Privacidad, comprueba la **carpeta que contiene tus proyectos**. Por defecto es `Proyectos` dentro de tu carpeta personal; si no existe, créala o elige otra.

## 2. Empezar una reunión

1. En el inicio elige un proyecto (o **Bandeja** si es una reunión sin proyecto). Con un proyecto elegido aparece la preparación.
2. Escribe el **tema** de la reunión. Si el proyecto tiene un plan de sesiones, elige también la sesión (o «Otra reunión»).
3. Elige el **idioma** (Automático reconoce español, catalán e inglés en cada intervención) y, en Opciones, el **ritmo del equipo**. Si quieres que no salga nada a Claude en esa reunión, marca **Solo local en esta reunión**.
4. Marca que **has avisado a los asistentes** de que vas a transcribir. La app no guarda audio, pero sí el texto, y ese texto se envía a Claude para analizarlo.
5. Pulsa **Empezar reunión**.

Durante la reunión ves la transcripción en directo (el micrófono se llama «Micro» y lo que suena en tu equipo, «Reunión»), lo que va saliendo y los objetivos de la sesión. Algunas ayudas:

- **Hallazgos** (menú «Más»): decisiones, preguntas, pendientes, riesgos y definiciones, todo junto.
- **Pregúntale**: una pregunta sobre la reunión; hace una sola llamada y solo si la lanzas.
- **Analizar ahora**: pide un análisis sin esperar al siguiente.
- **Modo reunión**: compacta la app en dos paneles laterales, siempre encima, para dejar el centro a Teams.
- Si Teams empieza una llamada, la app te lo propone con un aviso; nunca graba sola.

Pulsa **Terminar** al acabar. En la **revisión** ves el resumen final, los cambios propuestos al contexto del proyecto y un borrador de correo de cierre (se copia; la app no envía nada). Los cambios se aceptan o se rechazan uno a uno, y solo entonces se escribe algo en el contexto.

## 3. Proyectos y contexto

Un proyecto es una subcarpeta de tu carpeta de proyectos, o una carpeta que añadas con **Añadir carpeta de proyecto** (en el inicio o en Ajustes; también sirve una carpeta de OneDrive compartida por otra persona: márcala como compartida).

La app lee como contexto, de solo lectura, los ficheros `.md` del proyecto: la carpeta `00. CONTEXTO (IA)` primero, y después `CLAUDE.md`, `AGENTS.md`, `README.md` y el resto. No lee `.env`, credenciales, claves ni carpetas con pinta de secreto, y omite las líneas que parecen secretos y las secciones de contactos. En la galería de proyectos, el indicador de contexto te dice si a un proyecto le falta `00. CONTEXTO (IA)`.

Además, en Ajustes puedes poner una **carpeta de Knowledge**: documentación de consulta (`.md`, `.txt`, `.docx`, `.pptx`, `.xlsx`, `.xlsm` y `.pdf`) que el asesor puede leer durante la reunión. De una hoja de cálculo se leen solo las celdas de las hojas visibles (fechas como `AAAA-MM-DD`, porcentajes con su `%`, decimales a 6 cifras, sin fórmulas ni macros) y con topes: 20 hojas, 2.000 filas por hoja y 40 columnas. Los PDF solo se leen si hay un lector de PDF instalado (`pypdf`, `PyPDF2` o `pymupdf`; el instalador no lo instala): sin él se ignoran. Es de solo lectura: la app nunca escribe en ella, y no admite carpetas de claves ni carpetas que se solapen con tus proyectos o con la propia app.

## 4. Documentos del proyecto y Archivero

La ficha de cada proyecto (pulsa su tarjeta en el inicio) tiene el bloque **Documentos del proyecto**. Recorre la carpeta mirando solo nombres, tamaños y fechas (no abre ningún fichero ni descarga los que están solo en la nube) y los ordena por tipo: arranque, oferta y alcance, funcional, técnico, modelo de datos, usuarios y roles, planificación, seguimiento y actas, pruebas y formación. Te dice cuál es el último de cada tipo y qué tipos no aparecen. Si un documento está mal clasificado, puedes corregir su tipo a mano.

El **Agente Archivero** se lanza a mano desde el mismo bloque («Analizar con Claude»). Hace una sola llamada a Claude con una selección acotada de los documentos clave y devuelve un resumen de una línea de cada uno y qué cubre el proyecto (la solución tal como está, el modelo de datos, usuarios y roles, alcance y plan) con el documento que lo dice. También lee hojas de cálculo (`.xlsx` y `.xlsm`): una hoja llamada «Contactos» no sale y las columnas de correo o teléfono llegan tapadas. Antes de salir, el texto pierde secretos, secciones de contactos, correos y teléfonos. Nunca se ejecuta solo ni al abrir la ficha. Si te sirve, puedes guardar el resultado como un fichero más de `00. CONTEXTO (IA)`.

## 5. Plan de sesiones

El bloque **Plan de sesiones** de la ficha permite crear el plan sin tocar ningún fichero: sesiones con su nombre, fecha, hora, objetivos, checks, dependencias y fichero prioritario. Se reordenan con los botones (también con el teclado) y se guarda con **Guardar**; hasta entonces ves «Cambios sin guardar» y puedes **Descartar**. Si el fichero cambió fuera de la app, avisa en lugar de pisarlo, y guarda una copia del plan anterior.

**Proponer plan con Claude** lanza a mano una llamada que lee los documentos de arranque, alcance, planificación y funcionales, y te da un borrador que entra en el editor. No se guarda nada hasta que pulses **Guardar**, y las fechas solo se proponen si están escritas en los documentos.

Al empezar una reunión, la sesión del plan que elijas trae sus objetivos y checks: durante la reunión se van marcando como tratados, citando el minuto, y lo que marques o desmarques tú manda sobre lo que marque la app.

## 6. Ajustes

Se abren con el botón **Ajustes** de la cabecera. Tienen tres secciones:

- **Audio**: micrófono y audio de la reunión, precisión de la transcripción, **ancho de búsqueda**, **vocabulario de transcripción**, quitar el eco del micro, proponer grabar con las llamadas de Teams, efectos visuales y la lista de requisitos del equipo.
  - La precisión del modelo: más precisión tarda más; en un portátil, de «Precisa» en adelante la transcripción puede ir con retraso. Se aplica a la reunión siguiente.
  - El ancho de búsqueda va de 1 a 10 (5 por defecto): más ancho acierta más y va más lento. Si la transcripción va con retraso, bájalo; si falla en la jerga, súbelo.
  - El vocabulario es una lista de términos, uno por línea (siglas, nombres de producto, jerga): Whisper los tiene en cuenta y los escribe como tú los pongas. Hasta 60 términos de 40 caracteres. Vale para la reunión siguiente.
- **Equipo**: cuándo interviene el equipo, cuánto hace por su cuenta, avisos silenciados, y qué modelo usa cada tarea (ligero o potente) y con qué límite de uso por hora.
- **Privacidad**: ocultar la ventana en capturas y al compartir pantalla, **Modo solo local**, el registro de envíos y las carpetas que lee la app (carpeta de proyectos, carpetas añadidas y **carpeta de Knowledge**).

Si un valor no es válido (un ancho fuera de rango, un término demasiado largo, una carpeta que no existe), el error sale junto a su campo y no se guarda nada. Con una reunión en curso no se cambian la carpeta de proyectos, el modelo de transcripción ni la carpeta de Knowledge: el cambio se rechaza, con el error junto al campo, y hay que repetirlo al terminar. El resto de los ajustes sí se guardan durante la reunión.

## 7. Qué se guarda y dónde

- **Audio**: nunca se guarda en disco. Solo existe en memoria mientras se transcribe y se descarta.
- **Transcripciones**: un `.md` por reunión en la carpeta `02. Sesiones (transcripciones)` del proyecto; las reuniones sin proyecto, en `bandeja`. En un proyecto compartido, durante la reunión se guarda solo en tu equipo (`sesiones`), y al terminar se publica en la carpeta compartida sin sobrescribir nunca nada (o puedes elegir no publicar).
- **Contexto del proyecto**: solo cambia cuando aceptas un cambio en la revisión, en `00. CONTEXTO (IA)` (más el registro de cambios). La app no escribe en `CLAUDE.md`, `AGENTS.md`, `docs` ni en Knowledge.
- **En la carpeta de la app** (todo local, fuera de git): `datos` (tu configuración y el registro de consumo, sin contenido de reuniones), `planes`, `checks`, `backlog` (qué pendientes has dado por hechos), `cache`, `tipos_documento` y `modelos`.

El botón **Sesiones** de la cabecera reúne todas las sesiones pasadas y la lista conjunta de pendientes, ideas, decisiones, riesgos y preguntas; no hace llamadas a Claude, y marcar un pendiente como hecho solo se guarda en tu equipo, sin tocar los `.md`.

## 8. Qué sale de tu máquina y qué no

- **Sale**, hacia Claude Code (con tu licencia, nunca por una API ni con claves): el texto de la transcripción, los extractos del contexto del proyecto que hacen falta para cada análisis, y, cuando lanzas el Archivero o «Proponer plan», extractos acotados de los documentos del proyecto (sin secretos, sin contactos, sin correos ni teléfonos). La búsqueda en la web solo ocurre si, al pulsar «Profundizar», marcas la casilla (viene desmarcada) y lo que viaja va sin nombres de cliente, de proyecto, de persona ni importes.
- **No sale**: el audio, los ficheros de secretos, las secciones de contactos y nada de lo que pidas explícitamente que se quede (**Modo solo local**: ni una llamada a Claude, solo transcripción y detección local).
- En **Ajustes, Privacidad**, el registro de envíos te enseña cada llamada: qué agente la hizo, cuántos tokens gastó y cuándo; guarda como mucho un extracto de 120 caracteres, nunca el contenido de las reuniones.
- La app escucha solo en tu equipo y protege cada arranque con un código propio.

## 9. Problemas frecuentes

- **El panel «Antes de la primera reunión» dice que falta algo.** Lee «Qué hacer» en esa fila, arréglalo y pulsa «Volver a comprobar». Si es el modelo, ejecuta `instalar.bat` y acepta la descarga.
- **«claude» no se encuentra, o el análisis falla por la sesión.** Abre una terminal nueva (para que vea el PATH actualizado), escribe `claude` y entra con tu cuenta. Después, «Volver a comprobar».
- **No se transcribe lo que dicen los demás.** Falta el audio del sistema: el panel avisa si Windows no muestra ninguna salida de audio. Revisa en Ajustes que «Audio de la reunión» apunta a los altavoces o auriculares que usas.
- **La transcripción va con retraso.** Baja la precisión en Ajustes o el ancho de búsqueda, y cierra lo que gaste procesador. Añadir la jerga del proyecto al vocabulario mejora el acierto sin cambiar la velocidad.
- **Un término se transcribe mal una y otra vez.** Añádelo al vocabulario de Ajustes tal como quieres verlo escrito.
- **Mi carpeta de Knowledge «no existe» aunque está en OneDrive.** Puede estar sin conexión o sin sincronizar; la app no abre los ficheros que están solo en la nube. Espera a que se sincronice o vacía el campo.
- **Ajustes no me deja cambiar la carpeta de proyectos, el modelo de transcripción o la carpeta de Knowledge.** Hay una reunión en curso: termínala y repite el cambio. El resto de los ajustes sí se guardan mientras dura.
- **Los compañeros ven mi ventana al compartir pantalla.** Mira en Ajustes, Privacidad: «Ocultar la ventana en capturas y al compartir pantalla» debe estar marcado (también hay un botón en la cabecera).
- **Quiero cambiar de sitio la app o actualizarla.** Haz `git pull` y ejecuta `instalar.bat`: instala solo lo que haya cambiado y no toca tus datos. Si cambias la carpeta de sitio, vuelve a crear el acceso directo ejecutando `instalar.bat` (si ya existe uno que apunta a la ubicación anterior, bórralo a mano antes).
