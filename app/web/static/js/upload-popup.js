/**
 * The upload popup: one dialog that follows an upload from start to finish.
 *
 *   const popup = createUploadPopup({ onPickAgain });
 *   popup.start(files, { compressing })   opens with the file names and sizes
 *   popup.uploading(file)                 switches to the byte progress for the file being sent
 *   popup.progress(fraction)              0..1 from uploadDataset (the last 5% is the server)
 *   popup.reading()                       the server is turning the file into tables
 *   popup.done(dataset)                   check mark, table chips, "Start asking"
 *   popup.fail(message)                   cross, message, "Try again"
 *
 * The popup can be hidden while it works (the upload carries on); if it finishes hidden, the
 * caller gets `false` back from done()/fail() and shows a toast instead.
 * States are a data-state attribute on the dialog; all motion lives in components.css.
 */

import { describeSize } from "./datasets.js";
import { escapeHtml, plainNum } from "./format.js";
import { icon } from "./icons.js";

const $ = (id) => document.getElementById(id);
const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

export function formatBytes(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(0)} KB`;
  return `${(n / (1024 * 1024)).toFixed(n < 10 * 1024 * 1024 ? 1 : 0)} MB`;
}

function chips(items) {
  // items: [{icon, label, strong}] -> staggered chips; long lists end with "+N more".
  const shown = items.length > 5 ? items.slice(0, 4) : items;
  const extra = items.length - shown.length;
  const html = shown.map(
    (it, i) =>
      `<li style="animation-delay:${0.08 + i * 0.06}s">${icon(it.icon)}<span>${escapeHtml(it.label)}</span>${
        it.strong ? `<b>${escapeHtml(it.strong)}</b>` : ""
      }</li>`,
  );
  if (extra > 0) html.push(`<li style="animation-delay:${0.08 + shown.length * 0.06}s"><span>+${extra} more</span></li>`);
  return html.join("");
}

export function createUploadPopup({ onPickAgain }) {
  const dialog = $("upload-dialog");
  let hidden = false;
  let total = 0;
  let startedAt = 0;
  let timer = 0;

  const set = (id, text) => ($(id).textContent = text);
  const setState = (state) => {
    dialog.dataset.state = state;
    const order = ["compress", "upload", "read"];
    const at = order.indexOf(state);
    dialog.querySelectorAll(".up-steps li").forEach((li) => {
      const i = order.indexOf(li.dataset.step);
      li.classList.toggle("is-active", i === at);
      li.classList.toggle("is-done", at > i || state === "done");
    });
  };
  const stopTimer = () => window.clearInterval(timer);

  function show() {
    hidden = false;
    if (!dialog.open) dialog.showModal();
  }

  function hide() {
    if (!dialog.open) return;
    hidden = !["done", "error"].includes(dialog.dataset.state);
    if (reducedMotion()) return dialog.close();
    dialog.classList.add("is-closing");
    window.setTimeout(() => {
      dialog.classList.remove("is-closing");
      dialog.close();
    }, 190);
  }

  $("up-close").addEventListener("click", hide);
  dialog.addEventListener("cancel", (e) => {
    e.preventDefault(); // Esc: animate out instead of an abrupt close
    hide();
  });
  dialog.addEventListener("click", (e) => e.target === dialog && hide()); // click on the backdrop
  $("up-secondary").addEventListener("click", () => {
    hide();
    if (dialog.dataset.state === "done") window.setTimeout(onPickAgain, 220); // "Upload another"
  });
  $("up-primary").addEventListener("click", () => {
    hide();
    if (dialog.dataset.state === "error") window.setTimeout(onPickAgain, 220); // "Try again"
  });

  return {
    start(files, { compressing = false } = {}) {
      stopTimer();
      const size = files.reduce((n, f) => n + f.size, 0);
      $("up-steps").querySelector('[data-step="compress"]').hidden = !compressing;
      $("up-error").hidden = true;
      $("up-actions").hidden = true;
      $("up-fill").style.width = "0%";
      set("up-title", compressing ? "Packing your files" : "Uploading");
      set("up-sub", files.length > 1 ? `${files.length} files · ${formatBytes(size)}` : `${files[0].name} · ${formatBytes(size)}`);
      $("up-files").innerHTML = files.length > 1 ? chips(files.map((f) => ({ icon: "file", label: f.name }))) : "";
      set("up-pct", compressing ? "Compressing" : "0%");
      set("up-detail", compressing ? "so they upload as one dataset" : "");
      setState(compressing ? "compress" : "upload");
      show();
    },

    uploading(file) {
      total = file.size;
      startedAt = performance.now();
      if (dialog.dataset.state === "compress") {
        set("up-title", "Uploading");
        set("up-sub", `Compressed to ${formatBytes(file.size)}`);
      }
      setState("upload");
    },

    progress(fraction) {
      if (fraction >= 0.95) return this.reading();
      const sent = Math.min(1, fraction / 0.95) * total;
      const secs = (performance.now() - startedAt) / 1000;
      $("up-fill").style.width = `${Math.round(fraction * 100)}%`;
      set("up-pct", `${Math.round(fraction * 100)}%`);
      const speed = secs > 0.5 ? ` · ${formatBytes(sent / secs)}/s` : "";
      set("up-detail", `${formatBytes(sent)} of ${formatBytes(total)}${speed}`);
    },

    reading() {
      if (dialog.dataset.state === "read") return;
      setState("read");
      set("up-title", "Reading your tables");
      set("up-pct", "Almost there");
      const started = performance.now();
      const tick = () => {
        const s = Math.round((performance.now() - started) / 1000);
        set("up-detail", s < 3 ? "Detecting columns and types" : `Building tables · ${s}s`);
      };
      tick();
      timer = window.setInterval(tick, 1000);
    },

    done(dataset) {
      stopTimer();
      setState("done");
      set("up-title", "Ready to explore");
      set("up-sub", `${dataset.name} · ${describeSize(dataset)}`);
      $("up-files").innerHTML = chips(
        dataset.tables.map((t) => ({ icon: "table", label: t.name, strong: plainNum(t.rows) })),
      );
      set("up-secondary", "Upload another");
      set("up-primary", "Start asking");
      $("up-actions").hidden = false;
      if (hidden) return false;
      $("up-primary").focus();
      return true;
    },

    fail(message) {
      stopTimer();
      setState("error");
      set("up-title", "Upload failed");
      $("up-error").textContent = message.replace(/^./, (c) => c.toUpperCase());
      $("up-error").hidden = false;
      set("up-secondary", "Close");
      set("up-primary", "Try again");
      $("up-actions").hidden = false;
      return !hidden;
    },
  };
}
