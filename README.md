# WhisperMeet (carpeta y paquete: apuntes)

Herramienta local para Windows, al estilo Granola: transcribe reuniones en directo, da insights periódicos y propone cambios a las carpetas de contexto del proyecto. Sin correo ni calendario. Interfaz en español, modo claro y oscuro.

## Instalación

Solo Windows. Requiere Python 3.12 y el CLI de Claude Code (`claude`) instalado y con la sesión iniciada (las llamadas de análisis usan tu licencia; no hay claves de API).

```
cd <tu carpeta>\apuntes
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe app.py
```

Los modelos de Whisper se descargan solos la primera vez que se transcribe (carpeta `modelos\`). La configuración se guarda en `datos\config.json`; `config.example.json` muestra las claves habituales (carpeta raíz de proyectos, Knowledge de solo lectura, autor y proyectos extra). Con los valores por defecto la raíz es `~\Proyectos` y el autor, tu usuario de Windows.

## Arranque

```
cd <tu carpeta>\apuntes
.venv\Scripts\python.exe app.py
```

Para probarlo sin audio, con una transcripción ficticia a tiempo acelerado:

```
.venv\Scripts\python.exe app.py --simular pruebas\reunion-ficticia.txt
.venv\Scripts\python.exe app.py --simular pruebas\reunion-ficticia.txt --sin-ventana --velocidad 30   # solo servidor; abre la URL que imprime
.venv\Scripts\python.exe pruebas\ejecutar_simulacion.py       # recorre inicio, reunión, análisis, revisión y aceptación
.venv\Scripts\python.exe pruebas\ejecutar_simulacion.py --compartido --sesion-plan S1   # lo mismo con proyecto compartido, plan, checks y publicación (--no-publicar: elige «No publicar»)
.venv\Scripts\python.exe pruebas\medir_checks.py            # tokens que añaden 0, 6 y 15 checks a una llamada periódica (claude -p, texto ficticio)
.venv\Scripts\python.exe pruebas\simular_equipo.py [--objetivos "a;b"]   # cuántos turnos daría el equipo y qué leería cada perfil sobre TR2 (local, sin modelo)
.venv\Scripts\python.exe pruebas\probar_preguntale.py       # 3 preguntas reales a «Pregúntale» sobre la reunión ficticia (claude -p, haiku)
.venv\Scripts\python.exe pruebas\probar_tr2.py --modo equipo --velocidad 3 --proyecto "Planificador TR2 (sin 09 ni 11)" --salida pruebas\_real\resultado_equipo.json   # la reunión real TR2 con el equipo (--falso: ensayo sin tokens)
.venv\Scripts\python.exe pruebas\comparar_equipo.py       # antes frente a después: tokens, turnos, tarjetas, definiciones y decisiones de la lista
.venv\Scripts\python.exe pruebas\medir_perfiles.py --fase base   # GASTA llamadas reales: entrada, salida, razonamiento y caché de cada perfil (pruebas\_real\medicion_perfiles.txt)
esultado_adaptativo.json   # la reunión real TR2 con el disparo adaptativo
```

Opciones: `--raiz <carpeta>` (raíz de proyectos), `--puerto N`, `--mostrar-en-captura`. Solo para pruebas: `--config FICHERO.json` (configuración alternativa, no toca `datos\config.json`), `--extra NOMBRE=RUTA` (proyecto compartido que sustituye a `proyectos_extra` sin tocar `datos\config.json`), `--planes <carpeta>`, `--sesiones <carpeta>`, `--checks <carpeta>`.
Tests: `.venv\Scripts\python.exe -m pytest tests -q`.

### Instalación desde cero

```
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

El modelo de transcripción (`small`, unos 460 MB) se descarga la primera vez a `modelos\`.

## Requisitos

- Claude Code (`claude`) en el PATH y con la sesión iniciada con tu licencia. **El análisis usa solo Claude Code; nunca la API.** No hay clave que configurar.
- WASAPI loopback (Windows 10/11) para el audio del sistema.

## Cómo funciona

**Diseño.** La interfaz sigue la dirección «cuaderno» de `DESIGN-visual.md` §0: papel cálido en claro y grafito cálido en oscuro, acciones en tinta (sin azul de marca), Sitka (la serif que trae Windows) para lo que se lee y DM Sans para los controles, etiquetas en tipo frase, un solo nivel de caja y color solo con significado (grabación, tipo de aviso y agente). Fuentes y logo son locales (`web/fuentes`, `web/marca`): funciona sin internet. Lo funcional de la reunión sigue `DESIGN-agentico.md`. En la pantalla de reunión, bajo la cabecera, la banda **Orquestación** (96 px, plegable a una línea de 32 px) muestra los agentes que existen de verdad: Escucha Micro, Escucha Reunión, Transcriptor (Whisper, local), Contexto, Analista, Verificador, Redactor y Pulidor, cada uno con su estado real (en espera, trabajando, hecho, error, omitido), su modelo y su último dato (tramo, duración, tokens). Los estados salen de eventos `tarea` que emite el backend al empezar y acabar cada llamada al modelo y cada tramo transcrito: no hay temporizadores ni puesta en escena, y las llamadas al modelo se ven en serie, tal como ocurren. Un nodo solo se anima (anillo, trazos en el conector de salida) mientras trabaja de verdad; en reposo solo se mueven `●REC` y los medidores. Pulsa un nodo para abrir el **Registro** filtrado por ese agente.
Para verla sin gastar licencia: `.venv\Scripts\python.exe pruebas\servir_modelo_falso.py --retardo 4 -- --simular pruebas
eunion-ficticia.txt --velocidad 6 --sin-ventana --raiz pruebas\proyectos --planes pruebas\planes-beta --sesiones <carpeta> --checks <carpeta> --extra "Proyecto Compartido Beta=pruebas\compartidos\Proyecto Compartido Beta"` (`--limite-desde N` simula el límite del plan).


1. **Inicio.** Eliges proyecto (subcarpetas de primer nivel de la raíz configurada y los `proyectos_extra`, con buscador; los compartidos salen marcados como «compartida») o «Bandeja». Al elegir un proyecto aparece el **panel de contexto** (sin llamar a ningún modelo): con plan, la ficha del proyecto, un **Gantt** por semanas (fases, sesiones TR1..TR5, hitos y línea de «hoy»; HTML/CSS, claro y oscuro), los próximos hitos y la lista de sesiones (celebrada, hoy, propuesta, «por definir»…); si además eliges sesión, se resalta en el Gantt y se muestran sus objetivos principales, fecha, participantes, dependencias y los **checks**. Sin plan, o con «Otra reunión (sin objetivos)», el panel es sobrio, sin Gantt, con checks manuales. Se rellena el tema con el de la sesión. Escribes el tema; eliges cuándo se analiza: **Adaptativo** (por defecto), Cada 5 min, Cada 10 min o Solo cuando lo pida («Analizar ahora» funciona siempre). Sin plan o con «Otra reunión» puedes escribir tus propios objetivos antes de empezar, y bajo la lista de proyectos hay «Añadir carpeta de proyecto» (nombre, ruta y si es compartida; la valida el Guardian). Hay un recordatorio visible de avisar a los asistentes que hay que confirmar.
2. **Reunión.** Dos flujos separados: micrófono = «Micro» (en una sala física recoge a varias personas, así que nunca se da por hecho quién habla), audio del sistema = «Reunión». Transcripción en directo, medidores, cronómetro, pausa, notas libres y panel de insights (decisiones, pendientes con responsable, contradicciones con el contexto, preguntas que convendría hacer, riesgos), cada tarjeta con su minuto (pulsa el minuto para saltar a la transcripción). «Analizar ahora» fuerza un análisis.
   **Pocas tarjetas, bien elegidas:** como máximo 3 nuevas por análisis, por prioridad (decisión, contradicción, pendiente, riesgo, pregunta), sin duplicar lo ya emitido ni entre categorías (una pregunta y una decisión sobre lo mismo en el mismo minuto son una). Una **decisión** exige acuerdo explícito en la conversación; una propuesta o un «deberíamos» va como pendiente o pregunta, y una pregunta solo si sigue sin respuesta al final del tramo. Las candidatas a contradicción salen al momento como **«posible contradicción»** (hasta 8 por reunión) y se confirman todas juntas, con UNA sola llamada a sonnet, al terminar.
   Distribución: transcripción y notas en 1/3 del ancho (líneas compactas: minuto y hablante arriba, texto debajo); el resto, 2/3, en dos columnas: objetivos y checks (un único scroll) e insights (un único scroll); por debajo de ~1100 px esa zona pasa a una columna. El botón **Contexto** de la barra abre un cajón con el Gantt, la ficha y los checks sin perder el directo.
   Con plan, un panel de **objetivos** (sin tratar, parcial o cubierto) se actualiza con cada análisis periódico citando el minuto (pulsa el minuto para saltar a la transcripción). Un objetivo cubierto no retrocede salvo evidencia clara.
   **Checks** (antes y durante la reunión): los del plan para la sesión (p. ej. TR3: tenant y workspace, réplica del Data Lake, inventario, precios por tipología, frecuencia y calidad de la carga), los **sugeridos** por el digest (marca «sugerido», hasta 8) y los tuyos; se añaden, editan, borran, marcan y desmarcan. Lo que marcas o desmarcas tú queda **bloqueado**: el modelo no lo cambia. El análisis periódico marca solo los checks abiertos y sin bloquear, con su minuto y una cita de hasta 15 palabras (etiqueta «Automático»; **Deshacer** con un clic, y entonces queda bloqueado). Se guardan por proyecto y sesión en `checks\<proyecto>.json` (local, fuera de git; sobreviven a reiniciar) y entran en el .md de la sesión y en el resumen final como hechos y pendientes.
3. **Revisión.** Resumen final (con los objetivos cumplidos y los que quedan pendientes) y cambios propuestos a `00. CONTEXTO (IA)` en forma de diff; se aceptan o rechazan uno a uno y solo entonces se escribe. Cada aplicación añade una entrada a `10-registro-de-cambios.md`. Si el proyecto es compartido, la pantalla avisa de que se escribirá en una carpeta compartida (con su ruta) y pide confirmación al aplicar. Además, en proyectos compartidos muestra la **publicación** del documento final: ruta de destino en «02. Sesiones (transcripciones)», aviso de que es una carpeta compartida y casilla «Publicar en la carpeta compartida» (marcada por defecto; desmárcala para descartar reuniones de prueba). Se publica al cerrar la revisión; si falla, se muestra el error, la copia local se conserva y se puede reintentar.
   El resumen final se construye con el resumen de TODA la reunión (cada tramo con su minuto) y con TODAS las tarjetas en forma compacta, no solo con las últimas; para proponer cambios al contexto se comparan las decisiones con los ficheros más cercanos a la reunión (no el más grande) y, si no hay ninguno, la revisión dice el motivo.
   **Pulir con Opus (opcional).** Un botón junto al resumen final lanza UNA llamada a Opus con el resumen de sonnet y las tarjetas compactas (sin transcripción ni contexto) para ordenarlo y redactarlo mejor sin añadir nada. **Gasta bastante más de tu licencia que el resto del análisis** y es la única excepción a «nunca opus»: solo se ejecuta al pulsarlo, sin reintentos. Se muestran las dos versiones y eliges con cuál te quedas; solo la elegida entra en el documento (y en lo publicado). Si falla, se muestra el motivo y sigues con la de sonnet.

## Proyectos compartidos y plan de sesiones

`proyectos_extra` (en `datos\config.json` / `config.py`) lista proyectos fuera de la raíz: `{"nombre", "ruta", "compartido"}`. Por defecto está vacío; cada instalación declara los suyos (p. ej. una carpeta de OneDrive compartida y de otra persona, con `compartido: true`). Para un proyecto compartido:

- **Durante la reunión** la transcripción se guarda **solo en local**, de forma incremental: `apuntes\sesiones\<proyecto>\AAAA-MM-DD-tema.md` (no se sincroniza un borrador a medias y sobrevive a un cierre o a OneDrive sin conexión). «02. Sesiones» no se crea ni durante la reunión ni durante la revisión.
- **Al terminar** se publica el documento final (transcripción, resumen, objetivos y checks) en `<proyecto>\02. Sesiones (transcripciones)\AAAA-MM-DD-tema.md`, creando la carpeta si falta y **sin sobrescribir nunca** (si el nombre existe, `-2`, `-3`…). «No publicar» no crea nada en la carpeta compartida. Es la única ruta de sesión que el Guardian admite allí (`publicar_sesion`).
- `00. CONTEXTO (IA)` solo se toca tras aceptar un cambio en la revisión, y solo `NN-nombre.md` + `10-registro-de-cambios.md`; si la carpeta de contexto no existe no se crea.
- El resto de reglas del Guardian no cambia (ni CLAUDE.md/AGENTS.md/docs, ni secretos, ni Knowledge).

El plan vive en `apuntes\planes\<nombre>.json` (local, fuera de git, igual que `sesiones\` y `checks\`): `{"proyecto", "ficha": {"que_es": [...], "fuente": {"fichero", "version"}}, "gantt": {"semanas", "fases", "hitos", "sesiones", "ventana_sesiones"}, "sesiones": [{"id", "nombre", "fecha", "fecha_iso", "hora", "participantes", "objetivos": [...], "checks": [...], "fichero_prioritario", "depende_de": [...]}]}`. Las fechas del Gantt llevan `fecha_estado` (`confirmada`, `propuesta`, `por_definir`, `por_confirmar`) y solo tienen `fecha_iso` cuando el origen da el día: lo «por definir» o «por confirmar» se queda así (hay test contra fechas inventadas). El Gantt de Planificador de Grupos sale del kick-off v04 (`Kick_Off_Planificador_Grupos_v04_291026_editable.html`). El plan de Planificador de Grupos (`planificador-grupos.json`) tiene TR3 Revisión DataLake, TR4 Contrato de la petición con Salesforce, TR5 Validación del diseño funcional (propuesta martes 10 de noviembre, depende de TR3 y TR4) y «Otra reunión (sin objetivos)».

Coste en tokens de los checks: ver «Consumo con checks» más abajo. Los objetivos van dentro de la llamada periódica que ya existía (campo compacto `o` con solo los cambios; sin llamadas nuevas) y solo se envían los de la sesión elegida. El digest pone primero el fichero prioritario de la sesión y la sesión entra en la clave de caché (otra sesión = otro digest, una vez). Sin plan o con «Otra reunión» los prompts son idénticos a los de antes.

## Escucha activa: análisis según lo que se dice, preguntas en directo y proyectos genéricos

**El equipo (por defecto; sustituye al disparo adaptativo).** Un vigía **local** (el Monitor, `apuntes/equipo/monitor.py`: expresiones regulares y aritmética, cero tokens) escucha cada 30 s, cuenta palabras, detecta 14 señales en español, marca los objetivos y checks que se tocan («visto 27:40»), extrae definiciones («definimos cupo como…») y decide a quién le toca hablar entre cuatro perfiles de haiku: **Coordinador** (fechas, responsables, pendientes, decisiones), **Analista funcional** (definiciones, reglas, alcance), **Constructor** (datos, sistemas, cifras, riesgos) y **Revisor** (contraste con el contexto, objetivos y checks). Cada turno es UNA llamada corta con su tramo del contexto, su estado, sus últimos títulos y la transcripción nueva (tope 4.000 caracteres: si hay más, cada perfil conserva lo de su oficio y lo último). Las llamadas al modelo van **en serie** (nunca dos a la vez). La pantalla muestra, en una columna propia, la línea del Monitor, una tarjeta por perfil (estado real, lo último que aportó, su siguiente turno y por qué), las **Definiciones** (la detección local la sustituye la Analista con el mismo término, conservando el minuto más antiguo) y el **Minuto a minuto** (lo que detecta el Monitor, etiquetado «detección local»); nada se simula: una tarjeta solo figura TRABAJANDO si hay un evento `tarea` real. Cadencias: «Equipo» (por defecto), cada 5 o 10 min (el análisis generalista de siempre; el Monitor corre igual) y «solo cuando lo pida» («Analizar ahora» llama al perfil con más puntos). Umbrales en Ajustes y `config.py` (`equipo_*`).

**Presupuesto por hora** (`presupuesto_tokens_hora`, 60.000 por defecto; ventana de 60 min de reunión; cuenta entrada con caché y salida de TODAS las llamadas): visible en el pie (`Presupuesto 23,4k / 60k esta hora · haiku 11 · sonnet 0 · opus 0`). Al 80 % los turnos se espacian el doble y no hay rotación; al 100 % no hay turnos automáticos (el Monitor, «Analizar ahora» y Pregúntale siguen; las tarjetas dicen «Sin presupuesto» y la hora real en que la ventana libera tokens). El cierre con sonnet nunca se bloquea.

**Qué cuesta (medido, `claude -p` real; detalle en `pruebas\_real\medicion_perfiles.txt`).** Hallazgos que cambiaron la especificación original:
- `claude -p` cuesta ~**860 tokens por llamada** aunque el prompt sea vacío (no hay flag que lo quite: probados `--safe-mode`, `--restricted`). Un turno de perfil son ~**2.800 de entrada** (860 + prompt de sistema ~420 + tramo ~250 + transcripción ~1.100 + estado) y 250-500 de salida, no los 1.500 y 250 previstos.
- **Razonamiento de haiku**: con el prompt corto es 0 en la mayoría de turnos (base: 11 de 12), pero aparece a ratos (650-1.500 tokens; en la pasada real 5 de 10 turnos). No lo quitan ni la redacción (directiva «sin pensar», prompt de extracción, quitar «ya_emitido»: 2 de 4, 4 de 4, 3 de 4 con razonamiento) ni los flags (`CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING`, `alwaysThinkingEnabled=false`: 4 de 4, peor). Se asume como coste y entra en el presupuesto.
- **Caché de prefijo**: con prompts de sistema cortos (<~2.000 tokens) no hay caché (cada llamada «crea» y nunca lee). Con un sistema común y estable de ~2.500 tokens SÍ se leen entre perfiles (20 s después) y pasados 6,5 min (TTL de 1 h), pero los tokens que cuentan suben (4.600 por turno) y el coste de referencia baja solo ~20 %: no se usa.
- Con el enfriamiento global de 150 s, TR2 daba 21-24 turnos por hora; con **240 s**, 13-16 (`pruebas\simular_equipo.py`, sin modelo).
- Pasada real de TR2 (`probar_tr2.py --modo equipo`; sesión interrumpida por una suspensión del equipo de ~23 min, así que SOLO valen los primeros ~43 min de reunión, 9 turnos): turnos de 2.700-3.400 tokens de entrada; haiku 47,4k (digest 10,2k incluido) y sonnet 21,8k (confirmar 2,6k + cierre 19,1k); frente a 199,7k de la pasada de 5 min (haiku 176,6k).
- Cierre de sonnet: antes viajaban hasta 4 ficheros de 5.000 caracteres y 12.000 caracteres de transcripción sin analizar; ahora 3 de 4.000 y 6.000 (`final_max_ficheros`, `final_tope_fichero`, `final_chars_tramo`).

**Tema e ideas.** La llamada periódica devuelve además `e` (título del tema del tramo, ≤40 caracteres) y admite la categoría «idea» (la de menor prioridad dentro del tope de 3 tarjetas, nunca una decisión). Añaden ≈230 caracteres (~65 tokens) al prompt de sistema (el campo `e` suma además unos pocos tokens de salida por llamada; no se ha medido aparte). Una **pregunta** solo se propone si sigue abierta y conecta con un objetivo o un check, si los hay.

**Anotaciones propias.** Junto a «Notas»: un campo y tres botones, Comentario, Pregunta e Idea. Se guardan con el minuto actual, aparecen en el Gantt de la sesión y en Insights con la marca «tú», se editan y se borran, viajan con el siguiente análisis como las notas y entran en el .md y en el resumen final. Nunca se convierten en decisión. «Preguntar a la IA» en una pregunta tuya la lanza a Pregúntale solo con ese clic.

**Pregúntale.** Caja bajo Insights: escribes y recibes la respuesta en su zona. Una llamada por pregunta, solo si la lanzas, de una en una (haiku; sonnet si lo eliges para esa pregunta). Entrada: digest, resumen por tramos, las últimas 40 líneas de transcripción (tope de 5.000 caracteres) y, solo si la pregunta nombra un fichero de contexto, extractos locales de él (por términos, sin LLM; tope de 6.000 caracteres y 3 ficheros). Respuesta corta con minuto y fichero como citas clicables (las que no corresponden a lo entregado se descartan); si no hay base en los datos, lo dice. El historial es visible y entra en el .md. Es el nodo «Consultas» de la orquestación. La transcripción sigue siendo dato no fiable y la respuesta no ejecuta nada. Medido con `pruebas\probar_preguntale.py` (reunión ficticia, 3 preguntas reales a haiku): 4.483, 4.737 y 4.500 tokens por pregunta (entrada con caché y salida), 7-10 s cada una; la que nombra «alcance» recibió el extracto de `02-alcance.md` y lo citó.

**Gantt de la sesión.** Banda plegable «Sesión» (unos 132 px) sobre el cuerpo de la reunión, distinta del Gantt del proyecto: eje de 00:00 al minuto actual, carriles de temas, objetivos (primera a última evidencia), insights por tipo y anotaciones tuyas, marcas de análisis y línea de «ahora»; hover con el texto, clic o Intro para ir a la tarjeta y a la línea, filtro por tipo, teclado. Se muestra completa en la revisión. El .md lleva una cronología por tema y minuto (solo minutos y tipos: el texto no se repite). Detalle en `DESIGN-agentico.md`.

**Genérico para cualquier proyecto.** «Añadir carpeta de proyecto» (inicio y Ajustes) guarda la ruta en `proyectos_extra` tras validarla el Guardian (absoluta, existente, no raíz de unidad, sin nombre de secreto, fuera de Knowledge, nombre y carpeta sin repetir). Un proyecto sin `00. CONTEXTO (IA)` usa `CLAUDE.md`, `README.md` y `docs\*.md` como contexto de solo lectura (el pie lo indica). Sin plan: objetivos propios y checks; la llamada de digest que ya existía sugiere hasta 5 objetivos y 8 checks marcados como «sugeridos» (los objetivos sugeridos no se evalúan hasta que los confirmas). No hay Gantt del proyecto sin plan ni se inventan fechas.

## Dónde escribe (y dónde no)

| Qué | Dónde | Cuándo |
|---|---|---|
| Transcripción, notas e insights | `<proyecto>\02. Sesiones (transcripciones)\AAAA-MM-DD-tema.md` (o `apuntes\bandeja\`); proyectos compartidos: `apuntes\sesiones\<proyecto>\` durante la reunión | de forma incremental, tras cada línea |
| Documento final de un proyecto compartido | `<proyecto>\02. Sesiones (transcripciones)\AAAA-MM-DD-tema.md` (se crea la carpeta si falta; nunca sobrescribe) | al cerrar la revisión, salvo «No publicar» |
| Checks de preparación | `apuntes\checks\<proyecto>.json` (local, fuera de git) | al añadir, editar, marcar o cuando el análisis marca |
| Contexto | `<proyecto>\00. CONTEXTO (IA)\NN-nombre.md` (si falta, se crea con las plantillas del kit) y `10-registro-de-cambios.md` | solo tras aceptar el usuario |
| Digest de contexto | `apuntes\cache\` | al empezar la reunión, si cambian los ficheros de origen |
| Consumo | `apuntes\datos\consumo.jsonl` | por llamada, sin contenido de reuniones |

- **El audio nunca se guarda**: solo buffers en memoria que se descartan al transcribir.
- Nunca se escribe en `CLAUDE.md`, `AGENTS.md`, `docs\` ni en Knowledge. Todo pasa por `apuntes/rutas.py`, que valida nombres y rutas (sin path traversal ni enlaces que escapen).
- Nunca se lee ni se envía `.env`, credenciales, `.git`, `node_modules` ni ficheros con pinta de secreto; lectura con tope de tamaño, líneas con pinta de secreto omitidas, secciones «Contactos» fuera.

## Análisis: `claude -p` limpio y barato

Una sola implementación (`apuntes/analisis/claude_cli.py`) detrás de una interfaz mínima (`ModeloLLM`). Cada llamada arranca limpia: `--tools ""`, `--strict-mcp-config`, `--setting-sources ""`, `--disable-slash-commands`, `--no-session-persistence`, system prompt propio y directorio de trabajo neutro. Se quitan `ANTHROPIC_API_KEY` y `ANTHROPIC_AUTH_TOKEN` del entorno del subproceso (hay un test). No se usa `--bare` porque exige clave de API e ignora el login.

Reparto de modelos (en `config.py` / Ajustes, un solo sitio; nunca opus por defecto):

| Tarea | Modelo | Frecuencia |
|---|---|---|
| Digest del contexto en cuatro tramos, uno por perfil (8.400 de entrada con 14.000 caracteres de ficheros, 1.500 de salida medidos) | haiku | una vez por proyecto (y sesión del plan), cacheado por hash de los ficheros (`digest-v5`) |
| Turno de un perfil del equipo y «Analizar ahora» | haiku (`--effort low`, ~2.800 de entrada y 250-500 de salida) | por señales del Monitor (por defecto, ~13-16 por hora, ver «Escucha activa»); «Analizar ahora» llama al de más puntos |
| Análisis periódico generalista (cadencias de 5 y 10 min) | haiku | cada 5/10 min con ≥150 palabras nuevas |
| «Pregúntale» (una pregunta del usuario) | haiku (sonnet si lo eliges para esa pregunta) | una llamada por pregunta, solo si la lanzas |
| Confirmar contradicciones | sonnet | UNA llamada al terminar, con todas las candidatas (tope 8) |
| Resumen final y cambios al contexto | sonnet | una vez por reunión |
| Pulir el resumen final (botón opcional) | opus | solo si pulsas «Pulir con Opus»; una llamada, sin reintentos |

Cada envío lleva solo digest, resumen acumulado (con tope), transcripción nueva ya limpiada en local (muletillas, repeticiones, líneas unidas), notas nuevas y títulos de lo ya emitido. Respuesta JSON compacta con tope de longitud por campo (máx. 3 tarjetas entre todas las categorías). Como máximo un reintento por llamada.

**La transcripción es dato no fiable**: va entre marcas `<<<DATOS …>>>` (los delimitadores falsificados se neutralizan), el prompt prohíbe obedecerla, el modelo no tiene herramientas y nada se escribe sin aceptación explícita.

**Errores**: un fallo de análisis se muestra en la interfaz y nunca detiene la grabación. Si Claude Code no tiene la sesión iniciada o se alcanza el límite del plan, se muestra el motivo, los análisis automáticos se pausan y «Analizar ahora» los reactiva.

## Captura de pantalla

La ventana se excluye con `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` por defecto, para que los insights no salgan al compartir pantalla. Interruptor en Ajustes (o `--mostrar-en-captura`).

## Modo reunión

Botón «Modo reunión» en la cabecera de la reunión (solo con ventana nativa; con `--sin-ventana` no aparece). Compacta la app para seguir una reunión de Teams con ella delante: la ventana pasa a ocupar el área de trabajo del monitor en que está (sin tapar la barra de tareas), siempre encima (`HWND_TOPMOST`), sin marco, y `SetWindowRgn` deja solo dos paneles: el hueco central no es de la app, se ve lo que haya debajo y recibe los clics. A 1440 px CSS son 360, 720 y 360 px; los divisores se arrastran (o se mueven con las flechas, Mayús = 64 px) y la medida se recuerda (`modo_reunion` en `datos\config.json`). Panel izquierdo: transcripción. Panel derecho: mandos (REC, cronómetro, Analizar ahora, Salir, opacidad 60-100 %) y, con un solo scroll, insights, objetivos y checks. La orquestación queda plegada a su línea de 32 px. Por debajo de 1280 px CSS de ancho de pantalla no cabe el hueco: un único panel lateral a la derecha con pestañas Transcripción / Insights. Salir (o terminar la reunión) devuelve tamaño, posición, marco y estado de maximizada; la grabación y el análisis no se tocan. La región se recalcula al cambiar el tamaño de la ventana, al arrastrar un divisor y con la escala DPI (`GetDpiForWindow`; si la página informa de otro `devicePixelRatio`, manda ese). La exclusión de captura (`0x11`) se mantiene dentro del modo y tras salir. La opacidad usa `WS_EX_LAYERED` por ventana entera; si no se viera el efecto, `OPACIDAD_SOPORTADA = False` en `apuntes/ventana.py` oculta el control.

Cálculo puro en `apuntes/modo_reunion.py` (tests en `tests/test_modo_reunion.py`); Win32 en `apuntes/ventana.py`; interfaz en `web/modo-reunion.js`; API `GET /api/ventana`, `POST /api/ventana/modo-reunion`, `POST /api/ventana/opacidad`. Prueba con la ventana real, sin audio ni tokens: `.venv\Scripts\python.exe pruebas\probar_modo_reunion.py [--captura]` (instancia propia localizada por PID, modelo falso, datos temporales).

## Seguridad del servidor

Solo `127.0.0.1`, token aleatorio por ejecución (cabecera `X-Token` / query del WebSocket), comprobación de `Host` y `Origin`, CSP estricta.

## Estructura

```
app.py                  entrada (argumentos, servidor, ventana)
apuntes/rutas.py        Guardian: rutas permitidas, secretos, escritura atómica
apuntes/contexto.py     proyectos, selección local de contexto, plantillas del kit
apuntes/planes.py       plan de sesiones (ficha, Gantt, checks base), estado de objetivos, estados del panel de contexto
apuntes/checks.py       checks de preparación: almacén local, bloqueo manual, marcas automáticas, resumen
planes/  sesiones/  checks/   planes, transcripciones de proyectos compartidos y checks (locales, fuera de git)
apuntes/cambios.py      cambios propuestos: validación, aplicación, diff, registro
apuntes/analisis/       interfaz, claude -p, prompts y orquestación
apuntes/gestor.py       sesión, análisis periódico, revisión
apuntes/audio.py        captura (pyaudiowpatch) y segmentación por silencios
apuntes/transcripcion.py  faster-whisper
apuntes/servidor.py     FastAPI + WebSocket;  apuntes/ventana.py  pywebview + afinidad y parpadeo de la barra de tareas
apuntes/llamadas.py     aviso de llamada de Teams: lee en el registro de Windows si Teams usa el micro y propone grabar (nunca graba sola)
apuntes/disparo.py      cadencias (equipo, 5, 10, manual) y las señales locales base (sin LLM)
apuntes/equipo/         el equipo: monitor.py (vigía local), perfiles.py (4 prompts cortos, digest por tramos, normalización), director.py (turnos, estado), presupuesto.py, definiciones.py
apuntes/orquesta.py     eventos reales de cada tarea (agente, modelo, tramo, duración, tokens, resultado) y traza por análisis
web/                    HTML, CSS y JS sin build: app.js (base), agentes.js (orquestación, Registro, pie, medidores), reunion.js (transcripción, objetivos, insights), revision.js (diff y «Pulir con Opus»); fuentes/ y marca/ (DM Sans y logo, locales: funciona sin internet)
pruebas/                proyecto ficticio, transcripciones, scripts de medición; servir_modelo_falso.py (la app con un modelo falso y latencia, para ver y medir la interfaz)
web/equipo.js, equipo.css   Monitor, tarjetas de perfil, Definiciones y Minuto a minuto de la pantalla de reunión
web/sesion.js, sesion.css, escucha.js   banda «Sesión» (Gantt de la reunión, componente GanttSesion), anotaciones propias, Pregúntale, objetivos propios, carpeta añadida
tests/                  equipo (monitor, perfiles, presupuesto, definiciones y flujo completo), disparo, escucha activa, layout del Gantt de la sesión (Edge sin cabeza), reglas de rutas, claude -p, cambios, flujo completo con modelo falso
```

## Consumo medido (texto ficticio, `claude -p` con la licencia)

Una llamada periódica con el mismo prompt (haiku), `pruebas\comparar_arranque.py`:

| Arranque | Tokens de entrada | Salida | Coste de lista |
|---|---|---|---|
| Limpio (esta app) | 2.749 | 855 | 0,0006 USD |
| `claude -p` por defecto | 67.550 | 3.390 | 0,0079 USD |

Reunión simulada de 60 min a 10 min de cadencia (`pruebas\ejecutar_simulacion.py pruebas\reunion-60min.txt --cadencia 10 --velocidad 12`, 173 líneas, ~6.600 palabras sintéticas): 11 llamadas, ≈47.400 tokens de entrada (incluida caché) y ≈10.900 de salida; haiku 6 llamadas (≈9.300 de salida), sonnet 5 llamadas (4 confirmaciones de contradicciones y el resumen final). El digest salió de la caché. Cada llamada queda en `datos\consumo.jsonl` (sin contenido) y la interfaz muestra el total de la sesión en el pie.

### Consumo con plan de sesiones (medido)

Misma transcripción ficticia de 12 min (`pruebas\reunion-datos-beta.txt`, 24 líneas) sobre el proyecto compartido de pruebas, con `claude -p` y `pruebas\ejecutar_simulacion.py --compartido --sesion-plan S1|otra` (S1 = 4 objetivos; «otra» = sin plan). Tokens de entrada incluida caché / salida, 2 llamadas periódicas (haiku) + 1 confirmación y el resumen final (sonnet):

| Medición | Con plan (S1) | Sin plan («otra») |
|---|---|---|
| Ronda A: periódicas | 8.369 / 1.867 | 7.910 / 2.770 |
| Ronda B: periódicas | 8.602 / 3.511 | 7.783 / 2.246 |
| Ronda B: total de la reunión (digest en caché) | 15.308 / 4.936 | 14.494 / 3.869 |
| Digest (una vez por sesión del plan) | 3.519 / 2.395 | 2.827 / 1.673 |

Lo que añade el plan a la entrada es ≈ +230 a +410 tokens por llamada periódica (regla de objetivos en el system prompt y el bloque de objetivos; +6 % a +10 %) y ≈ +5 % al total de la reunión, sin llamadas nuevas. La salida varía más entre repeticiones del mismo caso (la ronda A salió más corta con plan y la B más larga) que por el plan: el campo `o` son ~20-40 tokens. El digest con plan cuesta una vez más por sesión (la clave de caché incluye la sesión); una sesión repetida sale de la caché.

### Consumo con checks (medido)

`pruebas\medir_checks.py` (haiku con `claude -p`, texto ficticio del proyecto Beta, 5 min de transcripción, objetivos de S1, 2 repeticiones por caso). Entrada incluida caché / salida, media:

| Caso | Entrada | Salida |
|---|---|---|
| Objetivos, sin checks | 3.410 | 1.346 |
| Objetivos + 6 checks abiertos | 3.730 (+320) | 1.994 |
| Objetivos + 15 checks abiertos (tope) | 3.890 (+480, +14 %) | 2.136 |

La entrada es determinista (regla de checks en el system prompt ≈ 370 caracteres más y ≈ 15 líneas compactas); la salida varía mucho entre repeticiones (1.160 a 2.361 con 6 checks) porque depende de cuántos checks marca el modelo (~40 tokens por marca con minuto y cita) y del resto del JSON. Sin plan, sin checks abiertos o con todos bloqueados o hechos, el prompt es idéntico al de antes. Los sugeridos van en la llamada de digest que ya existía (una vez por sesión del plan, cacheada).

### Prueba con una reunión real de 73 min (TR2) y correcciones

`pruebas\probar_tr2.py` pasa la transcripción real (en `pruebas\_real\`, fuera de git) contra una copia local del contexto, con haiku/sonnet por `claude -p`, y NO acepta los cambios que propone. Antes y después de las correcciones (la copia del contexto de la segunda columna no tiene `09-peticiones` ni `11-bitacora`, porque se actualizaron después de la reunión). Coste = «coste de referencia» que informa el CLI:

| | Antes | Después, pasada 1 | Después, pasada 2 |
|---|---|---|---|
| haiku: llamadas / entrada / salida / coste | 18 / 143.438 / 38.759 / 0,044 | 16 / 140.527 / 36.082 / 0,041 | 15 (digest en caché) / 127.436 / 35.473 / 0,037 |
| sonnet: llamadas / entrada / salida / coste | 13 / 34.298 / 2.135 / 0,128 | 2 / 20.543 / 2.556 / 0,105 | 2 / 20.623 / 2.050 / 0,094 |
| llamadas de confirmación de contradicciones | 12 | 1 | 1 |
| tarjetas (total) | 71 | 40 | 37 |
| decisión / pendiente / pregunta / riesgo / contradicción | 16 / 14 / 26 / 14 / 1 | 2 / 18 / 6 / 11 / 3 | 2 / 20 / 5 / 7 / 3 |
| máx. tarjetas en un análisis | 5 | 3 | 3 |
| mayor minuto citado en tarjetas | 82:32 (defecto de la prueba) | 73:03 | 73:03 |
| cambios propuestos al contexto | 0 | 2 | 1 |

Qué fallaba y por qué:

- **El resumen final olvidaba el principio.** `acumular_resumen` descartaba lo más antiguo al pasar de 2.500 caracteres (17 tramos de ~400 caracteres: solo sobrevivían los últimos ~6, de los minutos 44+) y el final solo recibía ese resumen y las últimas 40 tarjetas recortadas a 70 caracteres. Ahora recibe el resumen de toda la reunión (cada tramo con su minuto) y todas las tarjetas compactas, más la duración.
- **Cero cambios al contexto.** `ficheros_para_final` puntuaba por el número bruto de términos compartidos: los ficheros enormes (`09-peticiones`, `11-bitacora`, `13-guion…`) ganaban siempre por tamaño, así que el modelo veía ficheros que ya contenían lo hablado (o nada relacionado) y devolvía `[]`; ni siquiera veía el alcance (`03`). Ahora pondera por rareza, divide por el tamaño del vocabulario, envía hasta 4 ficheros con un extracto de las secciones cercanas (más el índice de encabezados) y el prompt pide comparar decisiones y ficheros; si no hay cambios, explica el motivo (`sin_cambios`). La variación entre repeticiones venía de que el modelo trabajaba con ficheros irrelevantes distintos cada vez.
- **Objetivos parados.** El prompt pedía incluir solo los objetivos cuyo estado cambiaba y la app solo completaba un minuto vacío. Ahora cada análisis reevalúa los no cubiertos (se les envía estado y minuto) y el minuto pasa a la evidencia más reciente.
- **Minutos de más (82:32 en una reunión de 73:09).** Defecto de la prueba: el simulador sumaba 0,4 s por palabra a cada línea aunque tuviera marca de tiempo y los minutos se iban desplazando. Ahora una marca de tiempo manda, el reloj de la simulación se detiene en su última línea y la app acota cualquier minuto inventado por el modelo al final del tramo analizado.
- **Salida de haiku.** Casi todo es razonamiento, no JSON (ver abajo).

**Razonamiento de haiku.** `pruebas\probar_thinking.py --real` (prompt periódico con plan, 8 repeticiones por variante, tramo real de 5 min): con `MAX_THINKING_TOKENS=0` (lo que había) salida media 2.384 tokens de los que 1.969 son razonamiento; añadiendo además `CLAUDE_CODE_DISABLE_ADAPTIVE_THINKING=1` y `--settings {"alwaysThinkingEnabled": false}`, 2.392 y 2.021. Es decir, **ninguno de los ajustes probados lo quita**: la variable no tiene efecto medible con este modelo y prompt (con un prompt más simple, sin plan, el razonamiento aparece en torno a la mitad de las llamadas y tampoco es controlable). El JSON útil son ~300-400 tokens. Lo único que bajó con certeza es la longitud del JSON (≈1.120 → ≈740 caracteres por respuesta con el formato compacto y los topes por campo): la salida media por llamada periódica queda en ≈2.100 (pasada 1) y ≈2.365 (pasada 2) frente a ≈2.140 antes. El digest salió con 4.642 tokens de salida (2.186 de razonamiento) frente a los 2.395 de antes. Cada llamada registra ahora `razonamiento` en `consumo.jsonl`.

**Pulir con Opus** (reunión ficticia, `ejecutar_simulacion.py --pulir`): una llamada, entrada 2.455 tokens (incluida caché), salida 599, coste de referencia 0,032 USD.

## Velocidad de transcripción (faster-whisper `small`, CPU int8, 6 hilos)

Con voz sintética de Windows (23 s de audio, `pruebas\medir_velocidad.py`): entre 0,56× y 1,66× tiempo real según la pasada (mediana 0,77×) con la máquina cargada. Es decir, **no es holgadamente más rápido que el tiempo real**: si hablan los dos flujos a la vez puede acumularse retraso (el pie y el panel lo indican). Si ocurre, usa `base` o `tiny` en Ajustes.

Ese dato es de la época de `whisper_beam` 1. Desde noviembre el defecto es **beam 5** y `temperature=(0.0, 0.2, 0.4)` (faster-whisper reintenta con la siguiente temperatura si un tramo falla por compresión o log-prob). Medido de nuevo con voz sintética (Helena, 33 s en 3 tramos, `small`, 6 hilos, 3 rondas): beam 1 + 0,0 dio de media 4,19× (3,14-5,04×) y beam 5 + tupla 3,23× (2,96-3,64×); la velocidad varía mucho con la carga de la máquina. Si se acumula retraso, vuelve a `whisper_beam` 1 en `datos\config.json`.

El `initial_prompt` de Whisper lleva el tema, un vocabulario del proyecto (siglas y nombres propios extraídos en local de los ficheros de contexto ya cargados; `vocabulario_transcripcion` en la config va primero) y la última frase conservada de la MISMA fuente (micro o reunión), con un tope de ~480 caracteres (~200 tokens). Si el resultado de un tramo es una copia del prompt, se descarta.
