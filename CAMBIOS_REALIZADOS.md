# Cambios realizados

## Diseño
- Nueva interfaz naranja y blanca con marca visual INLEARNING.
- Mejoras responsive para celular, tablet y escritorio.
- Estados visuales claros para disponible, reservado y cerrado.

## Reglas de inscripción
- Un código no puede aparecer dos veces en la misma reserva.
- Un código no puede participar en más de una reserva activa el mismo día.
- Un código no puede participar en reservas de días consecutivos.
- Se mantienen los límites de participantes por deporte.

## Administrador
- Total de alumnos.
- Reservas activas y canceladas.
- Porcentaje de ocupación semanal.
- Histograma por día.
- Histograma por hora.
- Gráfico por deporte.
- Detalle de alumnos por reserva.
- Cancelación conservando el registro histórico.
- Cierre y reapertura de horarios.
- Exportación CSV con estado y datos de cancelación.

## Base de datos / Render
- SQLite se mantiene como modo local.
- PostgreSQL se activa automáticamente si existe `DATABASE_URL`.
- Esquema PostgreSQL creado automáticamente al iniciar.
- Dependencia `psycopg[binary]` agregada a `requirements.txt`.
## Mejora visual de disponibilidad
- Los horarios **Disponibles** se muestran en tarjetas verdes con texto blanco.
- Los horarios **Reservados** se muestran en tarjetas rojas con texto blanco.
- Los horarios cerrados o en mantenimiento se muestran en azul con texto blanco.
- Se agregó una leyenda visual y tarjetas con mejor contraste, sombra y adaptación móvil.
- En el panel de administración, una reserva activa se identifica visualmente como **Reservado**.


- La tarjeta **Disponible** ya no muestra el texto secundario “Reservar”; toda la tarjeta sigue siendo clicable.
- Los bloqueos cuyo motivo contiene “mantenimiento” muestran **⚙ Mantenimiento**; los demás muestran **🔒 Cerrado**.


## Actualización de días de atención
- Se retiró el sábado del calendario de reservas.
- La disponibilidad, bloqueos y estadísticas semanales funcionan de lunes a viernes.
- Los registros históricos de sábado se conservan en la base de datos para no perder información, pero no se muestran ni cuentan en la semana activa.
