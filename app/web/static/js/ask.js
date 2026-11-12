/**
 * Ask view: chat-style question and answer thread.
 *
 * Flow: user types (or clicks a suggestion) -> question bubble + live "working" card ->
 * POST /api/ask -> answer card with tabs (Chart / Table / SQL / How it worked) and actions
 * (copy SQL, download CSV, ask again). Errors render as friendly cards with a retry button.
 *
 * Exports: initAsk(health), askQuestion(text), showSetup(health)
 */

import { ApiError, ask } from "./api.js";
import { drawChart } from "./charts.js";
import {
  escapeHtml,
  formatCell,
  highlightSql,
  isMoneyColumn,
  isRatioColumn,
  label,
  num,
  toCsv,
} from "./format.js";
import { hydrateIcons, icon } from "./icons.js";
import { remember } from "./recent.js";

// Starter questions shown on the welcome screen.
const SUGGESTIONS = [
  { icon: "trend", tag: "Trends", text: "Which region's revenue dropped last quarter?" },
  { icon: "bag", tag: "Products", text: "Top 5 products by revenue in 2025" },
  { icon: "chart", tag: "Growth", text: "Show monthly revenue for 2025" },
  { icon: "card", tag: "Payments", text: "What is the cancellation rate for each payment method?" },
  { icon: "undo", tag: "Returns", text: "Which category has the highest return rate?" },
  { icon: "users", tag: "Customers", text: "How many active customers did we have in 2025?" },
];

// Shown while waiting. The server answers in one response, so these advance on a timer
// to show what is happening; the real per-step timings appear in "How it worked".
const WORKING_STEPS = ["Understanding your question", "Writing SQL", "Checking it's safe", "Running it on the data", "Writing the answer"];

// Friendly names for the agent's trace steps.
const STEP_NAMES = { generate_sql: "Wrote SQL", validate: "Safety check", execute: "Ran the query", summarize: "Wrote the answer" };

let busy = false;
let health = null;
const $ = (id) => document.getElementById(id);

/* ---------- Setup banner (no API key) ---------- */

/** Show setup steps when the AI provider has no API key; hide them otherwise. */
export function showSetup(h) {
  health = h;
  const banner = $("setup-banner");
  if (!h || h.llm_ready) {
    banner.hidden = true;
    return;
  }
  banner.hidden = false;
  const name = PROVIDER_NAMES[h.llm_provider] || h.llm_provider;
  banner.innerHTML = `
    <summary><span data-icon="key"></span><span>Add your ${escapeHtml(name)} API key to start asking questions</span>
      <span class="setup-toggle">How?</span></summary>
    <div class="setup-body">${setupStepsHtml(h.llm_provider)}</div>`;
  hydrateIcons(banner);
}

const PROVIDER_NAMES = { gemini: "Gemini", anthropic: "Claude", openai: "OpenAI" };

function setupStepsHtml(provider) {
  const keys = {
    gemini: ["GEMINI_API_KEY", "https://aistudio.google.com/apikey", "Google AI Studio"],
    anthropic: ["ANTHROPIC_API_KEY", "https://console.anthropic.com", "the Anthropic Console"],
    openai: ["OPENAI_API_KEY", "https://platform.openai.com/api-keys", "the OpenAI dashboard"],
  };
  const [envVar, url, site] = keys[provider] || keys.gemini;
  const name = PROVIDER_NAMES[provider] || provider;
  return `
    <p>The Dashboard and Data pages already work. Answering questions needs an API key for <b>${escapeHtml(name)}</b>:</p>
    <ol>
      <li>Get a key from <a href="${url}" target="_blank" rel="noopener">${site}</a>.</li>
      <li>In the project folder, copy <code>.env.example</code> to <code>.env</code> (if you haven't already).</li>
      <li>Open <code>.env</code> and set <code>${envVar}=</code> your key, then save.</li>
      <li>Restart the server, then refresh this page.</li>
    </ol>`;
}

/* ---------- Thread rendering ---------- */

function thread() {
  // Messages live in an inner column so they share the composer's max width.
  let inner = $("thread").querySelector(".thread-inner");
  if (!inner) {
    inner = document.createElement("div");
    inner.className = "thread-inner";
    $("thread").appendChild(inner);
  }
  return inner;
}

function scrollToBottom() {
  const t = $("thread");
  t.scrollTop = t.scrollHeight;
}

function addQuestion(text) {
  const el = document.createElement("div");
  el.className = "msg-q";
  el.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  thread().appendChild(el);
}

function addAssistantShell() {
  const el = document.createElement("div");
  el.className = "msg-a";
  el.innerHTML = `<span class="avatar">${icon("sparkles")}</span><div class="answer-card"></div>`;
  thread().appendChild(el);
  return el.querySelector(".answer-card");
}

