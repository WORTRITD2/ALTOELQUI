"use strict";

const API = (window.CONFIG && window.CONFIG.API_URL) || "";
const estado = { obraId: null, presupuestoId: null, fecha: null, obra: null, cartera: null };

const $ = (sel) => document.querySelector(sel);
const pesos = (v) => "$" + Math.round(Number(v || 0)).toLocaleString("es-CL");
const pesosCortos = (v) => {
  const n = Math.round(Number(v || 0));
  if (Math.abs(n) >= 1e9) return "$" + (n / 1e9).toFixed(2).replace(".", ",") + " mil M";
  if (Math.abs(n) >= 1e6) return "$" + (n / 1e6).toFixed(1).replace(".", ",") + " M";
  return pesos(n);
};
const pct = (v, d = 2) => (Number(v || 0) * 100).toFixed(d) + "%";
const num = (v) => Number(v || 0).toLocaleString("es-CL", { maximumFractionDigits: 2 });
const hoy = () => new Date().toISOString().slice(0, 10);

// --------------------------------------------------------------------------
// Acceso a la API, con caché para funcionar sin conexión
// --------------------------------------------------------------------------
async function api(ruta, opciones = {}) {
  const url = API + "/api" + ruta;
  const esLectura = !opciones.method || opciones.method === "GET";
  try {
    const r = await fetch(url, { headers: { "Content-Type": "application/json" }, ...opciones });
    if (!r.ok) {
      let detalle = r.statusText;
      try {
        detalle = (await r.json()).detail || detalle;
      } catch (_) {}
      throw new Error(detalle);
    }
    const datos = r.status === 204 ? null : await r.json();
    if (esLectura) guardarCache(ruta, datos);
    $("#sin-conexion").classList.add("oculto");
    return datos;
  } catch (e) {
    if (esLectura) {
      const cache = leerCache(ruta);
      if (cache !== null) {
        $("#sin-conexion").classList.remove("oculto");
        return cache;
      }
    }
    throw e;
  }
}

function guardarCache(ruta, datos) {
  try {
    localStorage.setItem("cache:" + ruta, JSON.stringify({ t: Date.now(), datos }));
  } catch (_) {}
}
function leerCache(ruta) {
  try {
    const crudo = localStorage.getItem("cache:" + ruta);
    return crudo ? JSON.parse(crudo).datos : null;
  } catch (_) {
    return null;
  }
}

function avisar(texto, esError = false) {
  const el = $("#aviso");
  el.textContent = texto;
  el.className = "aviso" + (esError ? " error" : "");
  clearTimeout(avisar.t);
  avisar.t = setTimeout(() => el.classList.add("oculto"), 6000);
}

// --------------------------------------------------------------------------
// Presentación
// --------------------------------------------------------------------------
function tabla(columnas, filas, opciones = {}) {
  if (!filas || !filas.length) return '<p class="vacio">Sin datos para mostrar.</p>';
  const encabezado = columnas.map((c) => `<th class="${c.n ? "n" : ""}">${c.titulo}</th>`).join("");
  const cuerpo = filas
    .map((f) => {
      const clase = opciones.clase ? opciones.clase(f) : "";
      const celdas = columnas
        .map(
          (c, i) =>
            `<td class="${c.n ? "n" : ""}${i === 0 ? " principal" : ""}" ` +
            `data-etiqueta="${c.titulo}">${c.valor(f) ?? ""}</td>`
        )
        .join("");
      return `<tr class="${clase}">${celdas}</tr>`;
    })
    .join("");
  return `<table><thead><tr>${encabezado}</tr></thead><tbody>${cuerpo}</tbody></table>`;
}

const kpi = (etiqueta, valor, pie = "", clase = "") =>
  `<div class="kpi ${clase}"><div class="etiqueta">${etiqueta}</div>
   <div class="valor">${valor}</div><div class="pie">${pie}</div></div>`;

const pastilla = (texto) => `<span class="pastilla ${texto}">${(texto || "").replace(/_/g, " ")}</span>`;

const barra = (valor, referencia) =>
  `<div class="barra-avance"><span style="width:${Math.min(Math.max(valor, 0) * 100, 100)}%"></span>` +
  (referencia !== undefined
    ? `<i style="position:absolute;top:-2px;bottom:-2px;left:${Math.min(referencia * 100, 100)}%;
        width:2px;background:#5b6b7c;display:block"></i>`
    : "") +
  `</div>`;

function claseSemaforo(s) {
  return { VERDE: "verde", AMARILLO: "amarillo", ROJO: "rojo" }[s] || "";
}

// --------------------------------------------------------------------------
// Arranque
// --------------------------------------------------------------------------
async function iniciar() {
  const obras = await api("/obras");
  const sel = $("#selector-obra");
  sel.innerHTML = obras.map((o) => `<option value="${o.id}">${o.nombre}</option>`).join("");
  if (!obras.length) {
    avisar("No hay obras cargadas. Ejecuta seed.py o crea una desde la API.", true);
    return;
  }
  sel.onchange = () => cargarObra(Number(sel.value));
  $("#fecha-corte").onchange = () => {
    estado.fecha = $("#fecha-corte").value;
    refrescarVista();
  };
  await cargarObra(Number(obras[0].id));
}

