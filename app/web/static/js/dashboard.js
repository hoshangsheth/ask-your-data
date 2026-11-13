/**
 * Dashboard view.
 *   Demo store:       KPI cards and three charts from GET /api/kpis (loaded once).
 *   Uploaded dataset: an overview (tables, rows, columns, file) with a shortcut to ask questions,
 *                     since fixed KPIs only make sense for a known schema.
 *   Both:             "From your questions": the chart of every answered question on this
 *                     dataset (saved-charts.js), newest first, each removable.
 *
 * Exports: loadDashboard()  (called when the view opens and when the dataset changes)
 */

import { getKpis } from "./api.js";
import { drawChart } from "./charts.js";
import { currentDataset } from "./datasets.js";
import { escapeHtml, inr, num, pct, plainNum } from "./format.js";
import { icon } from "./icons.js";
import { clearCharts, listCharts, removeChart } from "./saved-charts.js";

let loaded = false;
const $ = (id) => document.getElementById(id);

function uploadOverview(ds) {
  const rows = ds.tables.reduce((n, t) => n + t.rows, 0);
  const cols = ds.tables.reduce((n, t) => n + t.columns, 0);
  const sizeKb = ds.size_bytes / 1024;
  const size = sizeKb > 1024 ? `${(sizeKb / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(sizeKb))} KB`;
  $("kpi-grid").innerHTML = [
    kpiCard({ ic: "table", labelText: "Tables", value: plainNum(ds.tables.length), sub: ds.tables.map((t) => t.name).join(", ") }),
    kpiCard({ ic: "list", labelText: "Rows", value: plainNum(rows), sub: "Across all tables" }),
    kpiCard({ ic: "database", labelText: "Columns", value: plainNum(cols), sub: "Cleaned and typed on upload" }),
    kpiCard({ ic: "file", labelText: "Source file", value: escapeHtml(ds.file_format.toUpperCase()), sub: `${escapeHtml(ds.filename)} · ${size}` }),
  ].join("");
  $("chart-grid").innerHTML = `
    <div class="card chart-card wide overview-cta">
      <span class="kpi-icon">${icon("sparkles")}</span>
      <div><h3>Charts for your data come from your questions</h3>
      <p class="muted">Ask something like “${escapeHtml(ds.suggestions[0] ?? "What are the totals by category?")}” and the answer includes a chart, table and the SQL behind it.</p></div>
      <a class="btn" href="#ask">${icon("chat")}Ask a question</a>
    </div>`;
  if (listCharts(ds.id).length) $("chart-grid").innerHTML = ""; // their charts are below
}

