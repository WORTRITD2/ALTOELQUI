// Configuración del cliente. En Netlify la reescribe netlify/build.sh a partir
// de la variable de entorno API_URL. Vacío = mismo origen (Netlify hace de proxy
// hacia la API, así el navegador nunca cruza dominios y no hay CORS).
window.CONFIG = { API_URL: "" };
