# Manual de WhisperMeet

Para quien usa la app, no para quien la programa (eso está en `README.md` y `CLAUDE.md`). WhisperMeet es una app de escritorio para Windows que transcribe tus reuniones en el momento, te va dando avisos útiles mientras hablan y, al terminar, te propone un resumen y cambios al contexto del proyecto. Por defecto todo corre en tu equipo, la transcripción incluida; para analizar el texto usa Claude Code con tu propia licencia. Si quieres, puedes pasar la transcripción a un servicio en la nube (apartado 11); es opcional y empieza apagada.

## 1. La primera vez

1. Ejecuta `instalar.bat` (doble clic). Prepara el entorno, instala lo necesario, crea tu configuración, las carpetas locales y el acceso directo, y ofrece descargar el modelo de transcripción (unos 460 MB, una sola vez). Si algo no se puede hacer solo, al final te dice qué queda por hacer a mano. Puedes repetirlo cuando quieras: lo que ya está hecho, lo deja como está.
2. Si no tienes Claude Code, instálalo, abre una terminal, escribe `claude` y entra con tu cuenta. Sin él la transcripción funciona, pero no hay análisis, resumen ni asesor.
3. Abre WhisperMeet desde el menú Inicio (o ancla el acceso directo a la barra de tareas).
4. Si algo falta, en la pantalla de inicio verás el panel **Antes de la primera reunión**: una lista con el estado de Python, Claude Code, el modelo de transcripción, el micrófono y las carpetas, y qué hacer en cada caso. No bloquea nada. Cuando lo arregles, pulsa **Volver a comprobar**. Con **Ocultar** se quita hasta la próxima vez que abras la app; si solo había avisos, no vuelve a salir. La misma lista está en **Ajustes**, en la sección Audio.
5. En **Ajustes**, sección Privacidad, comprueba la **carpeta que contiene tus proyectos**. Por defecto es `Proyectos` dentro de tu carpeta personal; si no existe, créala o elige otra.

## 2. Empezar una reunión

1. En el inicio elige un proyecto (o **Bandeja** si es una reunión sin proyecto). Con un proyecto elegido aparece la preparación.
2. Escribe el **tema** de la reunión. Si el proyecto tiene un plan de sesiones, elige también la sesión (o «Otra reunión»).
3. Elige el **idioma** (Automático reconoce español, catalán e inglés en cada intervención) y, en Opciones, el **ritmo del equipo**. Si quieres que no salga nada de tu equipo en esa reunión (ni a Claude ni a la nube), marca **Solo local en esta reunión**.
4. Marca que **has avisado a los asistentes** de que vas a transcribir. La app no guarda audio, pero sí el texto, y ese texto se envía a Claude para analizarlo. Si la transcripción va por la nube, la casilla lo dice con claridad (el audio sale a un tercero) y la ventana de aviso de llamada también: avisa a los asistentes de eso, no solo de que se transcribe.
5. Pulsa **Empezar reunión**.

Durante la reunión ves la transcripción en directo (el micrófono se llama «Micro» y lo que suena en tu equipo, «Reunión»), lo que va saliendo y los objetivos de la sesión. Algunas ayudas:

- **Hallazgos** (menú «Más»): decisiones, preguntas, pendientes, riesgos y definiciones, todo junto.
- **Pregúntale**: una pregunta sobre la reunión; hace una sola llamada y solo si la lanzas.
- **Analizar ahora**: pide un análisis sin esperar al siguiente.
- **Modo reunión**: compacta la app en dos paneles laterales, siempre encima, para dejar el centro a Teams.
- Si Teams empieza una llamada, la app te lo propone con un aviso; nunca graba sola.

Si tu equipo no da abasto para transcribir todo lo que se dice, la app prioriza: primero lo que dicen los demás («Reunión») y después tu micro. Lo que lleva más de medio minuto esperando se transcribe después, en cuanto hay un hueco, y aparece en su minuto, entre las líneas que ya había (el orden de la transcripción es siempre el del reloj de la reunión, no el de llegada). El eco de los altavoces que recoge tu micro se deja para el final y, si se acumula, no se transcribe. El aviso de la cabecera dice qué pasa:

- «Transcripción saturada: N s de audio se transcribirán más tarde.» Hay audio atrasado esperando su hueco; el texto en directo va al día, y lo atrasado llegará en su minuto. Si el atraso acumulado supera los ocho minutos, lo más antiguo se pierde y se avisa.
- «El texto del micro va con N s de retraso; el de la reunión va al día.» Lo que dicen los demás se lee casi en directo; tu micro espera.
- «Transcripción con N s de retraso · alcanzando el directo». Van atrasados los dos canales y la app transcribe en modo rápido, algo menos preciso, para recuperar.

