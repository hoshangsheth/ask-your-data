/**
 * Data view: what the assistant can see in the selected dataset - one card per table with its
 * row count and a description of every column (GET /api/schema?dataset=...).
 *
 * Exports: loadData()  (called when the view opens and when the dataset changes)
 */

import { getSchema } from "./api.js";
import { currentDataset, describeSize } from "./datasets.js";
import { escapeHtml, plainNum } from "./format.js";
import { icon } from "./icons.js";

let loadedFor = null; // dataset id currently rendered

function intro(ds) {
  const el = document.getElementById("data-intro");
  el.innerHTML = ds.kind === "demo"
    ? `${icon("info")}<p>This is the built-in demo: a synthetic Indian e-commerce store with planted patterns (festive spikes, an East-region slump in Q4 2025) so there's something to discover. Upload your own file from the sidebar to ask about your data.</p>`
    : `${icon("file")}<p><b>${escapeHtml(ds.filename)}</b> · ${describeSize(ds)}. Column names were cleaned and numbers and dates were detected automatically. Delete it from the sidebar list when you're done.</p>`;
}

export async function loadData() {
  const ds = currentDataset();
  if (loadedFor === ds.id) return;
  loadedFor = ds.id;
  intro(ds);
  const host = document.getElementById("table-cards");
  host.innerHTML = `<div class="card table-card"><div class="skeleton" style="width:50%"></div></div>`;
  try {
    const { tables } = await getSchema(ds.id);
    if (currentDataset().id !== ds.id) return; // user switched while loading
    host.innerHTML = Object.entries(tables)
      .map(([name, t]) => `
        <div class="card table-card">
          <div class="card-head"><h3>${escapeHtml(name)}</h3><span class="rows">${plainNum(t.row_count)} rows</span></div>
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
    loadedFor = null;
    host.innerHTML = `<div class="card table-card"><p>Couldn't load the tables: ${escapeHtml(err.message)}</p></div>`;
  }
}