function timeAgo(ms) {
  const m = Math.round((Date.now() - ms) / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h} h ago`;
  return new Date(ms).toLocaleDateString("en-IN", { day: "numeric", month: "short" });
}

/** "From your questions": one card per answered question that had a chart. */
function renderSaved(ds) {
  const box = $("saved-charts");
  const items = listCharts(ds.id);
  if (!items.length) {
    box.innerHTML = ds.kind === "demo" ? `
      <div class="saved-head"><div><h2>From your questions</h2>
        <p>Charts from the questions you ask on this dataset collect here.</p></div></div>` : "";
    return;
  }
  box.innerHTML = `
    <div class="saved-head">
      <div><h2>From your questions</h2><p>${items.length} chart${items.length === 1 ? "" : "s"} from your answers on ${escapeHtml(ds.name)}</p></div>
      <button class="btn btn-small" data-saved="clear">Clear all</button>
    </div>
    <div class="saved-grid">${items
      .map(
        (c, i) => `<div class="card chart-card saved-card" style="animation-delay:${Math.min(i, 6) * 0.05}s" data-id="${escapeHtml(c.id)}">
          <div class="card-head"><div><h3 title="${escapeHtml(c.question)}">${escapeHtml(c.question)}</h3>
            <div class="saved-when">${timeAgo(c.at)}</div></div>
            <button class="icon-btn saved-remove" data-saved="remove" title="Remove from dashboard" aria-label="Remove from dashboard">${icon("x")}</button></div>
          <div class="chart-box"><canvas></canvas></div>
        </div>`,
      )
      .join("")}</div>`;
  box.querySelectorAll(".saved-card").forEach((card, i) => drawChart(card.querySelector("canvas"), items[i].spec));
  box.onclick = (e) => {
    const action = e.target.closest("[data-saved]")?.dataset.saved;
    if (action === "remove") removeChart(ds.id, e.target.closest(".saved-card").dataset.id);
    if (action === "clear") clearCharts(ds.id);
    if (action) {
      renderSaved(ds);
      if (ds.kind !== "demo") uploadOverview(ds); // bring back the "ask a question" card when empty
    }
  };
}

const DEMO_CHARTS = `
  <div class="card chart-card wide">
    <div class="card-head"><h3>Monthly revenue</h3><span class="muted" id="trend-note"></span></div>
    <div class="chart-box tall"><canvas id="chart-monthly"></canvas></div>
  </div>
  <div class="card chart-card">
    <div class="card-head"><h3>Revenue by region</h3></div>
    <div class="chart-box"><canvas id="chart-region"></canvas></div>
  </div>
  <div class="card chart-card">
    <div class="card-head"><h3>Revenue by category</h3></div>
    <div class="chart-box"><canvas id="chart-category"></canvas></div>
  </div>`;

/** Render the dashboard for the selected dataset. */
export async function loadDashboard() {
  const ds = currentDataset();
  renderSaved(ds);
  if (ds.kind !== "demo") {
    loaded = false; // demo charts must be rebuilt when switching back
    uploadOverview(ds);
    return;
  }
  if (loaded) return;
  $("chart-grid").innerHTML = DEMO_CHARTS;
  await loadDemoKpis();
}

async function loadDemoKpis() {
  await loadDemoKpisInner();
}


function kpiCard({ ic, labelText, value, sub = "", delta = null }) {
  const d = delta == null ? "" : `<span class="delta ${delta >= 0 ? "up" : "down"}">${delta >= 0 ? "▲" : "▼"} ${pct(Math.abs(delta))}</span>`;
  return `<div class="card kpi">
    <div class="kpi-top"><span class="kpi-icon">${icon(ic)}</span>${d}</div>
    <div><div class="kpi-label">${labelText}</div><div class="kpi-value">${value}</div></div>
    ${sub ? `<div class="kpi-sub">${sub}</div>` : ""}
  </div>`;
}

function skeletonCards(n) {
  return Array.from({ length: n }, () => `<div class="card kpi"><div class="skeleton" style="width:40%"></div><div class="skeleton" style="height:26px;width:70%"></div></div>`).join("");
}

async function loadDemoKpisInner() {
  loaded = true;
  const grid = document.getElementById("kpi-grid");
  grid.innerHTML = skeletonCards(6);

  let k;
  try {
    k = await getKpis();
  } catch (err) {
    loaded = false;
    grid.innerHTML = `<div class="card kpi"><div class="kpi-label">Couldn't load the dashboard</div><div class="kpi-sub">${escapeHtml(err.message)}</div></div>`;
    return;
  }

  const month = k.latest_month ? new Date(`${k.latest_month}-01`).toLocaleString("en-IN", { month: "short", year: "numeric" }) : "";
  grid.innerHTML = [
    kpiCard({ ic: "rupee", labelText: "Revenue", value: inr(k.revenue), sub: "Delivered + shipped orders, all time" }),
    kpiCard({ ic: "receipt", labelText: "Orders", value: num(k.orders), sub: "Delivered + shipped" }),
    kpiCard({ ic: "bag", labelText: "Avg order value", value: inr(k.aov), sub: "Revenue ÷ orders" }),
    kpiCard({ ic: "users", labelText: "Active customers", value: num(k.active_customers), sub: "At least one order" }),
    kpiCard({ ic: "ban", labelText: "Cancellation rate", value: pct(k.cancellation_rate), sub: "Of all orders" }),
    kpiCard({ ic: "undo", labelText: "Return rate", value: pct(k.return_rate), sub: "Of delivered orders" }),
  ].join("");

  document.getElementById("trend-note").textContent = k.mom_change == null ? "" : `${month}: ${inr(k.latest_month_revenue)} (${k.mom_change >= 0 ? "+" : ""}${pct(k.mom_change)} vs previous month)`;

  // Short month labels: "2025-03" -> "Mar 25".
  const monthLabel = (m) => new Date(`${m}-01`).toLocaleString("en-IN", { month: "short", year: "2-digit" });
  drawChart(document.getElementById("chart-monthly"), {
    type: "line", labels: k.monthly.map((m) => monthLabel(m.month)), values: k.monthly.map((m) => m.revenue), label: "Revenue", money: true,
  });
  drawChart(document.getElementById("chart-region"), {
    type: "bar", labels: k.by_region.map((r) => r.region), values: k.by_region.map((r) => r.revenue), label: "Revenue", money: true, horizontal: true,
  });
  drawChart(document.getElementById("chart-category"), {
    type: "pie", labels: k.by_category.map((r) => r.category), values: k.by_category.map((r) => r.revenue), label: "Revenue", money: true,
  });
}
