/**
 * Ask view: chat-style question and answer thread about the selected dataset.
 *
 * Flow: user types (or clicks a suggestion) -> question bubble + live "working" card ->
 * POST /api/ask (with the dataset id and the conversation id) -> answer card with tabs (Chart /
 * Table / SQL / How it worked) and actions: helpful / not helpful feedback, export (CSV, Excel,
 * chart PNG, PDF report), ask again. Questions in one chat form a conversation, so follow-ups
 * ("same for 2024", "break that down by city") build on earlier answers. Errors render as
 * friendly cards with a retry button. "New chat" (or switching dataset) starts a new conversation.
 *
 * Exports: initAsk(), askQuestion(text), newChat(), showSetup(health)
 */

import { ApiError, ask, downloadReport, exportUrl, sendFeedback } from "./api.js";
import { drawChart } from "./charts.js";
import { currentDataset, describeSize, onDatasetChange } from "./datasets.js";
import { escapeHtml, formatCell, highlightSql, isMoneyColumn, isRatioColumn, label, num, toCsv } from "./format.js";
import { hydrateIcons, icon } from "./icons.js";
import { remember } from "./recent.js";
import { saveChart } from "./saved-charts.js";
import { toast } from "./toast.js";

// Icons and tags for starter questions (demo store); uploads cycle through generic ones.
const DEMO_TAGS = [["trend", "Trends"], ["bag", "Products"], ["chart", "Growth"], ["card", "Payments"], ["undo", "Returns"], ["users", "Customers"]];
const UPLOAD_TAGS = [["chart", "Breakdown"], ["trend", "Ranking"], ["clock", "Over time"], ["list", "Common values"], ["sparkles", "Averages"], ["table", "Size"]];

// Shown while waiting. The server answers in one response, so these advance on a timer
// to show what is happening; the real per-step timings appear in "How it worked".
const WORKING_STEPS = ["Understanding your question", "Writing SQL", "Checking it's safe", "Running it on the data", "Writing the answer"];

// Friendly names for the agent's trace steps.
const STEP_NAMES = { generate_sql: "Wrote SQL", validate: "Safety check", execute: "Ran the query", summarize: "Wrote the answer" };

let busy = false;
let health = null;
let conversationId = null; // set by the first answer; follow-up questions continue it
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

/** Bring a new exchange to the top of the thread, so its answer is read from the beginning. */
function scrollToExchange(questionEl) {
  const t = $("thread");
  const top = t.scrollTop + questionEl.getBoundingClientRect().top - t.getBoundingClientRect().top - 12;
  t.scrollTo({ top: Math.max(0, top), behavior: "smooth" });
}

/** Answer charts and tables are sized to the visible thread (CSS reads --thread-h). */
function trackThreadHeight() {
  const t = $("thread");
  const set = () => t.style.setProperty("--thread-h", `${t.clientHeight}px`);
  set();
  if ("ResizeObserver" in window) new ResizeObserver(set).observe(t);
}

