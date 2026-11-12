/**
 * "Recent questions" list in the sidebar, remembered in this browser (localStorage).
 * Storage can be unavailable (private mode); the list then just lasts for the visit.
 */

import { escapeHtml } from "./format.js";
import { icon } from "./icons.js";

const KEY = "ayd-recent";
const MAX = 12;
let items = load();

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || "[]");
  } catch {
    return [];
  }
}

function save() {
  try {
    localStorage.setItem(KEY, JSON.stringify(items));
  } catch {
    /* ignore */
  }
}

/** Add a question to the top (deduplicated) and re-render. */
export function remember(question) {
  items = [question, ...items.filter((q) => q !== question)].slice(0, MAX);
  save();
  render();
}

let onPick = () => {};

function render() {
  const list = document.getElementById("recent-list");
  list.innerHTML = items
    .map((q, i) => `<li><button data-i="${i}" title="${escapeHtml(q)}">${icon("history")}<span>${escapeHtml(q)}</span></button></li>`)
    .join("");
  document.getElementById("recent-empty").hidden = items.length > 0;
  document.getElementById("clear-recent").hidden = items.length === 0;
}

/** Wire up the list; `pick(question)` runs when a recent question is clicked. */
export function initRecent(pick) {
  onPick = pick;
  document.getElementById("recent-list").addEventListener("click", (e) => {
    const btn = e.target.closest("button[data-i]");
    if (btn) onPick(items[Number(btn.dataset.i)]);
  });
  document.getElementById("clear-recent").addEventListener("click", () => {
    items = [];
    save();
    render();
  });
  render();
}
