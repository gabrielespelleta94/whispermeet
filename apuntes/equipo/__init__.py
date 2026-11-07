"""El equipo de agentes: un vigía local (Monitor) y cuatro perfiles Haiku que hablan por turnos (ver DESIGN-equipo.md).

- `perfiles`: prompts cortos, entrada de cada turno y normalización de la respuesta (una llamada real por turno).
- `monitor`: señales, objetivos tocados, definiciones locales, puntuación y elección de turno. Todo local, sin LLM.
- `presupuesto`: ventana deslizante de tokens por hora.
- `definiciones`: panel de definiciones (detección local sustituida por la de la Analista funcional).
"""
