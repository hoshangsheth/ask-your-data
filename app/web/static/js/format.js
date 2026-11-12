/**
 * Formatting helpers (pure functions, no DOM).
 *
 *   inr(12345678)   -> "₹1.23 Cr"     money in Indian units (lakh / crore)
 *   num(13442)      -> "13,442"        Indian digit grouping
 *   pct(0.0735)     -> "7.4%"
 *   escapeHtml(s)   -> safe to insert with innerHTML
 */

export function inr(v, { compact = true } = {}) {
  if (v == null || Number.isNaN(Number(v))) return "–";
  const n = Number(v);
  const a = Math.abs(n);
  if (compact && a >= 1e7) return `₹${(n / 1e7).toFixed(2)} Cr`;
  if (compact && a >= 1e5) return `₹${(n / 1e5).toFixed(2)} L`;
  return `₹${Math.round(n).toLocaleString("en-IN")}`;
}

export const num = (v) => (v == null ? "–" : Number(v).toLocaleString("en-IN", { maximumFractionDigits: 2 }));

export const pct = (v, digits = 1) => (v == null ? "–" : `${(Number(v) * 100).toFixed(digits)}%`);

export function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Turn a snake_case column name into a readable label: "q4_revenue" -> "Q4 revenue". */
export function label(col) {
  const s = String(col).replace(/_/g, " ").trim();
  return s.charAt(0).toUpperCase() + s.slice(1);
}

/** Heuristic: does this column hold money? (used to format values and chart axes) */
export const isMoneyColumn = (col) => /revenue|sales|gmv|value|profit|amount|cost|price|aov|spend/i.test(col);

/** Heuristic: does this column hold a ratio between 0 and 1? */
export const isRatioColumn = (col) => /rate|share|margin|ratio|growth|change|pct|percent/i.test(col);

/** Format one cell for display in the results table. */
export function formatCell(value, col) {
  if (value == null) return "–";
  if (typeof value !== "number") return String(value);
  if (isMoneyColumn(col)) return inr(value, { compact: false });
  if (isRatioColumn(col) && Math.abs(value) <= 1.5) return pct(value, 2);
  return num(value);
}

/** Light SQL syntax highlighting (keywords, strings, numbers). Input must be escaped first. */
export function highlightSql(escapedSql) {
  const kw = /\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|HAVING|LIMIT|JOIN|LEFT|RIGHT|INNER|OUTER|ON|AS|AND|OR|NOT|IN|IS|NULL|CASE|WHEN|THEN|ELSE|END|WITH|UNION|ALL|DISTINCT|DESC|ASC|SUM|COUNT|AVG|MIN|MAX|ROUND|CAST|BETWEEN|LIKE|OVER|PARTITION BY)\b/gi;
  return escapedSql
    .replace(/(&#39;.*?&#39;)/g, '<span class="sql-str">$1</span>')
    .replace(/\b(\d+(?:\.\d+)?)\b/g, '<span class="sql-num">$1</span>')
    .replace(kw, '<span class="sql-kw">$1</span>');
}

/** CSV text for a result (RFC 4180 quoting). */
export function toCsv(columns, rows) {
  const q = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(q).join(","), ...rows.map((r) => r.map(q).join(","))].join("\n");
}
