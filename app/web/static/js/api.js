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
 *   uploadDataset(file, onProgress)  POST /api/datasets   (multipart, with upload progress)
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

/**
 * Upload a file. XMLHttpRequest (not fetch) so we can report upload progress.
 * onProgress(fraction 0..1) is called while bytes are sent; resolves with the dataset summary.
 */
export function uploadDataset(file, onProgress = () => {}) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/datasets");
    xhr.responseType = "json";
    xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total);
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) resolve(xhr.response);
      else reject(new ApiError(errorMessage(xhr.response, xhr.status), xhr.status));
    };
    xhr.onerror = () => reject(new ApiError("Upload failed: can't reach the server.", 0));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}
