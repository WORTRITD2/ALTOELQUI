# Despliegue: Netlify, Android y escalamiento

## La arquitectura, y por qué es así

Netlify publica **sitios estáticos y funciones en JavaScript**. La API de esta aplicación es
Python (FastAPI) y necesita una base de datos persistente, así que **no corre en Netlify**. El
reparto queda así:

```
   Android / navegador
          │
          ▼
   Netlify  ──────────────  frontend (PWA: HTML, JS, CSS, service worker)
      │  /api/*  →  proxy  (regla en frontend/_redirects, generada en el build)
      ▼
   API FastAPI  ─────────  Render / Railway / Fly / VPS  (contenedor Docker)
      │
      ▼
   PostgreSQL
```

El proxy de Netlify es lo que hace que el navegador vea **un solo origen**: el frontend llama a
`/api/...` de su propio dominio y Netlify reenvía a la API. Con eso no hay CORS, la PWA puede
cachear las respuestas y la app instalada en Android funciona igual que en escritorio.

## 1. Publicar el frontend en Netlify

En el repositorio ya están `netlify.toml` y `netlify/build.sh`.

1. **Conectar el repositorio** en Netlify → *Add new site* → *Import an existing project*.
2. Netlify lee `netlify.toml`, así que la configuración ya viene puesta:
   - *Build command*: `bash netlify/build.sh`
   - *Publish directory*: `frontend`
3. **Variable de entorno** (*Site settings → Environment variables*):

   | Variable | Valor | Para qué |
   |---|---|---|
   | `API_URL` | `https://tu-api.onrender.com` | El build genera el proxy `/api/* → API_URL/api/:splat` |

   Sin `API_URL` el sitio se publica igual, pero sin datos: el build lo avisa en el log.
4. *Deploy site*. Cada push a la rama publica una versión nueva.

Lo que hace el build (`netlify/build.sh`): escribe `frontend/config.js` con el origen de la API
(vacío = mismo origen) y `frontend/_redirects` con la regla de proxy más el fallback de SPA. Por
eso el host de la API **no queda escrito en el repositorio**.

## 2. Publicar la API

Con el `backend/Dockerfile` incluido, en Render (o Railway, Fly, un VPS con Docker):

1. *New → Web Service*, apuntando a este repositorio, *Root directory* `backend`.
2. Variables de entorno:

   | Variable | Ejemplo | Nota |
   |---|---|---|
   | `DATABASE_URL` | `postgresql+psycopg://usuario:clave@host/base` | Sin ella usa SQLite, que **no sirve** en hosts con disco efímero |
   | `ORIGENES_PERMITIDOS` | `https://tu-sitio.netlify.app` | Con el proxy de Netlify no es imprescindible, pero conviene cerrarlo |
   | `BCCH_USER` / `BCCH_PASS` | credenciales del Banco Central | Sin ellas la UF/UTM caen al respaldo no oficial |

3. Primera carga de datos: `python seed.py` (o importar la plantilla desde la propia aplicación).

> Con PostgreSQL hay que crear el esquema. Hoy se crea con `create_all` al arrancar; para producción
> corresponde incorporar Alembic, que está anotado como pendiente en el README.

## 3. Instalar en Android

### Como PWA (inmediato, sin tienda)

La aplicación ya cumple los requisitos de instalación: `manifest.webmanifest` con iconos de 192 y
512 px (uno *maskable*), `display: standalone`, service worker y HTTPS (que Netlify da por
defecto).

En el teléfono: abrir el sitio en Chrome → menú **⋮ → Instalar aplicación** (o el botón
**Instalar app** que aparece en la cabecera cuando el navegador lo ofrece). Queda con su icono en
el escritorio, abre a pantalla completa sin barra de navegador y **funciona sin señal**: el
service worker sirve la interfaz y la última respuesta de cada consulta, con un aviso amarillo de
que los datos pueden estar desactualizados — algo que en terreno pasa seguido.

### Como aplicación en Google Play (TWA)

Si se necesita estar en la tienda, se empaqueta la misma PWA en una *Trusted Web Activity*, sin
reescribir nada:

```bash
npm install -g @bubblewrap/cli
bubblewrap init --manifest https://tu-sitio.netlify.app/manifest.webmanifest
bubblewrap build          # genera app-release-signed.aab para Play Console
```

Bubblewrap pide la huella SHA-256 de la clave de firma. Hay que publicar en el sitio el archivo
`frontend/.well-known/assetlinks.json` con esa huella, para que Android confíe en el dominio y no
muestre la barra del navegador:

```json
[{
  "relation": ["delegate_permission/common.handle_all_urls"],
  "target": {
    "namespace": "android_app",
    "package_name": "cl.constructorarcr.obra",
    "sha256_cert_fingerprints": ["<huella SHA-256 de tu clave de firma>"]
  }
}]
```

No se incluye en el repositorio porque depende de una clave que aún no existe.

## 4. Qué se hizo para que escale

**En el servidor, no en el teléfono.** El panel filtra por capítulo, semáforo, estado de
ejecución y texto en la API (`/api/panel/obras/{id}`), y devuelve página por página. El móvil
recibe 25 partidas, no 116 — y en una obra de 2.000 partidas seguirá recibiendo 25.

**Menos columnas en pantalla chica.** La misma tabla se renderiza como tarjetas bajo 760 px y
esconde las columnas que no sirven para supervisar (unidad, cantidad contratada, peso). El dato
completo sigue en escritorio y en la exportación a Excel.

**Caché en dos niveles.** El service worker guarda la última respuesta de cada consulta y
`localStorage` respalda las lecturas: al abrir sin señal la aplicación muestra lo último conocido
en vez de una pantalla en blanco.

**Vista de cartera separada del detalle.** `/api/panel/cartera` responde un resumen por obra —
una consulta liviana— y el detalle pesado solo se pide para la obra que el gerente abre.

## 5. Lo que falta antes de exponerlo a usuarios reales

- **Autenticación y roles.** Los endpoints hoy no piden identidad. Antes de publicar en internet
  hay que poner login (los roles del flujo ya están definidos: terreno, oficina técnica, finanzas,
  mandante) y que el mandante vea solo lectura.
- **Migraciones (Alembic).** Con `create_all`, un cambio de modelo obliga a recrear la base.
- **Índices** en `avance_semanal(obra_id, partida_id, fecha_medicion)` y
  `programacion_semanal(programacion_id, iso_semana)` cuando el volumen crezca.
- **Caché del reporte semanal**: hoy recalcula el avance por cada semana del rango; con obras de
  dos años conviene materializar el acumulado por semana.
