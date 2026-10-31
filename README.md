# Control de Tardanzas

Aplicación web (Python + Streamlit + PostgreSQL/Supabase) para registrar las tardanzas de un
voluntariado, calcular automáticamente las penalidades y controlar su cobranza. Funciona desde
un único enlace en computadora, tablet o celular, y toda la información se guarda en una base de
datos central: lo que registras en un dispositivo aparece en los demás.

## Qué hace

| Sección | Para qué sirve |
|---|---|
| **Inicio** | Indicadores (tardanzas, personas, generado, recaudado, pendiente, % de cobranza) y gráficos por periodo. |
| **Registrar tardanza** | Eliges la fecha, la actividad y la hora de inicio **una sola vez**, agregas a una lista a todos los que llegaron tarde (el retraso y la penalidad se calculan solos), revisas la lista y la guardas con un botón: se guardan todos juntos o ninguno. Admite fechas anteriores. |
| **Historial de actividades** | **Por fecha:** eliges un día y ves a todos los que llegaron tarde con su deuda; marcas la casilla «Pagado» de quienes pagaron y confirmas. Además: todas las tardanzas con filtros (voluntario, fecha, rango, mes, actividad, estado), detalle por actividad y por voluntario, corrección y anulación con motivo. |
| **Control de pagos** | Deudas pendientes, búsqueda por nombre, saldos por persona, pago de una o varias deudas a la vez (Yape, Plin, transferencia, efectivo), pagos parciales e historial de pagos con anulación. |
| **Voluntarios** | Alta, búsqueda, edición de nombres, historial y totales (generado, pagado, pendiente) de cada persona. |
| **Reportes y Excel** | Consulta por fecha, actividad, mes, rango, voluntario o estado, con descarga en **Excel y PDF**. Botón **«Descargar todos los registros en Excel»** (5 hojas), PDF completo y copia de seguridad. |
| **Configuración** | Nombre de la app, hora de inicio predeterminada, tramos y montos de penalidad, recálculo opcional e historial de cambios. |

### Reglas de penalidad

La penalidad depende del **tramo** en el que llega la persona (no se multiplica por minuto).
Los tramos se expresan en minutos de retraso desde la hora de inicio de la actividad:

| Llegada (inicio 9:00) | Retraso | Penalidad |
|---|---|---:|
| antes de las 9:10 | 0–9 min | S/ 0 |
| 9:10 a 9:19 | 10–19 min | S/ 1 |
| 9:20 a 9:29 | 20–29 min | S/ 2 |
| 9:30 en adelante | 30+ min | S/ 3 |

Llegar antes o justo a la hora de inicio no es tardanza y no se registra.

### Cómo se protege la información

- **Historial intacto:** cada tardanza guarda una copia de las reglas y la hora de inicio con que se
  calculó. Cambiar la configuración solo afecta a los registros nuevos. Si de verdad quieres aplicar
  las reglas nuevas a registros antiguos, usa *Configuración → Recalcular registros* (muestra una
  vista previa y pide confirmación; nunca toca deudas ya pagadas).
- **Sin duplicados:** cada envío del formulario lleva un identificador único; si la conexión falla
  y vuelves a presionar «Guardar», no se crea un segundo registro. Además, una misma persona no
  puede tener dos tardanzas vigentes en la misma actividad, y los nombres se comparan sin importar
  mayúsculas, tildes ni espacios (si escribes un nombre parecido a uno existente, la app te sugiere
  el existente antes de crear uno nuevo).
- **Nada se borra:** corregir o anular deja el registro en el *Historial de cambios* con su motivo.
  Una tardanza con pagos no se puede anular sin anular antes el pago.
- **Pagos solo por el administrador:** una deuda pasa a «Pagado» únicamente cuando registras el pago.
  Un pago menor al saldo queda como pago parcial y la deuda sigue «Pendiente».
- **Fecha de actividad ≠ fecha de registro:** la primera es el día de la actividad; la segunda, el
  momento (hora de Lima) en que se ingresó el dato.

> Según lo solicitado, toda tardanza crea una deuda «Pendiente», incluso si la penalidad es S/ 0.
> Para cerrarla, selecciónala en *Control de pagos* y confirma el pago por S/ 0.00.

---

## 1. Crear la base de datos en Supabase (gratis)

1. Crea una cuenta en <https://supabase.com> y un proyecto nuevo (región sugerida: *South America
   (São Paulo)*). Guarda la contraseña de la base de datos que te pide.
2. En el proyecto, pulsa **Connect** (arriba) y copia la cadena de **Session pooler**. Se ve así:
   ```
   postgresql://postgres.abcdefghijkl:[YOUR-PASSWORD]@aws-0-sa-east-1.pooler.supabase.com:5432/postgres
   ```
   Reemplaza `[YOUR-PASSWORD]` por tu contraseña. Usa el *pooler* (no la conexión directa), porque
   Streamlit Community Cloud solo tiene IPv4.
