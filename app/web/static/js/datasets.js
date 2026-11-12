/**
 * Datasets: which data the user is asking about (demo store or an uploaded file).
 *
 * Holds the list and the current selection (remembered in localStorage "ayd-dataset"), renders
 * the "Your data" list in the sidebar, and notifies listeners when the selection changes, so
 * the Ask, Dashboard and Data views can follow.
 *
 * Exports: initDatasets(), currentDataset(), onDatasetChange(fn), selectDataset(id),
 *          addDataset(summary), refreshDatasets()
 */

import { deleteDataset, listDatasets } from "./api.js";
import { escapeHtml, plainNum } from "./format.js";
import { icon } from "./icons.js";
import { toast } from "./toast.js";

const KEY = "ayd-dataset";
const DEMO = { id: "demo", name: "Demo store", kind: "demo", tables: [], suggestions: [] };

let datasets = [DEMO];
let currentId = readSaved() || "demo";
const listeners = new Set();
const $ = (id) => document.getElementById(id);

function readSaved() {
  try {
    return localStorage.getItem(KEY);
  } catch {
    return null;
  }
}

function save(id) {
  try {
    localStorage.setItem(KEY, id);
  } catch {
    /* ignore */
  }
}

/** The selected dataset summary (see DatasetSummary in app/api/schemas.py). */
export const currentDataset = () => datasets.find((d) => d.id === currentId) ?? datasets[0] ?? DEMO;

/** Run fn(dataset) when the selection changes. */
export const onDatasetChange = (fn) => listeners.add(fn);

/** "2 tables · 1,234 rows" */
export function describeSize(ds) {
  const rows = ds.tables.reduce((n, t) => n + t.rows, 0);
  const tables = ds.tables.length;
  return `${tables} table${tables === 1 ? "" : "s"} · ${plainNum(rows)} rows`;
}

const FORMAT_ICON = { xlsx: "sheet", xlsm: "sheet", xls: "sheet", ods: "sheet", csv: "sheet", tsv: "sheet", pdf: "doc", docx: "doc", txt: "doc" };

function render() {
  $("dataset-list").innerHTML = datasets
    .map((d) => {
      const ic = d.kind === "demo" ? "store" : FORMAT_ICON[d.file_format] ?? "file";
      const active = d.id === currentId ? " is-active" : "";
      const del = d.kind === "upload"
        ? `<button class="ds-delete" data-delete="${d.id}" aria-label="Delete ${escapeHtml(d.name)}" title="Delete">${icon("trash")}</button>`
        : "";
      return `<li class="ds-item${active}">
        <button class="ds-select" data-select="${d.id}" title="${escapeHtml(d.filename || d.name)}">
          <span class="ds-icon">${icon(ic)}</span>
          <span class="ds-text"><span class="ds-name">${escapeHtml(d.name)}</span><span class="ds-meta">${d.tables.length ? describeSize(d) : "Sample sales data"}</span></span>
        </button>${del}</li>`;
    })
    .join("");
}

function notify() {
  const ds = currentDataset();
  listeners.forEach((fn) => fn(ds));
}

export function selectDataset(id) {
  if (!datasets.some((d) => d.id === id)) id = "demo";
  const changed = id !== currentId;
  currentId = id;
  save(id);
  render();
  if (changed) notify();
}

/** Add a freshly uploaded dataset and switch to it. */
export function addDataset(summary) {
  datasets = [datasets[0], summary, ...datasets.slice(1).filter((d) => d.id !== summary.id)];
  currentId = "";
  selectDataset(summary.id);
}

async function remove(id) {
  const ds = datasets.find((d) => d.id === id);
  if (!ds || !window.confirm(`Delete "${ds.name}"? Its uploaded data will be removed.`)) return;
  try {
    await deleteDataset(id);
  } catch (err) {
    toast(`Couldn't delete: ${err.message}`, { error: true });
    return;
  }
  datasets = datasets.filter((d) => d.id !== id);
  toast(`Deleted "${ds.name}"`);
  if (currentId === id) selectDataset("demo");
  else render();
}

export async function refreshDatasets() {
  try {
    datasets = await listDatasets();
  } catch {
    datasets = [DEMO];
  }
  const missing = !datasets.some((d) => d.id === currentId);
  if (missing) currentId = "demo";
  render();
  if (missing && listeners.size) notify(); // e.g. signed out while viewing an upload
}

export async function initDatasets() {
  $("dataset-list").addEventListener("click", (e) => {
    const del = e.target.closest("[data-delete]");
    if (del) return void remove(del.dataset.delete);
    const sel = e.target.closest("[data-select]");
    if (sel) selectDataset(sel.dataset.select);
  });
  await refreshDatasets();
}
