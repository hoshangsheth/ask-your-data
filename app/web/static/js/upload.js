/**
 * Uploading data files: file picker, drag-and-drop anywhere on the page, and progress.
 *
 * Entry points: the sidebar "Upload" button, the paperclip in the composer, the dropzone on the
 * welcome screen, or dropping a file anywhere. While uploading, a progress row appears in the
 * "Your data" list ("Uploading 45%" -> "Reading tables…"). On success the new dataset is
 * selected and a new chat starts on it.
 *
 * Exports: initUpload()
 */

import { getFormats, uploadDataset } from "./api.js";
import { requireSignIn } from "./auth.js";
import { addDataset, describeSize } from "./datasets.js";
import { escapeHtml } from "./format.js";
import { icon } from "./icons.js";
import { toast } from "./toast.js";

const $ = (id) => document.getElementById(id);
let formats = { extensions: [".csv", ".xlsx", ".json"], max_upload_mb: 50 };
let uploading = false;

/** Progress row shown at the top of the dataset list while a file uploads. */
function progressRow(name) {
  const li = document.createElement("li");
  li.className = "ds-item is-uploading";
  li.innerHTML = `<div class="ds-select"><span class="ds-icon">${icon("upload")}</span>
    <span class="ds-text"><span class="ds-name">${escapeHtml(name)}</span>
    <span class="ds-meta" data-status>Uploading 0%</span>
    <span class="ds-progress"><span data-bar></span></span></span></div>`;
  const list = $("dataset-list");
  list.insertBefore(li, list.children[1] ?? null);
  return {
    progress(fraction) {
      const pct = Math.round(fraction * 100);
      li.querySelector("[data-bar]").style.width = `${pct}%`;
      li.querySelector("[data-status]").textContent = pct < 100 ? `Uploading ${pct}%` : "Reading tables…";
    },
    remove: () => li.remove(),
  };
}

async function upload(file) {
  if (!file || uploading) return;
  const ext = `.${file.name.split(".").pop().toLowerCase()}`;
  if (!formats.extensions.includes(ext)) {
    toast(`"${ext}" files aren't supported. Try CSV, Excel, JSON, Parquet, PDF or Word.`, { error: true });
    return;
  }
  if (file.size > formats.max_upload_mb * 1024 * 1024) {
    toast(`That file is larger than ${formats.max_upload_mb} MB.`, { error: true });
    return;
  }
  if (!(await requireSignIn("Sign in to upload your own data. Your files stay private to your account."))) return;
  uploading = true;
  const row = progressRow(file.name);
  try {
    const dataset = await uploadDataset(file, (f) => row.progress(f));
    row.remove();
    addDataset(dataset); // selects it -> views switch and a new chat starts
    toast(`"${dataset.name}" is ready: ${describeSize(dataset)}`);
  } catch (err) {
    row.remove();
    toast(`Upload failed: ${err.message}`, { error: true });
  } finally {
    uploading = false;
  }
}

/** Show the drop overlay while files are dragged over the window. */
function initDragAndDrop() {
  const overlay = $("drop-overlay");
  let depth = 0;
  const hasFiles = (e) => [...(e.dataTransfer?.types ?? [])].includes("Files");
  window.addEventListener("dragenter", (e) => {
    if (!hasFiles(e)) return;
    depth += 1;
    overlay.hidden = false;
  });
  window.addEventListener("dragleave", () => {
    depth = Math.max(0, depth - 1);
    if (depth === 0) overlay.hidden = true;
  });
  window.addEventListener("dragover", (e) => hasFiles(e) && e.preventDefault());
  window.addEventListener("drop", (e) => {
    if (!hasFiles(e)) return;
    e.preventDefault();
    depth = 0;
    overlay.hidden = true;
    void upload(e.dataTransfer.files[0]);
  });
}

export async function initUpload() {
  const input = $("file-input");
  const pick = () => input.click();
  $("upload-btn").addEventListener("click", pick);
  $("attach-btn").addEventListener("click", pick);
  $("dropzone").addEventListener("click", pick);
  input.addEventListener("change", () => {
    void upload(input.files[0]);
    input.value = ""; // allow re-uploading the same file
  });
  initDragAndDrop();

  try {
    formats = await getFormats();
  } catch {
    /* keep defaults */
  }
  input.accept = formats.extensions.join(",");
  const summary = `CSV, Excel, JSON, Parquet, PDF, Word and more · up to ${formats.max_upload_mb} MB`;
  $("dz-sub").textContent = `Drop a file here or click to browse · ${summary}`;
  $("drop-formats").textContent = summary;
}