async function cargarObra(id) {
  estado.obraId = id;
  $("#selector-obra").value = String(id);
  const detalle = await api(`/obras/${id}`);
  estado.obra = detalle;
  estado.presupuestoId = detalle.presupuesto ? detalle.presupuesto.id : null;

  const eps = await api(`/obras/${id}/estados-pago`);
  const corte = eps.length ? eps[eps.length - 1].fecha_corte : detalle.fecha_inicio || hoy();
  estado.fecha = corte;
  $("#fecha-corte").value = corte;
  $("#semanal-desde").value = detalle.fecha_inicio || corte;
  $("#semanal-hasta").value = corte;
  $("#ep-fecha").value = corte;
  $("#ind-desde").value = detalle.fecha_inicio || corte;
  $("#ind-hasta").value = corte;

  await cargarCatalogoParametros();
  await cargarCapitulosFiltro();
  refrescarVista();
}

// --------------------------------------------------------------------------
// Navegación (escritorio + móvil sincronizados)
// --------------------------------------------------------------------------
function irA(vista) {
  document.querySelectorAll("#pestanas button, #nav-movil button").forEach((b) => {
    b.classList.toggle("activa", b.dataset.vista === vista);
  });
  document.querySelectorAll(".vista").forEach((v) => v.classList.remove("activa"));
  $("#vista-" + vista).classList.add("activa");
  window.scrollTo({ top: 0, behavior: "instant" });
  refrescarVista();
}

document.querySelectorAll("#pestanas button, #nav-movil button").forEach((b) => {
  b.onclick = () => irA(b.dataset.vista);
});

function vistaActiva() {
  const activo = document.querySelector("#pestanas button.activa, #nav-movil button.activa");
  return activo ? activo.dataset.vista : "panel";
}

function refrescarVista() {
  const acciones = {
    panel: cargarPanel,
    presupuesto: cargarPresupuesto,
    semanal: cargarSemanal,
    "estados-pago": cargarEstadosPago,
    parametros: cargarParametros,
    indicadores: cargarIndicadores,
    validaciones: cargarValidaciones,
  };
  const fn = acciones[vistaActiva()];
  if (fn) fn().catch((e) => avisar(e.message, true));
}

// --------------------------------------------------------------------------
// PANEL DE GERENCIA
// --------------------------------------------------------------------------
async function cargarPanel() {
  const cartera = await api(`/panel/cartera?fecha=${estado.fecha}`);
  estado.cartera = cartera;
  const t = cartera.totales;

  $("#cartera-kpis").innerHTML = [
    kpi("Obras", t.obras, `${t.en_rojo} con atraso relevante`, t.en_rojo ? "rojo" : "verde"),
    kpi("Contratado", pesosCortos(t.contrato), "todas las obras"),
    kpi("Ejecutado", pesosCortos(t.ejecutado), `avance ${pct(t.avance_ponderado)}`),
    kpi("Facturado", pesosCortos(t.facturado), "estados de pago aprobados"),
    kpi("Por facturar", pesosCortos(t.por_facturar), "ejecutado sin cobrar",
        Number(t.por_facturar) > 0 ? "amarillo" : ""),
    kpi("Con alertas", t.con_alertas, "requieren atención", t.con_alertas ? "amarillo" : "verde"),
  ].join("");

  $("#cartera-obras").innerHTML = cartera.obras
    .map((o) => {
      if (o.sin_presupuesto) {
        return `<button class="tarjeta-obra" onclick="seleccionarObra(${o.id})">
          <h3>${o.nombre}</h3><p class="meta">Sin presupuesto importado</p></button>`;
      }
      const sel = o.id === estado.obraId ? " seleccionada" : "";
      return `<button class="tarjeta-obra${sel}" onclick="seleccionarObra(${o.id})">
        <h3>${o.nombre}</h3>
        <p class="meta">${o.mandante || ""}${o.ubicacion ? " · " + o.ubicacion : ""}</p>
        <div style="display:flex;align-items:center;gap:.5rem">
          <strong style="font-size:1.15rem">${pct(o.avance_pct)}</strong>
          ${pastilla(o.semaforo)}
        </div>
        ${barra(o.avance_pct, o.programado_pct)}
        <div class="cifras">
          <div><span>Contrato</span><b>${pesosCortos(o.contrato)}</b></div>
          <div><span>Ejecutado</span><b>${pesosCortos(o.ejecutado)}</b></div>
          <div><span>SPI</span><b>${o.spi === null ? "—" : o.spi.toFixed(2)}</b></div>
        </div>
        ${o.alertas.length ? `<ul class="alertas">${o.alertas.map((a) => `<li>${a}</li>`).join("")}</ul>` : ""}
      </button>`;
    })
    .join("");

  await cargarPanelObra();
}

window.masPartidas = function () {
  cargarPanelObra(estado.panelPartidas.length).catch((e) => avisar(e.message, true));
};

