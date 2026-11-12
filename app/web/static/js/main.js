/**
 * Entry point: wires the shell (navigation, mobile menu, theme, status pill) and starts each view.
 *
 * Views are sections with id "view-<name>"; navigation buttons carry data-view="<name>".
 * The current view is kept in the URL hash (#ask, #dashboard, #data) so refresh and the browser
 * back button work.
 */

import { getHealth } from "./api.js";
import { askQuestion, initAsk, showSetup } from "./ask.js";
import { redrawAll } from "./charts.js";
import { loadDashboard } from "./dashboard.js";
import { loadData } from "./data.js";
import { hydrateIcons } from "./icons.js";
import { initRecent } from "./recent.js";
import { initTheme, onThemeChange } from "./theme.js";

const VIEWS = {
  ask: { title: "Ask a question", sub: "Get answers, charts and the SQL behind them.", load: null },
  dashboard: { title: "Dashboard", sub: "Key numbers for the demo store, 2024–2025.", load: loadDashboard },
  data: { title: "Your data", sub: "The tables and columns the assistant can use.", load: loadData },
};

const $ = (id) => document.getElementById(id);

function setMenu(open) {
  $("sidebar").classList.toggle("is-open", open);
  $("scrim").hidden = !open;
}

function showView(name) {
  if (!VIEWS[name]) name = "ask";
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
  $("page-title").textContent = VIEWS[name].title;
  $("page-sub").textContent = VIEWS[name].sub;
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  VIEWS[name].load?.();
  setMenu(false);
  if (name === "ask") $("question").focus({ preventScroll: true });
}

async function loadStatus() {
  const pill = $("status-pill");
  try {
    const h = await getHealth();
    const provider = { gemini: "Gemini", anthropic: "Claude", openai: "OpenAI" }[h.llm_provider] || h.llm_provider;
    pill.classList.add(h.llm_ready ? "ok" : "warn");
    $("status-text").textContent = h.llm_ready ? `${provider} · ${h.sql_model}` : `${provider} · API key needed`;
    pill.title = `SQL model: ${h.sql_model}\nAnswer model: ${h.summary_model}\nDatabase: ${h.database}`;
    showSetup(h);
  } catch {
    pill.classList.add("warn");
    $("status-text").textContent = "Server unreachable";
  }
}

function init() {
  hydrateIcons();

  // Navigation.
  document.querySelectorAll(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  window.addEventListener("hashchange", () => showView(location.hash.slice(1)));

  // Mobile menu.
  $("menu-btn").addEventListener("click", () => setMenu(true));
  $("scrim").addEventListener("click", () => setMenu(false));

  // Theme (charts redraw with the new colours).
  initTheme($("theme-toggle"));
  onThemeChange(() => redrawAll());

  // Views.
  initAsk();
  initRecent((q) => {
    showView("ask");
    askQuestion(q);
  });
  showView(location.hash.slice(1) || "ask");
  loadStatus();
}

init();