Lo que se pierde por saturación y el eco que no se llegó a transcribir quedan anotados en las **Incidencias** del acta, con su tramo horario.

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

- **Audio**: micrófono y audio de la reunión, precisión de la transcripción, **ancho de búsqueda**, **vocabulario de transcripción**, quitar el eco del micro, **dónde se transcribe** (en este equipo o en la nube, apartado 11), proponer grabar con las llamadas de Teams, efectos visuales y la lista de requisitos del equipo.
  - La precisión del modelo: más precisión tarda más; en un portátil, de «Precisa» en adelante la transcripción puede ir con retraso. Se aplica a la reunión siguiente.
  - El ancho de búsqueda va de 1 a 10 (5 por defecto): más ancho acierta más y va más lento. Si la transcripción va con retraso, bájalo; si falla en la jerga, súbelo.
  - El vocabulario es una lista de términos, uno por línea (siglas, nombres de producto, jerga): Whisper los tiene en cuenta y los escribe como tú los pongas. Hasta 60 términos de 40 caracteres. Vale para la reunión siguiente.
- **Equipo**: cuándo interviene el equipo, cuánto hace por su cuenta, avisos silenciados, y qué modelo usa cada tarea (ligero o potente) y con qué límite de uso por hora.
- **Privacidad**: ocultar la ventana en capturas y al compartir pantalla, **Modo solo local**, el registro de envíos, las carpetas que lee la app (carpeta de proyectos, carpetas añadidas y **carpeta de Knowledge**) y la **copia de seguridad** (apartado 10).

Si un valor no es válido (un ancho fuera de rango, un término demasiado largo, una carpeta que no existe), el error sale junto a su campo y no se guarda nada. Con una reunión en curso no se cambian la carpeta de proyectos, el modelo de transcripción ni la carpeta de Knowledge: el cambio se rechaza, con el error junto al campo, y hay que repetirlo al terminar. El resto de los ajustes sí se guardan durante la reunión, también dónde se transcribe (local o nube) y los datos de la nube: se aplican al siguiente trozo.

## 7. Qué se guarda y dónde

- **Audio**: nunca se guarda en disco. Solo existe en memoria mientras se transcribe y se descarta (con la transcripción en la nube, esa memoria es lo que se envía al servicio).
- **Transcripciones**: un `.md` por reunión en la carpeta `02. Sesiones (transcripciones)` del proyecto; las reuniones sin proyecto, en `bandeja`. En un proyecto compartido, durante la reunión se guarda solo en tu equipo (`sesiones`), y al terminar se publica en la carpeta compartida sin sobrescribir nunca nada (o puedes elegir no publicar).
- **Contexto del proyecto**: solo cambia cuando aceptas un cambio en la revisión, en `00. CONTEXTO (IA)` (más el registro de cambios). La app no escribe en `CLAUDE.md`, `AGENTS.md`, `docs` ni en Knowledge.
- **En la carpeta de la app** (todo local, fuera de git): `datos` (tu configuración, el registro de consumo, sin contenido de reuniones, y, si la pusiste, la clave de la nube cifrada con tu usuario de Windows), `planes`, `checks`, `backlog` (qué pendientes has dado por hechos), `cache`, `tipos_documento`, `copias` (tus copias de seguridad, apartado 10) y `modelos`.

El botón **Sesiones** de la cabecera reúne todas las sesiones pasadas y la lista conjunta de pendientes, ideas, decisiones, riesgos y preguntas; no hace llamadas a Claude, y marcar un pendiente como hecho solo se guarda en tu equipo, sin tocar los `.md`.

## 8. Qué sale de tu máquina y qué no

- **Sale**, hacia Claude Code (con tu licencia, nunca por una API ni con claves): el texto de la transcripción, los extractos del contexto del proyecto que hacen falta para cada análisis, y, cuando lanzas el Archivero o «Proponer plan», extractos acotados de los documentos del proyecto (sin secretos, sin contactos, sin correos ni teléfonos). La búsqueda en la web solo ocurre si, al pulsar «Profundizar», marcas la casilla (viene desmarcada) y lo que viaja va sin nombres de cliente, de proyecto, de persona ni importes.
- **Sale a la nube, solo si activas la transcripción en la nube** (apartado 11): el audio del micro y de la reunión, solo los tramos con voz; y, para acertar más, el tema de la reunión, el vocabulario del proyecto y la última frase de cada canal. Va al servicio que hayas configurado (por defecto, OpenAI). No sale nada de esto si está apagada, que es como viene, ni con el **Modo solo local**.
- **No sale**: el audio mientras la transcripción sea en este equipo (lo normal), los ficheros de secretos, las secciones de contactos y nada de lo que pidas explícitamente que se quede (**Modo solo local**: ni una llamada a Claude ni a la nube, solo transcripción y detección local). La clave de la nube solo viaja hacia ese servicio.
- En **Ajustes, Privacidad**, el registro de envíos te enseña cada llamada: qué agente la hizo, cuántos tokens gastó y cuándo; guarda como mucho un extracto de 120 caracteres, nunca el contenido de las reuniones. Lo que va a la nube aparece como un renglón cada dos minutos con los segundos de audio, los trozos y el servidor, sin contenido.
- La app escucha solo en tu equipo y protege cada arranque con un código propio.