window.seleccionarObra = async function (id) {
  await cargarObra(id);
  irA("panel");
};

const esMovil = () => window.matchMedia("(max-width: 759px)").matches;
const porPagina = () => (esMovil() ? 25 : 60);

function filtrosActuales(desplazamiento = 0) {
  const p = new URLSearchParams({ fecha: estado.fecha });
  const capitulo = $("#f-capitulo").value;
  const semaforo = $("#f-semaforo").value;
  const est = $("#f-estado").value;
  const texto = $("#f-texto").value.trim();
  const orden = $("#f-orden").value;
  if (capitulo) p.set("capitulo", capitulo);
  if (semaforo) p.set("semaforo", semaforo);
  if (est) p.set("estado", est);
  if (texto) p.set("texto", texto);
  if (orden) p.set("orden", orden);
  p.set("limite", String(porPagina()));
  p.set("desplazamiento", String(desplazamiento));
  return p.toString();
}

async function cargarPanelObra(desplazamiento = 0) {
  if (!estado.presupuestoId) {
    $("#panel-partidas").innerHTML = '<p class="vacio">La obra no tiene presupuesto importado.</p>';
    return;
  }
  const d = await api(`/panel/obras/${estado.obraId}?${filtrosActuales(desplazamiento)}`);
  estado.panelPartidas = desplazamiento ? estado.panelPartidas.concat(d.partidas) : d.partidas;
  const k = d.kpis;

  $("#panel-obra-titulo").textContent = d.obra.nombre;
  $("#panel-obra-sub").textContent =
    `${d.obra.mandante || ""} · corte ${d.fecha}` + (k.semana ? ` · semana ${k.semana}` : "");

  $("#panel-kpis").innerHTML = [
    kpi("Avance real", pct(k.avance_pct), `programado ${pct(k.programado_pct)}`),
    kpi("Desviación", k.desviacion_pp.toFixed(1) + " p.p.", "real − programado",
        k.desviacion_pp >= 0 ? "verde" : "rojo"),
    kpi("SPI", k.spi === null ? "—" : k.spi.toFixed(2), "1,00 = en programa",
        k.spi === null ? "" : k.spi >= 1 ? "verde" : k.spi >= 0.8 ? "amarillo" : "rojo"),
    kpi("Ejecutado", pesosCortos(k.ejecutado), `de ${pesosCortos(k.contrato)}`),
    kpi("Atraso", k.atraso_semanas + " sem", "respecto del programa"),
    kpi("Término proyectado", k.proyeccion_termino || "—", "al ritmo actual"),
  ].join("");

  $("#panel-curva").innerHTML = `<div class="grafico">${curvaS(d.curva_s)}</div>`;

  const r = d.resumen_filtro;
  $("#panel-resumen-filtro").innerHTML =
    `<strong>${r.partidas}</strong> partidas seleccionadas · ` +
    `${pct(r.incidencia)} del contrato · avance <strong>${pct(r.avance_pct)}</strong> · ` +
    `${pesosCortos(r.monto_ejecutado)} de ${pesosCortos(r.monto_contratado)}` +
    (Number(r.monto_atraso) > 0
      ? ` · <span style="color:#b42318">atraso ${pesosCortos(r.monto_atraso)}</span>`
      : "") +
    ` · ${r.sin_iniciar} sin iniciar, ${r.terminadas} terminadas` +
    "";

  const columnas = [
    { titulo: "Ítem", valor: (p) => p.codigo },
    { titulo: "Descripción", valor: (p) => p.descripcion },
    { titulo: "Un.", valor: (p) => p.unidad || "" },
    { titulo: "Contratado", n: true, valor: (p) => num(p.cantidad) },
    { titulo: "Ejecutado", n: true, valor: (p) => num(p.ejecutado) },
    {
      titulo: "Avance",
      n: true,
      valor: (p) => `${pct(p.avance_pct)}${barra(p.avance_pct, p.programado_pct)}`,
    },
    { titulo: "Programado", n: true, valor: (p) => pct(p.programado_pct) },
    { titulo: "Monto ejecutado", n: true, valor: (p) => pesos(p.monto_avance) },
    { titulo: "Atraso", n: true, valor: (p) => (Number(p.monto_atraso) ? pesos(p.monto_atraso) : "—") },
    { titulo: "Peso", n: true, valor: (p) => pct(p.incidencia) },
    { titulo: "Estado", valor: (p) => pastilla(p.semaforo) },
  ];
  // En móvil se muestran las columnas que importan para supervisar; el resto
  // sigue disponible en escritorio y en la exportación a Excel.
  const visibles = esMovil()
    ? columnas.filter((c) => !["Un.", "Contratado", "Programado", "Peso"].includes(c.titulo))
    : columnas;

  const faltan = d.paginacion.total - estado.panelPartidas.length;
  $("#panel-partidas").innerHTML =
    tabla(visibles, estado.panelPartidas) +
    (faltan > 0
      ? `<div style="padding:.8rem;text-align:center">
           <button class="boton secundario" onclick="masPartidas()">
             Mostrar ${Math.min(faltan, porPagina())} más (quedan ${faltan})</button></div>`
      : "");

  $("#panel-capitulos").innerHTML =
    `<div class="panel-cabecera"><h2>Avance por capítulo</h2></div>` +
    tabla(
      [
        { titulo: "Capítulo", valor: (c) => c.capitulo },
        { titulo: "Contrato", n: true, valor: (c) => pesosCortos(c.contrato) },
        { titulo: "Ejecutado", n: true, valor: (c) => pesosCortos(c.avance) },
        { titulo: "Avance", n: true, valor: (c) => `${pct(c.pct)}${barra(c.pct)}` },
        { titulo: "Peso", n: true, valor: (c) => pct(c.incidencia) },
      ],
      d.capitulos
    );
}

