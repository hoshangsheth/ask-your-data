/**
 * Entry point: wires the shell (navigation, mobile menu, theme, "Powered by") and starts each
 * feature module.
 *
 * Views are sections with id "view-<name>"; navigation buttons carry data-view="<name>".
 * The current view is kept in the URL hash (#ask, #dashboard, #data, #metrics) so refresh and the browser
 * back button work. Every view follows the selected dataset (js/datasets.js).
 */

import { getHealth } from "./api.js";
import { askQuestion, initAsk, newChat, showSetup } from "./ask.js";
import { currentUser, initAuth, onAuthChange } from "./auth.js";
import { redrawAll } from "./charts.js";
import { loadDashboard } from "./dashboard.js";
import { loadData } from "./data.js";
import { currentDataset, initDatasets, onDatasetChange, refreshDatasets, selectDataset } from "./datasets.js";
import { initHelp } from "./help.js";
import { hydrateIcons } from "./icons.js";
import { loadMetrics } from "./metrics.js";
import { initRecent } from "./recent.js";
import { initTheme, onThemeChange } from "./theme.js";
import { initUpload } from "./upload.js";

const VIEWS = {
  ask: { title: "Ask a question", sub: () => "Get answers, charts and the SQL behind them.", load: null },
  dashboard: {
    title: "Dashboard",
    sub: (ds) => (ds.kind === "demo" ? "Key numbers for the demo store, 2024–2025." : `Overview of ${ds.name}.`),
    load: loadDashboard,
  },
  data: { title: "Your data", sub: (ds) => `Tables and columns in ${ds.name}.`, load: loadData },
  metrics: { title: "Metrics", sub: () => "How accurate, fast and cheap the answers are.", load: loadMetrics },
};
const PROVIDER_NAMES = { gemini: "Gemini", anthropic: "Claude", openai: "OpenAI" };

const $ = (id) => document.getElementById(id);
let currentView = "ask";

function setMenu(open) {
  $("sidebar").classList.toggle("is-open", open);
  $("scrim").hidden = !open;
}

function showView(name) {
  if (!VIEWS[name] || (name === "metrics" && !currentUser().is_admin)) name = "ask"; // metrics: owner only
  currentView = name;
  document.querySelectorAll(".view").forEach((v) => v.classList.toggle("is-active", v.id === `view-${name}`));
  document.querySelectorAll(".nav-item").forEach((b) => b.classList.toggle("is-active", b.dataset.view === name));
  $("page-title").textContent = VIEWS[name].title;
  $("page-sub").textContent = VIEWS[name].sub(currentDataset());
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  VIEWS[name].load?.();
  setMenu(false);
  if (name === "ask") $("question").focus({ preventScroll: true });
}

/** "Powered by Gemini" in the sidebar footer; model details in the tooltip. */
async function loadPoweredBy() {
  const el = $("powered-by");
  try {
    const h = await getHealth();
    const provider = PROVIDER_NAMES[h.llm_provider] || h.llm_provider;
    el.classList.toggle("needs-key", !h.llm_ready);
    $("powered-text").textContent = h.llm_ready ? `Powered by ${provider}` : `${provider} · API key needed`;
    el.title = `Answers by ${provider}\nSQL model: ${h.sql_model}\nAnswer model: ${h.summary_model}`;
    showSetup(h);
  } catch {
    el.classList.add("needs-key");
    $("powered-text").textContent = "Server unreachable";
  }
}

async function init() {
  hydrateIcons();

  // Navigation and mobile menu.
  document.querySelectorAll(".nav-item").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
  window.addEventListener("hashchange", () => showView(location.hash.slice(1)));
  $("menu-btn").addEventListener("click", () => setMenu(true));
  $("scrim").addEventListener("click", () => setMenu(false));
  $("new-chat").addEventListener("click", () => showView("ask"));

  // Theme: ink transition from the toggle; charts redraw with the new colours.
  initTheme($("theme-toggle"), $("ink-canvas"));
  onThemeChange(() => redrawAll());

  // Account first (the dataset list depends on who is signed in), then the datasets.
  await initAuth();
  const showAdmin = () => ($("nav-metrics").hidden = !currentUser().is_admin);
  showAdmin();
  await initDatasets();
  onAuthChange(async () => {
    showAdmin();
    await refreshDatasets(); // uploads are private: the list changes with the account
    selectDataset(currentDataset().id);
    newChat();
    if (currentView === "metrics") showView(currentUser().is_admin ? "metrics" : "ask");
  });
  onDatasetChange(() => showView(currentView === "ask" ? "ask" : currentView));
  void initUpload();

  initAsk();
  initRecent((q) => {
    showView("ask");
    askQuestion(q);
  });
  showView(location.hash.slice(1) || "ask");
  void loadPoweredBy();
  initHelp();
}

void init();
