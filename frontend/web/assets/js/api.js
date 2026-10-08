// Cliente de la API. Todas las peticiones que modifican datos llevan la cabecera
// X-JobTracker (protección CSRF: ver backend/app/main.py).

export class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function request(method, path, { json, form, params } = {}) {
  const url = new URL(path, location.origin);
  for (const [k, v] of Object.entries(params || {})) if (v !== undefined && v !== null && v !== "") url.searchParams.set(k, v);
  const headers = { "X-JobTracker": "1" };
  let body;
  if (json !== undefined) { headers["Content-Type"] = "application/json"; body = JSON.stringify(json); }
  if (form) body = form;
  let res;
  try {
    res = await fetch(url, { method, headers, body });
  } catch {
    throw new ApiError("No hay conexión con el motor de la app. ¿Se ha cerrado?", 0);
  }
  if (res.status === 204) return null;
  const data = res.headers.get("content-type")?.includes("json") ? await res.json() : await res.text();
  if (!res.ok) {
    let msg = typeof data === "object" ? data.detail : data;
    if (Array.isArray(msg)) msg = msg.map((d) => d.msg).join(" · ");
    throw new ApiError(msg || `Error ${res.status}`, res.status);
  }
  return data;
}

export const api = {
  get: (p, params) => request("GET", p, { params }),
  post: (p, json, params) => request("POST", p, { json, params }),
  put: (p, json) => request("PUT", p, { json }),
  patch: (p, json) => request("PATCH", p, { json }),
  del: (p) => request("DELETE", p),
  upload: (p, file) => { const f = new FormData(); f.append("file", file); return request("POST", p, { form: f }); },
};