async function cargarCapitulosFiltro() {
  if (!estado.presupuestoId) return;
  try {
    const caps = await api(`/panel/obras/${estado.obraId}/capitulos`);
    $("#f-capitulo").innerHTML =
      '<option value="">Todos los capítulos</option>' +
      caps
        .map((c) => `<option value="${c.codigo}">${c.codigo} — ${c.descripcion}</option>`)
        .join("");
  } catch (_) {}
}

["#f-capitulo", "#f-semaforo", "#f-estado", "#f-orden"].forEach((sel) => {
  $(sel).onchange = () => cargarPanelObra().catch((e) => avisar(e.message, true));
});
let tecleo;
$("#f-texto").oninput = () => {
  clearTimeout(tecleo);
  tecleo = setTimeout(() => cargarPanelObra().catch((e) => avisar(e.message, true)), 350);
};
$("#f-limpiar").onclick = () => {
  ["#f-capitulo", "#f-semaforo", "#f-estado"].forEach((s) => ($(s).value = ""));
  $("#f-texto").value = "";
  $("#f-orden").value = "incidencia";
  cargarPanelObra().catch((e) => avisar(e.message, true));
};

// --------------------------------------------------------------------------
// Curva S
// --------------------------------------------------------------------------
function curvaS(datos) {
  if (!datos || datos.length < 2)
    return '<p class="vacio">Genera la programación para ver la curva S.</p>';
  const w = 900, h = 240, m = { t: 14, r: 14, b: 30, l: 42 };
  const x = (i) => m.l + (i * (w - m.l - m.r)) / (datos.length - 1);
  const y = (v) => h - m.b - v * (h - m.t - m.b);
  const linea = (clave, color, guion) =>
    `<path d="${datos
      .map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[clave]).toFixed(1)}`)
      .join(" ")}" fill="none" stroke="${color}" stroke-width="2.5"
      ${guion ? 'stroke-dasharray="5 4"' : ""} stroke-linejoin="round"/>`;
  const ejes = [0, 0.25, 0.5, 0.75, 1]
    .map(
      (v) =>
        `<line x1="${m.l}" x2="${w - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="#e6eaf0"/>
         <text x="${m.l - 6}" y="${y(v) + 3}" text-anchor="end">${v * 100}%</text>`
    )
    .join("");
  const paso = Math.max(1, Math.ceil(datos.length / 10));
  const etiquetas = datos
    .map((d, i) =>
      i % paso === 0 || i === datos.length - 1
        ? `<text x="${x(i)}" y="${h - 10}" text-anchor="middle">${d.iso.split("-")[1]}</text>`
        : ""
    )
    .join("");
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" role="img"
     aria-label="Curva S: avance programado contra avance real">${ejes}
    ${linea("programado", "#8a94a6", true)}${linea("real", "#1f3864", false)}${etiquetas}
    <g transform="translate(${m.l + 6},${m.t + 2})">
      <line x1="0" x2="16" y1="0" y2="0" stroke="#8a94a6" stroke-width="2.5" stroke-dasharray="5 4"/>
      <text x="22" y="3">Programado</text>
      <line x1="96" x2="112" y1="0" y2="0" stroke="#1f3864" stroke-width="2.5"/>
      <text x="118" y="3">Real</text>
    </g></svg>`;
}

// --------------------------------------------------------------------------
// Avance vs presupuesto
// --------------------------------------------------------------------------
let filasPresupuesto = [];

