/**
 * Chart.js wrapper: one consistent look for every chart, themed from CSS variables.
 *
 * Usage:
 *   drawChart(canvas, { type: "bar", labels, values, label: "Revenue", money: true, horizontal: false })
 * Calling it again on the same canvas replaces the previous chart. redrawAll() re-renders after
 * a theme change.
 */

import { compactNum, inr, num, pct } from "./format.js";
import { cssVar } from "./theme.js";

const PALETTE = ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#ec4899", "#8b5cf6", "#14b8a6", "#f97316"];
const charts = new Map(); // canvas -> { chart, spec }

/** spec.money = rupees (demo store), spec.ratio = 0..1, spec.compact = 1.2K / 3.4M (uploads). */
function formatter(spec) {
  if (spec.money) return (v) => inr(v);
  if (spec.ratio) return (v) => pct(v);
  if (spec.compact) return (v) => compactNum(v);
  return (v) => num(v);
}

/**
 * Axis options. Only the value axis gets a number formatter; the category axis must keep
 * Chart.js's default callback (setting it to undefined would print indexes 0, 1, 2...).
 */
function axes(spec, text, grid, fmt) {
  const category = { grid: { display: false, drawTicks: false }, border: { display: false }, ticks: { color: text, padding: 8, maxRotation: 0, autoSkip: true } };
  const value = { grid: { color: grid, drawTicks: false }, border: { display: false }, ticks: { color: text, padding: 8, maxRotation: 0, maxTicksLimit: 6, callback: (v) => fmt(v) } };
  return spec.horizontal ? { x: value, y: category } : { x: category, y: value };
}

function build(canvas, spec) {
  const text = cssVar("--muted");
  const grid = cssVar("--chart-grid");
  const primary = cssVar("--primary");
  const fmt = formatter(spec);
  const isPie = spec.type === "pie" || spec.type === "doughnut";
  const ctx = canvas.getContext("2d");

  // Soft gradient fill under line charts.
  let fill = primary;
  if (spec.type === "line") {
    fill = ctx.createLinearGradient(0, 0, 0, canvas.clientHeight || 300);
    fill.addColorStop(0, `${primary}55`);
    fill.addColorStop(1, `${primary}00`);
  }

  return new window.Chart(ctx, {
    type: spec.type === "pie" ? "doughnut" : spec.type,
    data: {
      labels: spec.labels,
      datasets: [{
        label: spec.label,
        data: spec.values,
        backgroundColor: isPie ? PALETTE : spec.type === "line" ? fill : spec.labels.map((_, i) => (spec.multicolor ? PALETTE[i % PALETTE.length] : primary)),
        borderColor: isPie ? cssVar("--surface") : primary,
        borderWidth: isPie ? 3 : 2,
        borderRadius: spec.type === "bar" ? 8 : 0,
        maxBarThickness: 46,
        tension: 0.35,
        fill: spec.type === "line",
        pointRadius: spec.type === "line" ? 0 : undefined,
        pointHoverRadius: 5,
        pointBackgroundColor: primary,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      indexAxis: spec.horizontal ? "y" : "x",
      cutout: isPie ? "62%" : undefined,
      interaction: { mode: "index", intersect: false },
      plugins: {
        legend: { display: isPie, position: "right", labels: { color: text, boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 14 } },
        tooltip: {
          backgroundColor: cssVar("--text"),
          titleColor: cssVar("--bg"),
          bodyColor: cssVar("--bg"),
          padding: 10,
          cornerRadius: 8,
          displayColors: isPie,
          callbacks: { label: (c) => ` ${isPie ? c.label + ": " : ""}${fmt(c.parsed?.y ?? c.parsed?.x ?? c.parsed)}` },
        },
      },
      scales: isPie ? {} : axes(spec, text, grid, fmt),
    },
  });
}

/** Draw (or replace) a chart on `canvas`. Does nothing if Chart.js failed to load. */
export function drawChart(canvas, spec) {
  if (!window.Chart || !canvas) return;
  charts.get(canvas)?.chart.destroy();
  charts.set(canvas, { chart: build(canvas, spec), spec });
}

/** Re-render every chart (e.g. after the theme changes). */
export function redrawAll() {
  for (const [canvas, { chart, spec }] of charts) {
    if (!canvas.isConnected) {
      chart.destroy();
      charts.delete(canvas);
      continue;
    }
    chart.destroy();
    charts.set(canvas, { chart: build(canvas, spec), spec });
  }
}