## 9. Problemas frecuentes

- **El panel «Antes de la primera reunión» dice que falta algo.** Lee «Qué hacer» en esa fila, arréglalo y pulsa «Volver a comprobar». Si es el modelo, ejecuta `instalar.bat` y acepta la descarga.
- **«claude» no se encuentra, o el análisis falla por la sesión.** Abre una terminal nueva (para que vea el PATH actualizado), escribe `claude` y entra con tu cuenta. Después, «Volver a comprobar».
- **No se transcribe lo que dicen los demás.** Falta el audio del sistema: el panel avisa si Windows no muestra ninguna salida de audio. Revisa en Ajustes que «Audio de la reunión» apunta a los altavoces o auriculares que usas.
- **La transcripción va con retraso.** Baja la precisión en Ajustes o el ancho de búsqueda, y cierra lo que gaste procesador. Mientras grabas, la app sube su prioridad en Windows y usa como mucho la mitad de los núcleos para transcribir, para no quedarse atrás frente a la videollamada; si prefieres que no lo haga, pon `"prioridad_reunion": false` y `"whisper_hilos_auto": false` en `datos\config.json`. Añadir la jerga del proyecto al vocabulario mejora el acierto sin cambiar la velocidad. Con auriculares no hay eco de altavoces que transcribir, y el equipo se dedica a lo que dicen los demás y a tu voz. Qué significa cada aviso de retraso, en el apartado 2.
- **Aparece «Hay una versión nueva de WhisperMeet en este equipo».** Tras actualizar el programa, la ventana abierta sigue con la versión anterior: ciérrala y vuelve a abrirla para usar la nueva (si estás en una reunión, espera a que acabe).
- **Dice «La transcripción en la nube está activada, pero no hay clave».** Falta la clave: ponla en Ajustes › Audio o en la variable `WHISPERMEET_CLAVE_NUBE` (apartado 11). Mientras tanto la reunión se transcribe en tu equipo, sin perder nada.
- **Dice «Modo solo local: esta reunión se transcribe en este equipo, sin la nube».** Es lo esperado: el Modo solo local también apaga la nube. Si la quieres, desactívalo (o desmarca «Solo local en esta reunión» antes de empezar).
- **Dice «La nube rechaza la clave (401)».** La clave está mal escrita, revocada o es de otra cuenta o proyecto. Vuelve a ponerla en Ajustes › Audio y pulsa «Probar»; al guardar vuelve a la nube sin esperar a la siguiente reunión.
- **Dice «La clave no tiene permiso para este modelo o esta dirección (403)».** Esa clave no puede usar ese modelo o esa dirección. Mira en el panel del proveedor los permisos del proyecto o prueba con otra clave.
- **Dice «La cuenta de la nube no tiene crédito o llegó a su límite de gasto».** Recarga saldo o sube el límite en el panel del proveedor; después, «Probar».
- **Dice «La nube no acepta la configuración (modelo, dirección o dialecto)».** Revisa en Ajustes › Audio la dirección, el nombre del modelo y, en «Ajuste fino del servicio», la autenticación y el dialecto. «Probar» te dice cuál falla.
- **Dice «No se puede verificar el certificado del servicio (¿proxy de la empresa?)».** Suele pasar en redes de empresa que inspeccionan el tráfico seguro. Habla con tu equipo de sistemas para que el certificado de la empresa esté instalado en Windows, o usa Whisper local.
- **Dice «Sin conexión con la nube: la transcripción sigue en este equipo y se vuelve a probar en N s».** La nube no responde (red, servicio saturado o caído). Esos trozos van a Whisper local, con el retraso que eso suponga (siempre que el modelo local esté descargado en tu equipo; si no, ese audio se pierde y la app te lo avisa), y la app vuelve a probar sola. Cada trozo tiene un plazo total de 12 segundos para todos sus intentos: pasado ese tiempo se transcribe en local. Cuando lo consigue, avisa con «Transcripción en la nube restablecida». Un proxy de empresa con configuración automática (PAC) o con usuario y contraseña no está soportado: ahí la nube no saldrá y seguirá todo en local.
- **Dice «Falló la nube y no se pudo cargar el modelo local: parte del audio no se ha transcrito».** Falló la nube y, además, el modelo de Whisper no está descargado o no se pudo cargar, así que ese tramo se perdió (la grabación sigue y queda en las Incidencias). El respaldo nunca descarga el modelo en plena reunión: al empezar con la nube, la app lo carga en segundo plano solo si ya está en el equipo. Ejecuta `instalar.bat` antes de la reunión para descargarlo.
- **«Probar» falla.** El mensaje dice la causa, con los mismos textos de arriba pero empezando por «Revisa…». «Probar» envía solo un tono de 1 segundo, nunca tu voz, y funciona aunque el Modo solo local esté activo.
- **Con la nube no veo las palabras dudosas.** Es normal: en los trozos de la nube no hay palabras dudosas.
- **Un término se transcribe mal una y otra vez.** Añádelo al vocabulario de Ajustes tal como quieres verlo escrito.
- **Mi carpeta de Knowledge «no existe» aunque está en OneDrive.** Puede estar sin conexión o sin sincronizar; la app no abre los ficheros que están solo en la nube. Espera a que se sincronice o vacía el campo.
- **Ajustes no me deja cambiar la carpeta de proyectos, el modelo de transcripción o la carpeta de Knowledge.** Hay una reunión en curso: termínala y repite el cambio. El resto de los ajustes sí se guardan mientras dura.
- **Los compañeros ven mi ventana al compartir pantalla.** Mira en Ajustes, Privacidad: «Ocultar la ventana en capturas y al compartir pantalla» debe estar marcado (también hay un botón en la cabecera).
- **Quiero cambiar de sitio la app o actualizarla.** Haz `git pull` y ejecuta `instalar.bat`: instala solo lo que haya cambiado y no toca tus datos. Si cambias la carpeta de sitio, vuelve a crear el acceso directo ejecutando `instalar.bat` (si ya existe uno que apunta a la ubicación anterior, bórralo a mano antes).