async function cargarPresupuesto() {
  const aprobados = $("#solo-aprobados").checked;
  const r = await api(
    `/obras/${estado.obraId}/reportes/presupuesto?fecha=${estado.fecha}&solo_aprobados=${aprobados}`
  );
  $("#descarga-presupuesto").href =
    `${API}/api/obras/${estado.obraId}/reportes/presupuesto.xlsx?fecha=${estado.fecha}`;

  $("#cierre-presupuesto").innerHTML = [
    kpi("Avance", pct(r.avance_pct), `al ${r.fecha_corte}`),
    kpi("Costo directo ejecutado", pesosCortos(r.avance.cd), `de ${pesosCortos(r.contrato.cd)}`),
    kpi("Total ejecutado", pesosCortos(r.avance.total), "con GG, utilidad e IVA"),
    kpi("Contrato", pesosCortos(r.contrato.total), r.contrato.origen || "recalculado"),
  ].join("");

  filasPresupuesto = r.filas;
  pintarPartidas();
  $("#filtro-partidas").oninput = pintarPartidas;

  $("#capitulos").innerHTML = tabla(
    [
      { titulo: "Capítulo", valor: (c) => c.capitulo },
      { titulo: "Contrato", n: true, valor: (c) => pesosCortos(c.contrato) },
      { titulo: "Ejecutado", n: true, valor: (c) => pesosCortos(c.avance) },
      { titulo: "Avance", n: true, valor: (c) => `${pct(c.pct)}${barra(c.pct)}` },
      { titulo: "Incidencia", n: true, valor: (c) => pct(c.incidencia) },
    ],
    r.capitulos
  );

  $("#top-incidencia").innerHTML = tabla(
    [
      { titulo: "Ítem", valor: (f) => f.codigo },
      { titulo: "Descripción", valor: (f) => f.descripcion },
      { titulo: "Incidencia", n: true, valor: (f) => pct(f.incidencia) },
      { titulo: "Avance", n: true, valor: (f) => pct(f.avance_pct) },
    ],
    r.top_incidencia
  );
}

function pintarPartidas() {
  const q = ($("#filtro-partidas").value || "").toLowerCase();
  const filas = q
    ? filasPresupuesto.filter(
        (f) => f.codigo.toLowerCase().includes(q) || f.descripcion.toLowerCase().includes(q)
      )
    : filasPresupuesto;
  $("#tabla-presupuesto").innerHTML = tabla(
    [
      { titulo: "Ítem", valor: (f) => f.codigo },
      { titulo: "Descripción", valor: (f) => f.descripcion },
      { titulo: "Un.", valor: (f) => f.unidad || "" },
      { titulo: "Cantidad", n: true, valor: (f) => num(f.cantidad) },
      { titulo: "P. unitario", n: true, valor: (f) => pesos(f.p_unitario) },
      { titulo: "P. total", n: true, valor: (f) => pesos(f.p_total) },
      { titulo: "Ejecutado", n: true, valor: (f) => num(f.cant_acumulada) },
      { titulo: "Avance", n: true, valor: (f) => pct(f.avance_pct) },
      { titulo: "Monto avance", n: true, valor: (f) => pesos(f.monto_avance) },
      { titulo: "Saldo", n: true, valor: (f) => pesos(f.saldo_monto) },
      { titulo: "Incidencia", n: true, valor: (f) => pct(f.incidencia) },
    ],
    filas
  );
}

$("#solo-aprobados").onchange = () => cargarPresupuesto().catch((e) => avisar(e.message, true));

// --------------------------------------------------------------------------
// Avance vs programa
// --------------------------------------------------------------------------
async function cargarSemanal() {
  const desde = $("#semanal-desde").value || estado.obra.fecha_inicio;
  const hasta = $("#semanal-hasta").value || estado.fecha;
  const r = await api(`/obras/${estado.obraId}/reportes/semanal?desde=${desde}&hasta=${hasta}`);
  $("#descarga-semanal").href =
    `${API}/api/obras/${estado.obraId}/reportes/semanal.xlsx?desde=${desde}&hasta=${hasta}`;

  const s = r.resumen;
  $("#resumen-semanal").innerHTML = [
    kpi("Real acumulado", pct(s.real_acumulado)),
    kpi("Programado acumulado", pct(s.programado_acumulado)),
    kpi("Desviación", s.desviacion_pp.toFixed(2) + " p.p.", "real − programado",
        s.desviacion_pp >= 0 ? "verde" : "rojo"),
    kpi("SPI", s.spi === null ? "—" : s.spi.toFixed(2), "<1 = atrasado",
        s.spi === null ? "" : s.spi >= 1 ? "verde" : s.spi >= 0.8 ? "amarillo" : "rojo"),
    kpi("Atraso", s.atraso_semanas + " sem"),
    kpi("Término proyectado", s.proyeccion_termino || "—"),
  ].join("");

  $("#tabla-semanal").innerHTML = tabla(
    [
      { titulo: "Semana", valor: (f) => f.iso },
      { titulo: "Desde", valor: (f) => f.inicio },
      { titulo: "Hasta", valor: (f) => f.fin },
      { titulo: "Días háb.", n: true, valor: (f) => f.dias_habiles },
      { titulo: "Feriados", valor: (f) => f.feriados.join(", ") },
      { titulo: "Prog. período", n: true, valor: (f) => pct(f.programado_periodo) },
      { titulo: "Real período", n: true, valor: (f) => pct(f.real_periodo) },
      { titulo: "Prog. acum.", n: true, valor: (f) => pct(f.programado_acumulado) },
      { titulo: "Real acum.", n: true, valor: (f) => pct(f.real_acumulado) },
      { titulo: "Δ p.p.", n: true, valor: (f) => f.desviacion_pp.toFixed(2) },
      { titulo: "SPI", n: true, valor: (f) => (f.spi === null ? "—" : f.spi.toFixed(2)) },
      { titulo: "Ejecutado", n: true, valor: (f) => pesos(f.monto_ejecutado_periodo) },
      { titulo: "Estado", valor: (f) => pastilla(f.semaforo) },
    ],
    r.semanas
  );

  $("#tabla-criticas").innerHTML = tabla(
    [
      { titulo: "Ítem", valor: (f) => f.codigo },
      { titulo: "Descripción", valor: (f) => f.descripcion },
      { titulo: "Un.", valor: (f) => f.unidad || "" },
      { titulo: "Programado", n: true, valor: (f) => num(f.cantidad_programada) },
      { titulo: "Ejecutado", n: true, valor: (f) => num(f.cantidad_ejecutada) },
      { titulo: "Avance prog.", n: true, valor: (f) => pct(f.avance_programado) },
      { titulo: "Avance real", n: true, valor: (f) => pct(f.avance_real) },
      { titulo: "Atraso", n: true, valor: (f) => f.atraso_pp.toFixed(1) + " p.p." },
      { titulo: "Monto atraso", n: true, valor: (f) => pesos(f.monto_atraso) },
      { titulo: "Estado", valor: (f) => pastilla(f.semaforo) },
    ],
    r.partidas_criticas
  );
}

