/**
 * Metrics view: how well the app answers, how fast, at what cost, and how it is engineered.
 *
 *   Evaluation    latest offline eval run (metrics/eval.json): accuracy overall and by category
 *   Live usage    from the question log: answer rate, latency percentiles, cost, satisfaction,
 *                 follow-ups, uploads, daily volume, latency histogram, time per agent step
 *   Engineering   tests and coverage (metrics/quality.json), API load test (metrics/loadtest.json)
 *   Feedback      admins only: answers rated "not helpful", with the SQL, to review
 *
 * Exports: loadMetrics()  (called each time the view opens; data is fetched fresh)
 */

import { getFeedbackList, getMetrics } from "./api.js";
import { currentUser } from "./auth.js";
import { drawChart } from "./charts.js";
import { escapeHtml, highlightSql, num } from "./format.js";
import { icon } from "./icons.js";

const $ = (id) => document.getElementById(id);

const pct = (v, digits = 1) => (v == null ? "–" : `${(v * 100).toFixed(digits)}%`);
const secs = (ms) => (ms == null ? "–" : `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)}s`);
const usd = (v) => (v == null ? "–" : v < 0.01 ? `$${v.toFixed(4)}` : `$${v.toFixed(2)}`);
const count = (v) => (v == null ? "–" : num(v));

function card(ic, labelText, value, sub = "") {
  return `<div class="card kpi">
    <div class="kpi-top"><span class="kpi-icon">${icon(ic)}</span></div>
    <div><div class="kpi-label">${labelText}</div><div class="kpi-value">${value}</div></div>
    ${sub ? `<div class="kpi-sub">${sub}</div>` : ""}
  </div>`;
}

function section(title, note, body) {
  return `<section class="metrics-section">
    <div class="metrics-head"><h2>${title}</h2>${note ? `<span class="muted">${note}</span>` : ""}</div>
    ${body}</section>`;
}

function missing(text, command) {
  return `<div class="card data-intro"><span data-icon="info">${icon("info")}</span>
    <div>${text}${command ? ` Run <code>${escapeHtml(command)}</code> and commit <code>metrics/</code>.` : ""}</div></div>`;
}

/* ---------- Sections ---------- */

function evalSection(e) {
  if (!e) return section("Evaluation", "", missing("No evaluation report yet.", "python -m evals.run_eval"));
  const s = e.summary;
  const cats = Object.entries(s.by_category || {});
  const table = cats.length
    ? `<div class="card table-card"><div class="table-wrap"><table>
        <thead><tr><th>Category</th><th class="num">Questions</th><th class="num">Passed</th><th class="num">Accuracy</th></tr></thead>
        <tbody>${cats.map(([k, v]) => `<tr><td>${escapeHtml(k.replace(/_/g, " "))}</td><td class="num">${v.questions}</td><td class="num">${v.passed}</td><td class="num">${pct(v.accuracy)}</td></tr>`).join("")}</tbody>
      </table></div></div>`
    : "";
  return section(
    "Evaluation",
    `${escapeHtml(s.sql_model)} · ${s.questions} questions with reference SQL · ${escapeHtml((s.run_at || "").slice(0, 10))}`,
    `<div class="kpi-grid metrics-grid">
      ${card("check", "Execution accuracy", pct(s.execution_accuracy), `${s.passed} of ${s.questions} results match the reference`)}
      ${card("link", "Follow-up accuracy", pct(s.by_category?.follow_up?.accuracy), "Multi-turn questions")}
      ${card("ban", "Declines correctly", pct(s.by_category?.unanswerable?.accuracy), "Says no when the data can't answer")}
      ${card("retry", "Fixed own errors", count(s.self_corrected), `${pct(s.first_try_accuracy)} right on the first try`)}
      ${card("clock", "Latency p50 / p95", `${secs(s.median_latency_ms)} / ${secs(s.p95_latency_ms)}`, "Question to answer, end to end")}
      ${card("rupee", "Cost per question", usd(s.avg_cost_usd), `${num(s.avg_input_tokens)} in / ${num(s.avg_output_tokens)} out tokens`)}
    </div>${table}`,
  );
}