function addQuestion(text) {
  const el = document.createElement("div");
  el.className = "msg-q";
  el.innerHTML = `<div class="bubble">${escapeHtml(text)}</div>`;
  thread().appendChild(el);
  return el;
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
    about: ["ok", "database", "About the data"],
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

function tableHtml(columns, rows, currency) {
  const numeric = columns.map((_, i) => rows.length > 0 && rows.every((r) => r[i] == null || typeof r[i] === "number"));
  const head = columns.map((c, i) => `<th class="${numeric[i] ? "num" : ""}">${escapeHtml(label(c))}</th>`).join("");
  const body = rows
    .slice(0, 200)
    .map((r) => `<tr>${r.map((v, i) => `<td class="${numeric[i] ? "num" : ""}">${escapeHtml(formatCell(v, columns[i], currency))}</td>`).join("")}</tr>`)
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
    <div class="answer-head">${statusBadge(r.kind === "about" ? "about" : r.status)}<div class="answer-meta">${metaHtml(r)}</div></div>
    ${followUpHtml(r)}
    <p class="answer-text${r.kind === "about" ? " is-prose" : ""}">${escapeHtml(r.answer)}</p>
    ${r.explanation && r.status === "ok" && r.kind !== "about" ? `<p class="answer-explain">${escapeHtml(r.explanation)}</p>` : ""}
    ${tabs.length ? `<div class="tabs" role="tablist">${tabs
      .map(([id, ic, text], i) => `<button class="tab ${i === 0 ? "is-active" : ""}" data-tab="${id}" role="tab">${icon(ic)}${text}</button>`)
      .join("")}</div>` : ""}
    ${r.chart ? `<div class="tab-panel" data-panel="chart"><div class="chart-box"><canvas></canvas></div></div>` : ""}
    ${hasTable ? `<div class="tab-panel" data-panel="table">${tableHtml(r.columns, r.rows, r.currency)}
        ${r.truncated ? `<p class="table-note">Showing the first ${num(r.rows.length)} rows.</p>` : ""}</div>` : ""}
    ${r.sql ? `<div class="tab-panel" data-panel="sql"><div class="sql-block">
        <button class="btn" data-action="copy">${icon("copy")}Copy</button>
        <pre><code>${highlightSql(escapeHtml(r.sql))}</code></pre></div></div>` : ""}
    ${r.trace.length ? `<div class="tab-panel" data-panel="steps">${stepsHtml(r.trace)}</div>` : ""}
    <div class="answer-actions">
      ${r.question_id ? feedbackHtml() : ""}
      <span class="actions-spacer"></span>
      ${hasTable ? exportMenuHtml(r) : ""}
      <button class="btn" data-action="again">${icon("retry")}Ask again</button>
    </div>
    <div class="feedback-note" hidden>
      <input type="text" maxlength="500" placeholder="What was wrong? (optional, helps improve the answers)" aria-label="What was wrong">
      <button class="btn" data-action="note">Send</button>
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
    const spec = {
      type: r.chart.type,
      labels,
      values: r.rows.map((row) => row[yi]),
      label: label(r.chart.y),
      money: r.currency === "INR" && isMoneyColumn(r.chart.y),
      ratio: isRatioColumn(r.chart.y),
      compact: r.currency !== "INR", // uploaded data: 1.2K / 3.4M axis labels
      horizontal: r.chart.type === "bar" && longLabels,
    };
    drawChart(card.querySelector("canvas"), spec);
    // Every charted answer also appears on the Dashboard ("From your questions").
    if (r.status === "ok") {
      saveChart(r.dataset_id || currentDataset().id, {
        id: r.question_id || `${Date.now()}`,
        question: r.standalone_question || r.question,
        spec,
      });
    }
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
    if (action === "again") askQuestion(r.question);
    if (action === "up" || action === "down") rate(card, r, action === "up" ? 1 : -1);
    if (action === "note") sendNote(card, r);
    if (action === "export") card.querySelector(".export-menu")?.toggleAttribute("open");
    if (["csv", "xlsx", "png", "pdf"].includes(action)) {
      card.querySelector(".export-menu")?.removeAttribute("open");
      void exportAs(card, r, action);
    }
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

async function copyText(text, done) {
  try {
    await navigator.clipboard.writeText(text);
    toast(done);
  } catch {
    toast("Couldn't copy - select the text instead");
  }
}

/* ---------- Follow-ups, feedback, export ---------- */

/** "Follow-up · understood as …" when a question built on earlier turns. */
function followUpHtml(r) {
  if (!r.turn || r.turn < 2) return "";
  const same = (r.standalone_question || "").trim().toLowerCase() === r.question.trim().toLowerCase();
  return `<p class="followup-note">${icon("link")}<span>Follow-up${same ? "" : ` · understood as “${escapeHtml(r.standalone_question)}”`}</span></p>`;
}

function feedbackHtml() {
  return `<span class="feedback" role="group" aria-label="Was this answer helpful?">
      <span class="feedback-label">Helpful?</span>
      <button class="icon-btn fb" data-action="up" aria-pressed="false" title="Helpful" aria-label="Helpful">${icon("thumbUp")}</button>
      <button class="icon-btn fb" data-action="down" aria-pressed="false" title="Not helpful" aria-label="Not helpful">${icon("thumbDown")}</button>
    </span>`;
}

function exportMenuHtml(r) {
  const chart = r.chart ? `<button data-action="png">${icon("image")}Chart image (PNG)</button>` : "";
  const server = r.question_id
    ? `<button data-action="xlsx">${icon("sheet")}Excel (.xlsx)</button>
       <button data-action="pdf">${icon("doc")}PDF report</button>`
    : "";
  return `<span class="export-wrap">
      <button class="btn" data-action="export" aria-haspopup="menu">${icon("download")}Export</button>
      <span class="export-menu" role="menu">
        <button data-action="csv">${icon("table")}Table (.csv)</button>${server}${chart}
      </span>
    </span>`;
}

async function rate(card, r, rating) {
  const buttons = card.querySelectorAll(".fb");
  const target = card.querySelector(`.fb[data-action="${rating === 1 ? "up" : "down"}"]`);
  const clear = target.getAttribute("aria-pressed") === "true"; // clicking again removes the rating
  try {
    await sendFeedback(r.question_id, clear ? 0 : rating);
  } catch (err) {
    toast(`Couldn't save feedback: ${err.message}`, { error: true });
    return;
  }
  buttons.forEach((b) => b.setAttribute("aria-pressed", String(!clear && b === target)));
  const note = card.querySelector(".feedback-note");
  note.hidden = clear || rating === 1;
  if (!note.hidden) note.querySelector("input").focus();
  if (!clear) toast(rating === 1 ? "Thanks for the feedback" : "Thanks - tell us what was wrong (optional)");
}

async function sendNote(card, r) {
  const input = card.querySelector(".feedback-note input");
  try {
    await sendFeedback(r.question_id, -1, input.value.trim());
    card.querySelector(".feedback-note").hidden = true;
    toast("Thanks - noted");
  } catch (err) {
    toast(`Couldn't save: ${err.message}`, { error: true });
  }
}

const fileStem = (q) => q.slice(0, 50).replace(/[^\w]+/g, "_").replace(/^_|_$/g, "") || "result";

function saveBlob(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/** The answer's chart as a PNG data URL on a solid background (null if there is no chart). */
function chartPng(card) {
  const src = card.querySelector(".chart-box canvas");
  if (!src || !src.width) return null;
  const out = document.createElement("canvas");
  out.width = src.width;
  out.height = src.height;
  const ctx = out.getContext("2d");
  ctx.fillStyle = getComputedStyle(document.documentElement).getPropertyValue("--surface").trim() || "#fff";
  ctx.fillRect(0, 0, out.width, out.height);
  ctx.drawImage(src, 0, 0);
  return out.toDataURL("image/png");
}

async function exportAs(card, r, format) {
  try {
    if (format === "csv" && !r.question_id) {
      saveBlob(new Blob([toCsv(r.columns, r.rows)], { type: "text/csv" }), `${fileStem(r.question)}.csv`);
    } else if (format === "csv" || format === "xlsx") {
      const a = document.createElement("a"); // server re-runs the query: full result, not just shown rows
      a.href = exportUrl(r.question_id, format);
      a.click();
    } else if (format === "png") {
      // Panels are hidden until their tab is opened; draw the chart tab first if needed.
      const png = chartPng(card);
      if (!png) return toast("Open the Chart tab first");
      const res = await fetch(png);
      saveBlob(await res.blob(), `${fileStem(r.question)}.png`);
    } else if (format === "pdf") {
      toast("Preparing the PDF report…");
      saveBlob(await downloadReport(r.question_id, chartPng(card) || ""), `${fileStem(r.question)}.pdf`);
    }
  } catch (err) {
    toast(`Export failed: ${err.message}`, { error: true });
  }
}

/* ---------- Public ---------- */

/** Ask a question about the selected dataset and render the exchange in the thread. */
export async function askQuestion(text) {
  const question = text.trim();
  if (question.length < 3 || busy) return;
  busy = true;
  document.documentElement.dataset.busy = "1"; // pauses theme snapshots while the thread updates
  $("send-btn").disabled = true;
  $("welcome").hidden = true;
  remember(question);

  const questionEl = addQuestion(question);
  const card = addAssistantShell();
  const stop = renderWorking(card);
  scrollToBottom();

  try {
    const result = await ask(question, currentDataset().id, conversationId);
    conversationId = result.conversation_id;
    stop();
    renderAnswer(card, result);
  } catch (err) {
    stop();
    renderError(card, question, err);
  } finally {
    busy = false;
    delete document.documentElement.dataset.busy;
    $("send-btn").disabled = false;
    scrollToExchange(questionEl);
  }
}

/** Welcome screen for the selected dataset: title, description, starter questions. */
function renderWelcome() {
  const ds = currentDataset();
  const demo = ds.kind === "demo";
  $("welcome-title").textContent = demo ? "What would you like to know?" : `Ask about ${ds.name}`;
  $("welcome-text").textContent = demo
    ? "Ask about sales, customers, products or orders in the demo store (2024–2025), or about the data itself (\"What tables are there?\", \"How is revenue defined?\"). Or upload your own data below. Try one of these:"
    : `${ds.filename} · ${describeSize(ds)}. Try one of these, or ask anything, including what the columns mean:`;
  const tags = demo ? DEMO_TAGS : UPLOAD_TAGS;
  const pills = [
    ...ds.suggestions.map((q, i) => [tags[i % tags.length][0], q]),
    ...ABOUT_QUESTIONS[demo ? "demo" : "upload"].map((q) => ["database", q]), // chat about the data
  ];
  $("suggestions").innerHTML = pillRows(pills);
  $("composer-dataset").textContent = `Asking about: ${ds.name}`;
}

// Questions about the data itself (answered from the schema, no SQL) mixed into the pills.
const ABOUT_QUESTIONS = {
  demo: ["What is this data about?", "How is revenue defined?"],
  upload: ["What is this data about?", "What does each column mean?"],
};

/**
 * Quick questions as two rows of pills drifting in opposite directions (a seamless loop: each
 * row's pills are repeated once, and the track moves by exactly half its width). Hovering or
 * focusing a row pauses it; with "reduce motion" the rows are still and scroll sideways.
 */
function pillRows(items) {
  const pill = ([ic, q], hidden) =>
    `<button class="pill" data-q="${escapeHtml(q)}"${hidden ? ' tabindex="-1" aria-hidden="true"' : ""}>${icon(ic)}<span>${escapeHtml(q)}</span></button>`;
  const half = Math.ceil(items.length / 2);
  const rows = items.length > 4 ? [items.slice(0, half), items.slice(half)] : [items];
  return rows
    .map((row, r) => {
      const chars = row.reduce((n, [, q]) => n + q.length, 0);
      const seconds = Math.max(26, Math.round(chars * 0.32)); // same reading speed for any row length
      return `<div class="pill-row${r % 2 ? " reverse" : ""}" style="--pill-duration:${seconds}s">
        <div class="pill-track">${row.map((p) => pill(p, false)).join("")}${row.map((p) => pill(p, true)).join("")}</div>
      </div>`;
    })
    .join("");
}

/** Clear the conversation and show the welcome screen. */
export function newChat() {
  if (busy) return;
  $("thread").querySelector(".thread-inner")?.remove();
  conversationId = null;
  renderWelcome();
  $("welcome").hidden = false;
  $("thread").scrollTop = 0;
  $("question").value = "";
  $("question").focus({ preventScroll: true });
}

export function initAsk() {
  renderWelcome();
  trackThreadHeight();
  onDatasetChange(() => newChat()); // a conversation is about one dataset
  $("new-chat").addEventListener("click", () => {
    newChat();
    toast("Started a new chat");
  });
  $("suggestions").addEventListener("click", (e) => {
    const b = e.target.closest(".pill");
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