$("#btn-semanal").onclick = () => cargarSemanal().catch((e) => avisar(e.message, true));
$("#btn-programacion").onclick = async () => {
  try {
    const r = await api(`/obras/${estado.obraId}/programacion`, {
      method: "POST",
      body: JSON.stringify({ cuadrillas: 1 }),
    });
    avisar(`Programación v${r.version} generada`);
    cargarSemanal();
  } catch (e) {
    avisar(e.message, true);
  }
};

// --------------------------------------------------------------------------
// Estados de pago
// --------------------------------------------------------------------------
async function cargarEstadosPago() {
  const eps = await api(`/obras/${estado.obraId}/estados-pago`);
  $("#lista-eps").innerHTML =
    `<div class="panel"><div class="panel-cabecera"><h2>Estados de pago emitidos</h2></div>` +
    tabla(
      [
        { titulo: "N°", valor: (e) => e.numero },
        { titulo: "Corte", valor: (e) => e.fecha_corte },
        {
          titulo: "Estado",
          valor: (e) => pastilla(e.estado) + (e.provisional ? " " + pastilla("PROVISIONAL") : ""),
        },
        { titulo: "Total período", n: true, valor: (e) => pesos(e.total) },
        { titulo: "Líquido", n: true, valor: (e) => pesos(e.liquido) },
        { titulo: "% acumulado", n: true, valor: (e) => pct(e.pct_acumulado) },
        {
          titulo: "Acciones",
          valor: (e) =>
            `<button class="boton mini" onclick="verEP(${e.id})">Ver</button>
             ${e.estado === "BORRADOR" ? `<button class="boton mini secundario" onclick="aprobarEP(${e.id})">Aprobar</button>` : ""}
             <a class="boton mini secundario" href="${API}/api/estados-pago/${e.id}/xlsx">Excel</a>
             <a class="boton mini secundario" href="${API}/api/estados-pago/${e.id}/imprimir" target="_blank">Imprimir</a>`,
        },
      ],
      eps
    ) +
    `</div>`;
  $("#detalle-ep").innerHTML = "";
}

window.verEP = async function (id) {
  const r = await api(`/estados-pago/${id}`);
  const pe = r.periodo_economico;
  const lineas = [
    ["Costo directo", pe.cd], ["Gastos generales", pe.gg], ["Utilidad", pe.utilidad],
    ["Neto", pe.neto], ["IVA", pe.iva], ["Total del período", pe.total],
    ["Reajuste", pe.reajuste], ["Amortización anticipo", pe.anticipo],
    ["Retención", pe.retencion], ["Multa", pe.multa], ["Líquido a pagar", pe.liquido],
  ];
  $("#detalle-ep").innerHTML = `
    <div class="panel">
      <div class="panel-cabecera">
        <h2>EP N°${r.numero} — corte ${r.fecha_corte} ${pastilla(r.estado)}</h2>
        <span class="nota">Período ${r.periodo.desde || "inicio"} → ${r.periodo.hasta} ·
          acumulado ${pct(r.acumulado.pct)}</span>
      </div>
      ${r.advertencias.filter(Boolean).map((a) => `<p class="leyenda provisional">⚠ ${a}</p>`).join("")}
      <div class="grid-2">
        <div class="scroll-x">${tabla(
          [
            { titulo: "Ítem", valor: (d) => d.codigo },
            { titulo: "Descripción", valor: (d) => d.descripcion },
            { titulo: "Del período", n: true, valor: (d) => num(d.cant_periodo) },
            { titulo: "% acum.", n: true, valor: (d) => pct(d.pct_acumulado) },
            { titulo: "Monto período", n: true, valor: (d) => pesos(d.monto_periodo) },
          ],
          r.detalle
        )}</div>
        <div>
          ${tabla(
            [
              { titulo: "Concepto", valor: (l) => l[0] },
              { titulo: "Monto", n: true, valor: (l) => pesos(l[1]) },
            ],
            lineas
          )}
          <p class="leyenda"><strong>Trazabilidad</strong> (${r.origen_parametros}):<br>
            ${r.pie_trazabilidad.join("<br>")}</p>
        </div>
      </div>
    </div>`;
};