/** Animated "working" state; returns a function that stops the timer. */
function renderWorking(card) {
  card.innerHTML = `
    <div class="answer-meta">Working on it…</div>
    <div class="loading-steps">
      ${WORKING_STEPS.map((s) => `<div class="loading-step"><span class="ls-icon"></span>${s}</div>`).join("")}
    </div>`;
  const steps = [...card.querySelectorAll(".loading-step")];
  let i = 0;
  const advance = () => {
    steps.forEach((s, j) => {
      s.classList.toggle("done", j < i);
      s.classList.toggle("active", j === i);
      if (j < i) s.querySelector(".ls-icon").innerHTML = icon("check");
    });
  };
  advance();
  const timer = setInterval(() => {
    if (i < steps.length - 1) {
      i += 1;
      advance();
    }
  }, 1100);
  return () => clearInterval(timer);
}

function statusBadge(status) {
  const map = {
    ok: ["ok", "check", "Answered"],
    unanswerable: ["unanswerable", "info", "Not in this data"],
    failed: ["failed", "alert", "Couldn't answer"],
  };
  const [cls, ic, text] = map[status] || map.failed;
  return `<span class="badge ${cls}">${icon(ic)}${text}</span>`;
}

function metaHtml(r) {
  const parts = [`${icon("clock")} ${(r.latency_ms / 1000).toFixed(1)}s`];
  if (r.attempts > 1) parts.push(`${icon("retry")} fixed itself after ${r.attempts - 1} retr${r.attempts === 2 ? "y" : "ies"}`);
  const tokens = (r.usage?.input_tokens || 0) + (r.usage?.output_tokens || 0);
  if (tokens) parts.push(`${icon("cpu")} ${num(tokens)} tokens`);
  return parts.map((p) => `<span style="display:inline-flex;gap:4px;align-items:center">${p}</span>`).join("");
}

function tableHtml(columns, rows) {
  const numeric = columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] == null || typeof r[i] === "number"));
  const head = columns.map((c, i) => `<th class="${numeric[i] ? "num" : ""}">${escapeHtml(label(c))}</th>`).join("");
  const body = rows
    .slice(0, 200)
    .map((r) => `<tr>${r.map((v, i) => `<td class="${numeric[i] ? "num" : ""}">${escapeHtml(formatCell(v, columns[i]))}</td>`).join("")}</tr>`)
    .join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function stepsHtml(trace) {
  return `<ul class="steps">${trace
    .map((t) => {
      const err = t.ok === false;
      const details = [];
      if (t.step === "generate_sql" && t.attempt > 1) details.push(`attempt ${t.attempt}`);
      if (t.rows != null) details.push(`${num(t.rows)} row${t.rows === 1 ? "" : "s"}`);
      if (t.tables) details.push(`tables: ${t.tables.join(", ")}`);
      if (t.input_tokens) details.push(`${num(t.input_tokens + t.output_tokens)} tokens`);
      details.push(`${t.ms} ms`);
      return `<li class="${err ? "err" : ""}">
        <span class="step-dot">${icon(err ? "x" : "check")}</span>
        <div><div class="step-title">${STEP_NAMES[t.step] || t.step}</div>
          <div class="step-detail">${escapeHtml(details.join(" · "))}</div>
          ${err ? `<div class="step-detail err">${escapeHtml(t.error)}</div>` : ""}</div>
      </li>`;
    })
    .join("")}</ul>`;
}

function renderAnswer(card, r) {
  const hasTable = r.columns.length > 0;
  const tabs = [];
  if (r.chart) tabs.push(["chart", "chart", "Chart"]);
  if (hasTable) tabs.push(["table", "table", `Table · ${num(r.rows.length)}${r.truncated ? "+" : ""}`]);
  if (r.sql) tabs.push(["sql", "code", "SQL"]);
  if (r.trace.length) tabs.push(["steps", "list", "How it worked"]);

  card.innerHTML = `
    <div class="answer-head">${statusBadge(r.status)}<div class="answer-meta">${metaHtml(r)}</div></div>
    <p class="answer-text">${escapeHtml(r.answer)}</p>
    ${r.explanation && r.status === "ok" ? `<p class="answer-explain">${escapeHtml(r.explanation)}</p>` : ""}
    ${tabs.length ? `<div class="tabs" role="tablist">${tabs
      .map(([id, ic, text], i) => `<button class="tab ${i === 0 ? "is-active" : ""}" data-tab="${id}" role="tab">${icon(ic)}${text}</button>`)
      .join("")}</div>` : ""}
    ${r.chart ? `<div class="tab-panel" data-panel="chart"><div class="chart-box"><canvas></canvas></div></div>` : ""}
    ${hasTable ? `<div class="tab-panel" data-panel="table">${tableHtml(r.columns, r.rows)}
        ${r.truncated ? `<p class="table-note">Showing the first ${num(r.rows.length)} rows.</p>` : ""}</div>` : ""}
    ${r.sql ? `<div class="tab-panel" data-panel="sql"><div class="sql-block">
        <button class="btn" data-action="copy">${icon("copy")}Copy</button>
        <pre><code>${highlightSql(escapeHtml(r.sql))}</code></pre></div></div>` : ""}
    ${r.trace.length ? `<div class="tab-panel" data-panel="steps">${stepsHtml(r.trace)}</div>` : ""}
    <div class="answer-actions">
      ${hasTable ? `<button class="btn" data-action="csv">${icon("download")}Download CSV</button>` : ""}
      <button class="btn" data-action="again">${icon("retry")}Ask again</button>
    </div>`;

  // Show only the first tab's panel.
  const panels = [...card.querySelectorAll(".tab-panel")];
  panels.forEach((p, i) => (p.hidden = i !== 0));

  // Chart.
  if (r.chart) {
    const xi = r.columns.indexOf(r.chart.x);
    const yi = r.columns.indexOf(r.chart.y);
    const labels = r.rows.map((row) => String(row[xi]));
    const longLabels = labels.reduce((a, l) => a + l.length, 0) / labels.length > 14;
    drawChart(card.querySelector("canvas"), {
      type: r.chart.type,
      labels,
      values: r.rows.map((row) => row[yi]),
      label: label(r.chart.y),
      money: isMoneyColumn(r.chart.y),
      ratio: isRatioColumn(r.chart.y),
      horizontal: r.chart.type === "bar" && longLabels,
    });
  }

  // Tabs, copy, CSV, ask again.
  card.addEventListener("click", (e) => {
    const tab = e.target.closest(".tab");
    if (tab) {
      card.querySelectorAll(".tab").forEach((t) => t.classList.toggle("is-active", t === tab));
      panels.forEach((p) => (p.hidden = p.dataset.panel !== tab.dataset.tab));
      return;
    }
    const action = e.target.closest("[data-action]")?.dataset.action;
    if (action === "copy") copyText(r.sql, "SQL copied");
    if (action === "csv") downloadCsv(r);
    if (action === "again") askQuestion(r.question);
  });
}

