"""Genera una transcripción SINTÉTICA de 60 minutos (texto ficticio, sin datos de cliente).

    .venv\\Scripts\\python.exe pruebas\\generar_reunion_60min.py   ->  pruebas\\reunion-60min.txt
"""
import random
from pathlib import Path

random.seed(7)
PERSONAS = ["Marta", "Luis", "Ana", "Carlos", "Elena"]
TEMAS = ["el calendario de disponibilidad", "el informe de ocupación", "los permisos de usuario", "el catálogo de hoteles",
         "la carga de reservas históricas", "el entorno de pruebas", "la pantalla de alta de grupos", "las notificaciones por correo",
         "el rendimiento de las consultas", "la formación de los comerciales", "el plan de pruebas", "la migración de datos"]
DETALLES = [
    "ha revisado los casos de uso y cree que faltan dos escenarios de cancelación parcial",
    "propone dividir el trabajo en tres entregas pequeñas para poder enseñar avances cada semana",
    "recuerda que en algunos hoteles el proceso actual se hace a mano con hojas de cálculo distintas",
    "ha medido los tiempos de respuesta y están dentro de lo esperado salvo en los informes más pesados",
    "explica que habrá que decidir cómo se tratan las reservas que cambian de fechas a última hora",
    "pide que se documente bien el criterio de cálculo para que operaciones pueda validarlo",
    "comenta que el equipo del cliente todavía no tiene claro quién será el responsable funcional",
    "sugiere hacer una demostración corta al principio de cada comité para ver la evolución",
    "avisa de que la próxima semana habrá menos disponibilidad por vacaciones del equipo",
    "indica que los datos de ejemplo que se enviaron tenían algunas columnas con formatos mezclados",
]
MULETILLAS = ["Eh,", "O sea,", "Bueno,", "Pues,", "Mmm,", ""]
NUCLEO = {
    90: ("reunion", "Arrancamos el seguimiento de este mes. El orden del día es el piloto, el calendario, los permisos y el informe semanal."),
    300: ("reunion", "Queda decidido que el piloto se mantiene con dos hoteles para el veinte de enero, sin adelantarlo."),
    420: ("yo", "Yo me encargo de enviar el acta de este comité el viernes y de actualizar el plan con las fechas nuevas."),
    700: ("reunion", "Hay un riesgo claro: el catálogo de hoteles sigue sin llegar y sin él no podemos cargar el calendario de disponibilidad."),
    900: ("reunion", "El cliente pide ahora que se incluya la integración con SAP para facturación dentro de la primera fase."),
    940: ("yo", "Eso estaba fuera de alcance, lo acordamos en el kick off como evolutivo. Habría que valorar el impacto antes de aceptarlo."),
    1250: ("reunion", "Luis se compromete a entregar la estimación de la integración con SAP el próximo viernes."),
    1500: ("reunion", "Se acuerda que cada hotel tendrá hasta cinco usuarios en lugar de tres, sujeto a revisar licencias."),
    1900: ("yo", "Pregunta abierta: quién del cliente validará los datos del informe semanal cada lunes, porque no está definido."),
    2300: ("reunion", "Decidimos que el informe de ocupación se publicará los lunes a las siete de la mañana."),
    2700: ("reunion", "Marta avisa de que el calendario de disponibilidad no estará hasta el quince de diciembre como pronto."),
    3000: ("reunion", "Otro riesgo: si el go live se retrasa a abril, coincide con la temporada alta y el cliente no podrá formar a los comerciales."),
    3300: ("yo", "Me comprometo a preparar el borrador del cambio de alcance para el comité del martes."),
    3500: ("reunion", "Resumiendo: piloto el veinte de enero, estimación de SAP el viernes, catálogo el miércoles y cambio de alcance al comité."),
}


def main():
    lineas, t, i = [], 5, 0
    while t < 3590:
        quien = "Micro" if random.random() < 0.28 else "Reunión"
        clave = next((k for k in NUCLEO if t <= k < t + 27), None)
        if clave is not None:
            f, tx = NUCLEO.pop(clave)
            lineas.append((t, "Micro" if f == "yo" else "Reunión", tx))
        else:
            p, tema, det = random.choice(PERSONAS), random.choice(TEMAS), random.choice(DETALLES)
            mul = random.choice(MULETILLAS)
            tx = f"{mul} sobre {tema}, {p} {det}. Y además {random.choice(DETALLES)}."
            lineas.append((t, quien, tx.replace("  ", " ").strip()))
        t += random.randint(16, 26)
        i += 1
    out = ["# Reunión sintética de 60 minutos (texto generado, sin datos de cliente)"]
    out += [f"[{s // 60:02d}:{s % 60:02d}] {q}: {tx}" for s, q, tx in lineas]
    destino = Path(__file__).with_name("reunion-60min.txt")
    destino.write_text("\n".join(out) + "\n", encoding="utf-8")
    palabras = sum(len(tx.split()) for _, _, tx in lineas)
    print(f"{destino.name}: {len(lineas)} líneas, {palabras} palabras")


main()