window.aprobarEP = async function (id) {
  try {
    await api(`/estados-pago/${id}/aprobar`, { method: "POST" });
    avisar("Estado de pago aprobado: parámetros e indicadores quedaron congelados");
    cargarEstadosPago();
  } catch (e) {
    avisar(e.message, true);
  }
};

$("#btn-generar-ep").onclick = async () => {
  try {
    const r = await api(`/obras/${estado.obraId}/estados-pago`, {
      method: "POST",
      body: JSON.stringify({
        fecha_corte: $("#ep-fecha").value,
        dias_atraso: Number($("#ep-atraso").value || 0),
      }),
    });
    avisar(`EP N°${r.numero} generado por ${pesos(r.periodo_economico.total)}`);
    cargarEstadosPago();
  } catch (e) {
    avisar(e.message, true);
  }
};

// --------------------------------------------------------------------------
// Parámetros
// --------------------------------------------------------------------------
let catalogo = [];

async function cargarCatalogoParametros() {
  catalogo = await api("/parametros/catalogo");
  $("#param-clave").innerHTML = catalogo
    .map((c) => `<option value="${c.clave}">${c.etiqueta} (${c.clave})</option>`)
    .join("");
  $("#param-clave").onchange = cargarHistorialParametro;
}

async function cargarParametros() {
  const vigentes = await api(`/obras/${estado.obraId}/parametros?fecha=${estado.fecha}`);
  const historial = await api(`/obras/${estado.obraId}/parametros/historial`);
  const porClave = {};
  historial.forEach((h) => {
    (porClave[h.clave] = porClave[h.clave] || []).push(h);
  });

  const filas = catalogo.map((c) => ({
    ...c,
    valor: vigentes[c.clave],
    vigencias: (porClave[c.clave] || []).length,
    desde: (porClave[c.clave] || []).filter((h) => h.vigente_desde <= estado.fecha).slice(-1)[0],
  }));

  $("#tabla-parametros").innerHTML = tabla(
    [
      { titulo: "Parámetro", valor: (f) => f.etiqueta },
      { titulo: "Clave", valor: (f) => `<code>${f.clave}</code>` },
      { titulo: "Valor vigente", n: true, valor: (f) => (f.tipo === "PORCENTAJE" ? pct(f.valor) : f.valor) },
      { titulo: "Desde", valor: (f) => (f.desde ? f.desde.vigente_desde : "defecto del sistema") },
      { titulo: "Vigencias", n: true, valor: (f) => f.vigencias },
      { titulo: "Descripción", valor: (f) => f.descripcion || "" },
    ],
    filas
  );
  if (!$("#param-desde").value) $("#param-desde").value = estado.fecha;
  cargarHistorialParametro();
}

async function cargarHistorialParametro() {
  const clave = $("#param-clave").value;
  const historial = await api(`/obras/${estado.obraId}/parametros/historial?clave=${clave}`);
  $("#historial-parametro").innerHTML = tabla(
    [
      { titulo: "Valor", valor: (h) => h.valor },
      { titulo: "Desde", valor: (h) => h.vigente_desde },
      { titulo: "Hasta", valor: (h) => h.vigente_hasta || "vigente" },
      { titulo: "Motivo", valor: (h) => h.motivo || "" },
      { titulo: "Usuario", valor: (h) => h.usuario || "" },
    ],
    historial
  );
}

$("#btn-simular").onclick = async () => {
  try {
    const r = await api(`/obras/${estado.obraId}/parametros/simular`, {
      method: "POST",
      body: JSON.stringify({
        clave: $("#param-clave").value,
        valor: $("#param-valor").value,
        vigente_desde: $("#param-desde").value,
      }),
    });
    $("#resultado-simulacion").innerHTML = `<p class="leyenda">
      Contrato ${pesos(r.contrato_antes)} → <strong>${pesos(r.contrato_despues)}</strong>
      (${pesos(r.delta_contrato)})<br>
      Ejecutado a la fecha ${pesos(r.avance_antes)} → <strong>${pesos(r.avance_despues)}</strong></p>`;
  } catch (e) {
    avisar(e.message, true);
  }
};

$("#form-parametro").onsubmit = async (ev) => {
  ev.preventDefault();
  try {
    await api(`/obras/${estado.obraId}/parametros`, {
      method: "POST",
      body: JSON.stringify({
        clave: $("#param-clave").value,
        valor: $("#param-valor").value,
        vigente_desde: $("#param-desde").value,
        motivo: $("#param-motivo").value,
        documento_respaldo_url: $("#param-doc").value || null,
        usuario: "oficina_tecnica",
      }),
    });
    avisar("Vigencia registrada. Los estados de pago aprobados no se tocan.");
    cargarParametros();
  } catch (e) {
    avisar(e.message, true);
  }
};