function renderError(card, question, err) {
  const keyMissing = err instanceof ApiError && err.status === 503;
  const rate = err instanceof ApiError && err.status === 429;
  const title = keyMissing ? "The AI isn't set up yet" : rate ? "Too many questions at once" : "Something went wrong";
  const hint = keyMissing
    ? setupStepsHtml(health?.llm_provider || "gemini")
    : rate
      ? "<p>Please wait a minute and try again.</p>"
      : `<p class="answer-explain">${escapeHtml(err.message)}</p>`;
  card.innerHTML = `
    <div class="answer-head">${statusBadge("failed")}</div>
    <p class="answer-text">${title}</p>
    <div class="setup-inline">${hint}</div>
    <div class="answer-actions"><button class="btn" data-action="again">${icon("retry")}Try again</button></div>`;
  card.querySelector('[data-action="again"]').addEventListener("click", () => askQuestion(question));
}

/* ---------- Actions ---------- */

export function toast(message) {
  const t = $("toast");
  t.textContent = message;
  t.classList.add("show");
  clearTimeout(t._timer);
  t._timer = setTimeout(() => t.classList.remove("show"), 1800);
}

async function copyText(text, done) {
  try {
    await navigator.clipboard.writeText(text);
    toast(done);
  } catch {
    toast("Couldn't copy - select the text instead");
  }
}

function downloadCsv(r) {
  const blob = new Blob([toCsv(r.columns, r.rows)], { type: "text/csv" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${r.question.slice(0, 40).replace(/[^\w]+/g, "_").replace(/_$/, "") || "result"}.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

/* ---------- Public ---------- */

/** Ask a question and render the exchange in the thread. */
export async function askQuestion(text) {
  const question = text.trim();
  if (question.length < 3 || busy) return;
  busy = true;
  $("send-btn").disabled = true;
  $("welcome").hidden = true;
  remember(question);

  addQuestion(question);
  const card = addAssistantShell();
  const stop = renderWorking(card);
  scrollToBottom();

  try {
    const result = await ask(question);
    stop();
    renderAnswer(card, result);
  } catch (err) {
    stop();
    renderError(card, question, err);
  } finally {
    busy = false;
    $("send-btn").disabled = false;
    scrollToBottom();
  }
}

export function initAsk() {
  // Suggestions.
  $("suggestions").innerHTML = SUGGESTIONS.map(
    (s) => `<button class="suggestion" data-q="${escapeHtml(s.text)}">
      <span class="s-icon">${icon(s.icon)}</span>
      <span><span class="s-tag">${s.tag}</span><span class="s-text" style="display:block">${escapeHtml(s.text)}</span></span>
    </button>`,
  ).join("");
  $("suggestions").addEventListener("click", (e) => {
    const b = e.target.closest(".suggestion");
    if (b) askQuestion(b.dataset.q);
  });

  // Composer: auto-growing textarea, Enter to send, Shift+Enter for a new line.
  const input = $("question");
  const grow = () => {
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 160)}px`;
  };
  input.addEventListener("input", grow);
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      $("composer").requestSubmit();
    }
  });
  $("composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const q = input.value;
    if (q.trim().length < 3) {
      toast("Type a question first");
      return;
    }
    input.value = "";
    grow();
    askQuestion(q);
  });

  // "/" focuses the box from anywhere (unless already typing somewhere).
  document.addEventListener("keydown", (e) => {
    if (e.key === "/" && !["INPUT", "TEXTAREA"].includes(document.activeElement.tagName)) {
      e.preventDefault();
      input.focus();
    }
  });
}