3. No necesitas crear tablas: la app las crea al conectarse por primera vez. Si prefieres hacerlo a
   mano, pega el contenido de [`schema.sql`](schema.sql) en *SQL Editor* y ejecútalo.

**Respaldos:** Supabase guarda respaldos diarios automáticos en los planes de pago. En el plan
gratuito, descarga cada cierto tiempo el **respaldo completo (.zip)** desde *Reportes y Excel*
(incluye todas las tablas y el historial de cambios) y el Excel completo. Ten en cuenta que Supabase
pausa los proyectos gratuitos tras una semana sin uso; se reactivan desde su panel.

## 2. Crear la contraseña del administrador

La contraseña nunca se escribe en el código. Se guarda como *hash* en los secretos:

```bash
pip install -r requirements.txt
```

```bash
python auth.py "una-contraseña-larga-y-segura"
```

Copia el texto que empieza con `pbkdf2_sha256$...`. (Después de cinco intentos fallidos, el acceso
se bloquea un minuto.)

## 3. Ejecutar en tu computadora

Requiere Python 3.10 o superior.

```bash
pip install -r requirements.txt
```

Crea el archivo `.streamlit/secrets.toml` copiando `.streamlit/secrets.toml.example` y completa:

```toml
DATABASE_URL = "postgresql://postgres.xxxx:TU-CONTRASEÑA@aws-0-sa-east-1.pooler.supabase.com:5432/postgres"
ADMIN_USER = "admin"
ADMIN_PASSWORD_HASH = "pbkdf2_sha256$310000$...."
```

```bash
streamlit run app.py
```

Se abre en <http://localhost:8501>.

**Probar sin Supabase:** usa `DATABASE_URL = "sqlite:///demo.db"` en `secrets.toml` y carga datos
ficticios con `python seed_demo.py` (este script se niega a ejecutarse contra una base que no sea
SQLite, para no ensuciar la real).

## 4. Publicar en internet (Streamlit Community Cloud, gratis)

1. Sube esta carpeta a un repositorio de GitHub (puede ser privado). El archivo
   `.streamlit/secrets.toml` **no** se sube: está en `.gitignore`.
2. Entra a <https://share.streamlit.io>, inicia sesión con GitHub y pulsa **Create app**.
3. Elige el repositorio, la rama y como *Main file path* `app.py`.
4. En **Advanced settings → Secrets** pega el mismo contenido de tu `secrets.toml`
   (`DATABASE_URL`, `ADMIN_USER`, `ADMIN_PASSWORD_HASH`).
5. Pulsa **Deploy**. En uno o dos minutos tendrás un enlace del tipo
   `https://tu-app.streamlit.app` que funciona en cualquier dispositivo.

Para usarla en el celular como si fuera una app: abre el enlace en el navegador y elige
*Agregar a la pantalla de inicio*.

Para cambiar la contraseña, genera un hash nuevo con `python auth.py "nueva"` y reemplaza
`ADMIN_PASSWORD_HASH` en *App settings → Secrets*.

## 5. Pruebas

```bash
pip install pytest
```

```bash
python -m pytest -q
```

Las pruebas usan una base SQLite temporal y verifican: los límites exactos de cada tramo (9:05,
9:09, 9:10, 9:19, 9:20, 9:29, 9:30, 9:45…), el registro consecutivo en una misma actividad,
fechas anteriores, la diferencia entre fecha de actividad y de registro, la prevención de
duplicados, pagos totales y parciales, anulaciones, que el historial conserve su penalidad al
cambiar las reglas, los filtros, el Excel (5 hojas, formatos y filtros) y que cada página se
dibuje sin errores.

## Estructura del proyecto

```
app.py              Aplicación principal, acceso y navegación
auth.py             Inicio de sesión del administrador y generador de hash
config.py           Configuración, reglas de penalidad, cálculo de retraso y zona horaria (Lima)
database.py         Conexión, tablas, transacciones e historial de cambios
volunteers.py       Gestión de voluntarios
tardiness.py        Actividades, registro, corrección, anulación y recálculo de tardanzas
payments.py         Pagos, anulaciones y estado de las deudas
reports.py          Filtros, indicadores y resúmenes
excel_export.py     Excel con formato y respaldo completo (.zip)
pdf_export.py       Reportes en PDF
ui.py               Estilos, tablas y filtros compartidos
views/              Una página por sección del menú
seed_demo.py        Datos ficticios para pruebas locales
schema.sql          Esquema SQL (opcional)
tests/              Pruebas automáticas
```

## Notas

- La sesión del administrador dura mientras la pestaña esté abierta; al recargar la página se
  vuelve a pedir la contraseña.
- La hora de referencia es la de Lima (America/Lima), aunque el servidor esté en otro país.
- Cada página consulta la base de datos al abrirse, así que los cambios hechos desde otro
  dispositivo se ven al cambiar de sección o recargar.