// --------------------------------------------------------------------------
// Indicadores
// --------------------------------------------------------------------------
async function cargarIndicadores() {
  const codigo = $("#ind-codigo").value;
  const serie = await api(`/indicadores/${codigo}/serie?limite=40`);
  $("#serie-indicador").innerHTML = tabla(
    [
      { titulo: "Fecha", valor: (f) => f.fecha },
      { titulo: "Valor", n: true, valor: (f) => num(f.valor) },
      { titulo: "Fuente", valor: (f) => f.fuente },
      { titulo: "Estado", valor: (f) => pastilla(f.estado) },
      { titulo: "Nota", valor: (f) => f.nota || "" },
    ],
    serie
  );
  const desde = $("#ind-desde").value || estado.fecha;
  const hasta = $("#ind-hasta").value || estado.fecha;
  const feriados = await api(`/feriados?desde=${desde}&hasta=${hasta}`);
  $("#lista-feriados").innerHTML = tabla(
    [
      { titulo: "Fecha", valor: (f) => f.fecha },
      { titulo: "Feriado", valor: (f) => f.nombre },
      { titulo: "Fuente", valor: (f) => f.fuente },
    ],
    feriados
  );
}

$("#ind-codigo").onchange = () => cargarIndicadores().catch((e) => avisar(e.message, true));

$("#btn-sincronizar").onclick = async () => {
  const codigo = $("#ind-codigo").value;
  $("#estado-sincronizacion").innerHTML = '<p class="leyenda">Consultando la fuente…</p>';
  try {
    const r = await api(
      `/indicadores/sincronizar?codigo=${codigo}&desde=${$("#ind-desde").value}&hasta=${$("#ind-hasta").value}`,
      { method: "POST" }
    );
    $("#estado-sincronizacion").innerHTML = `<p class="leyenda ${r.estado === "ERROR" ? "provisional" : ""}">
      ${r.estado} · fuente ${r.fuente || "ninguna"} · ${r.valores_nuevos} valores nuevos<br>
      ${r.detalle || ""}</p>`;
    cargarIndicadores();
  } catch (e) {
    avisar(e.message, true);
  }
};

$("#form-indicador").onsubmit = async (ev) => {
  ev.preventDefault();
  try {
    await api("/indicadores/manual", {
      method: "POST",
      body: JSON.stringify({
        codigo: $("#man-codigo").value,
        fecha: $("#man-fecha").value,
        valor: $("#man-valor").value,
        nota: $("#man-nota").value,
      }),
    });
    avisar("Valor registrado como carga manual");
    cargarIndicadores();
  } catch (e) {
    avisar(e.message, true);
  }
};

// --------------------------------------------------------------------------
// Validaciones
// --------------------------------------------------------------------------
async function cargarValidaciones() {
  if (!estado.presupuestoId) {
    $("#tabla-validaciones").innerHTML = '<p class="vacio">La obra no tiene presupuesto importado.</p>';
    return;
  }
  const filas = await api(`/presupuestos/${estado.presupuestoId}/validaciones`);
  const cuenta = (s) => filas.filter((f) => f.severidad === s).length;
  $("#resumen-validaciones").innerHTML = [
    kpi("Hallazgos", filas.length),
    kpi("Errores", cuenta("ERROR"), "bloquean la cuadratura", cuenta("ERROR") ? "rojo" : "verde"),
    kpi("Advertencias", cuenta("ADVERTENCIA"), "revisar y confirmar", "amarillo"),
    kpi("Informativos", cuenta("INFO")),
  ].join("");
  $("#tabla-validaciones").innerHTML = tabla(
    [
      { titulo: "Severidad", valor: (f) => pastilla(f.severidad) },
      { titulo: "Regla", valor: (f) => f.regla },
      { titulo: "Ubicación", valor: (f) => f.ubicacion || "" },
      { titulo: "Mensaje", valor: (f) => f.mensaje },
      { titulo: "Original", valor: (f) => f.valor_original || "" },
      { titulo: "Corregido", valor: (f) => f.valor_corregido || "" },
    ],
    filas
  );
}

// --------------------------------------------------------------------------
// PWA: instalación en Android y funcionamiento sin conexión
// --------------------------------------------------------------------------
if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  });
}

let promptInstalacion = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  promptInstalacion = e;
  $("#btn-instalar").classList.remove("oculto");
});
$("#btn-instalar").onclick = async () => {
  if (!promptInstalacion) return;
  promptInstalacion.prompt();
  await promptInstalacion.userChoice;
  promptInstalacion = null;
  $("#btn-instalar").classList.add("oculto");
};
window.addEventListener("appinstalled", () => $("#btn-instalar").classList.add("oculto"));
window.addEventListener("online", () => $("#sin-conexion").classList.add("oculto"));
window.addEventListener("offline", () => $("#sin-conexion").classList.remove("oculto"));

iniciar().catch((e) => avisar(e.message, true));
