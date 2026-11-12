/**
 * Dashboard view: KPI cards and three charts from GET /api/kpis.
 * Loaded once, the first time the view is opened (or on start if it is the first view).
 */

import { getKpis } from "./api.js";
import { drawChart } from "./charts.js";
import { escapeHtml, inr, num, pct } from "./format.js";
import { icon } from "./icons.js";

let loaded = false;

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

export async function loadDashboard() {
  if (loaded) return;
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
