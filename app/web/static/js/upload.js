/**
 * Uploading data files: file picker, drag-and-drop anywhere on the page, and progress.
 *
 * Entry points: the sidebar "Upload" button, the paperclip in the composer, the dropzone on the
 * welcome screen, or dropping files anywhere. Several files at once (for example the 9 CSVs of a
 * relational dataset) are zipped in the browser and uploaded as one dataset with one table per
 * file; a .zip file is uploaded as it is. While uploading, a progress row appears in the
 * "Your data" list ("Uploading 45%" -> "Reading tables…"). On success the new dataset is
 * selected and a new chat starts on it.
 *
 * Exports: initUpload()
 */

import { getFormats, uploadDataset } from "./api.js";
import { currentUser, requireSignIn } from "./auth.js";
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
    status: (text) => (li.querySelector("[data-status]").textContent = text),
    remove: () => li.remove(),
  };
}

const FFLATE_URL = "https://cdn.jsdelivr.net/npm/fflate@0.8.2/esm/browser.js";
const extOf = (name) => `.${name.split(".").pop().toLowerCase()}`;
const stemOf = (name) => name.replace(/\.[^.]+$/, "");

/** Several files -> one .zip (compressed in a background worker), so they upload as one dataset. */
async function zipFiles(files) {
  const { zip } = await import(FFLATE_URL);
  const entries = {};
  for (const f of files) entries[f.name] = [new Uint8Array(await f.arrayBuffer()), { level: 6 }];
  const bytes = await new Promise((resolve, reject) => zip(entries, (err, out) => (err ? reject(err) : resolve(out))));
  const name = `${stemOf(files[0].name)} and ${files.length - 1} more.zip`;
  return new File([bytes], name, { type: "application/zip" });
}

async function upload(fileList) {
  const files = [...(fileList ?? [])];
  if (!files.length || uploading) return;
  const unsupported = files.filter((f) => !formats.extensions.includes(extOf(f.name)));
  if (unsupported.length) {
    toast(`"${unsupported[0].name}" isn't a supported file. Try CSV, Excel, JSON, Parquet, PDF, Word or a .zip of them.`, {
      error: true,
    });
    return;
  }
  if (files.length > 1 && files.some((f) => extOf(f.name) === ".zip")) {
    toast("Upload a .zip on its own, or select the files inside it instead.", { error: true });
    return;
  }
  // Drag and drop skips the picker, so check here too.
  if (!(await requireSignIn("Sign in to upload your own data. Your files stay private to your account."))) return;
  uploading = true;
  const label = files.length > 1 ? `${files.length} files` : files[0].name;
  const row = progressRow(label);
  try {
    let file = files[0];
    if (files.length > 1) {
      row.status("Compressing…");
      file = await zipFiles(files);
    }
    if (file.size > formats.max_upload_mb * 1024 * 1024) {
      throw new Error(
        files.length > 1
          ? `even compressed, these files are larger than ${formats.max_upload_mb} MB`
          : `the file is larger than ${formats.max_upload_mb} MB (zipping it first usually helps)`,
      );
    }
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
    void upload(e.dataTransfer.files);
  });
}

export async function initUpload() {
  const input = $("file-input");
  const SIGN_IN_REASON = "Sign in to upload your own data. Your files stay private to your account.";
  // Guests sign in first; the file picker opens right after (or straight away when signed in).
  const pick = async () => {
    if (currentUser().signed_in || (await requireSignIn(SIGN_IN_REASON))) input.click();
  };
  $("upload-btn").addEventListener("click", pick);
  $("attach-btn").addEventListener("click", pick);
  $("dropzone").addEventListener("click", pick);
  input.addEventListener("change", () => {
    void upload(input.files);
    input.value = ""; // allow re-uploading the same file
  });
  initDragAndDrop();

  try {
    formats = await getFormats();
  } catch {
    /* keep defaults */
  }
  input.accept = formats.extensions.join(",");
  const summary = `CSV, Excel, JSON, Parquet, PDF, Word, a .zip or several files at once · up to ${formats.max_upload_mb} MB`;
  $("dz-sub").textContent = `Drop files here or click to browse · ${summary}`;
  $("drop-formats").textContent = summary;
}
