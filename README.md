# Sistema INLEARNING · Reserva de Cancha Deportiva

Sistema web semanal para gestionar reservas de una cancha deportiva por alumnos, con validación de códigos y panel administrativo.

## Mejoras incluidas

- Diseño renovado en **naranja y blanco**, inspirado en la identidad visual de INLEARNING.
- Vista semanal de lunes a viernes, de 08:00 a 22:00.
- Fútbol: mínimo 5 y máximo 8 alumnos.
- Vóley: mínimo 8 y máximo 12 alumnos.
- Validación de códigos contra la base de alumnos.
- Un código no puede repetirse dentro de una misma reserva.
- **Un alumno no puede inscribirse más de una vez el mismo día.**
- **Un alumno no puede inscribirse en dos días consecutivos.**
- No se puede reservar un horario ya reservado o cerrado por administración.
- Cancelación administrativa sin borrar el registro histórico.
- Cierre y reapertura de horarios desde el panel administrador.
- Panel con:
  - alumnos registrados;
  - reservas activas;
  - reservas canceladas;
  - porcentaje de ocupación semanal;
  - histograma de uso por día;
  - histograma de uso por hora;
  - distribución por deporte;
  - detalle de alumnos por reserva.
- Exportación de registros a CSV.
- Importación de base de alumnos desde `.xlsx` o `.csv`.
- Compatible con **SQLite en local** y **PostgreSQL en Render**.

## Ejecutar localmente

1. Instala dependencias:

```bash
pip install -r requirements.txt
```

2. Ejecuta:

```bash
python app.py
```

3. Abre:

```text
http://127.0.0.1:5000
```

## Administrador local

Por defecto:

```text
Usuario: admin
Clave: admin123
```

Para producción, cambia obligatoriamente estos valores usando variables de entorno.

## Base de alumnos

El archivo inicial se encuentra en:

```text
data/base_alumnos.xlsx
```

Formato esperado:

```text
NombreCompleto | DNI | Código
```

Si PostgreSQL está vacío, el sistema carga automáticamente esta base inicial.

# Publicar en Render con PostgreSQL

## 1. Subir el proyecto a GitHub

Sube el contenido de esta carpeta a un repositorio.

## 2. Crear PostgreSQL en Render

En Render:

1. Crea un nuevo **PostgreSQL**.
2. Copia la variable o URL de conexión interna que Render proporciona.

## 3. Crear el Web Service

Conecta el repositorio de GitHub y usa:

**Build Command**

```bash
pip install -r requirements.txt
```

**Start Command**

```bash
python app.py
```

## 4. Variables de entorno

Configura estas variables en el Web Service:

```text
DATABASE_URL=<Internal Database URL de PostgreSQL>
ADMIN_USER=<usuario administrador>
ADMIN_PASS=<contraseña segura>
```

Render agrega `PORT` automáticamente.

## PostgreSQL / SQLite

- Si `DATABASE_URL` existe, el sistema usa PostgreSQL.
- Si `DATABASE_URL` no existe, usa `data/cancha.db` para desarrollo local.
- No necesitas modificar el código para cambiar entre ambos.

## Importante sobre Render

No uses SQLite como base definitiva en Render, porque el disco del Web Service puede reiniciarse y perder cambios. Para producción utiliza PostgreSQL mediante `DATABASE_URL`.