## 10. Copia de seguridad y cambio de equipo

Sirve para tener una copia de tus datos de la app o para llevártelos a otro equipo. Se hace en **Ajustes, Privacidad, Copia de seguridad**.

**Crear la copia.** Pulsa **Crear copia**, fuera de una reunión (durante una reunión la app no la hace, para no competir con la transcripción por el disco). La app guarda un zip llamado `whispermeet-copia-AAAA-MM-DD-HHMMSS.zip` en la carpeta `copias` de la app y te dice cuántos ficheros lleva y cuánto ocupa. **Abrir la carpeta de copias** la enseña en el explorador, y la línea «Última copia» te recuerda cuándo hiciste la última. La app nunca borra copias antiguas: las quitas tú cuando quieras.

**Qué entra.** Tu configuración, los planes de sesiones, los checks, el estado del backlog, el seguimiento, los tipos de documento corregidos a mano, el glosario, las reglas y demás datos de la carpeta `datos\ola4`, las reuniones de la bandeja y las sesiones locales de los proyectos compartidos. Cada fichero va con su ruta relativa a la carpeta de la app, y un `MANIFIESTO.json` en la raíz del zip los lista.

**Qué no entra.** La caché (se regenera sola), los modelos de transcripción (se descargan de nuevo con `instalar.bat`), el registro de consumo y el de errores, el entorno virtual, las copias anteriores y los documentos de tus proyectos: las transcripciones guardadas en `02. Sesiones (transcripciones)` y el contexto de cada proyecto viven en tu carpeta de proyectos, y esa carpeta la llevas tú. Un fichero que no se puede leer, que pesa más de 200 MB, que tiene un nombre con pinta de clave o que no se puede guardar en el zip (por ejemplo, un nombre con caracteres que no se codifican) se salta, y la app lo lista con su motivo; un fichero con una fecha de modificación fuera del rango del zip (antes de 1980 o después de 2107) sí entra, con la fecha ajustada. Si la copia llega a 2 GB, se corta: la línea de resultado dice «Copia incompleta», avisa de que faltan ficheros y la lista desplegable explica dónde se cortó.

**Restaurar (a mano).**

1. Cierra la app.
2. En el equipo nuevo, instala la app con `instalar.bat`.
3. Descomprime el zip sobre la carpeta de la app, la que contiene `datos`, `planes` y `bandeja`, y acepta sobrescribir.
4. Abre la app y revisa en **Ajustes, Privacidad** que la carpeta de proyectos y la de Knowledge son las de este equipo: la configuración guarda las rutas del equipo anterior.

