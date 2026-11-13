/**
 * Charts from answered questions, kept for the Dashboard's "From your questions" section.
 *
 *   saveChart(datasetId, { id, question, spec })   newest first; asking the same question again
 *                                                   replaces its chart; at most MAX per dataset
 *   listCharts(datasetId) -> [{ id, question, spec, at }]
 *   removeChart(datasetId, id) / clearCharts(datasetId)
 *
 * Stored in this browser (localStorage), separately for each account and for guests, so two
 * people sharing a computer don't see each other's charts. Storage can be unavailable (private
 * windows, blocked site data): every call then quietly does nothing / returns [].
 */

import { currentUser } from "./auth.js";

const MAX = 12;
const MAX_POINTS = 60; // enough for 5 years of months; keeps storage small
const key = () => `ayd.charts.v1:${currentUser().email || "guest"}`;

function readAll() {
  try {
    return JSON.parse(localStorage.getItem(key()) || "{}");
  } catch {
    return {};
  }
}

function writeAll(all) {
  try {
    localStorage.setItem(key(), JSON.stringify(all));
  } catch {
    /* storage full or blocked: the dashboard just won't remember this chart */
  }
}

export function saveChart(datasetId, { id, question, spec }) {
  const all = readAll();
  const norm = question.trim().toLowerCase();
  const kept = (all[datasetId] || []).filter((c) => c.question.trim().toLowerCase() !== norm);
  const small = { ...spec, labels: spec.labels.slice(0, MAX_POINTS), values: spec.values.slice(0, MAX_POINTS) };
  all[datasetId] = [{ id, question, spec: small, at: Date.now() }, ...kept].slice(0, MAX);
  writeAll(all);
}

export const listCharts = (datasetId) => readAll()[datasetId] || [];

export function removeChart(datasetId, id) {
  const all = readAll();
  all[datasetId] = (all[datasetId] || []).filter((c) => c.id !== id);
  writeAll(all);
}

export function clearCharts(datasetId) {
  const all = readAll();
  delete all[datasetId];
  writeAll(all);
}
