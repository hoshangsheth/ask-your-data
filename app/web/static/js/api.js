/**
 * HTTP client for the backend. One function per endpoint; errors become ApiError with the
 * server's message and status, so views can show friendly text.
 *
 * Endpoints (see app/api/routes/):
 *   getHealth()   GET  /api/health
 *   getKpis()     GET  /api/kpis
 *   getSchema()   GET  /api/schema
 *   ask(q)        POST /api/ask
 */

export class ApiError extends Error {
  constructor(message, status) {
    super(message);
    this.status = status;
  }
}

async function request(path, options = {}) {
  let res;
  try {
    res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  } catch {
    throw new ApiError("Can't reach the server. Is it running?", 0);
  }
  let body = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error page */
  }
  if (!res.ok) {
    const detail = body?.detail;
    const msg = typeof detail === "string" ? detail : Array.isArray(detail) ? detail[0]?.msg : `HTTP ${res.status}`;
    throw new ApiError(msg || `HTTP ${res.status}`, res.status);
  }
  return body;
}

export const getHealth = () => request("/api/health");
export const getKpis = () => request("/api/kpis");
export const getSchema = () => request("/api/schema");
export const ask = (question) => request("/api/ask", { method: "POST", body: JSON.stringify({ question }) });