El zip lleva un `MANIFIESTO.json` con la lista de ficheros; al descomprimir sobre la carpeta de la app queda ahí, es solo una referencia y se puede borrar.

No hay restauración automática ni migración de versiones todavía.

**Ojo con lo que contiene.** La copia lleva transcripciones y datos de tus reuniones. Se guarda en local, en tu equipo, y dónde la llevas después (un disco, la nube, un correo) es responsabilidad tuya.

## 11. Transcribir en la nube (opcional)

Por defecto la transcripción se hace en tu equipo con Whisper y el audio no sale. Si durante una videollamada tu equipo no da abasto, puedes mandar la transcripción a un servicio en la nube (por defecto, OpenAI). Lo que ganas es que el procesador deja de ser el cuello de botella; no es una promesa de «sin retraso», porque también cuenta tu conexión y el servicio. Y el respaldo: si la nube falla, ese trozo lo transcribe tu equipo, siempre que el modelo de Whisper esté descargado (la app lo carga en segundo plano al empezar); si no lo está, ese audio se pierde y la app te lo avisa. Está probada contra un servidor de pruebas, todavía no contra el servicio real: pulsa «Probar» antes de una reunión importante.

**Activarla, paso a paso.**

1. Necesitas una cuenta de pago del proveedor y una clave de API (una cadena larga, algo como `sk-ficticia-0000000000`), que se crea en el panel del proveedor. No es la de Claude.
2. Abre **Ajustes**, sección **Audio**, y en la transcripción elige **En la nube**. Si antes estaba en tu equipo, marca **Entiendo que el audio sale del equipo**.
3. Pon la clave de una de estas dos maneras. En el campo de clave de Ajustes, escribe la clave y pulsa el botón de guardarla: se guarda cifrada con tu usuario de Windows, el campo se vacía y la app no la vuelve a enseñar. O crea en Windows una variable de entorno de usuario llamada `WHISPERMEET_CLAVE_NUBE` con la clave y reinicia la app. Si hay las dos, manda la variable. Para borrar la guardada, el botón de quitarla (no toca la variable).
4. Deja la dirección (`https://api.openai.com/v1`) y el modelo (`gpt-transcribe`) como vienen, salvo que tengas otro servicio compatible (Azure, Groq o un servidor propio): en ese caso cámbialos y, en **Ajuste fino del servicio**, la autenticación y el dialecto (el `README.md` da los valores). La residencia europea es opcional y depende de tu cuenta del proveedor: se logra con un proyecto europeo y la dirección `https://eu.api.openai.com/v1`; no está confirmado que valga para `gpt-transcribe`.
5. Pulsa **Probar**: envía un tono de 1 segundo (no tu voz) y te dice si va bien y cuánto tarda, o qué falla.
6. Guarda los ajustes. Vale desde el siguiente trozo, también en plena reunión, y puedes volver a tu equipo cuando quieras.

**Qué ves.** En la cabecera aparece un indicador: «Nube» (todo va por la nube), «Nube · local» (la nube está apartada un rato y se transcribe en tu equipo), «Local (nube caída)» (error de configuración o de crédito: bloqueada hasta el final de la reunión o hasta que lo arregles), «Local (sin clave)» o «Local» (Modo solo local). Pasa el ratón por encima para leer el motivo. Los avisos de arriba (apartado 9) explican cada caso.

**Qué sale y qué no.** Lo que está en el apartado 8. Resumido: sale el audio con voz y las pistas (tema, vocabulario y última frase); no sale si está apagada ni con el Modo solo local. El dictado del contexto antes de la reunión sigue siendo en tu equipo.

**Qué cambia.** No hay palabras dudosas en lo que transcribe la nube. Con la nube, en modo rápido solo se acortan las pistas que se mandan. Y avisa a los asistentes de que el audio va a un tercero.

**Cuánto cuesta (orientativo).** OpenAI cobraba en noviembre de 2026 0,0045 $ por minuto de audio con `gpt-transcribe`, unos 0,27 $ por hora de audio; el silencio no se envía y, si hablan los dos canales a la vez, se suman. Una reunión de una hora cuesta entre unos céntimos y poco más de 0,5 $. Confírmalo en la página de precios del proveedor, que puede cambiar. La app no pone tope de gasto: ponlo en el panel del proveedor.

**Copia de seguridad.** La clave guardada no entra en la copia y está atada a tu usuario de Windows: en un equipo o perfil nuevo hay que volver a ponerla.
