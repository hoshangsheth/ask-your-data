/**
 * Data view: one card per table with row count and column descriptions (GET /api/schema).
 * Helps users see what they can ask about.
 */

import { getSchema } from "./api.js";
import { escapeHtml, num } from "./format.js";

let loaded = false;

export async function loadData() {
  if (loaded) return;
  loaded = true;
  const host = document.getElementById("table-cards");
  host.innerHTML = `<div class="card table-card"><div class="skeleton" style="width:50%"></div></div>`;
  try {
    const { tables } = await getSchema();
    host.innerHTML = Object.entries(tables)
      .map(([name, t]) => `
        <div class="card table-card">
          <div class="card-head"><h3>${escapeHtml(name)}</h3><span class="rows">${num(t.row_count)} rows</span></div>
          <p>${escapeHtml(t.description)}</p>
          <ul class="col-list">
            ${t.columns.map((c) => `<li>
              <span class="col-name">${escapeHtml(c.name)}</span>
              <span class="col-desc">${escapeHtml(c.description)}</span>
              <span class="col-type">${escapeHtml(c.type.toLowerCase())}</span>
            </li>`).join("")}
          </ul>
        </div>`)
      .join("");
  } catch (err) {
    loaded = false;
    host.innerHTML = `<div class="card table-card"><p>Couldn't load the tables: ${escapeHtml(err.message)}</p></div>`;
  }
}
