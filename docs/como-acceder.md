# Cómo acceder a la aplicación

Hoy la aplicación **no está publicada en ninguna parte**: el código está en el repositorio, pero
no hay ningún servidor encendido, así que todavía no existe una dirección web que abrir. Esto es
lo que falta, según lo que quieras hacer.

---

## Opción A — Verla en tu computador (5 minutos, sin cuentas ni costo)

Es la forma de mirarla funcionando hoy mismo. Sirve en tu PC y también desde tu celular si está
en la misma red WiFi.

**Necesitas:** Python 3.11 o superior instalado ([python.org/downloads](https://www.python.org/downloads/);
en Windows marca *"Add Python to PATH"* durante la instalación).

1. Descarga el repositorio: en GitHub, rama `claude/obra-avance-reportes-prompt-afk7in` →
   botón verde **Code → Download ZIP** → descomprimir.
2. Entra a la carpeta y ejecuta:
   - **Windows**: doble clic en `iniciar.bat`
   - **Mac / Linux**: abre la terminal en esa carpeta y escribe `./iniciar.sh`
3. Espera a que diga `Abre en el navegador: http://127.0.0.1:8000` y abre esa dirección.

El script crea el entorno, instala lo necesario y carga la obra de referencia desde la plantilla.
La primera vez demora un par de minutos; las siguientes, segundos.

**Para verla en el celular** (mismo WiFi): averigua la IP de tu computador (`ipconfig` en Windows,
`ifconfig` en Mac) y abre en el teléfono `http://192.168.x.x:8000`. Así se ve el formato móvil,
aunque todavía no se puede *instalar* como app: para eso hace falta HTTPS, y eso llega con la
opción B.

---

## Opción B — Publicarla en internet y usarla como app en Android

Aquí sí queda una dirección permanente, entra desde cualquier lugar y se instala en el teléfono.
Son **dos servicios**, porque Netlify solo publica la parte visual:

| Parte | Dónde va | Por qué |
|---|---|---|
| Interfaz (lo que se ve) | **Netlify** | Publica sitios estáticos y da HTTPS gratis |
| API + base de datos | **Render** | Netlify no ejecuta Python ni guarda datos |

**Necesitas:** una cuenta gratuita en [Render](https://render.com) y otra en
[Netlify](https://netlify.com), ambas conectadas a tu GitHub.

### B.1 — Publicar la API en Render (primero, porque Netlify necesita su dirección)

1. Render → **New → Blueprint** → elige este repositorio.
2. Render lee el archivo `render.yaml` y propone crear el servicio `obra-api` y la base de datos
   `obra-db`. Confirma.
3. Cuando termine, copia la dirección que te da, del estilo
   `https://obra-api.onrender.com`. Comprueba que responde abriendo
   `https://obra-api.onrender.com/salud` → debe decir `{"estado":"ok"}`.
4. Carga los datos iniciales: en Render, pestaña **Shell** del servicio, escribe `python seed.py`.

> El plan gratuito de Render duerme el servicio tras un rato sin uso: la primera carga después de
> unas horas puede tardar ~30 segundos. Con el plan pagado más bajo eso desaparece.

### B.2 — Publicar la interfaz en Netlify

1. Netlify → **Add new site → Import an existing project** → elige este repositorio y la rama
   `claude/obra-avance-reportes-prompt-afk7in`.
2. No cambies nada de la configuración: Netlify lee `netlify.toml` y ya sabe qué hacer.
3. Antes de desplegar, en **Site settings → Environment variables**, agrega:

   | Variable | Valor |
   |---|---|
   | `API_URL` | la dirección de Render, por ejemplo `https://obra-api.onrender.com` |

4. **Deploy**. Al terminar te da una dirección tipo `https://tu-sitio.netlify.app`. Esa es la
   aplicación.
5. Vuelve a Render y agrega la variable `ORIGENES_PERMITIDOS` con esa dirección de Netlify.

### B.3 — Instalarla en el teléfono

Abre la dirección de Netlify en Chrome en el Android → menú **⋮ → Instalar aplicación** (o el
botón **Instalar app** de la cabecera). Queda con su icono en el escritorio, abre a pantalla
completa y sigue funcionando sin señal mostrando los últimos datos cargados.

Si además la quieres en Google Play, se empaqueta la misma aplicación con Bubblewrap: los pasos
están en [`despliegue-netlify-android.md`](despliegue-netlify-android.md).

---

## Antes de dársela a otras personas

Con la opción B la aplicación queda **abierta en internet: cualquiera con la dirección entra y ve
todo**, porque todavía no tiene inicio de sesión. Para uso interno de prueba puede bastar; antes
de compartirla con el mandante o con la gerencia hay que agregar:

1. **Inicio de sesión y roles** — los roles ya están definidos en el diseño (terreno, oficina
   técnica, finanzas, mandante en solo lectura); falta implementar el login. Es lo primero
   pendiente.
2. **Migraciones (Alembic)** — para poder cambiar el modelo de datos sin recrear la base.
3. **Respaldos** de la base de datos en Render.

Si prefieres no exponerla todavía, la opción A dentro de la oficina cubre la revisión y las
pruebas sin ningún riesgo.

---

## Resumen

| Quiero… | Qué hago | Qué necesito |
|---|---|---|
| Verla funcionando hoy | `iniciar.sh` / `iniciar.bat` | Python instalado |
| Verla en mi celular en la oficina | Lo anterior + entrar por la IP del computador | Mismo WiFi |
| Una dirección permanente e instalarla en Android | Render + Netlify | Dos cuentas gratuitas |
| Dársela al equipo o al mandante | Lo anterior + inicio de sesión | Falta implementar el login |
