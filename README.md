# VIVA · Vive tu campus

**VIVA** transforma el antiguo sistema de “reserva de cancha” en una experiencia de campus con varias actividades:

> ¿Qué quieres hacer hoy?
>
> ⚽ Fútbol · 🏐 Vóley · 🖥️ Laboratorio Mac · ▦ Laboratorio Windows · ✦ Aula de Diseño
>
> **Reserva. Participa. VIVE.**

Actualmente hay **cinco experiencias de reserva configuradas**. La interfaz de escritorio quedó preparada para admitir una sexta opción sin rediseñar la portada.

## Experiencia principal

- Inicio ordenado y centrado como **VIVA** → *Vive tu campus.* → **¿Qué quieres hacer hoy?**.
- Animaciones flotantes a ambos costados del mensaje principal.
- Tarjetas dinámicas inmediatamente debajo del banner para elegir la actividad.
- En escritorio las experiencias se acomodan en una sola fila; la cuadrícula admite hasta seis opciones.
- En celular las tarjetas cambian automáticamente a una columna vertical tipo app.
- Cada opción tiene un símbolo visual relacionado y una transición VIVA.
- Fútbol, Vóley, laboratorios y Diseño cuentan con animaciones diferenciadas durante la transición.
- Calendario de **lunes a viernes**, con horario independiente por actividad.
- Los ambientes **105, 210 y 510** resaltan en grande al entrar al detalle, reserva, confirmación y administración.

## Deportes

### Fútbol
- Horarios: 08:00 a 22:00.
- Reserva grupal: mínimo 5 y máximo 8 alumnos.

### Vóley
- Horarios: 08:00 a 22:00.
- Reserva grupal: mínimo 8 y máximo 12 alumnos.

### Reglas deportivas
- Un código no puede repetirse dentro de una reserva.
- Un alumno no puede participar más de una vez en un mismo día deportivo.
- Un alumno no puede participar en dos días deportivos consecutivos.
- Fútbol y Vóley comparten la cancha, por lo que un mismo horario deportivo no puede reservarse dos veces.

## Laboratorios

### Laboratorio Mac
- Espacio: **105**.
- Horarios: 09:00 a 22:00.
- Aforo: **40 alumnos por horario**.

### Laboratorio Windows
- Espacio: **210**.
- Horarios: 09:00 a 22:00.
- Aforo: **40 alumnos por horario**.

En el inicio se muestran solo los nombres **Laboratorio Mac** y **Laboratorio Windows**; los ambientes 105 y 210 se muestran al entrar y en el panel administrador.

### Mecanismo de reserva de laboratorios
- El alumno ingresa su código.
- El sistema valida el código y muestra su nombre.
- Cada reserva consume 1 cupo.
- La disponibilidad baja automáticamente de 40 a 39, 38, etc.
- No se aplican las restricciones deportivas de “una vez por día” ni “días consecutivos”.
- Se evita únicamente reservar dos veces el mismo código en el mismo laboratorio, día y horario.

## Aula de Diseño

Se agregó como quinta experiencia con el mismo mecanismo de cupos de los laboratorios.

- Horarios: **11:00 a 22:00**.
- Aforo: **36 alumnos por horario**.
- Espacio: **510**.
- En la pantalla de inicio se muestra solo **Aula de Diseño**; el número 510 aparece en el detalle de reserva y en administración.

## Panel administrador

El administrador ahora puede visualizar y gestionar en un solo panel:

- Fútbol.
- Vóley.
- Laboratorio Mac 105.
- Laboratorio Windows 210.
- Aula de Diseño 510.
- Total de alumnos registrados.
- Reservas activas y canceladas.
- Cupos/participantes registrados.
- Uso por día y por hora.
- Reservas por actividad.
- Estado de uso de cada espacio.
- Cierre y reapertura de horarios por actividad.
- Detalle de alumnos por reserva.
- Importación del padrón desde `.xlsx` o `.csv`.
- Exportación semanal a CSV con actividad y espacio.

## Base de datos

El sistema sigue siendo compatible con:

- **SQLite** para desarrollo local.
- **PostgreSQL** para Render.

La migración automática elimina la antigua restricción que hacía único cualquier horario y crea una restricción especial solo para la cancha deportiva. Esto permite que los laboratorios acepten varias reservas hasta completar su aforo.

## Ejecutar localmente

```bash
pip install -r requirements.txt
python app.py
```

Luego abre:

```text
http://127.0.0.1:5000
```

## Administrador local

Por defecto:

```text
Usuario: admin
Clave: admin123
```

Para producción configura:

```text
DATABASE_URL=<Internal Database URL de PostgreSQL>
ADMIN_USER=<usuario administrador>
ADMIN_PASS=<contraseña segura>
```

Render agrega `PORT` automáticamente.

## Base de alumnos

Archivo inicial:

```text
data/base_alumnos.xlsx
```

Formato esperado:

```text
NombreCompleto | DNI | Código
```

## Publicación en Render

**Build Command**

```bash
pip install -r requirements.txt
```

**Start Command**

```bash
python app.py
```

Para producción usa PostgreSQL mediante `DATABASE_URL`; no se recomienda SQLite como almacenamiento definitivo en Render.
