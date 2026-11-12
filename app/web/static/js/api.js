/**
 * HTTP client for the backend. One function per endpoint; errors become ApiError with the
 * server's message and status, so views can show friendly text.
 *
 * Endpoints (see app/api/routes/):
 *   getHealth()                   GET    /api/health
 *   getKpis()                     GET    /api/kpis
 *   getSchema(datasetId)          GET    /api/schema?dataset=
 *   ask(question, datasetId)      POST   /api/ask
 *   listDatasets()                GET    /api/datasets
 *   getFormats()                  GET    /api/formats
 *   uploadDataset(file, onProgress)  POST /api/uploads, PUT .../parts/{n}, POST .../complete
 *                                 (file sent in parts, with upload progress)
 *   deleteDataset(id)             DELETE /api/datasets/{id}
 */

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

function errorMessage(body, status) {
  const detail = body?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail[0]?.msg ?? `HTTP ${status}`;
  return `HTTP ${status}`;
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch {
    throw new ApiError("Can't reach the server. Is it running?", 0);
  }
  if (res.status === 204) return null;
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) throw new ApiError(errorMessage(body, res.status), res.status);
  return body;
}

export const getHealth = () => request("/api/health");
export const getKpis = () => request("/api/kpis");
export const getSchema = (datasetId) => request(`/api/schema?dataset=${encodeURIComponent(datasetId)}`);
export const ask = (question, datasetId) =>
  request("/api/ask", { method: "POST", body: JSON.stringify({ question, dataset_id: datasetId }) });
export const listDatasets = () => request("/api/datasets");
export const getFormats = () => request("/api/formats");
export const deleteDataset = (id) => request(`/api/datasets/${encodeURIComponent(id)}`, { method: "DELETE" });

/** PUT one part with XMLHttpRequest (not fetch) so upload progress can be reported. */
function putPart(url, blob, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("PUT", url);
    xhr.responseType = "json";
    xhr.setRequestHeader("Content-Type", "application/octet-stream");
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve();
      else reject(new ApiError(errorMessage(xhr.response, xhr.status), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Upload failed: can't reach the server.", 0));
    xhr.send(blob);
  });
}

/**
 * Upload a file in parts of a few MB (hosting caps one request at 4.5 MB), then ask the server
 * to build the dataset. onProgress(fraction 0..1) follows the bytes sent; the last 5% is the
 * server reading the file. Resolves with the dataset summary.
 */
export async function uploadDataset(file, onProgress = () => {}) {
  const start = await request("/api/uploads", {
    method: "POST",
    body: JSON.stringify({ filename: file.name, size: file.size }),
  });
  const base = `/api/uploads/${encodeURIComponent(start.upload_id)}`;
  let sent = 0;
  for (let i = 0; i < start.parts; i++) {
    const part = file.slice(i * start.part_bytes, (i + 1) * start.part_bytes);
    await putPart(`${base}/parts/${i}`, part, (loaded) => onProgress((0.95 * (sent + loaded)) / file.size));
    sent += part.size;
  }
  onProgress(0.95);
  const dataset = await request(`${base}/complete`, {
    method: "POST",
    body: JSON.stringify({ filename: file.name, parts: start.parts }),
  });
  onProgress(1);
  return dataset;
}
