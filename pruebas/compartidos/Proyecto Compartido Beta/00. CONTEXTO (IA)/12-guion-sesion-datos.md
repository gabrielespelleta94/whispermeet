# 12 · Guion de la sesión de datos (ficticio)

Preparación de la sesión «Revisión del almacén de datos» del proyecto Beta (datos inventados para pruebas).

## Qué necesitamos saber

- Qué espacio de trabajo y qué inquilino de la plataforma de datos se usarán para el proyecto.
- Qué tablas se replican en el almacén de la calculadora: reservas confirmadas, previsión de ocupación, tarifa pública y habitaciones fuera de servicio.
- Si hay inventario y precios por tipología de habitación para todos los hoteles del piloto.
- Cada cuánto se carga y con qué controles de calidad (recuento de filas, fechas límite, nulos).

## Supuestos de partida

- El almacén corporativo se actualiza cada noche.
- El histórico de reservas llega hasta 2025.
- Las tarifas por tipología están en una tabla separada de las reservas.

## Riesgos

- Si falta el inventario por tipología, la calculadora no puede cotizar habitaciones concretas.
- Una carga que falla en silencio daría precios desactualizados.
