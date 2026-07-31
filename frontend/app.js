"use strict";

const estado = { obraId: null, presupuestoId: null, fecha: null, obra: null };

const $ = (sel) => document.querySelector(sel);
const pesos = (v) =>
  "$" + Math.round(Number(v || 0)).toLocaleString("es-CL", { maximumFractionDigits: 0 });
const pct = (v, d = 2) => (Number(v || 0) * 100).toFixed(d) + "%";
const hoy = () => new Date().toISOString().slice(0, 10);

async function api(ruta, opciones = {}) {
  const r = await fetch("/api" + ruta, {
    headers: { "Content-Type": "application/json" },
    ...opciones,
  });
  if (!r.ok) {
    let detalle = r.statusText;
    try {
      detalle = (await r.json()).detail || detalle;
    } catch (_) {}
    throw new Error(detalle);
  }
  return r.status === 204 ? null : r.json();
}

function avisar(texto, esError = false) {
  const el = $("#aviso");
  el.textContent = texto;
  el.className = "aviso" + (esError ? " error" : "");
  clearTimeout(avisar.t);
  avisar.t = setTimeout(() => el.classList.add("oculto"), 6000);
}

function tabla(columnas, filas, opciones = {}) {
  if (!filas.length) return '<p class="vacio">Sin datos para mostrar.</p>';
  const encabezado = columnas
    .map((c) => `<th class="${c.n ? "n" : ""}">${c.titulo}</th>`)
    .join("");
  const cuerpo = filas
    .map((f) => {
      const clase = opciones.clase ? opciones.clase(f) : "";
      const celdas = columnas
        .map((c) => `<td class="${c.n ? "n" : ""}">${c.valor(f) ?? ""}</td>`)
        .join("");
      return `<tr class="${clase}">${celdas}</tr>`;
    })
    .join("");
  return `<table><thead><tr>${encabezado}</tr></thead><tbody>${cuerpo}</tbody></table>`;
}

const kpi = (etiqueta, valor, pie = "", clase = "") =>
  `<div class="kpi ${clase}"><div class="etiqueta">${etiqueta}</div>
   <div class="valor">${valor}</div><div class="pie">${pie}</div></div>`;

const pastilla = (texto) => `<span class="pastilla ${texto}">${texto}</span>`;

// --------------------------------------------------------------------------
// Arranque
// --------------------------------------------------------------------------
async function iniciar() {
  const obras = await api("/obras");
  const sel = $("#selector-obra");
  sel.innerHTML = obras
    .map((o) => `<option value="${o.id}">${o.nombre}</option>`)
    .join("");
  if (!obras.length) {
    avisar("No hay obras cargadas. Ejecuta seed.py o crea una desde la API.", true);
    return;
  }
  $("#fecha-corte").value = hoy();
  sel.onchange = () => cargarObra(Number(sel.value));
  $("#fecha-corte").onchange = () => {
    estado.fecha = $("#fecha-corte").value;
    refrescarVista();
  };
  await cargarObra(Number(obras[0].id));
}

async function cargarObra(id) {
  estado.obraId = id;
  const detalle = await api(`/obras/${id}`);
  estado.obra = detalle;
  estado.presupuestoId = detalle.presupuesto ? detalle.presupuesto.id : null;
  if (detalle.fecha_inicio) {
    $("#semanal-desde").value = detalle.fecha_inicio;
  }
  // La fecha de corte por defecto es el último estado de pago, o hoy
  const eps = await api(`/obras/${id}/estados-pago`);
  const ultima = eps.length ? eps[eps.length - 1].fecha_corte : hoy();
  $("#fecha-corte").value = ultima;
  $("#semanal-hasta").value = ultima;
  $("#ep-fecha").value = ultima;
  $("#ind-desde").value = detalle.fecha_inicio || ultima;
  $("#ind-hasta").value = ultima;
  estado.fecha = ultima;
  await cargarCatalogoParametros();
  refrescarVista();
}

// --------------------------------------------------------------------------
// Navegación
// --------------------------------------------------------------------------
document.querySelectorAll("#pestanas button").forEach((b) => {
  b.onclick = () => {
    document.querySelectorAll("#pestanas button").forEach((x) => x.classList.remove("activa"));
    document.querySelectorAll(".vista").forEach((x) => x.classList.remove("activa"));
    b.classList.add("activa");
    $("#vista-" + b.dataset.vista).classList.add("activa");
    refrescarVista();
  };
});

function vistaActiva() {
  return document.querySelector("#pestanas button.activa").dataset.vista;
}