function liveSection(m) {
  const o = m.outcomes;
  const empty = !m.questions;
  return section(
    "Live usage",
    `All questions asked on this deployment · updated ${escapeHtml((m.generated_at || "").replace("T", " ").slice(0, 16))} UTC`,
    empty
      ? missing("No questions asked yet. Ask something and come back.")
      : `<div class="kpi-grid metrics-grid">
      ${card("chat", "Questions", count(m.questions), `${count(m.conversations)} conversations · ${count(m.accounts)} accounts`)}
      ${card("check", "Answer rate", pct(o.answer_rate), `${pct(o.first_try_rate)} first try · ${pct(o.failure_rate)} failed`)}
      ${card("clock", "Latency p50 / p95", `${secs(m.latency_ms.p50)} / ${secs(m.latency_ms.p95)}`, `p99 ${secs(m.latency_ms.p99)}`)}
      ${card("rupee", "Avg cost / question", usd(m.cost_usd.avg_per_question), `${usd(m.cost_usd.per_1000_questions)} per 1,000 · ${usd(m.cost_usd.total)} total`)}
      ${card("thumbUp", "Satisfaction", pct(m.feedback.satisfaction, 0), `${m.feedback.helpful} 👍 · ${m.feedback.not_helpful} 👎 (${pct(m.feedback.rating_rate, 0)} rated)`)}
      ${card("link", "Follow-ups", pct(m.follow_ups.share, 0), `of questions · ${pct(m.follow_ups.answer_rate, 0)} answered`)}
      ${card("upload", "Uploads", count(m.uploads.uploads), `${count(m.uploads.rows_ingested)} rows · p50 ${secs(m.uploads.processing_ms.p50)} to process`)}
      ${card("cpu", "Tokens / question", `${count(Math.round(m.tokens.avg_input || 0))} / ${count(Math.round(m.tokens.avg_output || 0))}`, "input / output")}
      ${card("retry", "Self-corrected", count(o.self_corrected), `${pct(o.self_correction_share_of_answers)} of answers needed a retry`)}
    </div>
    <div class="chart-grid">
      <div class="card chart-card wide"><div class="card-head"><h3>Questions per day</h3><span class="muted">last 30 days</span></div>
        <div class="chart-box"><canvas id="m-daily"></canvas></div></div>
      <div class="card chart-card"><div class="card-head"><h3>Answer time</h3><span class="muted">number of questions</span></div>
        <div class="chart-box"><canvas id="m-latency"></canvas></div></div>
      <div class="card chart-card"><div class="card-head"><h3>Where the time goes</h3><span class="muted">average per step</span></div>
        <div class="chart-box"><canvas id="m-steps"></canvas></div></div>
    </div>`,
  );
}

function engineeringSection(quality, load) {
  const q = quality
    ? [
        card("check", "Automated tests", count(quality.tests_passed), `${quality.tests_failed ? `${quality.tests_failed} failing` : "all passing"} · ${secs(quality.duration_ms)} run`),
        card("code", "Code coverage", pct(quality.coverage, 0), `${count(quality.statements)} statements`),
      ]
    : [];
  const l = load
    ? [
        card("gauge", "API p95 under load", secs(load.overall.p95_ms), `${load.concurrency} concurrent · ${count(load.requests)} requests`),
        card("trend", "Throughput", `${num(Math.round(load.overall.rps))} req/s`, `${pct(load.overall.error_rate)} errors`),
      ]
    : [];
  if (!q.length && !l.length) return section("Engineering", "", missing("No quality or load-test report yet.", "python -m scripts.quality_report"));
  return section("Engineering", "tests, coverage and load test", `<div class="kpi-grid metrics-grid">${[...q, ...l].join("")}</div>`);
}

async function feedbackSection() {
  if (!currentUser().is_admin) return "";
  let rows = [];
  try {
    rows = await getFeedbackList(-1);
  } catch {
    return "";
  }
  const body = rows.length
    ? rows
        .map((r) => `<div class="card fb-item">
          <div class="fb-q">${escapeHtml(r.standalone_question || r.question)}</div>
          ${r.feedback_note ? `<div class="fb-note">“${escapeHtml(r.feedback_note)}”</div>` : ""}
          <div class="muted fb-meta">${escapeHtml(r.created_at.slice(0, 16))} · ${escapeHtml(r.name ? `${r.name}${r.company ? `, ${r.company}` : ""}` : "Guest")} · ${escapeHtml(r.dataset_kind)} · ${escapeHtml(r.status)}</div>
          ${r.sql ? `<pre class="fb-sql"><code>${highlightSql(escapeHtml(r.sql))}</code></pre>` : ""}
        </div>`)
        .join("")
    : missing("No answers rated “not helpful”.");
  return section(
    "Answers to review",
    `<a class="link-btn" href="/api/metrics/feedback.xlsx">Download all feedback (Excel)</a> · <a class="link-btn" href="/api/metrics/eval-candidates" download="eval-candidates.jsonl">Download as eval candidates</a>`,
    `<div class="fb-list">${body}</div>`,
  );
}

function drawLiveCharts(m) {
  if (!m.questions) return;
  drawChart($("m-daily"), {
    type: "bar",
    labels: m.daily.map((d) => d.date.slice(5)),
    values: m.daily.map((d) => d.questions),
    label: "Questions",
  });
  const b = m.latency_ms.histogram.buckets_s;
  drawChart($("m-latency"), {
    type: "bar",
    labels: [...b.map((s, i) => (i === 0 ? `≤${s}s` : `${b[i - 1]}–${s}s`)), `>${b.at(-1)}s`],
    values: m.latency_ms.histogram.counts,
    label: "Questions",
  });
  const s = m.latency_ms.avg_by_step;
  drawChart($("m-steps"), {
    type: "bar",
    horizontal: true,
    multicolor: true,
    labels: ["Write SQL", "Safety check", "Run query", "Write answer"],
    values: [s.write_sql, s.safety_check, s.run_query, s.write_answer].map((v) => Math.round(v || 0)),
    label: "Milliseconds",
  });
}

/** Render the metrics view (fetches fresh numbers every time it opens). */
export async function loadMetrics() {
  const root = $("metrics-root");
  root.innerHTML = `<div class="kpi-grid">${'<div class="card kpi skeleton"></div>'.repeat(3)}</div>`;
  let data;
  try {
    data = await getMetrics();
  } catch (err) {
    root.innerHTML = missing(`Couldn't load metrics: ${escapeHtml(err.message)}`);
    return;
  }
  root.innerHTML =
    evalSection(data.eval) + liveSection(data.live) + engineeringSection(data.quality, data.loadtest) + (await feedbackSection());
  drawLiveCharts(data.live);
}
