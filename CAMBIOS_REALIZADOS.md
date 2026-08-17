# Cambios realizados · VIVA v3

## 1. Inicio más centrado y dinámico
- **VIVA** queda centrado como elemento principal.
- Debajo aparece la firma *“Vive tu campus.”*.
- Luego se muestra **“¿Qué quieres hacer hoy?”** también centrado.
- Se agregaron animaciones flotantes a ambos costados: deportes a la izquierda y laboratorios/diseño a la derecha.
- Se añadió un pequeño cierre visual: **Reserva · Participa · VIVE**.

## 2. Opciones del inicio
- Las experiencias actuales se muestran en una sola fila en escritorio cuando hay espacio suficiente.
- La cuadrícula está preparada para acomodar **hasta seis opciones** sin deformar las tarjetas.
- Actualmente existen cinco reservas configuradas: Fútbol, Vóley, Laboratorio Mac, Laboratorio Windows y Aula de Diseño.
- En el inicio se mantienen ocultos los números 105, 210 y 510 para conservar una portada limpia.

## 3. Mejor experiencia en celular
- En pantallas móviles las opciones cambian automáticamente a **una columna vertical**.
- Las tarjetas se vuelven horizontales, más táctiles y fáciles de leer.
- Las animaciones laterales se reposicionan en las esquinas del banner para no tapar el mensaje central.
- Encabezados, navegación, pestañas y tarjetas se adaptan a anchos pequeños.

## 4. Espacios 105, 210 y 510 con mayor presencia
- Al entrar a Laboratorio Mac se muestra un bloque grande **ESPACIO 105**.
- Al entrar a Laboratorio Windows se muestra **ESPACIO 210**.
- Al entrar a Aula de Diseño se muestra **ESPACIO 510**.
- El número también resalta en la pantalla de reserva, confirmación y panel administrador.
- Se mantienen sus datos:
  - Mac 105: aforo 40, desde 09:00.
  - Windows 210: aforo 40, desde 09:00.
  - Diseño 510: aforo 36, desde 11:00.

## 5. Animaciones mejoradas
- Fútbol mantiene animación de pelota.
- Vóley tiene rebote/rotación propia.
- Mac y Windows tienen pulso tecnológico.
- Diseño tiene animación de destello.
- Se agregó un movimiento suave tipo parallax en la portada para equipos con mouse.
- Se respeta `prefers-reduced-motion` para usuarios que desactiven animaciones.

## 6. Administrador
- Los ambientes 105, 210 y 510 ahora se ven con tipografía más grande dentro de las tarjetas de estado.
- Se conserva toda la gestión previa: reservas, aforo, cancelaciones, bloqueos, gráficos y exportación.

## VIVA v4 — salones editables y mapa visual de puestos
- El administrador puede editar los ambientes de Laboratorio Mac, Laboratorio Windows y Aula de Cutting desde el panel.
- Los ambientes se guardan en `settings`, por lo que persisten al reiniciar la aplicación.
- Laboratorio Mac y Windows muestran aforo de 40 puestos con iconos de computadora.
- Aula de Cutting muestra aforo de 36 puestos.
- Se agregó una vista de puestos por día y horario; cada computadora ocupada muestra nombre y código del alumno registrado.
- La portada tiene tarjetas más coloridas por actividad y una pelota de fútbol con tratamiento visual más destacado.

## V5 – Laboratorios y Cutting sin horarios por día
- Laboratorio Mac: 40 computadoras totales visibles, sin tabla de lunes a viernes por horas.
- Laboratorio Windows: 40 computadoras totales visibles, sin tabla de lunes a viernes por horas.
- Aula de Cutting: 36 computadoras totales visibles, sin tabla de lunes a viernes por horas.
- Los tres ambientes muestran arriba: disponible de lunes a viernes, de 9:00 a. m. a 10:00 p. m.
- El aforo se controla como un total del ambiente, no como 40/36 cupos repetidos por cada horario.
- Cada alumno registrado ocupa un icono PC y su nombre/código aparece debajo.
- La gestión de cierre por día/hora del administrador queda solo para Fútbol y Vóley.

## VIVA v6 · Aforo disponible en tiempo real
- En Inicio, Laboratorio Mac, Laboratorio Windows y Aula de Cutting ya no muestran el texto descriptivo inferior.
- Cada tarjeta muestra el aforo disponible real: 40/40/36 al iniciar y disminuye con cada reserva activa.
- El mismo contador dinámico se muestra dentro de cada ambiente y en la pantalla de reserva.
- El mapa de computadoras conserva el total físico, pero destaca como cifra principal el aforo disponible actual.
- Si una reserva es cancelada, el cupo vuelve a sumarse automáticamente porque solo se cuentan reservas ACTIVAS.


## V7 · Estados de reserva más visibles
- En Mac, Windows y Aula Cutting la palabra **Disponible** ahora se muestra más grande y con un **check ✅** al costado.
- Cuando una computadora ya fue reservada, ahora aparece **Ocupado** con una **manito ☝️** resaltada.
- Debajo de cada computadora ocupada se muestra el **nombre del alumno** y su **código**.
- El estilo se aplicó tanto al mapa general del ambiente como a la vista dentro del formulario de reserva.

## V12 - Control administrativo de laboratorios
- El administrador puede cambiar Laboratorio Mac, Laboratorio Windows y Aula Cutting entre Disponible, Cerrado y En mantenimiento.
- Se puede registrar un motivo/aviso visible para los alumnos.
- Cerrado y En mantenimiento bloquean nuevas reservas sin eliminar las reservas ya registradas.
- Inicio, detalle del ambiente, leyenda y mapa de puestos reflejan el estado real.
- Los puestos libres dejan de mostrarse como disponibles cuando el ambiente está cerrado o en mantenimiento.
- Se mantiene la edición de los números/códigos de salón y la contraseña de administrador Welcome05@@.