function refrescarVista() {
  const acciones = {
    tablero: cargarTablero,
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
// Tablero
// --------------------------------------------------------------------------
async function cargarTablero() {
  const t = await api(`/obras/${estado.obraId}/reportes/tablero?fecha=${estado.fecha}`);
  const spi = t.spi === null ? "—" : t.spi.toFixed(2);
  const claseSpi = t.spi === null ? "" : t.spi >= 1 ? "verde" : t.spi >= 0.8 ? "amarillo" : "rojo";
  $("#kpis").innerHTML = [
    kpi("Avance físico", pct(t.avance_fisico_pct), "ponderado por costo"),
    kpi("Contrato", pesos(t.contrato_total), "con IVA"),
    kpi("Ejecutado", pesos(t.avance_total), `facturado ${pesos(t.facturado)}`),
    kpi("Por facturar", pesos(t.por_facturar), `próximo EP N°${t.proximo_ep}`),
    kpi("SPI", spi, `desviación ${t.desviacion_pp.toFixed(2)} p.p.`, claseSpi),
    kpi(
      "Semana en curso",
      t.semana.iso,
      `${t.semana.dias_habiles} días hábiles` +
        (t.semana.feriados.length ? ` · ${t.semana.feriados.join(", ")}` : "")
    ),
    kpi("Atraso", t.atraso_semanas + " sem", "respecto del programa"),
    kpi("Término proyectado", t.proyeccion_termino || "—", "ritmo últimas 4 semanas"),
  ].join("");

  $("#curva-s").innerHTML = curvaS(t.curva_s);
  $("#criticas-tablero").innerHTML = tabla(
    [
      { titulo: "Ítem", valor: (f) => f.codigo },
      { titulo: "Descripción", valor: (f) => f.descripcion },
      { titulo: "Atraso", n: true, valor: (f) => f.atraso_pp.toFixed(1) + " p.p." },
      { titulo: "Monto", n: true, valor: (f) => pesos(f.monto_atraso) },
    ],
    t.partidas_criticas
  );
  $("#eps-tablero").innerHTML = tabla(
    [
      { titulo: "N°", valor: (e) => e.numero },
      { titulo: "Estado", valor: (e) => pastilla(e.estado) },
      { titulo: "Total", n: true, valor: (e) => pesos(e.total) },
    ],
    t.estados_pago
  );
}

function curvaS(datos) {
  if (!datos || datos.length < 2) return '<p class="vacio">Genera la programación para ver la curva S.</p>';
  const w = 900, h = 260, m = { t: 16, r: 16, b: 34, l: 46 };
  const x = (i) => m.l + (i * (w - m.l - m.r)) / (datos.length - 1);
  const y = (v) => h - m.b - v * (h - m.t - m.b);
  const linea = (clave, color, guion) =>
    `<path d="${datos.map((d, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(d[clave]).toFixed(1)}`).join(" ")}"
      fill="none" stroke="${color}" stroke-width="2" ${guion ? 'stroke-dasharray="5 4"' : ""}/>`;
  const ejes = [0, 0.25, 0.5, 0.75, 1]
    .map(
      (v) =>
        `<line x1="${m.l}" x2="${w - m.r}" y1="${y(v)}" y2="${y(v)}" stroke="#e6eaf0"/>
         <text x="${m.l - 8}" y="${y(v) + 3}" text-anchor="end">${v * 100}%</text>`
    )
    .join("");
  const paso = Math.max(1, Math.ceil(datos.length / 12));
  const etiquetas = datos
    .map((d, i) =>
      i % paso === 0
        ? `<text x="${x(i)}" y="${h - 12}" text-anchor="middle">${d.iso.replace("2025-", "")}</text>`
        : ""
    )
    .join("");
  return `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}">${ejes}
    ${linea("programado", "#8a94a6", true)}${linea("real", "#1f3864", false)}${etiquetas}
    <g transform="translate(${m.l + 8},${m.t + 4})">
      <line x1="0" x2="18" y1="0" y2="0" stroke="#8a94a6" stroke-width="2" stroke-dasharray="5 4"/>
      <text x="24" y="3">Programado</text>
      <line x1="100" x2="118" y1="0" y2="0" stroke="#1f3864" stroke-width="2"/>
      <text x="124" y="3">Real</text>
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
    `/api/obras/${estado.obraId}/reportes/presupuesto.xlsx?fecha=${estado.fecha}`;

  $("#cierre-presupuesto").innerHTML = [
    kpi("Avance", pct(r.avance_pct), `al ${r.fecha_corte}`),
    kpi("Costo directo ejecutado", pesos(r.avance.cd), `de ${pesos(r.contrato.cd)}`),
    kpi("Total ejecutado", pesos(r.avance.total), "con GG, utilidad e IVA"),
    kpi("Contrato", pesos(r.contrato.total), r.contrato.origen || "recalculado"),
  ].join("");

  filasPresupuesto = r.filas;
  pintarPartidas();
  $("#filtro-partidas").oninput = pintarPartidas;

  $("#capitulos").innerHTML = tabla(
    [
      { titulo: "Capítulo", valor: (c) => c.capitulo },
      { titulo: "Contrato", n: true, valor: (c) => pesos(c.contrato) },
      { titulo: "Ejecutado", n: true, valor: (c) => pesos(c.avance) },
      {
        titulo: "Avance",
        n: true,
        valor: (c) =>
          `${pct(c.pct)} <div class="barra-avance"><span style="width:${Math.min(c.pct * 100, 100)}%"></span></div>`,
      },
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
      { titulo: "Cantidad", n: true, valor: (f) => Number(f.cantidad).toLocaleString("es-CL") },
      { titulo: "P. unitario", n: true, valor: (f) => pesos(f.p_unitario) },
      { titulo: "P. total", n: true, valor: (f) => pesos(f.p_total) },
      { titulo: "Ejecutado", n: true, valor: (f) => Number(f.cant_acumulada).toLocaleString("es-CL") },
      { titulo: "Avance", n: true, valor: (f) => pct(f.avance_pct) },
      { titulo: "Monto avance", n: true, valor: (f) => pesos(f.monto_avance) },
      { titulo: "Saldo", n: true, valor: (f) => pesos(f.saldo_monto) },
      { titulo: "Incidencia", n: true, valor: (f) => pct(f.incidencia, 2) },
    ],
    filas,
    { clase: (f) => (f.avance_pct >= 1 ? "nivel-1" : "") }
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
    `/api/obras/${estado.obraId}/reportes/semanal.xlsx?desde=${desde}&hasta=${hasta}`;

  const s = r.resumen;
  const claseSpi = s.spi === null ? "" : s.spi >= 1 ? "verde" : s.spi >= 0.8 ? "amarillo" : "rojo";
  $("#resumen-semanal").innerHTML = [
    kpi("Real acumulado", pct(s.real_acumulado)),
    kpi("Programado acumulado", pct(s.programado_acumulado)),
    kpi("Desviación", s.desviacion_pp.toFixed(2) + " p.p.", "real − programado",
        s.desviacion_pp >= 0 ? "verde" : "rojo"),
    kpi("SPI", s.spi === null ? "—" : s.spi.toFixed(2), "<1 = atrasado", claseSpi),
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
      { titulo: "Programado", n: true, valor: (f) => Number(f.cantidad_programada).toLocaleString("es-CL") },
      { titulo: "Ejecutado", n: true, valor: (f) => Number(f.cantidad_ejecutada).toLocaleString("es-CL") },
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
        { titulo: "Estado", valor: (e) => pastilla(e.estado) + (e.provisional ? " " + pastilla("PROVISIONAL") : "") },
        { titulo: "Total período", n: true, valor: (e) => pesos(e.total) },
        { titulo: "Líquido", n: true, valor: (e) => pesos(e.liquido) },
        { titulo: "% acumulado", n: true, valor: (e) => pct(e.pct_acumulado) },
        {
          titulo: "Acciones",
          valor: (e) =>
            `<button class="boton mini" onclick="verEP(${e.id})">Ver</button>
             ${e.estado === "BORRADOR" ? `<button class="boton mini secundario" onclick="aprobarEP(${e.id})">Aprobar</button>` : ""}
             <a class="boton mini secundario" href="/api/estados-pago/${e.id}/xlsx">Excel</a>
             <a class="boton mini secundario" href="/api/estados-pago/${e.id}/imprimir" target="_blank">Imprimir</a>`,
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
        <div>${tabla(
          [
            { titulo: "Ítem", valor: (d) => d.codigo },
            { titulo: "Descripción", valor: (d) => d.descripcion },
            { titulo: "Del período", n: true, valor: (d) => Number(d.cant_periodo).toLocaleString("es-CL") },
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
    porClave[h.clave] = porClave[h.clave] || [];
    porClave[h.clave].push(h);
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
      {
        titulo: "Valor vigente",
        n: true,
        valor: (f) => (f.tipo === "PORCENTAJE" ? pct(f.valor) : f.valor),
      },
      { titulo: "Desde", valor: (f) => (f.desde ? f.desde.vigente_desde : "defecto del sistema") },
      { titulo: "Vigencias", n: true, valor: (f) => f.vigencias },
      { titulo: "Descripción", valor: (f) => f.descripcion || "" },
    ],
    filas
  );
  $("#param-desde").value = $("#param-desde").value || estado.fecha;
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
      { titulo: "Valor", n: true, valor: (f) => Number(f.valor).toLocaleString("es-CL") },
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

iniciar().catch((e) => avisar(e.message, true));
